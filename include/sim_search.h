// Event-driven simulation of concurrent DiskANN beam searches on a simplified SSD (N2 experiment).
// Search logic is the real PQFlashIndex logic (candidate list, PQ distances, full-precision distances) and node
// contents are read from the index file; all *times* are simulated: SSD read times come from a per-unit FIFO model,
// host times from a measured profile. Real I/O and CPU time of the simulator do not affect the results.
#pragma once
#include <cstdint>
#include <vector>

namespace diskann
{
struct SimHostProfile
{
    double pre_us = 5.2;     // round start (frontier chosen) -> first read reaches the SSD
    double spacing_us = 0.5; // between consecutive reads of a round
    double post_us = 2.7;    // last completion -> host sees the round's data
    std::vector<double> first_gap_us; // query start -> first round start (setup), sampled
    std::vector<double> gap_us;       // round data processed -> next round start (host compute), sampled
};

struct SimSSDParams
{
    uint32_t units = 96;           // parallel units (calibrated T500 model: 4 ch x 2 chips x 12 dies)
    uint32_t channels = 4;         // unit u is on channel u % channels (CWDP allocation)
    uint32_t sectors_per_page = 4; // unit(sector) = (sector / sectors_per_page) % units
    double cmd_us = 0.29;
    double tr_us = 70.02;
    double xfer_us = 1.707; // 4 KiB data-out on the channel
    double iface_us = 1.0;  // device-side completion path to the host
    double hit_us = 5.0;    // read served from the SSD buffer (prefetched sector)
    // Shared host interface (FIFO) for every read returned to the host, flash or buffer: 0.94 us per 4 KiB gives
    // the ~1.06 M IOPS cap of the calibrated MQSim model (PCIe 1.35 GB/s x 4 standing in for the controller limit).
    // Internal prefetch reads do not use it. 0 = no cap.
    double host_xfer_us = 0.94;
};

struct SimPolicy
{
    uint32_t nominate = 0;            // 0: original top-W beam. >0: host nominates top-k, SSD chooses W
    bool avoid_busy = true;           // SSD prefers nominees whose unit is free (else: top-W in rank order)
    double wait_threshold_us = 0;     // nominee counts as free if its estimated wait <= threshold
    uint32_t prefetch_buffer = 0;     // shared SSD buffer (sectors) for nominated-but-unchosen reads; 0 = off
    uint32_t prefetch_queue_limit = 2; // max queued low-priority prefetches per unit (excess dropped)
};

struct SimQueryResult
{
    double start_us = 0, end_us = 0;
    uint32_t worker = 0, rounds = 0, reads = 0, buffer_hits = 0, prefetch_waits = 0;
};

struct SimSummary
{
    double end_us = 0;
    uint64_t critical_reads = 0, flash_reads = 0, prefetch_issued = 0, prefetch_dropped = 0, prefetch_completed = 0;
    uint64_t buffer_hits = 0, prefetch_waits = 0, prefetch_promoted = 0;
    double unit_busy_us = 0;
    std::vector<float> read_wait_us;   // critical flash reads: SSD arrival -> start of service
    std::vector<float> read_latency_us; // critical reads: SSD arrival -> completion seen by host side
    std::vector<float> round_us;       // first read arrival -> last completion, per round
};
} // namespace diskann
