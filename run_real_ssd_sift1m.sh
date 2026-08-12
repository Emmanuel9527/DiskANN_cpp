#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
BUILD_DIR="${BUILD_DIR:-${ROOT_DIR}/build}"
RESULT_DIR="${RESULT_DIR:-${ROOT_DIR}/results/real_ssd}"

INDEX_DIR="${INDEX_DIR:-/home/emmanuel/projects/data/sift1m_diskann_indexes}"
INDEX_VARIANT="${INDEX_VARIANT:-block_shuffle}"
PREFIX_STEM="${PREFIX_STEM:-sift1m_l2_R64_L100_pq0}"
INDEX_PREFIX="${INDEX_PREFIX:-${INDEX_DIR}/${PREFIX_STEM}_${INDEX_VARIANT}}"

QUERY_FILE="${QUERY_FILE:-/home/emmanuel/projects/data/sift1m/sift_query.fbin}"
GT_FILE="${GT_FILE:-/home/emmanuel/projects/data/sift1m/sift_groundtruth.bin}"
DATA_TYPE="${DATA_TYPE:-float}"
DIST_FN="${DIST_FN:-l2}"
K="${K:-10}"
L_VALUES="${L_VALUES:-40}"
W="${W:-16}"
T="${T:-1}"
NUM_NODES_TO_CACHE="${NUM_NODES_TO_CACHE:-0}"
USE_SECTOR_CANDIDATES="${USE_SECTOR_CANDIDATES:-0}"
RUN_LABEL="${RUN_LABEL:-${INDEX_VARIANT}_L${L_VALUES// /-}_W${W}_T${T}_cache${NUM_NODES_TO_CACHE}}"

SEARCH_BIN="${SEARCH_BIN:-${BUILD_DIR}/apps/search_disk_index}"
RESULT_PREFIX="${RESULT_PREFIX:-${RESULT_DIR}/${RUN_LABEL}}"
LOG_FILE="${LOG_FILE:-${RESULT_DIR}/${RUN_LABEL}.log}"
PERF_TABLE_FILE="${PERF_TABLE_FILE:-${RESULT_DIR}/${RUN_LABEL}.performance_table.txt}"

require_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    echo "Missing required file: ${path}" >&2
    exit 1
  fi
}

require_exe() {
  local path="$1"
  if [[ ! -x "${path}" ]]; then
    echo "Missing executable: ${path}" >&2
    echo "Build DiskANN first, e.g. cmake --build build --target search_disk_index -j" >&2
    exit 1
  fi
}

extract_performance_table() {
  local log_file="$1"
  local out_file="$2"

  awk '
    /[[:space:]]L[[:space:]]+Beamwidth[[:space:]]+QPS[[:space:]]+Mean Latency/ {
      capture = 1
      rows = 0
    }
    capture {
      if ($0 ~ /[[:space:]]L[[:space:]]+Beamwidth[[:space:]]+QPS[[:space:]]+Mean Latency/ ||
          $0 ~ /^=+/) {
        print
        next
      }
      if ($1 ~ /^[0-9]+$/) {
        print
        rows++
        next
      }
      if (rows > 0)
        exit
    }
  ' "${log_file}" > "${out_file}"
}

require_exe "${SEARCH_BIN}"
require_file "${QUERY_FILE}"
require_file "${GT_FILE}"
require_file "${INDEX_PREFIX}_disk.index"
require_file "${INDEX_PREFIX}_pq_pivots.bin"
require_file "${INDEX_PREFIX}_pq_compressed.bin"

mkdir -p "${RESULT_DIR}"

SEARCH_ARGS=(
  --data_type "${DATA_TYPE}"
  --dist_fn "${DIST_FN}"
  --index_path_prefix "${INDEX_PREFIX}"
  --result_path "${RESULT_PREFIX}"
  --query_file "${QUERY_FILE}"
  --gt_file "${GT_FILE}"
  -K "${K}"
  -W "${W}"
  -T "${T}"
  --num_nodes_to_cache "${NUM_NODES_TO_CACHE}"
)

for l_value in ${L_VALUES}; do
  SEARCH_ARGS+=(-L "${l_value}")
done

MAP_FILE="${INDEX_PREFIX}_disk.index_block_shuffle_new_to_old.bin"
if [[ -f "${MAP_FILE}" ]]; then
  SEARCH_ARGS+=(--result_new_to_old_map "${MAP_FILE}")
fi

if [[ "${USE_SECTOR_CANDIDATES}" == "1" ]]; then
  SEARCH_ARGS+=(--use_sector_candidates)
fi

"${SEARCH_BIN}" "${SEARCH_ARGS[@]}" | tee "${LOG_FILE}"

extract_performance_table "${LOG_FILE}" "${PERF_TABLE_FILE}"

echo
echo "DiskANN performance table:"
if [[ -s "${PERF_TABLE_FILE}" ]]; then
  cat "${PERF_TABLE_FILE}"
else
  echo "  Could not find the DiskANN performance table in ${LOG_FILE}"
fi

echo
echo "Saved:"
echo "  ${LOG_FILE}"
echo "  ${PERF_TABLE_FILE}"
