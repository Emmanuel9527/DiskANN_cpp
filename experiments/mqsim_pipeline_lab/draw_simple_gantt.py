#!/usr/bin/env python3
"""Monochrome Gantt explanations from actual MQSim traces (first two batches)."""
import os,csv
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR','/tmp/mqsim_pipeline_lab_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch
root=Path(__file__).resolve().parents[2]/'results/mqsim_pipeline_lab'
font_manager.fontManager.addfont('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':'Noto Sans CJK JP','font.size':11,'svg.fonttype':'none','axes.spines.top':False,'axes.spines.right':False})
cases=[('batch_gap0','① 整批完成，再立即提交下一批','299.467'),('batch_gap20us','② 整批完成，再等待 20 μs 才提交','359.467'),('stream','③ 每完成一筆，就立即補一筆','299.464')]
def load(name):
 r={}
 for row in csv.DictReader((root/(name+'.csv')).open()):
  i=int(row['id']);r.setdefault(i,{})[row['event']]=int(row['time_ns'])/1000
 return r
def bar(ax,a,b,y,label='',hatch=None,fill='white'):
 if b<=a:return
 ax.barh(y,b-a,left=a,height=.48,color=fill,edgecolor='black',linewidth=.9,hatch=hatch,zorder=3)
 if label:ax.text((a+b)/2,y,label,ha='center',va='center',fontsize=10,zorder=4)
def panel(ax,case,compact=False):
 name,title,total=case;r=load(name)
 ax.set_title(title if compact else title+f'　｜全部 16 筆完成：{total} μs',loc='left',fontsize=18 if compact else 14,pad=18)
 # Only channel 0 is shown: channel 1 behaves symmetrically in this experiment.
 for i in [0,2,4,6]:
  t=r[i];lane=1 if i%4==0 else 2
  bar(ax,t['cmd_start'],t['array_start'],0,fill='black')
  bar(ax,t['data_start'],t['data_end'],0,f'R{i} 資料',hatch='///')
  bar(ax,t['array_start'],t['array_end'],lane,f'R{i}：array read',fill='#dddddd')
 if name=='batch_gap20us':
  start=max(r[i]['complete'] for i in range(4));end=r[4]['submit']
  ax.axvspan(start,end,facecolor='#f3f3f3',edgecolor='#999999',linestyle=':',zorder=0)
  ax.text((start+end)/2,-.65,'Host 等待\n20 μs',ha='center',va='center',fontsize=10)
 t=r[4];a=t['submit'];b=t['cmd_start']
 if b-a>.01:bar(ax,a,b,3,'排隊',hatch='...')
 ax.scatter([a],[3],marker='v',s=65,color='black',zorder=5)
 ax.scatter([b],[3],marker='|',s=220,color='black',zorder=6)
 ax.set_yticks([0,1,2,3],['Channel 0\n命令／資料傳輸','Chip 0 / die 0\nArray 運作','Chip 1 / die 0\nArray 運作','R4：提交 ▼\n開始命令 │'])
 ax.set_ylim(3.65,-1.0);ax.set_xlim(0,180);ax.set_xticks(range(0,181,25));ax.grid(axis='x',alpha=.18);ax.set_xlabel('模擬時間（μs）')
 if name=='stream':msg=f'R4 在 {a:.3f} μs 提交，但 channel 正傳 R2 資料；等到 {b:.3f} μs 才開始命令。'
 elif name=='batch_gap20us':msg=f'Channel 在 74.866 μs 可用，但 host 延後提交；R4 到 {b:.3f} μs 才開始命令。'
 else:msg=f'R4 在 {a:.3f} μs 提交並開始命令；此前 channel 正在傳 R2 資料。'
 if not compact: ax.text(0,-.28,msg,transform=ax.transAxes,fontsize=11,va='top')
def save(fig,name):
 for ext in ['png','svg']:fig.savefig(root/(name+'.'+ext),dpi=180,bbox_inches='tight',facecolor='white')
 plt.close(fig)
legend=[Patch(facecolor='black',label='Command/address（0.290 μs，很細）'),Patch(facecolor='#dddddd',edgecolor='black',label='Array read'),Patch(facecolor='white',edgecolor='black',hatch='///',label='Data-out'),Patch(facecolor='white',edgecolor='black',hatch='...',label='已提交，但等待 channel')]
fig,axes=plt.subplots(3,1,figsize=(15,13));fig.subplots_adjust(hspace=.8,top=.88,bottom=.16,left=.13,right=.98)
fig.suptitle('三種提交方式：前兩批的簡化甘特圖',fontsize=22,y=.98)
fig.text(.5,.94,'實際 trace 時間｜共 2 channels；此處只畫 Channel 0，Channel 1 行為對稱',ha='center',fontsize=12)
fig.text(.5,.915,'第一批：R0–R3　第二批：R4–R7；空白表示該列資源沒有執行圖中的操作，不代表整顆 SSD 閒置。',ha='center',fontsize=11)
for ax,case in zip(axes,cases):panel(ax,case)
fig.legend(handles=legend,loc='lower center',ncol=2,frameon=False,fontsize=11)
save(fig,'simple_gantt_comparison')
for case in cases:
 fig,ax=plt.subplots(figsize=(12,5.5));fig.subplots_adjust(top=.84,bottom=.22,left=.18,right=.98)
 panel(ax,case,compact=True)
 ax.set_yticklabels(['Channel 0','Chip 0 array','Chip 1 array','R4 提交 ▼ / 開始 │'],fontsize=12)
 fig.legend(handles=[Patch(facecolor='#dddddd',edgecolor='black',label='Array read'),Patch(facecolor='white',edgecolor='black',hatch='///',label='Data-out'),Patch(facecolor='black',label='Command')],loc='lower center',ncol=3,frameon=False,fontsize=12)
 save(fig,'simple_gantt_'+case[0])
print(root/'simple_gantt_comparison.png')
