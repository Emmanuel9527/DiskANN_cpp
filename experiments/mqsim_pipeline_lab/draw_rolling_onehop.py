#!/usr/bin/env python3
"""Illustrative dependency schedule, not MQSim measurements. Equal link payloads."""
import os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR', '/tmp/mqsim_pipeline_lab_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch
font_manager.fontManager.addfont('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':'Noto Sans CJK JP','svg.fonttype':'none','font.size':11})
OUT=Path(__file__).resolve().parents[2]/'results/mqsim_pipeline_lab'
OUT.mkdir(parents=True,exist_ok=True)
C={'read':'#737b83','local':'#b46b27','link':'#087e8b','host':'#365fa0'}
N=['A','X','Y','Z']
def block(ax,s,e,y,label,k):
 ax.barh(y,e-s,left=s,height=.62,color=C[k],edgecolor='white',linewidth=.7)
 ax.text((s+e)/2,y,label,ha='center',va='center',color='white',fontsize=10)
def arrow(ax,s,y,e,z):
 ax.annotate('',xy=(e,z),xytext=(s,y),arrowprops={'arrowstyle':'->','color':'#444','lw':1})
def setup(ax,rows,end):
 ax.set_xlim(0,end);ax.set_ylim(len(rows)-.25,-.8);ax.set_yticks(range(len(rows)),rows)
 ax.set_xticks(range(0,end+1,4));ax.grid(axis='x',alpha=.13);ax.set_axisbelow(True)
 ax.tick_params(axis='y',length=0)
 for p in ['top','right','left']:ax.spines[p].set_visible(False)
 ax.set_xlabel('時間 →（任意單位；非實測）')
def save(fig,name):
 for ext in ['png','svg']:fig.savefig(OUT/f'{name}.{ext}',dpi=180,bbox_inches='tight',facecolor='white')
 plt.close(fig)
legend=[Patch(color=C[k],label=t) for k,t in [('read','灰：SSD adjacency read'),('local','橘：PQ 取得／局部評分'),('link','青：host–SSD 傳輸'),('host','藍：host 全域決策')]]
fig,ax=plt.subplots(figsize=(17,8))
fig.subplots_adjust(left=.14,right=.98,top=.84,bottom=.21)
setup(ax,[f'第 {i+1} 輪：{n}' for i,n in enumerate(N)],40)
ax.set_title('滾動 one-hop：每輪確認後，再向前推進一跳',loc='left',fontsize=19,pad=20)
for i,n in enumerate(N):
 r=2+8*i;l=r+6
 block(ax,r,l,i,f'讀 {n}'+('（推測）' if i else ''),'read')
 block(ax,l,l+2,i,'PQ','local');block(ax,l+2,l+4,i,'回報','link')
 block(ax,l+4,l+7,i,'Host 決策','host')
 if i<3:
  block(ax,l+7,l+8,i,'確認','link')
  arrow(ax,l+2,i+.32,l+2,i+1-.32)
  ax.text(l+4.8,i+.55,f'提前讀 {N[i+1]}，同時回報／決策',fontsize=9,color='#444',ha='center')
  arrow(ax,l+8,i+.32,l+8,i+1-.32)
fig.legend(handles=legend,loc='upper center',bbox_to_anchor=(.55,.96),ncol=4,frameon=False,fontsize=10)
fig.text(.14,.105,'假設：每輪預取均命中；一次只允許一個未確認的下一跳。Host 確認 X 後，才允許 X 產生下一跳 Y。',fontsize=11)
fig.text(.14,.06,'灰色是整體 read 延遲，不代表 channel 全程忙碌。PQ／全頁評分成本在橘色階段計入；此圖未模擬資源爭用。',fontsize=11)
save(fig,'rolling_onehop_rounds')
fig,axs=plt.subplots(2,1,figsize=(19,10))
fig.subplots_adjust(left=.12,right=.98,top=.85,bottom=.16,hspace=.65)
for ax,prefetch in zip(axs,[False,True]):
 setup(ax,['SSD：讀取','SSD：局部評分','SSD → Host','Host：全域決策','Host → SSD'],60)
 ax.set_title('滾動 one-hop 預取：讀下一跳與回報／決策重疊' if prefetch else '相同 CSD 分工，關閉預取：下一次讀取等待 host 指令',loc='left',fontsize=15,pad=12)
 block(ax,0,1,3,'啟動','host');block(ax,1,2,4,'A','link')
 for i,n in enumerate(N):
  r=2+(8 if prefetch else 14)*i;l=r+6
  block(ax,r,l,0,f'讀 {n}','read');block(ax,l,l+2,1,f'{n}: PQ','local')
  block(ax,l+2,l+4,2,f'{n} 結果','link');block(ax,l+4,l+7,3,f'整合 {n}','host')
  arrow(ax,l,0,l,1);arrow(ax,l+2,1,l+2,2);arrow(ax,l+4,2,l+4,3)
  if i<3:
   block(ax,l+7,l+8,4,N[i+1],'link')
   if prefetch:
    arrow(ax,l+2,1,l+2,0)
   else:arrow(ax,l+8,4,l+8,0)
 ax.text(59,4,'向上：回報 IDs＋scores；向下：seed／確認指令',ha='right',va='center',fontsize=10,color='#444')
fig.suptitle('Host–SSD 詳細時間軸：回報間隔縮短，但傳輸不會自動連續',fontsize=21,y=.98)
fig.legend(handles=legend,loc='upper center',bbox_to_anchor=(.55,.94),ncol=4,frameon=False,fontsize=11)
fig.text(.12,.085,'控制變因：兩者回報相同資料量、相同 PQ 處理，僅切換預取。上下行分開畫，不代表 NVMe／PCIe 實際交易粒度。',fontsize=11)
fig.text(.12,.045,'示意 SSD → Host 回報：原間隔 14 → 預取間隔 8；每次傳輸仍為 2。間隙縮短，尚未填滿；不代表實測頻寬利用率。',fontsize=11)
save(fig,'rolling_onehop_link_detail')
print(OUT/'rolling_onehop_rounds.png')
print(OUT/'rolling_onehop_link_detail.png')
