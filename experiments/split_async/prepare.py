"""Split a uint8 DiskANN index without changing graph IDs or edges."""
import argparse, json, struct
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--index',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
a=p.parse_args()
with a.index.open('rb') as f:
    h=f.read(4096)
rows,cols=struct.unpack_from('<II',h)
n,d,medoid,stride,per,frozen,fid,reorder=struct.unpack_from('<8Q',h,8)
if cols!=1 or rows<8 or d!=128 or stride!=388 or per!=10 or frozen or reorder:
    raise ValueError('Expected unfiltered uint8 SIFT128 R64 index, without disk PQ/reorder/frozen nodes')
if a.index.stat().st_size < 4096+(n+per-1)//per*4096:
    raise ValueError('Truncated input')
a.out.mkdir(parents=True,exist_ok=False)
src=np.memmap(a.index,dtype='u1',mode='r',offset=4096,shape=((n+per-1)//per,4096))
# Bounded working memory; source IDs and PQ indexing are preserved.
with (a.out/'neighbors.bin').open('wb') as nf, (a.out/'vectors.bin').open('wb') as vf:
    for start in range(0,n,150000):
        count=min(150000,n-start)
        ids=np.arange(start,start+count,dtype=np.uint64)
        records=src[(ids//per)[:,None],(ids%per)[:,None]*stride+np.arange(stride)[None,:]]
        degree=records[:,128:132].copy().view('<u4').reshape(-1)
        if np.any(degree>64): raise ValueError('Invalid degree')
        neighbors=records[:,132:].copy().view('<u4')
        mask=np.arange(64)[None,:]<degree[:,None]
        if np.any(neighbors[mask]>=n): raise ValueError('Invalid neighbor ID')
        pages=np.zeros(((count+14)//15,4096),dtype='u1')
        target=pages[:,:3900].reshape(-1,15,260)
        padded=np.zeros((((count+14)//15)*15,260),dtype='u1')
        padded[:count]=records[:,128:388]
        target[:]=padded.reshape(-1,15,260)
        nf.write(pages.tobytes())
        vf.write(records[:,:128].tobytes())
        print(f'{start+count}/{n}',flush=True)
    vf.write(bytes((-n*128)%4096))
(a.out/'layout.json').write_text(json.dumps(dict(nodes=n,dimension=d,medoid=medoid,degree=64,
    data_type='uint8',page_bytes=4096,neighbor_records_per_page=15,vector_records_per_page=32,
    header_pages=0,id_order='source index IDs',source_index=str(a.index.resolve())),indent=2)+'\n')
