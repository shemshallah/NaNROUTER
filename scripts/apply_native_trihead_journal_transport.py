#!/usr/bin/env python3
"""CI-only transport: replay one native meta-accepted candidate tensor word.

Never computes a model gradient, optimizer step, proposal score or admission.
The guest MUST author the 6-word journal and PASS marker in the trusted CI
invocation. Outside that trusted execution context the text is untrusted and
MUST NOT be accepted as authorization for production root/candidate writes.

This v1 transport does NOT promote the active tensor or modify the 8 MiB root.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys

from init_full128_mirror_tensor_storage import BANK_BYTES, physical_offset, sha256_file, verify

ENTRY = re.compile(r"^MTH_META_ACCEPTED_HEX ([0-9A-F]{8}) ([0-9A-F]{8}) "
                   r"([0-9A-F]{8}) ([0-9A-F]{8}) ([0-9A-F]{8}) ([0-9A-F]{8})$")
PASS = "MTH TRIHEAD META FEEDBACK PASS"


def parse_native_log(raw: bytes) -> tuple[int, int, int, int, int, int]:
    lines = raw.decode("ascii", errors="strict").splitlines()
    entries = [ENTRY.fullmatch(line) for line in lines if line.startswith("MTH_META_ACCEPTED_HEX")]
    if len(entries) != 1 or entries[0] is None:
        raise ValueError("Expected exactly one strictly formatted guest-approved journal")
    if lines.count(PASS) != 1 or any("MTH TRIHEAD META FEEDBACK FAIL" in x for x in lines):
        raise ValueError("Guest did not pass verified native feedback fixture")
    numbers = tuple(int(s, 16) for s in entries[0].groups())
    proposer, h, a, b, offset, word = numbers
    if proposer > 254:
        raise ValueError("Head255 never has candidate permission")
    expected_offset, _, _ = physical_offset(0, h, a, b)
    if offset != expected_offset:
        raise ValueError("Journal address is not the exact native mirror coordinate")
    if (word & 0x7f800000) == 0x7f800000:
        raise ValueError("Refuse non-finite native candidate value")
    return numbers


def apply(arena: Path, metadata: Path, native_log: Path) -> dict:
    # CI caller is responsible for supplying a log from a PINNED native VM
    # invocation, not arbitrary user-provided data. Validate data regardless.
    trusted_bytes = native_log.read_bytes()
    proposer, h, a, b, offset, word = parse_native_log(trusted_bytes)
    verify(arena, metadata)  # attest prior committed bytes against metadata
    info = json.loads(metadata.read_text(encoding="utf-8"))
    if info.get("candidate_generation", 0) != 0:
        raise ValueError("v1 one-shot replay requires untouched candidate generation 0")
    candidate_offset = BANK_BYTES + offset
    if candidate_offset < BANK_BYTES or candidate_offset + 4 > 2*BANK_BYTES:
        raise ValueError("Attempt to escape candidate tensor bank")

    fd = os.open(arena, os.O_RDWR)
    try:
        if os.pread(fd, 4, candidate_offset) != b"\x00\x00\x00\x00":
            raise ValueError("Candidate slot must be zero for v1 initial replay")
        if os.pread(fd, 4, offset) != b"\x00\x00\x00\x00":
            raise ValueError("Unexpected nonzero active tensor before replay")
        # Pure byte transport: the *native guest*, not Python, determined
        # the exact accepted float32 word.
        count = os.pwrite(fd, struct.pack("<I", word), candidate_offset)
        if count != 4:
            raise OSError("Incomplete candidate byte transport")
        os.fsync(fd)
        if os.pread(fd, 4, offset) != b"\x00\x00\x00\x00":
            raise AssertionError("Active tensor changed during candidate replay")
    finally:
        os.close(fd)

    info["current_sha256"] = sha256_file(arena)
    info["candidate_generation"] = 1
    info["state"] = "candidate-has-native-meta-accepted-sparse-write-not-promoted"
    info["last_native_log_sha256"] = hashlib.sha256(trusted_bytes).hexdigest()
    info["native_proposer"] = proposer
    info["native_coordinate"] = [h, a, b]
    info["native_candidate_relative_offset"] = offset
    info["promotion_implemented"] = False

    tmp = metadata.with_name(metadata.name + ".pending")
    try:
        with tmp.open("x", encoding="utf-8") as f:
            json.dump(info, f, sort_keys=True, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, metadata)
    finally:
        tmp.unlink(missing_ok=True)
    verify(arena, metadata)
    return {
        "native_candidate_write": "transported",
        "head": proposer,
        "target": [h, a, b],
        "offset_in_candidate_bank": candidate_offset,
        "raw_native_f32_bits": f"0x{word:08X}",
        "candidate_generation": 1,
        "active_bank_written": False,
        "root_8MiB_written": False,
        "arena_sha256": info["current_sha256"],
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arena", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--native-log", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(apply(args.arena, args.manifest, args.native_log), sort_keys=True))


if __name__ == "__main__":
    main()
