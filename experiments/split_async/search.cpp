// Experimental SIFT128 uint8 split-layout baseline. Original DiskANN search is untouched.
#include "distance.h"
#include "neighbor.h"
#include "pq.h"
#include "tsl/robin_set.h"
#include <array>
#include <algorithm>
#include <limits>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <iostream>
#include <libaio.h>
#include <memory>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <deque>
#include <unistd.h>
using Clock = std::chrono::steady_clock;
double us(Clock::time_point t)
{
    return std::chrono::duration<double, std::micro>(Clock::now() - t).count();
}
double thread_cpu_us()
{
    timespec ts{};
    if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &ts) != 0)
        throw std::runtime_error("thread CPU clock failed");
    return double(ts.tv_sec) * 1000000.0 + double(ts.tv_nsec) / 1000.0;
}
// CLOCK_MONOTONIC matches trace-cmd's mono trace clock.
uint64_t mono_ns()
{
    timespec ts{};
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return uint64_t(ts.tv_sec) * 1000000000 + ts.tv_nsec;
}
struct IoStamp
{
    uint64_t query, beam, request, offset, submit_begin = 0, submit_end = 0, observed = 0, process = 0,
                                           wait_begin = 0, wait_end = 0;
    const char *kind;
    uint32_t node;
};
thread_local std::vector<IoStamp> io_stamps;
bool trace_io = false;
thread_local uint64_t trace_query = 0, trace_beam = 0;
struct File
{
    int fd;
    explicit File(const char *p) : fd(open(p, O_RDONLY | O_DIRECT))
    {
        if (fd < 0)
            throw std::runtime_error(p);
    }
    ~File()
    {
        close(fd);
    }
};
struct AioContext
{
    io_context_t value = 0;
    AioContext()
    {
        if (io_setup(1024, &value) < 0)
            throw std::runtime_error("io_setup failed");
    }
    ~AioContext()
    {
        if (value)
            io_destroy(value);
    }
};
struct Batch
{
    io_context_t ctx = 0;
    std::vector<iocb> cb;
    std::vector<iocb *> ptr;
    std::vector<void *> buffers;
    std::vector<bool> ready;
    size_t pending = 0;
    size_t stamp_base = 0;
    explicit Batch(size_t n, io_context_t shared)
        : ctx(shared), cb(n), ptr(n), buffers(n, nullptr), ready(n, false)
    {
        stamp_base = io_stamps.size();
        if (trace_io)
            io_stamps.resize(stamp_base + n);
        for (size_t i = 0; i < n; i++)
            if (posix_memalign(&buffers[i], 4096, 4096))
                throw std::bad_alloc();
    }
    ~Batch()
    {
        while (pending)
        {
            io_event e{};
            int r = io_getevents(ctx, 1, 1, &e, nullptr);
            if (r == 1)
                --pending;
            else if (r != -EINTR)
                break;
        }
        for (auto b : buffers)
            free(b);
    }
    void set(size_t i, int fd, uint64_t page, const char *kind, uint32_t node)
    {
        io_prep_pread(&cb[i], fd, buffers[i], 4096, page * 4096);
        cb[i].data = reinterpret_cast<void *>(i + 1);
        ptr[i] = &cb[i];
        if (trace_io)
            io_stamps[stamp_base + i] = {trace_query, trace_beam, i, page * 4096, 0,    0,
                                         0,           0,          0, 0,           kind, node};
    }
    void submit()
    {
        size_t sent = 0;
        while (sent < ptr.size())
        {
            uint64_t begin = trace_io ? mono_ns() : 0;
            int r = io_submit(ctx, ptr.size() - sent, ptr.data() + sent);
            if (r == -EINTR)
                continue;
            if (r <= 0)
                throw std::runtime_error("io_submit failed");
            uint64_t end = trace_io ? mono_ns() : 0;
            if (trace_io)
                for (int j = 0; j < r; j++)
                {
                    auto &s = io_stamps[stamp_base + sent + j];
                    s.submit_begin = begin;
                    s.submit_end = end;
                }
            sent += r;
            pending += r;
        }
    }
    void wait(size_t i)
    {
        if (trace_io)
            io_stamps[stamp_base + i].wait_begin = mono_ns();
        while (!ready[i])
        {
            io_event e{};
            int r = io_getevents(ctx, 1, 1, &e, nullptr);
            uint64_t observed = trace_io ? mono_ns() : 0;
            if (r == -EINTR)
                continue;
            if (r == 1)
                --pending; // Event was consumed even if it reports an I/O error.
            if (r != 1 || e.res != 4096 || e.res2)
                throw std::runtime_error("short/failed AIO read");
            ready[reinterpret_cast<uintptr_t>(e.data) - 1] = true;
            if (trace_io)
                io_stamps[stamp_base + reinterpret_cast<uintptr_t>(e.data) - 1].observed = observed;
        }
        if (trace_io)
        {
            auto &s = io_stamps[stamp_base + i];
            s.wait_end = mono_ns();
            s.process = s.wait_end;
        }
    }
};
// Persistent worker: independent AIO context; at most depth vector reads per batch.
class VectorWorker
{
    struct Job { uint32_t node; uint64_t beam; };
    int fd;
    size_t depth;
    bool profile;
    std::mutex mutex;
    std::condition_variable cv;
    std::deque<Job> queue;
    bool stopping = false, active = false, ended = false, done = true;
    uint64_t query_id = 0;
    alignas(64) std::array<uint8_t, 128> query{};
    std::exception_ptr error;
    std::thread thread;
    void run()
    {
        try
        {
            AioContext context;
            std::unique_ptr<diskann::Distance<uint8_t>> distance(
                diskann::get_distance_function<uint8_t>(diskann::Metric::L2));
            std::unique_lock<std::mutex> lock(mutex);
            for (;;)
            {
                cv.wait(lock, [&] { return stopping || active; });
                if (stopping) return;
                const double cpu_start = thread_cpu_us();
                trace_query = query_id;
                io_stamps.clear();
                for (;;)
                {
                    cv.wait(lock, [&] { return stopping || ended || !queue.empty(); });
                    if (stopping) return;
                    if (queue.empty() && ended) break;
                    std::vector<Job> jobs;
                    while (!queue.empty() && jobs.size() < depth)
                    {
                        jobs.push_back(queue.front());
                        queue.pop_front();
                    }
                    lock.unlock();
                    {
                        Batch io(jobs.size(), context.value);
                        for (size_t i = 0; i < jobs.size(); ++i)
                        {
                            trace_beam = jobs[i].beam;
                            io.set(i, fd, jobs[i].node / 32, "vector", jobs[i].node);
                        }
                        auto t = profile ? Clock::now() : Clock::time_point{};
                        io.submit();
                        if (profile) submit_us += us(t);
                        for (size_t i = 0; i < jobs.size(); ++i)
                        {
                            t = profile ? Clock::now() : Clock::time_point{};
                            io.wait(i);
                            if (profile) wait_us += us(t);
                            t = profile ? Clock::now() : Clock::time_point{};
                            auto v = static_cast<uint8_t *>(io.buffers[i]) + (jobs[i].node % 32) * 128;
                            results.emplace_back(jobs[i].node, distance->compare(query.data(), v, 128));
                            if (profile) exact_us += us(t);
                        }
                    }
                    lock.lock();
                }
                cpu_us = thread_cpu_us() - cpu_start;
                stamps.swap(io_stamps);
                active = false;
                done = true;
                cv.notify_all();
            }
        }
        catch (...)
        {
            std::lock_guard<std::mutex> lock(mutex);
            error = std::current_exception();
            done = true;
            cv.notify_all();
        }
    }
public:
    double cpu_us = 0, submit_us = 0, wait_us = 0, exact_us = 0;
    size_t max_queue = 0;
    std::vector<diskann::Neighbor> results;
    std::vector<IoStamp> stamps;
    VectorWorker(int file, size_t limit, bool timing) : fd(file), depth(limit), profile(timing)
    {
        thread = std::thread([this] { run(); });
    }
    ~VectorWorker()
    {
        { std::lock_guard<std::mutex> lock(mutex); stopping = true; cv.notify_all(); }
        thread.join();
    }
    void begin(uint64_t id, const uint8_t *q)
    {
        std::lock_guard<std::mutex> lock(mutex);
        if (error) std::rethrow_exception(error);
        query_id = id;
        std::copy_n(q, 128, query.data());
        results.clear(); stamps.clear(); queue.clear();
        cpu_us = submit_us = wait_us = exact_us = 0;
        max_queue = 0;
        ended = false; done = false; active = true;
        cv.notify_all();
    }
    void enqueue(const std::vector<uint32_t> &nodes, uint64_t beam)
    {
        std::lock_guard<std::mutex> lock(mutex);
        if (error) std::rethrow_exception(error);
        for (auto node : nodes) queue.push_back({node, beam});
        max_queue = std::max(max_queue, queue.size());
        cv.notify_all();
    }
    void finish()
    {
        std::unique_lock<std::mutex> lock(mutex);
        ended = true; cv.notify_all();
        cv.wait(lock, [&] { return done; });
        if (error) std::rethrow_exception(error);
    }
};
template <class T> std::vector<T> bin(const char *path, uint32_t &n, uint32_t &d)
{
    std::ifstream f(path, std::ios::binary);
    f.read((char *)&n, 4);
    f.read((char *)&d, 4);
    if (!f || !n || !d)
        throw std::runtime_error("bad bin header");
    std::vector<T> v(size_t(n) * d);
    f.read((char *)v.data(), v.size() * sizeof(T));
    if (!f)
        throw std::runtime_error("truncated bin");
    return v;
}
int main(int argc, char **argv)
try
{
    if (argc != 14)
    {
        std::cerr << "Usage: search_split_async neighbors.bin vectors.bin pq_codes.bin pq_pivots.bin "
                     "query.u8bin medoid L beam K query_limit output.csv old_to_new.bin new_to_old.bin\n";
        return 2;
    }
    const std::string mode = std::getenv("SEARCH_MODE") ? std::getenv("SEARCH_MODE") : "baseline";
    if (mode != "baseline" && mode != "traverse_only" && mode != "host_worker" && mode != "deferred")
        throw std::runtime_error("SEARCH_MODE must be baseline, traverse_only, host_worker or deferred");
    const bool deferred = mode == "deferred";
    const unsigned rerank_percent = deferred && std::getenv("RERANK_PERCENT")
                                        ? std::stoul(std::getenv("RERANK_PERCENT")) : 100;
    if (rerank_percent == 0 || rerank_percent > 100)
        throw std::runtime_error("RERANK_PERCENT must be in [1, 100]");
    const std::string expansion = std::getenv("GRAPH_EXPANSION") ? std::getenv("GRAPH_EXPANSION") : "page";
    if (expansion != "page" && expansion != "node")
        throw std::runtime_error("GRAPH_EXPANSION must be page or node");
    const bool node_expansion = expansion == "node";
    const bool do_exact = mode != "traverse_only";
    const bool use_worker = mode == "host_worker";
    File nf(argv[1]);
    std::unique_ptr<File> vf;
    if (do_exact)
        vf.reset(new File(argv[2]));
    uint32_t n, m, qn, qd;
    std::cout << "Loading resident PQ codes and queries..." << std::endl;
    auto codes = bin<uint8_t>(argv[3], n, m);
    auto queries = bin<uint8_t>(argv[5], qn, qd);
    uint32_t medoid = std::stoul(argv[6]), L = std::stoul(argv[7]), W = std::stoul(argv[8]),
             K = std::stoul(argv[9]);
    qn = std::min(qn, uint32_t(std::stoul(argv[10])));
    if (qd != 128 || medoid >= n || K == 0 || L < K || W == 0 || W > 512 || m > 128 || !qn)
        throw std::runtime_error("invalid parameters");
    uint32_t mn, md, rn, rd;
    std::cout << "Loading and checking shuffled layout maps..." << std::endl;
    auto node_to_slot = bin<uint32_t>(argv[12], mn, md);
    auto slot_to_node = bin<uint32_t>(argv[13], rn, rd);
    if (mn != n || rn != n || md != 1 || rd != 1)
        throw std::runtime_error("map shape mismatch");
    for (uint32_t id = 0; id < n; id++)
        if (node_to_slot[id] >= n || slot_to_node[node_to_slot[id]] != id)
            throw std::runtime_error("maps are not inverse permutations");
    std::ifstream header(argv[1], std::ios::binary);
    std::array<char, 4096> h{};
    header.read(h.data(), h.size());
    auto field = [&](size_t off) {
        uint32_t v;
        memcpy(&v, h.data() + off, 4);
        return v;
    };
    uint64_t frozen = 0;
    memcpy(&frozen, h.data() + 32, 8);
    if (!header || memcmp(h.data(), "NBRONLY1", 8) || field(8) != 1 || field(12) != n || field(16) != 64 ||
        field(20) != 260 || field(24) != 15 || field(28) != medoid || frozen)
        throw std::runtime_error("NBRONLY1 header/medoid mismatch");
    // Optional native multi-medoid initialization for controlled layout comparisons.
    std::vector<uint32_t> entry_medoids;
    std::vector<float> entry_centroids;
    if (std::getenv("SEARCH_MEDOIDS") || std::getenv("SEARCH_CENTROIDS"))
    {
        if (!std::getenv("SEARCH_MEDOIDS") || !std::getenv("SEARCH_CENTROIDS"))
            throw std::runtime_error("Set both SEARCH_MEDOIDS and SEARCH_CENTROIDS");
        uint32_t en, ed, cn, cd;
        entry_medoids = bin<uint32_t>(std::getenv("SEARCH_MEDOIDS"), en, ed);
        entry_centroids = bin<float>(std::getenv("SEARCH_CENTROIDS"), cn, cd);
        if (!en || ed != 1 || cn != en || cd != 128)
            throw std::runtime_error("Invalid medoid/centroid shape");
        for (auto id : entry_medoids)
            if (id >= n) throw std::runtime_error("Medoid out of range");
    }
    std::unique_ptr<diskann::Distance<float>> entry_distance(
        diskann::get_distance_function<float>(diskann::Metric::L2));
    diskann::FixedChunkPQTable table;
    table.load_pq_centroid_bin(argv[4], m);
    std::ofstream out(argv[11]);
    if (!out)
        throw std::runtime_error("cannot open CSV");
    out << "query_id,total_us,pq_us,candidate_us,exact_us,wait_us,submit_us,neighbor_reads,vector_reads,host_"
           "read_bytes,resident_pq_evaluations,pq_evaluations,profile_host,search_mode,thread_cpu_us,beam_count,selected_nodes,neighbor_wait_us,vector_wait_us,traversal_us,tail_wait_us,worker_cpu_us,total_cpu_us,worker_submit_us,worker_wait_us,worker_exact_us,worker_max_queue,vector_qd,graph_expansion,rerank_percent,rerank_pool,rerank_selected,rerank_us,result_ids\n";
    trace_io = std::getenv("TRACE_IO") && std::string(std::getenv("TRACE_IO")) == "1";
    std::ofstream trace;
    if (trace_io)
    {
        trace.open(std::string(argv[11]) + ".io.csv");
        if (!trace)
            throw std::runtime_error("cannot open I/O trace");
        trace << "pid,query,beam,request,kind,node,file_offset,bytes,submit_begin_ns,submit_end_ns,"
                 "completion_observed_ns,processing_start_ns,wait_begin_ns,wait_end_ns\n";
    }
    const bool profile_host = std::getenv("PROFILE_HOST") && std::string(std::getenv("PROFILE_HOST")) == "1";
    auto stage_now = [&]() { return profile_host ? Clock::now() : Clock::time_point{}; };
    auto stage_us = [&](Clock::time_point t) { return profile_host ? us(t) : 0.0; };
    std::unique_ptr<diskann::Distance<uint8_t>> exact_distance(
        diskann::get_distance_function<uint8_t>(diskann::Metric::L2));
    alignas(64) std::array<uint8_t, 128> exact_query{};
    alignas(64) std::array<uint8_t, 65 * 128> pq_coords{};
    alignas(64) std::array<float, 65> pq_distances{};
    std::cout << "PQ kernel: DiskANN aggregate_coords + pq_dist_lookup; PROFILE_HOST=" << profile_host
              << std::endl;
    std::cout << "Search mode: " << mode << "; graph expansion: " << expansion << std::endl;
    AioContext context;
    const size_t vector_qd = std::getenv("VECTOR_QD") ? std::stoul(std::getenv("VECTOR_QD")) : W;
    if (vector_qd == 0 || vector_qd > 512)
        throw std::runtime_error("VECTOR_QD must be between 1 and 512");
    std::unique_ptr<VectorWorker> worker;
    if (use_worker)
        worker.reset(new VectorWorker(vf->fd, vector_qd, profile_host));
    std::cout << "Searching " << qn << " queries (L=" << L << ", W=" << W << ")..." << std::endl;
    diskann::NeighborPriorityQueue frontier;
    frontier.reserve(L);
    tsl::robin_set<uint64_t> seen;
    seen.reserve(4096);
    tsl::robin_set<uint32_t> expanded_pages;
    std::vector<diskann::Neighbor> exact;
    std::vector<diskann::Neighbor> deferred_candidates;
    std::vector<uint32_t> nodes, pages;
    nodes.reserve(W);
    pages.reserve(W);
    alignas(64) std::array<float, 128 * 256> lut{};
    for (uint32_t qi = 0; qi < qn; qi++)
    {
        trace_query = qi;
        trace_beam = 0;
        io_stamps.clear();
        auto total = Clock::now();
        const double cpu_start = thread_cpu_us();
        uint64_t selected_nodes = 0;
        double neighbor_wait = 0, vector_wait = 0;
        double pqtime = 0, candtime = 0, exacttime = 0, waittime = 0, submit = 0;
        uint64_t reads = 0, vector_reads = 0, residents_scored = 0, pq_evaluations = 0;
        expanded_pages.clear();
        seen.clear();
        frontier.clear();
        exact.clear();
        deferred_candidates.clear();
        alignas(64) std::array<float, 128> q{};
        for (unsigned j = 0; j < 128; j++)
            q[j] = queries[size_t(qi) * 128 + j];
        auto t = stage_now();
        uint32_t query_medoid = medoid;
        if (!entry_medoids.empty())
        {
            float best = std::numeric_limits<float>::max();
            alignas(64) std::array<float, 128> centroid{};
            for (size_t j = 0; j < entry_medoids.size(); ++j)
            {
                std::copy_n(entry_centroids.data() + j * 128, 128, centroid.data());
                const float distance = entry_distance->compare(q.data(), centroid.data(), 128);
                if (distance < best)
                {
                    best = distance;
                    query_medoid = entry_medoids[j];
                }
            }
        }
        table.preprocess_query(q.data());

        table.populate_chunk_distances(q.data(), lut.data());
        pqtime += stage_us(t);
        auto compute_dists = [&](const uint32_t *ids, size_t count) {
            diskann::aggregate_coords(ids, count, codes.data(), m, pq_coords.data());
            diskann::pq_dist_lookup(pq_coords.data(), count, m, lut.data(), pq_distances.data());
        };
        std::copy_n(queries.data() + size_t(qi) * 128, 128, exact_query.data());
        if (worker) worker->begin(qi, exact_query.data());
        compute_dists(&query_medoid, 1);

        frontier.insert(diskann::Neighbor(query_medoid, pq_distances[0]));
        seen.insert(query_medoid);
        while (frontier.has_unexpanded_node())
        {
            t = stage_now();
            nodes.clear();
            while (nodes.size() < W && frontier.has_unexpanded_node())
            {
                const auto candidate = frontier.closest_unexpanded();
                nodes.push_back(candidate.id);
                if (deferred) deferred_candidates.push_back(candidate);
            }
            candtime += stage_us(t);
            const size_t b = nodes.size();
            selected_nodes += b;
            const size_t vector_count = do_exact && !use_worker && !deferred ? b : 0;
            pages.clear();
            for (auto id : nodes)
            {
                uint32_t page = node_to_slot[id] / 15;
                if (node_expansion || expanded_pages.insert(page).second)
                    pages.push_back(page);
            }
            const size_t g = pages.size();
            ++trace_beam;
            Batch io(g + vector_count, context.value);
            for (size_t i = 0; i < g; i++)
                io.set(i, nf.fd, 1 + pages[i], "neighbor", UINT32_MAX);
            for (size_t i = 0; i < vector_count; i++)
                io.set(g + i, vf->fd, nodes[i] / 32, "vector", nodes[i]);
            t = stage_now();
            io.submit();
            submit += stage_us(t);
            if (worker) worker->enqueue(nodes, trace_beam);
            reads += g;
            vector_reads += vector_count;
            // Node mode reads one page per selected node, matching native no-cache traversal.
            // Page mode expands every valid record; IDs remain original IDs.
            for (size_t i = 0; i < g; i++)
            {
                t = stage_now();
                io.wait(i);
                const double waited = stage_us(t);
                waittime += waited;
                neighbor_wait += waited;
                const uint64_t first = uint64_t(pages[i]) * 15;
                const uint32_t first_slot = node_expansion ? node_to_slot[nodes[i]] % 15 : 0;
                const uint32_t end_slot = node_expansion ? first_slot + 1 : 15;
                for (uint32_t slot = first_slot; slot < end_slot && first + slot < n; slot++)
                {
                    uint32_t resident = slot_to_node[first + slot];
                    auto row = (uint32_t *)((char *)io.buffers[i] + slot * 260);
                    const uint32_t degree = row[0];
                    if (degree > 64)
                        throw std::runtime_error("bad graph degree");
                    // Preserve resident-then-neighbors insertion order, using DiskANN batch scoring.
                    std::array<uint32_t, 65> ids{};
                    ids[0] = resident;
                    for (uint32_t j = 0; j < degree; j++)
                    {
                        if (row[j + 1] >= n)
                            throw std::runtime_error("bad graph ID");
                        ids[j + 1] = row[j + 1];
                    }
                    t = stage_now();
                    const uint32_t begin = node_expansion ? 1 : 0;
                    compute_dists(ids.data() + begin, degree + 1 - begin);
                    pqtime += stage_us(t);
                    residents_scored += !node_expansion;
                    pq_evaluations += degree + 1 - begin;
                    // Native DiskANN scores the adjacency batch before visited filtering.
                    t = stage_now();
                    for (uint32_t j = begin; j <= degree; j++)
                        if (seen.insert(ids[j]).second)
                            frontier.insert(diskann::Neighbor(ids[j], pq_distances[j - begin]));
                    candtime += stage_us(t);
                }
            }
            for (size_t i = 0; i < vector_count; i++)
            {
                t = stage_now();
                io.wait(g + i);
                const double waited = stage_us(t);
                waittime += waited;
                vector_wait += waited;
                t = stage_now();
                auto v = (uint8_t *)io.buffers[g + i] + (nodes[i] % 32) * 128;
                float d = exact_distance->compare(exact_query.data(), v, 128);
                exact.emplace_back(nodes[i], d);
                exacttime += stage_us(t);
            }
        }
        const double traversal_elapsed = us(total);
        const uint64_t graph_beams = trace_beam;
        size_t rerank_pool = 0, rerank_selected = 0;
        double rerank_us = 0;
        if (deferred)
        {
            const auto rerank_start = Clock::now();
            // Pool = unique nodes selected by the beam across the full traversal.
            // Keep their PQ scores; exact distances never affect this selection.
            std::sort(deferred_candidates.begin(), deferred_candidates.end(),
                      [](const diskann::Neighbor &a, const diskann::Neighbor &b) { return a.id < b.id; });
            deferred_candidates.erase(std::unique(deferred_candidates.begin(), deferred_candidates.end(),
                [](const diskann::Neighbor &a, const diskann::Neighbor &b) { return a.id == b.id; }),
                deferred_candidates.end());
            std::sort(deferred_candidates.begin(), deferred_candidates.end());
            rerank_pool = deferred_candidates.size();
            rerank_selected = std::min(rerank_pool,
                std::max(size_t(K), (rerank_pool * rerank_percent + 99) / 100));
            for (size_t begin = 0; begin < rerank_selected; begin += W)
            {
                const size_t count = std::min(size_t(W), rerank_selected - begin);
                ++trace_beam; // Tail-vector batches have distinct trace IDs.
                Batch io(count, context.value);
                for (size_t i = 0; i < count; ++i)
                {
                    const auto id = deferred_candidates[begin + i].id;
                    io.set(i, vf->fd, id / 32, "vector", id);
                }
                t = stage_now();
                io.submit();
                submit += stage_us(t);
                vector_reads += count;
                for (size_t i = 0; i < count; ++i)
                {
                    t = stage_now();
                    io.wait(i);
                    const double waited = stage_us(t);
                    waittime += waited;
                    vector_wait += waited;
                    t = stage_now();
                    const auto id = deferred_candidates[begin + i].id;
                    auto v = static_cast<uint8_t *>(io.buffers[i]) + (id % 32) * 128;
                    exact.emplace_back(id, exact_distance->compare(exact_query.data(), v, 128));
                    exacttime += stage_us(t);
                }
            }
            rerank_us = us(rerank_start);
        }
        double tail_wait = 0;
        if (worker)
        {
            auto tail_start = Clock::now();
            worker->finish();
            tail_wait = us(tail_start);
            exact.swap(worker->results);
            vector_reads = selected_nodes;
        }
        t = stage_now();
        if (do_exact)
            std::sort(exact.begin(), exact.end());
        candtime += stage_us(t);
        const double cpu_elapsed = thread_cpu_us() - cpu_start;
        const double total_elapsed = us(total);
        out << qi << ',' << total_elapsed << ',' << pqtime << ',' << candtime << ',' << exacttime << ','
            << waittime << ',' << submit << ',' << reads << ',' << vector_reads << ','
            << (reads + vector_reads) * 4096 << ',' << residents_scored << ',' << pq_evaluations << ','
            << profile_host << ',' << mode << ',' << cpu_elapsed << ',' << graph_beams << ','
            << selected_nodes << ',' << neighbor_wait << ',' << vector_wait << ','
            << traversal_elapsed << ',' << tail_wait << ',' << (worker ? worker->cpu_us : 0) << ','
            << cpu_elapsed + (worker ? worker->cpu_us : 0) << ','
            << (worker ? worker->submit_us : 0) << ',' << (worker ? worker->wait_us : 0) << ','
            << (worker ? worker->exact_us : 0) << ',' << (worker ? worker->max_queue : 0) << ','
            << (worker ? vector_qd : 0) << ',' << expansion << ','
            << (do_exact ? rerank_percent : 0) << ',' << rerank_pool << ',' << rerank_selected << ','
            << rerank_us << ",\"";
        for (size_t i = 0; i < std::min(size_t(K), exact.size()); i++)
            out << (i ? " " : "") << exact[i].id;
        out << "\"\n";
        if (trace_io)
        {
            if (worker) io_stamps.insert(io_stamps.end(), worker->stamps.begin(), worker->stamps.end());
            for (const auto &s : io_stamps)
                trace << getpid() << ',' << s.query << ',' << s.beam << ',' << s.request << ',' << s.kind
                      << ',' << s.node << ',' << s.offset << ",4096," << s.submit_begin << ',' << s.submit_end
                      << ',' << s.observed << ',' << s.process << ',' << s.wait_begin << ',' << s.wait_end
                      << '\n';
            trace.flush();
            if (!trace)
                throw std::runtime_error("I/O trace write failed");
        }
        if ((qi + 1) % std::max(1u, qn / 20) == 0 || qi + 1 == qn)
        {
            out.flush();
            if (!out)
                throw std::runtime_error("CSV write failed");
            std::cout << "Progress: " << qi + 1 << "/" << qn << " queries (" << 100.0 * (qi + 1) / qn << "%)"
                      << std::endl;
        }
    }
    return 0;
}
catch (const std::exception &e)
{
    std::cerr << e.what() << '\n';
    return 1;
}
