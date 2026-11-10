#!/usr/bin/env python3
"""NaNROUTER runner adapter for the raw-NaN16 phase-vector bank.

The vector arithmetic is performed by NaNLMind's guest kernels via
`phase-ingest`. This runner only schedules the command, selects an external
output directory, verifies the emitted digest, and publishes a small manifest.
It never calculates vector or trig values on the host.

Example:
  python3 -m runner_riddle.phase_bank_runner \
    --corpus /data/data/com.termux/files/home/NaNLMind/state/gutenberg_150_train.txt \
    --out-dir /storage/emulated/0/Download/NaNLMind/phase_bank \
    --dim 64 --window 8
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_NANLMIND = Path("/data/data/com.termux/files/home/NaNLMind")
DEFAULT_OUT = Path("/storage/emulated/0/Download/NaNLMind/phase_bank")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--name", default="gutenberg150")
    ap.add_argument("--dim", type=int, choices=(64, 128), default=64)
    ap.add_argument("--window", type=int, choices=range(1, 9), default=8)
    ap.add_argument("--max-lines", type=int, default=0)
    ap.add_argument("--max-windows", type=int, default=0)
    ap.add_argument("--nanlmind", type=Path, default=DEFAULT_NANLMIND)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--allow-repo", action="store_true")
    args = ap.parse_args()

    out_dir = args.out_dir.expanduser().resolve()
    repo_roots = [args.nanlmind.resolve(), Path(__file__).resolve().parents[1]]
    if not args.allow_repo and any(
            out_dir == root or root in out_dir.parents for root in repo_roots):
        print("refusing to write phase bank inside a repository; "
              "choose an external --out-dir", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / args.name
    bin_path = Path(str(prefix) + ".bin")
    json_path = Path(str(prefix) + ".json")
    manifest_path = out_dir / (args.name + ".manifest.json")
    if not args.force:
        for path in (bin_path, json_path, manifest_path):
            if path.exists():
                print(f"refusing to overwrite {path}; use --force", file=sys.stderr)
                return 2

    binary = args.nanlmind / "build" / "nanlm-universal"
    if not binary.is_file():
        print(f"missing NaNLMind binary: {binary}", file=sys.stderr)
        return 2
    command = [
        str(binary), "phase-ingest", str(args.corpus),
        str(args.max_lines), str(args.window), str(args.dim),
        str(args.max_windows), str(prefix),
    ]
    print(json.dumps({"runner": "NaNROUTER/phase-bank",
                      "command": command}, sort_keys=True), flush=True)
    completed = subprocess.run(command, cwd=args.nanlmind)
    if completed.returncode != 0:
        print(f"phase-ingest failed rc={completed.returncode}", file=sys.stderr)
        return completed.returncode
    vectors_doc = json.loads(json_path.read_text(encoding="utf-8"))
    artifacts = {}
    for suffix in (".codes.bin", ".knn.bin", ".spectral.bin"):
        artifact = Path(str(prefix) + suffix)
        if artifact.is_file():
            artifacts[suffix] = {
                "path": str(artifact),
                "bytes": artifact.stat().st_size,
                "sha256": sha256_file(artifact),
            }
    manifest = {
        "schema": "nanlm.phase-bank-runner/1",
        "runner": "NaNROUTER/phase-bank",
        "canonical_universe": "HW0::BS0",
        "node_instantiated": False,
        "math_owner": "NaNLMind raw NaN16 guest",
        "host_role": "schedule, transport, digest, external storage only",
        "corpus": str(args.corpus),
        "corpus_sha256": sha256_file(args.corpus),
        "dim": args.dim,
        "window": args.window,
        "vectors": vectors_doc,
        "artifacts": artifacts,
        "binary": str(bin_path),
        "binary_bytes": bin_path.stat().st_size,
        "binary_sha256": sha256_file(bin_path),
        "command": command,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path),
                      "binary": str(bin_path),
                      "sha256": manifest["binary_sha256"],
                      "samples": vectors_doc.get("samples")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
