#!/usr/bin/env python3
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd

def busy_in_windows(s,e,ws,we):
 s=np.sort(np.asarray(s));e=np.sort(np.asarray(e));ps=np.r_[0,np.cumsum(s,dtype=np.float64)];pe=np.r_[0,np.cumsum(e,dtype=np.float64)]
 def integral(t):
  si=np.searchsorted(s,t,side='right');ei=np.searchsorted(e,t,side='right');return t*(si-ei)-ps[si]+pe[ei]
 return float(np.sum(integral(np.asarray(we,dtype=float))-integral(np.asarray(ws,dtype=float))))
def nonoverlap(s,e):
 order=np.argsort(s,kind='stable');s=np.asarray(s)[order];e=np.asarray(e)[order]
 assert np.all(e>=s) and (len(s)<2 or np.all(s[1:]>=e[:-1]))
def analyze(out):
 rows=[];validation=[]
 for folder in sorted(out.glob('L*_W*')):
  L,W=map(int,folder.name.replace('L','').replace('W','').split('_'));audit=json.loads((folder/'audit.json').read_text())
  for mapping,read in [('stripe',50000),('hash',50000),('stripe',100000)]:
   pair={}
   for mode in ['baseline','oracle']:
    stem=f'{mapping}_r{read}_{mode}';r=pd.read_csv(folder/f'{stem}_requests.csv');q=pd.read_csv(folder/f'{stem}_queries.csv');b=pd.read_csv(folder/f'{stem}_batches.csv')
    assert len(r)==audit['request_count'] and len(q)==audit['accepted_queries']
    assert np.all(r.ready_ns-r.array_ns==read);assert np.all(r.array_ns-r.cmd_ns==290);assert np.all(r.complete_ns-r.data_ns==12288)
    for _,g in r.groupby('channel'):nonoverlap(np.r_[g.cmd_ns,g.data_ns],np.r_[g.array_ns,g.complete_ns])
    for _,g in r.groupby(['channel','chip','die']):nonoverlap(g.array_ns,g.ready_ns)
    for _,g in r.groupby(['channel','chip']):nonoverlap(g.cmd_ns,g.complete_ns)
    bb=b[b.gap_before_ns>0];ws=bb.demand_ns-bb.gap_before_ns;we=bb.demand_ns
    chan_gap=busy_in_windows(np.r_[r.cmd_ns,r.data_ns],np.r_[r.array_ns,r.complete_ns],ws,we)
    arr_gap=busy_in_windows(r.array_ns,r.ready_ns,ws,we)
    residual=np.maximum(0,r.complete_ns-r.demand_ns)
    maxima=r.groupby('batch').complete_ns.max().to_numpy();assert len(maxima)==len(b)
    full_ready=(maxima<=b.demand_ns.to_numpy())&(b.gap_before_ns.to_numpy()>0)
    span=q.window_ns.sum();total=q.total_ns.sum()
    v=dict(L=L,W=W,mapping=mapping,array_us=read/1000,mode=mode,queries=len(q),reads=len(r),gap_p50_us=audit['gap_us']['p50'],gap_mean_us=audit['gap_us']['mean'],query_mean_us=q.total_ns.mean()/1000,window_mean_us=q.window_ns.mean()/1000,query_p95_us=np.percentile(q.total_ns,95)/1000,request_demand_wait_us=residual.mean()/1000,backend_submit_complete_us=(r.complete_ns-r.submit_ns).mean()/1000,media_cmd_complete_us=(r.complete_ns-r.cmd_ns).mean()/1000,tsu_queue_us=(r.cmd_ns-r.submit_ns).mean()/1000,nand_array_us=(r.ready_ns-r.array_ns).mean()/1000,array_work_ms=(r.ready_ns-r.array_ns).sum()/1e6,channel_work_ms=((r.array_ns-r.cmd_ns)+(r.complete_ns-r.data_ns)).sum()/1e6,channel_busy_pct=100*((r.array_ns-r.cmd_ns)+(r.complete_ns-r.data_ns)).sum()/(8*span),array_busy_pct=100*(r.ready_ns-r.array_ns).sum()/(64*span),gap_channel_busy_pct=100*chan_gap/(8*bb.gap_before_ns.sum()),gap_array_busy_pct=100*arr_gap/(64*bb.gap_before_ns.sum()),ready_request_pct=100*float(np.mean(r.complete_ns<=r.demand_ns)),next_batch_fully_ready_pct=100*full_ready.sum()/len(bb),host_gap_share_pct=100*q.gap_ns.sum()/total)
    rows.append(v);pair[mode]=(r,q,b,v)
    if mode=='baseline':assert chan_gap==0 and arr_gap==0 and np.all(r.submit_ns==r.demand_ns)
    validation.append(dict(setting=folder.name,mapping=mapping,array_ns=read,mode=mode,phase_durations=True,channel_no_overlap=True,die_no_overlap=True,chip_serial=True,request_counts=True))
   br,bq,bb,bv=pair['baseline'];orr,oq,ob,ov=pair['oracle']
   assert np.array_equal(br[['id','batch','page','channel','chip','die','block','physical_page']],orr[['id','batch','page','channel','chip','die','block','physical_page']])
   assert np.array_equal(bb.gap_before_ns,ob.gap_before_ns);assert np.array_equal(bq["query"],oq["query"]);assert np.all(oq.total_ns<=bq.total_ns)
   ov['query_reduction_pct']=100*(1-ov['query_mean_us']/bv['query_mean_us']);ov['window_reduction_pct']=100*(1-ov['window_mean_us']/bv['window_mean_us']);ov['demand_wait_reduction_pct']=100*(1-ov['request_demand_wait_us']/bv['request_demand_wait_us'])
 df=pd.DataFrame(rows);df.to_csv(out/'summary.csv',index=False);(out/'validation.json').write_text(json.dumps(validation,indent=2))
 primary=df[(df.mapping=='stripe')&(df.array_us==50)].sort_values(['L','W','mode'])
 print(primary.to_string(index=False))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();analyze(a.out)
