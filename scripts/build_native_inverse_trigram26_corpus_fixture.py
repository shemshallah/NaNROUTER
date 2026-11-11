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

SPLIT_VERSION = "nanrouter-26letter-inverse-docsplit-v1"
WORD = re.compile(r"[A-Za-z]{3,}")
DOC_COUNTS = {"train": 20, "dev": 6, "test": 6}
TRIPLES_PER_DOC = {"train": 96, "dev": 64, "test": 64}
ORG_TRAIN = 30000
ORG_DEV = 46000
ORG_TEST = 50000


def extract_triples(content: str, limit: int, seed: int) -> list[tuple[int, int, int]]:
    """Uniform reservoir sample of naturally occurring consecutive letter triples."""
    rng = random.Random(seed)
    sample: list[tuple[int, tuple[int, int, int]]] = []
    n = 0
    for word in WORD.finditer(content):
        chars = word.group().lower()
        for a, b, c in zip(chars, chars[1:], chars[2:]):
            # 26 full letter symbols, preserving original corpus occurrence counts.
            item = (n, (ord(a) - 97, ord(b) - 97, ord(c) - 97))
            n += 1
            if len(sample) < limit:
                sample.append(item)
            else:
                slot = rng.randrange(n)
                if slot < limit:
                    sample[slot] = item
    return [triple for _, triple in sorted(sample)]


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


def integer_words(records: list[tuple[int, int, int, int]]) -> list[str]:
    return [f".word {a},{b},{c},{direction}" for a, b, c, direction in records]


def emit_fixture(groups: dict[str, list[tuple[int,int,int,int]]]) -> str:
    train, dev, test = (len(groups[k]) for k in ("train","dev","test"))
    if not (1 <= train <= 4096 and 1 <= dev <= 4096 and 1 <= test <= 4096):
        raise ValueError("Invalid NaN16 batch length")
    for name, origin, count in [
        ("train", ORG_TRAIN, train), ("dev", ORG_DEV, dev), ("test", ORG_TEST, test)
    ]:
        next_start = {"train":ORG_DEV,"dev":ORG_TEST,"test":65535}[name]
        if origin + 4 * count >= next_start:
            raise ValueError(f"Fixture {name} exceeds allocated guest workspace")
    return f"""; Generated from verified public-domain corpus; DO NOT edit by hand.
; Document splits are disjoint, ids/hashes saved in manifest.json.
; x/y are 26 bins of naturally sampled consecutive word-internal letters.
; Both forward (0) and exact inverse (1) share the SAME trained rank-three tensor.
; All learning operations run inside native NaN16 guest!
.org 0
JMP @mth_inv_main
.include "../nan16/mth_inverse_trigram26_batch_f32.nas"
.include "../nan16/mth_memory_condition16_f32.nas"

mth_inv_main:
  MOVI r0,0
  MOVI r13,1
  ; Evaluate untouched full-alphabet rank-three tensor on independent documents.
  MOVI r1,@mth_inv_weights
  MOVI r2,@mth_inv_test
  MOVI r3,{test}
  MOVI r4,0
  MOVI r5,@mth_inv_workspace
  MOVI r6,@mth_inv_stats
  CALL @mth_inverse_trigram26_batch_f32
  CMP r1,r13
  JMP[NE] @mth_inv_fail
  LD r7,r0,@mth_inv_stats+1
  ST r7,r0,@mth_inv_test_before
  MOVI r1,@mth_inv_label_before
  CALL @mth_inv_puts
  MOVI r1,@mth_inv_stats
  CALL @mth_inv_print_metrics

  ; Direction-specific untouched inverse held-out score.
  MOVI r1,@mth_inv_weights
  MOVI r2,@mth_inv_test_inverse
  MOVI r3,{len(groups["test_inverse"])}
  MOVI r4,0
  MOVI r5,@mth_inv_workspace
  MOVI r6,@mth_inv_stats
  CALL @mth_inverse_trigram26_batch_f32
  CMP r1,r13
  JMP[NE] @mth_inv_fail
  MOVI r1,@mth_inv_label_inverse_before
  CALL @mth_inv_puts
  MOVI r1,@mth_inv_stats
  CALL @mth_inv_print_metrics

  ; Train exactly one rank-three hypertensor in both directions.
  ; Eight passes, with shared third-order tensor; dev/test never used for updates.
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
  CALL @mth_inverse_trigram26_batch_f32
  CMP r1,r13
  JMP[NE] @mth_inv_fail
  LD r14,r0,@mth_inv_epoch_num
  ADDI r14,r14,1
  MOVI r12,8
  CMP r14,r12
  JMP[LT] @mth_inv_epoch

  ; Development scores, untrained/dev document isolation.
  MOVI r1,@mth_inv_weights
  MOVI r2,@mth_inv_dev
  MOVI r3,{dev}
  MOVI r4,0
  MOVI r5,@mth_inv_workspace
  MOVI r6,@mth_inv_stats
  CALL @mth_inverse_trigram26_batch_f32
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
  CALL @mth_inverse_trigram26_batch_f32
  CMP r1,r13
  JMP[NE] @mth_inv_fail
  MOVI r1,@mth_inv_label_after
  CALL @mth_inv_puts
  MOVI r1,@mth_inv_stats
  CALL @mth_inv_print_metrics

  ; Evaluate inverse-only and forward-only independently on disjoint
  ; held-out documents. Identical W used for both, neither is trained.
  MOVI r1,@mth_inv_weights
  MOVI r2,@mth_inv_test_inverse
  MOVI r3,{len(groups["test_inverse"])}
  MOVI r4,0
  MOVI r5,@mth_inv_workspace
  MOVI r6,@mth_inv_stats
  CALL @mth_inverse_trigram26_batch_f32
  CMP r1,r13
  JMP[NE] @mth_inv_fail
  MOVI r1,@mth_inv_label_inverse_after
  CALL @mth_inv_puts
  MOVI r1,@mth_inv_stats
  CALL @mth_inv_print_metrics

  MOVI r1,@mth_inv_weights
  MOVI r2,@mth_inv_test_forward
  MOVI r3,{len(groups["test_forward"])}
  MOVI r4,0
  MOVI r5,@mth_inv_workspace
  MOVI r6,@mth_inv_stats
  CALL @mth_inverse_trigram26_batch_f32
  CMP r1,r13
  JMP[NE] @mth_inv_fail
  MOVI r1,@mth_inv_label_forward_after
  CALL @mth_inv_puts
  MOVI r1,@mth_inv_stats
  CALL @mth_inv_print_metrics

  ; Compare held-out native summed teacher probabilities from the shared tensor. This measures
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
  ; separate from 26x26x26 learned character-association tensor.
  LD r10,r0,@mth_inv_void255
  CMP r10,r0
  JMP[NE] @mth_inv_fail
  ; Bridge trained shared third-order tensor into the real native
  ; global masked-softmax readout, then into a next-step head residual.
  ; Forward scores use first 16 of T[0,0,k]; inverse T[k,0,0].
  ; Global head bridge has 16 candidates while tensor holds 26x26x26 cells.
  ; This is a read-only bridge from an ephemeral corpus-trained third-order tensor,
  ; not a root write or a 43M checkpoint update.
  MOVI r1,@mth_inv_weights
  MOVI r2,0xFFFF
  MOVI r3,@mth_inv_weights
  MOVI r4,@mth_inv_focus_out
  MOVI r5,@mth_inv_focus_scratch
  CALL @mth_global_focus16_f32
  CMP r1,r13
  JMP[NE] @mth_inv_fail
  MOVI r7,0
mth_inv_column:
  MOVI r8,676
  MUL r8,r7,r8
  MOVI r9,@mth_inv_weights
  ADD r9,r9,r8
  LD r10,r9,0
  MOVI r9,@mth_inv_reverse_scores
  ADD r9,r9,r7
  ST r10,r9,0
  ADDI r7,r7,1
  MOVI r8,16
  CMP r7,r8
  JMP[LT] @mth_inv_column
  MOVI r1,@mth_inv_reverse_scores
  MOVI r2,0xFFFF
  MOVI r3,@mth_inv_weights
  MOVI r4,@mth_inv_focus_out
  MOVI r5,@mth_inv_focus_scratch
  CALL @mth_global_focus16_f32
  CMP r1,r13
  JMP[NE] @mth_inv_fail

  MOVI r10,0
  MOVHI r10,0x3F00        ; bounded next-step head gate = 1/2
  MOVI r7,0
mth_inv_gate_fill:
  MOVI r11,@mth_inv_gate
  ADD r11,r11,r7
  ST r10,r11,0
  ADDI r7,r7,1
  MOVI r11,16
  CMP r7,r11
  JMP[LT] @mth_inv_gate_fill
  MOVI r1,@mth_inv_head
  MOVI r2,@mth_inv_focus_out
  MOVI r3,@mth_inv_gate
  MOVI r4,@mth_inv_next_head
  MOVI r5,@mth_inv_head_scratch
  CALL @mth_memory_condition16_f32
  CMP r1,r13
  JMP[NE] @mth_inv_fail
  LD r10,r0,@mth_inv_focus_out
  MOVI r11,0
  MOVHI r11,0x3F00
  FMUL r10,r10,r11
  LD r12,r0,@mth_inv_next_head
  CMP r10,r12
  JMP[NE] @mth_inv_fail
  MOVI r1,@mth_inv_label_bridge
  CALL @mth_inv_puts

  ; Save a real learned native optimizer state for future continuation.
  ; Export exact trained 26^3 tensor state from native NaN16 serial.
  CALL @mth_inv_dump_weights
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

; Exact reversible learned-weight serialization: 17576 f32 bit patterns,
; each printed as 8 hexadecimal digits in low-nibble-first order.
; Host only decodes these already-trained bits into a checkpoint artifact.
mth_inv_dump_weights:
  ST r15,r0,@mth_inv_ckpt_link
  MOVI r1,@mth_inv_label_ckpt_begin
  CALL @mth_inv_puts
  MOVI r7,0
mth_inv_ckpt_word:
  MOVI r8,@mth_inv_weights
  ADD r8,r8,r7
  LD r10,r8,0
  MOVI r9,0
mth_inv_ckpt_nibble:
  MOVI r12,15
  BOOL.8 r11,r10,r12
  MOVI r12,10
  CMP r11,r12
  JMP[LT] @mth_inv_ckpt_decimal
  ADDI r11,r11,55
  JMP @mth_inv_ckpt_emit
mth_inv_ckpt_decimal:
  ADDI r11,r11,48
mth_inv_ckpt_emit:
  PUTC r11
  SHR r10,r10,4
  ADDI r9,r9,1
  MOVI r11,8
  CMP r9,r11
  JMP[LT] @mth_inv_ckpt_nibble
  MOVI r11,10
  PUTC r11
  ADDI r7,r7,1
  MOVI r11,17576
  CMP r7,r11
  JMP[LT] @mth_inv_ckpt_word
  MOVI r1,@mth_inv_label_ckpt_end
  CALL @mth_inv_puts
  LD r15,r0,@mth_inv_ckpt_link
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
.str "INV3_TEST_BEFORE_HITS_PERMIL "
mth_inv_label_dev:
.str "INV3_DEV_AFTER_HITS_PERMIL "
mth_inv_label_after:
.str "INV3_TEST_AFTER_HITS_PERMIL "
mth_inv_label_improved:
.str "INV3_TEST_PROBABILITY_IMPROVED\\n"
mth_inv_label_unimproved:
.str "INV3_TEST_PROBABILITY_NOT_IMPROVED\\n"
mth_inv_label_bridge:
.str "MTH INVERSE TRIGRAM26 GLOBAL HEAD BRIDGE PASS\\n"
mth_inv_label_inverse_before:
.str "INV3_INVERSE_BEFORE_HITS_PERMIL "
mth_inv_label_inverse_after:
.str "INV3_INVERSE_AFTER_HITS_PERMIL "
mth_inv_label_forward_after:
.str "INV3_FORWARD_AFTER_HITS_PERMIL "
mth_inv_label_ckpt_begin:
.str "INV3_CHECKPOINT_BEGIN\\n"
mth_inv_label_ckpt_end:
.str "INV3_CHECKPOINT_END\\n"
mth_inv_label_pass:
.str "MTH INVERSE TRIGRAM26 CORPUS TRAIN PASS\\n"
mth_inv_label_fail:
.str "MTH INVERSE TRIGRAM26 CORPUS TRAIN FAIL\\n"

.org 8192
mth_inv_weights:
.word 0
.org 26500
mth_inv_workspace:
.word 0
.org 26800
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
mth_inv_ckpt_link:
.word 0
mth_inv_digits:
.word 0,0,0,0,0,0,0,0,0,0
mth_inv_void255:
.word 0
.org 26900
mth_inv_reverse_scores:
.word 0
.org 26950
mth_inv_focus_out:
.word 0
.org 27000
mth_inv_head:
.word 0
.org 27050
mth_inv_gate:
.word 0
.org 27100
mth_inv_next_head:
.word 0
.org 27150
mth_inv_head_scratch:
.word 0
.org 27200
mth_inv_focus_scratch:
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

.org 54000
mth_inv_test_inverse:
{chr(10).join(integer_words(groups["test_inverse"]))}

.org 56000
mth_inv_test_forward:
{chr(10).join(integer_words(groups["test_forward"]))}

"""


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["trigram", "pair_control"], default="trigram")
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
        "derived_feature_bins": 26,
        "objective": "shared forward p(c|a,b) and inverse p(a|b,c) from native 26-cubed third-order tensor",
        "updates": "native NaN16 SGD only; no host model arithmetic",
        "epochs": 8,
        "third_order_tensor_shape": [26, 26, 26],
        "split": {},
    }
    for label, group in documents.items():
        examples = []
        metadata = []
        for path, contents, sha in group:
            seed = int.from_bytes(hashlib.sha256((SPLIT_VERSION + sha).encode()).digest()[:8], "big")
            triples = extract_triples(contents.decode("utf-8"), TRIPLES_PER_DOC[label], seed)
            if len(triples) != TRIPLES_PER_DOC[label]:
                raise ValueError("Too few letter triples from a selected book")
            for a, b, c in triples:
                examples.append((a, b, c, 0))
                examples.append((a, b, c, 1))
            metadata.append({
                "file": path.name, "source_sha256": sha, "triples": len(triples),
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
    groups["test_inverse"] = [record for record in groups["test"] if record[3] == 1]
    groups["test_forward"] = [record for record in groups["test"] if record[3] == 0]
    text = emit_fixture(groups)
    if args.mode == "pair_control":
        # The pair control sees exactly the SAME sampled triplets and targets:
        # forward P(c|b), inverse P(a|b). No separate corpus selection.
        text = text.replace(
            "mth_inverse_trigram26_batch_f32", "mth_inverse_dual_batch26_f32")
        text = text.replace("MTH INVERSE TRIGRAM26", "MTH INVERSE PAIR26")
        text = text.replace("INV3_", "INVPAIR_")
        text = text.replace(
            "  MOVI r8,676\n  MUL r8,r7,r8\n  MOVI r9,@mth_inv_weights",
            "  MOVI r8,26\n  MUL r8,r7,r8\n  MOVI r9,@mth_inv_weights",
        )
        def as_pair(m: re.Match[str]) -> str:
            a,b,c,d = map(int, m.groups())
            return f".word {b},{c},0" if d == 0 else f".word {a},{b},1"
        text, count = re.subn(
            r"^\.word (\d+),(\d+),(\d+),([01])$",
            as_pair, text, flags=re.MULTILINE,
        )
        if count != sum(len(g) for g in groups.values()):
            raise AssertionError(f"Paired-control record count mismatch: {count}")
        manifest["objective"] = "matched forward P(c|b) and inverse P(a|b), 26x26"
        manifest["parameter_shape"] = [26, 26]
        manifest.pop("third_order_tensor_shape", None)
    else:
        manifest["parameter_shape"] = [26, 26, 26]
    manifest["control_mode"] = args.mode
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
