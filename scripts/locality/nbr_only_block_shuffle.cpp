// Offline NBR-only block-shuffle layout builder.
//
// This utility reuses the graph-edge block placement objective from DiskANN's
// block-shuffle implementation, but computes page capacity from fixed-width
// neighbor-list records only. It writes original logical neighbor IDs, a
// new-to-old / old-to-new mapping, and a 4 KiB page-aligned NBR file. It does
// not alter DiskANN's search path or read full vectors.

#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

namespace
{
constexpr uint32_t PAGE_SIZE = 4096;
constexpr uint32_t HEADER_PAGES = 1;
constexpr uint32_t MAP_DIM = 1;

struct MemIndexHeader
{
    uint64_t file_size;
    uint32_t width;
    uint32_t medoid;
    uint64_t frozen_count;
};

uint32_t read_base_count(const std::string &path)
{
    std::ifstream in(path, std::ios::binary);
    if (!in)
        throw std::runtime_error("Cannot open base file: " + path);
    uint32_t npts = 0, dims = 0;
    in.read(reinterpret_cast<char *>(&npts), sizeof(npts));
    in.read(reinterpret_cast<char *>(&dims), sizeof(dims));
    if (!in || npts == 0 || dims == 0)
        throw std::runtime_error("Invalid base-file header: " + path);
    return npts;
}

std::vector<std::vector<uint32_t>> read_graph(const std::string &path, uint32_t expected_npts,
                                               uint32_t &width, uint32_t &medoid,
                                               uint64_t &frozen_count)
{
    std::ifstream in(path, std::ios::binary);
    if (!in)
        throw std::runtime_error("Cannot open Vamana index: " + path);

    MemIndexHeader header{};
    in.read(reinterpret_cast<char *>(&header.file_size), sizeof(header.file_size));
    in.read(reinterpret_cast<char *>(&header.width), sizeof(header.width));
    in.read(reinterpret_cast<char *>(&header.medoid), sizeof(header.medoid));
    in.read(reinterpret_cast<char *>(&header.frozen_count), sizeof(header.frozen_count));
    if (!in || header.width == 0 || header.file_size < sizeof(header))
        throw std::runtime_error("Invalid Vamana index header: " + path);

    in.seekg(0, std::ios::end);
    const auto actual_size = static_cast<uint64_t>(in.tellg());
    if (actual_size != header.file_size)
        throw std::runtime_error("Vamana index file size does not match its header");
    in.seekg(sizeof(header), std::ios::beg);

    std::vector<std::vector<uint32_t>> graph(expected_npts);
    for (uint32_t u = 0; u < expected_npts; ++u)
    {
        uint32_t degree = 0;
        in.read(reinterpret_cast<char *>(&degree), sizeof(degree));
        if (!in || degree > header.width)
            throw std::runtime_error("Invalid degree at node " + std::to_string(u));
        graph[u].resize(degree);
        if (degree)
            in.read(reinterpret_cast<char *>(graph[u].data()), degree * sizeof(uint32_t));
        if (!in)
            throw std::runtime_error("Truncated neighbor list at node " + std::to_string(u));
        for (const auto v : graph[u])
            if (v >= expected_npts)
                throw std::runtime_error("Neighbor ID out of range at node " + std::to_string(u));
        if ((u + 1) % std::max<uint32_t>(1, expected_npts / 10) == 0 || u + 1 == expected_npts)
            std::cout << "Loaded graph node " << (u + 1) << "/" << expected_npts << std::endl;
    }

    width = header.width;
    medoid = header.medoid;
    frozen_count = header.frozen_count;
    return graph;
}

double edge_locality(const std::vector<std::vector<uint32_t>> &graph,
                     const std::vector<uint32_t> &node_to_page)
{
    uint64_t edges = 0, local_edges = 0;
    for (uint32_t u = 0; u < graph.size(); ++u)
        for (const uint32_t v : graph[u])
        {
            ++edges;
            local_edges += node_to_page[u] == node_to_page[v];
        }
    return edges ? static_cast<double>(local_edges) / edges : 0.0;
}

std::vector<uint32_t> compute_order(const std::vector<std::vector<uint32_t>> &graph,
                                    uint32_t capacity, uint32_t max_iterations,
                                    double gain_threshold)
{
    const uint32_t npts = static_cast<uint32_t>(graph.size());
    std::vector<uint32_t> new_to_old(npts);
    std::iota(new_to_old.begin(), new_to_old.end(), 0);
    if (!npts || !capacity || !max_iterations)
        return new_to_old;

    const uint32_t num_blocks = (npts + capacity - 1) / capacity;
    std::vector<std::vector<uint32_t>> blocks(num_blocks);
    std::vector<uint32_t> node_to_block(npts), next_node_to_block(npts);
    std::vector<uint32_t> block_neighbor_counts(num_blocks, 0), touched_blocks;
    std::vector<uint8_t> empty_block(num_blocks, 1), nonfull_block(num_blocks, 1);
    uint32_t first_empty = 0, first_nonfull = 0;
    touched_blocks.reserve(num_blocks);

    auto append = [&](uint32_t block, uint32_t node) {
        blocks[block].push_back(node);
        empty_block[block] = 0;
        if (blocks[block].size() >= capacity)
            nonfull_block[block] = 0;
    };

    for (uint32_t u = 0; u < npts; ++u)
        node_to_block[u] = u / capacity;
    double previous = edge_locality(graph, node_to_block);
    std::cout << "Initial edge locality=" << previous << ", NBR slots/page=" << capacity << std::endl;

    for (uint32_t iter = 0; iter < max_iterations; ++iter)
    {
        for (auto &block : blocks)
            block.clear();
        std::fill(empty_block.begin(), empty_block.end(), 1);
        std::fill(nonfull_block.begin(), nonfull_block.end(), 1);
        first_empty = first_nonfull = 0;
        const uint32_t progress_step = std::max<uint32_t>(1, npts / 10);
        std::cout << "NBR-only block-shuffle iteration " << iter + 1 << " placing nodes..." << std::endl;

        for (uint32_t u = 0; u < npts; ++u)
        {
            touched_blocks.clear();
            for (const uint32_t v : graph[u])
            {
                const uint32_t b = node_to_block[v];
                if (block_neighbor_counts[b] == 0)
                    touched_blocks.push_back(b);
                ++block_neighbor_counts[b];
            }

            bool placed = false;
            while (!placed)
            {
                uint32_t best_block = num_blocks, best_count = 0;
                for (const uint32_t b : touched_blocks)
                    if (block_neighbor_counts[b] > best_count)
                    {
                        best_count = block_neighbor_counts[b];
                        best_block = b;
                    }
                if (best_block == num_blocks)
                    break;
                if (blocks[best_block].size() < capacity)
                {
                    append(best_block, u);
                    placed = true;
                }
                block_neighbor_counts[best_block] = 0;
            }

            if (!placed)
            {
                uint32_t target = num_blocks;
                while (first_empty < num_blocks && !empty_block[first_empty])
                    ++first_empty;
                if (first_empty < num_blocks)
                    target = first_empty;
                else
                {
                    while (first_nonfull < num_blocks && !nonfull_block[first_nonfull])
                        ++first_nonfull;
                    if (first_nonfull < num_blocks)
                        target = first_nonfull;
                }
                if (target == num_blocks)
                    throw std::runtime_error("No free NBR page slot during placement");
                append(target, u);
            }

            for (const uint32_t b : touched_blocks)
                block_neighbor_counts[b] = 0;
            if ((u + 1) % progress_step == 0 || u + 1 == npts)
                std::cout << "Placed " << (u + 1) << "/" << npts << " nodes in iteration " << iter + 1 << std::endl;
        }

        for (uint32_t b = 0; b < num_blocks; ++b)
            for (const uint32_t u : blocks[b])
                next_node_to_block[u] = b;
        const double current = edge_locality(graph, next_node_to_block);
        const double gain = current - previous;
        std::cout << "Iteration " << iter + 1 << ": edge locality=" << current << ", gain=" << gain << std::endl;
        node_to_block.swap(next_node_to_block);
        previous = current;
        if (gain < gain_threshold)
            break;
    }

    uint32_t new_id = 0;
    for (const auto &block : blocks)
        for (const uint32_t old_id : block)
            new_to_old[new_id++] = old_id;
    if (new_id != npts)
        throw std::runtime_error("Block-shuffle did not place every node");
    return new_to_old;
}

void write_map(const std::string &path, const std::vector<uint32_t> &values)
{
    std::ofstream out(path, std::ios::binary);
    if (!out)
        throw std::runtime_error("Cannot create map: " + path);
    const uint32_t count = static_cast<uint32_t>(values.size());
    out.write(reinterpret_cast<const char *>(&count), sizeof(count));
    out.write(reinterpret_cast<const char *>(&MAP_DIM), sizeof(MAP_DIM));
    out.write(reinterpret_cast<const char *>(values.data()), values.size() * sizeof(uint32_t));
    if (!out)
        throw std::runtime_error("Failed writing map: " + path);
}

void write_nbr_layout(const std::string &prefix, const std::vector<std::vector<uint32_t>> &graph,
                      uint32_t width, uint32_t medoid, uint64_t frozen_count,
                      const std::vector<uint32_t> &new_to_old, uint32_t max_iterations,
                      double gain_threshold, uint32_t capacity)
{
    const std::filesystem::path prefix_path(prefix);
    if (prefix_path.has_parent_path())
        std::filesystem::create_directories(prefix_path.parent_path());

    const uint32_t npts = static_cast<uint32_t>(graph.size());
    const uint32_t record_size = sizeof(uint32_t) * (width + 1);
    const uint32_t page_count = (npts + capacity - 1) / capacity;
    const uint64_t total_size = static_cast<uint64_t>(page_count + HEADER_PAGES) * PAGE_SIZE;
    std::vector<uint32_t> old_to_new(npts);
    for (uint32_t new_id = 0; new_id < npts; ++new_id)
        old_to_new[new_to_old[new_id]] = new_id;

    // Keep output buffering bounded while avoiding millions of tiny writes.
    constexpr size_t OUTPUT_BUFFER_SIZE = 64ULL * 1024 * 1024;
    std::vector<char> output_buffer;
    output_buffer.reserve(OUTPUT_BUFFER_SIZE + PAGE_SIZE);
    std::ofstream out(prefix + ".nbr.index", std::ios::binary);
    if (!out)
        throw std::runtime_error("Cannot create NBR index: " + prefix + ".nbr.index");

    std::vector<char> page(PAGE_SIZE, 0);
    const char magic[8] = {'N', 'B', 'R', 'O', 'N', 'L', 'Y', '1'};
    memcpy(page.data(), magic, sizeof(magic));
    uint32_t version = 1, slots_per_page = capacity;
    memcpy(page.data() + 8, &version, sizeof(version));
    memcpy(page.data() + 12, &npts, sizeof(npts));
    memcpy(page.data() + 16, &width, sizeof(width));
    memcpy(page.data() + 20, &record_size, sizeof(record_size));
    memcpy(page.data() + 24, &slots_per_page, sizeof(slots_per_page));
    memcpy(page.data() + 28, &medoid, sizeof(medoid));
    memcpy(page.data() + 32, &frozen_count, sizeof(frozen_count));
    memcpy(page.data() + 40, &page_count, sizeof(page_count));
    memcpy(page.data() + 48, &total_size, sizeof(total_size));
    out.write(page.data(), PAGE_SIZE);

    uint64_t records_written = 0;
    for (uint32_t p = 0; p < page_count; ++p)
    {
        std::fill(page.begin(), page.end(), 0);
        for (uint32_t slot = 0; slot < capacity && records_written < npts; ++slot, ++records_written)
        {
            const uint32_t old_id = new_to_old[records_written];
            char *record = page.data() + static_cast<size_t>(slot) * record_size;
            const uint32_t degree = static_cast<uint32_t>(graph[old_id].size());
            memcpy(record, &degree, sizeof(degree));
            if (degree)
                memcpy(record + sizeof(degree), graph[old_id].data(), degree * sizeof(uint32_t));
        }
        output_buffer.insert(output_buffer.end(), page.begin(), page.end());
        if (output_buffer.size() >= OUTPUT_BUFFER_SIZE)
        {
            out.write(output_buffer.data(), static_cast<std::streamsize>(output_buffer.size()));
            output_buffer.clear();
        }
    }
    if (!output_buffer.empty())
        out.write(output_buffer.data(), static_cast<std::streamsize>(output_buffer.size()));
    out.close();
    if (!out)
        throw std::runtime_error("Failed writing NBR index");

    write_map(prefix + ".old_to_new.bin", old_to_new);
    write_map(prefix + ".new_to_old.bin", new_to_old);

    std::ofstream meta(prefix + ".json");
    meta << "{\n"
         << "  \"format\": \"NBRONLY1\",\n"
         << "  \"logical_node_ids_in_neighbor_lists\": true,\n"
         << "  \"node_count\": " << npts << ",\n"
         << "  \"max_degree\": " << width << ",\n"
         << "  \"record_size_bytes\": " << record_size << ",\n"
         << "  \"page_size_bytes\": " << PAGE_SIZE << ",\n"
         << "  \"nodes_per_page\": " << capacity << ",\n"
         << "  \"data_start_offset_bytes\": " << PAGE_SIZE << ",\n"
         << "  \"page_count\": " << page_count << ",\n"
         << "  \"file_size_bytes\": " << total_size << ",\n"
         << "  \"max_iterations\": " << max_iterations << ",\n"
         << "  \"gain_threshold\": " << gain_threshold << "\n"
         << "}\n";
}
} // namespace

int main(int argc, char **argv)
{
    if (argc != 6)
    {
        std::cerr << "Usage: " << argv[0]
                  << " <base.(fbin|u8bin)> <vamana_mem.index> <output_prefix> <max_iterations> <gain_threshold>\n";
        return 2;
    }

    try
    {
        const std::string base_path = argv[1], mem_index_path = argv[2], output_prefix = argv[3];
        const uint32_t max_iterations = static_cast<uint32_t>(std::stoul(argv[4]));
        const double gain_threshold = std::stod(argv[5]);
        const uint32_t npts = read_base_count(base_path);
        uint32_t width = 0, medoid = 0;
        uint64_t frozen_count = 0;
        auto graph = read_graph(mem_index_path, npts, width, medoid, frozen_count);
        const uint64_t record_size = sizeof(uint32_t) * (static_cast<uint64_t>(width) + 1);
        const uint32_t capacity = static_cast<uint32_t>(PAGE_SIZE / record_size);
        if (capacity == 0)
            throw std::runtime_error("NBR record does not fit in one 4 KiB page");

        const auto order = compute_order(graph, capacity, max_iterations, gain_threshold);
        uint64_t edge_count = 0, same_page_edges = 0;
        std::vector<uint32_t> node_to_page(npts);
        for (uint32_t new_id = 0; new_id < npts; ++new_id)
            node_to_page[order[new_id]] = new_id / capacity;
        for (uint32_t u = 0; u < npts; ++u)
            for (const uint32_t v : graph[u])
            {
                ++edge_count;
                same_page_edges += node_to_page[u] == node_to_page[v];
            }
        const double final_ratio = edge_count ? static_cast<double>(same_page_edges) / edge_count : 0.0;
        std::cout << "Final NBR edge locality=" << final_ratio << " (" << same_page_edges << "/" << edge_count
                  << "), capacity=" << capacity << " nodes/page" << std::endl;
        write_nbr_layout(output_prefix, graph, width, medoid, frozen_count, order,
                         max_iterations, gain_threshold, capacity);
        std::cout << "Wrote NBR-only layout: " << output_prefix << ".nbr.index" << std::endl;
    }
    catch (const std::exception &e)
    {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }
    return 0;
}
