#!/usr/bin/env python3
"""Pack original-ID adjacency records into NBRONLY1 pages, without shuffling."""
import argparse
import json
import struct
from pathlib import Path
import numpy as np

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--index', type=Path, required=True)
p.add_argument('--vectors', type=Path, required=True, help='Existing headerless original-ID vectors.bin')
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
with a.index.open('rb') as f:
    h = f.read(4096)
rows, cols = struct.unpack_from('<II', h)
n, d, medoid, stride, per, frozen, fid, reorder = struct.unpack_from('<8Q', h, 8)
if cols != 1 or rows < 8 or d != 128 or stride != 388 or per != 10 or frozen or reorder:
    raise ValueError('Expected unfiltered uint8 SIFT128 R64 full-vector disk index')
if a.index.stat().st_size < 4096 + ((n + per - 1) // per) * 4096:
    raise ValueError('Truncated source index')
if a.vectors.stat().st_size != ((n * 128 + 4095) // 4096) * 4096:
    raise ValueError('Wrong vector file size')
src = np.memmap(a.index, dtype='u1', mode='r', offset=4096, shape=((n + per - 1) // per, 4096))
vectors = np.memmap(a.vectors, dtype='u1', mode='r', shape=(n, 128))
# Check the reused vectors against the source, including both ends and reproducible random IDs.
sample = np.unique(np.r_[0, n-1, np.random.default_rng(0).integers(0, n, min(n, 10000))])
expected = src[(sample // per)[:, None], (sample % per)[:, None] * stride + np.arange(128)]
if not np.array_equal(expected, vectors[sample]):
    raise ValueError('Reused vectors do not match source logical IDs')
manifest = dict(nodes=n, dimension=d, medoid=medoid, layout='neighbor_only_identity',
                neighbor_header_pages=1, neighbor_records_per_page=15, record_bytes=260,
                vector_order='original logical ID', source_index=str(a.index.resolve()),
                vectors=str(a.vectors.resolve()))
if a.out.exists():
    if json.loads((a.out / 'layout.json').read_text()) != manifest:
        raise ValueError('Existing layout manifest differs; use a new output directory')
    if (a.out/'neighbors.bin').stat().st_size != (1+(n+14)//15)*4096:
        raise ValueError('Incomplete neighbor file')
    if (a.out/'old_to_new.bin').stat().st_size != 8+4*n or not (a.out/'new_to_old.bin').samefile(a.out/'old_to_new.bin'):
        raise ValueError('Incomplete identity maps')
    if not (a.out/'vectors.bin').samefile(a.vectors):
        raise ValueError('Vector link mismatch')
    print('Reusing validated layout:', a.out)
    raise SystemExit(0)
a.out.mkdir(parents=True)
header = bytearray(4096)
header[:8] = b'NBRONLY1'
struct.pack_into('<6IQ', header, 8, 1, n, 64, 260, 15, medoid, 0)
with (a.out/'neighbors.bin').open('xb') as nf, (a.out/'old_to_new.bin').open('xb') as mf:
    nf.write(header)
    mf.write(struct.pack('<II', n, 1))
    for start in range(0, n, 150000):  # divisible by 15: no padding between chunks
        count = min(150000, n-start)
        ids = np.arange(start, start+count, dtype=np.uint32)
        records = src[(ids//per)[:, None], (ids%per)[:, None]*stride + np.arange(128, 388)]
        values = records.copy().view('<u4').reshape(count, 65)
        if np.any(values[:, 0] > 64) or np.any(values[:, 1:][np.arange(64)[None, :] < values[:, :1]] >= n):
            raise ValueError('Invalid source adjacency')
        pages = np.zeros(((count+14)//15, 4096), dtype='u1')
        packed = np.zeros((((count+14)//15)*15, 260), dtype='u1')
        packed[:count] = records
        pages[:, :3900] = packed.reshape(-1, 3900)
        nf.write(pages.tobytes())
        mf.write(ids.astype('<u4').tobytes())
        if start // 150000 % 20 == 0 or start+count == n:
            print(f'Packed {start+count:,}/{n:,} nodes', flush=True)
(a.out/'new_to_old.bin').symlink_to('old_to_new.bin')
(a.out/'vectors.bin').symlink_to(a.vectors.resolve())
(a.out/'layout.json').write_text(json.dumps(manifest, indent=2)+'\n')
print('Layout ready:', a.out, flush=True)
