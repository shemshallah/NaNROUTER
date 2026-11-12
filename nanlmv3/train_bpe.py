#!/usr/bin/env python3
"""Train a 32k byte-level BPE tokenizer for frontier_model.py.

This uses the standard `tokenizers` library.  It is intentionally a separate
step because a 32k BPE should be trained once on a large, deduplicated sample,
not inside every model run.

Run on a host with a prebuilt tokenizers wheel (Ubuntu/GitHub Actions is the
easy path):

    pip install tokenizers
    python train_bpe.py --corpus ~/meta/corpus_sample_5m.txt \
        --vocab-size 32000 --output ~/meta/bpe32k.json

On Termux/Android there is no manylinux wheel; the Rust source build may work
but is not required for the char-level Stage 0.  The model accepts
``--tokenizer char`` in that case.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from supplied_text import DEFAULT_SUPPLIED, extract_supplied_text


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", action="append", default=None,
                   help="Text file(s) to train on. Default: supplied embedded text.")
    p.add_argument("--supplied", action="append", default=None)
    p.add_argument("--vocab-size", type=int, default=32000)
    p.add_argument("--min-frequency", type=int, default=2)
    p.add_argument("--max-bytes", type=int, default=0)
    p.add_argument("--output", default=str(Path.home() / "meta" / "bpe32k.json"))
    p.add_argument("--meta", default=str(Path.home() / "meta" / "bpe32k_meta.json"))
    args = p.parse_args()

    try:
        from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers
    except Exception:
        print(
            "BPE-32k requires the `tokenizers` package (a Rust extension).\n"
            "On Ubuntu/GitHub Actions:  pip install tokenizers\n"
            "On Termux/Android there is no prebuilt wheel; use the char-level "
            "Stage 0 or run this step on a Linux host/container.\n"
            "The model still supports --tokenizer char for local runs.",
            file=sys.stderr,
        )
        return 2

    if args.corpus:
        text = "\n\n".join(
            Path(f).expanduser().read_text(encoding="utf-8", errors="ignore")
            for f in args.corpus
        )
    else:
        supplied = [Path(f).expanduser() for f in args.supplied] if args.supplied else DEFAULT_SUPPLIED
        text = extract_supplied_text(supplied)
    if args.max_bytes > 0:
        text = text[: args.max_bytes]
    if len(text) < 100_000:
        print(
            f"warning: corpus is only {len(text)} chars; 32k BPE will overfit. "
            "Pass --corpus with a larger sample.",
            file=sys.stderr,
        )

    tok = Tokenizer(models.BPE(unk_token="<unk>"))
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(
        vocab_size=args.vocab_size,
        min_frequency=args.min_frequency,
        special_tokens=["<pad>", "<unk>", "<s>", "</s>"],
        show_progress=True,
        initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
    )
    # Line iterator avoids materializing a second copy of a large corpus.
    def lines():
        for line in text.splitlines(keepends=True):
            if line.strip():
                yield line

    tok.train_from_iterator(lines(), trainer=trainer)
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    tok.save(str(output))
    meta = {
        "output": str(output),
        "vocab_size": tok.get_vocab_size(),
        "corpus_chars": len(text),
        "min_frequency": args.min_frequency,
        "tokenizer": "byte-level-bpe",
    }
    meta_path = Path(args.meta).expanduser()
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    print(json.dumps(meta, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
