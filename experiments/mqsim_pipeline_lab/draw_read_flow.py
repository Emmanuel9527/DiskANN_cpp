#!/usr/bin/env python3
"""Export a Chinese explanatory read flow as PNG and editable SVG."""
from pathlib import Path
from html import escape
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[2]/'results/mqsim_pipeline_lab'
ROOT.mkdir(parents=True,exist_ok=True)
W,H=1200,1410
im=Image.new('RGB',(W,H),'white');d=ImageDraw.Draw(im);svg=[]
FONT='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
def txt(x,y,s,size=25,c='#333333'):
 f=ImageFont.truetype(FONT,size)
 d.text((x,y),s,font=f,fill=c,anchor='mm')
 svg.append(f'<text x="{x}" y="{y}" text-anchor="middle" dominant-baseline="central" font-family="Noto Sans CJK TC,sans-serif" font-size="{size}" fill="{c}">{escape(s)}</text>')
def box(x,y,w,h,lines,fill='#ffffff',stroke='#333333'):
 d.rounded_rectangle((x,y,x+w,y+h),radius=16,fill=fill,outline=stroke,width=2)
 svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
 for i,s in enumerate(lines):txt(x+w/2,y+h/2+(i-(len(lines)-1)/2)*34,s,25 if i==0 else 21)
def arrow(points):
 d.line(points,fill='#333333',width=3)
 x,y=points[-1];px,py=points[-2]
 if y>py:tri=[(x,y),(x-7,y-12),(x+7,y-12)]
 elif x>px:tri=[(x,y),(x-12,y-7),(x-12,y+7)]
 else:tri=[(x,y),(x+12,y-7),(x+12,y+7)]
 d.polygon(tri,fill='#333333')
 svg.append('<polyline points="'+' '.join(f'{x},{y}' for x,y in points)+'" fill="none" stroke="#333333" stroke-width="3"/>')
 svg.append('<polygon points="'+' '.join(f'{x},{y}' for x,y in tri)+'" fill="#333333"/>')
txt(600,56,'MQSim：一筆 NAND Read 的流程',36)
txt(600,106,'兩次等待：等「開始讀」→ 等「把資料傳出來」',25,'#333333')
x=160;w=600;cx=460
box(x,155,w,70,['提交讀取請求'])
arrow([(cx,225),(cx,260)])
box(x,260,w,110,['① TSU 排隊：等待開始讀取','UserReadTRQueue[channel][chip]'],'#ffffff','#333333')
arrow([(cx,370),(cx,405)])
box(x,405,w,80,['排程器確認 channel／chip 可派發'])
arrow([(cx,485),(cx,520)])
box(x,520,w,100,['傳送 Command／Address','占用 channel'],'#ffffff')
arrow([(cx,620),(cx,655)])
box(x,655,w,110,['NAND array 讀取資料','Channel 可供其他工作使用'],'#ffffff','#333333')
arrow([(cx,765),(cx,805)])
pts=[(cx,805),(cx+190,885),(cx,965),(cx-190,885)]
d.polygon(pts,fill='#ffffff',outline='#333333',width=2)
svg.append('<polygon points="'+' '.join(f'{x},{y}' for x,y in pts)+'" fill="#ffffff" stroke="#333333" stroke-width="2"/>')
txt(cx,885,'Channel 空閒？',26)
arrow([(650,885),(800,885)])
txt(720,856,'否',22)
box(800,820,350,130,['② PHY 排隊','資料已讀好，等待傳輸','WaitingReadTX[channel]'],'#ffffff','#333333')
arrow([(cx,965),(cx,1040)])
txt(cx-30,1001,'是',22)
arrow([(975,950),(975,1095),(760,1095)])
txt(1070,1007,'Channel 可用時',22)
box(x,1040,w,110,['Data-out：資料傳到 controller','占用 channel'],'#ffffff','#333333')
arrow([(cx,1150),(cx,1190)])
box(x,1190,w,85,['NAND read transaction 完成'],'#ffffff','#333333')
txt(600,1330,'注意：此處完成的是 NAND → controller，尚不等於回到 host。',23,'#333333')
txt(600,1370,'簡化流程：一般 USERIO read；依本次 MQSim OUT_OF_ORDER 路徑。',20,'#333333')
im.save(ROOT/'read_flow.png')
(ROOT/'read_flow.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}"><rect width="100%" height="100%" fill="white"/>'+''.join(svg)+'</svg>')
print(ROOT/'read_flow.png');print(ROOT/'read_flow.svg')
