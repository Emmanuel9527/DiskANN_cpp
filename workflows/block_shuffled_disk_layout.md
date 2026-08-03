# Block-Shuffled Disk Layout Experiment

This document records the experimental changes in this fork and gives a
reproducible comparison between the original DiskANN disk layout and the
block-shuffled layout.

## What was changed

The implementation has two independent experimental dimensions:

1. **Block-shuffled disk layout**: graph-near nodes are renumbered and packed
   into the same 4 KB sector where possible.
2. **Sector-candidate search**: after reading a frontier node's sector, search
   also expands the other valid nodes already available in that sector.

The main implementation locations are:

- `src/disk_utils.cpp`
  - `compute_block_shuffled_order`: computes the graph-local block assignment.
  - `create_disk_layout_block_shuffling`: rewrites node order, graph neighbor
    IDs, optional reorder vectors, and PQ codes.
- `src/pq_flash_index.cpp`
  - `PQFlashIndex::cached_beam_search`: implements sector-aware expansion under
    `use_sector_candidates`.
- `apps/utils/create_disk_layout.cpp`
  - exposes `default` and `block_shuffle` layout modes.
- `apps/search_disk_index.cpp`
  - exposes `--use_sector_candidates` and `--result_new_to_old_map`.

Relevant Git commits on branch `cpp_bs` are:

- `5d82497`: initial block-shuffling implementation.
- `92161ae`: search/build integration.
- `13cbe26`: PQ-code remapping and recall ID mapping.
- `075b7f5`: sector-candidate expansion and initial documentation.

## Experimental matrix

Run all three configurations to separate the effects of physical layout and
search behavior:

| Run | Disk layout | Sector candidates | Purpose |
|---|---|---:|---|
| A | Default | Off | Original DiskANN baseline |
| B | Block shuffled | Off | Effect of layout alone |
| C | Block shuffled | On | Layout plus sector-aware search |

Do not enable sector candidates for the default layout as a primary result:
consecutive IDs in the original layout were not deliberately grouped by graph
locality, so that comparison answers a different question.

## Assumptions

The commands below use:

- Linux or the WSL Linux filesystem (not `/mnt/c` or `/mnt/d` for measured I/O).
- Float vectors and L2 distance.
- No disk-PQ compression (`--PQ_disk_bytes 0`).
- An existing ground-truth file.

Replace the paths and memory budgets for the dataset and machine. Keep all
search parameters identical across A, B, and C.

## 1. Build the programs

```bash
cd ~/DiskANN
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target build_disk_index search_disk_index create_disk_layout -j
```

## 2. Define experiment parameters

```bash
cd ~/DiskANN

DATA_TYPE=float
DIST_FN=l2
BASE=~/DiskANN/data/base.fbin
QUERY=~/DiskANN/data/query.fbin
GT=~/DiskANN/data/gt.bin

PREFIX_DEFAULT=~/DiskANN/index/default
PREFIX_BLOCK=~/DiskANN/index/block
RESULT_DIR=~/DiskANN/results

R=64
L_BUILD=100
SEARCH_GB=1
BUILD_GB=8
K=10
L_VALUES="20 30 40 50 60 100"
W=4
T=8

mkdir -p ~/DiskANN/index "${RESULT_DIR}"
```

## 3. Build the original index and retain the Vamana graph

`--keep_vamana_graph` is required because the same graph is reused to construct
the block-shuffled disk layout.

```bash
build/apps/build_disk_index \
  --data_type "${DATA_TYPE}" \
  --dist_fn "${DIST_FN}" \
  --data_path "${BASE}" \
  --index_path_prefix "${PREFIX_DEFAULT}" \
  -R "${R}" \
  -L "${L_BUILD}" \
  -B "${SEARCH_GB}" \
  -M "${BUILD_GB}" \
  -T "${T}" \
  --PQ_disk_bytes 0 \
  --keep_vamana_graph
```

This produces the default disk index as well as the files needed for the
second layout, including:

```text
${PREFIX_DEFAULT}_disk.index
${PREFIX_DEFAULT}_mem.index
${PREFIX_DEFAULT}_pq_pivots.bin
${PREFIX_DEFAULT}_pq_compressed.bin
```

## 4. Build the block-shuffled layout from exactly the same graph

```bash
build/apps/utils/create_disk_layout \
  "${DATA_TYPE}" \
  "${BASE}" \
  "${PREFIX_DEFAULT}_mem.index" \
  "${PREFIX_BLOCK}_disk.index" \
  block_shuffle \
  5 \
  0.0001 \
  reorder_pq
```

`reorder_pq` rewrites the PQ codes from the default prefix into
`${PREFIX_BLOCK}_pq_compressed.bin` using the new node IDs. PQ pivots do not
depend on node order, but search resolves them through the block prefix, so copy
the same pivot table:

```bash
cp "${PREFIX_DEFAULT}_pq_pivots.bin" "${PREFIX_BLOCK}_pq_pivots.bin"
```

The layout command also creates:

```text
${PREFIX_BLOCK}_disk.index_block_shuffle_old_to_new.bin
${PREFIX_BLOCK}_disk.index_block_shuffle_new_to_old.bin
```

The new-to-old map is required when recall is evaluated against ground truth in
the original ID space.

## 5. Run A: original layout and original search

```bash
build/apps/search_disk_index \
  --data_type "${DATA_TYPE}" \
  --dist_fn "${DIST_FN}" \
  --index_path_prefix "${PREFIX_DEFAULT}" \
  --result_path "${RESULT_DIR}/A_default" \
  --query_file "${QUERY}" \
  --gt_file "${GT}" \
  -K "${K}" \
  -L ${L_VALUES} \
  -W "${W}" \
  -T "${T}" \
  --num_nodes_to_cache 0 \
  | tee "${RESULT_DIR}/A_default.log"
```

## 6. Run B: block-shuffled layout and original search

Do not pass `--use_sector_candidates` in this run.

```bash
build/apps/search_disk_index \
  --data_type "${DATA_TYPE}" \
  --dist_fn "${DIST_FN}" \
  --index_path_prefix "${PREFIX_BLOCK}" \
  --result_path "${RESULT_DIR}/B_block_layout_only" \
  --query_file "${QUERY}" \
  --gt_file "${GT}" \
  -K "${K}" \
  -L ${L_VALUES} \
  -W "${W}" \
  -T "${T}" \
  --num_nodes_to_cache 0 \
  --result_new_to_old_map "${PREFIX_BLOCK}_disk.index_block_shuffle_new_to_old.bin" \
  | tee "${RESULT_DIR}/B_block_layout_only.log"
```

## 7. Run C: block-shuffled layout and sector-candidate search

This is the full modified version. The only search-mode difference from Run B
is `--use_sector_candidates`.

```bash
build/apps/search_disk_index \
  --data_type "${DATA_TYPE}" \
  --dist_fn "${DIST_FN}" \
  --index_path_prefix "${PREFIX_BLOCK}" \
  --result_path "${RESULT_DIR}/C_block_sector_candidates" \
  --query_file "${QUERY}" \
  --gt_file "${GT}" \
  -K "${K}" \
  -L ${L_VALUES} \
  -W "${W}" \
  -T "${T}" \
  --num_nodes_to_cache 0 \
  --result_new_to_old_map "${PREFIX_BLOCK}_disk.index_block_shuffle_new_to_old.bin" \
  --use_sector_candidates \
  | tee "${RESULT_DIR}/C_block_sector_candidates.log"
```

## Flags introduced or required by this experiment

| Flag or argument | Stage | Meaning |
|---|---|---|
| `--keep_vamana_graph` | build | Retains `_mem.index` for constructing both layouts from the same graph. |
| `default` | layout | Writes nodes in the original order. |
| `block_shuffle` | layout | Groups graph-near nodes into sector-sized blocks and renumbers IDs. |
| `max_iterations` | layout | Maximum block-assignment refinement rounds. |
| `gain_threshold` | layout | Stops when locality-ratio improvement falls below this value. |
| `reorder_pq` | layout | Reorders in-memory PQ codes to match the new IDs. |
| `--result_new_to_old_map` | search | Converts returned IDs back to original IDs for output and recall. |
| `--use_sector_candidates` | search | Expands other valid nodes obtained from the same sector read. |
| `--trace_stats_csv` | search | Enables opt-in per-query, per-iteration locality tracing and writes raw rows to CSV. |
| `--trace_sample_rate` | search | Traces every Nth query when `--trace_stats_csv` is set. |
| `--trace_max_queries` | search | Caps the number of sampled queries traced per search run. |
| `--trace_run_label` | search | Adds a run label to every trace CSV row for later grouping. |

## Reproducing the four locality observations

The trace mode is disabled unless `--trace_stats_csv` is provided. When enabled,
the search path records one aggregate row per sampled query iteration without
storing node-id lists. Each row includes lifecycle bin, iteration time, IO wait,
cache hits, uncached nodes, issued reads, unique sectors, useful payload bytes,
and neighbor-utilization counters.

The helper below runs the default layout, block-shuffled layout, and
block-shuffled layout with sector candidates across cache sizes:

```bash
BASE=/path/to/sift1b/base.fbin \
QUERY=/path/to/sift1b/query.fbin \
GT=/path/to/sift1b/gt.bin \
BUILD_DIR=build \
CACHE_SIZES="1000 5000 10000 25000 50000" \
TRACE_SAMPLE_RATE=10 \
TRACE_MAX_QUERIES=1000 \
scripts/locality/run_block_shuffle_cache_locality.sh
```

The raw trace is written to:

```text
results/cache_locality/iteration_trace.csv
```

The summarizer produces four CSV files corresponding to the meeting slides:

```text
results/cache_locality/summaries/experiment1_iteration_io_by_lifecycle.csv
results/cache_locality/summaries/experiment2_overfetch_by_lifecycle.csv
results/cache_locality/summaries/experiment3_uncached_reads_by_lifecycle.csv
results/cache_locality/summaries/experiment4_neighbor_utilization_by_lifecycle.csv
```

These summaries group by run label, `L`, beamwidth, cache size, sector-candidate
mode, and normalized lifecycle bin. Use the raw CSV if you want to plot the same
metrics with a different aggregation.

## Fair-comparison checklist

- Use the same `_mem.index` for both layouts.
- Keep `K`, `L`, `W`, thread count, query set, and ground truth identical.
- Start with `--num_nodes_to_cache 0`; caching can hide disk-layout effects.
- Run on a native Linux filesystem and an SSD when measuring I/O behavior.
- Use separate output prefixes so one run does not overwrite another.
- Compare A vs. B for layout effects and B vs. C for sector-expansion effects.
- Confirm that Run B and C load the new-to-old map before trusting recall.

## Current limitation

The recipe intentionally uses `--PQ_disk_bytes 0`. If disk-resident PQ is
enabled, its auxiliary files must also be made consistent with the renumbered
layout; that path should be validated separately before using it for reported
results.
