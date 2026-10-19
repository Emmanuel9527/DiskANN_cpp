#!/usr/bin/env python3
"""Summarize per-iteration node/sector co-location from DiskANN trace CSVs."""

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


BATCH_KEYS = (
    "run_label",
    "L",
    "beamwidth",
    "num_nodes_to_cache",
    "use_sector_candidates",
    "query_id",
    "iteration",
)
CONFIG_KEYS = ("run_label", "L", "beamwidth")


def load_csv(path):
    with open(path, newline="") as source:
        return list(csv.DictReader(source))


def safe_ratio(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Measure actual node-read co-location within each query iteration."
    )
    parser.add_argument("--access_csv", required=True)
    parser.add_argument("--iteration_csv", required=True)
    parser.add_argument("--out_dir", required=True)
    args = parser.parse_args()

    # The iteration stats define all traced query/iteration batches, including
    # any batch that happens to contain zero submitted node reads.
    iteration_rows = load_csv(args.iteration_csv)
    access_rows = load_csv(args.access_csv)
    batches = {}
    for row in iteration_rows:
        key = tuple(row[name] for name in BATCH_KEYS)
        batches[key] = {"sectors": [], "stats": row}

    for row in access_rows:
        key = tuple(row[name] for name in BATCH_KEYS)
        if key not in batches:
            batches[key] = {"sectors": [], "stats": {}}
        batches[key]["sectors"].append(row["sector_id"])

    batch_rows = []
    grouped = defaultdict(list)
    for key, batch in sorted(batches.items()):
        sector_counts = Counter(batch["sectors"])
        node_reads = len(batch["sectors"])
        unique_sectors = len(sector_counts)
        shared_sectors = sum(count >= 2 for count in sector_counts.values())
        shared_node_reads = sum(count for count in sector_counts.values() if count >= 2)
        duplicate_requests = node_reads - unique_sectors
        stats = batch["stats"]

        result = dict(zip(BATCH_KEYS, key))
        result.update(
            {
                "node_reads_N": node_reads,
                "unique_sector_starts_U": unique_sectors,
                "shared_sector_groups": shared_sectors,
                "has_shared_sector": int(shared_sectors > 0),
                "node_reads_in_shared_groups": shared_node_reads,
                "shared_node_read_ratio": safe_ratio(shared_node_reads, node_reads),
                "duplicate_sector_requests_N_minus_U": duplicate_requests,
                "duplicate_sector_request_ratio": safe_ratio(duplicate_requests, node_reads),
                "stats_issued_reads": stats.get("issued_reads", ""),
                "stats_unique_sectors": stats.get("unique_sectors", ""),
                "stats_duplicate_sectors": stats.get("duplicate_sectors", ""),
            }
        )
        batch_rows.append(result)
        grouped[(key[0], key[1], key[2])].append(result)

    summary_rows = []
    for key, rows in sorted(grouped.items()):
        total_batches = len(rows)
        total_reads = sum(int(row["node_reads_N"]) for row in rows)
        total_unique_sectors = sum(int(row["unique_sector_starts_U"]) for row in rows)
        batches_with_shared = sum(int(row["has_shared_sector"]) for row in rows)
        shared_reads = sum(int(row["node_reads_in_shared_groups"]) for row in rows)
        duplicate_requests = sum(int(row["duplicate_sector_requests_N_minus_U"]) for row in rows)
        summary = dict(zip(CONFIG_KEYS, key))
        summary.update(
            {
                "batches": total_batches,
                "batches_with_shared_sector": batches_with_shared,
                "batches_with_shared_sector_pct": 100.0 * safe_ratio(batches_with_shared, total_batches),
                "total_node_reads_N": total_reads,
                "total_unique_sector_starts_U": total_unique_sectors,
                "mean_node_reads_per_batch": safe_ratio(total_reads, total_batches),
                "mean_unique_sectors_per_batch": safe_ratio(total_unique_sectors, total_batches),
                "node_reads_in_shared_groups": shared_reads,
                "node_read_share_in_shared_groups_pct": 100.0 * safe_ratio(shared_reads, total_reads),
                "duplicate_sector_requests_N_minus_U": duplicate_requests,
                "duplicate_sector_request_ratio_pct": 100.0 * safe_ratio(duplicate_requests, total_reads),
            }
        )
        summary_rows.append(summary)

    out_dir = Path(args.out_dir)
    write_csv(
        out_dir / "sector_batch_metrics.csv",
        list(BATCH_KEYS)
        + [
            "node_reads_N",
            "unique_sector_starts_U",
            "shared_sector_groups",
            "has_shared_sector",
            "node_reads_in_shared_groups",
            "shared_node_read_ratio",
            "duplicate_sector_requests_N_minus_U",
            "duplicate_sector_request_ratio",
            "stats_issued_reads",
            "stats_unique_sectors",
            "stats_duplicate_sectors",
        ],
        batch_rows,
    )
    write_csv(
        out_dir / "sector_locality_summary.csv",
        list(CONFIG_KEYS)
        + [
            "batches",
            "batches_with_shared_sector",
            "batches_with_shared_sector_pct",
            "total_node_reads_N",
            "total_unique_sector_starts_U",
            "mean_node_reads_per_batch",
            "mean_unique_sectors_per_batch",
            "node_reads_in_shared_groups",
            "node_read_share_in_shared_groups_pct",
            "duplicate_sector_requests_N_minus_U",
            "duplicate_sector_request_ratio_pct",
        ],
        summary_rows,
    )
    print(f"Wrote {len(batch_rows)} iteration batches and {len(summary_rows)} L/W summaries to {out_dir}")


if __name__ == "__main__":
    main()
