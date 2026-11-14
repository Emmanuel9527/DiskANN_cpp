#!/usr/bin/env python3
"""Run instrumented native MQSim backend in an isolated copy; no changes to installation."""
import argparse, concurrent.futures, hashlib, json, pathlib, shutil, subprocess, sys
HERE=pathlib.Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--mqsim',type=pathlib.Path,default=pathlib.Path('/home/emmanuel/projects/MQSim'));p.add_argument('--out',type=pathlib.Path,required=True);a=p.parse_args()
a.out=a.out.resolve();a.mqsim=a.mqsim.resolve();a.out.mkdir(parents=True,exist_ok=False)
copy=a.out/'mqsim';shutil.copytree(a.mqsim/'src',copy/'src')
manifest={'source':str(a.mqsim),'commit':subprocess.check_output(['git','-C',str(a.mqsim),'rev-parse','HEAD'],text=True).strip(),'source_status':subprocess.check_output(['git','-C',str(a.mqsim),'status','--short'],text=True),'sha256':{str(x.relative_to(a.mqsim)):hashlib.sha256(x.read_bytes()).hexdigest() for x in sorted((a.mqsim/'src').rglob('*')) if x.is_file()},'model':{'channels':2,'chips_per_channel':2,'dies_per_chip':2,'planes_per_die':1,'request_bytes':4096,'array_read_ns':50000,'RB_signal_delay_ns':0,'channel_width_bytes':1,'DDR_two_byte_ns':6,'window':4,'bypass':['host NVMe/PCIe','L2P','data cache','GC','ECC/retry'],'refill_event_delay_ns':1}}
(a.out/'manifest.json').write_text(json.dumps(manifest,indent=2))
for script in ['run.py', 'lab.cpp', 'analyze.py']:
 shutil.copy2(HERE/script, a.out/script)
f=copy/'src/ssd/NVM_PHY_ONFI_NVDDR2.cpp';s=f.read_text();s='#include "lab_trace.h"\n'+s
patches=[
('dieBKE->Free = false;', 'lab_trace("dispatch", transaction_list.front());\n\t\tdieBKE->Free = false;'),
('targetChip->EndCMDXfer(dieBKE->ActiveCommand);','for(auto tr: dieBKE->ActiveTransactions) lab_trace("array_start",tr);\n\t\t\t\ttargetChip->EndCMDXfer(dieBKE->ActiveCommand);'),
('chipBKE->No_of_active_dies--;','for(auto tr: dieBKE->ActiveTransactions) lab_trace("array_end",tr);\n\t\t\tchipBKE->No_of_active_dies--;'),
('dieBKE->ActiveTransfer = tr;','lab_trace("data_start",tr);\n\t\tdieBKE->ActiveTransfer = tr;'),
('targetChip->EndDataOutXfer(dieBKE->ActiveCommand);','lab_trace("data_end",dieBKE->ActiveTransfer);\n\t\t\t\ttargetChip->EndDataOutXfer(dieBKE->ActiveCommand);'),
('ONFI_Channel_NVDDR2* target_channel = channels[bookKeepingEntry->ActiveTransactions.front()->Address.ChannelID];','lab_trace("cmd_start",bookKeepingEntry->ActiveTransactions.front());\n\t\tONFI_Channel_NVDDR2* target_channel = channels[bookKeepingEntry->ActiveTransactions.front()->Address.ChannelID];'),
('targetChip->StartCMDXfer();\n\t\t\t\t\tchipBKE->Status = ChipStatus::CMD_IN;', 'lab_trace("cmd_start",transaction_list.front());\n\t\t\t\t\ttargetChip->StartCMDXfer();\n\t\t\t\t\tchipBKE->Status = ChipStatus::CMD_IN;')]
for old,new in patches:
 assert old in s,old;s=s.replace(old,new,1)
f.write_text(s)
(copy/'src/lab_trace.h').write_text('#pragma once\n#include "ssd/NVM_Transaction_Flash.h"\nvoid lab_trace(const char*, SSD_Components::NVM_Transaction_Flash*);\n')
shutil.copy2(HERE/'lab.cpp',copy/'lab.cpp')
# Instrumentation only; preserve the diff so scheduling changes can be audited.
diff=subprocess.run(['diff','-u',str(a.mqsim/'src/ssd/NVM_PHY_ONFI_NVDDR2.cpp'),str(f)],text=True,capture_output=True)
(a.out/'instrumentation.patch').write_text(diff.stdout)
sources=[x for x in (copy/'src').rglob('*.cpp') if x.name!='main.cpp']+[copy/'lab.cpp']
obj=copy/'obj';obj.mkdir()
flags=['g++','-std=c++11','-O1','-g','-ffunction-sections','-fdata-sections','-I'+str(copy/'src')]
def build(x):
 dest=obj/(str(x.relative_to(copy)).replace('/','_')+'.o')
 r=subprocess.run(flags+['-c',str(x),'-o',str(dest)],capture_output=True,text=True)
 if r.returncode:raise RuntimeError(str(x)+'\n'+r.stderr)
 return dest,r.stderr
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool: built=list(pool.map(build,sources))
(a.out/'build.log').write_text(''.join(x[1] for x in built))
exe=copy/'pipeline_lab';subprocess.run(['g++','-Wl,--gc-sections',*[str(x[0]) for x in built],'-o',str(exe)],check=True)
for name,mode,gap in [('channels','channels',0),('chips','chips',0),('dies','dies',0),('pages','pages',0),('phy_die_interleave','phy_die_interleave',0),('batch_gap0','batch',0),('batch_gap20us','batch',20000),('stream','stream',0)]:
 with (a.out/(name+'.csv')).open('w') as f:subprocess.run([str(exe),mode,str(gap)],stdout=f,check=True)
subprocess.run([sys.executable,str(HERE/'analyze.py'),str(a.out)],check=True)
print(a.out,flush=True)
