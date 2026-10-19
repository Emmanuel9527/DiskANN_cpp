#!/usr/bin/env bash
set -euo pipefail

# Use the first fixed query sample for each L/W pair. This keeps the 100M trace
# run practical while preserving the same query IDs across all configurations.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-/home/emmanuel/projects/data/sift100m}"
INDEX_DIR="${INDEX_DIR:-/home/emmanuel/projects/data/sift100m_diskann_indexes}"
INDEX_PREFIX="${INDEX_PREFIX:-${INDEX_DIR}/sift100m_l2_R64_L100_pq0_block_shuffle}"
SEARCH_BIN="${SEARCH_BIN:-${ROOT_DIR}/build/apps/search_disk_index}"
RESULT_DIR="${RESULT_DIR:-${ROOT_DIR}/results/locality_sift100m_sector_batch_$(date +%Y%m%d_%H%M%S)}"
QUERY_COUNT="${QUERY_COUNT:-1000}"
THREADS="${THREADS:-1}"

FULL_QUERY_FILE="${FULL_QUERY_FILE:-${DATA_DIR}/bigann_query.u8bin}"
FULL_GT_FILE="${FULL_GT_FILE:-${DATA_DIR}/idx_100M.bin}"
MAP_FILE="${MAP_FILE:-${INDEX_PREFIX}_disk.index_block_shuffle_new_to_old.bin}"
QUERY_FILE="${RESULT_DIR}/bigann_query_first${QUERY_COUNT}.u8bin"
GT_FILE="${RESULT_DIR}/idx_100M_first${QUERY_COUNT}.bin"
ACCESS_CSV="${RESULT_DIR}/sift100m_block_shuffle_access.csv"
STATS_CSV="${RESULT_DIR}/sift100m_block_shuffle_iterations.csv"

for required in "${SEARCH_BIN}" "${FULL_QUERY_FILE}" "${FULL_GT_FILE}" \
                "${INDEX_PREFIX}_disk.index" "${INDEX_PREFIX}_pq_compressed.bin" \
                "${INDEX_PREFIX}_pq_pivots.bin" "${MAP_FILE}"; do
  if [[ ! -e "${required}" ]]; then
    echo "Missing required file: ${required}" >&2
    exit 1
  fi
done

mkdir -p "${RESULT_DIR}"
python3 "${ROOT_DIR}/scripts/locality/slice_bin_prefix.py" \
  --input "${FULL_QUERY_FILE}" --output "${QUERY_FILE}" \
  --count "${QUERY_COUNT}" --dtype uint8
python3 "${ROOT_DIR}/scripts/locality/slice_bin_prefix.py" \
  --input "${FULL_GT_FILE}" --output "${GT_FILE}" \
  --count "${QUERY_COUNT}" --dtype uint32

echo "Results: ${RESULT_DIR}"
echo "Searching and tracing the same first ${QUERY_COUNT} SIFT100M queries for every L/W configuration."

for W in 8 16 32 64; do
  echo "Running SIFT100M block-shuffle search: L=20,60,120 W=${W}"
  "${SEARCH_BIN}" \
    --data_type uint8 --dist_fn l2 \
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
    --trace_max_queries "${QUERY_COUNT}" \
    --trace_run_label "sift100m_block_shuffle_w${W}" \
    | tee "${RESULT_DIR}/search_w${W}.log"
done

python3 "${ROOT_DIR}/scripts/locality/summarize_sector_batch_trace.py" \
  --access_csv "${ACCESS_CSV}" \
  --iteration_csv "${STATS_CSV}" \
  --out_dir "${RESULT_DIR}"

echo "Done. Batch metrics: ${RESULT_DIR}/sector_batch_metrics.csv"
echo "Done. L/W summaries: ${RESULT_DIR}/sector_locality_summary.csv"
