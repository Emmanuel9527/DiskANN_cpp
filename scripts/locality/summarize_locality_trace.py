#!/usr/bin/env python3
import argparse
import csv
from collections import defaultdict
from pathlib import Path


GROUP_KEYS = (
    "run_label",
    "L",
    "beamwidth",
    "num_nodes_to_cache",
    "use_sector_candidates",
    "lifecycle_bin",
)


def percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int((len(ordered) - 1) * pct)
    return ordered[idx]


def median(values):
    return percentile(values, 0.5)


def as_float(row, name):
    value = row.get(name, "")
    return float(value) if value != "" else 0.0


def as_int(row, name):
    value = row.get(name, "")
    return int(value) if value != "" else 0


def grouped_rows(trace_csv):
    groups = defaultdict(list)
    with open(trace_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = tuple(row[k] for k in GROUP_KEYS)
            groups[key].append(row)
    return groups


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def base_summary(key):
    return {name: value for name, value in zip(GROUP_KEYS, key)}


def summarize_experiment_1(groups):
    rows = []
    for key, items in groups.items():
        row = base_summary(key)
        iteration_us = [as_float(item, "iteration_us") for item in items]
        io_us = [as_float(item, "io_us") for item in items]
        row.update(
            {
                "median_iteration_us": median(iteration_us),
                "p95_iteration_us": percentile(iteration_us, 0.95),
                "median_io_wait_us": median(io_us),
                "p95_io_wait_us": percentile(io_us, 0.95),
            }
        )
        rows.append(row)
    return rows


def summarize_experiment_2(groups):
    rows = []
    for key, items in groups.items():
        row = base_summary(key)
        requested_kib = [as_float(item, "requested_bytes") / 1024.0 for item in items]
        useful_kib = [as_float(item, "useful_payload_bytes") / 1024.0 for item in items]
        requested_total = sum(as_float(item, "requested_bytes") for item in items)
        useful_total = sum(as_float(item, "useful_payload_bytes") for item in items)
        row.update(
            {
                "median_requested_KiB": median(requested_kib),
                "median_useful_payload_KiB": median(useful_kib),
                "aggregate_requested_KiB": requested_total / 1024.0,
                "aggregate_useful_payload_KiB": useful_total / 1024.0,
                "aggregate_overfetch_ratio": requested_total / useful_total if useful_total > 0 else 0.0,
            }
        )
        rows.append(row)
    return rows


def summarize_experiment_3(groups):
    rows = []
    for key, items in groups.items():
        row = base_summary(key)
        reads_total = sum(as_int(item, "issued_reads") for item in items)
        duplicate_total = sum(as_int(item, "duplicate_sectors") for item in items)
        row.update(
            {
                "median_uncached_nodes": median([as_float(item, "uncached_nodes") for item in items]),
                "median_issued_reads": median([as_float(item, "issued_reads") for item in items]),
                "median_unique_sectors": median([as_float(item, "unique_sectors") for item in items]),
                "aggregate_duplicate_sector_ratio": duplicate_total / reads_total if reads_total > 0 else 0.0,
            }
        )
        rows.append(row)
    return rows


def summarize_experiment_4(groups):
    rows = []
    for key, items in groups.items():
        row = base_summary(key)
        rows_seen = [as_float(item, "neighbors_seen") for item in items]
        unique_neighbors = [as_float(item, "unique_neighbors") for item in items]
        new_visited = [as_float(item, "new_visited") for item in items]
        candidates = [as_float(item, "candidates_inserted") for item in items]
        total_seen = sum(rows_seen)
        total_candidates = sum(candidates)
        row.update(
            {
                "median_neighbors_seen": median(rows_seen),
                "median_unique_neighbors": median(unique_neighbors),
                "median_new_visited": median(new_visited),
                "median_candidates_inserted": median(candidates),
                "aggregate_candidate_utilization": total_candidates / total_seen if total_seen > 0 else 0.0,
            }
        )
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description="Summarize DiskANN per-iteration locality traces.")
    parser.add_argument("--trace_csv", required=True)
    parser.add_argument("--out_dir", required=True)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    groups = grouped_rows(args.trace_csv)

    write_csv(
        out_dir / "experiment1_iteration_io_by_lifecycle.csv",
        list(GROUP_KEYS) + ["median_iteration_us", "p95_iteration_us", "median_io_wait_us", "p95_io_wait_us"],
        summarize_experiment_1(groups),
    )
    write_csv(
        out_dir / "experiment2_overfetch_by_lifecycle.csv",
        list(GROUP_KEYS)
        + [
            "median_requested_KiB",
            "median_useful_payload_KiB",
            "aggregate_requested_KiB",
            "aggregate_useful_payload_KiB",
            "aggregate_overfetch_ratio",
        ],
        summarize_experiment_2(groups),
    )
    write_csv(
        out_dir / "experiment3_uncached_reads_by_lifecycle.csv",
        list(GROUP_KEYS)
        + [
            "median_uncached_nodes",
            "median_issued_reads",
            "median_unique_sectors",
            "aggregate_duplicate_sector_ratio",
        ],
        summarize_experiment_3(groups),
    )
    write_csv(
        out_dir / "experiment4_neighbor_utilization_by_lifecycle.csv",
        list(GROUP_KEYS)
        + [
            "median_neighbors_seen",
            "median_unique_neighbors",
            "median_new_visited",
            "median_candidates_inserted",
            "aggregate_candidate_utilization",
        ],
        summarize_experiment_4(groups),
    )


if __name__ == "__main__":
    main()
