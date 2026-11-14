#!/usr/bin/env python3
"""Analyze native DiskANN block traces against the actual search sector multiset.
No experiment is launched. All accepted latency samples are unambiguous 4 KiB
issue/complete pairs on index sectors, issued by search_disk_ind. A sector is
excluded if its observed issue count differs from access.csv. No per-query
block timestamps are inferred from this aggregate matching.
"""
import argparse, bisect, csv, json, re, struct
from array import array
from collections import Counter
from pathlib import Path
import numpy as np


def extents(path):
    out=[]
    for line in path.read_text().splitlines():
        m=re.match(r'\s*\d+:\s*(\d+)\.\.\s*(\d+):\s*(\d+)\.\.\s*(\d+):',line)
        if m:
            a,b,c,d=map(int,m.groups())
            if b-a != d-c: raise ValueError('Nonlinear extent')
            if out and a==out[-1][1]+1 and c==out[-1][3]+1:
                out[-1]=(out[-1][0],b,out[-1][2],d)
            else: out.append((a,b,c,d))
    if not out: raise ValueError('No extents')
    return out


def analyze(root, old, gtfile):
    before=extents(root/'index.extents.before.txt');after=extents(root/'index.extents.after.txt')
    if before!=after: raise ValueError('Index extent mapping changed')
    mount=(root/'index.mount.txt').read_text().splitlines()[1].split()[0]
    devices={}
    for line in (root/'devices.txt').read_text().splitlines()[1:]:
        fields=line.split();name=fields[0].lstrip('├─└│')
        devices[name]=fields[1:]
    dev=devices[Path(mount).name]
    if dev[1]!='part': raise ValueError('Only recorded plain partitions are supported')
    parent=devices[dev[2]];device=parent[0].replace(':',',');partition_start=int(dev[3])
    starts=[x[0] for x in before]
    def physical(page):
        s=page*8;i=bisect.bisect_right(starts,s)-1
        if i<0 or s+7>before[i][1]: raise ValueError('Page crosses/misses extent')
        return before[i][2]+s-before[i][0]+partition_start
    with gtfile.open('rb') as f:
        gn,gd=struct.unpack('<II',f.read(8))
    gt=np.memmap(gtfile,dtype='<u4',mode='r',offset=8,shape=(gn,gd))[:,:10]
    pattern=re.compile(r'^\s*(.+)-(\d+)\s+\[\d+\].*?\s(\d+)\.(\d+): block_rq_(issue|complete):\s+(\d+,\d+)\s+(\S+)\s+.*?(\d+) \+ (\d+)')
    summaries=[]
    for L in (20,60,120):
        for W in (8,16,32):
            run=root/f'L{L}_W{W}'
            print(f'Analyzing {run.name}',flush=True)
            stats=list(csv.DictReader((run/f'search_{L}_stats.csv').open()))
            nq=len(stats)
            if nq!=10000 or [int(x['query_id']) for x in stats]!=list(range(nq)):raise ValueError('Incomplete query stats')
            counts=Counter();perquery=Counter()
            with (run/'access.csv').open() as f:
                for r in csv.DictReader(f):
                    if r['use_sector_candidates']!='0' or r['num_nodes_to_cache']!='0' or not r['index_path_prefix'].endswith('_default'):raise ValueError('Not native default settings')
                    counts[physical(int(r['sector_id']))]+=1;perquery[int(r['query_id'])]+=1
            if any(perquery[i]!=int(stats[i]['host_reads']) for i in range(nq)):raise ValueError('Host/access count mismatch')
            io_sum=0;iteration_reads=0
            with (run/'iterations.csv').open() as f:
                for r in csv.DictReader(f):io_sum+=float(r['io_us']);iteration_reads+=int(r['issued_reads'])
            if iteration_reads!=sum(counts.values()):raise ValueError('Iteration read mismatch')
            active={};issued=Counter();pair_sectors=array('Q');pair_us=array('d')
            lost=0;ambiguous_issues=0;unpaired=0;bad=0;pids=set()
            with (run/'block.txt').open() as f:
                for line in f:
                    if 'LOST' in line.upper():lost+=1
                    if 'block_rq_' not in line or device+' R' not in line:continue
                    m=pattern.search(line)
                    if not m or m[6]!=device or not m[7].startswith('R'):continue
                    sec=int(m[8]);length=int(m[9])
                    if length!=8 or sec not in counts:continue
                    t=int(m[3])*10**9+int(m[4].ljust(9,'0'))
                    if m[5]=='issue':
                        target=m[1].strip().startswith('search_disk_ind')
                        if target:issued[sec]+=1;pids.add(int(m[2]))
                        if sec in active:
                            active[sec]=(None,False,active[sec][2]+1);ambiguous_issues+=1
                        else:active[sec]=(t,target,1)
                    else:
                        a=active.get(sec)
                        if a is None:unpaired+=1;continue
                        start,target,pending=a
                        if pending>1:active[sec]=(None,False,pending-1)
                        else:del active[sec]
                        if start is not None and target:
                            if t<start or not line.rstrip().endswith('[0]'):bad+=1;continue
                            pair_sectors.append(sec);pair_us.append((t-start)/1000)
            if lost or (run/'report.log').stat().st_size:
                raise ValueError(f'{run}: lost events or nonempty trace report diagnostics; inspect before publishing')
            mismatch={s for s,c in counts.items() if issued[s]!=c}
            valid=np.fromiter((s not in mismatch for s in pair_sectors),dtype=bool,count=len(pair_sectors))
            durations=np.asarray(pair_us)[valid]
            ids=np.fromfile(run/f'search_{L}_idx_uint32.bin',dtype='<u4')
            if tuple(ids[:2])!=(nq,10) or len(ids)!=2+nq*10:raise ValueError('Incomplete top-10 IDs')
            ids=ids[2:].reshape(nq,10)
            recall=100*sum(len(set(a)&set(b)) for a,b in zip(ids,gt))/(nq*10)
            result=dict(L=L,W=W,queries=nq,host_reads=sum(counts.values()),mean_reads=sum(counts.values())/nq,
                        matched_requests=len(durations),matched_pct=100*len(durations)/sum(counts.values()),
                        block_mean_us=float(durations.mean()) if len(durations) else None,
                        block_p95_us=float(np.percentile(durations,95)) if len(durations) else None,
                        host_reader_ms=io_sum/nq/1000,query_mean_ms=sum(float(x['total_us']) for x in stats)/nq/1000,
                        recall_at_10_pct=recall,extent_mapping_unchanged=True,lost_lines=lost,
                        sectors_count_mismatch=len(mismatch),requests_on_mismatched_sectors=sum(counts[s] for s in mismatch),
                        ambiguous_issues=ambiguous_issues,unpaired_completions=unpaired,error_pairs=bad,
                        active_at_end=len(active),issue_pids=sorted(pids))
            summaries.append(result)
            (root/'native_block_summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
            print(json.dumps(result),flush=True)
    with (root/'native_block_summary.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(summaries[0]));w.writeheader();w.writerows(summaries)
    old_io={(r['mode'],r['L'],r['W'],r['kind']):r for r in json.loads((old/'io_summary.json').read_text())}
    old_q={(r['mode'],r['L'],r['W']):r for r in json.loads((old/'query_summary.json').read_text())}
    lines=['# 原始 DiskANN baseline 與既有 H/T block latency','','B = 原始 default layout、10 nodes/page、逐節點展開；H/T 使用既有 split＋shuffle 實驗。每組 10,000 queries。','','B latency 為成功配對的 combined vector＋neighbors 4 KiB requests 之 issue→complete 平均。H/T 值取自先前的 block trace 分析，兩批不是同期交錯測量。','','| L | W | B reads/query | B combined latency μs | H neighbor μs | H vector μs | T neighbor μs | B 配對率 |','|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in summaries:
        L,W=r['L'],r['W']
        h=old_io['host_worker',L,W,'neighbor']['block_mean_us'];v=old_io['host_worker',L,W,'vector']['block_mean_us'];t=old_io['traverse_only',L,W,'neighbor']['block_mean_us']
        lines.append(f"| {L} | {W} | {r['mean_reads']:.2f} | {r['block_mean_us']:.1f} | {h:.1f} | {v:.1f} | {t:.1f} | {r['matched_pct']:.3f}% |")
    lines+=['','| L | W | B host reader ms/query | H 主 thread io.wait ms/query | T io.wait ms/query |','|---:|---:|---:|---:|---:|']
    for r in summaries:
        L,W=r['L'],r['W'];h=old_q['host_worker',L,W]['wait_us']/1000;t=old_q['traverse_only',L,W]['wait_us']/1000
        lines.append(f"| {L} | {W} | {r['host_reader_ms']:.3f} | {h:.3f} | {t:.3f} |")
    lines+=['','B host reader 包含提交及等待，H/T 為 Batch::wait 的累積；H 不含 worker_wait_us，不能把三欄視為完全相同的計時定義。','','配對方式：filefrag 512-byte extent ＋記錄的 partition start → parent disk sector；核對 access.csv 與逐 query stats；保留 search_disk_ind 在預期 sector 發出的 4 KiB reads，配對同 sector 的唯一未完成 issue。sector 的 issue 總數與搜尋 access 次數不一致時整個 sector 排除；重疊的同 sector requests 不推測配對。此法取得 aggregate request latency，沒有聲稱逐 query block 時間窗配對。','','latency 不含 issue 前排隊；不是 NAND latency。Trace 與存取記錄輸出有量測開銷，且 B 與舊 H/T 的搜尋起點設定／量測時間不同；不能單靠此表推導模式加速比。','']
    (root/'comparison_native_B.md').write_text('\n'.join(lines))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('root',type=Path)
    p.add_argument('--old',type=Path,default=Path('/home/emmanuel/projects/nvmevirt-mqsim/results/split_async_diagnosis/10000'))
    p.add_argument('--gt',type=Path,default=Path('/home/emmanuel/projects/data/sift100m/idx_100M.bin'))
    a=p.parse_args();analyze(a.root,a.old,a.gt)
