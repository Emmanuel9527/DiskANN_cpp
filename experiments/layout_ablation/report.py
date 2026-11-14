#!/usr/bin/env python3
"""Render measured I/O counts and recall, preserving every repeat."""
import argparse
import csv
from pathlib import Path


def report(directory):
    directory = Path(directory)
    with (directory/'summary.csv').open() as f:
        rows = list(csv.DictReader(f))
    lines = ['# SIFT100M layout comparison', '',
             'K=10, one query thread, no node cache, exact reranking; shared logical medoids. '
             'Expansion policy is shown per row. All counts are actual submitted 4 KiB host reads, including repeated reads.', '',
             '| Repeat | Layout | Expansion | L | W | Recall@10 (%) | Mean ms | Neighbor reads/query | Vector reads/query | Combined reads/query | Total reads/query | Change vs baseline |',
             '|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    baselines = {(r['repeat'], r['L'], r['W']): float(r['mean_host_reads']) for r in rows if r['case']=='diskann_baseline'}
    for r in rows:
        change = 100*(float(r['mean_host_reads'])/baselines[r['repeat'], r['L'], r['W']]-1)
        lines.append(f"| {r['repeat']} | {r['case']} | {r.get('expansion', 'node')} | {r['L']} | {r['W']} | "
                     f"{float(r['recall_at_10_pct']):.2f} | {float(r['mean_us'])/1000:.3f} | "
                     f"{float(r.get('mean_neighbor_reads', 0)):.3f} | {float(r.get('mean_vector_reads', 0)):.3f} | "
                     f"{float(r.get('mean_combined_reads', 0)):.3f} | {float(r['mean_host_reads']):.3f} | {change:+.2f}% |")
    lines += ['', 'Count interpretation:', '',
              '- Combined reads carry both vectors and adjacency lists; do not count them twice. Zero separate vector reads does not mean no vector data was read.',
              '- Split page mode PQ-scores every resident plus its adjacency, expands all valid lists, and reads each graph page once per query. Vector requests remain per selected node without page deduplication.',
              '- Native greedy sector expansion scores all resident vectors exactly and all their neighbors with PQ; split reranks only selected nodes. Compare recall alongside I/O.',
              '- Host requests are not NAND operations. Native and split use different I/O drivers.',
              '- The node-mode run is an optional diagnostic, not the primary whole-page experiment.', '']
    (directory/'summary.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory', type=Path)
    report(p.parse_args().directory)
