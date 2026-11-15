// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT license.

#pragma once

#include <cstddef>
#include <cstdint>
#include <fstream>
#include <functional>
#ifdef _WINDOWS
#include <numeric>
#endif
#include <string>
#include <vector>

#include "distance.h"
#include "parameters.h"

namespace diskann
{
struct QueryStats
{
    float total_us = 0; // total time to process query in micros
    float io_us = 0;    // total time spent in IO
    float cpu_us = 0;   // total time spent in CPU

    unsigned n_4k = 0;         // # of 4kB reads
    unsigned n_8k = 0;         // # of 8kB reads
    unsigned n_12k = 0;        // # of 12kB reads
    unsigned n_ios = 0;        // total # of IOs issued
    unsigned read_size = 0;    // total # of bytes read
    unsigned n_cmps_saved = 0; // # cmps saved
    unsigned n_cmps = 0;       // # cmps
    unsigned n_cache_hits = 0; // # cache_hits
    unsigned n_hops = 0;       // # search hops
    // Experimental nominate/choose policy counters (zero unless --frontier_nominate is used).
    unsigned n_busy_reads = 0;      // uncached reads issued to a unit marked busy
    unsigned n_busy_rounds = 0;     // iterations with at least one such read
    unsigned n_prefetch_issued = 0; // nominated-but-not-chosen sectors put into the prefetch buffer
    unsigned n_prefetch_hits = 0;   // chosen reads whose sector was already in the prefetch buffer
};

// One uncached node read in the order it is submitted for a query iteration.
// sector_id is the node's logical sector in the selected on-disk index layout.
struct QueryNodeAccess
{
    uint32_t node_id = 0;
    uint64_t sector_id = 0;
};

struct QueryRerankCandidate
{
    uint32_t node_id = 0;
    float pq_distance = 0;
};

struct QueryIterationTrace
{
    uint32_t iteration = 0;
    std::vector<QueryNodeAccess> node_accesses;
    // Process-wide steady-clock timestamps, in nanoseconds. Zero means not recorded.
    uint64_t iteration_begin_ns = 0;
    uint64_t iteration_end_ns = 0;
    uint64_t read_begin_ns = 0;
    uint64_t read_end_ns = 0;
    float iteration_us = 0;
    float io_us = 0;

    uint32_t cache_hits = 0;
    uint32_t uncached_nodes = 0;
    uint32_t issued_reads = 0;
    uint32_t unique_sectors = 0;
    uint32_t duplicate_sectors = 0;

    uint64_t requested_bytes = 0;
    uint64_t useful_payload_bytes = 0;

    uint32_t neighbors_seen = 0;
    uint32_t unique_neighbors = 0;
    uint32_t new_visited = 0;
    uint32_t candidates_inserted = 0;

    uint32_t pq_computed = 0;
    uint32_t pq_evaluated = 0;
    uint32_t pq_passed = 0;
    uint32_t entered_top_l = 0;
    uint32_t eventually_expanded = 0;
    uint32_t final_topk = 0;
};

// One neighbor seen while expanding a node (optional expansion log, used to replay the candidate list offline).
// flags: bit0 neighbor was not visited before, bit1 inserted into the candidate list,
//        bit2 parent came from the node cache, bit3 parent was a co-located sector node (use_sector_candidates).
struct QueryExpansionRecord
{
    uint32_t iteration = 0;
    uint32_t parent = 0;
    uint32_t neighbor = 0;
    float pq_distance = 0;
    uint8_t flags = 0;
};

struct QueryTrace
{
    int worker_id = -1;
    bool enable_funnel = false;
    std::vector<QueryIterationTrace> iterations;
    std::vector<QueryRerankCandidate> rerank_candidates;
    // Optional expansion log (disabled by default).
    bool enable_expansion_log = false;
    uint32_t start_node = 0;
    float start_pq_distance = 0;
    std::vector<QueryExpansionRecord> expansions;
    // Frontier candidates skipped because their parallel unit was already used in the same iteration.
    uint64_t unit_conflicts_skipped = 0;
};

template <typename T>
inline T get_percentile_stats(QueryStats *stats, uint64_t len, float percentile,
                              const std::function<T(const QueryStats &)> &member_fn)
{
    std::vector<T> vals(len);
    for (uint64_t i = 0; i < len; i++)
    {
        vals[i] = member_fn(stats[i]);
    }

    std::sort(vals.begin(), vals.end(), [](const T &left, const T &right) { return left < right; });

    auto retval = vals[(uint64_t)(percentile * len)];
    vals.clear();
    return retval;
}

template <typename T>
inline double get_mean_stats(QueryStats *stats, uint64_t len, const std::function<T(const QueryStats &)> &member_fn)
{
    double avg = 0;
    for (uint64_t i = 0; i < len; i++)
    {
        avg += (double)member_fn(stats[i]);
    }
    return avg / len;
}
} // namespace diskann
