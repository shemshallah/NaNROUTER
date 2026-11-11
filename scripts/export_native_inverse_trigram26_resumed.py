#!/usr/bin/env python3
"""Validate and export *resumed* 26^3 native NaN16 checkpoint.

All gradient/loss/SGD computations were done by the NaN16 guest. This
script checks complete VM serial frames, 17,576 finite f32 word images,
new document separation, and development-only candidate admission.
The original parent weights are never overwritten.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

LABELS = (
    "INV3_RESUME_DEV_BEFORE_HITS_PERMIL",
    "INV3_DEV_AFTER_HITS_PERMIL",
    "INV3_TEST_BEFORE_HITS_PERMIL",
    "INV3_TEST_AFTER_HITS_PERMIL",
    "INV3_INVERSE_BEFORE_HITS_PERMIL",
    "INV3_INVERSE_AFTER_HITS_PERMIL",
    "INV3_FORWARD_AFTER_HITS_PERMIL",
)
PARENT_SHA = "c43ab50b88da8b6fb3d1bb7a060a40a73ebeb95cea3494b1ee53c246e7881afa"


def main():
    p=argparse.ArgumentParser()
    for flag in ("log","manifest","output-dir"):
        p.add_argument("--"+flag,type=Path,required=True)
    a=p.parse_args()
    raw=a.log.read_bytes()
    lines=raw.decode("utf-8").splitlines()
    for marker in ("INV3_RESUME_PARENT_VERIFIED","MTH INVERSE TRIGRAM26 GLOBAL HEAD BRIDGE PASS",
                   "MTH INVERSE TRIGRAM26 CORPUS TRAIN PASS"):
        if lines.count(marker)!=1:
            raise ValueError("Missing/duplicate successful native marker: "+marker)
    if lines.count("INV3_CHECKPOINT_BEGIN")!=1 or lines.count("INV3_CHECKPOINT_END")!=1:
        raise ValueError("Expected one exact guest checkpoint frame")
    start=lines.index("INV3_CHECKPOINT_BEGIN")
    end=lines.index("INV3_CHECKPOINT_END")
    if end-start!=17577:
        raise ValueError(f"Expected 17576 tensor words, found {end-start-1}")
    data=bytearray()
    for idx,word in enumerate(lines[start+1:end]):
        if not re.fullmatch(r"[0-9A-F]{8}",word):
            raise ValueError("Invalid native raw f32 hex word "+str(idx))
        value=int(word[::-1],16)
        if value & 0x7F800000 == 0x7F800000:
            raise ValueError("Nonfinite native raw f32 word "+str(idx))
        data+=struct.pack("<I",value)
    metrics={}
    for line in lines[:start]:
        match=re.fullmatch(r"(INV3_[A-Z_]+) (\d+) (\d+)",line)
        if match:
            if match.group(1) in metrics:
                raise ValueError("Duplicate metric "+match.group(1))
            metrics[match.group(1)]={
                "correct":int(match.group(2)),
                "mean_target_probability_per_mille_truncated":int(match.group(3))
            }
    for name in LABELS:
        if name not in metrics:
            raise ValueError("Missing native metric "+name)
    manifest=json.loads(a.manifest.read_text())
    if (manifest["schema"]!="nanrouter.inverse26.resume.fresh-v1"
        or manifest["parent_tensor_sha256"] != PARENT_SHA
        or manifest["semantic_head255"]!="zero/void"
        or manifest["parameter_shape"]!=[26,26,26]
        or manifest["new_epochs"]!=4
        or manifest["split"]["test"]["examples"]!=768):
        raise ValueError("Resume manifest contract invalid")
    old=set(manifest["excluded_prior_gutenberg_ids"])
    for label in ("train","dev","test"):
        docs=manifest["split"][label]["documents"]
        if old & {x["gutenberg_id"] for x in docs}:
            raise ValueError("Historical document leaked into new split")
    dv0=metrics["INV3_RESUME_DEV_BEFORE_HITS_PERMIL"]
    dv1=metrics["INV3_DEV_AFTER_HITS_PERMIL"]
    admission=(
        dv1["mean_target_probability_per_mille_truncated"] >
        dv0["mean_target_probability_per_mille_truncated"]
        or (
            dv1["mean_target_probability_per_mille_truncated"] ==
            dv0["mean_target_probability_per_mille_truncated"]
            and dv1["correct"]>=dv0["correct"]
        )
    )
    digest=hashlib.sha256(data).hexdigest()
    a.output_dir.mkdir(parents=True,exist_ok=True)
    file=a.output_dir/"inverse_trigram26_resume.tensor.f32le.bin"
    file.write_bytes(data)
    (a.output_dir/"SHA256SUMS").write_text(f"{digest}  {file.name}\n",encoding="ascii")
    result={
        "schema":"nanrouter.inverse-trigram26.resumed-native-checkpoint/1",
        "parent_tensor_sha256":PARENT_SHA,
        "candidate_tensor_sha256":digest,
        "candidate_file":file.name,
        "candidate_bytes":len(data),
        "new_native_sgd_epochs":manifest["new_epochs"],
        "cumulative_epochs":manifest["cumulative_epochs_from_parent"],
        "native_resume_check":"Passed both complete 32-bit checksums and zero/void255 check",
        "training_corpus_split_sha256":hashlib.sha256(a.manifest.read_bytes()).hexdigest(),
        "native_training_stdout_sha256":hashlib.sha256(raw).hexdigest(),
        "admitted_by_fresh_dev_only":admission,
        "admission_policy":"mean correct-target probability per mille nondecreasing; ties require top1 nondecreasing",
        "previous_parent_retained_on_reject":not admission,
        "all_new_books_disjoint_from_prior":True,
        "test_not_used_for_admission":True,
        "hybrid_48M_checkpoint_updated":False,
        "root8MiB_updated":False,
        "void_head":255,
        "metrics":metrics,
    }
    (a.output_dir/"checkpoint.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
        "admitted":admission,
        "candidate_sha256":digest,
        "parent_sha256":PARENT_SHA,
        "candidate_bytes":len(data),
        "native_metrics":metrics,
    },sort_keys=True))


if __name__=="__main__":
    main()
