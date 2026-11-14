#!/usr/bin/env python3
import argparse,json,hashlib,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();out=a.out.resolve()
backend=Path('results/mqsim_pipeline_lab/mqsim').resolve()
manifest=dict(backend_manifest=json.loads(Path('results/mqsim_pipeline_lab/manifest.json').read_text()),backend_objects={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in (backend/'obj').glob('*.o') if x.name!='lab.cpp.o'},channels=8,chips_per_channel=4,dies_per_chip=2,planes_per_die=1,array_read_ns=[50000,100000],dataout_ns=12288,command_ns=290,queries_requested_per_setting=1000,policy='one batch ahead; prefetch starts previous batch completion + 1ns; retain measured within-batch issue offsets; demand next batch at simulated previous completion + measured gap',cache='no persistent reuse across batches, same physical transaction count in both policies; sufficient result buffer',mapping='LBA/8 striped or splitmix64 then ch/chip/die; unique compact addresses within each die',limitations=['native TSU serializes reads within chip','no NVMe/PCIe/FTL/GC/ECC/PQ compute cost','isolated single query, no background IO','block boundary timestamps, microsecond precision','trace host gap held constant after acceleration; no traversal re-execution'])
(out/'manifest.json').write_text(json.dumps(manifest,indent=2))
for folder in sorted(out.glob('L*_W*')):
 for mapping,read in [('stripe',50000),('hash',50000),('stripe',100000)]:
  for mode in ['baseline','oracle']:
   name=f'{mapping}_r{read}_{mode}'
   subprocess.run([str(out/'replay'),str(folder/'input.txt'),mode,str(folder/name),mapping,str(read)],check=True)
   print(folder.name,name,flush=True)
