#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=${ROOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
BUILD_DIR=${BUILD_DIR:-"${ROOT_DIR}/build"}

DATA_TYPE=${DATA_TYPE:-float}
DIST_FN=${DIST_FN:-l2}
BASE=${BASE:?Set BASE to the DiskANN .bin base vector file}
QUERY=${QUERY:?Set QUERY to the DiskANN .bin query vector file}
GT=${GT:-null}

PREFIX_DEFAULT=${PREFIX_DEFAULT:-"${ROOT_DIR}/index/default"}
PREFIX_BLOCK=${PREFIX_BLOCK:-"${ROOT_DIR}/index/block"}
RESULT_DIR=${RESULT_DIR:-"${ROOT_DIR}/results/cache_locality"}

R=${R:-64}
L_BUILD=${L_BUILD:-100}
SEARCH_GB=${SEARCH_GB:-1}
BUILD_GB=${BUILD_GB:-8}
K=${K:-10}
L_VALUES=${L_VALUES:-"20 30 40 50 60 100"}
W=${W:-4}
T=${T:-8}
CACHE_SIZES=${CACHE_SIZES:-"1000 5000 10000 25000 50000"}

TRACE_SAMPLE_RATE=${TRACE_SAMPLE_RATE:-1}
TRACE_MAX_QUERIES=${TRACE_MAX_QUERIES:-1000}
TRACE_CSV=${TRACE_CSV:-"${RESULT_DIR}/iteration_trace.csv"}

RUN_BUILD=${RUN_BUILD:-1}
RUN_LAYOUT=${RUN_LAYOUT:-1}
RUN_SEARCH=${RUN_SEARCH:-1}
BLOCK_SHUFFLE_ITERS=${BLOCK_SHUFFLE_ITERS:-5}
BLOCK_SHUFFLE_GAIN=${BLOCK_SHUFFLE_GAIN:-0.0001}

mkdir -p "$(dirname "${PREFIX_DEFAULT}")" "$(dirname "${PREFIX_BLOCK}")" "${RESULT_DIR}"

if [[ "${RUN_BUILD}" == "1" ]]; then
  "${BUILD_DIR}/apps/build_disk_index" \
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
fi

if [[ "${RUN_LAYOUT}" == "1" ]]; then
  "${BUILD_DIR}/apps/utils/create_disk_layout" \
    "${DATA_TYPE}" \
    "${BASE}" \
    "${PREFIX_DEFAULT}_mem.index" \
    "${PREFIX_BLOCK}_disk.index" \
    block_shuffle \
    "${BLOCK_SHUFFLE_ITERS}" \
    "${BLOCK_SHUFFLE_GAIN}" \
    reorder_pq
fi

if [[ "${RUN_SEARCH}" == "1" ]]; then
  rm -f "${TRACE_CSV}"

  for cache_size in ${CACHE_SIZES}; do
    "${BUILD_DIR}/apps/search_disk_index" \
      --data_type "${DATA_TYPE}" \
      --dist_fn "${DIST_FN}" \
      --index_path_prefix "${PREFIX_DEFAULT}" \
      --result_path "${RESULT_DIR}/default_cache_${cache_size}" \
      --query_file "${QUERY}" \
      --gt_file "${GT}" \
      -K "${K}" \
      -L ${L_VALUES} \
      -W "${W}" \
      -T "${T}" \
      --num_nodes_to_cache "${cache_size}" \
      --trace_stats_csv "${TRACE_CSV}" \
      --trace_sample_rate "${TRACE_SAMPLE_RATE}" \
      --trace_max_queries "${TRACE_MAX_QUERIES}" \
      --trace_run_label "default_cache_${cache_size}" \
      | tee "${RESULT_DIR}/default_cache_${cache_size}.log"

    "${BUILD_DIR}/apps/search_disk_index" \
      --data_type "${DATA_TYPE}" \
      --dist_fn "${DIST_FN}" \
      --index_path_prefix "${PREFIX_BLOCK}" \
      --result_path "${RESULT_DIR}/block_cache_${cache_size}" \
      --query_file "${QUERY}" \
      --gt_file "${GT}" \
      -K "${K}" \
      -L ${L_VALUES} \
      -W "${W}" \
      -T "${T}" \
      --num_nodes_to_cache "${cache_size}" \
      --result_new_to_old_map "${PREFIX_BLOCK}_disk.index_block_shuffle_new_to_old.bin" \
      --trace_stats_csv "${TRACE_CSV}" \
      --trace_sample_rate "${TRACE_SAMPLE_RATE}" \
      --trace_max_queries "${TRACE_MAX_QUERIES}" \
      --trace_run_label "block_cache_${cache_size}" \
      | tee "${RESULT_DIR}/block_cache_${cache_size}.log"

    "${BUILD_DIR}/apps/search_disk_index" \
      --data_type "${DATA_TYPE}" \
      --dist_fn "${DIST_FN}" \
      --index_path_prefix "${PREFIX_BLOCK}" \
      --result_path "${RESULT_DIR}/block_sector_cache_${cache_size}" \
      --query_file "${QUERY}" \
      --gt_file "${GT}" \
      -K "${K}" \
      -L ${L_VALUES} \
      -W "${W}" \
      -T "${T}" \
      --num_nodes_to_cache "${cache_size}" \
      --result_new_to_old_map "${PREFIX_BLOCK}_disk.index_block_shuffle_new_to_old.bin" \
      --use_sector_candidates \
      --trace_stats_csv "${TRACE_CSV}" \
      --trace_sample_rate "${TRACE_SAMPLE_RATE}" \
      --trace_max_queries "${TRACE_MAX_QUERIES}" \
      --trace_run_label "block_sector_cache_${cache_size}" \
      | tee "${RESULT_DIR}/block_sector_cache_${cache_size}.log"
  done

  python3 "${ROOT_DIR}/scripts/locality/summarize_locality_trace.py" \
    --trace_csv "${TRACE_CSV}" \
    --out_dir "${RESULT_DIR}/summaries"
fi
