#!/usr/bin/env python3
"""Register the R10 native MTH capability manifest into MC0DB.

This is control-plane bookkeeping: it hashes source/fixture files and records
operator/capability rows. It does not execute or recompute mathematics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DEFAULT_MANIFEST = REPO_ROOT / "spec" / "wave-capabilities.json"
# MTH guest working-set ceiling: 1 MiB / 8 bytes per NaN16 word.
DEFAULT_GUEST_WORKSPACE_WORDS = 262_144


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != "nanrouter.wave-capabilities.v1":
        raise ValueError("unsupported capability manifest schema")
    kernels = document.get("kernels")
    if not isinstance(kernels, list) or not kernels:
        raise ValueError("manifest has no kernels")
    seen: set[str] = set()
    for kernel in kernels:
        kernel_id = kernel.get("kernel_id")
        if not kernel_id or kernel_id in seen:
            raise ValueError(f"missing or duplicate kernel_id: {kernel_id!r}")
        seen.add(kernel_id)
        for field in ("source", "fixture", "marker", "precision"):
            if not kernel.get(field):
                raise ValueError(f"{kernel_id}: missing {field}")
        if not isinstance(kernel.get("steps"), int) or kernel["steps"] < 0:
            raise ValueError(f"{kernel_id}: invalid steps")
        if not isinstance(kernel.get("workspace_words"), int) or kernel["workspace_words"] < 0:
            raise ValueError(f"{kernel_id}: invalid workspace_words")
        for field in ("source", "fixture"):
            if not (REPO_ROOT / kernel[field]).is_file():
                raise ValueError(f"{kernel_id}: missing {field} file")
    return document


def register_manifest(store, manifest: dict[str, Any], *, runner_id: str,
                      epoch: int = 1, nanclock_tick: int = 0,
                      guest_workspace_words: int = DEFAULT_GUEST_WORKSPACE_WORDS,
                      dry_run: bool = False) -> list[dict[str, Any]]:
    from runner_riddle.wave_store import WaveStore  # local import for CLI

    if not dry_run and not isinstance(store, WaveStore):
        raise TypeError("store must be a WaveStore")
    if not isinstance(guest_workspace_words, int) or guest_workspace_words < 0:
        raise ValueError("guest_workspace_words must be a non-negative integer")
    rows: list[dict[str, Any]] = []
    for kernel in manifest["kernels"]:
        source = REPO_ROOT / kernel["source"]
        fixture = REPO_ROOT / kernel["fixture"]
        source_digest = sha256_file(source)
        fixture_digest = sha256_file(fixture)
        shape = {
            "shape": kernel.get("shape", []),
            "fixture": kernel["fixture"],
            "fixture_digest": fixture_digest,
            "marker": kernel["marker"],
            "steps": kernel["steps"],
            "ci_verified": bool(kernel.get("ci_verified", False)),
        }
        record = {
            "kernel_id": kernel["kernel_id"],
            "source_digest": source_digest,
            "fixture_digest": fixture_digest,
            "precision": kernel["precision"],
            "workspace_words": kernel["workspace_words"],
        }
        rows.append(record)
        if dry_run:
            continue
        store.register_operator(
            operator_id=kernel["kernel_id"],
            version=1,
            digest=source_digest,
            shape=shape,
            precision=kernel["precision"],
            evidence_level="native_verified",
            workspace=kernel["workspace_words"],
            status="active",
            nanclock_tick=nanclock_tick,
        )
        store.register_capability(
            kernel_id=kernel["kernel_id"],
            runner_id=runner_id,
            verified_digest=source_digest,
            # Capability workspace is the runner's available guest budget;
            # operator.workspace above remains the kernel's required workspace.
            workspace=guest_workspace_words,
            precision=kernel["precision"],
            status="native_verified",
            epoch=epoch,
            nanclock_tick=nanclock_tick,
        )
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--bs0db", type=Path, help="BS0DB SQLite path")
    parser.add_argument("--mc0db", type=Path, help="MC0DB SQLite path")
    parser.add_argument("--runner-id", default="MC0:0/R0")
    budget = parser.add_mutually_exclusive_group()
    budget.add_argument("--guest-workspace-words", type=int,
                        help="available guest workspace in NaN16 words")
    budget.add_argument("--guest-workspace-mib", type=int,
                        help="available guest workspace in MiB (2 MiB = 262144 NaN16 words)")
    parser.add_argument("--epoch", type=int, default=1)
    parser.add_argument("--tick", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.guest_workspace_words is not None:
        guest_workspace_words = args.guest_workspace_words
    elif args.guest_workspace_mib is not None:
        guest_workspace_words = args.guest_workspace_mib * 262_144
    else:
        guest_workspace_words = DEFAULT_GUEST_WORKSPACE_WORDS
    if guest_workspace_words < 0:
        print("guest workspace must be non-negative", file=sys.stderr)
        return 2
    manifest = load_manifest(args.manifest)
    if args.dry_run:
        rows = register_manifest(None, manifest, runner_id=args.runner_id, dry_run=True)
        for row in rows:
            print(f"{row['kernel_id']} {row['source_digest'][:12]} {row['precision']}")
        print(f"{len(rows)} kernels; dry run only")
        return 0
    if args.bs0db is None or args.mc0db is None:
        print("--bs0db and --mc0db are required unless --dry-run is used", file=sys.stderr)
        return 2
    from runner_riddle.wave_store import WaveStore

    store = WaveStore(args.bs0db, args.mc0db)
    rows = register_manifest(
        store, manifest, runner_id=args.runner_id, epoch=args.epoch,
        nanclock_tick=args.tick,
        guest_workspace_words=guest_workspace_words,
    )
    print(f"registered {len(rows)} kernels for {args.runner_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
