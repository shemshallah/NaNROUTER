#!/usr/bin/env python3
"""Decode a checkpoint emitted by the native NaN16 inverse trainer.

This script DOES NOT train a model, compute softmax/gradients or modify weights.
It validates and byte-copies the exact 26x26 float32 parameter bit patterns
already learned and printed by the NaN16 guest over its serial output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    raw = args.log.read_bytes()
    log = raw.decode("utf-8")
    lines = log.splitlines()
    if lines.count("INV26_CHECKPOINT_BEGIN") != 1 or lines.count("INV26_CHECKPOINT_END") != 1:
        raise ValueError("Expected exactly one native checkpoint frame")
    begin = lines.index("INV26_CHECKPOINT_BEGIN")
    end = lines.index("INV26_CHECKPOINT_END")
    if end - begin != 677:
        raise ValueError(f"Expected 676 native f32 words, got {end-begin-1}")
    if "MTH INVERSE26 CORPUS TRAIN PASS" not in lines:
        raise ValueError("Guest did not pass all native training/bridge checks")

    words = lines[begin+1:end]
    output = bytearray()
    for idx, word in enumerate(words):
        if not re.fullmatch("[0-9A-F]{8}", word):
            raise ValueError(f"Invalid native hex word #{idx}")
        val = int(word[::-1], 16)  # guest printed least significant nibble first
        if (val & 0x7F800000) == 0x7F800000:
            raise ValueError(f"Nonfinite native trained parameter #{idx}")
        output.extend(struct.pack("<I", val))

    expected = {
        "INV26_TEST_BEFORE_HITS_PERMIL",
        "INV26_INVERSE_BEFORE_HITS_PERMIL",
        "INV26_DEV_AFTER_HITS_PERMIL",
        "INV26_TEST_AFTER_HITS_PERMIL",
        "INV26_INVERSE_AFTER_HITS_PERMIL",
        "INV26_FORWARD_AFTER_HITS_PERMIL",
    }
    metrics: dict[str, dict[str, int]] = {}
    for line in lines[:begin]:
        match = re.fullmatch(r"(INV26_[A-Z_]+) ([0-9]+) ([0-9]+)", line)
        if match:
            if match.group(1) in metrics:
                raise ValueError("Duplicate native metric: " + match.group(1))
            metrics[match.group(1)] = {
                "correct": int(match.group(2)),
                "mean_target_probability_per_mille_truncated": int(match.group(3)),
            }
    if not expected <= set(metrics):
        raise ValueError("Missing native metrics: " + str(sorted(expected - set(metrics))))
    split = json.loads(args.split_manifest.read_text())
    if split["derived_feature_bins"] != 26 or split["void_semantic_head_index"] != 255:
        raise ValueError("Mismatched data/void-head contract")
    if split["split"]["test"]["examples"] != 768:
        raise ValueError("Expected distinct 768-direction held-out test examples")
    for label in expected:
        value = metrics[label]
        denominator = 384 if "INVERSE" in label or "FORWARD" in label else 768
        if label == "INV26_DEV_AFTER_HITS_PERMIL":
            denominator = 768
        if value["correct"] > denominator or value["mean_target_probability_per_mille_truncated"] > 1000:
            raise ValueError("Invalid native metric " + label)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    binary_path = args.output_dir / "inverse26.weights.f32le.bin"
    binary_path.write_bytes(output)
    args.output_dir.joinpath("inverse26.weights.rawhex.txt").write_text(
        "\n".join(words) + "\n", encoding="ascii")
    digest = hashlib.sha256(output).hexdigest()
    record = {
        "schema": "nanrouter.inverse26.native-checkpoint/1",
        "source": "NaN16 guest serial output, exact losslessly decoded bits",
        "source_fixture_sha256": split["fixture_sha256"],
        "source_training_log_sha256": hashlib.sha256(raw).hexdigest(),
        "source_split_manifest_sha256": hashlib.sha256(args.split_manifest.read_bytes()).hexdigest(),
        "weight_matrix_shape": [26, 26],
        "f32": "IEEE-754 little endian, 676 words",
        "native_export": "eight hex digits least-significant-nibble-first per word",
        "weight_file": binary_path.name,
        "weights_sha256": digest,
        "trained_epochs": split["epochs"],
        "model_scope": "same 26-letter inverse/forward adapter, NOT 43M decoder",
        "physical_root_updated": False,
        "active_mathematical_heads": "0..254; existing control ACLs remain",
        "void_head": 255,
        "metrics": metrics,
        "split": {
            k: {"documents": len(v["documents"]), "examples": v["examples"]}
            for k, v in split["split"].items()
        },
    }
    args.output_dir.joinpath("inverse26.checkpoint.json").write_text(
        json.dumps(record, sort_keys=True, indent=2) + "\n")
    args.output_dir.joinpath("SHA256SUMS").write_text(
        f"{digest}  {binary_path.name}\n", encoding="ascii")
    print(json.dumps({
        "weights_sha256": digest,
        "weight_bytes": len(output),
        "epochs": split["epochs"],
        "metrics": metrics,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
