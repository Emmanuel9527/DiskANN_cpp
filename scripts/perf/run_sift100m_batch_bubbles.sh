#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export INDEX_PREFIX="${INDEX_PREFIX:-/home/emmanuel/projects/data/sift100m_diskann_indexes/sift100m_l2_R64_L100_pq0_block_shuffle}"
FULL_QUERY_FILE="${FULL_QUERY_FILE:-/home/emmanuel/projects/data/sift100m/bigann_query.u8bin}"
FULL_GT_FILE="${FULL_GT_FILE:-/home/emmanuel/projects/data/sift100m/idx_100M.bin}"
QUERY_COUNT="${QUERY_COUNT:-1000}"
RAM_ROOT="${RAM_ROOT:-/dev/shm}"
export SEARCH_BIN="${SEARCH_BIN:-${ROOT_DIR}/build/apps/search_disk_index}"
export DATA_TYPE=uint8
export DIST_FN=l2
export THREADS="${THREADS:-1 2 4 8 16}"
export WIDTHS="${WIDTHS:-8}"
export REPEATS="${REPEATS:-3}"
export L="${L:-40}"
export K="${K:-10}"
export CACHE_NODES="${CACHE_NODES:-0}"
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --check ) ]]; then
    echo "Usage: bash $0 [--check]" >&2
    exit 1
fi
for file in "$SEARCH_BIN" "$FULL_QUERY_FILE" "$FULL_GT_FILE" \
    "${INDEX_PREFIX}_disk.index" "${INDEX_PREFIX}_pq_compressed.bin" "${INDEX_PREFIX}_pq_pivots.bin"; do
    [[ -r "$file" ]] || { echo "Missing/unreadable: $file" >&2; exit 1; }
done
[[ -x "$SEARCH_BIN" ]] || { echo 'Search binary is not executable' >&2; exit 1; }
if [[ "$INDEX_PREFIX" == *_block_shuffle ]]; then
    [[ -r "${INDEX_PREFIX}_disk.index_block_shuffle_new_to_old.bin" ]] || exit 1
fi
[[ "$(findmnt -n -o FSTYPE -T "$RAM_ROOT")" == tmpfs ]] || {
    echo "RAM_ROOT must be an existing tmpfs: $RAM_ROOT" >&2; exit 1;
}
# Check headers and memory without loading the 100M index or writing output.
python3 - "$FULL_QUERY_FILE" "$FULL_GT_FILE" "$QUERY_COUNT" "$RAM_ROOT" <<'PY'
import os, struct, sys
from pathlib import Path
query, gt, count, ram = sys.argv[1:]
count = int(count)
counts = []
for name, width in ((query, 1), (gt, 4)):
    with open(name, 'rb') as stream:
        n, d = struct.unpack('<II', stream.read(8))
    assert 0 < count <= n, f'Invalid QUERY_COUNT for {name}: {count}/{n}'
    assert Path(name).stat().st_size == 8 + n * d * width, f'Unexpected format: {name}'
    counts.append(n)
assert counts[0] == counts[1], 'Query/ground-truth count mismatch'
v = os.statvfs(ram)
available_tmpfs = v.f_bavail * v.f_frsize
mem = {line.split(':')[0]: int(line.split()[1]) * 1024
       for line in Path('/proc/meminfo').read_text().splitlines()}
print(f'Tmpfs available: {available_tmpfs / 2**30:.1f} GiB; '
      f'MemAvailable: {mem["MemAvailable"] / 2**30:.1f} GiB; queries: {count}')
# Conservative startup guards, not a bound on arbitrary overridden sweeps.
assert available_tmpfs >= 4 * 2**30, 'Need at least 4 GiB free tmpfs'
assert mem['MemAvailable'] >= 24 * 2**30, 'Need at least 24 GiB available RAM for this 100M preset'
PY
echo "Index: $INDEX_PREFIX"
echo "Query source: $FULL_QUERY_FILE"
echo "Ground truth: $FULL_GT_FILE"
echo "T=[$THREADS] W=[$WIDTHS] L=$L K=$K cache=$CACHE_NODES repeats=$REPEATS"
findmnt -T "${INDEX_PREFIX}_disk.index"
findmnt -T "$RAM_ROOT"
if [[ "${1:-}" == --check ]]; then
    echo 'Read-only checks passed. No files written; actual tmpfs writeability is checked at launch.'
    exit 0
fi
# mktemp also checks actual write access; never fall back silently to disk.
RUN_DIR="$(mktemp -d "${RAM_ROOT}/diskann_sift100m_bubbles_XXXXXXXX")"
export QUERY_FILE="${RUN_DIR}/queries.u8bin"
export GT_FILE="${RUN_DIR}/groundtruth.bin"
export RESULT_DIR="${RUN_DIR}/results"
echo "RAM output: $RUN_DIR (volatile; copy it to persistent storage after the sweep)"
python3 "${ROOT_DIR}/scripts/locality/slice_bin_prefix.py" \
    --input "$FULL_QUERY_FILE" --output "$QUERY_FILE" --count "$QUERY_COUNT" --dtype uint8
python3 "${ROOT_DIR}/scripts/locality/slice_bin_prefix.py" \
    --input "$FULL_GT_FILE" --output "$GT_FILE" --count "$QUERY_COUNT" --dtype uint32
bash "${ROOT_DIR}/scripts/perf/run_batch_bubble_sweep.sh"
echo "Finished. Results remain in $RUN_DIR; archive them before rebooting."
