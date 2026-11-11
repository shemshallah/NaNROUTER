#!/usr/bin/env python3
"""Corpus intake ONLY: deterministic document split and NaN16 fixture assembly.

Training, logits, softmax, SGD, evaluation scores and inverse arithmetic are
all executed by the existing NaN16 guest. This file does not implement an ML
model, optimizer or hidden host-side weight update.

The published corpora are release assets, not checked-in .txt files. The
runner extracts a verified sentences batch and passes the extraction path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from pathlib import Path

SPLIT_VERSION = "nanrouter-16bin-inverse-docsplit-v1"
WORD = re.compile(r"[A-Za-z]{3,}")
DOC_COUNTS = {"train": 12, "dev": 4, "test": 4}
PAIRS_PER_DOC = {"train": 128, "dev": 64, "test": 64}
ORG_TRAIN = 16000
ORG_DEV = 32000
ORG_TEST = 35000


def extract_pairs(content: str, limit: int, seed: int) -> list[tuple[int, int]]:
    """Uniform reservoir sample of naturally occurring adjacent letter pairs."""
    rng = random.Random(seed)
    sample: list[tuple[int, tuple[int, int]]] = []
    n = 0
    for word in WORD.finditer(content):
        chars = word.group().lower()
        for a, b in zip(chars, chars[1:]):
            # 16 feature bins, preserving original corpus occurrence counts.
            item = (n, ((ord(a) - 97) % 16, (ord(b) - 97) % 16))
            n += 1
            if len(sample) < limit:
                sample.append(item)
            else:
                slot = rng.randrange(n)
                if slot < limit:
                    sample[slot] = item
    return [pair for _, pair in sorted(sample)]


def split_documents(root: Path) -> dict[str, list[tuple[Path, bytes, str]]]:
    docs: list[tuple[bytes, Path, bytes, str]] = []
    seen = set()
    for file in root.rglob("*.txt"):
        if not re.match(r"^\d+--", file.name):
            continue
        b = file.read_bytes()
        if len(b) < 5000 or len(b) > 1_500_000:
            continue
        try:
            s = b.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if len(WORD.findall(s[:40_000])) < 200:
            continue
        digest = hashlib.sha256(b).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        key = hashlib.sha256((SPLIT_VERSION + ":" + file.name).encode()).digest()
        docs.append((key, file, b, digest))
    docs.sort(key=lambda x: x[0])
    needed = sum(DOC_COUNTS.values())
    if len(docs) < needed:
        raise ValueError(f"Not enough distinct UTF-8 Gutenberg books: {len(docs)} < {needed}")
    chosen = docs[:needed]
    start = 0
    result = {}
    for split, count in DOC_COUNTS.items():
        chunk = chosen[start:start+count]
        result[split] = [(path, data, digest) for _, path, data, digest in chunk]
        start += count
    return result


def integer_words(records: list[tuple[int, int, int]]) -> list[str]:
    return [f".word {left},{right},{direction}" for left, right, direction in records]


def emit_fixture(groups: dict[str, list[tuple[int,int,int]]]) -> str:
    train, dev, test = (len(groups[k]) for k in ("train","dev","test"))
    if not (1 <= train <= 4096 and 1 <= dev <= 4096 and 1 <= test <= 4096):
        raise ValueError("Invalid NaN16 batch length")
    for name, origin, count in [
        ("train", ORG_TRAIN, train), ("dev", ORG_DEV, dev), ("test", ORG_TEST, test)
    ]:
        next_start = {"train":ORG_DEV,"dev":ORG_TEST,"test":65535}[name]
        if origin + 3 * count >= next_start:
            raise ValueError(f"Fixture {name} exceeds allocated guest workspace")
    return f"""; Generated from verified public-domain corpus; DO NOT edit by hand.
; Document splits are disjoint, ids/hashes saved in manifest.json.
; x/y are 16 bins of naturally sampled consecutive word-internal letters.
; Both forward (0) and exact inverse (1) share the SAME trained W.
; All learning operations run inside native NaN16 guest!
.org 0
JMP @mth_inv_main
.include "../nan16/mth_inverse_dual_batch16_f32.nas"

mth_inv_main:
  MOVI r0,0
  MOVI r13,1
  ; Evaluate untouched matrix on independent test documents.
  MOVI r1,@mth_inv_weights
  MOVI r2,@mth_inv_test
  MOVI r3,{test}
  MOVI r4,0
  MOVI r5,@mth_inv_workspace
  MOVI r6,@mth_inv_stats
  CALL @mth_inverse_dual_batch16_f32
  CMP r1,r13
  JMP[NE] @mth_inv_fail
  LD r7,r0,@mth_inv_stats+1
  ST r7,r0,@mth_inv_test_before
  MOVI r1,@mth_inv_label_before
  CALL @mth_inv_puts
  MOVI r1,@mth_inv_stats
  CALL @mth_inv_print_metrics

  ; Train with exactly the same relation weights in both directions.
  ; Two passes only; dev/test never used for updates.
  MOVI r14,0
mth_inv_epoch:
  ST r14,r0,@mth_inv_epoch_num
  MOVI r1,@mth_inv_weights
  MOVI r2,@mth_inv_train
  MOVI r3,{train}
  MOVI r4,0xCCCD
  MOVHI r4,0x3DCC            ; 0.1f SGD
  MOVI r5,@mth_inv_workspace
  MOVI r6,@mth_inv_stats
  CALL @mth_inverse_dual_batch16_f32
  CMP r1,r13
  JMP[NE] @mth_inv_fail
  LD r14,r0,@mth_inv_epoch_num
  ADDI r14,r14,1
  MOVI r12,2
  CMP r14,r12
  JMP[LT] @mth_inv_epoch

  ; Development scores, untrained/dev document isolation.
  MOVI r1,@mth_inv_weights
  MOVI r2,@mth_inv_dev
  MOVI r3,{dev}
  MOVI r4,0
  MOVI r5,@mth_inv_workspace
  MOVI r6,@mth_inv_stats
  CALL @mth_inverse_dual_batch16_f32
  CMP r1,r13
  JMP[NE] @mth_inv_fail
  MOVI r1,@mth_inv_label_dev
  CALL @mth_inv_puts
  MOVI r1,@mth_inv_stats
  CALL @mth_inv_print_metrics

  ; Final independent document-level test evaluation.
  MOVI r1,@mth_inv_weights
  MOVI r2,@mth_inv_test
  MOVI r3,{test}
  MOVI r4,0
  MOVI r5,@mth_inv_workspace
  MOVI r6,@mth_inv_stats
  CALL @mth_inverse_dual_batch16_f32
  CMP r1,r13
  JMP[NE] @mth_inv_fail
  MOVI r1,@mth_inv_label_after
  CALL @mth_inv_puts
  MOVI r1,@mth_inv_stats
  CALL @mth_inv_print_metrics

  ; Compare held-out native summed teacher probabilities. This measures
  ; whether the inverse adapter learned more signal than zero-init, not
  ; whether 43M language perplexity improved.
  LD r10,r0,@mth_inv_test_before
  LD r11,r0,@mth_inv_stats+1
  FCMP r11,r10
  JMP[LE] @mth_inv_not_improved
  MOVI r1,@mth_inv_label_improved
  CALL @mth_inv_puts
  JMP @mth_inv_void_check
mth_inv_not_improved:
  MOVI r1,@mth_inv_label_unimproved
  CALL @mth_inv_puts
mth_inv_void_check:
  ; Semantic head index 255 remains an untouched exact zero/void register,
  ; separate from 16x16 feature relationship weights.
  LD r10,r0,@mth_inv_void255
  CMP r10,r0
  JMP[NE] @mth_inv_fail
  MOVI r1,@mth_inv_label_pass
  CALL @mth_inv_puts
  HALT

mth_inv_fail:
  MOVI r1,@mth_inv_label_fail
  CALL @mth_inv_puts
  HALT

; Print: hit count and average teacher probability in parts-per-thousand.
; All arithmetic (including scoring) performed inside guest instructions.
mth_inv_print_metrics:
  ST r15,r0,@mth_inv_print_link
  ST r1,r0,@mth_inv_print_stats_ptr
  LD r1,r1,0
  CALL @mth_inv_print_uint
  MOVI r1,32
  PUTC r1
  MOVI r12,@mth_inv_print_stats_ptr
  LD r12,r12,0
  LD r7,r12,1                 ; sum p(teacher)
  LD r8,r12,2                 ; number of examples
  CVTIF r8,r8
  FDIV r7,r7,r8
  MOVI r8,0
  MOVHI r8,0x447A             ; 1000.0f
  FMUL r7,r7,r8
  CVTFI r1,r7
  CALL @mth_inv_print_uint
  MOVI r1,10
  PUTC r1
  LD r15,r0,@mth_inv_print_link
  RET

mth_inv_print_uint:
  MOVI r9,0
mth_inv_digit:
  MOVI r10,10
  MODU r11,r1,r10
  ADDI r11,r11,48
  MOVI r12,@mth_inv_digits
  ADD r12,r12,r9
  ST r11,r12,0
  ADDI r9,r9,1
  DIV r1,r1,r10
  CMP r1,r0
  JMP[NE] @mth_inv_digit
mth_inv_emit:
  ADDI r9,r9,-1
  MOVI r12,@mth_inv_digits
  ADD r12,r12,r9
  LD r11,r12,0
  PUTC r11
  CMP r9,r0
  JMP[GT] @mth_inv_emit
  RET

mth_inv_puts:
  MOVI r4,255
mth_inv_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_inv_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_inv_puts_byte
  ADD r1,r1,r13
  JMP @mth_inv_puts_word

mth_inv_label_before:
.str "INV_TEST_BEFORE_HITS_PERMIL "
mth_inv_label_dev:
.str "INV_DEV_AFTER_HITS_PERMIL "
mth_inv_label_after:
.str "INV_TEST_AFTER_HITS_PERMIL "
mth_inv_label_improved:
.str "INV_TEST_PROBABILITY_IMPROVED\\n"
mth_inv_label_unimproved:
.str "INV_TEST_PROBABILITY_NOT_IMPROVED\\n"
mth_inv_label_pass:
.str "MTH INVERSE CORPUS TRAIN PASS\\n"
mth_inv_label_fail:
.str "MTH INVERSE CORPUS TRAIN FAIL\\n"

.org 8192
mth_inv_weights:
.word 0
.org 8600
mth_inv_workspace:
.word 0
.org 8950
mth_inv_stats:
.word 0,0,0
mth_inv_test_before:
.word 0
mth_inv_epoch_num:
.word 0
mth_inv_print_link:
.word 0
mth_inv_print_stats_ptr:
.word 0
mth_inv_digits:
.word 0,0,0,0,0,0,0,0,0,0
mth_inv_void255:
.word 0

.org {ORG_TRAIN}
mth_inv_train:
{chr(10).join(integer_words(groups["train"]))}

.org {ORG_DEV}
mth_inv_dev:
{chr(10).join(integer_words(groups["dev"]))}

.org {ORG_TEST}
mth_inv_test:
{chr(10).join(integer_words(groups["test"]))}
"""


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--corpus-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    args = p.parse_args()
    documents = split_documents(args.corpus_root)
    groups = {}
    manifest = {
        "schema": SPLIT_VERSION,
        "source": "shemshallah/NaNROUTER/corpora/sentences release asset",
        "license": "Project Gutenberg public domain USA; Gutenberg license",
        "active_semantic_head_indices": [0, 254],
        "void_semantic_head_index": 255,
        "derived_feature_bins": 16,
        "objective": "shared forward-and-inverse 16-bin letter adjacency CE",
        "updates": "native NaN16 SGD only; no host model arithmetic",
        "epochs": 2,
        "split": {},
    }
    for label, group in documents.items():
        examples = []
        metadata = []
        for path, contents, sha in group:
            seed = int.from_bytes(hashlib.sha256((SPLIT_VERSION + sha).encode()).digest()[:8], "big")
            pairs = extract_pairs(contents.decode("utf-8"), PAIRS_PER_DOC[label], seed)
            if len(pairs) != PAIRS_PER_DOC[label]:
                raise ValueError("Too few letter pairs from a selected book")
            for a, b in pairs:
                examples.append((a, b, 0))
                examples.append((a, b, 1))
            metadata.append({
                "file": path.name, "source_sha256": sha, "pairs": len(pairs),
                "gutenberg_id": int(path.name.split("--")[0]),
            })
        groups[label] = examples
        manifest["split"][label] = {
            "documents": metadata, "examples": len(examples)
        }
    for a in groups:
        for b in groups:
            if a >= b:
                continue
            aa = {x["source_sha256"] for x in manifest["split"][a]["documents"]}
            bb = {x["source_sha256"] for x in manifest["split"][b]["documents"]}
            if aa & bb:
                raise AssertionError("Document leakage across partitions")
    text = emit_fixture(groups)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    manifest["fixture_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: {
        "books": len(v["documents"]), "examples": v["examples"]
    } for k, v in manifest["split"].items()}, sort_keys=True))
    print("fixture sha256", manifest["fixture_sha256"])


if __name__ == "__main__":
    main()
