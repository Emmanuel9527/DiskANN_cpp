# Study 1: DiskANN Baseline Characterization

## Goal

This study answers the first-order question behind the DiskANN SSD-side design:

> Is Host-SSD data transfer actually on the critical path of DiskANN search, and
> under what conditions?

The immediate goal is not to build a computational SSD design yet. The goal is
to collect enough baseline evidence to decide which SSD-side mechanism is worth
simulating.

The main hypothesis to test is:

> DiskANN transfers many bytes from SSD to host that are never useful to the
> final result. If those useless transfers are removed, end-to-end latency may
> improve only when the removed transfer time is exposed on the critical path.

Therefore, this study must separate useless transfer volume from actual
end-to-end performance impact.

## Key Questions

1. How much time does DiskANN spend in host computation, I/O software overhead,
   exposed device waiting, data transfer, and final full-vector reranking?
2. During a query, where do raw neighbors disappear in the search pipeline?
3. Which traffic class dominates search cost: neighbor-list reads, host DRAM PQ
   accesses, or full-vector reads?
4. Do 4 KB pages have reuse across later search iterations?
5. If SSD-side PQ distance computation is considered, how many additional PQ
   pages would each expanded node require?
6. Which SSD-side architecture is justified by the measured critical path?

## Phase 1: Baseline Critical Path Profiling

Run unmodified DiskANN search behavior first and collect per-query and
per-iteration timing.

Recommended sweep:

| Parameter | Values |
| --- | --- |
| `K` | `10` |
| `L` | `20 40 60 80 100` |
| `W` | `1 2 4 8 16` |
| `num_nodes_to_cache` | `0 1000 5000 10000 25000 50000` |
| threads | start with `1`, then test `8` and `16` |

Metrics:

- mean, p95, p99, and p999 latency
- recall@K
- QPS
- I/Os per query
- 4 KB reads per query
- host CPU time per query
- I/O time per query
- exposed I/O time per query
- per-iteration lifecycle timing

Required code changes:

- Extend `diskann::QueryIterationTrace` in `include/percentile_stats.h`.
- Instrument `PQFlashIndex::cached_beam_search()` in `src/pq_flash_index.cpp`.
- Extend search CLI and CSV output in `apps/search_disk_index.cpp`.
- Split Linux AIO timing in `src/linux_aligned_file_reader.cpp` if we need
  separate `io_submit()` and `io_getevents()` measurements.

Important timing buckets:

- candidate selection
- I/O request construction
- I/O submission
- device/kernel waiting
- completion handling
- cached-node compute
- returned-page parsing
- visited filtering
- PQ distance computation
- queue update
- termination check

## Phase 2: Neighbor Survival Funnel

For every search iteration, record how many neighbors survive each stage:

| Stage | Meaning |
| --- | --- |
| Raw neighbors | All IDs read from expanded neighbor lists |
| Unique neighbors | Duplicates removed within the iteration |
| Unvisited neighbors | IDs not already in the query visited set |
| Pass filter/dummy check | IDs not removed by filter or dummy-node rules |
| PQ distance computed | IDs that actually receive approximate distance |
| Enter top-L queue | IDs accepted into the search candidate queue |
| Eventually expanded | IDs later selected as frontier nodes |
| Final top-K | IDs contributing to returned results |

This phase answers whether SSD-side visited filtering or SSD-side PQ filtering
has enough pruning power to matter.

Required code changes:

- Change `NeighborPriorityQueue::insert()` in `include/neighbor.h` to return an
  insertion result instead of `void`, or add a side-channel helper that reports
  whether the candidate was inserted, duplicated, or dropped by capacity.
- Track candidate insertion and later expansion in
  `PQFlashIndex::cached_beam_search()`.
- After final result selection, mark which candidates contributed to top-K.
- Add funnel summary logic to `scripts/locality/summarize_locality_trace.py`.

## Phase 3: I/O Class Breakdown

Separate three traffic classes:

| Class | Source |
| --- | --- |
| NBR reads | Disk sectors containing node vectors and neighbor lists |
| Host DRAM PQ accesses | In-memory compressed PQ codes used by `compute_dists` |
| Full-vector reads | Reorder reads when `use_reorder_data` is enabled |

Metrics for each class:

- requests per query
- pages per query
- bytes per query
- latency per query
- repeated page ratio

Required code changes:

- Count NBR reads when `frontier_read_reqs` is built in
  `src/pq_flash_index.cpp`.
- Count PQ bytes and PQ page IDs inside the `compute_dists` lambda.
- Count full-vector reads in the reorder block of `cached_beam_search()`.
- Add class-specific CSV columns in `apps/search_disk_index.cpp`.

## Phase 4: Page Reuse and Dynamic Cache Feasibility

Record raw page accesses within sampled queries:

```text
query_id,iteration,access_seq,io_type,page_id,node_id
```

`io_type` should include:

- `NBR`
- `PQ`
- `FULL_VECTOR`

Metrics:

- probability that a page is accessed again
- reuse distance measured in search iterations
- reuse distance measured in distinct page accesses
- fraction of pages reused within the next 1, 2, 4, and 8 iterations
- oracle LRU cache hit-rate curve

This phase answers whether SSD DRAM dynamic caching is worth pursuing. If pages
read from NAND are almost never reused in later iterations, dynamic caching is
unlikely to help.

Required code changes:

- Add optional page trace output, likely `--trace_page_csv`, in
  `apps/search_disk_index.cpp`.
- Add page access vectors to `QueryTrace`, or write page trace rows separately
  to avoid making iteration trace rows too large.
- Record NBR page accesses using `get_node_sector()`.
- Record PQ page accesses using `pq_page = node_id * _n_chunks / 4096`.
- Record full-vector page accesses in the reorder block.
- Extend `scripts/locality/summarize_locality_trace.py` with reuse-distance and
  LRU simulation summaries.

## Phase 5: NBR + PQ Page Fan-Out

For each expanded node, evaluate how expensive SSD-side PQ distance computation
would be if PQ codes lived on NAND.

Metrics:

- neighbor count per expanded node
- unique PQ pages touched by those neighbors
- PQ page fan-out per expanded node
- PQ page overlap between expanded nodes
- PQ page reuse distance
- PQ cache hit-rate curve
- oracle upper bound for NBR+PQ co-location
- PQ replication factor needed for 25%, 50%, 75%, and 90% read reduction

Required code changes:

- In the neighbor-processing loops of `PQFlashIndex::cached_beam_search()`,
  compute each neighbor's PQ page from `_n_chunks`.
- Output per-expanded-node fan-out rows.
- Keep actual disk layout unchanged during this phase; first analyze the oracle
  limits offline.
- Only later, if justified, modify `src/disk_utils.cpp` and
  `apps/utils/create_disk_layout.cpp` for real NBR+PQ co-location.

## Phase 6: Architecture Simulation

After Phases 1-5, choose the architecture based on measured bottlenecks.

Candidate designs:

| Design | Required evidence |
| --- | --- |
| SSD-side visited filtering | Large drop from raw/unique neighbors to unvisited neighbors |
| SSD-side PQ filtering | Large drop from unvisited neighbors to top-L candidates |
| SSD DRAM dynamic NBR cache | Meaningful cross-iteration NBR page reuse |
| NBR+PQ co-location | Low PQ fan-out or tolerable PQ replication factor |

Do not simulate all designs blindly. Simulate the design whose target cost is
both large and exposed on the critical path.

## Main Files To Modify

| File | Planned role |
| --- | --- |
| `include/percentile_stats.h` | Trace data structures |
| `include/pq_flash_index.h` | Search API signatures for trace options |
| `src/pq_flash_index.cpp` | Main search-loop instrumentation |
| `apps/search_disk_index.cpp` | CLI options and CSV writers |
| `include/neighbor.h` | Candidate queue insertion outcome |
| `src/linux_aligned_file_reader.cpp` | Linux AIO submission/wait timing |
| `scripts/locality/summarize_locality_trace.py` | Offline summaries |
| `scripts/locality/run_block_shuffle_cache_locality.sh` | Experiment runner |
| `src/disk_utils.cpp` | Later layout changes only if co-location is justified |
| `apps/utils/create_disk_layout.cpp` | Later layout CLI changes only if needed |

## Expected Outputs

Raw CSVs:

- `iteration_trace.csv`
- `page_trace.csv`
- `neighbor_funnel_trace.csv`
- `pq_fanout_trace.csv`

Summary CSVs:

- `critical_path_by_lifecycle.csv`
- `neighbor_survival_funnel.csv`
- `io_class_breakdown.csv`
- `page_reuse_distance.csv`
- `lru_oracle_hit_rate.csv`
- `pq_page_fanout.csv`
- `architecture_decision_summary.csv`

## Initial Rule

Study 1 is a characterization study. Keep it focused on measurement and
evidence. Avoid changing DiskANN search semantics unless the change is explicitly
part of an isolated experiment mode.
