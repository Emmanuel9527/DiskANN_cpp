#!/usr/bin/env python3
"""Conceptual request-starvation timeline; time is not to scale."""
import os
os.environ.setdefault('MPLCONFIGDIR','/tmp/mqsim_pipeline_lab_mpl')
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch
font_manager.fontManager.addfont('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':'Noto Sans CJK JP','svg.fonttype':'none','font.size':12})
fig,ax=plt.subplots(figsize=(13,5));fig.subplots_adjust(left=.15,right=.97,top=.78,bottom=.20)
ax.set_xlim(0,21);ax.set_ylim(3.7,-.7)
colors={'cmd':'#171717','array':'#c6cbd0','data':'#087e8b','host':'#365fa0'}
def bar(s,e,y,label,k):
 ax.barh(y,e-s,left=s,height=.55,color=colors[k],edgecolor='white',linewidth=.5)
 if label:ax.text((s+e)/2,y,label,ha='center',va='center',color='white' if k!='array' else '#333',fontsize=11)
# Two sequential batches, with a deliberately long host-side supply gap.
for t in [0,14]:
 bar(t,t+.45,1,'','cmd');bar(t+.45,t+.9,2,'','cmd')
 bar(t+.45,t+4,1,'Sensing','array');bar(t+.9,t+4.45,2,'Sensing','array')
 bar(t+4,t+5.3,1,'A','data');bar(t+5.3,t+6.6,2,'B','data')
 for s,e,k,label in [(t,t+.45,'cmd',''),(t+.45,t+.9,'cmd',''),(t+4,t+5.3,'data','A'),(t+5.3,t+6.6,'data','B')]:bar(s,e,3,label,k)
ax.axvspan(6.6,14,color='#f0f0f0',zorder=-1)
bar(6.6,14,0,'Completion → Global decision → Submit','host')
ax.text(10.3,1.5,'Chips ready, but no requests',ha='center',va='center',fontsize=14)
ax.text(10.3,3,'Idle: waiting for host',ha='center',va='center',fontsize=13)
ax.text(2.4,3,'Sensing',ha='center',va='center',fontsize=10,color='#666')
ax.axvline(6.6,color='#777',ls='--',lw=1);ax.axvline(14,color='#777',ls='--',lw=1)
ax.annotate('Batch 1 done',xy=(6.6,3.25),xytext=(6.6,3.6),ha='center',fontsize=10)
ax.annotate('Batch 2 arrives',xy=(14,.75),xytext=(14,-.55),ha='center',fontsize=11,arrowprops={'arrowstyle':'->','color':'#333'})
ax.set_yticks([0,1,2,3],['Host','Chip A','Chip B','Shared channel']);ax.tick_params(axis='y',length=0);ax.set_xticks([])
ax.spines[['top','left','right']].set_visible(False);ax.set_xlabel('Time →',labelpad=18)
fig.suptitle('Idle caused by missing requests',fontsize=21,y=.96)
fig.legend(handles=[Patch(color=colors[k],label=v) for k,v in [('cmd','Command'),('array','Array sensing'),('data','Data-out'),('host','Host processing')]],loc='upper center',bbox_to_anchor=(.55,.89),ncol=4,frameon=False)
fig.text(.15,.06,'Hardware can accept work; the next batch has not arrived.',fontsize=12)
out=Path(__file__).resolve().parents[2]/'results/mqsim_pipeline_lab'
for ext in ['png','svg']:fig.savefig(out/f'host_supply_idle.{ext}',dpi=170,facecolor='white')
