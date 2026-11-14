#!/usr/bin/env python3
"""Feasible illustrative bus schedule, command included; not MQSim TSU output."""
import os
os.environ.setdefault('MPLCONFIGDIR','/tmp/mqsim_pipeline_lab_mpl')
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch
font_manager.fontManager.addfont('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':'Noto Sans CJK JP','svg.fonttype':'none','font.size':11})
out=Path(__file__).resolve().parents[2]/'results/mqsim_pipeline_lab'
CMD,ARRAY,DATA=.290,50.,12.288
colors={'cmd':'#171717','array':'#c6cbd0','data':'#087e8b'}
for n,name in [(5,'channel_ideal_5'),(4,'channel_original_4')]:
 bus=[];work=[];ready=[];t=0
 for i in range(n):
  bus.append((t,t+CMD,i,'cmd'));work.append((t,t+CMD,i,'cmd'));work.append((t+CMD,t+CMD+ARRAY,i,'array'));ready.append(t+CMD+ARRAY);t+=CMD
 for k in range(10):
  i=k%n;s=max(t,ready[i])
  if s>t:bus.append((t,s,-1,'idle'))
  e=s+DATA;bus.append((s,e,i,'data'));work.append((s,e,i,'data'))
  bus.append((e,e+CMD,i,'cmd'));work.append((e,e+CMD,i,'cmd'));work.append((e+CMD,e+CMD+ARRAY,i,'array'));ready[i]=e+CMD+ARRAY;t=e+CMD
 for a,b in zip(bus,bus[1:]):assert a[1]<=b[0]+1e-8
 fig=plt.figure(figsize=(14,6.3));ax=fig.add_axes([.12,.35,.85,.44]);ax.set_xlim(0,180);ax.set_ylim(n+1,-.6)
 ax.set_yticks(list(range(n))+[n+.65],[f'Chip {chr(65+i)}' for i in range(n)]+['Shared channel'])
 for s,e,i,kind in work:
  ax.broken_barh([(s,e-s)],(i-.26,.52),facecolors=colors[kind])
  if kind=='cmd':ax.vlines((s+e)/2,i-.26,i+.26,color=colors[kind],lw=1.2)
 for s,e,i,kind in bus:
  if s>=180:continue
  if kind=='idle':
   if s<5:ax.text((s+e)/2,n+.65,'Initial sensing',ha='center',va='center',fontsize=9)
   else:
    ax.broken_barh([(s,e-s)],(n+.36,.58),facecolors='white',edgecolors='#777',linestyles='--');ax.text((s+e)/2,n+.65,'Idle',ha='center',va='center',fontsize=9)
  else:
   ax.broken_barh([(s,e-s)],(n+.36,.58),facecolors=colors[kind])
   if kind=='cmd':ax.vlines((s+e)/2,n+.36,n+.94,color=colors[kind],lw=1.2)
   else:ax.text((s+min(e,180))/2,n+.65,chr(65+i),ha='center',va='center',color='white',fontsize=10)
 ax.set_xticks([0,50,100,150]);ax.set_xlabel('時間（μs）');ax.spines[['top','right','left']].set_visible(False);ax.tick_params(axis='y',length=0)
 fig.suptitle(('5 個獨立來源：command 與 data-out 可接續填滿 channel' if n==5 else '4 個獨立來源：加入 command 後，仍有 sensing 空檔'),fontsize=18,y=.98)
 fig.legend(handles=[Patch(color=colors[k],label=v) for k,v in [('cmd','Command/address 0.290 μs'),('array','Array sensing 50 μs'),('data','Data-out 12.288 μs')]],loc='upper center',bbox_to_anchor=(.55,.92),ncol=3,frameon=False)
 # Magnify the short command so it is readable without distorting the main timeline.
 z=fig.add_axes([.25,.16,.52,.065]);z.set_xlim(62.0,64.0);z.set_ylim(0,1);z.set_yticks([])
 for s,e,i,kind in bus:
  if e<62 or s>64 or kind=='idle':continue
  z.axvspan(s,e,color=colors[kind]);label=('Next A command' if kind=='cmd' else f'{chr(65+i)} data-out')
  z.text((max(s,62)+min(e,64))/2,.5,label,ha='center',va='center',color='white',fontsize=9)
 z.set_xticks([62,62.578,62.868,64]);z.tick_params(axis='x',labelsize=8)
 fig.text(.12,.18,'Zoom →',fontsize=11)
 fig.text(.12,.055,'示意排程：請求充足；每次 data-out 後先送該 chip 的下一次 command，再傳其他 chip 的資料。非 MQSim 原排程實測。',fontsize=10)
 fig.text(.12,.018,'Command 和 data-out Shared channel，不能重疊；array sensing 可跨 chips 並行。尚未加入 host 空窗。',fontsize=10)
 for ext in ['png','svg']:fig.savefig(out/f'{name}.{ext}',dpi=170,facecolor='white')
 plt.close(fig)
