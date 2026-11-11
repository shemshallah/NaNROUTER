#!/usr/bin/env python3
"""Transcribe read-only frozen decoder logit traces into a NaN16 CE fixture.

No Python cross-entropy, learner, meta update, probability or optimizer.
Only validates pinned causal logits and exact mirror address / formats words.
Run trace exporter on the same frozen root with disjoint development/test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from init_full128_mirror_tensor_storage import physical_offset

HEADER = re.compile(r"FROZEN_DECODER_TRACE_V1 (\d+) (\d+) (\d+)")
HEX = re.compile(r"^[0-9A-F]{8}$")


def parse(path: Path, h: int, a: int) -> list[tuple[int, tuple[int, ...]]]:
    lines = path.read_text("ascii").splitlines()
    if not lines:
        raise ValueError("Empty decoder trace")
    m = HEADER.fullmatch(lines[0])
    if m is None or (int(m[1]), int(m[2])) != (h,a):
        raise ValueError("Trace must be causal and match the chosen tensor context")
    count = int(m[3])
    if not 1 <= count <= 32 or len(lines) != count + 1:
        raise ValueError("Unexpected decoder trace count")
    rows = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) != 257:
            raise ValueError("Each decoder row needs target plus 256 raw logits")
        if not re.fullmatch(r"(?:0|[1-9][0-9]{0,2})", fields[0]):
            raise ValueError("Invalid next-byte target")
        label = int(fields[0])
        if label >= 255:
            raise ValueError("Reserved void byte may not be a language target")
        if not all(HEX.fullmatch(w) for w in fields[1:]):
            raise ValueError("Logits must be exact native float32 bit patterns")
        bits = tuple(int(w, 16) for w in fields[1:])
        if bits[255] != 0xFF800000 or any(
            (w & 0x7F800000) == 0x7F800000 and w != 0xFF800000
            for w in bits[:255]
        ) or bits[label] == 0xFF800000:
            raise ValueError("Decoder trace has invalid logits, masked target or nonvoid class255")
        rows.append((label, bits))
    return rows


def word(hex_or_integer: int) -> str:
    return f"0x{hex_or_integer:08X}"


def emit_rows(label: str, rows: list[tuple[int, tuple[int, ...]]]) -> str:
    out = [f"mth_dce_{label}_records:"]
    for target, logits in rows:
        for i in range(0, 256, 16):
            out.append(".word "+",".join(map(word, logits[i:i+16])))
        out.append(f".word {target}")
    return "\n".join(out)


def build(dev: Path, test: Path, output: Path, manifest: Path,
          h: int, a: int, b: int, model_kind: str = "hw0-byte") -> None:
    if any(v > 254 or v < 0 for v in (h, a, b)):
        raise ValueError("Semantic head 255 is not a tensor coordinate")
    if model_kind not in ("hw0-byte", "r25-48m-char"):
        raise ValueError("Unknown frozen decoder type")
    dev_rows = parse(dev, h, a)
    test_rows = parse(test, h, a)
    if model_kind == "r25-48m-char":
        if h > 25 or a > 25 or b > 27:
            raise ValueError("Hybrid character tensor must use alphabet indices, not ASCII")
        for target, bits in (*dev_rows, *test_rows):
            if target > 27 or any(w != 0xFF800000 for w in bits[28:]):
                raise ValueError("Hybrid 28-way spelling trace must pad all unused logits with -inf")
    decoder_name = ("real HW0 unified byte" if model_kind == "hw0-byte"
                    else "original frozen 48M R25 contextual spelling")
    offset, cell, lane = physical_offset(0, h, a, b)
    # Deterministic signed backtracking grid selected before any results.
    # Every trial is scored by native NaN16 against the CURRENT tensor tile.
    # Only development labels contribute to the candidate and meta-credit.
    # The final test trace is entered ONCE, in read-only mode.
    import struct
    signed_grid = (0.5, -0.25, 0.125, -0.0625, 0.03125, -0.015625)
    steps = []
    for step, delta in enumerate(signed_grid):
        raw = struct.unpack("<I", struct.pack("<f", delta))[0]
        steps.append(f"""
  ; Development-only feedback move {step}: {delta:+g}f
  MOVI r11,0x{raw & 65535:04X}
  MOVHI r11,0x{raw >> 16:04X}
  ST r11,r0,@mth_dce_proposal+4
  MOVI r1,@mth_dce_proposal
  MOVI r2,@mth_dce_permission
  MOVI r3,@mth_dce_credit
  MOVI r4,@mth_dce_tile
  MOVI r5,@mth_dce_dev_records
  MOVI r6,{len(dev_rows)}
  MOVI r7,@mth_dce_dev_stats
  MOVI r8,@mth_dce_workspace
  MOVI r9,7
  MOVI r10,1
  CALL @mth_trihead_decoder_ce_feedback_f32
  CMP r1,r13
  JMP[NE] @mth_dce_fail
  LD r11,r0,@mth_dce_dev_stats+2
  LD r12,r0,@mth_dce_accepted_moves
  ADD r12,r12,r11
  ST r12,r0,@mth_dce_accepted_moves
""")
    dev_steps = "\n".join(steps)
    code = f"""; Frozen {decoder_name} decoder logits -> NaN16 CE meta gate.
; Dev is the only training/admission signal. Test is read-only.
; Source traces are read-only, causal; the active 8 MiB model is frozen.
.org 0
JMP @mth_dce_main
.include "../nan16/mth_hypertensor256_mirror_arena_map.nas"
.include "../nan16/mth_lm_cross_entropy256_f32.nas"
.include "../nan16/mth_trihead_decoder_ce_feedback_f32.nas"

mth_dce_main:
  MOVI r0,0
  MOVI r13,1
  ; authorize proposer head 1 (head 0 remains route/control).
  ST r13,r0,@mth_dce_permission+1

  ; Each proposer remains eligible for feedback updates to ANY mirror
  ; coordinate, with one trusted local tile. Only the DEV split trains.
{dev_steps}
  ; Final read-only DEV audit: measure original frozen CE against the
  ; development-selected candidate after all six signed trials.
  MOVI r1,@mth_dce_proposal
  MOVI r2,@mth_dce_permission
  MOVI r3,@mth_dce_credit
  MOVI r4,@mth_dce_tile
  MOVI r5,@mth_dce_dev_records
  MOVI r6,{len(dev_rows)}
  MOVI r7,@mth_dce_dev_stats
  MOVI r8,@mth_dce_workspace
  MOVI r9,7
  MOVI r10,0
  CALL @mth_trihead_decoder_ce_feedback_f32
  CMP r1,r13
  JMP[NE] @mth_dce_fail

  ; Candidate weight and credit MUST remain unchanged by test CE.
  LD r11,r0,@mth_dce_tile+1
  ST r11,r0,@mth_dce_dev_weight
  LD r11,r0,@mth_dce_credit+1
  ST r11,r0,@mth_dce_dev_credit

  MOVI r1,@mth_dce_proposal
  MOVI r2,@mth_dce_permission
  MOVI r3,@mth_dce_credit
  MOVI r4,@mth_dce_tile
  MOVI r5,@mth_dce_test_records
  MOVI r6,{len(test_rows)}
  MOVI r7,@mth_dce_test_stats
  MOVI r8,@mth_dce_workspace
  MOVI r9,7
  MOVI r10,0
  CALL @mth_trihead_decoder_ce_feedback_f32
  CMP r1,r13
  JMP[NE] @mth_dce_fail

  LD r11,r0,@mth_dce_dev_weight
  LD r12,r0,@mth_dce_tile+1
  CMP r11,r12
  JMP[NE] @mth_dce_fail
  LD r11,r0,@mth_dce_dev_credit
  LD r12,r0,@mth_dce_credit+1
  CMP r11,r12
  JMP[NE] @mth_dce_fail

  MOVI r1,@mth_dce_dev_label
  CALL @mth_dce_puts
  MOVI r1,@mth_dce_dev_stats
  CALL @mth_dce_print_metrics
  MOVI r1,@mth_dce_test_label
  CALL @mth_dce_puts
  MOVI r1,@mth_dce_test_stats
  CALL @mth_dce_print_metrics
  MOVI r1,@mth_dce_moves_label
  CALL @mth_dce_puts
  LD r1,r0,@mth_dce_accepted_moves
  CALL @mth_dce_print_uint
  MOVI r1,10
  PUTC r1

  ; Journal written ONLY when DEV admitted an improvement. The test
  ; result is explicitly excluded from the admission decision. These
  ; six raw U32 words are native-authored, not a host optimizer result.
  LD r11,r0,@mth_dce_dev_stats+2
  CMP r11,r13
  JMP[NE] @mth_dce_no_journal
  LD r11,r0,@mth_dce_accepted_moves
  CMP r11,r0
  JMP[EQ] @mth_dce_no_journal
  MOVI r1,@mth_dce_journal_label
  CALL @mth_dce_puts
  LD r1,r0,@mth_dce_proposal
  CALL @mth_dce_hex32
  MOVI r1,32
  PUTC r1
  LD r1,r0,@mth_dce_proposal+1
  CALL @mth_dce_hex32
  MOVI r1,32
  PUTC r1
  LD r1,r0,@mth_dce_proposal+2
  CALL @mth_dce_hex32
  MOVI r1,32
  PUTC r1
  LD r1,r0,@mth_dce_proposal+3
  CALL @mth_dce_hex32
  MOVI r1,32
  PUTC r1
  LD r1,r0,@mth_dce_tile
  CALL @mth_dce_hex32
  MOVI r1,32
  PUTC r1
  LD r1,r0,@mth_dce_tile+1
  CALL @mth_dce_hex32
  MOVI r1,10
  PUTC r1
mth_dce_no_journal:
  MOVI r1,@mth_dce_pass
  CALL @mth_dce_puts
  HALT
mth_dce_fail:
  MOVI r1,@mth_dce_bad
  CALL @mth_dce_puts
  HALT

; Print before/after loss as *truncated milli-nats per character*, then
; native accepted flag; all arithmetic and formatting is native NaN16.
mth_dce_print_metrics:
  ST r15,r0,@mth_dce_pr_link
  ST r1,r0,@mth_dce_pr_ptr
  LD r11,r1,5
  CVTIF r11,r11
  LD r12,r1,0
  FDIV r12,r12,r11
  MOVI r11,0
  MOVHI r11,0x447A      ; 1000.0f
  FMUL r12,r12,r11
  CVTFI r1,r12
  CALL @mth_dce_print_uint
  MOVI r1,32
  PUTC r1
  LD r11,r0,@mth_dce_pr_ptr
  LD r12,r11,5
  CVTIF r12,r12
  LD r14,r11,1
  FDIV r14,r14,r12
  MOVI r12,0
  MOVHI r12,0x447A
  FMUL r14,r14,r12
  CVTFI r1,r14
  CALL @mth_dce_print_uint
  MOVI r1,32
  PUTC r1
  LD r11,r0,@mth_dce_pr_ptr
  LD r1,r11,2
  CALL @mth_dce_print_uint
  MOVI r1,10
  PUTC r1
  LD r15,r0,@mth_dce_pr_link
  RET

mth_dce_print_uint:
  MOVI r9,0
mth_dce_num_digit:
  MOVI r10,10
  MODU r11,r1,r10
  ADDI r11,r11,48
  MOVI r12,@mth_dce_digits
  ADD r12,r12,r9
  ST r11,r12,0
  ADDI r9,r9,1
  DIV r1,r1,r10
  CMP r1,r0
  JMP[NE] @mth_dce_num_digit
mth_dce_num_out:
  ADDI r9,r9,-1
  MOVI r12,@mth_dce_digits
  ADD r12,r12,r9
  LD r11,r12,0
  PUTC r11
  CMP r9,r0
  JMP[GT] @mth_dce_num_out
  RET

; Exact eight-hex-digit native U32 printer (no host learner).
mth_dce_hex32:
  MOVI r3,0
mth_dce_hex_nibble:
  SHR r2,r1,28
  MOVI r4,15
  BOOL.8 r2,r2,r4
  MOVI r4,10
  CMP r2,r4
  JMP[LT] @mth_dce_hex_digit
  ADDI r2,r2,55
  JMP @mth_dce_hex_emit
mth_dce_hex_digit:
  ADDI r2,r2,48
mth_dce_hex_emit:
  PUTC r2
  SHL r1,r1,4
  ADDI r3,r3,1
  MOVI r4,8
  CMP r3,r4
  JMP[LT] @mth_dce_hex_nibble
  RET

mth_dce_puts:
  MOVI r4,255
mth_dce_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_dce_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_dce_puts_byte
  ADD r1,r1,r13
  JMP @mth_dce_puts_word

.org 11000
mth_dce_proposal:
.word 1,{h},{a},{b},0x3F000000,0
mth_dce_tile:
.word {word(offset)},0,7
mth_dce_permission:
.word 0
.org 11400
mth_dce_credit:
.word 0,0x3F800000
.org 11700
mth_dce_dev_stats:
.word 0,0,0,0,0,0
mth_dce_test_stats:
.word 0,0,0,0,0,0
mth_dce_dev_weight:
.word 0
mth_dce_dev_credit:
.word 0
mth_dce_accepted_moves:
.word 0
mth_dce_pr_link:
.word 0
mth_dce_pr_ptr:
.word 0
mth_dce_digits:
.word 0,0,0,0,0,0,0,0,0,0
mth_dce_dev_label:
.str "DCE_DEV_NAT_MILLI "
mth_dce_test_label:
.str "DCE_TEST_NAT_MILLI "
mth_dce_moves_label:
.str "DCE_DEV_ACCEPTED_MOVES "
mth_dce_journal_label:
.str "MTH_DECODER_CE_ACCEPTED_HEX "
mth_dce_pass:
.str "MTH REAL DECODER CE FEEDBACK PASS\\n"
mth_dce_bad:
.str "MTH REAL DECODER CE FEEDBACK FAIL\\n"

.org 12500
mth_dce_workspace:
.word 0

.org 24000
{emit_rows('dev', dev_rows)}
.org 44000
{emit_rows('test', test_rows)}
"""
    # A bounded guest image: no data overlaps or falls outside 65,536 words.
    if 24000 + 257 * len(dev_rows) >= 44000:
        raise ValueError("Dev trace would overlap test section")
    if 44000 + 257 * len(test_rows) >= 65536:
        raise ValueError("Test trace exceeds guest word budget")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(code, encoding="utf8")
    evidence = {
        "schema": "nanrouter.real-frozen-decoder-ce-feedback/1",
        "model": decoder_name,
        "model_kind": model_kind,
        "hybrid_spelling_48m_connected": model_kind == "r25-48m-char",
        "hybrid_full_word_perplexity_connected": False,
        "geometry": "full 256^3 mirrored directional tensor, 128 MiB dual bank",
        "tensor_coordinate": [h,a,b],
        "mirror_canonical_cell": cell,
        "mirror_direction": lane,
        "mirror_relative_offset": offset,
        "proposer": 1,
        "candidate_delta_grid_dev_only": list(signed_grid),
        "admission_split": "six signed native dev-only moves; test read-only",
        "loss": ("native NaN16 255-way byte CE" if model_kind == "hw0-byte"
                 else "native NaN16 masked 28-way contextual character CE"),
        "frozen_trace_sha256": {
            "dev": hashlib.sha256(dev.read_bytes()).hexdigest(),
            "test": hashlib.sha256(test.read_bytes()).hexdigest(),
        },
        "sample_count": {"dev":len(dev_rows),"test":len(test_rows)},
        "native_fixture_sha256": hashlib.sha256(code.encode()).hexdigest(),
        "host_optimizer": False,
        "root_updated": False,
        "full_model_43m_connected": False,
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(evidence, sort_keys=True, indent=2)+"\n")
    print(json.dumps({"samples": evidence["sample_count"],"coordinate":[h,a,b],
                      "fixture_sha256":evidence["native_fixture_sha256"]},sort_keys=True))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dev", type=Path, required=True)
    p.add_argument("--test", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--h", type=int, default=116)  # 't'
    p.add_argument("--a", type=int, default=104)  # 'h'
    p.add_argument("--b", type=int, default=101)  # 'e' as raw HW0 byte
    p.add_argument("--model-kind", choices=("hw0-byte","r25-48m-char"),
                   default="hw0-byte")
    args = p.parse_args()
    build(args.dev,args.test,args.output,args.manifest,
          args.h,args.a,args.b,args.model_kind)


if __name__ == "__main__":
    main()
