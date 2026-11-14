#!/usr/bin/env python3
"""Build from the existing isolated logging-only MQSim source; not installation."""
import argparse,concurrent.futures,hashlib,json,shutil,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('out',type=Path);p.add_argument('--backend',type=Path,default=Path('results/mqsim_pipeline_lab/mqsim/src'));a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
dest=a.out/'backend_src'
if not dest.exists():shutil.copytree(a.backend,dest)
obj=a.out/'obj';obj.mkdir(exist_ok=True)
sources=[x for x in dest.rglob('*.cpp') if x.name!='main.cpp']+[Path(__file__).with_name('replay.cpp').resolve()]
def build(x):
 name=str(x.relative_to(dest)) if x.is_relative_to(dest) else 'replay.cpp';o=obj/(name.replace('/','_')+'.o')
 r=subprocess.run(['g++','-std=c++11','-O1','-g','-ffunction-sections','-fdata-sections','-I'+str(dest),'-c',str(x),'-o',str(o)],text=True,capture_output=True)
 if r.returncode:raise RuntimeError(r.stderr)
 return str(o),r.stderr
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(build,sources))
(a.out/'build.log').write_text(''.join(r[1] for r in results));subprocess.run(['g++','-Wl,--gc-sections',*[r[0] for r in results],'-o',str(a.out/'replay')],check=True)
(a.out/'build_sources.json').write_text(json.dumps({str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in sources},indent=2))
