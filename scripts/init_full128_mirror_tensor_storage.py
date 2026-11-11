#!/usr/bin/env python3
"""Provision/verify FULL 128 MiB dual f32 hypertensors without host ML.

Transport/layout only: this module never computes gradients, updates weights,
chooses candidates, or writes the canonical 8 MiB NaN16 root. The trained
candidate update decision runs in native NaN16; promotion and journaling are
intentionally NOT performed by this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

N = 256
SCALAR_BYTES = 4
BANK_BYTES = N**3 * SCALAR_BYTES              # 64 MiB
TOTAL_BYTES = BANK_BYTES * 2                   # 128 MiB
HEAD_BANK_BYTES = N*N*SCALAR_BYTES            # 256 KiB
MIRROR_PAIRS = N*(N-1)//2                    # 32,640
FIXED_POINTS = N                              # 256


def physical_offset(bank: int, h: int, a: int, b: int) -> tuple[int, int, int]:
    """Pure storage-address oracle matching the independently tested guest.

    A mirrored unordered pair has one canonical identity but two fully
    independent float32 directional words. The two full banks are replicas
    of the ADDRESS SPACE, not necessarily identical weights.
    """
    if bank not in (0, 1):
        raise ValueError("invalid full-tensor bank")
    if any(type(v) is not int or not 0 <= v <= 254 for v in (h, a, b)):
        raise ValueError("void255/out-of-range head coordinate")
    base = bank * BANK_BYTES + h * HEAD_BANK_BYTES
    if a == b:
        return base + a*4, a, 0
    lo, hi = sorted((a, b))
    ordinal = lo * (511 - lo) // 2 + (hi - lo - 1)
    assert 0 <= ordinal < MIRROR_PAIRS
    lane = int(a > b)
    cell = FIXED_POINTS + ordinal
    byte_offset = base + FIXED_POINTS*4 + ordinal*8 + lane*4
    assert byte_offset % 4 == 0
    assert bank*BANK_BYTES <= byte_offset < (bank+1)*BANK_BYTES
    return byte_offset, cell, lane


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(2**20), b""):
            h.update(chunk)
    return h.hexdigest()


def create(path: Path, manifest_path: Path) -> dict:
    if path.resolve() == manifest_path.resolve():
        raise ValueError("arena and metadata cannot share the same path")
    if path.exists() or manifest_path.exists():
        raise FileExistsError("Refusing to overwrite existing tensor or manifest")
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    # Truncate allocates a full LOGICAL address range. A sparse filesystem
    # may defer physical disk allocation; bytes still read as independent
    # zero-initialized elements across every legal coordinate.
    with path.open("xb") as f:
        os.ftruncate(f.fileno(), TOTAL_BYTES)
        f.flush()
        os.fsync(f.fileno())
    payload = {
        "schema": "nanrouter-hypertensor256-mirror-dual-f32le/v1",
        "storage_path": path.name,
        "bytes": TOTAL_BYTES,
        "bank_bytes": BANK_BYTES,
        "banks": {"active": 0, "candidate": 1},
        "tensor_shape_per_bank": [256, 256, 256],
        "data_type": "IEEE754-f32le",
        "weights_per_bank": N**3,
        "head_plane_bytes": HEAD_BANK_BYTES,
        "mirror_pairs_per_plane": MIRROR_PAIRS,
        "fixed_points_per_plane": FIXED_POINTS,
        "mirror_pair_lanes": 2,
        "directional_values_independent": True,
        "void_semantic_head": 255,
        "trainable_head_coordinates": [0, 254],
        "root_8MiB_untouched": True,
        "initialized_zeros_sha256": sha256_file(path),
        "state": "untrained-full-capacity-zero-initialized",
        "candidate_generation": 0,
        "native_update_required": True,
        "promotion_implemented": False,
    }
    try:
        with manifest_path.open("x", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return payload


def verify(path: Path, manifest_path: Path) -> dict:
    info = json.loads(manifest_path.read_text(encoding="utf-8"))
    if info["schema"] != "nanrouter-hypertensor256-mirror-dual-f32le/v1":
        raise ValueError("Incompatible tensor arena profile")
    if path.stat().st_size != TOTAL_BYTES or info["bytes"] != TOTAL_BYTES:
        raise ValueError("Tensor arena must contain both full 64 MiB banks")
    if info["tensor_shape_per_bank"] != [256, 256, 256]:
        raise ValueError("Unexpected shape")
    if info["void_semantic_head"] != 255 or info["root_8MiB_untouched"] is not True:
        raise ValueError("Invalid native root/head contract")
    digest = sha256_file(path)
    if digest != info.get("current_sha256", info["initialized_zeros_sha256"]):
        raise ValueError("Unadmitted arena mutation or corruption")
    return {"verified": True, "bytes": TOTAL_BYTES, "sha256": digest}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--verify", action="store_true")
    args = p.parse_args()
    result = verify(args.output, args.manifest) if args.verify else create(args.output, args.manifest)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
