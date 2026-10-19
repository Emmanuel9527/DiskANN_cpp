#!/usr/bin/env python3
import csv
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

INPUTS = {
    "SIFT1M": Path("/home/emmanuel/projects/DiskANN_cpp/results/nbr_only_block_shuffle_sift1m_20261013/replay/nbr_only_replay_summary.csv"),
    "SIFT100M": Path("/home/emmanuel/projects/DiskANN_cpp/results/nbr_only_block_shuffle_sift100m_20261014/replay/nbr_only_replay_summary.csv"),
}
OUT = Path("/tmp/locality_nbr_only_heatmaps_20261016")
PHASES = ["0–20%", "20–40%", "40–60%", "60–80%", "80–100%"]
CONFIGS = [(L, W) for L in (20, 60, 120) for W in (8, 16, 32, 64)]
PANELS = [
    ("batches_with_shared_page_pct", "Batches with a shared sector (%)", 60.0),
    ("node_reads_in_shared_pages_pct", "Node reads in shared sectors (%)", 12.0),
    ("duplicate_page_request_ratio_pct", "Duplicate sector requests, (N−U)/N (%)", 6.0),
]


def make_heatmap(dataset, csv_path):
    rows = list(csv.DictReader(csv_path.open(newline="")))
    rows = [r for r in rows if r["layout"] == "nbr_block_shuffle"]
    lookup = {(int(r["L"]), int(r["beamwidth"]), int(r["lifecycle_bin"])): r for r in rows}
    labels = [f"L={L}, W={W}" for L, W in CONFIGS]
    matrices = []
    for metric, _, _ in PANELS:
        matrices.append(np.array([[float(lookup[(L, W, phase)][metric]) for phase in range(1, 6)] for L, W in CONFIGS]))

    fig, axes = plt.subplots(1, 3, figsize=(22.15, 12.63), dpi=150)
    fig.suptitle(f"{dataset}: NBR-only sector reuse by search progress", fontsize=18, y=0.985)
    for ax, values, (metric, title, vmax) in zip(axes, matrices, PANELS):
        im = ax.imshow(values, cmap="YlOrRd", vmin=0, vmax=vmax, aspect="auto")
        ax.set_title(title, fontsize=14, pad=10)
        ax.set_xticks(range(5), PHASES, rotation=30, ha="right", rotation_mode="anchor", fontsize=10)
        ax.set_yticks(range(len(labels)), labels)
        ax.set_xticks(np.arange(-0.5, 5, 1), minor=True)
        ax.set_yticks(np.arange(-0.5, len(labels), 1), minor=True)
        ax.grid(which="minor", color="white", linestyle="-", linewidth=1.5)
        ax.tick_params(which="minor", bottom=False, left=False)
        ax.set_xlabel("Search progress within each query", fontsize=12)
        for i in range(values.shape[0]):
            for j in range(values.shape[1]):
                val = values[i, j]
                # Use white labels over the darker part of the fixed YlOrRd scale.
                ax.text(j, i, f"{val:.1f}", ha="center", va="center",
                        color="white" if val >= vmax * 0.58 else "#333333", fontsize=9)
        cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.025)
        cbar.ax.tick_params(labelsize=9)
    fig.subplots_adjust(left=0.060, right=0.99, bottom=0.105, top=0.945, wspace=0.38)
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"{dataset.lower()}_nbr_only_sector_reuse_heatmap.png"
    fig.savefig(target, dpi=150, facecolor="white")
    plt.close(fig)
    print(target)


if __name__ == "__main__":
    for name, path in INPUTS.items():
        make_heatmap(name, path)
