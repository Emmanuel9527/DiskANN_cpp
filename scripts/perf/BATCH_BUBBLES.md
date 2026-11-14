# Real-SSD DiskANN batch observation

## Configured SIFT100M run (tmpfs output)

```bash
bash scripts/perf/run_sift100m_batch_bubbles.sh --check
bash scripts/perf/run_sift100m_batch_bubbles.sh
```

This preset uses the existing uint8 SIFT100M block-shuffle index in
`/home/emmanuel/projects/data/sift100m_diskann_indexes`, queries from
`/home/emmanuel/projects/data/sift100m/bigann_query.u8bin`, and ground truth
`idx_100M.bin` in the same data directory. It slices the first 1,000 queries
and matching ground-truth rows into a unique `/dev/shm/diskann_sift100m_bubbles_*`
directory before search. All run outputs go into its `results` subdirectory.
The 100M index stays on the real SSD; only query slices and outputs go to tmpfs.
Defaults: T=1/2/4/8/16, W=8, L=40, K=10, cache=0, three repeats, plain/traced.

The launcher verifies tmpfs and requires at least 4 GiB free tmpfs and 24 GiB
MemAvailable. These are startup guards, not a peak-memory guarantee, especially
if QUERY_COUNT or the sweep is enlarged. Tmpfs can be swapped under memory
pressure, so keep adequate RAM headroom. `--check` only reads metadata; normal
launch checks writeability with mktemp and never falls back to disk. Sandboxed
terminals may expose `/dev/shm` as read-only; run from the normal host terminal
in that case. No remount or sudo is needed by the script.

Outputs are volatile. After the entire sweep finishes, copy the printed run
directory to persistent storage. Override `RAM_ROOT` only with another existing
tmpfs mount. For a short smoke run use `THREADS=1 REPEATS=1 QUERY_COUNT=100`.

Build `search_disk_index` and run on an index resident on the real target SSD:

```bash
INDEX_PREFIX=/path/to/index_prefix \
QUERY_FILE=/path/to/queries.fbin GT_FILE=/path/to/groundtruth.bin \
RESULT_DIR=/tmp/bubbles-run1 \
bash scripts/perf/run_batch_bubble_sweep.sh
```

Start with W=8, T=1/2/4/8/16, L=40, cache=0 (defaults). Then vary
`WIDTHS="4 8 16"` or `CACHE_NODES`. Keep the query set, index, L and K fixed.
There must be many more queries than workers. The OpenMP dynamic loop executes
one query per worker at a time: query count is the amount of work, not a second
independent concurrency control. This is a closed-loop throughput experiment,
not an externally rate-controlled query service.

The runner performs plain and fully traced runs, three repeats by default.
Compare QPS/latency/recall from the logs to assess trace perturbation. The existing
trace also collects access information; its overhead can be material. Results
are written after search, but memory allocation and clock reads still cost time.
Use a modest query set for initial traces. For careful comparisons, stabilize
device temperature/warm state and repeat in reversed or randomized configuration
order; the script's fixed plain-before-traced order can confound warmup and
instrumentation overhead. Do not clear caches or reinitialize a device blindly.

## Timestamp semantics

CSV adds worker_id, iteration_begin_ns, iteration_end_ns, read_begin_ns,
read_end_ns. All timestamps use the process-wide steady clock. No-read iterations
have zero read timestamps. read_begin/end enclose the synchronous frontier
reader call, including submission, waiting and return overhead; they are NOT
individual device issue/completion timestamps. Use fresh CSV files, since the
previous schema cannot be appended to safely. Do not combine different runs on
one absolute timeline.

The analyzer measures the union of frontier read-call intervals across all
queries. Its window is first read begin through last read end, excluding query
startup/final processing outside that interval but including ramp-up/drain.
`no_search_read_call_fraction` is time with no search read call active, NOT SSD
idle utilization. `mean_concurrent_search_read_calls` counts calls, NOT requests
or device QD. `within_query_gap_mean_us` includes computation, cached-only
iterations and scheduling between consecutive read calls in the same query.

All queries must be traced (sample_rate=1, max_queries=0). Sampling would turn
unobserved work into false gaps. The analyzer requires an explicit assertion of
complete tracing because it cannot infer missing queries from the CSV. Use the
synchronous Linux reader, disable full-vector reranking, and exclude unrelated
device traffic for interpretation. This trace does not cover reranking or other
I/O paths. It does not measure per-request completion spread within a batch.

## Interpretation and next measurement

Compare per-query gaps against the global no-read-call fraction as T increases.
If per-query gaps persist while the global fraction decreases and QPS rises,
other queries are covering the application-level gaps. If QPS stops rising,
that alone does not distinguish CPU contention from device saturation.

For actual batch drain and device QD, capture block request issue/complete events
on the target device, match requests (including splits/merges), and align their
clock with the application trace. Plot device QD with per-worker read-call bars.
Application intervals can overcount pending I/O after completion and before the
reader returns. Even block-device QD does not expose physical NAND utilization.
Neither measurement alone proves that a semantics-preserving DiskANN change
can remove the observed gaps.
