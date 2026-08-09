#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

DATA_DIR="${DATA_DIR:-/home/emmanuel/projects/data/sift1m}"
INDEX_DIR="${INDEX_DIR:-/home/emmanuel/projects/data/sift1m_diskann_indexes}"

DATA_TYPE="${DATA_TYPE:-float}"
DIST_FN="${DIST_FN:-l2}"
R="${R:-64}"
L_BUILD="${L_BUILD:-100}"
SEARCH_GB="${SEARCH_GB:-4}"
BUILD_GB="${BUILD_GB:-8}"
THREADS="${THREADS:-32}"
PQ_DISK_BYTES="${PQ_DISK_BYTES:-0}"
BLOCK_SHUFFLE_ITERS="${BLOCK_SHUFFLE_ITERS:-5}"
BLOCK_SHUFFLE_GAIN="${BLOCK_SHUFFLE_GAIN:-0.0001}"

BASE_FVECS="${BASE_FVECS:-${DATA_DIR}/sift_base.fvecs}"
QUERY_FVECS="${QUERY_FVECS:-${DATA_DIR}/sift_query.fvecs}"
GT_IVECS="${GT_IVECS:-${DATA_DIR}/sift_groundtruth.ivecs}"

BASE="${BASE:-${DATA_DIR}/sift_base.fbin}"
QUERY="${QUERY:-${DATA_DIR}/sift_query.fbin}"
GT="${GT:-${DATA_DIR}/sift_groundtruth.bin}"

PREFIX_STEM="${PREFIX_STEM:-sift1m_${DIST_FN}_R${R}_L${L_BUILD}_pq${PQ_DISK_BYTES}}"
PREFIX_DEFAULT="${PREFIX_DEFAULT:-${INDEX_DIR}/${PREFIX_STEM}_default}"
PREFIX_BLOCK="${PREFIX_BLOCK:-${INDEX_DIR}/${PREFIX_STEM}_block_shuffle}"

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
    echo "Build it first, for example: cmake --build build --target build_disk_index create_disk_layout fvecs_to_bin ivecs_to_bin -j" >&2
    exit 1
  fi
}

cd "${REPO_ROOT}"
mkdir -p "${INDEX_DIR}"

require_exe build/apps/utils/fvecs_to_bin
require_exe build/apps/utils/ivecs_to_bin
require_exe build/apps/build_disk_index
require_exe build/apps/utils/create_disk_layout

require_file "${BASE_FVECS}"

if [[ ! -f "${BASE}" ]]; then
  build/apps/utils/fvecs_to_bin "${DATA_TYPE}" "${BASE_FVECS}" "${BASE}"
else
  echo "Found ${BASE}; skipping base conversion."
fi

if [[ -f "${QUERY_FVECS}" && ! -f "${QUERY}" ]]; then
  build/apps/utils/fvecs_to_bin "${DATA_TYPE}" "${QUERY_FVECS}" "${QUERY}"
elif [[ -f "${QUERY}" ]]; then
  echo "Found ${QUERY}; skipping query conversion."
fi

if [[ -f "${GT_IVECS}" && ! -f "${GT}" ]]; then
  build/apps/utils/ivecs_to_bin "${GT_IVECS}" "${GT}"
elif [[ -f "${GT}" ]]; then
  echo "Found ${GT}; skipping ground-truth conversion."
fi

echo "Building default disk index at prefix: ${PREFIX_DEFAULT}"
build/apps/build_disk_index \
  --data_type "${DATA_TYPE}" \
  --dist_fn "${DIST_FN}" \
  --data_path "${BASE}" \
  --index_path_prefix "${PREFIX_DEFAULT}" \
  -R "${R}" \
  -L "${L_BUILD}" \
  -B "${SEARCH_GB}" \
  -M "${BUILD_GB}" \
  -T "${THREADS}" \
  --PQ_disk_bytes "${PQ_DISK_BYTES}" \
  --keep_vamana_graph

echo "Building block-shuffled disk layout at prefix: ${PREFIX_BLOCK}"
build/apps/utils/create_disk_layout \
  "${DATA_TYPE}" \
  "${BASE}" \
  "${PREFIX_DEFAULT}_mem.index" \
  "${PREFIX_BLOCK}_disk.index" \
  block_shuffle \
  "${BLOCK_SHUFFLE_ITERS}" \
  "${BLOCK_SHUFFLE_GAIN}" \
  reorder_pq

cp "${PREFIX_DEFAULT}_pq_pivots.bin" "${PREFIX_BLOCK}_pq_pivots.bin"

echo
echo "Block-shuffled index prefix:"
echo "${PREFIX_BLOCK}"
echo
ls -lh "${PREFIX_BLOCK}"*
