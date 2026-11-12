#!/usr/bin/env python3
"""Build a chunk-sampled corpus with a chunk-disjoint validation tail.

The 100M corpus is sorted by book.  Taking ``head -c`` would put the validation
split inside the first few books, which is out-of-distribution.  This utility
samples contiguous chunks evenly across the source and writes the reserved
validation chunks *last*, so the model's contiguous 90/10 split sees held-out
chunks from across the corpus.

No NaN* code or data is used beyond the corpus file itself.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--bytes", type=int, default=20_000_000)
    p.add_argument("--chunks", type=int, default=20)
    p.add_argument("--val-chunks", type=int, default=0,
                   help="Reserve this many chunks and write them last.")
    p.add_argument("--manifest", default=None)
    args = p.parse_args()

    src = Path(args.source).expanduser().read_bytes()
    total = len(src)
    if total == 0:
        raise SystemExit("empty source")
    chunks = max(1, args.chunks)
    chunk_bytes = max(1, args.bytes // chunks)
    val_chunks = max(0, min(args.val_chunks, chunks - 1))
    train_chunks = chunks - val_chunks
    stride = max(1, (total - chunk_bytes) // max(1, chunks - 1))

    selected: list[tuple[int, int]] = []
    for i in range(chunks):
        offset = min(i * stride, total - chunk_bytes)
        selected.append((offset, min(chunk_bytes, total - offset)))
    if val_chunks:
        val_indices = sorted(
            {
                min(chunks - 1, (i + 1) * chunks // (val_chunks + 1))
                for i in range(val_chunks)
            }
        )
    else:
        val_indices = []
    val_set = set(val_indices)
    train = [selected[i] for i in range(chunks) if i not in val_set]
    val = [selected[i] for i in val_indices]

    out = Path(args.output).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out.open("wb") as fh:
        for offset, size in train + val:
            fh.write(src[offset : offset + size])
            written += size

    print(f"chunks={chunks} train={len(train)} val={len(val)} "
          f"chunk_bytes={chunk_bytes} bytes={written}")
    print(f"train_offsets={[o for o, _ in train][:5]}... "
          f"val_offsets={[o for o, _ in val]}")
    if args.manifest:
        import json
        Path(args.manifest).expanduser().write_text(
            json.dumps(
                {
                    "source": str(Path(args.source).expanduser()),
                    "output": str(out),
                    "bytes": written,
                    "chunks": chunks,
                    "chunk_bytes": chunk_bytes,
                    "train_chunks": len(train),
                    "val_chunks": len(val),
                    "train_offsets": [o for o, _ in train],
                    "val_offsets": [o for o, _ in val],
                    "val_chunk_indices": val_indices,
                },
                indent=2,
            )
            + "\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
