#!/usr/bin/env python3
"""Build a NaN16 guest from paired TRUE full-word probabilities.

Input probabilities are inferred by the ORIGINAL frozen R25 decoder +
exact known-lexicon trie complement. This builder does no scoring, CE,
optimization, accept/reject or model arithmetic. Only the guest does.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path
from init_full128_mirror_tensor_storage import physical_offset

HEADER=re.compile(r"FROZEN_48M_WHOLEWORD_PROB_V1 ([1-9][0-9]{0,3})$")
PAIR=re.compile(r"([0-9A-F]{8}) ([0-9A-F]{8})")


def parse(path:Path) -> list[tuple[int,int]]:
    lines=path.read_text("ascii").splitlines()
    if not lines or (m:=HEADER.fullmatch(lines[0])) is None:
        raise ValueError("Expected frozen 48M full-word probability trace")
    n=int(m[1])
    if n>1024 or len(lines)!=n+1:raise ValueError("Invalid trace count")
    result=[]
    for line in lines[1:]:
        row=PAIR.fullmatch(line)
        if row is None:raise ValueError("Invalid float32 probability word")
        x,y=(int(z,16) for z in row.groups())
        for word in (x,y):
            # Float32 positive, finite and <=1; reject quietly altered logits.
            if word==0 or (word>>31) or word>0x3F800000:
                raise ValueError("Invalid probability; P(w) must be in (0,1]")
        result.append((x,y))
    return result


def generated_rows(label,rows):
    lines=[f"mth_ww_{label}_rows:"]
    for i in range(0,len(rows),8):
        values=[f"0x{w:08X}" for pair in rows[i:i+8] for w in pair]
        lines.append(".word "+",".join(values))
    return "\n".join(lines)


def build(dev:Path,test:Path,dest:Path,manifest:Path,
          h=19,a=7,b=4,theta=-0.125,expected=None):
    if not 0<=h<26 or not 0<=a<26 or not 0<=b<26:
        raise ValueError("Use letter-symbol head coordinates, not raw ASCII")
    if abs(theta)>1 or not -1<=theta<=1:
        raise ValueError("Unbounded candidate")
    # No access to test labels before the developer candidate is fixed.
    d=parse(dev)
    t=parse(test)
    offset,cell,lane=physical_offset(0,h,a,b)
    theta_bits=struct.unpack("<I",struct.pack("<f",theta))[0]
    code=rf'''; Original 48M R25 exact normalized whole-word NLL.
; Native admission is based on development WHOLEWORD loss, not char CE.
; Test is readonly, even if its direction disagrees with development.
.org 0
JMP @mth_ww_main
.include "../nan16/mth_hypertensor256_mirror_arena_map.nas"
.include "../nan16/mth_vector_log256_f32.nas"
.include "../nan16/mth_trihead_wholeword_nll_feedback_f32.nas"

mth_ww_main:
  MOVI r0,0
  MOVI r13,1
  ; Native authorized proposer 1, proposal targets T[{h},{a},{b}].
  ST r13,r0,@mth_ww_permissions+1
  MOVI r1,@mth_ww_dev_rows
  MOVI r2,{len(d)}
  MOVI r3,@mth_ww_permissions
  MOVI r4,@mth_ww_proposal
  MOVI r5,@mth_ww_tile
  MOVI r6,@mth_ww_credit
  MOVI r7,@mth_ww_dev_out
  MOVI r8,@mth_ww_scratch
  MOVI r9,7
  MOVI r10,1
  MOVI r11,0x{theta_bits&65535:04X}
  MOVHI r11,0x{theta_bits>>16:04X}
  CALL @mth_trihead_wholeword_nll_feedback_f32
  CMP r1,r13
  JMP[NE] @mth_ww_fail

  LD r11,r0,@mth_ww_tile+1
  ST r11,r0,@mth_ww_stored_weight
  LD r11,r0,@mth_ww_credit+1
  ST r11,r0,@mth_ww_stored_credit

  MOVI r1,@mth_ww_test_rows
  MOVI r2,{len(t)}
  MOVI r3,@mth_ww_permissions
  MOVI r4,@mth_ww_proposal
  MOVI r5,@mth_ww_tile
  MOVI r6,@mth_ww_credit
  MOVI r7,@mth_ww_test_out
  MOVI r8,@mth_ww_scratch
  MOVI r9,7
  MOVI r10,0         ; immutable HELDOUT feedback
  MOVI r11,0x{theta_bits&65535:04X}
  MOVHI r11,0x{theta_bits>>16:04X}
  CALL @mth_trihead_wholeword_nll_feedback_f32
  CMP r1,r13
  JMP[NE] @mth_ww_fail
  LD r11,r0,@mth_ww_tile+1
  LD r12,r0,@mth_ww_stored_weight
  CMP r11,r12
  JMP[NE] @mth_ww_fail
  LD r11,r0,@mth_ww_credit+1
  LD r12,r0,@mth_ww_stored_credit
  CMP r11,r12
  JMP[NE] @mth_ww_fail

  MOVI r1,@mth_ww_dev_label
  CALL @mth_ww_puts
  MOVI r1,@mth_ww_dev_out
  CALL @mth_ww_print_stats
  MOVI r1,@mth_ww_test_label
  CALL @mth_ww_puts
  MOVI r1,@mth_ww_test_out
  CALL @mth_ww_print_stats

  ; Native dev-only acceptance journal. The six words are contiguous:
  ; [proposer,h,a,b,mirror_offset,candidate_weight].
  LD r11,r0,@mth_ww_dev_out+2
  CMP r11,r13
  JMP[NE] @mth_ww_no_journal
  MOVI r1,@mth_ww_journal_label
  CALL @mth_ww_puts
  MOVI r6,0
mth_ww_journal_words:
  MOVI r2,@mth_ww_proposal
  ADD r2,r2,r6
  LD r1,r2,0
  CALL @mth_ww_hex32
  ADDI r6,r6,1
  MOVI r12,6
  CMP r6,r12
  JMP[EQ] @mth_ww_journal_end
  MOVI r1,32
  PUTC r1
  JMP @mth_ww_journal_words
mth_ww_journal_end:
  MOVI r1,10
  PUTC r1
mth_ww_no_journal:
  MOVI r1,@mth_ww_pass_label
  CALL @mth_ww_puts
  HALT
mth_ww_fail:
  MOVI r1,@mth_ww_bad_label
  CALL @mth_ww_puts
  HALT

; Emit native loss SUM in thousandths of a nat, not host-scored.
mth_ww_print_stats:
  ST r15,r0,@mth_ww_printlink
  ST r1,r0,@mth_ww_printptr
  LD r12,r1,0
  MOVI r11,0
  MOVHI r11,0x447A
  FMUL r12,r12,r11
  CVTFI r1,r12
  CALL @mth_ww_print_uint
  MOVI r1,32
  PUTC r1
  LD r11,r0,@mth_ww_printptr
  LD r12,r11,1
  MOVI r11,0
  MOVHI r11,0x447A
  FMUL r12,r12,r11
  CVTFI r1,r12
  CALL @mth_ww_print_uint
  MOVI r1,32
  PUTC r1
  LD r11,r0,@mth_ww_printptr
  LD r1,r11,2
  CALL @mth_ww_print_uint
  MOVI r1,10
  PUTC r1
  LD r15,r0,@mth_ww_printlink
  RET

mth_ww_print_uint:
  MOVI r9,0
mth_ww_num:
  MOVI r10,10
  MODU r11,r1,r10
  ADDI r11,r11,48
  MOVI r12,@mth_ww_digits
  ADD r12,r12,r9
  ST r11,r12,0
  ADDI r9,r9,1
  DIV r1,r1,r10
  CMP r1,r0
  JMP[NE] @mth_ww_num
mth_ww_num_print:
  ADDI r9,r9,-1
  MOVI r12,@mth_ww_digits
  ADD r12,r12,r9
  LD r11,r12,0
  PUTC r11
  CMP r9,r0
  JMP[GT] @mth_ww_num_print
  RET

; Native exact eight-hex-digit U32 transport printer.
mth_ww_hex32:
  MOVI r3,0
mth_ww_hex_nibble:
  SHR r2,r1,28
  MOVI r4,15
  BOOL.8 r2,r2,r4
  MOVI r4,10
  CMP r2,r4
  JMP[LT] @mth_ww_hex_digit
  ADDI r2,r2,55
  JMP @mth_ww_hex_emit
mth_ww_hex_digit:
  ADDI r2,r2,48
mth_ww_hex_emit:
  PUTC r2
  SHL r1,r1,4
  ADDI r3,r3,1
  MOVI r4,8
  CMP r3,r4
  JMP[LT] @mth_ww_hex_nibble
  RET

mth_ww_puts:
  MOVI r4,255
mth_ww_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_ww_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_ww_puts_byte
  ADD r1,r1,r13
  JMP @mth_ww_puts_word

.org 11000
mth_ww_proposal:
.word 1,{h},{a},{b}
mth_ww_tile:
.word 0x{offset:08X},0,7
mth_ww_permissions:
.word 0
.org 11400
mth_ww_credit:
.word 0,0x3F800000
.org 11800
mth_ww_dev_out:
.word 0,0,0,0,0
mth_ww_test_out:
.word 0,0,0,0,0
mth_ww_stored_weight:
.word 0
mth_ww_stored_credit:
.word 0
mth_ww_printlink:
.word 0
mth_ww_printptr:
.word 0
mth_ww_digits:
.word 0,0,0,0,0,0,0,0,0,0
mth_ww_dev_label:
.str "WHOLEWORD_DEV_NLL_MILLI "
mth_ww_test_label:
.str "WHOLEWORD_TEST_NLL_MILLI "
mth_ww_journal_label:
.str "MTH_WHOLEWORD_ACCEPTED_HEX "
mth_ww_pass_label:
.str "MTH ORIGINAL 48M WHOLEWORD NLL FEEDBACK PASS\n"
mth_ww_bad_label:
.str "MTH ORIGINAL 48M WHOLEWORD NLL FEEDBACK FAIL\n"

.org 12500
mth_ww_scratch:
.word 0

.org 24000
{generated_rows('dev',d)}
.org 32000
{generated_rows('test',t)}
'''
    if 24000+2*len(d)>=32000 or 32000+2*len(t)>=65536:
        raise ValueError("Native guest word image overlaps")
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(code,encoding="ascii")
    meta={"schema":"nanrouter-native-48m-wholeword-nll-fixture/1",
          "native_decides":True,"loss":"sum -ln P(original true next word)",
          "spelling_lexicon":"original trained 69974-type vocabulary",
          "trie_nodes":205073,
          "dev_rows":len(d),"test_rows":len(t),"candidate_theta":theta,
          "coordinate":[h,a,b],"relative_mirror_offset":offset,
          "cell":cell,"lane":lane,
          "dev_trace_sha256":hashlib.sha256(dev.read_bytes()).hexdigest(),
          "test_trace_sha256":hashlib.sha256(test.read_bytes()).hexdigest(),
          "generated_sha256":hashlib.sha256(code.encode("ascii")).hexdigest(),
          "heldout_selects_parameters":False,"root_mutated":False}
    manifest.parent.mkdir(parents=True,exist_ok=True)
    manifest.write_text(json.dumps(meta,sort_keys=True,indent=2)+"\n")
    print(json.dumps({k:meta[k] for k in ("dev_rows","test_rows","candidate_theta",
             "relative_mirror_offset","generated_sha256")},sort_keys=True))


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--dev",type=Path,required=True)
    p.add_argument("--test",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--h",type=int,default=19)
    p.add_argument("--a",type=int,default=7)
    p.add_argument("--b",type=int,default=4)
    p.add_argument("--theta",type=float,default=-.125)
    args=p.parse_args()
    build(args.dev,args.test,args.output,args.manifest,
          args.h,args.a,args.b,args.theta)

if __name__=="__main__":main()
