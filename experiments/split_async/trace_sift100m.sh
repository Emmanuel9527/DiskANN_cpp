#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
LAYOUT=${LAYOUT:-/home/emmanuel/projects/data/sift100m_split_shuffled}
RESULT_DIR=${RESULT_DIR:-$ROOT/results/split_block_$(date +%Y%m%d_%H%M%S)_$$}
mkdir -p "$RESULT_DIR"
RESULT_DIR=$(realpath "$RESULT_DIR")
command -v trace-cmd >/dev/null
# Map file offsets to device sectors. Capture both sides to detect layout changes.
for name in neighbors vectors; do
 filefrag -v -b512 "$LAYOUT/$name.bin" > "$RESULT_DIR/$name.extents.before.txt"
 findmnt -T "$LAYOUT/$name.bin" -o SOURCE,FSTYPE,TARGET > "$RESULT_DIR/$name.mount.txt"
done
lsblk -o NAME,MAJ:MIN,TYPE,PKNAME,START > "$RESULT_DIR/devices.txt"
echo 'Recording kernel block events with CLOCK_MONOTONIC. sudo is needed for kernel tracing.'
sudo trace-cmd record -C mono -b 16384 -o "$RESULT_DIR/block.dat" \
 -e block:block_rq_issue -e block:block_rq_complete -e block:block_bio_queue -e block:block_bio_complete \
 sudo -u "$(id -un)" env TRACE_IO=1 PROFILE_HOST="${PROFILE_HOST:-0}" RESULT_DIR="$RESULT_DIR" LAYOUT="$LAYOUT" \
 SEARCH_MODE="${SEARCH_MODE:-baseline}" \
 QUERY_LIMIT="${QUERY_LIMIT:-100}" BEAM_WIDTHS="${BEAM_WIDTHS:-16}" \
 bash "$ROOT/experiments/split_async/run_sift100m.sh" \
 2>&1 | tee "$RESULT_DIR/recorder.log"
sudo trace-cmd report -i "$RESULT_DIR/block.dat" > "$RESULT_DIR/block.txt" 2> "$RESULT_DIR/report.log"
for name in neighbors vectors; do
 filefrag -v -b512 "$LAYOUT/$name.bin" > "$RESULT_DIR/$name.extents.after.txt"
done
echo "Trace complete: $RESULT_DIR"
echo 'Check recorder.log/report.log/block.txt for LOST EVENTS before analysis.'
