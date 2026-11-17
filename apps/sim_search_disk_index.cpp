// N2: event-driven simulation of concurrent DiskANN searches on a simplified SSD model.
// Search logic and node contents are real (PQFlashIndex + the index file); times are simulated (SSD model +
// measured host profile). See include/sim_search.h. Writes <out>_summary.txt, <out>_queries.csv,
// <out>_idx_uint32.bin.
#include <algorithm>
#include <boost/program_options.hpp>
#include <fstream>
#include <iostream>
#include <numeric>
#include <sstream>

#include "linux_aligned_file_reader.h"
#include "pq_flash_index.h"
#include "utils.h"

namespace po = boost::program_options;

static diskann::SimHostProfile load_profile(const std::string &path)
{
    diskann::SimHostProfile p;
    std::ifstream in(path);
    if (!in)
        throw std::runtime_error("cannot open host profile " + path);
    std::string line;
    while (std::getline(in, line))
    {
        std::istringstream ss(line);
        std::string key;
        if (!(ss >> key) || key[0] == '#')
            continue;
        double v;
        if (key == "pre_us")
            ss >> p.pre_us;
        else if (key == "spacing_us")
            ss >> p.spacing_us;
        else if (key == "post_us")
            ss >> p.post_us;
        else if (key == "first_gap_us")
            while (ss >> v)
                p.first_gap_us.push_back(v);
        else if (key == "gap_us")
            while (ss >> v)
                p.gap_us.push_back(v);
    }
    return p;
}

static double pct(std::vector<float> v, double q)
{
    if (v.empty())
        return 0;
    std::sort(v.begin(), v.end());
    return v[(size_t)std::min<double>(v.size() - 1, q * v.size())];
}

static double mean(const std::vector<float> &v)
{
    return v.empty() ? 0 : std::accumulate(v.begin(), v.end(), 0.0) / v.size();
}

template <typename T>
int run(const std::string &prefix, const std::string &query_file, const std::string &gt_file, uint32_t K, uint32_t L,
        uint32_t W, uint32_t workers, uint64_t nq_limit, uint32_t num_nodes_to_cache, const diskann::SimHostProfile &host,
        const diskann::SimSSDParams &ssd, const diskann::SimPolicy &policy, uint64_t seed, const std::string &out)
{
    T *query = nullptr;
    size_t nq, qdim, qadim;
    diskann::load_aligned_bin<T>(query_file, query, nq, qdim, qadim);
    if (nq_limit > 0 && nq_limit < nq)
        nq = nq_limit;
    std::shared_ptr<AlignedFileReader> reader(new LinuxAlignedFileReader());
    diskann::PQFlashIndex<T> index(reader, diskann::Metric::L2);
    if (index.load(1, prefix.c_str()) != 0)
        return -1;
    if (num_nodes_to_cache > 0)
    { // same cache as search_disk_index: BFS levels around the medoid(s)
        std::vector<uint32_t> node_list;
        std::cout << "Caching " << num_nodes_to_cache << " nodes around medoid(s)" << std::endl;
        index.cache_bfs_levels(num_nodes_to_cache, node_list);
        index.load_cache_list(node_list);
    }
    std::vector<uint64_t> ids64(nq * K);
    std::vector<float> dists(nq * K);
    std::vector<diskann::SimQueryResult> pq;
    diskann::SimSummary s;
    index.simulate_search(query, nq, qadim, K, L, W, workers, host, ssd, policy, seed, ids64.data(), dists.data(), pq, s);

    std::vector<uint32_t> ids32(ids64.begin(), ids64.end());
    diskann::save_bin<uint32_t>(out + "_idx_uint32.bin", ids32.data(), nq, K);
    double recall = -1;
    if (!gt_file.empty() && file_exists(gt_file))
    {
        uint32_t *gt_ids = nullptr;
        float *gt_dists = nullptr;
        size_t gt_num, gt_dim;
        diskann::load_truthset(gt_file, gt_ids, gt_dists, gt_num, gt_dim);
        recall = diskann::calculate_recall((uint32_t)nq, gt_ids, gt_dists, (uint32_t)gt_dim, ids32.data(), K, K);
    }
    std::vector<float> lat;
    double rounds = 0, nreads = 0;
    std::ofstream qcsv(out + "_queries.csv");
    qcsv << "query,worker,start_us,end_us,latency_us,rounds,reads,buffer_hits,prefetch_waits\n";
    for (size_t i = 0; i < nq; i++)
    {
        const auto &r = pq[i];
        lat.push_back((float)(r.end_us - r.start_us));
        rounds += r.rounds;
        nreads += r.reads;
        qcsv << i << ',' << r.worker << ',' << r.start_us << ',' << r.end_us << ',' << r.end_us - r.start_us << ','
             << r.rounds << ',' << r.reads << ',' << r.buffer_hits << ',' << r.prefetch_waits << '\n';
    }
    std::ostringstream o;
    o << "queries=" << nq << "\nworkers=" << workers << "\nL=" << L << "\nW=" << W
      << "\nnum_nodes_to_cache=" << num_nodes_to_cache << "\nnominate=" << policy.nominate
      << "\navoid_busy=" << policy.avoid_busy << "\nwait_threshold_us=" << policy.wait_threshold_us
      << "\nprefetch_buffer=" << policy.prefetch_buffer << "\nprefetch_queue_limit=" << policy.prefetch_queue_limit
      << "\nhit_us=" << ssd.hit_us << "\nhost_xfer_us=" << ssd.host_xfer_us << "\nseed=" << seed << "\nsim_time_s=" << s.end_us / 1e6
      << "\nqps=" << nq / (s.end_us / 1e6) << "\nlatency_mean_us=" << mean(lat) << "\nlatency_p50_us=" << pct(lat, 0.5)
      << "\nlatency_p99_us=" << pct(lat, 0.99) << "\nrounds_mean=" << rounds / nq << "\nreads_mean=" << nreads / nq
      << "\nrecall=" << recall << "\nround_mean_us=" << mean(s.round_us) << "\nround_p50_us=" << pct(s.round_us, 0.5)
      << "\nround_p99_us=" << pct(s.round_us, 0.99) << "\nread_wait_mean_us=" << mean(s.read_wait_us)
      << "\nread_wait_p99_us=" << pct(s.read_wait_us, 0.99) << "\nread_latency_mean_us=" << mean(s.read_latency_us)
      << "\nread_latency_p50_us=" << pct(s.read_latency_us, 0.5)
      << "\nread_latency_p99_us=" << pct(s.read_latency_us, 0.99) << "\ncritical_reads=" << s.critical_reads
      << "\nflash_reads_critical=" << s.flash_reads << "\nbuffer_hits=" << s.buffer_hits
      << "\nprefetch_waits=" << s.prefetch_waits << "\nprefetch_promoted=" << s.prefetch_promoted
      << "\nprefetch_issued=" << s.prefetch_issued << "\nprefetch_completed=" << s.prefetch_completed
      << "\nprefetch_dropped=" << s.prefetch_dropped << "\ncache_hits=" << s.cache_hits
      << "\ncache_only_rounds=" << s.cache_only_rounds
      << "\nunit_utilization=" << s.unit_busy_us / (ssd.units * s.end_us) << "\n";
    std::ofstream(out + "_summary.txt") << o.str();
    std::cout << o.str();
    diskann::aligned_free(query);
    return 0;
}

int main(int argc, char **argv)
{
    std::string data_type, prefix, query_file, gt_file, profile, out;
    uint32_t K, L, W, workers;
    uint64_t nq, seed;
    uint32_t cache_nodes;
    diskann::SimSSDParams ssd;
    diskann::SimPolicy pol;
    bool no_avoid = false;
    po::options_description desc("sim_search_disk_index (N2 simulation)");
    desc.add_options()("help,h", "help")("data_type", po::value(&data_type)->required(), "uint8/int8/float")(
        "index_path_prefix", po::value(&prefix)->required(), "disk index prefix")(
        "query_file", po::value(&query_file)->required(), "query bin")(
        "gt_file", po::value(&gt_file)->default_value(""), "ground truth (optional)")(
        "recall_at,K", po::value(&K)->default_value(10), "K")("search_list,L", po::value(&L)->default_value(100), "L")(
        "beamwidth,W", po::value(&W)->default_value(4), "W")("workers,T", po::value(&workers)->default_value(16),
                                                              "concurrent search workers")(
        "num_queries", po::value(&nq)->default_value(0), "0 = all")(
        "num_nodes_to_cache", po::value(&cache_nodes)->default_value(0), "node cache (BFS around medoid), as search_disk_index")(
        "host_profile", po::value(&profile)->required(), "host time profile (make_host_profile.py)")(
        "out", po::value(&out)->required(), "output prefix")("seed", po::value(&seed)->default_value(1), "rng seed")(
        "nominate", po::value(&pol.nominate)->default_value(0), "0 = original beam; k = host nominates top-k")(
        "no_avoid_busy", po::bool_switch(&no_avoid), "with nominate: SSD takes the top-W regardless of unit state")(
        "wait_threshold_us", po::value(&pol.wait_threshold_us)->default_value(0), "nominee is free if wait <= this")(
        "prefetch_buffer", po::value(&pol.prefetch_buffer)->default_value(0), "shared SSD buffer sectors; 0 = off")(
        "prefetch_queue_limit", po::value(&pol.prefetch_queue_limit)->default_value(2), "per-unit queued prefetches")(
        "hit_us", po::value(&ssd.hit_us)->default_value(5.0), "buffer hit latency")(
        "iface_us", po::value(&ssd.iface_us)->default_value(1.0), "completion path latency")(
        "tr_us", po::value(&ssd.tr_us)->default_value(70.02), "array read time")(
        "host_xfer_us", po::value(&ssd.host_xfer_us)->default_value(0.94), "shared host interface time per read; 0 = no cap");
    po::variables_map vm;
    try
    {
        po::store(po::parse_command_line(argc, argv, desc), vm);
        if (vm.count("help"))
        {
            std::cout << desc;
            return 0;
        }
        po::notify(vm);
    }
    catch (const std::exception &e)
    {
        std::cerr << e.what() << '\n' << desc;
        return -1;
    }
    pol.avoid_busy = !no_avoid;
    auto host = load_profile(profile);
    if (data_type == "uint8")
        return run<uint8_t>(prefix, query_file, gt_file, K, L, W, workers, nq, cache_nodes, host, ssd, pol, seed, out);
    if (data_type == "int8")
        return run<int8_t>(prefix, query_file, gt_file, K, L, W, workers, nq, cache_nodes, host, ssd, pol, seed, out);
    if (data_type == "float")
        return run<float>(prefix, query_file, gt_file, K, L, W, workers, nq, cache_nodes, host, ssd, pol, seed, out);
    std::cerr << "unknown data_type\n";
    return -1;
}
