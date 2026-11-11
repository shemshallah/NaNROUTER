#!/usr/bin/env python3
"""Lossless native NaN16 tensor checkpoint admission into an assembled guest fixture.

This is a transport/validation tool ONLY. It never computes gradients, predictions,
softmax or updates. All continuation training executes inside the NaN16 guest.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

N = 26 ** 3
WEIGHT_MARKER = "mth_inv_weights:\n.word 0\n.org 26500"
EXPECTED_SOURCE_SHA256 = "c43ab50b88da8b6fb3d1bb7a060a40a73ebeb95cea3494b1ee53c246e7881afa"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--fixture", required=True, type=Path)
    p.add_argument("--weights", required=True, type=Path)
    p.add_argument("--checkpoint", required=True, type=Path)
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--admission", required=True, type=Path)
    args = p.parse_args()

    checkpoint = json.loads(args.checkpoint.read_text())
    manifest = json.loads(args.manifest.read_text())
    raw = args.weights.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != 4 * N or digest != EXPECTED_SOURCE_SHA256:
        raise ValueError("Unapproved tensor snapshot bytes or digest")
    if (checkpoint["weights_sha256"] != digest
            or checkpoint["weight_tensor_shape"] != [26, 26, 26]
            or checkpoint["trained_epochs"] != 8
            or checkpoint["void_head"] != 255
            or checkpoint["physical_root_updated"] is not False):
        raise ValueError("Checkpoint provenance/shape/head contract mismatch")
    if (manifest["parameter_shape"] != [26, 26, 26]
            or manifest["control_mode"] != "trigram"
            or manifest["void_semantic_head_index"] != 255):
        raise ValueError("Intake manifest incompatible with native checkpoint")

    words = struct.unpack("<" + "I" * N, raw)
    if any((w & 0x7F800000) == 0x7F800000 for w in words):
        raise ValueError("Checkpoint has NaN or infinity")
    # Explicit 32-bit hexadecimal data words preserve float32 bit patterns.
    # They are assembled as NaN16 guest data, never evaluated by Python.
    lines = ["mth_inv_weights:"]
    for start in range(0, N, 16):
        lines.append(".word " + ",".join(f"0x{w:08X}" for w in words[start:start+16]))
    lines.append(".org 26500")
    fixture = args.fixture.read_text()
    if fixture.count(WEIGHT_MARKER) != 1:
        raise ValueError("Expected one zero-initialized tensor section")
    updated = fixture.replace(WEIGHT_MARKER, "\n".join(lines))
    if updated.count("mth_inv_weights:") != 1:
        raise ValueError("Unexpected tensor symbol count")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(updated)
    admission = {
        "schema": "nanrouter.native-inverse-trigram-checkpoint-admission/1",
        "weights_sha256": digest,
        "previous_epochs": checkpoint["trained_epochs"],
        "additional_epochs": manifest["epochs"],
        "tensor_shape": [26,26,26],
        "source_fixture_sha256": manifest["fixture_sha256"],
        "admitted_guest_fixture_sha256": hashlib.sha256(updated.encode()).hexdigest(),
        "head255_void": True,
        "frozen_43m_root_untouched": True,
        "training_backend": "NaN16 guest",
    }
    args.admission.parent.mkdir(parents=True, exist_ok=True)
    args.admission.write_text(json.dumps(admission, sort_keys=True, indent=2) + "\n")
    print(json.dumps(admission, sort_keys=True))


if __name__ == "__main__":
    main()
