#!/usr/bin/env python3
"""Summarize synchronous search read-call envelopes, NOT device outstanding I/O."""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def summarize(rows):
    queries = defaultdict(list)
    events = defaultdict(int)
    for row in rows:
        queries[row['query_id']].append(row)
        begin, end = int(row['read_begin_ns']), int(row['read_end_ns'])
        if begin:
            if end < begin:
                raise ValueError('Read end precedes begin')
            events[begin] += 1
            events[end] -= 1
    if not events:
        raise ValueError('No recorded read calls')
    lo, hi = min(events), max(events)
    active, previous = 0, lo
    duration_by_active = defaultdict(int)
    for timestamp, delta in sorted(events.items()):
        duration_by_active[active] += timestamp - previous
        active += delta
        previous = timestamp
    gaps = []
    for iterations in queries.values():
        reads = sorted((int(r['read_begin_ns']), int(r['read_end_ns']))
                       for r in iterations if int(r['read_begin_ns']))
        gaps.extend(b[0] - a[1] for a, b in zip(reads, reads[1:]))
    span = hi - lo
    if span <= 0:
        raise ValueError('Empty measurement interval')
    return {
        'queries': len(queries),
        'workers_observed': len({r['worker_id'] for r in rows}),
        'read_batches': sum(bool(int(r['read_begin_ns'])) for r in rows),
        'window_ms': span / 1e6,
        'no_search_read_call_fraction': duration_by_active[0] / span,
        'mean_concurrent_search_read_calls': sum(k * v for k, v in duration_by_active.items()) / span,
        'within_query_gap_mean_us': sum(gaps) / len(gaps) / 1000 if gaps else None,
        'fraction_by_active_read_calls': {str(k): v / span for k, v in sorted(duration_by_active.items())},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--complete-trace', action='store_true', required=True,
                        help='Assert all queries were traced, with synchronous Linux reads and no reranking')
    args = parser.parse_args()
    groups = defaultdict(list)
    with args.trace.open(newline='') as source:
        for row in csv.DictReader(source):
            key = tuple(row[k] for k in ('run_label', 'index_path_prefix', 'L', 'beamwidth',
                                        'num_nodes_to_cache', 'use_sector_candidates'))
            groups[key].append(row)
    results = []
    for key, rows in groups.items():
        identities = [(r['query_id'], r['iteration']) for r in rows]
        if len(set(identities)) != len(identities):
            raise ValueError('Duplicate query/iteration: use a fresh CSV and unique run labels')
        results.append({'configuration': key, **summarize(rows)})
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
