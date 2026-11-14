#!/usr/bin/env python3
"""Reproducible sampled consistency checks of the three SIFT100M layouts."""
import argparse
import json
import struct
from pathlib import Path
import numpy as np


def disk(path):
    with open(path, 'rb') as f:
        h = f.read(4096)
    n, d, medoid, stride, per = struct.unpack_from('<5Q', h, 8)
    assert (n, d, stride, per) == (100000000, 128, 388, 10), path
    data = np.memmap(path, dtype='u1', mode='r', offset=4096, shape=((n+per-1)//per, 4096))
    return medoid, lambda ids: data[(ids//per)[:, None], (ids%per)[:, None]*stride+np.arange(stride)]


def binary(path, dtype):
    with open(path, 'rb') as f:
        n, d = struct.unpack('<II', f.read(8))
    assert Path(path).stat().st_size == 8+n*d*np.dtype(dtype).itemsize
    return np.memmap(path, dtype=dtype, mode='r', offset=8, shape=(n, d))


def verify(default, shuffled, layout):
    n = 100000000
    medoid, original = disk(default+'_disk.index')
    shuffled_medoid, reordered = disk(shuffled+'_disk.index')
    old_to_new = binary(shuffled+'_disk.index_block_shuffle_old_to_new.bin', '<u4')[:, 0]
    new_to_old = binary(shuffled+'_disk.index_block_shuffle_new_to_old.bin', '<u4')[:, 0]
    assert len(old_to_new) == len(new_to_old) == n
    ids = np.unique(np.r_[0, n-1, medoid, np.random.default_rng(42).integers(0, n, 10000)]).astype(np.int64)
    remapped = old_to_new[ids].astype(np.int64)
    assert np.all(remapped < n) and np.array_equal(new_to_old[remapped], ids)
    assert new_to_old[shuffled_medoid] == medoid
    a, b = original(ids), reordered(remapped)
    assert np.array_equal(a[:, :132], b[:, :132]), 'vectors or degree changed'
    av, bv = a[:, 128:].copy().view('<u4'), b[:, 128:].copy().view('<u4')
    mask = np.arange(64)[None, :] < av[:, :1]
    assert np.array_equal(av[:, 1:][mask], new_to_old[bv[:, 1:][mask]]), 'edges changed'
    pq_a, pq_b = binary(default+'_pq_compressed.bin', 'u1'), binary(shuffled+'_pq_compressed.bin', 'u1')
    assert pq_a.shape == pq_b.shape and pq_a.shape[0] == n
    assert np.array_equal(pq_a[ids], pq_b[remapped]), 'PQ remap mismatch'
    assert Path(default+'_pq_pivots.bin').read_bytes() == Path(shuffled+'_pq_pivots.bin').read_bytes(), 'PQ tables differ'
    layout = Path(layout)
    nh = np.memmap(layout/'neighbors.bin', dtype='u1', mode='r', offset=4096, shape=((n+14)//15, 4096))
    records = nh[(ids//15)[:, None], (ids%15)[:, None]*260+np.arange(260)]
    assert np.array_equal(records, a[:, 128:]), 'identity adjacency mismatch'
    assert np.array_equal(binary(layout/'old_to_new.bin', '<u4')[ids, 0], ids)
    assert np.array_equal(binary(layout/'new_to_old.bin', '<u4')[ids, 0], ids)
    return dict(sampled_nodes=len(ids), seed=42, nodes=n, pq_bytes=pq_a.shape[1],
                medoid=medoid, shuffled_medoid=shuffled_medoid, status='passed',
                scope='Sampled records, edges, vectors, PQ codes and maps; complete PQ pivot files')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--default', required=True)
    p.add_argument('--shuffled', required=True)
    p.add_argument('--layout', required=True)
    a = p.parse_args()
    print(json.dumps(verify(a.default, a.shuffled, a.layout), indent=2))
