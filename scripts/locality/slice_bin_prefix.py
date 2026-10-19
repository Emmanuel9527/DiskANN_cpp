#!/usr/bin/env python3
"""Write the first N vectors from a DiskANN uint8/uint32/float32 .bin file."""

import argparse
import struct
from pathlib import Path


DTYPE_SIZE = {"uint8": 1, "uint32": 4, "float32": 4}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--count", required=True, type=int)
    parser.add_argument("--dtype", required=True, choices=DTYPE_SIZE)
    args = parser.parse_args()

    source_path = Path(args.input)
    output_path = Path(args.output)
    with source_path.open("rb") as source:
        header = source.read(8)
        if len(header) != 8:
            raise SystemExit(f"Invalid DiskANN bin header: {source_path}")
        npts, dims = struct.unpack("<II", header)
        expected_size = 8 + npts * dims * DTYPE_SIZE[args.dtype]
        actual_size = source_path.stat().st_size
        if expected_size != actual_size:
            raise SystemExit(
                f"Unexpected file size for {source_path}: expected {expected_size}, got {actual_size}"
            )
        if args.count <= 0 or args.count > npts:
            raise SystemExit(f"count must be in [1, {npts}], got {args.count}")

        remaining = args.count * dims * DTYPE_SIZE[args.dtype]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("wb") as destination:
            destination.write(struct.pack("<II", args.count, dims))
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise SystemExit(f"Unexpected end of input while reading {source_path}")
                destination.write(chunk)
                remaining -= len(chunk)
    print(f"Wrote {args.count} x {dims} {args.dtype} vectors to {output_path}")


if __name__ == "__main__":
    main()
