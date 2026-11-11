#!/usr/bin/env python3
"""Replay the exact native decoder-CE-admitted tensor word, CI-only.

The real HW0 frozen decoder emits causal next-byte logits. Only the NaN16
cross-entropy/meta kernel accepts a candidate weight. This file performs
strict provenance/mirror validation and transport ONLY. It never calculates
cross entropy, changes gradients or decides a candidate's quality.

SECURITY CONTRACT: unsigned log lines are NOT production authority.
Only a pinned runner invocation with trusted NaN16 guest and attested
frozen decoder/corpus may use this CI pilot. There is no active promotion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from apply_native_trihead_journal_transport import apply
from init_full128_mirror_tensor_storage import physical_offset, sha256_file

ACCEPTED = re.compile(
    r"^MTH_DECODER_CE_ACCEPTED_HEX "
    r"([0-9A-F]{8}) ([0-9A-F]{8}) ([0-9A-F]{8}) "
    r"([0-9A-F]{8}) ([0-9A-F]{8}) ([0-9A-F]{8})$"
)
PASS = "MTH REAL DECODER CE FEEDBACK PASS"
MOVES = re.compile(r"^DCE_DEV_ACCEPTED_MOVES ([1-6])$")
DEV = re.compile(r"^DCE_DEV_NAT_MILLI (\d+) (\d+) 1$")
TEST = re.compile(r"^DCE_TEST_NAT_MILLI (\d+) (\d+) [01]$")


def parse_decoder_native_log(log: bytes) -> tuple[int,int,int,int,int,int]:
    lines=log.decode("ascii",errors="strict").splitlines()
    records=[ACCEPTED.fullmatch(x) for x in lines
             if x.startswith("MTH_DECODER_CE_ACCEPTED_HEX")]
    if len(records)!=1 or records[0] is None:
        raise ValueError("native decoder-CE acceptance journal missing/ambiguous")
    if lines.count(PASS)!=1 or any("MTH REAL DECODER CE FEEDBACK FAIL" in x for x in lines):
        raise ValueError("native decoder-CE proof did not pass")
    for pattern in (MOVES,DEV,TEST):
        rows=[pattern.fullmatch(line) for line in lines if line.startswith(
            "DCE_DEV_ACCEPTED_MOVES " if pattern is MOVES else
            "DCE_DEV_NAT_MILLI " if pattern is DEV else "DCE_TEST_NAT_MILLI ")]
        if len(rows)!=1 or rows[0] is None:
            raise ValueError("incomplete native CE dev/test provenance")
    numbers=tuple(int(s,16) for s in records[0].groups())
    proposer,h,a,b,offset,word=numbers
    if not 0<=proposer<=254:
        raise ValueError("proposer void/out of range")
    expected,_,_=physical_offset(0,h,a,b)
    if offset!=expected:
        raise ValueError("native journal mirror address mismatch")
    if (word & 0x7f800000)==0x7f800000:
        raise ValueError("nonfinite native candidate weight")
    return numbers


def replay(arena: Path, arena_manifest: Path, native_log: Path,
           frozen_root: Path, book_manifest: Path) -> dict:
    record=json.loads(book_manifest.read_text(encoding="utf8"))
    if record.get("schema")!="nanrouter-frozen-real-decoder-disjoint-books/1":
        raise ValueError("missing registered document-split manifest")
    groups=record["groups"]
    if any(len(groups[k]["books"])!=6 or groups[k]["rows"]<1
           for k in ("dev","test")):
        raise ValueError("dev and test must contain six distinct Gutenberg books")
    dev={item["sha256"] for item in groups["dev"]["books"]}
    test={item["sha256"] for item in groups["test"]["books"]}
    if dev & test or len(dev)!=6 or len(test)!=6:
        raise ValueError("leaked or duplicated Gutenberg documents")
    if sha256_file(frozen_root)!=record["decoder_root_sha256"]:
        raise ValueError("frozen decoder root digest changed")
    result=apply(arena,arena_manifest,native_log,parser=parse_decoder_native_log)
    if sha256_file(frozen_root)!=record["decoder_root_sha256"]:
        raise ValueError("frozen root changed during journal transport")
    result["feedback"]="native real frozen decoder next-byte cross entropy"
    result["decoder_root_sha256"]=record["decoder_root_sha256"]
    result["dev_books"]=len(dev)
    result["test_books"]=len(test)
    result["test_used_for_admission"]=False
    result["promotion_implemented"]=False
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arena",type=Path,required=True)
    p.add_argument("--arena-manifest",type=Path,required=True)
    p.add_argument("--native-log",type=Path,required=True)
    p.add_argument("--decoder-root",type=Path,required=True)
    p.add_argument("--books-manifest",type=Path,required=True)
    q=p.parse_args()
    print(json.dumps(replay(q.arena,q.arena_manifest,q.native_log,
                            q.decoder_root,q.books_manifest),sort_keys=True))
