#!/usr/bin/env python3
"""Local offline fallback for the cached CPython 3.11 pandas wheel; no installation."""
import sys,pathlib,runpy
for p in pathlib.Path('/home/emmanuel/.cache/uv/archive-v0').iterdir():
 if p.is_dir():
  so=list(p.rglob('*.so'))
  if not any('cpython-' in x.name and 'cpython-311' not in x.name for x in so):sys.path.append(str(p))
runpy.run_path(str(pathlib.Path(__file__).with_name('analyze.py')),run_name='__main__')
