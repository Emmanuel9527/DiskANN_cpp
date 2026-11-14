#!/usr/bin/env python3
"""Conceptual adjacency-streaming pipeline. Times are arbitrary, not simulated."""
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
colors={'read':'#737b83','device':'#b76a24','link':'#087e8b','host':'#365fa0'}
legend=[Patch(color=colors[k],label=v) for k,v in [('read','灰：SSD 讀取至裝置 buffer'),('device','橘：CSD adjacency 處理'),('link','青：host–SSD 傳輸'),('host','藍：host 計算與決策')]]
def box(ax,s,e,y,label,k):
 ax.barh(y,e-s,left=s,height=.58,color=colors[k],edgecolor='white',linewidth=1,zorder=3)
 ax.text((s+e)/2,y,label,color='white',ha='center',va='center',fontsize=11,zorder=4)
def arrow(ax,x,y,x2,y2):
 ax.annotate('',xy=(x2,y2),xytext=(x,y),arrowprops=dict(arrowstyle='->',color='#333333',lw=1.2),zorder=5)
def panel(ax,proposed):
 ax.set_xlim(0,15);ax.set_ylim(4.8,-.8);ax.set_xticks([])
 ax.set_yticks(range(5),['SSD 讀取 A','SSD 讀取 B','CSD 處理','傳輸介面','Host'])
 for spine in ['top','left','right']:ax.spines[spine].set_visible(False)
 ax.tick_params(axis='y',length=0);ax.set_xlabel('時間 →（僅示意相依與重疊，長度非實測）',labelpad=12)
 ax.set_title('提案：已完成的 adjacency 立即處理並串流' if proposed else '既有：整批 I/O 完成後，host 才開始處理',loc='left',fontsize=17,pad=20)
 box(ax,0,1,4,'選 A/B','host');box(ax,1,1.5,3,'IDs','link')
 box(ax,1.5,4.5,0,'讀 A','read');box(ax,1.5,7.5,1,'讀 B（較慢）','read')
 arrow(ax,1,4,1,3)
 if not proposed:
  box(ax,4.5,5.3,3,'A page','link');box(ax,7.5,8.3,3,'B page','link')
  arrow(ax,4.5,0,4.5,3);arrow(ax,7.5,1,7.5,3)
  ax.axvline(8.3,color='#444444',ls='--',lw=1.2)
  ax.text(8.3,-.65,'整批完成 barrier',ha='center',fontsize=11)
  box(ax,8.3,10,4,'A：解析\nPQ＋更新','host');box(ax,10,11.7,4,'B：解析\nPQ＋更新','host')
  box(ax,11.7,12.7,4,'選 C','host');box(ax,12.7,13.2,3,'C ID','link');box(ax,13.2,15,0,'下一輪讀 C →','read')
  arrow(ax,8.3,3,8.3,4);arrow(ax,12.7,4,12.7,3);arrow(ax,13.2,3,13.2,0)
  ax.text(5.2,4,'等待整批 I/O',ha='center',color='#555555')
  ax.text(5.2,2,'無裝置端 adjacency 處理',ha='center',color='#666666',fontsize=11)
 else:
  box(ax,4.5,5.5,2,'解析 A\n局部去重','device');box(ax,5.5,6.3,3,'A IDs','link');box(ax,6.3,7.5,4,'A：PQ\n更新 frontier','host')
  box(ax,7.5,8.5,2,'解析 B\n局部去重','device');box(ax,8.5,9.3,3,'B IDs','link');box(ax,9.3,10.5,4,'B：PQ\n更新 frontier','host')
  arrow(ax,4.5,0,4.5,2);arrow(ax,5.5,2,5.5,3);arrow(ax,6.3,3,6.3,4)
  arrow(ax,7.5,1,7.5,2);arrow(ax,8.5,2,8.5,3);arrow(ax,9.3,3,9.3,4)
  box(ax,10.5,11.5,4,'選 C','host');box(ax,11.5,12,3,'C ID','link');box(ax,12,15,0,'下一輪讀 C →','read')
  arrow(ax,11.5,4,11.5,3);arrow(ax,12,3,12,0)
  ax.annotate('',xy=(7.5,-.40),xytext=(4.5,-.40),arrowprops=dict(arrowstyle='|-|',color='#333333'))
  ax.text(6,-.65,'B 尚未完成，A 已往下處理',ha='center',fontsize=11)
  ax.axvline(13.2,color='#888888',ls='--',lw=1)
  ax.text(13.2,2,'原本 C 開始位置',rotation=90,ha='right',va='center',fontsize=10,color='#666666')
  ax.text(8.4,4,'等 B',ha='center',color='#555555',fontsize=11)
def save(fig,name):
 for ext in ['png','svg']:fig.savefig(out/(name+'.'+ext),dpi=180,bbox_inches='tight',facecolor='white')
 plt.close(fig)
fig,axs=plt.subplots(2,1,figsize=(17,11));fig.subplots_adjust(top=.83,bottom=.18,left=.10,right=.98,hspace=.65)
fig.suptitle('Adjacency 串流：把批次尾端工作移到 I/O 期間',fontsize=23,y=.98)
fig.legend(handles=legend,loc='upper center',bbox_to_anchor=(.5,.945),ncol=2,frameon=False,fontsize=12)
for ax,p in zip(axs,[False,True]):panel(ax,p)
fig.text(.10,.09,'此圖保留「A/B 都處理完才選 C」：提早處理 A，縮短最後一筆完成後的計算尾巴。',fontsize=13)
fig.text(.10,.045,'假設兩筆 SSD reads 可重疊、CSD 不拖慢必要讀取。尚未驗證效能；未消除真正的搜尋資料相依性。',fontsize=12)
save(fig,'adjacency_streaming_comparison')
for p,name in [(False,'adjacency_streaming_baseline'),(True,'adjacency_streaming_proposal')]:
 fig,ax=plt.subplots(figsize=(17,6));fig.subplots_adjust(top=.80,bottom=.22,left=.10,right=.98)
 panel(ax,p);fig.legend(handles=legend,loc='lower center',ncol=2,frameon=False,fontsize=11)
 save(fig,name)
print(out/'adjacency_streaming_comparison.png')
