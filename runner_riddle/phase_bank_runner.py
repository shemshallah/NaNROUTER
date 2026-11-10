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
DEFAULT_OUT = Path("/data/data/com.termux/files/usr/tmp/phase_bank")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def split_bank(path: Path, chunk_bytes: int) -> tuple[Path, list[Path]]:
    """Split a bank into deterministic ordered parts and a parts index."""
    import hashlib
    parts = []
    index = []
    h = hashlib.sha256()
    with path.open("rb") as source:
        ordinal = 0
        while True:
            data = source.read(chunk_bytes)
            if not data:
                break
            part = path.with_name(path.name + f".part{ordinal:02d}")
            part.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            h.update(data)
            parts.append(part)
            index.append({"name": part.name, "bytes": len(data),
                          "sha256": digest})
            ordinal += 1
    document = {
        "schema": "nanlm.phase-bank-parts/1",
        "binary": path.name,
        "bytes": path.stat().st_size,
        "sha256": h.hexdigest(),
        "chunk_bytes": chunk_bytes,
        "parts": index,
    }
    parts_manifest = path.with_name(path.stem + ".parts.json")
    parts_manifest.write_text(
        __import__("json").dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return parts_manifest, parts


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
    ap.add_argument("--release", action="store_true",
                    help="upload the bank and sidecars as GitHub release assets")
    ap.add_argument("--release-repo", default="shemshallah/NaNLMind")
    ap.add_argument("--release-tag", default=None)
    ap.add_argument("--release-title", default=None)
    ap.add_argument("--cleanup-local", action="store_true",
                    help="remove the large local bank after a successful release upload")
    ap.add_argument("--chunk-bytes", type=int, default=0,
                    help="split the bank into release assets no larger than this")
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
    for suffix in (".codebook.bin", ".codes.bin", ".residuals.bin", ".knn.bin", ".spectral.bin", ".matrix.bin"):
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
    release_info = None
    if args.release:
        tag = args.release_tag or f"phase-bank-{args.name}"
        title = args.release_title or f"Phase bank {args.name} (D={args.dim})"
        repo = args.release_repo
        try:
            view = subprocess.run(
                ["gh", "release", "view", tag, "--repo", repo],
                text=True, capture_output=True)
            if view.returncode != 0:
                create = subprocess.run(
                    ["gh", "release", "create", tag, "--repo", repo,
                     "--title", title,
                     "--notes", f"Raw NaN16 phase bank generated by NaNROUTER runner.\n\n"
                                f"dim={args.dim} window={args.window} samples={vectors_doc.get('samples')}"],
                    text=True, capture_output=True)
                if create.returncode != 0:
                    print(create.stderr, file=sys.stderr)
                    return create.returncode
            if args.chunk_bytes > 0 and bin_path.stat().st_size > args.chunk_bytes:
                parts_manifest, parts = split_bank(bin_path, args.chunk_bytes)
                assets = [manifest_path, parts_manifest, *parts]
                split_assets = True
            else:
                assets = [bin_path, manifest_path]
                split_assets = False
            assets.extend(Path(str(prefix) + suffix)
                          for suffix in (".codebook.bin", ".codes.bin",
                                         ".residuals.bin", ".knn.bin",
                                         ".spectral.bin", ".matrix.bin",
                                         ".triads.bin")
                          if Path(str(prefix) + suffix).is_file())
            upload = subprocess.run(
                ["gh", "release", "upload", tag, *[str(a) for a in assets],
                 "--repo", repo, "--clobber"],
                text=True, capture_output=True)
            if upload.returncode != 0:
                print(upload.stderr, file=sys.stderr)
                return upload.returncode
            release_info = {"repo": repo, "tag": tag,
                            "url": f"https://github.com/{repo}/releases/tag/{tag}",
                            "chunked": split_assets,
                            "assets": [a.name for a in assets]}
            manifest["release"] = release_info
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
        except FileNotFoundError:
            print("gh CLI is required for --release", file=sys.stderr)
            return 2
    print(json.dumps({"manifest": str(manifest_path),
                      "binary": str(bin_path),
                      "sha256": manifest["binary_sha256"],
                      "samples": vectors_doc.get("samples"),
                      "release": release_info}, indent=2))
    if args.cleanup_local and release_info is not None:
        for path in [bin_path, json_path, manifest_path]:
            if path.exists():
                path.unlink()
        for suffix in (".codebook.bin", ".codes.bin", ".residuals.bin", ".knn.bin", ".spectral.bin", ".matrix.bin"):
            path = Path(str(prefix) + suffix)
            if path.exists():
                path.unlink()
        print(json.dumps({"cleanup": str(out_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
