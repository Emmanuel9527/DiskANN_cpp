#!/usr/bin/env python3
"""Conceptual host-gap filling, no measured timing or channel occupancy claim."""
import os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR','/tmp/mqsim_pipeline_lab_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch
font_manager.fontManager.addfont('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':'Noto Sans CJK JP','svg.fonttype':'none','font.size':11})
C={'read':'#737b83','local':'#b46b27','link':'#087e8b','host':'#365fa0'}
out=Path(__file__).resolve().parents[2]/'results/mqsim_pipeline_lab'
fig=plt.figure(figsize=(19,10))
ax=fig.add_axes([.13,.40,.84,.43])
ax.set_xlim(0,30);ax.set_ylim(5.7,-.8)
ax.set_yticks(range(6),['Host','Host → CSD','CSD：正式工作','CSD → Host','CSD：預探索','CSD：暫存／合併'])
ax.set_xticks([]);ax.tick_params(axis='y',length=0)
for k in ['top','left','right']:ax.spines[k].set_visible(False)
ax.set_xlabel('時間 →（概念示意；非實測比例）')
ax.axvspan(12,21,color='#eeeeee',zorder=0)
ax.text(16.5,-.59,'下一批正式請求尚未到達',ha='center',fontsize=12)
def b(s,e,y,t,k):
 ax.barh(y,e-s,left=s,height=.62,color=C[k],edgecolor='white',linewidth=1)
 ax.text((s+e)/2,y,t,color='white',ha='center',va='center',fontsize=10)
def a(s,y,e,z):
 ax.annotate('',xy=(e,z),xytext=(s,y),arrowprops={'arrowstyle':'->','color':'#333','lw':1.2})
b(0,2,1,'VUC\nSeeds＋全域提示','link');b(2,8,2,'本批 adjacency reads','read');b(8,10,2,'局部 PQ','local')
b(10,12,3,'回報候選','link');a(10,2,10,3);a(12,3,12,0)
b(12,14,0,'C：完成處理','host');b(14,18,0,'全域 visited／frontier\n選出 X、P、Q','host');b(18,20,0,'A：提交','host')
b(20,21,1,'VUC','link');a(20,0,20,1)
b(10,11.5,4,'篩選','local');b(11.5,17,4,'預讀 X','read');b(17,19,4,'PQ／整理','local');a(10,2,10,4)
b(19,23,5,'X 就緒 → 合併命中','local');a(19,4,19,5);a(21,1,21,5)
b(21,28,2,'正式讀取 P、Q（未命中）','read');a(21,1,21,2)
ax.text(24.9,4,'Y 尚未派發：暫停／重新評估\n不再重讀 X',ha='center',va='center',fontsize=11)
ax.axvline(21,color='#444',linestyle='--',lw=1)
fig.suptitle('以全域提示約束局部預探索，填補 host 供給空窗',fontsize=23,y=.97)
fig.legend(handles=[Patch(color=C[k],label=v) for k,v in [('host','藍：host 控制／I/O stack'),('link','青：host–SSD 通訊'),('read','灰：SSD 讀取'),('local','橘：裝置評分／管理')]],loc='upper center',bbox_to_anchor=(.54,.93),ncol=4,frameon=False)
fig.text(.13,.29,'VUC：提交／更新探索任務',fontsize=15,weight='bold')
fig.text(.13,.245,'query／epoch、正式 seeds、全域候選提示及 PQ 分數、frontier 門檻、額外 page／in-flight 預算',fontsize=12)
fig.text(.13,.18,'CSD 派發前判斷',fontsize=15,weight='bold')
fig.text(.13,.135,'候選是否值得？ → 已快取／在途／重複？ → 正式請求優先、資源與預算允許？ → 才派發預探索',fontsize=12)
fig.text(.13,.075,'示意假設 X 命中、P/Q 未命中。灰色 read 包含 array 等待，不代表 channel 全程忙碌；已派發推測仍可能干擾新請求。',fontsize=11,color='#444')
fig.text(.13,.035,'VUC 授權有限探索，不逐點等待命令；正式結果回報後，預探索可依 query 狀態與預算繼續。提示僅用於推測排序。',fontsize=11,color='#444')
for ext in ['png','svg']:fig.savefig(out/f'gap_filling_pipeline.{ext}',dpi=180,bbox_inches='tight',facecolor='white')
print(out/'gap_filling_pipeline.png')
