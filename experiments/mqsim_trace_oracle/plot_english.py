#!/usr/bin/env python3
"""Standalone English plots from the validated replay summary."""
import csv,os,sys
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR','/tmp/mqsim_pipeline_lab_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
plt.rcParams.update({'font.family':'DejaVu Sans','svg.fonttype':'none','font.size':12})
out=Path(sys.argv[1])
rows=list(csv.DictReader((out/'summary.csv').open()))
sel=[r for r in rows if r['mapping']=='stripe' and float(r['array_us'])==50]
key=lambda r:(int(r['L']),int(r['W']))
b=sorted([r for r in sel if r['mode']=='baseline'],key=key)
o=sorted([r for r in sel if r['mode']=='oracle'],key=key)
x=np.arange(len(b));labels=[f"L{r['L']}\nW{r['W']}" for r in b]
for name,title,col,unit,scale in [
 ('inter_batch_gap_en','Median Inter-Batch Gap','gap_p50_us','μs',1),
 ('search_latency_en','Mean Search Latency (MQSim Replay)','query_mean_us','ms',1000),
 ('demand_wait_en','Mean Wait After Demand Arrival','request_demand_wait_us','μs',1)]:
 fig,ax=plt.subplots(figsize=(6.8,4.6))
 if name=='inter_batch_gap_en':
  ax.bar(x,[float(r[col]) for r in b],color='#737b83',width=.72)
  ax.axhline(62.578,color='#b46b27',linestyle='--',label='Uncontended read: 62.578 μs')
 else:
  ax.bar(x-.18,[float(r[col])/scale for r in b],.36,color='#737b83',label='Baseline')
  ax.bar(x+.18,[float(r[col])/scale for r in o],.36,color='#087e8b',label='100% Oracle')
 ax.set_title(title,pad=13,fontsize=14);ax.set_ylabel(unit);ax.set_xticks(x,labels)
 ax.spines[['top','right']].set_visible(False);ax.legend(loc='upper left',fontsize=10,frameon=True)
 fig.tight_layout()
 for ext in ['png','svg']:fig.savefig(out/f'{name}.{ext}',dpi=200,facecolor='white')
 plt.close(fig)
