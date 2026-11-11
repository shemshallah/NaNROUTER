#!/usr/bin/env python3
"""CI-only, exact-bit transport of native-admitted ORIGINAL 48M whole-word weight.

NO optimizer, loss arithmetic, gradient or candidacy decision runs here.
The native NaN16 guest supplies its 6-word journal after scoring original
full-word probabilities; this module verifies the pinned decoder trace hashes,
admission metadata and mirror address and calls the existing verified bank1
transport. Never use a string log as production write authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from apply_native_trihead_journal_transport import apply
from init_full128_mirror_tensor_storage import physical_offset

ENTRY = re.compile(
    r"^MTH_WHOLEWORD_ACCEPTED_HEX "
    r"([0-9A-F]{8}) ([0-9A-F]{8}) ([0-9A-F]{8}) "
    r"([0-9A-F]{8}) ([0-9A-F]{8}) ([0-9A-F]{8})$"
)
METRIC = re.compile(r"^WHOLEWORD_(DEV|TEST)_NLL_MILLI ([0-9]+) ([0-9]+) ([01])$")
PASS = "MTH ORIGINAL 48M WHOLEWORD NLL FEEDBACK PASS"
DEV_TRACE = "1965d42b41ee547feea6f76fae23747c83aac07c4ce908098c0186ddbd9b4217"
TEST_TRACE = "ed15c6b43bf1b3988b1e9cdc8bd5a5b25f1c01d73f94188998caa285aceff22d"
EXPECTED = (1,19,7,4,0x004C23C4,0xBE000000)


def parse_native_wholeword_log(raw: bytes) -> tuple[int,int,int,int,int,int]:
    lines=raw.decode("ascii",errors="strict").splitlines()
    if lines.count(PASS)!=1 or any("WHOLEWORD NLL FEEDBACK FAIL" in x for x in lines):
        raise ValueError("Native whole-word loss did not complete successfully")
    journals=[ENTRY.fullmatch(line) for line in lines
              if line.startswith("MTH_WHOLEWORD_ACCEPTED_HEX")]
    if len(journals)!=1 or journals[0] is None:
        raise ValueError("Missing/ambiguous native whole-word acceptance journal")
    rows=[METRIC.fullmatch(line) for line in lines
          if line.startswith("WHOLEWORD_")]
    if len(rows)!=2 or any(row is None for row in rows):
        raise ValueError("Malformed/missing native aggregate word-NLL records")
    values={m[1]:(int(m[2]),int(m[3]),int(m[4])) for m in rows}
    if set(values)!={"DEV","TEST"}:
        raise ValueError("Need separate development and read-only test")
    before,after,admitted=values["DEV"]
    if admitted!=1 or not before>after:
        raise ValueError("No native development whole-word improvement")
    nums=tuple(int(x,16) for x in journals[0].groups())
    proposer,h,a,b,offset,raw_weight=nums
    if nums!=EXPECTED:
        raise ValueError("Wrong pinned original-48M proposal or unadmitted weight")
    if physical_offset(0,h,a,b)[0]!=offset:
        raise ValueError("Candidate mirror orientation/address invalid")
    if (raw_weight&0x7F800000)==0x7F800000:
        raise ValueError("Nonfinite candidate")
    # Test metrics are presented but NEVER consulted for admission.
    return nums


def transport(arena:Path,arena_manifest:Path,native_log:Path,
              source_dev:Path,source_test:Path,fixture_manifest:Path) -> dict:
    for path,expected in [(source_dev,DEV_TRACE),(source_test,TEST_TRACE)]:
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError("Frozen original 48M source probability trace changed")
    evidence=json.loads(fixture_manifest.read_text("utf8"))
    if evidence.get("schema")!="nanrouter-native-48m-wholeword-nll-fixture/1":
        raise ValueError("Wrong native provenance schema")
    if (evidence.get("dev_rows"),evidence.get("test_rows"))!=(128,128):
        raise ValueError("Unsupported original 48M derivation")
    if evidence.get("dev_trace_sha256")!=DEV_TRACE or evidence.get("test_trace_sha256")!=TEST_TRACE:
        raise ValueError("Fixture manifest trace digest mismatch")
    if evidence.get("coordinate")!=[19,7,4] or evidence.get("candidate_theta")!=-0.125:
        raise ValueError("Wrong precommitted tensor residual")
    if evidence.get("heldout_selects_parameters") is not False:
        raise ValueError("Held-out test must not select a parameter")
    result=apply(arena,arena_manifest,native_log,parser=parse_native_wholeword_log)
    result["feedback"]="original frozen 48M R25 whole-word NLL in NaN16"
    result["dev_provenance_sha256"]=DEV_TRACE
    result["test_provenance_sha256"]=TEST_TRACE
    result["heldout_used_to_admit"]=False
    result["promotion_to_active"]=False
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arena",required=True,type=Path)
    p.add_argument("--arena-manifest",required=True,type=Path)
    p.add_argument("--native-log",required=True,type=Path)
    p.add_argument("--dev-trace",required=True,type=Path)
    p.add_argument("--test-trace",required=True,type=Path)
    p.add_argument("--fixture-manifest",required=True,type=Path)
    a=p.parse_args()
    print(json.dumps(transport(a.arena,a.arena_manifest,a.native_log,
                               a.dev_trace,a.test_trace,a.fixture_manifest),
                     sort_keys=True))


if __name__=="__main__":
    main()
