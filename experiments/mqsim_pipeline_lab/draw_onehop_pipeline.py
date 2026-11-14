#!/usr/bin/env python3
"""Conceptual one-hop speculation; arbitrary units, no claimed speedup."""
import os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR','/tmp/mqsim_pipeline_lab_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch
font_manager.fontManager.addfont('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':'Noto Sans CJK JP','svg.fonttype':'none','font.size':12})
out=Path(__file__).resolve().parents[2]/'results/mqsim_pipeline_lab'
C={'read':'#737b83','local':'#b46b27','link':'#087e8b','host':'#365fa0'}
legend=[Patch(color=C[k],label=v) for k,v in [('read','灰：SSD graph read'),('local','橘：SSD 局部處理／PQ 取得'),('link','青：host–SSD 傳輸'),('host','藍：host 搜尋控制')]]
def block(ax,s,e,y,label,k,hatch=None):
 ax.barh(y,e-s,left=s,height=.66,color=C[k],edgecolor='white',hatch=hatch,linewidth=1)
 ax.text((s+e)/2,y,label,ha='center',va='center',color='white',fontsize=11)
def arrow(ax,x,y,x2,y2):
 ax.annotate('',xy=(x2,y2),xytext=(x,y),arrowprops={'arrowstyle':'->','color':'#333333','lw':1.4})
def draw(ax,proposal):
 ax.set_xlim(0,18);ax.set_ylim(5.2,-.8);ax.set_xticks([])
 ax.set_yticks(range(5),['SSD：讀 A','SSD：局部探索','傳輸介面','Host','SSD：讀 X'])
 for s in ['top','left','right']:ax.spines[s].set_visible(False)
 ax.tick_params(axis='y',length=0);ax.set_xlabel('時間 →（概念示意，非實測比例）',labelpad=12)
 ax.set_title('CSD 一跳探索：裝置先啟動 X，host 隨後確認' if proposal else 'Host 非同步探索：A 一完成就處理，X 仍須等待 host 選擇',loc='left',fontsize=17,pad=18)
 block(ax,0,1.5,3,'選 A\n提交任務','host');block(ax,1.5,2.2,2,'A ID','link');arrow(ax,1.5,3,1.5,2);arrow(ax,2.2,2,2.2,0)
 block(ax,2.2,6.2,0,'讀取 A adjacency','read')
 if not proposal:
  block(ax,6.2,7.7,2,'回傳 adjacency','link');arrow(ax,6.2,0,6.2,2);arrow(ax,7.7,2,7.7,3)
  block(ax,7.7,10.2,3,'Host PQ 評分\n更新全域 frontier','host');block(ax,10.2,11.6,3,'選中 X','host')
  block(ax,11.6,12.3,2,'X ID','link');arrow(ax,11.6,3,11.6,2);arrow(ax,12.3,2,12.3,4)
  block(ax,12.3,16.3,4,'讀取 X adjacency','read')
  ax.text(8.8,1,'沒有 batch barrier，仍有一次 host 決策往返',ha='center',fontsize=12,color='#555555')
 else:
  arrow(ax,6.2,0,6.2,1)
  block(ax,6.2,7.5,1,'取得鄰居\nPQ codes','local')
  block(ax,7.5,9.3,1,'PQ 評分\n選局部候選 X','local')
  block(ax,9.3,13.3,4,'提前讀 X adjacency（推測）','read');arrow(ax,9.3,1,9.3,4)
  block(ax,9.3,10.8,2,'候選 IDs＋分數\n回報 host','link');arrow(ax,10.8,2,10.8,3)
  block(ax,10.8,12.6,3,'全域 visited／frontier\n確認是否採用 X','host')
  ax.annotate('',xy=(12.3,4.55),xytext=(9.3,4.55),arrowprops=dict(arrowstyle='|-|',color='#333333'))
  ax.text(10.8,4.62,'X 的讀取可提前',ha='center',va='top',fontsize=11)
  ax.axvline(12.3,color='#777777',ls='--',ymin=.02,ymax=.25,lw=1)
  ax.text(15.6,1,'只允許一跳\n最多提前讀 1–2 個候選',ha='center',fontsize=12,color='#444444')
  ax.text(15.6,3,'X 不被採用：\n計入無效預讀成本',ha='center',fontsize=11,color='#555555')
def save(fig,name):
 for ext in ['png','svg']:fig.savefig(out/(name+'.'+ext),dpi=180,bbox_inches='tight',facecolor='white')
 plt.close(fig)
fig,axs=plt.subplots(2,1,figsize=(18,12));fig.subplots_adjust(top=.84,bottom=.18,left=.10,right=.98,hspace=.67)
fig.suptitle('CSD 一跳探索：跨過一次 host 決策往返',fontsize=23,y=.98)
fig.legend(handles=legend,loc='upper center',bbox_to_anchor=(.5,.95),ncol=2,frameon=False,fontsize=12)
for ax,p in zip(axs,[False,True]):draw(ax,p)
fig.text(.10,.09,'前提：SSD 已取得 query 的 PQ 查表資訊。X 在讀到 A 後才被發現；host 保留全域決策。',fontsize=13)
fig.text(.10,.05,'收益條件：PQ 取得／計算夠便宜、X 最後有用、推測不拖慢必要讀取。PQ cache miss 可能抵銷收益。',fontsize=12)
save(fig,'onehop_pipeline_comparison')
for p,name in [(False,'onehop_pipeline_host_async'),(True,'onehop_pipeline_csd')]:
 fig,ax=plt.subplots(figsize=(18,6.5));fig.subplots_adjust(top=.83,bottom=.24,left=.10,right=.98)
 draw(ax,p);fig.legend(handles=legend,loc='lower center',ncol=2,frameon=False,fontsize=11)
 save(fig,name)
print(out/'onehop_pipeline_comparison.png')
