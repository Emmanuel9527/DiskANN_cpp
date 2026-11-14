#!/usr/bin/env python3
"""English conceptual pipeline, not a measured timeline."""
import os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR','/tmp/mqsim_pipeline_lab_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
plt.rcParams.update({'font.family':'DejaVu Sans','svg.fonttype':'none','font.size':11})
C={'read':'#737b83','local':'#b46b27','link':'#087e8b','host':'#365fa0'}
fig,ax=plt.subplots(figsize=(17,5.8));fig.subplots_adjust(left=.14,right=.985,top=.79,bottom=.16)
ax.set_xlim(-.3,29);ax.set_ylim(5.6,-.8)
ax.set_yticks(range(6),['Host','Host → CSD','CSD: Demand','CSD → Host','CSD: Speculation','CSD: Buffer'])
ax.set_xticks([]);ax.tick_params(axis='y',length=0)
ax.spines[['top','left','right']].set_visible(False);ax.set_xlabel('Time →',labelpad=12)
ax.axvspan(12,21,color=C['local'],alpha=.10,zorder=0)
ax.text(16.5,-.62,'Host gap',ha='center',fontsize=12,color='#555')
def b(s,e,y,t,k):
 ax.barh(y,e-s,left=s,height=.58,color=C[k],edgecolor='white',linewidth=.6)
 ax.text((s+e)/2,y,t,color='white',ha='center',va='center',fontsize=10)
def a(x,y,x2,y2):ax.annotate('',xy=(x2,y2),xytext=(x,y),arrowprops={'arrowstyle':'->','color':'#444','lw':1})
b(0,2,1,'VUC\nSeeds + hints','link');b(2,8,2,'Adjacency reads','read');b(8,10,2,'Local PQ','local')
b(10,12,3,'Candidates','link');a(10,2,10,3);a(12,3,12,0)
b(12,14,0,'Complete','host');b(14,18,0,'Update frontier\nSelect X, P, Q','host');b(18,20,0,'Submit','host')
b(20,21,1,'VUC','link');a(20,0,20,1)
b(10,11.5,4,'Select','local');b(11.5,17,4,'Prefetch X','read');b(17,19,4,'PQ + pack','local');a(10,2,10,4)
b(19,23,5,'X ready → Reuse','local');a(19,4,19,5);a(21,1,21,5)
b(21,28,2,'Read P, Q (misses)','read');a(21,1,21,2)
ax.text(25,4,'Pending Y: reassess\nNo duplicate read for X',ha='center',va='center',fontsize=11,color='#444')
ax.axvline(21,color='#333',ls='--',lw=1)
ax.text(21.15,-.62,'Next batch arrives',ha='left',fontsize=11)
fig.suptitle('Global Hints Guide CSD Speculation',fontsize=19,y=.97)
fig.legend(handles=[Patch(color=C[k],label=v) for k,v in [('host','Host processing'),('link','Host–CSD transfer'),('read','NAND read'),('local','CSD processing')]]+[Line2D([0],[0],color='#333',ls='--',lw=1,label='Batch arrival')],loc='upper center',bbox_to_anchor=(.55,.91),ncol=5,frameon=False,fontsize=10)
fig.text(.14,.035,'VUC: seeds, global hints, and speculation budget',fontsize=10,color='#555')
out=Path(__file__).resolve().parents[2]/'results/mqsim_pipeline_lab'
for ext in ['png','svg']:fig.savefig(out/f'gap_filling_pipeline_en.{ext}',dpi=180,bbox_inches='tight',facecolor='white')
