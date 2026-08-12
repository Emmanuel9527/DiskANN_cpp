#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
BUILD_DIR="${BUILD_DIR:-${ROOT_DIR}/build}"
RESULT_DIR="${RESULT_DIR:-${ROOT_DIR}/results/nvmevirt_mqsim}"

NVMEV_MOUNT="${NVMEV_MOUNT:-/mnt/nvmevirt}"
INDEX_DIR="${INDEX_DIR:-${NVMEV_MOUNT}/sift1m_diskann_index}"
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
TRACE_SAMPLE_RATE="${TRACE_SAMPLE_RATE:-10}"
TRACE_MAX_QUERIES="${TRACE_MAX_QUERIES:-1000}"
RUN_LABEL="${RUN_LABEL:-${INDEX_VARIANT}_L${L_VALUES// /-}_W${W}_T${T}_cache${NUM_NODES_TO_CACHE}}"

SEARCH_BIN="${SEARCH_BIN:-${BUILD_DIR}/apps/search_disk_index}"
IPC_PROC="${IPC_PROC:-/proc/nvmev/mqsim_ipc}"
RESULT_PREFIX="${RESULT_PREFIX:-${RESULT_DIR}/${RUN_LABEL}}"
TRACE_CSV="${TRACE_CSV:-${RESULT_DIR}/iteration_trace.csv}"
LOG_FILE="${LOG_FILE:-${RESULT_DIR}/${RUN_LABEL}.log}"
PERF_TABLE_FILE="${PERF_TABLE_FILE:-${RESULT_DIR}/${RUN_LABEL}.performance_table.txt}"
BEFORE_COUNTERS="${BEFORE_COUNTERS:-${RESULT_DIR}/${RUN_LABEL}.mqsim_before.txt}"
AFTER_COUNTERS="${AFTER_COUNTERS:-${RESULT_DIR}/${RUN_LABEL}.mqsim_after.txt}"
COUNTER_DIFF="${COUNTER_DIFF:-${RESULT_DIR}/${RUN_LABEL}.mqsim_diff.txt}"

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

read_counter() {
  local file="$1"
  local key="$2"
  awk -v key="${key}:" '$1 == key { print $2 }' "${file}"
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

echo "DiskANN NVMeVirt/MQSim run"
echo "  index_prefix=${INDEX_PREFIX}"
echo "  query_file=${QUERY_FILE}"
echo "  gt_file=${GT_FILE}"
echo "  result_prefix=${RESULT_PREFIX}"
echo "  log_file=${LOG_FILE}"

require_exe "${SEARCH_BIN}"
require_file "${QUERY_FILE}"
require_file "${GT_FILE}"
require_file "${INDEX_PREFIX}_disk.index"
require_file "${INDEX_PREFIX}_pq_pivots.bin"
require_file "${INDEX_PREFIX}_pq_compressed.bin"

if [[ ! -d "${NVMEV_MOUNT}" ]]; then
  echo "Missing NVMeVirt mount directory: ${NVMEV_MOUNT}" >&2
  exit 1
fi

if ! findmnt -T "${NVMEV_MOUNT}" >/dev/null; then
  echo "${NVMEV_MOUNT} is not mounted" >&2
  exit 1
fi

if [[ ! -r "${IPC_PROC}" ]]; then
  echo "Missing ${IPC_PROC}; is nvmev loaded with mqsim_ipc_enable=1?" >&2
  exit 1
fi

if ! awk '$1 == "daemon_connected:" && $2 == "1" { found = 1 } END { exit found ? 0 : 1 }' "${IPC_PROC}"; then
  echo "MQSim daemon is not connected. Start MQSimIPCDaemon before running this script." >&2
  cat "${IPC_PROC}" >&2
  exit 1
fi

mkdir -p "${RESULT_DIR}"
cat "${IPC_PROC}" > "${BEFORE_COUNTERS}"

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
  --trace_stats_csv "${TRACE_CSV}"
  --trace_sample_rate "${TRACE_SAMPLE_RATE}"
  --trace_max_queries "${TRACE_MAX_QUERIES}"
  --trace_run_label "${RUN_LABEL}"
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

echo
echo "Before counters:"
cat "${BEFORE_COUNTERS}"
echo
echo "Running search_disk_index..."

"${SEARCH_BIN}" "${SEARCH_ARGS[@]}" | tee "${LOG_FILE}"

extract_performance_table "${LOG_FILE}" "${PERF_TABLE_FILE}"
cat "${IPC_PROC}" > "${AFTER_COUNTERS}"
diff -u "${BEFORE_COUNTERS}" "${AFTER_COUNTERS}" > "${COUNTER_DIFF}" || true

before_req="$(read_counter "${BEFORE_COUNTERS}" requests || echo 0)"
after_req="$(read_counter "${AFTER_COUNTERS}" requests || echo 0)"
before_rep="$(read_counter "${BEFORE_COUNTERS}" replies || echo 0)"
after_rep="$(read_counter "${AFTER_COUNTERS}" replies || echo 0)"
before_fallbacks="$(read_counter "${BEFORE_COUNTERS}" fallbacks || echo 0)"
after_fallbacks="$(read_counter "${AFTER_COUNTERS}" fallbacks || echo 0)"
before_send_errors="$(read_counter "${BEFORE_COUNTERS}" send_errors || echo 0)"
after_send_errors="$(read_counter "${AFTER_COUNTERS}" send_errors || echo 0)"
before_ring_full="$(read_counter "${BEFORE_COUNTERS}" req_ring_full || echo 0)"
after_ring_full="$(read_counter "${AFTER_COUNTERS}" req_ring_full || echo 0)"
after_pending="$(read_counter "${AFTER_COUNTERS}" pending || echo unknown)"
after_max_pending="$(read_counter "${AFTER_COUNTERS}" max_pending || echo unknown)"
after_late="$(read_counter "${AFTER_COUNTERS}" late_replies || echo unknown)"

echo
echo "DiskANN performance table:"
if [[ -s "${PERF_TABLE_FILE}" ]]; then
  cat "${PERF_TABLE_FILE}"
else
  echo "  Could not find the DiskANN performance table in ${LOG_FILE}"
fi

echo
echo "After counters:"
cat "${AFTER_COUNTERS}"
echo
echo "MQSim IPC delta:"
echo "  requests_delta=$((after_req - before_req))"
echo "  replies_delta=$((after_rep - before_rep))"
echo "  fallbacks_delta=$((after_fallbacks - before_fallbacks))"
echo "  send_errors_delta=$((after_send_errors - before_send_errors))"
echo "  req_ring_full_delta=$((after_ring_full - before_ring_full))"
echo "  pending=${after_pending}"
echo "  max_pending=${after_max_pending}"
echo "  late_replies=${after_late}"
echo
echo "Saved:"
echo "  ${LOG_FILE}"
echo "  ${PERF_TABLE_FILE}"
echo "  ${TRACE_CSV}"
echo "  ${BEFORE_COUNTERS}"
echo "  ${AFTER_COUNTERS}"
echo "  ${COUNTER_DIFF}"
