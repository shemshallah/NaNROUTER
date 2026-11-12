#!/usr/bin/env python3
"""Frontier-trajectory LM built ONLY from the supplied Python files.

Supplied sources used here:
  * transformer_baseline_lm.py  — ALPHABET, normalize(), embedded corpus,
    the tiny causal transformer baseline shape.
  * c256_..._6gram_final.py     — 255 heads, 2 rails, 32,640 mirror pairs,
    3/4/5/6-gram counts, hierarchical backoff.
  * mirror.py / CHANGELOG       — palindromic head addresses, 85 triheads,
    head field, mirror-pair field, NaN/absence heads, two temporal rails.

No NaN* repository code, imports, data, or tooling is used.  The only corpus
used by default is the text embedded in the supplied Python files.  Pass
``--corpus`` to train on your own text.

What this file is
-----------------
Stage 0 of the scalable design:

  tokenizer (char or BPE-32k)
      -> exact smoothed n-gram memory (no ctx_embed anywhere)
      -> 255-head credit projection
      -> 85 triheads (2/3, 3/3, hot/cold)
      -> 255-head field + 32,640-pair mirror field
      -> S+/S- rail features
      -> triangle curvature + curvature codebook ("global fabric")
      -> ~10M-parameter MLP mixer with tied token embeddings
      -> next-token logits

The memory is a prior; the MLP is the trainable generalizer.  This is the
smallest honest build that can measure whether the geometry helps and whether
the path can be scaled.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

from head_geometry import (
    FIXED_TRIADS,
    TorchHeadGeometry,
    geometry_stats,
    geometry_param_count,
)
from poincare_geometry import PoincareTriheadLayer, POINCARE_OUT_DIM
from supplied_text import DEFAULT_SUPPLIED, extract_supplied_text


# ---------------------------------------------------------------------------
# Tokenizers
# ---------------------------------------------------------------------------

ALPHABET = list("abcdefghijklmnopqrstuvwxyz") + [
    " ", ".", "'", '"', ":", ";", ",", "?", "!", "(", ")", "-", "_",
]
VOCAB = sorted(ALPHABET)
VOCAB_INDEX = {ch: i for i, ch in enumerate(VOCAB)}
SPACE_ID = VOCAB_INDEX[" "]
BYTE_TO_ID = np.full(256, SPACE_ID, dtype=np.int64)
for _b in range(256):
    _ch = chr(_b)
    if "A" <= _ch <= "Z":
        _ch = _ch.lower()
    if _ch in VOCAB_INDEX:
        BYTE_TO_ID[_b] = VOCAB_INDEX[_ch]


def normalize_text(text: str) -> str:
    text = text.lower()
    return "".join(ch if ch in VOCAB_INDEX else " " for ch in text)


class CharTokenizer:
    kind = "char"

    def __init__(self):
        self.vocab_size = len(VOCAB)
        self.vocab = VOCAB

    def encode(self, text: str) -> np.ndarray:
        text = normalize_text(text)
        return np.fromiter(
            (VOCAB_INDEX[ch] for ch in text), dtype=np.int32, count=len(text)
        )

    def decode(self, ids: np.ndarray) -> str:
        return "".join(VOCAB[int(i)] for i in ids)


class ByteTokenizer:
    kind = "bytes"
    vocab_size = 256

    def encode(self, text: str) -> np.ndarray:
        return np.frombuffer(text.encode("utf-8", errors="replace"), dtype=np.uint8).astype(np.int32)

    def decode(self, ids: np.ndarray) -> str:
        return bytes(int(i) for i in ids).decode("utf-8", errors="replace")


class BPETokenizer:
    kind = "bpe"

    def __init__(self, model_path: str):
        try:
            from tokenizers import Tokenizer
        except Exception as exc:
            raise SystemExit(
                "BPE-32k needs the `tokenizers` package. Install it on the "
                "trainer host (GitHub Actions Ubuntu: pip install tokenizers)."
            ) from exc
        self._tok = Tokenizer.from_file(str(model_path))
        self.vocab_size = self._tok.get_vocab_size()
        self.vocab = None

    def encode(self, text: str) -> np.ndarray:
        return np.asarray(self._tok.encode(text).ids, dtype=np.int32)

    def decode(self, ids: np.ndarray) -> str:
        return self._tok.decode([int(i) for i in ids])


def build_tokenizer(kind: str, bpe_model: str | None):
    if kind == "char":
        return CharTokenizer()
    if kind == "bytes":
        return ByteTokenizer()
    if kind == "bpe":
        if not bpe_model:
            raise SystemExit("--tokenizer bpe requires --bpe-model tokenizer.json")
        return BPETokenizer(bpe_model)
    raise SystemExit(f"unknown tokenizer {kind!r}")


# ---------------------------------------------------------------------------
# Exact smoothed n-gram memory (no ctx_embed)
# ---------------------------------------------------------------------------


class NgramMemory:
    """Interpolated absolute-discounting n-gram memory.

    This replaces the old `ctx_emb`/prototype path.  There is no per-context
    float vector.  A context is a tuple of token ids; counts are stored in
    Python dicts for Stage 0.  The scalable version replaces these dicts with
    the set-associative hashed store described in the design note.
    """

    def __init__(self, orders: int, vocab_size: int, discount: float = 0.75, alpha: float = 0.1):
        self.orders = orders
        self.vocab_size = vocab_size
        self.discount = discount
        self.alpha = alpha
        self.counts: list[dict] = [{} for _ in range(orders + 1)]
        self.totals: list[dict] = [{} for _ in range(orders + 1)]
        self.singletons: list[dict] = [{} for _ in range(orders + 1)]
        self.unigram = np.zeros(vocab_size, dtype=np.float64)
        self.unigram_total = 0.0

    def fit(self, ids: np.ndarray) -> None:
        ids = np.asarray(ids, dtype=np.int64)
        for pos in range(1, len(ids)):
            target = int(ids[pos])
            self.unigram[target] += 1.0
            self.unigram_total += 1.0
            max_order = min(self.orders, pos)
            for order in range(1, max_order + 1):
                ctx = tuple(int(x) for x in ids[pos - order : pos])
                table = self.counts[order]
                row = table.get(ctx)
                if row is None:
                    row = {}
                    table[ctx] = row
                row[target] = row.get(target, 0) + 1
        for order in range(1, self.orders + 1):
            for ctx, row in self.counts[order].items():
                total = sum(row.values())
                self.totals[order][ctx] = total
                self.singletons[order][ctx] = sum(1 for c in row.values() if c == 1)

    def order_distributions(self, context: list[int] | tuple[int, ...]) -> np.ndarray:
        """Per-order smoothed distributions, shape (orders, vocab).

        Row o is the distribution after interpolating unigram through order o.
        Row -1 is the full interpolation used by the plain n-gram baseline.
        These rows are the candidate experts for geometry-routed memory.
        """
        v = self.vocab_size
        if self.unigram_total <= 0:
            base = np.full(v, 1.0 / v, dtype=np.float64)
        else:
            base = (self.unigram + self.alpha) / (self.unigram_total + self.alpha * v)
        context = tuple(int(x) for x in context)
        rows: list[np.ndarray] = []
        p = base
        for order in range(1, self.orders + 1):
            if len(context) >= order:
                ctx = context[-order:]
                row = self.counts[order].get(ctx)
                if row:
                    total = self.totals[order][ctx]
                    n1 = self.singletons[order][ctx]
                    d = self.discount
                    seen = np.zeros(v, dtype=np.float64)
                    for tok, count in row.items():
                        seen[tok] = max(count - d, 0.0) / total
                    p = seen + (d * n1 / total) * p
            rows.append(np.maximum(p, 1e-12))
        out = np.stack(rows, axis=0)
        return out / out.sum(axis=1, keepdims=True)

    def distribution(self, context: list[int] | tuple[int, ...]) -> np.ndarray:
        """Dense interpolated next-token distribution for one context."""
        return self.order_distributions(context)[-1]

    def features(self, context: list[int] | tuple[int, ...]) -> np.ndarray:
        """Compact scalar features for the mixer."""
        context = tuple(int(x) for x in context)
        feats: list[float] = []
        depth = 0
        for order in range(1, self.orders + 1):
            if len(context) < order:
                feats.extend([0.0, 0.0, 0.0, 0.0])
                continue
            ctx = context[-order:]
            row = self.counts[order].get(ctx)
            if not row:
                feats.extend([0.0, 0.0, 0.0, 0.0])
                continue
            depth = order
            total = self.totals[order][ctx]
            n1 = self.singletons[order][ctx]
            top = max(row.values()) / total
            probs = np.array([c / total for c in row.values()], dtype=np.float64)
            entropy = float(-(probs * np.log2(probs + 1e-12)).sum())
            feats.extend([top, entropy, n1 / max(1, len(row)), 1.0])
        p = self.distribution(context)
        top = float(p.max())
        entropy = float(-(p * np.log2(p + 1e-12)).sum())
        feats.extend([top, entropy, depth / self.orders])
        return np.asarray(feats, dtype=np.float32)

    @property
    def feature_dim(self) -> int:
        return self.orders * 4 + 3

    def dense_bias(self, context: list[int] | tuple[int, ...]) -> np.ndarray:
        """Full interpolation log-probs (kept for the non-routed baseline)."""
        p = self.distribution(context)
        return np.log(p + 1e-9).astype(np.float32)

    def order_bias(self, context: list[int] | tuple[int, ...]) -> np.ndarray:
        """Per-order log-probs, shape (orders, vocab)."""
        p = self.order_distributions(context)
        return np.log(p + 1e-9).astype(np.float32)

    def hard_predict(self, context: list[int] | tuple[int, ...]) -> tuple[int, int]:
        """Longest-covered-order argmax; the c256 hard-backoff baseline."""
        context = tuple(int(x) for x in context)
        for order in range(min(self.orders, len(context)), 0, -1):
            row = self.counts[order].get(context[-order:])
            if row:
                return int(max(row, key=row.get)), order
        return int(np.argmax(self.unigram)), 0


# ---------------------------------------------------------------------------
# ~10M-parameter mixer
# ---------------------------------------------------------------------------


@dataclass
class ModelConfig:
    vocab_size: int
    ctx: int
    d_model: int = 256
    hidden: int = 1024
    layers: int = 2
    geom_dim: int = 147
    mem_dim: int = 35
    orders: int = 8
    use_geometry: bool = True
    use_poincare: bool = True
    use_memory: bool = True
    use_prev: bool = True
    use_order_gate: bool = True
    trunk_layers: int = 0
    trunk_heads: int = 4
    trunk_ff: int = 1024


class CausalBlock(nn.Module):
    """Pre-LN causal self-attention + MLP block."""

    def __init__(self, d_model: int, n_heads: int, ff_dim: int, dropout: float, ctx: int):
        super().__init__()
        self.ln1 = nn.LayerNorm(d_model)
        self.attn = nn.MultiheadAttention(
            d_model, n_heads, dropout=dropout, batch_first=True
        )
        self.ln2 = nn.LayerNorm(d_model)
        self.ff1 = nn.Linear(d_model, ff_dim)
        self.ff2 = nn.Linear(ff_dim, d_model)
        self.drop = nn.Dropout(dropout)
        mask = torch.triu(torch.ones(ctx, ctx, dtype=torch.bool), diagonal=1)
        self.register_buffer("causal_mask", mask, persistent=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.ln1(x)
        a, _ = self.attn(
            h, h, h, attn_mask=self.causal_mask, need_weights=False
        )
        x = x + self.drop(a)
        h = self.ln2(x)
        h = self.ff2(self.drop(F.gelu(self.ff1(h))))
        return x + h


class CausalTrunk(nn.Module):
    def __init__(
        self, d_model: int, n_layers: int, n_heads: int, ff_dim: int,
        dropout: float, ctx: int,
    ):
        super().__init__()
        self.blocks = nn.ModuleList(
            [
                CausalBlock(d_model, n_heads, ff_dim, dropout, ctx)
                for _ in range(n_layers)
            ]
        )
        self.ln_f = nn.LayerNorm(d_model)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        for block in self.blocks:
            x = block(x)
        return self.ln_f(x)


def build_mixer(input_dim: int, hidden: int, layers: int, out_dim: int) -> nn.Sequential:
    blocks: list[nn.Module] = []
    dim = input_dim
    for _ in range(layers):
        blocks.extend(
            [
                nn.Linear(dim, hidden),
                nn.GELU(),
                nn.LayerNorm(hidden),
            ]
        )
        dim = hidden
    blocks.append(nn.Linear(dim, out_dim))
    return nn.Sequential(*blocks)


class FrontierLM(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.cfg = cfg
        self.tok = nn.Embedding(cfg.vocab_size, cfg.d_model)
        self.pos = nn.Embedding(cfg.ctx, cfg.d_model)
        self.head_proj = nn.Linear(cfg.d_model, 255) if (cfg.use_geometry or cfg.use_poincare) else None
        self.geometry = TorchHeadGeometry() if cfg.use_geometry else None
        self.poincare = PoincareTriheadLayer() if cfg.use_poincare else None
        self.mem_proj = nn.Linear(cfg.mem_dim, cfg.d_model) if cfg.use_memory else None
        self.prev_proj = nn.Linear(cfg.d_model, cfg.d_model) if cfg.use_prev else None
        self.trunk = (
            CausalTrunk(
                cfg.d_model, cfg.trunk_layers, cfg.trunk_heads,
                cfg.trunk_ff, 0.1, cfg.ctx,
            )
            if cfg.trunk_layers > 0
            else None
        )
        geom_dim = (129 if cfg.use_geometry else 0) + (POINCARE_OUT_DIM if cfg.use_poincare else 0)
        mem_dim = cfg.d_model if cfg.use_memory else 0
        gate_dim = geom_dim if geom_dim > 0 else cfg.d_model
        self.order_gate = (
            nn.Linear(gate_dim, cfg.orders)
            if cfg.use_memory and cfg.use_order_gate
            else None
        )
        self.mixer = build_mixer(
            cfg.d_model + geom_dim + mem_dim,
            cfg.hidden,
            cfg.layers,
            cfg.d_model,
        )
        self.apply(self._init)
        nn.init.normal_(self.tok.weight, mean=0.0, std=0.02)
        nn.init.normal_(self.pos.weight, mean=0.0, std=0.02)
        if self.order_gate is not None:
            nn.init.zeros_(self.order_gate.weight)
            nn.init.zeros_(self.order_gate.bias)

    @staticmethod
    def _init(module: nn.Module) -> None:
        if isinstance(module, nn.Linear):
            nn.init.xavier_uniform_(module.weight)
            if module.bias is not None:
                nn.init.zeros_(module.bias)

    def forward(self, tokens: torch.Tensor, mem_feat: torch.Tensor, mem_bias: torch.Tensor):
        b, t = tokens.shape
        pos = torch.arange(t, device=tokens.device).unsqueeze(0)
        x = self.tok(tokens) + self.pos(pos)
        if self.trunk is not None:
            x = self.trunk(x)
        h = x[:, -1, :]
        parts = [h]
        geom_parts: list[torch.Tensor] = []
        aux: dict[str, torch.Tensor] = {}
        credits = None
        if self.head_proj is not None:
            credits = self.head_proj(h)
        if self.geometry is not None:
            geom = self.geometry(credits)
            parts.append(geom)
            geom_parts.append(geom)
            aux["field_quorum"] = geom[:, 15].mean()
            aux["head_curvature_mean"] = geom[:, 20].mean()
        if self.poincare is not None:
            pgeom, paux = self.poincare(credits)
            parts.append(pgeom)
            geom_parts.append(pgeom)
            aux.update(paux)
        if self.mem_proj is not None:
            parts.append(self.mem_proj(mem_feat))
        if self.order_gate is not None:
            gate_input = torch.cat(geom_parts, dim=1) if geom_parts else h
            order_w = F.softmax(self.order_gate(gate_input), dim=-1)  # (B,orders)
            mem_bias = torch.einsum("bo,bov->bv", order_w, mem_bias)
            aux["order_weights"] = order_w.mean(dim=0)
        else:
            mem_bias = mem_bias[:, -1, :]
        z = torch.cat(parts, dim=1)
        z = self.mixer(z)
        logits = z @ self.tok.weight.T
        if self.mem_proj is not None:
            logits = logits + mem_bias
        prev_logits = None
        if self.prev_proj is not None:
            prev_logits = (self.prev_proj(z)) @ self.tok.weight.T
        return logits, prev_logits, aux


def parameter_count(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


def choose_profile(vocab_size: int, requested: str) -> tuple[int, int, int, int, int, int]:
    """Return d_model, mixer_hidden, mixer_layers, trunk_layers, heads, ff."""
    if requested == "small":
        return 128, 512, 2, 1, 4, 512
    # ~10M total with tied embeddings (vocab * d_model is the dominant term).
    if vocab_size >= 4096:
        return 224, 512, 2, 2, 4, 896
    return 256, 2048, 3, 2, 4, 1024


# ---------------------------------------------------------------------------
# Data and batches
# ---------------------------------------------------------------------------


@dataclass
class PreparedData:
    ids: np.ndarray
    train_end: int
    val_start: int
    ctx: int
    tokenizer_kind: str


def prepare_data(text: str, tokenizer, ctx: int, max_bytes: int, train_fraction: float = 0.8) -> PreparedData:
    if max_bytes > 0:
        text = text[:max_bytes]
    ids = tokenizer.encode(text)
    if len(ids) < ctx + 64:
        raise SystemExit(f"corpus too small: {len(ids)} tokens, need at least {ctx + 64}")
    split = int(len(ids) * train_fraction)
    split = max(ctx + 32, min(split, len(ids) - 64))
    return PreparedData(ids=ids, train_end=split, val_start=split, ctx=ctx, tokenizer_kind=tokenizer.kind)


class MemoryBank:
    """Precomputed memory features/bias for char/bytes; on-the-fly for BPE."""

    def __init__(self, memory: NgramMemory, data: PreparedData, mode: str):
        self.memory = memory
        self.data = data
        self.mode = mode
        self.cache: dict[tuple[int, ...], tuple[np.ndarray, np.ndarray]] = {}
        self.max_cache = 200_000 if memory.vocab_size <= 256 else 256

    def at(self, pos: int) -> tuple[np.ndarray, np.ndarray]:
        ctx = tuple(int(x) for x in self.data.ids[max(0, pos - self.memory.orders) : pos])
        key = ctx
        cached = self.cache.get(key)
        if cached is None:
            feats = self.memory.features(ctx)
            bias = self.memory.order_bias(ctx)
            cached = (feats, bias)
            if len(self.cache) < self.max_cache:
                self.cache[key] = cached
        return cached


def make_batch(
    data: PreparedData,
    bank: MemoryBank,
    batch_size: int,
    rng: np.random.Generator,
    train: bool = True,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    ctx = data.ctx
    lo = ctx
    hi = data.train_end if train else len(data.ids) - 1
    if not train:
        lo = max(data.val_start, ctx)
    positions = rng.integers(lo, hi, size=batch_size)
    xs = np.stack([data.ids[p - ctx : p] for p in positions]).astype(np.int64)
    ys = np.array([data.ids[p] for p in positions], dtype=np.int64)
    prev_pos = positions - ctx - 1
    valid = prev_pos >= 0
    y_prev = np.zeros(batch_size, dtype=np.int64)
    y_prev[valid] = data.ids[prev_pos[valid]]
    prev_mask = valid.astype(np.float32)
    mem_feats = []
    mem_biases = []
    for p in positions:
        f, b = bank.at(int(p))
        mem_feats.append(f)
        mem_biases.append(b)
    return (
        torch.from_numpy(xs),
        torch.from_numpy(ys),
        torch.from_numpy(y_prev),
        torch.from_numpy(prev_mask),
        torch.from_numpy(np.stack(mem_feats)),
        torch.from_numpy(np.stack(mem_biases)),
    )


def eval_batches(
    data: PreparedData,
    bank: MemoryBank,
    batch_size: int,
    max_batches: int,
    seed: int = 1234,
):
    rng = np.random.default_rng(seed)
    lo = max(data.val_start, data.ctx)
    hi = len(data.ids) - 1
    if hi <= lo:
        return
    for _ in range(max_batches):
        positions = rng.integers(lo, hi, size=batch_size)
        xs = np.stack([data.ids[p - data.ctx : p] for p in positions]).astype(np.int64)
        ys = np.array([data.ids[p] for p in positions], dtype=np.int64)
        prev_pos = positions - data.ctx - 1
        valid = prev_pos >= 0
        y_prev = np.zeros(batch_size, dtype=np.int64)
        y_prev[valid] = data.ids[prev_pos[valid]]
        prev_mask = valid.astype(np.float32)
        mem_feats = []
        mem_biases = []
        for p in positions:
            f, b = bank.at(int(p))
            mem_feats.append(f)
            mem_biases.append(b)
        yield (
            torch.from_numpy(xs),
            torch.from_numpy(ys),
            torch.from_numpy(y_prev),
            torch.from_numpy(prev_mask),
            torch.from_numpy(np.stack(mem_feats)),
            torch.from_numpy(np.stack(mem_biases)),
        )


# ---------------------------------------------------------------------------
# Training / evaluation
# ---------------------------------------------------------------------------


def bits_per_token(loss: float) -> float:
    return loss / math.log(2.0)


def save_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def evaluate(
    model: FrontierLM,
    data: PreparedData,
    bank: MemoryBank,
    batch_size: int,
    max_batches: int,
    device: torch.device,
) -> dict:
    model.eval()
    total_loss = 0.0
    total_correct = 0
    total_prev = 0
    total_prev_correct = 0
    mem_correct = 0
    total = 0
    quorum = []
    curvature = []
    mirror = []
    hyp = []
    with torch.no_grad():
        for x, y, yp, pm, mf, mb in eval_batches(data, bank, batch_size, max_batches):
            x, y, yp, pm, mf, mb = (
                x.to(device), y.to(device), yp.to(device),
                pm.to(device), mf.to(device), mb.to(device),
            )
            logits, prev_logits, aux = model(x, mf, mb)
            loss = F.cross_entropy(logits, y, reduction="sum")
            total_loss += float(loss)
            total_correct += int((logits.argmax(dim=-1) == y).sum())
            mem_correct += int((mb[:, -1, :].argmax(dim=-1) == y).sum())
            total += y.numel()
            if prev_logits is not None and pm.sum() > 0:
                mask = pm.bool()
                total_prev_correct += int(
                    (prev_logits[mask].argmax(dim=-1) == yp[mask]).sum()
                )
                total_prev += int(mask.sum())
            if "field_quorum" in aux:
                quorum.append(float(aux["field_quorum"]))
            if "curvature_mean" in aux:
                curvature.append(float(aux["curvature_mean"]))
            if "mirror_loss" in aux:
                mirror.append(float(aux["mirror_loss"]))
            if "hyp_mean" in aux:
                hyp.append(float(aux["hyp_mean"]))
    model.train()
    return {
        "loss": total_loss / max(1, total),
        "bits_per_token": bits_per_token(total_loss / max(1, total)),
        "accuracy": total_correct / max(1, total),
        "prev_accuracy": total_prev_correct / max(1, total_prev) if total_prev else None,
        "memory_accuracy": mem_correct / max(1, total),
        "field_quorum": float(np.mean(quorum)) if quorum else None,
        "curvature_mean": float(np.mean(curvature)) if curvature else None,
        "mirror_loss": float(np.mean(mirror)) if mirror else None,
        "hyp_mean": float(np.mean(hyp)) if hyp else None,
        "tokens": total,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["ngram", "hybrid"], default="hybrid")
    p.add_argument("--corpus", action="append", default=None,
                   help="Your own text file(s). Default: text embedded in supplied Python.")
    p.add_argument("--supplied", action="append", default=None,
                   help="Supplied Python file(s) to extract embedded text from.")
    p.add_argument("--tokenizer", choices=["char", "bytes", "bpe"], default="char")
    p.add_argument("--bpe-model", default=None)
    p.add_argument("--orders", type=int, default=6)
    p.add_argument("--discount", type=float, default=0.75)
    p.add_argument("--train-fraction", type=float, default=0.8)
    p.add_argument("--ctx", type=int, default=32)
    p.add_argument("--max-bytes", type=int, default=0)
    p.add_argument("--steps", type=int, default=3000)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--eval-every", type=int, default=250)
    p.add_argument("--eval-batches", type=int, default=8)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--warmup", type=int, default=100)
    p.add_argument("--grad-clip", type=float, default=1.0)
    p.add_argument("--params", choices=["small", "10m"], default="10m")
    p.add_argument("--trunk-layers", type=int, default=-1,
                   help="-1 uses the profile default; 0 disables the attention trunk")
    p.add_argument("--trunk-heads", type=int, default=4)
    p.add_argument("--trunk-ff", type=int, default=-1)
    p.add_argument("--no-routed-memory", action="store_true")
    p.add_argument("--no-geometry", action="store_true")
    p.add_argument("--no-poincare", action="store_true")
    p.add_argument("--no-prev", action="store_true")
    p.add_argument("--prev-weight", type=float, default=0.5)
    p.add_argument("--recluster-every", type=int, default=500)
    p.add_argument("--aux-mirror", type=float, default=0.05)
    p.add_argument("--aux-load", type=float, default=0.01)
    p.add_argument("--aux-curv", type=float, default=1e-4)
    p.add_argument("--no-memory", action="store_true")
    p.add_argument("--seed", type=int, default=3)
    p.add_argument("--threads", type=int, default=0)
    p.add_argument("--device", default="cpu")
    p.add_argument("--checkpoint", default=str(Path.home() / "meta" / "frontier_ckpt.pt"))
    p.add_argument("--summary", default=str(Path.home() / "meta" / "frontier_summary.json"))
    p.add_argument("--log", default=str(Path.home() / "meta" / "frontier_metrics.jsonl"))
    p.add_argument("--resume", default="none", help="none | path")
    args = p.parse_args()

    if args.threads <= 0:
        args.threads = min(8, os.cpu_count() or 1)
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    device = torch.device(args.device)

    if args.corpus:
        text = "\n\n".join(Path(f).expanduser().read_text(encoding="utf-8", errors="ignore") for f in args.corpus)
    else:
        supplied = [Path(f).expanduser() for f in args.supplied] if args.supplied else DEFAULT_SUPPLIED
        text = extract_supplied_text(supplied)
    tokenizer = build_tokenizer(args.tokenizer, args.bpe_model)
    data = prepare_data(text, tokenizer, args.ctx, args.max_bytes, args.train_fraction)
    print(f"[data] {data.tokenizer_kind} tokens={len(data.ids)} train_end={data.train_end} val_start={data.val_start} vocab={tokenizer.vocab_size}")

    memory = NgramMemory(args.orders, tokenizer.vocab_size, args.discount)
    train_ids = data.ids[: data.train_end]
    print(f"[memory] fitting orders 1..{args.orders} on {len(train_ids)} train tokens")
    t0 = time.time()
    memory.fit(train_ids)
    print(f"[memory] fit in {time.time() - t0:.1f}s; total contexts="
          f"{sum(len(memory.counts[o]) for o in range(1, args.orders + 1))}")
    bank = MemoryBank(memory, data, args.mode)

    if args.mode == "ngram":
        # Direct memory-only evaluation; no model and no ctx_embed.
        total = 0
        correct = 0
        hard_correct = 0
        used_orders: list[int] = []
        loss = 0.0
        rng = np.random.default_rng(args.seed)
        lo, hi = max(data.val_start, data.ctx), len(data.ids) - 1
        for _ in range(max(1, args.eval_batches)):
            positions = rng.integers(lo, hi, size=args.batch_size)
            for p in positions:
                p = int(p)
                context = tuple(int(x) for x in data.ids[max(0, p - memory.orders) : p])
                bias = bank.at(p)[1][-1]
                target = int(data.ids[p])
                correct += int(np.argmax(bias) == target)
                pred, used = memory.hard_predict(context)
                hard_correct += int(pred == target)
                used_orders.append(used)
                loss += -float(bias[target])
                total += 1
        summary = {
            "mode": "ngram",
            "orders": args.orders,
            "tokens": total,
            "loss": loss / total,
            "bits_per_token": bits_per_token(loss / total),
            "accuracy": correct / total,
            "hard_backoff_accuracy": hard_correct / total,
            "mean_used_order": float(np.mean(used_orders)),
            "vocab_size": tokenizer.vocab_size,
            "train_tokens": int(data.train_end),
            "val_tokens": int(len(data.ids) - data.val_start),
        }
        save_json(Path(args.summary).expanduser(), summary)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    d_model, hidden, layers, prof_trunk_layers, prof_trunk_heads, prof_trunk_ff = choose_profile(
        tokenizer.vocab_size, args.params
    )
    trunk_layers = prof_trunk_layers if args.trunk_layers < 0 else args.trunk_layers
    trunk_heads = prof_trunk_heads if args.trunk_heads <= 0 else args.trunk_heads
    trunk_ff = prof_trunk_ff if args.trunk_ff <= 0 else args.trunk_ff
    use_poincare = (not args.no_geometry) and (not args.no_poincare)
    use_prev = not args.no_prev
    geom_dim = (129 if not args.no_geometry else 0) + (POINCARE_OUT_DIM if use_poincare else 0)
    cfg = ModelConfig(
        vocab_size=tokenizer.vocab_size,
        ctx=args.ctx,
        d_model=d_model,
        hidden=hidden,
        layers=layers,
        geom_dim=geom_dim,
        mem_dim=memory.feature_dim if not args.no_memory else 0,
        orders=args.orders,
        use_geometry=not args.no_geometry,
        use_poincare=use_poincare,
        use_memory=not args.no_memory,
        use_prev=use_prev,
        use_order_gate=not args.no_routed_memory,
        trunk_layers=trunk_layers,
        trunk_heads=trunk_heads,
        trunk_ff=trunk_ff,
    )
    model = FrontierLM(cfg).to(device)
    print(f"[model] params={parameter_count(model):,} d_model={d_model} hidden={hidden} "
          f"layers={layers} trunk={trunk_layers}x{trunk_heads} ff={trunk_ff} "
          f"geom={cfg.use_geometry} poincare={cfg.use_poincare} "
          f"prev={cfg.use_prev} routed_memory={cfg.use_order_gate} memory={cfg.use_memory}")
    if cfg.use_geometry:
        print(f"[model] geometry params={geometry_param_count():,}")

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    start_step = 0
    if args.resume != "none":
        ckpt = torch.load(Path(args.resume).expanduser(), map_location=device, weights_only=False)
        model.load_state_dict(ckpt["model"])
        optimizer.load_state_dict(ckpt["optimizer"])
        start_step = int(ckpt.get("step", 0))
        print(f"[resume] step {start_step}")

    log_path = Path(args.log).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed + start_step)
    t0 = time.time()
    ema = None
    model.train()
    for step in range(start_step, args.steps):
        x, y, yp, pm, mf, mb = make_batch(data, bank, args.batch_size, rng, train=True)
        x, y, yp, pm, mf, mb = (
            x.to(device), y.to(device), yp.to(device),
            pm.to(device), mf.to(device), mb.to(device),
        )
        lr = args.lr * min(1.0, (step + 1) / max(1, args.warmup))
        if step > args.warmup:
            progress = (step - args.warmup) / max(1, args.steps - args.warmup)
            lr = args.lr * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(1.0, progress))))
        for g in optimizer.param_groups:
            g["lr"] = lr
        optimizer.zero_grad(set_to_none=True)
        logits, prev_logits, aux = model(x, mf, mb)
        loss = F.cross_entropy(logits, y)
        if prev_logits is not None and pm.sum() > 0:
            mask = pm.bool()
            loss = loss + args.prev_weight * F.cross_entropy(prev_logits[mask], yp[mask])
        zero = torch.zeros((), device=device)
        loss = loss + args.aux_mirror * aux.get("mirror_loss", zero)
        loss = loss + args.aux_load * aux.get("load_balance", zero)
        loss = loss + args.aux_curv * aux.get("curv_reg", zero)
        loss.backward()
        if args.grad_clip > 0:
            torch.nn.utils.clip_grad_norm_(model.parameters(), args.grad_clip)
        optimizer.step()
        if (
            model.poincare is not None
            and args.recluster_every > 0
            and (step + 1) % args.recluster_every == 0
        ):
            model.poincare.recluster()
            print(f"  [poincare] re-clustered triheads at step {step + 1}")
        lv = float(loss.detach())
        ema = lv if ema is None else 0.98 * ema + 0.02 * lv
        if (step + 1) % 50 == 0:
            record = {
                "event": "train",
                "step": step + 1,
                "loss": lv,
                "ema_loss": ema,
                "bits_per_token": bits_per_token(lv),
                "lr": lr,
                "elapsed": time.time() - t0,
            }
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
            print(f"step {step + 1:6d}/{args.steps} loss={lv:.4f} bits={bits_per_token(lv):.3f} lr={lr:.2e}")
        if (step + 1) % args.eval_every == 0 or step + 1 == args.steps:
            metrics = evaluate(model, data, bank, args.batch_size, args.eval_batches, device)
            record = {"event": "eval", "step": step + 1, **metrics, "elapsed": time.time() - t0}
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
            print(f"  EVAL step {step + 1}: loss={metrics['loss']:.4f} "
                  f"bits={metrics['bits_per_token']:.3f} acc={metrics['accuracy']*100:.2f}% "
                  f"prev={metrics['prev_accuracy']} mem_acc={metrics['memory_accuracy']*100:.2f}% "
                  f"quorum={metrics['field_quorum']} curv={metrics['curvature_mean']} "
                  f"mirror={metrics['mirror_loss']}")
            torch.save(
                {"model": model.state_dict(), "optimizer": optimizer.state_dict(),
                 "step": step + 1, "config": cfg.__dict__},
                Path(args.checkpoint).expanduser(),
            )

    final = evaluate(model, data, bank, args.batch_size, args.eval_batches, device)
    summary = {
        "mode": "hybrid",
        "params": parameter_count(model),
        "vision_params": geometry_param_count() if cfg.use_geometry else 0,
        "poincare_params": sum(p.numel() for p in model.poincare.parameters()) if model.poincare is not None else 0,
        "config": cfg.__dict__,
        "final": final,
        "steps": args.steps,
        "elapsed_seconds": time.time() - t0,
        "tokenizer": tokenizer.kind,
        "vocab_size": tokenizer.vocab_size,
        "train_tokens": int(data.train_end),
        "val_tokens": int(len(data.ids) - data.val_start),
        "orders": args.orders,
        "geometry": cfg.use_geometry,
        "poincare": cfg.use_poincare,
        "prev": cfg.use_prev,
        "memory": cfg.use_memory,
    }
    save_json(Path(args.summary).expanduser(), summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
