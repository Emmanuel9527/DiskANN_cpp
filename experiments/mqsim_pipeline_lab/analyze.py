#!/usr/bin/env python3
"""Validate actual backend event traces and plot measured simulation timestamps."""
import argparse,csv,json,os
from collections import defaultdict
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR','/tmp/mqsim_pipeline_lab_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();root=a.out
names=['channels','chips','dies','pages','phy_die_interleave','batch_gap0','batch_gap20us','stream']
colors={'queue':'#f2c078','command':'#283747','array':'#80858c','wait_data':'#bda6d9','data':'#008598'}
phases=[('queue','submit','dispatch'),('command','cmd_start','array_start'),('array','array_start','array_end'),('wait_data','array_end','data_start'),('data','data_start','data_end')]
allreq={}; traces={};summary=[]
def no_overlap(intervals):
 intervals=sorted(intervals)
 for left,right in zip(intervals,intervals[1:]):assert left[1]<=right[0],(left,right)
for name in names:
 rows=list(csv.DictReader((root/(name+'.csv')).open()));req=defaultdict(dict)
 for r in rows:
  for k in ['time_ns','id','channel','chip','die','plane','page']:r[k]=int(r[k])
  assert r['event'] not in req[r['id']],(name,r)
  req[r['id']][r['event']]=r['time_ns'];req[r['id']]['addr']=(r['channel'],r['chip'],r['die'],r['plane'],r['page'])
 bus=defaultdict(list);arrays=defaultdict(list)
 for i,t in req.items():
  order=['submit','dispatch','cmd_start','array_start','array_end','data_start','data_end','complete']
  assert all(k in t for k in order),(name,i,t)
  assert [t[k] for k in order]==sorted(t[k] for k in order),(name,i,t)
  assert t['array_start']-t['cmd_start']==290
  assert t['array_end']-t['array_start']==50000
  assert t['data_end']-t['data_start']==12288
  assert t['complete']==t['data_end']
  bus[t['addr'][0]] += [(t['cmd_start'],t['array_start']),(t['data_start'],t['data_end'])]
  arrays[t['addr'][:3]].append((t['array_start'],t['array_end']))
 for x in [*bus.values(),*arrays.values()]:no_overlap(x)
 outstanding=0;last=0;area=0;zero=0;peak=0
 for r in rows:
  if r['event'] not in ['submit','complete']:continue
  dt=r['time_ns']-last;area+=outstanding*dt
  if outstanding==0:zero+=dt
  outstanding+=1 if r['event']=='submit' else -1
  assert outstanding>=0;peak=max(peak,outstanding);last=r['time_ns']
 assert outstanding==0 and peak<=4
 total=max(t['complete'] for t in req.values())
 summary.append(dict(case=name,requests=len(req),makespan_us=total/1000,mean_outstanding=area/total,peak_outstanding=peak,zero_outstanding_us=zero/1000,channel_busy_pct=100*sum(e-s for v in bus.values() for s,e in v)/(2*total)))
 allreq[name]=req;traces[name]=rows
# Same exact physical sequence and transfer volume for all delivery policies.
assert [allreq['batch_gap0'][i]['addr'] for i in range(16)]==[allreq['batch_gap20us'][i]['addr'] for i in range(16)]==[allreq['stream'][i]['addr'] for i in range(16)]
assert allreq['channels'][0]['cmd_start']==allreq['channels'][1]['cmd_start']==0
assert allreq['chips'][1]['array_start']<allreq['chips'][0]['array_end']
assert allreq['dies'][1]['cmd_start']==allreq['dies'][0]['complete']
assert allreq['pages'][1]['cmd_start']==allreq['pages'][0]['complete']
assert allreq['phy_die_interleave'][1]['array_start']<allreq['phy_die_interleave'][0]['array_end']
with (root/'summary.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=list(summary[0]));w.writeheader();w.writerows(summary)
(root/'validation.json').write_text(json.dumps({'passed':True,'checks':['every request has ordered and complete lifecycle','command=290 ns, array=50000 ns, data=12288 ns','no shared-channel transfer overlap','no same-die array overlap','outstanding bounded by 4 and returns to zero','identical addresses for all arrival policies','expected channel/chip overlap and stock die serialization','PHY-only die interleave demonstrated']},indent=2))
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
def save(fig,name):
 for ext in ['png','svg','pdf']:fig.savefig(root/(name+'.'+ext),dpi=170,bbox_inches='tight')
 plt.close(fig)
titles=['Different channels (stock TSU)','Same channel, different chips (stock TSU)','Same channel/chip, different dies (stock TSU)','Same die/plane, different pages (stock TSU)','Different dies: PHY-only interleave control (bypasses TSU)']
fig,axes=plt.subplots(5,1,figsize=(13,12));fig.subplots_adjust(hspace=.75,top=.90,bottom=.08)
for ax,name,title in zip(axes,names[:5],titles):
 req=allreq[name]
 for i,t in req.items():
  for label,start,end in phases:
   lo,hi=t[start]/1000,t[end]/1000
   if hi>lo:ax.broken_barh([(lo,hi-lo)],(i-.22,.44),facecolors=colors[label])
  ax.text(t['complete']/1000+1,i,f"{t['complete']/1000:.3f} us",va='center',fontsize=9)
 ax.set_yticks(list(req),[f"R{i}: ch{t['addr'][0]}/chip{t['addr'][1]}/die{t['addr'][2]}" for i,t in req.items()]);ax.invert_yaxis();ax.set_xlim(0,145);ax.set_xlabel('Simulation time (us)');ax.set_title(title,loc='left',fontweight='bold');ax.grid(axis='x',alpha=.2)
fig.suptitle('MQSim read lifecycle: measured backend events\n4 KiB reads | array 50 us | command 0.290 us | data-out 12.288 us',fontsize=15)
fig.legend(handles=[Patch(color=c,label=k) for k,c in colors.items()],loc='lower center',ncol=5)
save(fig,'read_cases')
fig,axes=plt.subplots(3,1,figsize=(14,10));fig.subplots_adjust(hspace=.55,top=.88,bottom=.09)
for ax,name,title in zip(axes,names[5:],['Wait-all batches, no added host gap','Wait-all batches, 20 us host gap','Completion refill, window = 4']):
 req=allreq[name]
 for i,t in req.items():
  lane=t['addr'][0]*2+t['addr'][1]
  for label,start,end in phases:
   if label=='queue':continue
   lo,hi=t[start]/1000,t[end]/1000
   if hi>lo:ax.broken_barh([(lo,hi-lo)],(lane-.3,.6),facecolors=colors[label])
  ax.text((t['array_start']+t['array_end'])/2000,lane,f'R{i}',ha='center',va='center',color='white',fontsize=8)
 ax.set_yticks(range(4),['ch0/chip0','ch0/chip1','ch1/chip0','ch1/chip1']);ax.invert_yaxis();ax.set_xlim(0,375);ax.grid(axis='x',alpha=.2);ax.set_xlabel('Simulation time (us)');ax.set_title(title+f" | finish {max(t['complete'] for t in req.values())/1000:.3f} us",loc='left',fontweight='bold')
fig.suptitle('Same 16 physical reads, same maximum outstanding = 4\nRows show active die 0 in each chip; purple = data ready, waiting for channel',fontsize=14)
fig.legend(handles=[Patch(color=c,label=k) for k,c in colors.items() if k!='queue'],loc='lower center',ncol=4)
save(fig,'batch_vs_stream')
fig,axes=plt.subplots(3,1,figsize=(13,8),sharex=True)
for ax,name in zip(axes,names[5:]):
 xs=[0];ys=[0];n=0
 for r in traces[name]:
  if r['event'] in ['submit','complete']:
   n+=1 if r['event']=='submit' else -1;xs.append(r['time_ns']/1000);ys.append(n)
 ax.step(xs,ys,where='post',color='#007b83');ax.set_ylim(-.2,4.5);ax.set_yticks(range(5));ax.grid(alpha=.2);ax.set_title(name,loc='left');ax.set_ylabel('Outstanding')
axes[-1].set_xlabel('Simulation time (us)');fig.suptitle('Backend outstanding reads (submitted to TSU, not host NVMe queue depth)');fig.tight_layout()
save(fig,'outstanding')
# Precise resource view for the same-channel/different-chip example.
req=allreq['chips'];fig,ax=plt.subplots(figsize=(13,4.3))
for i,t in req.items():
 for label,s,e,lane in [('command','cmd_start','array_start',0),('data','data_start','data_end',0),('array','array_start','array_end',i+1),('wait_data','array_end','data_start',i+1)]:
  lo,hi=t[s]/1000,t[e]/1000
  if hi>lo:ax.broken_barh([(lo,hi-lo)],(lane-.25,.5),facecolors=colors[label])
 ax.text((t['array_start']+t['array_end'])/2000,i+1,f'R{i}: array read',ha='center',va='center',color='white')
ax.set_yticks([0,1,2],['Shared channel 0','Chip 0 / die 0','Chip 1 / die 0']);ax.invert_yaxis();ax.set_xlim(0,80);ax.set_xlabel('Simulation time (us)');ax.grid(axis='x',alpha=.2);ax.set_title('Channel becomes free at 0.290 us while chip 0 remains READING',loc='left');fig.tight_layout();save(fig,'resource_timeline')
print(json.dumps(summary,indent=2))
