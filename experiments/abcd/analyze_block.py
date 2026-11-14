#!/usr/bin/env python3
"""Summarize block issue->complete means for captured A/B/C/D/E-host runs.
Uses the same conservative sector-count matching for native and split layouts.
Only unambiguous 4 KiB pairs on expected file sectors are accepted. This is
aggregate matching, not a per-query latency assignment or a NAND measurement.
"""
import argparse
from array import array
from bisect import bisect_right
from collections import Counter
import csv
import json
from pathlib import Path
import re
import numpy as np


def extents(path):
    out=[]
    for line in path.read_text().splitlines():
        m=re.match(r'\s*\d+:\s*(\d+)\.\.\s*(\d+):\s*(\d+)\.\.\s*(\d+):',line)
        if not m:continue
        a,b,c,d=map(int,m.groups())
        if b-a!=d-c:raise ValueError('Nonlinear extent mapping')
        if out and out[-1][1]+1==a and out[-1][3]+1==c:out[-1]=(out[-1][0],b,out[-1][2],d)
        else:out.append((a,b,c,d))
    if not out:raise ValueError(f'No extents in {path}')
    return out


def read_csv(path):
    with path.open() as f:return list(csv.DictReader(f))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);a=p.parse_args()
    root=a.root.resolve();manifest=json.loads((root/'manifest.json').read_text())
    if not manifest['trace_block']:raise ValueError('This run did not capture block events')
    devices={}
    for line in (root/'devices.txt').read_text().splitlines()[1:]:
        f=line.split();devices[f[0].lstrip('├─└│')]=f[1:]
    pattern=re.compile(r'^\s*(.+)-(\d+)\s+\[\d+\].*?\s(\d+)\.(\d+): block_rq_(issue|complete):\s+(\d+,\d+)\s+(\S+)\s+.*?(\d+) \+ (\d+)')
    summaries=[];audits=[]
    for job in json.loads((root/'jobs.json').read_text()):
        if not job['complete']:raise ValueError(f"Incomplete job: {job['folder']}")
        folder=root/job['folder'];print('Analyzing',folder.name,flush=True)
        mappings={}
        for kind in job['files']:
            before=extents(folder/f'{kind}.extents.before.txt');after=extents(folder/f'{kind}.extents.after.txt')
            if before!=after:raise ValueError(f'{folder}: extents changed')
            mount=(folder/f'{kind}.mount.txt').read_text().splitlines()[1].split()[0]
            fields=devices[Path(mount).name]
            if fields[1]=='part':device=devices[fields[2]][0].replace(':',',');start=int(fields[3])
            elif fields[1]=='disk':device=fields[0].replace(':',',');start=0
            else:raise ValueError('Only plain disks/partitions supported; inspect device mapping')
            mappings[kind]=(before,[x[0] for x in before],device,start)
        def physical(kind,byte_offset):
            extent,starts,device,offset=mappings[kind];s=byte_offset//512;i=bisect_right(starts,s)-1
            if i<0 or s+7>extent[i][1]:raise ValueError('Unmapped request or extent-crossing request')
            return (device,extent[i][2]+s-extent[i][0]+offset)
        expected=Counter();kinds={}
        if job['native']:
            source=folder/'access.csv'
            with source.open() as f:
                for r in csv.DictReader(f):
                    key=physical('combined',int(r['sector_id'])*4096);expected[key]+=1;kinds[key]='combined'
            raw=read_csv(folder/f"search_{job['L']}_stats.csv")
            host_total=sum(int(r['host_reads']) for r in raw)
        else:
            with (folder/'queries.csv.io.csv').open() as f:
                for r in csv.DictReader(f):
                    if int(r['bytes'])!=4096:raise ValueError('Expected 4 KiB host requests')
                    key=physical(r['kind'],int(r['file_offset']))
                    if key in kinds and kinds[key]!=r['kind']:raise ValueError('Physical sectors overlap between files')
                    expected[key]+=1;kinds[key]=r['kind']
            raw=read_csv(folder/'queries.csv')
            host_total=sum(int(r['neighbor_reads'])+int(r['vector_reads']) for r in raw)
        if len(raw)!=job['queries'] or host_total!=sum(expected.values()):raise ValueError('Host trace/stats counts differ')
        device_ids={d:i for i,d in enumerate(sorted({k[0] for k in expected}))}
        active={};issued=Counter();pair_dev=array('I');pair_sector=array('Q');pair_latency=array('d')
        lost=ambiguous=unpaired=bad=0
        with (folder/'block.txt').open() as f:
            for line in f:
                if 'LOST' in line.upper():lost+=1
                if 'block_rq_' not in line:continue
                m=pattern.search(line)
                if not m or not m[7].startswith('R') or int(m[9])!=8:continue
                key=(m[6],int(m[8]))
                if key not in expected:continue
                t=int(m[3])*10**9+int(m[4].ljust(9,'0'))
                if m[5]=='issue':
                    target=m[1].strip().startswith(('search_disk','search_split'))
                    if target:issued[key]+=1
                    if key in active:active[key]=(None,False,active[key][2]+1);ambiguous+=1
                    else:active[key]=(t,target,1)
                else:
                    prior=active.get(key)
                    if prior is None:unpaired+=1;continue
                    start,target,pending=prior
                    if pending>1:active[key]=(None,False,pending-1)
                    else:del active[key]
                    if start is not None and target:
                        if t<start or not line.rstrip().endswith('[0]'):bad+=1;continue
                        pair_dev.append(device_ids[key[0]]);pair_sector.append(key[1]);pair_latency.append((t-start)/1000)
        devnames={v:k for k,v in device_ids.items()}
        mismatch={key for key,count in expected.items() if issued[key]!=count}
        accepted={kind:array('d') for kind in job['files']}
        for dev,sector,latency in zip(pair_dev,pair_sector,pair_latency):
            key=(devnames[dev],sector)
            if key not in mismatch:accepted[kinds[key]].append(latency)
        requests=Counter()
        for key,count in expected.items():requests[kinds[key]]+=count
        all_values=array('d')
        for values in accepted.values():all_values.extend(values)
        accepted['all']=all_values;requests['all']=host_total
        diagnostics=bool((folder/'report.log').stat().st_size)
        for kind,values in accepted.items():
            measured=np.asarray(values);valid=not lost and not diagnostics and len(measured)>0
            summaries.append(dict(case=job['case'],repeat=job['repeat'],L=job['L'],W=job['W'],kind=kind,
                                  host_requests=requests[kind],matched_requests=len(measured),
                                  matched_pct=100*len(measured)/requests[kind] if requests[kind] else '',
                                  block_mean_us=float(measured.mean()) if valid else '',
                                  block_p95_us=float(np.percentile(measured,95)) if valid else '',
                                  status='matched_subset' if valid else 'invalid_or_no_samples',
                                  SSD_internal_cost='X (unmeasured)' if job['case']=='E_host' else ''))
        audits.append(dict(folder=folder.name,extent_mapping_unchanged=True,lost_lines=lost,
                           report_diagnostics=diagnostics,ambiguous_issues=ambiguous,unpaired_completions=unpaired,
                           error_pairs=bad,active_at_end=len(active),count_mismatch_sectors=len(mismatch),
                           excluded_requests_on_mismatched_sectors=sum(expected[k] for k in mismatch)))
        with (root/'block_summary.csv').open('w') as f:
            w=csv.DictWriter(f,fieldnames=list(summaries[0]));w.writeheader();w.writerows(summaries)
        (root/'block_audit.json').write_text(json.dumps(audits,indent=2)+'\n')
        print('Accepted',len(all_values),'/',host_total,flush=True)
    print('Saved:',root/'block_summary.csv')


if __name__=='__main__':main()
