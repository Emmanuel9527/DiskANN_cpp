#!/usr/bin/env python3
import csv,json,sys,os
from pathlib import Path
import numpy as np
os.environ.setdefault('MPLCONFIGDIR','/tmp/mqsim_pipeline_lab_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
font_manager.fontManager.addfont('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':'Noto Sans CJK JP','svg.fonttype':'none'})
out=Path(sys.argv[1]);rows=list(csv.DictReader((out/'summary.csv').open()))
base=sorted([r for r in rows if r['mapping']=='stripe' and float(r['array_us'])==50 and r['mode']=='baseline'],key=lambda r:(int(r['L']),int(r['W'])))
ora=sorted([r for r in rows if r['mapping']=='stripe' and float(r['array_us'])==50 and r['mode']=='oracle'],key=lambda r:(int(r['L']),int(r['W'])))
x=np.arange(len(base));labels=[f"L{r['L']}\nW{r['W']}" for r in base]
fig,axs=plt.subplots(1,3,figsize=(16,4.7));axs[0].bar(x,[float(r['gap_p50_us']) for r in base],color='#737b83');axs[0].axhline(62.578,color='#b46b27',ls='--',label='無競爭單筆 read：62.578 μs');axs[0].set_ylabel('μs');axs[0].set_title('實測批間空窗：中位數');axs[0].legend(fontsize=8)
for ax,col,title,div,ylabel in [(axs[1],'query_mean_us','MQSim 回放平均搜尋時間',1000,'ms'),(axs[2],'request_demand_wait_us','正式 demand 後剩餘等待',1,'μs')]:
 ax.bar(x-.18,[float(r[col])/div for r in base],.36,color='#737b83',label='Baseline');ax.bar(x+.18,[float(r[col])/div for r in ora],.36,color='#087e8b',label='100% oracle');ax.set_title(title);ax.set_ylabel(ylabel);ax.legend(fontsize=9)
for ax in axs:ax.set_xticks(x,labels);ax.spines[['top','right']].set_visible(False)
fig.suptitle('SIFT100M neighbor-only trace｜每組前 1,000 queries，完整配對者 993–994｜8 channels × 4 chips',fontsize=12)
fig.text(.02,.01,'Trace 空窗包含 host 搜尋與 stack；50 μs array、4 KiB read。Oracle 僅預讀下一批；不含候選發現／PQ／VUC 成本。',fontsize=9)
fig.tight_layout(rect=(0,.05,1,.94))
for ext in ['png','svg']:fig.savefig(out/f'results.{ext}',dpi=180)
plt.close(fig)
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
 ax.set_yticks(range(8),[f'Ch {i}' for i in range(8)]);ax.set_ylim(7.6,-.6);ax.set_title(mode+'｜青：command / data-out；淡橘：等待下一批正式 demand；虛線：批次到達',loc='left',fontsize=11)
axs[-1].set_xlabel('μs（同一個實際 trace query，MQSim 時間；array sensing 不畫在 channel 上）');fig.tight_layout()
for ext in ['png','svg']:fig.savefig(out/f'timeline.{ext}',dpi=180)
plt.close(fig)
