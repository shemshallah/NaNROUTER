#!/usr/bin/env python3
"""Export the REAL 48M R25/R26 checkpoint's contextual character logits.

This is an optional local/offline trace adapter for the original R25 Python
hybrid, NOT an implementation of a replacement language model. It calls
direct_context_eval_v22.DirectChar.step() from the restored frozen checkpoint.
Only the existing R25 model computes probabilities. No host learning,
gradients, candidate accept/reject decisions, or tensor writes occur here.

Full-word R25 predictions include a 69,974-word lexicon and a 205,073-node
known-spelling trie. The output here is explicitly its causal 28-way SPELLING
head, NOT full-word perplexity. The native NaN16 CE kernel receives masked
float32 logit rows, evaluates candidate class residuals, and keeps training
decisions outside the Python host.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import struct
import sys

import numpy as np

BASE_SHA = "299a91daf65c8e66fe3489940371d262afef18dd2ef6fef61947ac14c62bb717"
OVERLAY_SHA = "62bf1e5defbb8224d795db16a8e6959cc9aa3d7fed8a63346c4cee205a1bea04"
MASK = 0xFF800000
SLOTS = 28
WORDS = 256


def digest(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda:f.read(1<<20),b""):
            h.update(part)
    return h.hexdigest()


def select_samples(source: Path, ids: dict, prefix: str,
                   count: int, seed: int, r22) -> tuple[list, int]:
    rng=random.Random(seed)
    chosen=[]
    eligible=0
    for prev2,prev1,_,word,ok in r22.iter_valid_with_context(source,ids):
        if not ok or not word.startswith(prefix) or len(word)<=len(prefix):
            continue
        target=word[len(prefix)]
        if target not in "abcdefghijklmnopqrstuvwxyz":
            continue
        item=(int(prev2),int(prev1),ord(target)-97)
        eligible+=1
        if len(chosen)<count:
            chosen.append(item)
        else:
            slot=rng.randrange(eligible)
            if slot<count:chosen[slot]=item
    if len(chosen)<count:
        raise ValueError(f"Insufficient held-out examples of prefix {prefix}: {len(chosen)}")
    return chosen,eligible


def f32bits(value: float) -> int:
    return struct.unpack("<I",struct.pack("<f",value))[0]


def build(archive: Path, dev: Path, test: Path, out: Path,
          manifest: Path, prefix: str, target_class: str,
          samples: int, seed: int) -> None:
    if len(prefix)!=2 or any(c not in "abcdefghijklmnopqrstuvwxyz" for c in prefix):
        raise ValueError("Expected exactly two lowercase natural letters")
    if len(target_class)!=1 or target_class not in "abcdefghijklmnopqrstuvwxyz":
        raise ValueError("Target residual must be an ordinary letter")
    if not 1<=samples<=32:
        raise ValueError("NaN16 ABI supports 1..32 next-character rows per split")
    # These 3 physical axes are 26-letter SYMBOLS, not ASCII byte values:
    # e.g., (t,h,e) -> T[19,7,4]. Mirror directions remain independent.
    coords=(ord(prefix[0])-97,ord(prefix[1])-97,ord(target_class)-97)
    base=archive/"run_v20_new_prose/state.npz"
    overlay=archive/"run_v22_direct_context_char/state_overlay.npz"
    report=archive/"run_v25_pair_context_trie/evaluation.json"
    r21=archive/"run_v21_open_vocab/report.json"
    if digest(base)!=BASE_SHA or digest(overlay)!=OVERLAY_SHA:
        raise ValueError("48M frozen hybrid model digest mismatch")
    cfg=json.loads(report.read_text())
    if cfg["base_sha256"]!=BASE_SHA or cfg["overlay_sha256"]!=OVERLAY_SHA:
        raise ValueError("R25 decoder is not bound to the original checkpoint")
    if cfg["checkpoint_events"]!=48_000_000 or cfg["additional_training_events"]!=0:
        raise ValueError("Unexpected trained-state generation")
    if cfg["chosen_pair_weight"]!=0.1:
        raise ValueError("Frozen development-selected R25 pair mixing changed")
    # Import only the user's archive's original decoder implementation.
    sys.path.insert(0,str(archive.resolve()))
    import normalized_context_vocab_v23 as r23
    import direct_context_char_v22 as r22
    original=argparse.Namespace(base=base,overlay=overlay,r21_report=r21)
    vocab,spelling,direct,_=r23.load(original)
    ids={str(w):int(i) for i,w in enumerate(vocab)}
    alpha=float(cfg["alpha"])
    gamma=float(cfg["gamma"])
    rho=float(cfg["chosen_pair_weight"])
    out.mkdir(parents=True,exist_ok=True)
    record={"schema":"nanrouter-r25-frozen-48m-spelling-ce-trace/1",
            "source_checkpoint_events":48_000_000,
            "base_sha256":BASE_SHA,"overlay_sha256":OVERLAY_SHA,
            "decoder":"original R25 DirectChar.step with frozen 0.1 pair context",
            "not_full_word_probability":True,
            "alphabet_size":28,"nan16_masked_classes":[28,255],
            "tensor_coordinate":list(coords),"prefix":prefix,
            "target_residual":target_class,
            "parameters":{"alpha":alpha,"gamma":gamma,"pair_weight":rho},
            "train_updates":0,
            "sources":{}}
    if dev.resolve()==test.resolve() or digest(dev)==digest(test):
        raise ValueError("Development and test are not disjoint files")
    for group,source,which in (
            ("dev",dev,seed),("test",test,seed+1)):
        selected,nseen=select_samples(source,ids,prefix,samples,which,r22)
        lines=[f"FROZEN_DECODER_TRACE_V1 {coords[0]} {coords[1]} {samples}"]
        for prev2,prev1,label in selected:
            p=direct.step(prefix,(prev2,prev1),0,alpha,gamma,rho)
            if p.shape!=(SLOTS,) or not np.all(np.isfinite(p)) or np.any(p<0):
                raise ValueError("Unnormalized or nonfinite R25 next-character output")
            if abs(float(p.sum())-1)>1e-7 or not float(p[label])>0:
                raise ValueError("R25 spelling target has no finite support")
            logits=[f32bits(math.log(float(x))) if x>0 else MASK for x in p]
            logits.extend([MASK]*(WORDS-SLOTS))
            lines.append(str(label)+" "+" ".join(f"{x:08X}" for x in logits))
        dest=out/f"{group}.trace"
        dest.write_text("\n".join(lines)+"\n",encoding="ascii")
        record["sources"][group]={"path":str(source),
          "sha256":digest(source),"eligible_count":nseen,
          "selected_count":len(selected),
          "trace_sha256":digest(dest)}
    # The exporter is read-only; assert the trained checkpoint remained exact.
    if digest(base)!=BASE_SHA or digest(overlay)!=OVERLAY_SHA:
        raise ValueError("Frozen checkpoint mutated during trace export")
    manifest.parent.mkdir(parents=True,exist_ok=True)
    manifest.write_text(json.dumps(record,sort_keys=True,indent=2)+"\n")
    print("R25_FROZEN_CONTEXT_CHAR_TRACE "+
          json.dumps({"prefix":prefix,"coordinate":list(coords),
          "dev_count":samples,"test_count":samples,
          "dev_eligible":record["sources"]["dev"]["eligible_count"],
          "test_eligible":record["sources"]["test"]["eligible_count"],
          "frozen":True},sort_keys=True))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive-root",type=Path,required=True)
    p.add_argument("--dev",type=Path,required=True)
    p.add_argument("--test",type=Path,required=True)
    p.add_argument("--output-dir",type=Path,required=True)
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--prefix",default="th")
    p.add_argument("--residual-class",default="e")
    p.add_argument("--samples",type=int,default=24)
    p.add_argument("--seed",type=int,default=26048)
    q=p.parse_args()
    build(q.archive_root,q.dev,q.test,q.output_dir,q.manifest,
          q.prefix,q.residual_class,q.samples,q.seed)
