#!/usr/bin/env python3
"""Build an *actual* NaN16 checkpoint-resume training image.

The inherited 26x26x26 tensor is restored bit-for-bit from the previous
GitHub Actions artifact. This script verifies parent SHA-256 and old
train/dev/test book IDs, selects NEW nonoverlapping Gutenberg books,
transcribes corpus triples and the raw tensor bytes into a canonical NaN16
assembler image, and records its provenance. It never performs model
inference, softmax, SGD or any weight updates: those occur only in NaN16.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

import build_native_inverse_trigram26_corpus_fixture as base

SPLIT_VERSION = "nanrouter-inverse-trigram26-resume-fresh-docs-v1"
BASELINE_SHA = "c43ab50b88da8b6fb3d1bb7a060a40a73ebeb95cea3494b1ee53c246e7881afa"
DOC_COUNTS = {"train": 20, "dev": 6, "test": 6}
TRIPLES_PER_DOC = {"train": 96, "dev": 64, "test": 64}
EPOCHS = 4


def select_fresh_books(root: Path, previous: dict) -> dict:
    prior = previous["split"]
    excluded_ids = {
        entry["gutenberg_id"]
        for data in prior.values()
        for entry in data["documents"]
    }
    excluded_digests = {
        entry["source_sha256"]
        for data in prior.values()
        for entry in data["documents"]
    }
    candidates = []
    observed = set()
    for file in root.rglob("*.txt"):
        match = re.fullmatch(r"(\d+)--.*\.txt", file.name)
        if not match or int(match.group(1)) in excluded_ids:
            continue
        payload = file.read_bytes()
        if len(payload) < 5000 or len(payload) > 1_500_000:
            continue
        try:
            content = payload.decode("utf-8")
        except UnicodeError:
            continue
        if len(base.WORD.findall(content[:40_000])) < 200:
            continue
        digest = hashlib.sha256(payload).hexdigest()
        if digest in excluded_digests or digest in observed:
            continue
        observed.add(digest)
        book = int(match.group(1))
        key = hashlib.sha256(f"{SPLIT_VERSION}/{book}/{digest}".encode()).digest()
        candidates.append((key, file, payload, digest, book))
    candidates.sort(key=lambda x: x[0])
    total = sum(DOC_COUNTS.values())
    if len(candidates) < total:
        raise ValueError(f"Insufficient untouched books {len(candidates)}/{total}")
    selected, offset = {}, 0
    for split, num in DOC_COUNTS.items():
        selected[split] = candidates[offset:offset+num]
        offset += num
    if len({v[4] for group in selected.values() for v in group}) != total:
        raise AssertionError("Duplicate Gutenberg book ID across splits")
    return selected


def load_checkpoint(weights_path: Path, meta_path: Path):
    raw = weights_path.read_bytes()
    meta = json.loads(meta_path.read_text())
    digest = hashlib.sha256(raw).hexdigest()
    if (len(raw) != 17576*4 or digest != BASELINE_SHA or
        meta.get("weights_sha256") != digest or
        meta.get("weight_tensor_shape") != [26,26,26] or
        meta.get("void_head") != 255 or
        meta.get("trained_epochs") != 8 or
        meta.get("physical_root_updated") is not False):
        raise ValueError("Unexpected or corrupted parent native tensor checkpoint")
    words = list(struct.unpack("<17576I", raw))
    if any((word & 0x7F800000) == 0x7F800000 for word in words):
        raise ValueError("Parent tensor contains NaN/Infinity")
    raw_sum = sum(words) & 0xffffffff
    weighted_sum = sum((i+1)*v for i,v in enumerate(words)) & 0xffffffff
    return words, raw_sum, weighted_sum, digest


def generate(groups: dict, words: list, checksum: int, weighted: int) -> str:
    original = base.emit_fixture(groups)
    original = original.replace(
        '.include "../nan16/mth_memory_condition16_f32.nas"',
        '.include "../nan16/mth_memory_condition16_f32.nas"\n'
        '.include "../nan16/mth_inverse_trigram26_resume_verify.nas"'
    )
    preamble = f"""  ; Mandatory native tensor preflight BEFORE any evaluation or SGD.
  MOVI r1,@mth_inv_weights
  MOVI r2,0x{checksum & 0xffff:04X}
  MOVHI r2,0x{checksum >> 16:04X}
  MOVI r3,0x{weighted & 0xffff:04X}
  MOVHI r3,0x{weighted >> 16:04X}
  MOVI r4,@mth_inv_void255
  CALL @mth_inverse_trigram26_resume_verify
  CMP r1,r13
  JMP[NE] @mth_inv_fail
  MOVI r1,@mth_inv_label_resume_ok
  CALL @mth_inv_puts

  ; First score fresh development books read-only for dev-only admission.
  MOVI r1,@mth_inv_weights
  MOVI r2,@mth_inv_dev
  MOVI r3,{len(groups["dev"])}
  MOVI r4,0
  MOVI r5,@mth_inv_workspace
  MOVI r6,@mth_inv_stats
  CALL @mth_inverse_trigram26_batch_f32
  CMP r1,r13
  JMP[NE] @mth_inv_fail
  MOVI r1,@mth_inv_label_resume_dev
  CALL @mth_inv_puts
  MOVI r1,@mth_inv_stats
  CALL @mth_inv_print_metrics
"""
    header = "mth_inv_main:\n  MOVI r0,0\n  MOVI r13,1\n"
    if original.count(header) != 1:
        raise ValueError("Unexpected main prologue in prior validated fixture")
    original = original.replace(header, header + preamble)
    old_block = "mth_inv_weights:\n.word 0\n.org 26500"
    if original.count(old_block) != 1:
        raise ValueError("Cannot find trained tensor preload location")
    data = "\n".join(f".word 0x{v:08X}" for v in words)
    original = original.replace(old_block, f"mth_inv_weights:\n{data}\n.org 26500")
    original = original.replace(
        'mth_inv_label_before:\n',
        'mth_inv_label_resume_ok:\n.str "INV3_RESUME_PARENT_VERIFIED\\n"\n'
        'mth_inv_label_resume_dev:\n.str "INV3_RESUME_DEV_BEFORE_HITS_PERMIL "\n'
        'mth_inv_label_before:\n'
    )
    train_seq = '  MOVI r12,8\n  CMP r14,r12\n  JMP[LT] @mth_inv_epoch'
    if original.count(train_seq) != 1:
        raise ValueError("Cannot find epoch bound")
    original = original.replace(train_seq, train_seq.replace("r12,8",f"r12,{EPOCHS}"))
    return original


def main():
    p = argparse.ArgumentParser()
    for arg in ("corpus-root", "parent-split-manifest",
                "parent-checkpoint", "parent-checkpoint-meta", "output", "manifest"):
        p.add_argument("--"+arg, type=Path, required=True)
    args = p.parse_args()
    previous = json.loads(args.parent_split_manifest.read_text())
    if previous.get("void_semantic_head_index") != 255 or previous.get("parameter_shape") != [26,26,26]:
        raise ValueError("Incompatible parent split/void contract")
    words, raw_sum, weighted_sum, parent_sha = load_checkpoint(
        args.parent_checkpoint, args.parent_checkpoint_meta)
    selected = select_fresh_books(args.corpus_root, previous)
    groups, records = {}, {}
    for split, books in selected.items():
        groups[split] = []
        records[split] = []
        for _, path, payload, digest, book in books:
            seed = int.from_bytes(hashlib.sha256(
                f"{SPLIT_VERSION}/{book}/{digest}".encode()).digest()[:8],"big")
            triples = base.extract_triples(payload.decode("utf-8"), TRIPLES_PER_DOC[split], seed)
            if len(triples) != TRIPLES_PER_DOC[split]:
                raise ValueError("Insufficient new natural-frequency triples")
            for a,b,c in triples:
                groups[split].extend([(a,b,c,0),(a,b,c,1)])
            records[split].append({
                "file": path.name, "gutenberg_id": book,
                "source_sha256": digest, "triples":len(triples)
            })
    groups["test_inverse"] = [x for x in groups["test"] if x[3]==1]
    groups["test_forward"] = [x for x in groups["test"] if x[3]==0]
    program = generate(groups, words, raw_sum, weighted_sum)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(program,encoding="utf-8")
    report = {
        "schema":"nanrouter.inverse26.resume.fresh-v1",
        "corpus":"NaNROUTER/corpora/sentences public Gutenberg release, SHA256 verified",
        "parent_training_artifact_run":42950787457,
        "parent_tensor_sha256":parent_sha,
        "parent_split_manifest_sha256":hashlib.sha256(args.parent_split_manifest.read_bytes()).hexdigest(),
        "import_uint32_sum": raw_sum,
        "import_uint32_weighted_sum": weighted_sum,
        "import_contract":"SHA256 host + complete two-sum native verifier + void255 check",
        "semantic_head255":"zero/void",
        "root_writer_permissions_changed":False,
        "language_48M_checkpoint_changed":False,
        "parameter_shape":[26,26,26],
        "new_epochs":EPOCHS,
        "cumulative_epochs_from_parent":8+EPOCHS,
        "learning_rate":0.1,
        "split":{
            name:{"documents": docs,"examples":len(groups[name])}
            for name,docs in records.items()
        },
        "excluded_prior_gutenberg_ids":sorted({
            d["gutenberg_id"]
            for row in previous["split"].values() for d in row["documents"]
        }),
        "program_sha256": hashlib.sha256(program.encode()).hexdigest(),
    }
    assert not set(report["excluded_prior_gutenberg_ids"]) & {
        d["gutenberg_id"] for row in records.values() for d in row
    }
    args.manifest.parent.mkdir(parents=True,exist_ok=True)
    args.manifest.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
        "parent_sha256":parent_sha, "new_docs":{k:len(x) for k,x in records.items()},
        "examples":{k:len(groups[k]) for k in records},
        "native_import_checksums": [raw_sum,weighted_sum],
        "program_sha256":report["program_sha256"],
    },sort_keys=True))


if __name__=="__main__":
    main()
