#!/usr/bin/env python3
"""Run A/B/C/D100/D40 and E host traversal; no SSD-time assumption is measured."""
import argparse
import csv
import hashlib
import json
import os
import pwd
import shutil
import struct
import subprocess
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CASES = {
    'A': {'layout': 'native_default', 'expansion': 'node', 'mode': 'native'},
    'B': {'layout': 'native_bnf', 'expansion': 'page', 'mode': 'native'},
    'C': {'layout': 'split_identity', 'expansion': 'page', 'mode': 'deferred', 'percent': 100},
    'D100': {'layout': 'split_bnf', 'expansion': 'page', 'mode': 'deferred', 'percent': 100},
    'D40': {'layout': 'split_bnf', 'expansion': 'page', 'mode': 'deferred', 'percent': 40},
    'E_host': {'layout': 'split_bnf', 'expansion': 'page', 'mode': 'traverse_only'},
}


def binary(path, dtype):
    with Path(path).open('rb') as f:
        n, d = struct.unpack('<II', f.read(8))
    if Path(path).stat().st_size != 8+n*d*np.dtype(dtype).itemsize:
        raise ValueError(f'Invalid bin size: {path}')
    return np.memmap(path, mode='r', dtype=dtype, offset=8, shape=(n, d))


def save_csv(path, rows):
    with path.open('w') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--queries', type=int, default=10000)
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--L', type=int, nargs='+', default=[60, 120])
    p.add_argument('--W', type=int, nargs='+', default=[8, 16, 32])
    p.add_argument('--cases', nargs='+', choices=list(CASES), default=list(CASES))
    p.add_argument('--trace-block', action='store_true')
    p.add_argument('--data-root', type=Path, default=Path('/home/emmanuel/projects/data'))
    p.add_argument('--identity', type=Path, default=ROOT/'results/layout_ablation_assets/sift100m_identity')
    p.add_argument('--shuffled', type=Path)
    a = p.parse_args()
    if not 1 <= a.queries <= 10000 or a.repeats < 1 or min(a.L) < 10 or not all(1 <= w <= 128 for w in a.W):
        p.error('Use 1..10000 queries, L>=10, 1<=W<=128, repeats>=1')
    if len(set(a.cases)) != len(a.cases): p.error('Duplicate cases')
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    data = a.data_root.resolve()
    identity = a.identity.resolve()
    shuffled = (a.shuffled or data/'sift100m_split_shuffled').resolve()
    index = str(data/'sift100m_diskann_indexes/sift100m_l2_R64_L100_pq0_default')
    bnf = str(data/'sift100m_diskann_indexes/sift100m_l2_R64_L100_pq0_block_shuffle')
    mapped = str(out/'native_bnf')
    base_env = dict(os.environ, OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    commands = []

    def execute(cmd, log, env=None):
        cmd = list(map(str, cmd))
        commands.append(cmd)
        (out/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
        print('Running:', ' '.join(cmd), flush=True)
        with log.open('w') as f:
            proc = subprocess.Popen(cmd, cwd=ROOT, env=env or base_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                f.write(line); f.flush(); print(line, end='', flush=True)
            if proc.wait(): raise RuntimeError(f'Failed: see {log}')

    if a.trace_block:
        if not shutil.which('trace-cmd'): raise RuntimeError('trace-cmd is required')
        subprocess.run(['sudo', '-v'], check=True)
        (out/'devices.txt').write_text(subprocess.check_output(['lsblk', '-o', 'NAME,MAJ:MIN,TYPE,PKNAME,START'], text=True))
    execute(['cmake', '--build', ROOT/'build', '--target', 'search_disk_index', 'search_split_async', '-j4'], out/'build.log')
    if 'C' in a.cases:
        execute([sys.executable, ROOT/'experiments/layout_ablation/prepare.py', '--index', index+'_disk.index',
                 '--vectors', shuffled/'vectors.bin', '--out', identity], out/'identity.log')
    entries = binary(index+'_disk.index_medoids.bin', '<u4')
    if entries.shape[1] != 1: raise ValueError('Bad medoid file')
    if 'B' in a.cases:
        for suffix in ['_disk.index', '_pq_compressed.bin', '_pq_pivots.bin']:
            Path(mapped+suffix).symlink_to(bnf+suffix)
        mapping = binary(bnf+'_disk.index_block_shuffle_old_to_new.bin', '<u4')[:, 0]
        with open(mapped+'_disk.index_medoids.bin', 'xb') as f:
            f.write(struct.pack('<II', len(entries), 1)); f.write(mapping[entries[:, 0]].astype('<u4').tobytes())
        Path(mapped+'_disk.index_centroids.bin').symlink_to(index+'_disk.index_centroids.bin')
    query = out/'queries.u8bin'
    execute([sys.executable, ROOT/'scripts/locality/slice_bin_prefix.py', '--input', data/'sift100m/bigann_query.u8bin',
             '--output', query, '--count', a.queries, '--dtype', 'uint8'], out/'queries.log')
    gt = binary(data/'sift100m/idx_100M.bin', '<u4')[:a.queries, :10]
    manifest = dict(queries=a.queries, repeats=a.repeats, L=a.L, W=a.W, K=10, cases={c: CASES[c] for c in a.cases},
                    trace_block=a.trace_block, threads=1, node_cache=0, entry_medoids=entries[:, 0].tolist(),
                    query=str(query), gt=str(data/'sift100m/idx_100M.bin'), default_index=index,
                    identity_layout=str(identity), shuffled_layout=str(shuffled),
                    source_sha256={f: hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in
                                   ['experiments/split_async/search.cpp', 'src/pq_flash_index.cpp', 'apps/search_disk_index.cpp']},
                    D_policy='Unique beam-selected nodes across traversal, ranked by PQ distance then ID; read min(N,max(K,ceil(N*percent/100))) after traversal; no vector-page dedup',
                    E_model='Unknown X per query: T_E = T_host_traversal + X only under serial/non-overlapping residual-cost model. X includes unmeasured SSD work and result delivery. E end-to-end p95 and recall unknown.',
                    baseline_policy='A selected-node expansion; B/C/D/E full-page expansion. B exact-scores page residents, split exact-scores selected candidates.')
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    jobs=[]; summaries=[]
    for repeat in range(1, a.repeats+1):
        rotation=(repeat-1) % len(a.cases)
        order=a.cases[rotation:]+a.cases[:rotation]
        for W in a.W:
            for L in a.L:
                for case in order:
                    cfg=CASES[case];native=cfg['mode']=='native'
                    folder=out/f'r{repeat}_{case}_L{L}_W{W}';folder.mkdir()
                    overrides=dict(OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
                                   DISKANN_WRITE_QUERY_STATS='1', PROFILE_HOST='0', TRACE_IO=str(int(a.trace_block)),
                                   GRAPH_EXPANSION=cfg['expansion'], SEARCH_MODE=cfg['mode'],
                                   RERANK_PERCENT=str(cfg.get('percent',100)), VECTOR_QD=str(W),
                                   SEARCH_MEDOIDS=index+'_disk.index_medoids.bin', SEARCH_CENTROIDS=index+'_disk.index_centroids.bin')
                    if native:
                        prefix=index if case=='A' else mapped
                        files={'combined':str(Path(prefix+'_disk.index').resolve())}
                        cmd=[ROOT/'build/apps/search_disk_index','--data_type','uint8','--dist_fn','l2',
                             '--index_path_prefix',prefix,'--query_file',query,'--result_path',folder/'search',
                             '-K',10,'-L',L,'-W',W,'-T',1,'--num_nodes_to_cache',0]
                        if case=='B': cmd += ['--use_sector_candidates','--result_new_to_old_map',bnf+'_disk.index_block_shuffle_new_to_old.bin']
                        if a.trace_block:
                            cmd += ['--trace_access_csv',folder/'access.csv','--trace_stats_csv',folder/'iterations.csv',
                                    '--trace_sample_rate',1,'--trace_max_queries',a.queries]
                    else:
                        layout=identity if case=='C' else shuffled
                        meta=json.loads((layout/'layout.json').read_text())
                        files={'neighbor':str((layout/'neighbors.bin').resolve())}
                        if case!='E_host':files['vector']=str((layout/'vectors.bin').resolve())
                        cmd=[ROOT/'build/apps/search_split_async',layout/'neighbors.bin',layout/'vectors.bin',
                             index+'_pq_compressed.bin',index+'_pq_pivots.bin',query,meta['medoid'],L,W,10,a.queries,
                             folder/'queries.csv',layout/'old_to_new.bin',layout/'new_to_old.bin']
                    job=dict(case=case,repeat=repeat,L=L,W=W,queries=a.queries,native=native,files=files,folder=folder.name,env=overrides,complete=False)
                    jobs.append(job);(out/'jobs.json').write_text(json.dumps(jobs,indent=2)+'\n')
                    if a.trace_block:
                        for kind,path in files.items():
                            (folder/f'{kind}.extents.before.txt').write_text(subprocess.check_output(['filefrag','-v','-b512',path],text=True))
                            (folder/f'{kind}.mount.txt').write_text(subprocess.check_output(['findmnt','-T',path,'-o','SOURCE,FSTYPE,TARGET'],text=True))
                        cmd=['sudo','trace-cmd','record','-C','mono','-b','16384','-o',folder/'block.dat',
                             '-e','block:block_rq_issue','-e','block:block_rq_complete',
                             'sudo','-u',pwd.getpwuid(os.getuid()).pw_name,'env',*[f'{k}={v}' for k,v in overrides.items()],*cmd]
                    execute(cmd,folder/'run.log',dict(base_env,**overrides))
                    if a.trace_block:
                        with (folder/'block.txt').open('w') as f, (folder/'report.log').open('w') as e:
                            subprocess.run(['sudo','trace-cmd','report','-i',str(folder/'block.dat')],stdout=f,stderr=e,check=True)
                        for kind,path in files.items():
                            (folder/f'{kind}.extents.after.txt').write_text(subprocess.check_output(['filefrag','-v','-b512',path],text=True))
                    source=folder/(f'search_{L}_stats.csv' if native else 'queries.csv')
                    with source.open() as f: raw=list(csv.DictReader(f))
                    if len(raw)!=a.queries or [int(r['query_id']) for r in raw]!=list(range(a.queries)):raise ValueError('Incomplete query results')
                    elapsed=np.array([float(r['total_us']) for r in raw])/1000
                    if native:
                        ids=binary(folder/f'search_{L}_idx_uint32.bin','<u4')
                        combined=np.mean([int(r['host_reads']) for r in raw]);neighbor=vector=0
                    else:
                        ids=None if case=='E_host' else [[int(x) for x in r['result_ids'].split()] for r in raw]
                        neighbor=np.mean([int(r['neighbor_reads']) for r in raw]);vector=np.mean([int(r['vector_reads']) for r in raw]);combined=0
                    if ids is not None and (len(ids)!=a.queries or any(len(x)!=10 for x in ids)):raise ValueError('Incomplete top-10')
                    recall='' if ids is None else 100*sum(len(set(x)&set(y)) for x,y in zip(ids,gt))/(10*a.queries)
                    summaries.append(dict(case=case,repeat=repeat,L=L,W=W,queries=a.queries,trace_block=int(a.trace_block),
                                          mean_neighbor_reads=neighbor,mean_vector_reads=vector,mean_combined_reads=combined,
                                          mean_host_reads=neighbor+vector+combined,mean_host_bytes=4096*(neighbor+vector+combined),
                                          recall_at_10_pct=recall,query_mean_ms='' if case=='E_host' else elapsed.mean(),
                                          query_p95_ms='' if case=='E_host' else np.percentile(elapsed,95),
                                          host_traversal_mean_ms=elapsed.mean() if case=='E_host' else '',
                                          host_traversal_p95_ms=np.percentile(elapsed,95) if case=='E_host' else '',
                                          E_unknown='X' if case=='E_host' else ''))
                    save_csv(out/'query_summary.csv',summaries)
                    job['complete']=True;(out/'jobs.json').write_text(json.dumps(jobs,indent=2)+'\n')
    # Check the controlled D/E comparison after measurement, outside query timing.
    checks=[]
    for repeat in range(1,a.repeats+1):
        for W in a.W:
            for L in a.L:
                control={}
                for case in ('D100','D40','E_host'):
                    if case not in a.cases:continue
                    with (out/f'r{repeat}_{case}_L{L}_W{W}'/'queries.csv').open() as f:
                        control[case]=list(csv.DictReader(f))
                    for r in control[case]:
                        if case=='E_host':
                            if int(r['vector_reads']) or r['result_ids']:
                                raise ValueError('E_host unexpectedly performed exact search')
                        else:
                            pool=int(r['rerank_pool']);percent=CASES[case]['percent']
                            keep=min(pool,max(10,(pool*percent+99)//100))
                            if int(r['rerank_selected'])!=keep or int(r['vector_reads'])!=keep:
                                raise ValueError('Deferred rerank count mismatch')
                if len(control)>1:
                    reference=next(iter(control.values()))
                    keys=['neighbor_reads','resident_pq_evaluations','pq_evaluations','selected_nodes','beam_count']
                    for case,raw in control.items():
                        if any(x[k]!=y[k] for x,y in zip(reference,raw) for k in keys):
                            raise ValueError(f'D/E traversal counters differ: {case}, L={L}, W={W}')
                checks.append(dict(repeat=repeat,L=L,W=W,cases=list(control),status='passed',
                                   scope='Traversal counters and exact selection counts; not full sequence equality'))
    (out/'consistency.json').write_text(json.dumps(checks,indent=2)+'\n')
    print('Finished:',out/'query_summary.csv')
    if a.trace_block:print('Analyze block latency: python3 experiments/abcd/analyze_block.py',out)


if __name__=='__main__':main()
