#!/usr/bin/env python3
"""Replay DiskANN node-access traces through an offline NBR-only page map."""

import argparse
import csv
import struct
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np


BATCH_KEYS = ("run_label", "L", "beamwidth", "query_id", "iteration")
LAYOUTS = ("current_full_node", "nbr_id_order", "nbr_random", "nbr_block_shuffle")


def read_diskann_bin_map(path):
    """Read DiskANN's uint32 bin format: uint32 count, uint32 dims, values."""
    with open(path, "rb") as f:
        header = f.read(8)
        if len(header) != 8:
            raise ValueError(f"Truncated map header: {path}")
        count, dims = struct.unpack("<II", header)
        if dims != 1:
            raise ValueError(f"Expected one-dimensional map in {path}; got dims={dims}")
        values = np.fromfile(f, dtype="<u4", count=count)
    if values.size != count:
        raise ValueError(f"Map count mismatch in {path}: expected {count}, got {values.size}")
    return values


def safe_pct(numerator, denominator):
    return 100.0 * numerator / denominator if denominator else 0.0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--access_csv", required=True)
    p.add_argument("--iteration_csv", required=True)
    p.add_argument("--current_new_to_old_map", required=True,
                   help="Map from IDs in the block-shuffle trace back to original logical IDs")
    p.add_argument("--nbr_old_to_new_map", required=True,
                   help="Map from original logical IDs to NBR-only physical slots")
    p.add_argument("--nodes_per_page", required=True, type=int)
    p.add_argument("--random_seed", type=int, default=20261013)
    p.add_argument("--out_dir", required=True)
    args = p.parse_args()

    current_new_to_old = read_diskann_bin_map(args.current_new_to_old_map)
    nbr_old_to_new = read_diskann_bin_map(args.nbr_old_to_new_map)
    if current_new_to_old.size != nbr_old_to_new.size:
        raise ValueError("Trace and NBR-only maps have different node counts")
    random_new_to_old = np.random.default_rng(args.random_seed).permutation(current_new_to_old.size)
    random_old_to_new = np.empty_like(random_new_to_old)
    random_old_to_new[random_new_to_old] = np.arange(random_new_to_old.size, dtype=random_new_to_old.dtype)

    # Per-batch accumulators let the large raw access CSV be processed as a stream.
    batches = {}
    with open(args.iteration_csv, newline="") as f:
        for row in csv.DictReader(f):
            key = tuple(row[k] for k in BATCH_KEYS)
            batches[key] = {
                "lifecycle_bin": int(row["lifecycle_bin"]),
                "node_count": 0,
                "pages": {layout: Counter() for layout in LAYOUTS},
            }

    with open(args.access_csv, newline="") as f:
        for row in csv.DictReader(f):
            key = tuple(row[k] for k in BATCH_KEYS)
            batch = batches.get(key)
            if batch is None:
                raise ValueError(f"Access row has no matching iteration row: {key}")
            trace_id = int(row["node_id"])
            if trace_id >= current_new_to_old.size:
                raise ValueError(f"Trace node ID out of range: {trace_id}")
            logical_id = int(current_new_to_old[trace_id])
            nbr_slot = int(nbr_old_to_new[logical_id])
            batch["node_count"] += 1
            batch["pages"]["current_full_node"][int(row["sector_id"])] += 1
            batch["pages"]["nbr_id_order"][logical_id // args.nodes_per_page] += 1
            batch["pages"]["nbr_random"][int(random_old_to_new[logical_id]) // args.nodes_per_page] += 1
            batch["pages"]["nbr_block_shuffle"][nbr_slot // args.nodes_per_page] += 1

    batch_rows = []
    summary = defaultdict(Counter)
    for key, batch in sorted(batches.items()):
        n = batch["node_count"]
        phase = batch["lifecycle_bin"]
        configs = (key[1], key[2], phase)
        row = dict(zip(BATCH_KEYS, key))
        row["lifecycle_bin"] = phase
        row["node_reads_N"] = n
        for prefix in LAYOUTS:
            counts = batch["pages"][prefix]
            u = len(counts)
            shared_reads = sum(count for count in counts.values() if count >= 2)
            s = summary[(prefix, *configs)]
            s["batches"] += 1
            s["shared_batches"] += int(any(count >= 2 for count in counts.values()))
            s["reads"] += n
            s["unique_pages"] += u
            s["shared_reads"] += shared_reads
            s["duplicate_reads"] += n - u
            row[f"{prefix}_unique_pages_U"] = u
            row[f"{prefix}_node_reads_in_shared_pages"] = shared_reads
            row[f"{prefix}_duplicate_page_requests_N_minus_U"] = n - u
        batch_rows.append(row)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_fields = list(BATCH_KEYS) + ["lifecycle_bin", "node_reads_N"] + [
        f"{layout}_{metric}"
        for layout in LAYOUTS
        for metric in ("unique_pages_U", "node_reads_in_shared_pages", "duplicate_page_requests_N_minus_U")
    ]
    with (out_dir / "nbr_only_batch_replay.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=batch_fields)
        writer.writeheader()
        writer.writerows(batch_rows)

    summary_fields = [
        "layout", "L", "beamwidth", "lifecycle_bin", "progress_range", "batches",
        "total_node_reads_N", "total_unique_pages_U", "batches_with_shared_page_pct",
        "node_reads_in_shared_pages_pct", "duplicate_page_request_ratio_pct",
    ]
    summary_rows = []
    for (layout, L, W, phase), s in sorted(summary.items(), key=lambda item: (item[0][0], int(item[0][1]), int(item[0][2]), item[0][3])):
        summary_rows.append({
            "layout": layout,
            "L": L,
            "beamwidth": W,
            "lifecycle_bin": phase,
            "progress_range": f"{(phase - 1) * 20}-{phase * 20}%",
            "batches": s["batches"],
            "total_node_reads_N": s["reads"],
            "total_unique_pages_U": s["unique_pages"],
            "batches_with_shared_page_pct": safe_pct(s["shared_batches"], s["batches"]),
            "node_reads_in_shared_pages_pct": safe_pct(s["shared_reads"], s["reads"]),
            "duplicate_page_request_ratio_pct": safe_pct(s["duplicate_reads"], s["reads"]),
        })
    with (out_dir / "nbr_only_replay_summary.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"Wrote {len(batch_rows)} batches and {len(summary_rows)} layout/phase summaries to {out_dir}")


if __name__ == "__main__":
    main()
