#!/usr/bin/env bash
set -euo pipefail

# Run the same sampled SIFT1M queries for each requested L and beamwidth, then
# summarize actual node reads by query iteration and logical sector.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-/home/emmanuel/projects/data/sift1m}"
INDEX_DIR="${INDEX_DIR:-/home/emmanuel/projects/data/sift1m_diskann_indexes}"
INDEX_PREFIX="${INDEX_PREFIX:-${INDEX_DIR}/sift1m_l2_R64_L100_pq0_block_shuffle}"
SEARCH_BIN="${SEARCH_BIN:-${ROOT_DIR}/build/apps/search_disk_index}"
RESULT_DIR="${RESULT_DIR:-${ROOT_DIR}/results/locality_sift1m_sector_batch_$(date +%Y%m%d_%H%M%S)}"
TRACE_MAX_QUERIES="${TRACE_MAX_QUERIES:-1000}"
THREADS="${THREADS:-1}"

QUERY_FILE="${QUERY_FILE:-${DATA_DIR}/sift_query.fbin}"
GT_FILE="${GT_FILE:-${DATA_DIR}/sift_groundtruth.bin}"
MAP_FILE="${MAP_FILE:-${INDEX_PREFIX}_disk.index_block_shuffle_new_to_old.bin}"
ACCESS_CSV="${RESULT_DIR}/sift1m_block_shuffle_access.csv"
STATS_CSV="${RESULT_DIR}/sift1m_block_shuffle_iterations.csv"

for required in "${SEARCH_BIN}" "${QUERY_FILE}" "${GT_FILE}" \
                "${INDEX_PREFIX}_disk.index" "${INDEX_PREFIX}_pq_compressed.bin" \
                "${INDEX_PREFIX}_pq_pivots.bin" "${MAP_FILE}"; do
  if [[ ! -e "${required}" ]]; then
    echo "Missing required file: ${required}" >&2
    exit 1
  fi
done

mkdir -p "${RESULT_DIR}"
echo "Results: ${RESULT_DIR}"
echo "Tracing the first ${TRACE_MAX_QUERIES} queries per L/W configuration."

for W in 8 16 32 64; do
  echo "Running SIFT1M block-shuffle search: L=20,60,120 W=${W}"
  "${SEARCH_BIN}" \
    --data_type float --dist_fn l2 \
    --index_path_prefix "${INDEX_PREFIX}" \
    --result_path "${RESULT_DIR}/search_w${W}" \
    --query_file "${QUERY_FILE}" \
    --gt_file "${GT_FILE}" \
    -K 10 -W "${W}" -T "${THREADS}" --num_nodes_to_cache 0 \
    -L 20 -L 60 -L 120 \
    --result_new_to_old_map "${MAP_FILE}" \
    --trace_stats_csv "${STATS_CSV}" \
    --trace_access_csv "${ACCESS_CSV}" \
    --trace_sample_rate 1 \
    --trace_max_queries "${TRACE_MAX_QUERIES}" \
    --trace_run_label "sift1m_block_shuffle_w${W}" \
    | tee "${RESULT_DIR}/search_w${W}.log"
done

python3 "${ROOT_DIR}/scripts/locality/summarize_sector_batch_trace.py" \
  --access_csv "${ACCESS_CSV}" \
  --iteration_csv "${STATS_CSV}" \
  --out_dir "${RESULT_DIR}"

echo "Done. Batch metrics: ${RESULT_DIR}/sector_batch_metrics.csv"
echo "Done. L/W summaries: ${RESULT_DIR}/sector_locality_summary.csv"
