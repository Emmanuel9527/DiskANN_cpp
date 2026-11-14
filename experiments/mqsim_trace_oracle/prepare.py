#!/usr/bin/env python3
"""Join timestamped SIFT100M application requests with unique block pairs."""
import argparse,bisect,csv,hashlib,json,re
from collections import defaultdict,Counter
from pathlib import Path
import numpy as np
P=re.compile(r'^\s*(.+)-(\d+)\s+\[\d+\].*?\s(\d+)\.(\d+): block_rq_(issue|complete):\s+(\d+,\d+)\s+(\S+)\s+.*?(\d+) \+ (\d+)')
def extents(p):
 out=[]
 for l in p.read_text().splitlines():
  m=re.match(r'\s*\d+:\s*(\d+)\.\.\s*(\d+):\s*(\d+)\.\.\s*(\d+):',l)
  if m:
   a,b,c,d=map(int,m.groups());assert b-a==d-c;out.append((a,b,c,d))
 assert out;return out

def prepare(root,out,L,W,n):
 run=root/f'r1_E_host_L{L}_W{W}';dest=out/f'L{L}_W{W}';dest.mkdir(parents=True,exist_ok=True)
 before=extents(run/'neighbor.extents.before.txt');assert before==extents(run/'neighbor.extents.after.txt')
 assert '/dev/nvme0n1p2' in (run/'neighbor.mount.txt').read_text()
 devices=(root/'devices.txt').read_text();assert re.search(r'nvme0n1p2\s+259:2\s+part\s+nvme0n1\s+2203648',devices)
 starts=[a[0] for a in before]
 def phys(offset):
  s=offset//512;i=bisect.bisect_right(starts,s)-1;assert i>=0 and s+7<=before[i][1]
  return before[i][2]+s-before[i][0]+2203648
 app=[]
 with (run/'queries.csv.io.csv').open() as f:
  for r in csv.DictReader(f):
   if int(r['query'])>=n:break
   assert r['kind']=='neighbor' and int(r['bytes'])==4096
   app.append({k:int(v) for k,v in r.items() if k!='kind'})
 assert app
 keys={phys(r['file_offset']) for r in app};pid=app[0]['pid'];assert all(r['pid']==pid for r in app)
 end=max(r['completion_observed_ns'] for r in app)+1000000
 begin=min(r['submit_begin_ns'] for r in app)-1000000
 active={};pairs=defaultdict(list);bad=Counter();background=[];allactive=defaultdict(list)
 assert (run/'report.log').stat().st_size==0
 # Scan full report to detect lost events, but only retain selected sample's interval.
 with (run/'block.txt').open() as f:
  for l in f:
   if 'LOST' in l.upper():raise ValueError('Lost events')
   if 'block_rq_' not in l:continue
   m=P.search(l)
   if not m or m[6]!='259,0':continue
   t=int(m[3])*10**9+int(m[4].ljust(9,'0'))
   if not begin<=t<=end:continue
   sec,length=int(m[8]),int(m[9]);key=(sec,length,m[7][0])
   if m[5]=='issue':allactive[key].append((t,int(m[2])==pid))
   elif allactive[key]:
    bt,target=allactive[key].pop(0)
    if not target:background.append((bt,t))
   if sec not in keys or length!=8 or not m[7].startswith('R'):continue
   if m[5]=='issue':
    if sec in active:bad['overlapping_sector']+=1;active[sec].append((t,int(m[2])==pid,True));active[sec][0]=(active[sec][0][0],active[sec][0][1],True)
    else:active[sec]=[(t,int(m[2])==pid,False)]
   elif sec in active:
    s,target,ambiguous=active[sec].pop(0)
    if not active[sec]:del active[sec]
    if target and not ambiguous and l.rstrip().endswith('[0]'):pairs[sec].append((s,t))
 matched=defaultdict(list);reasons=Counter();used=set()
 for r in app:
  sec=phys(r['file_offset']);cand=[(i,c) for i,c in pairs[sec] if r['submit_begin_ns']-1000<=i<=r['submit_end_ns']+1000 and c<=r['completion_observed_ns']+1000]
  if len(cand)!=1:reasons[(r['query'],'unmatched_or_ambiguous')]+=1;continue
  i,c=cand[0]
  if (sec,i,c) in used:reasons[(r['query'],'reused_pair')]+=1;continue
  used.add((sec,i,c));matched[r['query']].append(dict(r,sector=sec,issue=i,complete=c))
 stats={int(r['query_id']):r for r in csv.DictReader((run/'queries.csv').open()) if int(r['query_id'])<n}
 groups=[];gaps=[];excluded={};count=Counter(r['query'] for r in app)
 for q in range(n):
  rows=matched[q]
  if len(rows)!=count[q] or any(x[0]==q for x in reasons):excluded[q]='request matching incomplete';continue
  assert len(rows)==int(stats[q]['neighbor_reads']) and int(stats[q]['vector_reads'])==0
  beams=defaultdict(list)
  for r in rows:beams[r['beam']].append(r)
  batches=[];valid=True
  for beam,rr in sorted(beams.items()):
   rr.sort(key=lambda r:(r['issue'],r['request']));start=min(r['issue'] for r in rr);finish=max(r['complete'] for r in rr)
   if batches and start<batches[-1]['finish']:valid=False
   batches.append(dict(beam=beam,start=start,finish=finish,rows=rr))
  if not valid:excluded[q]='overlapping beams';continue
  duration=batches[-1]['finish']-batches[0]['start'];outside=round(float(stats[q]['total_us'])*1000)-duration
  if outside<0:excluded[q]='query timer inconsistency';continue
  groups.append((q,batches,outside))
  for a,b in zip(batches,batches[1:]):
   c=a['finish'];s=b['start'];submit=min(r['submit_begin_ns'] for r in b['rows']);obs=max(r['completion_observed_ns'] for r in a['rows'])
   gaps.append(dict(query=q,beam=a['beam'],next_beam=b['beam'],last_complete_ns=c,next_issue_ns=s,gap_ns=s-c,complete_to_observed_ns=obs-c,observed_to_submit_ns=submit-obs,submit_to_issue_ns=s-submit,background_overlap=any(x<s and y>c for x,y in background)))
 with (dest/'gaps.csv').open('w') as f:
  w=csv.DictWriter(f,fieldnames=list(gaps[0]));w.writeheader();w.writerows(gaps)
 # Input is grouped: query q outside; batch beam gap_before count; requests page offset_ns.
 with (dest/'input.txt').open('w') as f:
  f.write(str(len(groups))+'\n')
  for q,batches,outside in groups:
   f.write(f'{q} {outside} {len(batches)}\n')
   for j,b in enumerate(batches):
    gap=0 if j==0 else b['start']-batches[j-1]['finish']
    f.write(f"{b['beam']} {gap} {len(b['rows'])}\n")
    for r in b['rows']:f.write(f"{r['sector']//8} {r['issue']-b['start']}\n")
 def describe(v):return dict(mean=float(np.mean(v)),p50=float(np.percentile(v,50)),p95=float(np.percentile(v,95)),min=float(min(v)),max=float(max(v)))
 audit=dict(source=str(run),dataset='SIFT100M',mode='split BNF/page expansion/traverse_only',requested_queries=n,accepted_queries=len(groups),excluded=excluded,request_count=sum(len(b['rows']) for _,bs,_ in groups for b in bs),gap_count=len(gaps),gap_us=describe([g['gap_ns']/1000 for g in gaps]),background_overlap_gaps=sum(g['background_overlap'] for g in gaps),pair_diagnostics=dict(bad),boundary='block_rq_complete to next block_rq_issue; not hardware SSD departure/arrival',array50us_gap_fraction=float(np.mean([g['gap_ns']>=50000 for g in gaps])),single_read62578ns_gap_fraction=float(np.mean([g['gap_ns']>=62578 for g in gaps])),observed_query_mean_us=float(np.mean([float(stats[q]['total_us']) for q,_,_ in groups])))
 (dest/'audit.json').write_text(json.dumps(audit,indent=2));print(json.dumps(audit),flush=True)
 return audit
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--queries',type=int,default=1000);p.add_argument('--root',type=Path,default=Path('results/abcd_block'));a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
 audits=[prepare(a.root,a.out,L,W,a.queries) for L in [60,120] for W in [8,16,32]]
 (a.out/'trace_audit.json').write_text(json.dumps(audits,indent=2))
