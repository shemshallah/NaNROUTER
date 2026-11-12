#!/usr/bin/env python3
"""Build a deterministic 100M-character corpus from extracted text files.

No NaN* code is used.  The source is the published corpus data (or any local
directory of .txt files).  The output and manifest are written under
nanlmv3/data/, which is gitignored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

START = re.compile(rb"(?im)^\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^\n]*\n")
END = re.compile(rb"(?im)^\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK")


def clean(raw: bytes, strip_gutenberg: bool) -> bytes:
    if not strip_gutenberg:
        return raw
    start = START.search(raw)
    end = END.search(raw)
    if start and end and end.start() > start.end():
        return raw[start.end() : end.start()]
    return raw


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", action="append", required=True,
                   help="Directory or .txt file. Can repeat.")
    p.add_argument("--output", default=str(Path.home() / "NaNROUTER" / "nanlmv3" / "data" / "corpus_100m.txt"))
    p.add_argument("--manifest", default=None)
    p.add_argument("--bytes", type=int, default=100_000_000)
    p.add_argument("--min-file-bytes", type=int, default=4096)
    p.add_argument("--max-files", type=int, default=0)
    p.add_argument("--strip-gutenberg", action="store_true", default=True)
    p.add_argument("--no-strip-gutenberg", dest="strip_gutenberg", action="store_false")
    args = p.parse_args()

    files: list[Path] = []
    for spec in args.source:
        path = Path(spec).expanduser()
        if path.is_dir():
            files.extend(sorted(path.rglob("*.txt")))
        elif path.is_file():
            files.append(path)
    files = [f for f in files if f.stat().st_size >= args.min_file_bytes]
    if args.max_files > 0:
        files = files[: args.max_files]
    if not files:
        raise SystemExit("no source .txt files found")

    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    written = 0
    used: list[dict] = []
    with output.open("wb") as out:
        for path in files:
            if written >= args.bytes:
                break
            raw = path.read_bytes()
            raw = clean(raw, args.strip_gutenberg)
            if len(raw) < args.min_file_bytes:
                continue
            take = raw[: args.bytes - written]
            out.write(take)
            if take and take[-1:] != b"\n":
                out.write(b"\n")
                take += b"\n"
            digest.update(take)
            written += len(take)
            used.append({"path": str(path), "bytes": len(take)})

    manifest = {
        "output": str(output),
        "bytes": written,
        "sha256": digest.hexdigest(),
        "files": len(used),
        "sources": used,
    }
    manifest_path = Path(args.manifest).expanduser() if args.manifest else output.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in manifest.items() if k != "sources"}, indent=2, sort_keys=True))
    print(f"files used: {len(used)}; first: {used[0]['path'] if used else None}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
