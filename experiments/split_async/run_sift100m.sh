#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
DATA_ROOT=${DATA_ROOT:-/home/emmanuel/projects/data}
LAYOUT=${LAYOUT:-$DATA_ROOT/sift100m_split_shuffled}
NBR_PREFIX=${NBR_PREFIX:-$ROOT/results/nbr_only_block_shuffle_sift100m_20261014/sift100m_nbr_block_shuffle}
INDEX=${INDEX:-$DATA_ROOT/sift100m_diskann_indexes/sift100m_l2_R64_L100_pq0_default}
QUERY_LIMIT=${QUERY_LIMIT:-100}
export SEARCH_MODE=${SEARCH_MODE:-baseline}
[[ "$SEARCH_MODE" == baseline || "$SEARCH_MODE" == traverse_only || "$SEARCH_MODE" == host_worker ]] || { echo 'ERROR: Invalid SEARCH_MODE.' >&2; exit 1; }
BUILD_JOBS=${BUILD_JOBS:-4}
RESULT_DIR=${RESULT_DIR:-$ROOT/results/split_async_sift100m_${SEARCH_MODE}_$(date +%Y%m%d_%H%M%S)_$$}
[[ "$QUERY_LIMIT" =~ ^[1-9][0-9]*$ ]] || { echo 'ERROR: QUERY_LIMIT must be a positive integer.' >&2; exit 1; }
mkdir -p "$RESULT_DIR"
exec > >(tee "$RESULT_DIR/run.log") 2>&1
printf 'Starting SIFT100M split-layout experiment\nL: 20 60 120 | W: %s | K: 10 | Query limit: %s\nMode: %s\nResults: %s\n' "${BEAM_WIDTHS:-16}" "$QUERY_LIMIT" "$SEARCH_MODE" "$RESULT_DIR"
for f in "$DATA_ROOT/sift100m/base.100M.u8bin" "$DATA_ROOT/sift100m/bigann_query.u8bin" "${NBR_PREFIX}.nbr.index" "${NBR_PREFIX}.old_to_new.bin" "${NBR_PREFIX}.new_to_old.bin" "${INDEX}_pq_compressed.bin" "${INDEX}_pq_pivots.bin"; do
  [[ -r "$f" ]] || { printf 'ERROR: Missing input: %s\n' "$f" >&2; exit 1; }
done
if [[ ! -e "$LAYOUT" ]]; then
  echo '[1/3] Preparing vector layout; reusing existing shuffled graph and maps.'
  python3 -u "$ROOT/experiments/split_async/prepare_shuffled.py" \
    --neighbor-prefix "$NBR_PREFIX" --base "$DATA_ROOT/sift100m/base.100M.u8bin" --out "$LAYOUT"
else
  echo '[1/3] Existing layout found. Checking completeness.'
fi
MEDOID=$(python3 - "$LAYOUT" "$NBR_PREFIX" <<'PY'
import json,sys,struct
from pathlib import Path
p=Path(sys.argv[1]);prefix=Path(sys.argv[2]).resolve()
try:
    m=json.loads((p/'layout.json').read_text())
    n=m['nodes'];assert n==100000000 and m['dimension']==128
    assert m['vector_order']=='original logical ID'
    assert Path(m['neighbor_prefix']).resolve()==prefix
    assert (p/'vectors.bin').stat().st_size==((n*128+4095)//4096)*4096
    assert (p/'neighbors.bin').stat().st_size==(1+(n+14)//15)*4096
    for filename,suffix in [('neighbors.bin','.nbr.index'),('old_to_new.bin','.old_to_new.bin'),('new_to_old.bin','.new_to_old.bin')]:
        assert (p/filename).samefile(str(prefix)+suffix)
    print(m['medoid'])
except Exception as e:
    raise SystemExit(f'ERROR: Layout is incomplete or incompatible: {p}. Inspect it before retrying; no files were overwritten. {e}')
PY
)
echo '[2/3] Building search_split_async.'
cmake -S "$ROOT" -B "$ROOT/build" > "$RESULT_DIR/configure.log" 2>&1 || { cat "$RESULT_DIR/configure.log"; exit 1; }
cmake --build "$ROOT/build" --target search_split_async -j "$BUILD_JOBS"
echo '[3/3] Running sequential L sweep.'
for W in ${BEAM_WIDTHS:-16}; do
for L in 20 60 120; do
  printf '\nStarting L=%s, W=%s ...\n' "$L" "$W"
  "$ROOT/build/apps/search_split_async" \
    "$LAYOUT/neighbors.bin" "$LAYOUT/vectors.bin" \
    "${INDEX}_pq_compressed.bin" "${INDEX}_pq_pivots.bin" \
    "$DATA_ROOT/sift100m/bigann_query.u8bin" \
    "$MEDOID" "$L" "$W" 10 "$QUERY_LIMIT" "$RESULT_DIR/L${L}_W${W}.csv" \
    "$LAYOUT/old_to_new.bin" "$LAYOUT/new_to_old.bin" \
    2>&1 | tee "$RESULT_DIR/L${L}_W${W}.log"
  printf 'Completed L=%s. CSV: %s/L%s_W%s.csv\n' "$L" "$RESULT_DIR" "$L" "$W"
done
done
printf '\nAll runs completed. Results: %s\n' "$RESULT_DIR"
echo 'Recall is not calculated by this script. Read counts are host requests, not NAND reads.'

if [[ "$SEARCH_MODE" == traverse_only || "$SEARCH_MODE" == host_worker ]]; then
  echo "Traversal-only diagnostic: no vector reads, no exact rerank, result_ids intentionally empty."
fi
