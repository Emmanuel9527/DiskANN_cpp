"""Use existing NBRONLY1 shuffle and pack original-order SIFT100M uint8 vectors."""
import argparse,json,struct,shutil
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--neighbor-prefix',type=Path,required=True)
p.add_argument('--base',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
a=p.parse_args()
prefix=str(a.neighbor_prefix.resolve())
with open(prefix+'.nbr.index','rb') as f: h=f.read(4096)
version,n,width,record,slots,medoid=struct.unpack_from('<6I',h,8)
if h[:8]!=b'NBRONLY1' or (version,width,record,slots)!=(1,64,260,15):
    raise ValueError('Expected NBRONLY1 R64, 15 records/page')
with a.base.open('rb') as f: bn,dim=struct.unpack('<II',f.read(8))
if (bn,dim)!=(n,128) or a.base.stat().st_size!=8+n*128:
    raise ValueError('Base must be matching original-ID uint8 SIFT128')
for suffix in ('.old_to_new.bin','.new_to_old.bin'):
    with open(prefix+suffix,'rb') as f: shape=struct.unpack('<II',f.read(8))
    if shape!=(n,1): raise ValueError('Map shape mismatch')
a.out.mkdir(parents=True,exist_ok=False)
for suffix,name in (('.nbr.index','neighbors.bin'),('.old_to_new.bin','old_to_new.bin'),('.new_to_old.bin','new_to_old.bin')):
    (a.out/name).symlink_to(prefix+suffix)
with a.base.open('rb') as src,(a.out/'vectors.bin').open('wb') as dst:
    src.seek(8)
    copied=0;report_at=0;total=n*128
    print(f'Copying original-order vectors: {total/1e9:.2f} GB',flush=True)
    while True:
        chunk=src.read(16*1024*1024)
        if not chunk: break
        dst.write(chunk);copied+=len(chunk)
        if copied>=report_at or copied==total:
            print(f'Vector copy: {copied/1e9:.2f}/{total/1e9:.2f} GB ({copied*100/total:.1f}%)',flush=True)
            report_at=copied+512*1024*1024
    dst.write(bytes((-n*128)%4096))
(a.out/'layout.json').write_text(json.dumps(dict(nodes=n,dimension=128,medoid=medoid,
    neighbor_header_pages=1,vector_header_pages=0,neighbor_prefix=prefix,
    vector_order='original logical ID',base=str(a.base.resolve())),indent=2)+'\n')
print('Layout ready:',a.out,'medoid:',medoid)
