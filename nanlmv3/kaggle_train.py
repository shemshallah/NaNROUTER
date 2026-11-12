#!/usr/bin/env python3
"""Kaggle GPU entrypoint for nanlmv3.

Expected Kaggle dataset layout:

    /kaggle/input/nanlmv3-corpus/corpus_100m.txt
    /kaggle/input/nanlmv3-corpus/bpe32k.json   (optional; trained here if absent)

The dataset can be created from the local files:

    nanlmv3/data/corpus_100m.txt
    bpe32k.json

Run in a GPU notebook after cloning the repo:

    !git clone https://github.com/shemshallah/NaNROUTER
    !python NaNROUTER/nanlmv3/kaggle_train.py

Environment overrides: STEPS, BATCH, CTX, LR, MODEL_MB.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CORPUS = Path(os.environ.get("CORPUS", "/kaggle/input/nanlmv3-corpus/corpus_100m.txt"))
BPE = Path(os.environ.get("BPE", "/kaggle/input/nanlmv3-corpus/bpe32k.json"))
OUT = Path(os.environ.get("OUT", "/kaggle/working"))
STEPS = os.environ.get("STEPS", "20000")
BATCH = os.environ.get("BATCH", "16")
CTX = os.environ.get("CTX", "128")
LR = os.environ.get("LR", "3e-4")


def main() -> int:
    import torch

    if not torch.cuda.is_available():
        print("CUDA is not available. Select a Kaggle GPU accelerator.", file=sys.stderr)
        return 2
    if not CORPUS.exists():
        print(f"missing corpus: {CORPUS}", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)

    if not BPE.exists():
        print("[kaggle] BPE missing; training 32k on the corpus", flush=True)
        cmd = [
            sys.executable, "nanlmv3/train_bpe.py",
            "--corpus", str(CORPUS),
            "--vocab-size", "32000",
            "--output", str(OUT / "bpe32k.json"),
            "--meta", str(OUT / "bpe32k_meta.json"),
        ]
        subprocess.run(cmd, check=True)
        bpe_path = OUT / "bpe32k.json"
    else:
        bpe_path = BPE

    cmd = [
        sys.executable, "nanlmv3/frontier_model.py",
        "--mode", "hybrid",
        "--corpus", str(CORPUS),
        "--tokenizer", "bpe",
        "--bpe-model", str(bpe_path),
        "--params", "10m",
        "--trunk-layers", "4",
        "--trunk-heads", "8",
        "--trunk-ff", "1024",
        "--steps", STEPS,
        "--batch-size", BATCH,
        "--ctx", CTX,
        "--orders", "4",
        "--train-fraction", "0.95",
        "--eval-every", "500",
        "--eval-batches", "64",
        "--dropout", "0.15",
        "--weight-decay", "0.05",
        "--lr", LR,
        "--prev-weight", "0.1",
        "--recluster-every", "2000",
        "--amp",
        "--device", "cuda",
        "--threads", "4",
        "--summary", str(OUT / "train_summary.json"),
        "--checkpoint", str(OUT / "train.pt"),
        "--best-checkpoint", str(OUT / "best.pt"),
        "--log", str(OUT / "train.jsonl"),
    ]
    print("[kaggle] running:", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    print("[kaggle] done; see /kaggle/working", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
