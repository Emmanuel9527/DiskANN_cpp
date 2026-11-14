#!/usr/bin/env python3
"""Prepare and benchmark three layouts with whole-page expansion and exact reranking."""
import argparse
import csv
import datetime
import json
import os
import platform
import re
import struct
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
from verify import verify, binary
from report import report

ROOT = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--data-root', type=Path, default=Path('/home/emmanuel/projects/data'))
p.add_argument('--layout', type=Path, default=ROOT/'results/layout_ablation_assets/sift100m_identity')
p.add_argument('--queries', type=int, default=1000)
p.add_argument('--repeats', type=int, default=3)
p.add_argument('--L', type=int, nargs='+', default=[20, 60, 120])
p.add_argument('--W', type=int, nargs='+', default=[16])
p.add_argument('--out', type=Path)
p.add_argument('--expansion', choices=['page', 'node'], default='page', help='page: use all page adjacency lists in split and greedy; baseline stays native')
p.add_argument('--prepare-only', action='store_true')
a = p.parse_args()
a.data_root = a.data_root.resolve()
a.layout = a.layout.resolve()
if not 1 <= a.queries <= 10000 or a.repeats < 1 or min(a.L) < 10 or not all(1 <= w <= 512 for w in a.W):
    p.error('Invalid query count, repetitions, L or W')
out = a.out or ROOT/'results'/('layout_ablation_'+datetime.datetime.now(ZoneInfo('Asia/Taipei')).strftime('%Y%m%d_%H%M%S'))
out = out.resolve()
out.mkdir(parents=True, exist_ok=False)
index_dir = a.data_root/'sift100m_diskann_indexes'
default = str(index_dir/'sift100m_l2_R64_L100_pq0_default')
shuffled = str(index_dir/'sift100m_l2_R64_L100_pq0_block_shuffle')
env = dict(os.environ, SEARCH_MEDOIDS=default+'_disk.index_medoids.bin', SEARCH_CENTROIDS=default+'_disk.index_centroids.bin', SEARCH_MODE='baseline', GRAPH_EXPANSION=a.expansion, DISKANN_WRITE_QUERY_STATS='1', PROFILE_HOST='0', TRACE_IO='0', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
commands = []


def run(command, log):
    command = [str(x) for x in command]
    commands.append(command)
    (out/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
    print('Running:', ' '.join(command), flush=True)
    with (out/log).open('w') as f:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, cwd=ROOT)
        for line in process.stdout:
            f.write(line)
            f.flush()
            print(line, end='', flush=True)
        if process.wait():
            raise RuntimeError(f'Command failed; see {out/log}')


run([sys.executable, ROOT/'experiments/layout_ablation/prepare.py', '--index', default+'_disk.index',
     '--vectors', a.data_root/'sift100m_split_shuffled/vectors.bin', '--out', a.layout], 'prepare.log')
checks = verify(default, shuffled, a.layout)
# Existing shuffled data lacks multi-medoid sidecars. Supply mapped sidecars in a
# private prefix so all cases choose the same logical starting node per query.
shuffled_alias = str(out/'shuffled_index')
for suffix in ['_disk.index', '_pq_compressed.bin', '_pq_pivots.bin']:
    Path(shuffled_alias+suffix).symlink_to(shuffled+suffix)
entry_ids = np.asarray(binary(default+'_disk.index_medoids.bin', '<u4'))
entry_centroids = binary(default+'_disk.index_centroids.bin', '<f4')
if entry_ids.shape[1] != 1 or entry_centroids.shape != (len(entry_ids), 128):
    raise ValueError('Invalid native entry-point metadata')
entry_map = binary(shuffled+'_disk.index_block_shuffle_old_to_new.bin', '<u4')[:, 0]
with open(shuffled_alias+'_disk.index_medoids.bin', 'xb') as f:
    f.write(struct.pack('<II', len(entry_ids), 1))
    f.write(entry_map[entry_ids[:, 0]].astype('<u4').tobytes())
Path(shuffled_alias+'_disk.index_centroids.bin').symlink_to(default+'_disk.index_centroids.bin')
checks['entry_medoids'] = entry_ids[:, 0].tolist()
checks['mapped_entry_medoids'] = entry_map[entry_ids[:, 0]].tolist()
(out/'verification.json').write_text(json.dumps(checks, indent=2)+'\n')
manifest = dict(queries=a.queries, repeats=a.repeats, L=a.L, W=a.W, K=10, threads=1,
                graph_expansion=dict(diskann_baseline='node', neighbor_only_identity=a.expansion, traditional_greedy=a.expansion), node_cache=0, profile_host=0, trace_io=0,
                default_index=default, shuffled_index=shuffled, shuffled_search_prefix=shuffled_alias, entry_medoids=entry_ids[:, 0].tolist(), identity_layout=str(a.layout.resolve()),
                platform=platform.platform(), environment={k: env[k] for k in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS']},
                recall_definition='mean intersection of returned top-10 and ground-truth first 10 IDs / 10; no tie extension',
                caveat='Split uses separate experimental I/O driver. Whole-page policy in split and greedy unless --expansion node. Native greedy exact-scores all page residents; split exact-scores selected nodes. Not identical search implementations.')
(out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
run(['cmake', '--build', ROOT/'build', '--target', 'search_disk_index', 'search_split_async', '-j4'], 'build.log')
if a.prepare_only:
    print('Prepared and verified:', out)
    raise SystemExit(0)
query = out/'queries.u8bin'
run([sys.executable, ROOT/'scripts/locality/slice_bin_prefix.py', '--input', a.data_root/'sift100m/bigann_query.u8bin',
     '--output', query, '--count', a.queries, '--dtype', 'uint8'], 'queries.log')
gt = binary(a.data_root/'sift100m/idx_100M.bin', '<u4')[:a.queries, :10]
if gt.shape != (a.queries, 10):
    raise ValueError('Ground truth too small')
rows = []
for repeat in range(a.repeats):
    cases = ['diskann_baseline', 'neighbor_only_identity', 'traditional_greedy']
    cases = cases[repeat % 3:] + cases[:repeat % 3]
    for W in a.W:
        for L in a.L:
            results = {}
            for case in cases:
                tag = f'r{repeat+1}_{case}_L{L}_W{W}'
                if case == 'neighbor_only_identity':
                    output = out/(tag+'.csv')
                    run([ROOT/'build/apps/search_split_async', a.layout/'neighbors.bin', a.layout/'vectors.bin',
                         default+'_pq_compressed.bin', default+'_pq_pivots.bin', query, checks['medoid'], L, W,
                         10, a.queries, output, a.layout/'old_to_new.bin', a.layout/'new_to_old.bin'], tag+'.log')
                    with output.open() as f:
                        raw = list(csv.DictReader(f))
                    ids = np.array([[int(x) for x in r['result_ids'].split()] for r in raw], dtype=np.uint32)
                    latencies = np.array([float(r['total_us']) for r in raw])
                    mean_us = float(latencies.mean())
                    p999_us = float(np.sort(latencies)[min(len(raw)-1, int(.999*len(raw)))])
                    neighbor_total = sum(int(r['neighbor_reads']) for r in raw)
                    vector_total = sum(int(r['vector_reads']) for r in raw)
                    combined_total = 0
                    resident_pq = float(np.mean([int(r['resident_pq_evaluations']) for r in raw]))
                    pq_evaluations = float(np.mean([int(r['pq_evaluations']) for r in raw]))
                    if a.expansion == 'page':
                        assert len(raw) == a.queries
                        # SIFT100M has 15 records/page; only its last page has 10.
                        assert all(15*int(r['neighbor_reads']) - int(r['resident_pq_evaluations']) in (0, 5) for r in raw)
                        assert all(r['graph_expansion'] == 'page' for r in raw)
                else:
                    prefix = default if case == 'diskann_baseline' else shuffled_alias
                    cmd = [ROOT/'build/apps/search_disk_index', '--data_type', 'uint8', '--dist_fn', 'l2',
                           '--index_path_prefix', prefix, '--result_path', out/tag, '--query_file', query,
                           '-K', 10, '-L', L, '-W', W, '-T', 1, '--num_nodes_to_cache', 0]
                    if case == 'traditional_greedy':
                        cmd += ['--result_new_to_old_map', shuffled+'_disk.index_block_shuffle_new_to_old.bin']
                        if a.expansion == 'page':
                            cmd += ['--use_sector_candidates']
                    run(cmd, tag+'.log')
                    ids = np.asarray(binary(str(out/tag)+f'_{L}_idx_uint32.bin', '<u4'))
                    text = (out/(tag+'.log')).read_text()
                    table = text.split('Mean Latency')[-1]
                    numeric = [line.split() for line in table.splitlines() if re.match(r'^\s*\d+\s+\d+\s+', line)]
                    if len(numeric) != 1:
                        raise ValueError('Expected one native summary row')
                    fields = numeric[0]
                    mean_us, p999_us = map(float, [fields[3], fields[4]])
                    with Path(str(out/tag)+f'_{L}_stats.csv').open() as f:
                        native_stats = list(csv.DictReader(f))
                    assert len(native_stats) == a.queries
                    combined_total = sum(int(r['host_reads']) for r in native_stats)
                    assert all(r['host_reads'] == r['host_4k_reads'] for r in native_stats)
                    neighbor_total = vector_total = 0
                    resident_pq = pq_evaluations = ''
                if ids.shape != (a.queries, 10):
                    raise ValueError(f'Incomplete results: {case}')
                total_reads = neighbor_total + vector_total + combined_total
                ios = total_reads / a.queries
                recall = 100*sum(len(set(x) & set(y)) for x, y in zip(ids, gt))/(a.queries*10)
                results[case] = ids
                rows.append(dict(repeat=repeat+1, case=case, L=L, W=W, queries=a.queries, expansion='node' if case == 'diskann_baseline' else a.expansion,
                                 total_host_reads=total_reads, mean_neighbor_reads=neighbor_total/a.queries,
                                 mean_vector_reads=vector_total/a.queries, mean_combined_reads=combined_total/a.queries,
                                 mean_resident_pq=resident_pq, mean_pq_evaluations=pq_evaluations,
                                 recall_at_10_pct=recall, mean_us=mean_us, p999_us=p999_us,
                                 inverse_mean_qps=1e6/mean_us, mean_host_reads=ios, mean_host_bytes=ios*4096))
                with (out/'summary.csv').open('w') as f:
                    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
            agreements = {case: float(np.mean(np.all(ids == results['diskann_baseline'], axis=1)))
                          for case, ids in results.items()}
            (out/f'r{repeat+1}_L{L}_W{W}_agreement.json').write_text(json.dumps(agreements, indent=2)+'\n')
report(out)
print('Completed. Summary:', out/'summary.csv')
