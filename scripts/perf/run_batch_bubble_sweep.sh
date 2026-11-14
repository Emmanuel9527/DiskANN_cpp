#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
: "${INDEX_PREFIX:?Set INDEX_PREFIX to the index on the real SSD}"
: "${QUERY_FILE:?Set QUERY_FILE}"
: "${GT_FILE:?Set GT_FILE}"
: "${RESULT_DIR:?Set a new RESULT_DIR outside the measured SSD if possible}"
if [[ -e "${RESULT_DIR}" ]]; then
    echo 'RESULT_DIR already exists; choose a fresh directory.' >&2
    exit 1
fi
mkdir -p "${RESULT_DIR}"
SEARCH_BIN="${SEARCH_BIN:-${ROOT_DIR}/build/apps/search_disk_index}"
for repeat in $(seq 1 "${REPEATS:-3}"); do
    for width in ${WIDTHS:-8}; do
        for threads in ${THREADS:-1 2 4 8 16}; do
            for mode in plain traced; do
                label="r${repeat}_W${width}_T${threads}_${mode}"
                args=(--data_type "${DATA_TYPE:-float}" --dist_fn "${DIST_FN:-l2}"
                    --index_path_prefix "${INDEX_PREFIX}" --query_file "${QUERY_FILE}"
                    --gt_file "${GT_FILE}" --result_path "${RESULT_DIR}/${label}"
                    -K "${K:-10}" -L "${L:-40}" -W "${width}" -T "${threads}"
                    --num_nodes_to_cache "${CACHE_NODES:-0}")
                map="${INDEX_PREFIX}_disk.index_block_shuffle_new_to_old.bin"
                if [[ -f "$map" ]]; then
                    args+=(--result_new_to_old_map "$map")
                fi
                if [[ "$mode" == traced ]]; then
                    args+=(--trace_stats_csv "${RESULT_DIR}/${label}.csv"
                        --trace_sample_rate 1 --trace_max_queries 0 --trace_run_label "$label")
                fi
                printf '%q ' "${SEARCH_BIN}" "${args[@]}" > "${RESULT_DIR}/${label}.command"
                printf '\n' >> "${RESULT_DIR}/${label}.command"
                "${SEARCH_BIN}" "${args[@]}" | tee "${RESULT_DIR}/${label}.log"
                if [[ "$mode" == traced ]]; then
                    python3 "${ROOT_DIR}/scripts/perf/summarize_batch_bubbles.py" \
                        "${RESULT_DIR}/${label}.csv" --complete-trace > "${RESULT_DIR}/${label}.summary.json"
                fi
            done
        done
    done
done
