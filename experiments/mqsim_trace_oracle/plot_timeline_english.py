#!/usr/bin/env python3
"""English version of the measured MQSim replay timeline."""
import csv,sys,os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR','/tmp/mqsim_pipeline_lab_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
plt.rcParams.update({'font.family':'DejaVu Sans','svg.fonttype':'none','font.size':11})
out=Path(sys.argv[1])
folder=out/'L120_W16';fig,axs=plt.subplots(2,1,figsize=(17,7),sharex=True)
for ax,mode in zip(axs,['baseline','oracle']):
 bs=list(csv.DictReader((folder/f'stripe_r50000_{mode}_batches.csv').open()));first=bs[0]['query'];bs=[b for b in bs if b['query']==first];origin=int(bs[0]['demand_ns'])
 with (folder/f'stripe_r50000_{mode}_requests.csv').open() as f:
  for row in csv.DictReader(f):
   r={k:int(v) for k,v in row.items()}
   if r['batch']>=len(bs):break
   ch=r['channel'];ax.broken_barh([((r['cmd_ns']-origin)/1000,(r['array_ns']-r['cmd_ns'])/1000),((r['data_ns']-origin)/1000,(r['complete_ns']-r['data_ns'])/1000)],(ch-.32,.64),facecolors='#087e8b')
 for b in bs:
  t=(int(b['demand_ns'])-origin)/1000;g=int(b['gap_before_ns'])/1000;ax.axvline(t,color='#333',lw=.65,ls='--')
  if g:ax.axvspan(t-g,t,color='#b46b27',alpha=.12)
 ax.set_yticks(range(8),[f'Ch {i}' for i in range(8)]);ax.set_ylim(7.6,-.6);ax.set_title('Baseline' if mode=='baseline' else '100% Oracle',loc='left',fontsize=11)
axs[-1].set_xlabel('Time (μs)')
fig.legend(handles=[Patch(facecolor='#087e8b',label='Command / Data-out'),Patch(facecolor='#b46b27',alpha=.12,label='Host gap'),Line2D([0],[0],color='#333',ls='--',lw=1,label='Batch arrival')],loc='upper center',ncol=3,frameon=False,bbox_to_anchor=(.5,.995))
fig.text(.5,.012,'Same query · MQSim replay · Array sensing not shown',ha='center',fontsize=10)
fig.tight_layout(rect=(0,.035,1,.94))
for ext in ['png','svg']:fig.savefig(out/f'timeline_en.{ext}',dpi=180)
plt.close(fig)
