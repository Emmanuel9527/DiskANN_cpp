#!/usr/bin/env python3
from pathlib import Path
import os
os.environ.setdefault('MPLCONFIGDIR','/tmp/mqsim_pipeline_lab_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch
font_manager.fontManager.addfont('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
plt.rcParams.update({'font.family':'Noto Sans CJK JP','svg.fonttype':'none','font.size':12,'axes.spines.top':False,'axes.spines.right':False})
out=Path(__file__).resolve().parents[2]/'results/mqsim_pipeline_lab'
def block(ax,x,end,y,label,kind='work'):
 ax.barh(y,end-x,left=x,height=.55,color='#dedede' if kind=='work' else 'white',edgecolor='black',hatch='///' if kind=='prefetch' else None,linewidth=1)
 ax.text((x+end)/2,y,label,ha='center',va='center',fontsize=12)
def setup(ax,title):
 ax.set_title(title,loc='left',fontsize=18,pad=20)
 ax.set_yticks([0,1,2],['Host','SSD：必要讀取','SSD：候選預讀'])
 ax.set_ylim(2.65,-.65);ax.set_xlim(0,13);ax.set_xticks([]);ax.set_xlabel('時間 →（概念示意，非實測比例）');ax.spines['left'].set_visible(False)
def arr(ax,x,y,x2,y2):ax.annotate('',xy=(x2,y2),xytext=(x,y),arrowprops=dict(arrowstyle='->',color='black',lw=1.5))
fig,axes=plt.subplots(2,1,figsize=(16,9));fig.subplots_adjust(top=.84,bottom=.19,left=.13,right=.98,hspace=.85)
fig.suptitle('候選預讀改善哪一段 pipeline？',fontsize=24,y=.97)
fig.text(.5,.915,'前提：C 已在 frontier，但尚未正式選中；預讀使用可用資源，不延誤 A／B。',ha='center',fontsize=13)
a=axes[0];setup(a,'原本：選到 C 之後，才開始讀 C 的 neighbor page')
block(a,0,1.5,0,'選 A／B\n提交');block(a,1.5,5,1,'讀 A／B adjacency');arr(a,1.5,0,1.5,1);arr(a,5,1,5,0)
block(a,5,7,0,'PQ＋更新 frontier\n選中 C');block(a,7,10.5,1,'讀 C adjacency');arr(a,7,0,7,1);arr(a,10.5,1,10.5,0);block(a,10.5,12,0,'處理 C\n繼續探索')
a.annotate('',xy=(10.5,-.48),xytext=(7,-.48),arrowprops=dict(arrowstyle='|-|',color='black'))
a.text(8.75,-.60,'下一輪的 flash 等待',ha='center',va='bottom',fontsize=12)
a.text(6,2,'此時尚未對 C 做任何預讀',ha='center',color='#555555')
a=axes[1];setup(a,'提案：先讀已知候選 C，host 選中時直接取用')
block(a,0,1.5,0,'選 A／B\n附 C 提示');block(a,1.5,5,1,'讀 A／B adjacency');arr(a,1.5,0,1.5,1);arr(a,5,1,5,0)
block(a,1.8,5.3,2,'提前讀 C adjacency',kind='prefetch');block(a,5.3,7,2,'C 在 buffer',kind='empty')
block(a,5,7,0,'PQ＋更新 frontier\n選中 C');block(a,7,8,1,'Buffer\n回傳 C',kind='empty');arr(a,7,0,7,1);arr(a,8,1,8,0);block(a,8,9.5,0,'處理 C\n繼續探索')
a.annotate('',xy=(7,1.28),xytext=(7,2),arrowprops=dict(arrowstyle='->',color='black',lw=1.5))
a.axvline(10.5,ymin=.68,ymax=.98,color='#666666',ls='--',lw=1)
a.annotate('',xy=(10.5,-.48),xytext=(8,-.48),arrowprops=dict(arrowstyle='|-|',color='black'))
a.text(9.25,-.60,'C 的處理可以提早',ha='center',va='bottom',fontsize=12)
fig.text(.13,.10,'改善：把 C 的 flash read 提前，與目前這輪工作重疊；下一輪只需等待 buffer 回傳。',fontsize=14)
fig.text(.13,.055,'仍存在：A／B 的 batch barrier、host 的 PQ／frontier 更新；若下一步選到未知的 X，此預讀無法命中。',fontsize=13)
for ext in ['png','svg']:fig.savefig(out/('neighbor_prefetch_pipeline.'+ext),dpi=170,bbox_inches='tight',facecolor='white')
plt.close(fig)
print(out/'neighbor_prefetch_pipeline.png')
