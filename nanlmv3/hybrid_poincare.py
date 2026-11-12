#!/usr/bin/env python3
"""Hybrid of the new poincare.py v23 and the nanlmv3 geometry stack.

From the new poincare.py:
  * deterministic 4-branch chain curriculum (branching 4, CTX 16)
  * last-token + attended-context representation
  * hyperbolic branch gate (4 Poincare centroids)
  * 256 experts arranged as 128 mirror pairs, top-8 routing, load balance
  * two MoE layers, gradient training, 90% accuracy gate

From nanlmv3:
  * 255 head credits -> 85 triheads -> head field / mirror-pair field
  * S+/S- rails, triangle curvature, curvature codebook
  * Poincare-disk trihead clustering, curvature/polarity/hot routing
  * geometry features used as a learned bias on the MoE expert gates

No NaN* repository code is used.  The only external inputs are this file and
the two geometry modules in the same directory.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

from head_geometry import TorchHeadGeometry
from poincare_geometry import PoincareTriheadLayer, POINCARE_OUT_DIM

# ---------------------------------------------------------------------------
# v23 deterministic 4-branch curriculum
# ---------------------------------------------------------------------------

CHAIN_A = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf",
           "hotel", "india", "juliet", "kilo", "lima", "mike", "november", "oscar"]
CHAIN_B = ["apple", "banana", "cherry", "date", "elder", "fig", "grape",
           "honey", "iris", "jasmine", "kiwi", "lemon", "mango", "nectar", "orange"]
CHAIN_C = ["cat", "dog", "bird", "fish", "horse", "cow", "pig",
           "sheep", "goat", "duck", "hen", "frog", "mouse", "bear", "wolf"]
CHAIN_D = ["red", "blue", "green", "yellow", "purple", "coral", "pink",
           "brown", "black", "white", "gray", "silver", "gold", "bronze", "copper"]
MIDS = ["midone", "midtwo", "midthree", "midfour", "midfive"]
CHAINS = [CHAIN_A, CHAIN_B, CHAIN_C, CHAIN_D]


def build_sentences(n_sents: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    out: list[str] = []
    for i in range(n_sents):
        chain = CHAINS[i % 4] if i < 4 else rng.choice(CHAINS)
        toks = [chain[0]]
        mid_idx = 0
        chain_idx = 1
        for j in range(19):
            if j % 2 == 0:
                toks.append(MIDS[mid_idx % len(MIDS)])
                mid_idx += 1
            else:
                toks.append(chain[chain_idx % len(chain)])
                chain_idx += 1
        out.append(" ".join(toks) + " .")
    return out


def build_vocab(sentences: list[str]) -> tuple[dict[str, int], list[str]]:
    words = sorted({w for s in sentences for w in s.split()})
    return {w: i for i, w in enumerate(words)}, words


def encode_sentences(sentences: list[str], vocab: dict[str, int], ctx: int):
    xs: list[list[int]] = []
    ys: list[int] = []
    for s in sentences:
        ids = [vocab.get(w, 0) for w in s.split()]
        for i in range(ctx, len(ids)):
            xs.append(ids[i - ctx : i])
            ys.append(ids[i])
    return np.asarray(xs, dtype=np.int64), np.asarray(ys, dtype=np.int64)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class PairMoE(nn.Module):
    """128 mirror pairs, top-K routing, pos-minus-neg expert output."""

    def __init__(self, d_in: int, d_hidden: int, n_pairs: int = 128, topk: int = 8):
        super().__init__()
        self.n_pairs = n_pairs
        self.topk = topk
        self.gate = nn.Linear(d_in, n_pairs)
        self.pos = nn.Parameter(torch.randn(n_pairs, d_in, d_hidden) * 0.02)
        self.neg = nn.Parameter(torch.randn(n_pairs, d_in, d_hidden) * 0.02)

    def forward(self, x: torch.Tensor, geom_bias: torch.Tensor | None = None):
        logits = self.gate(x)
        if geom_bias is not None:
            logits = logits + geom_bias
        probs = F.softmax(logits, dim=-1)
        topv, topi = torch.topk(logits, k=min(self.topk, self.n_pairs), dim=-1)
        w = F.softmax(topv, dim=-1)
        pos = self.pos[topi]  # (B,K,d_in,d_hidden)
        neg = self.neg[topi]
        h_pos = torch.einsum("bd,bkdh->bkh", x, pos)
        h_neg = torch.einsum("bd,bkdh->bkh", x, neg)
        h = h_pos - h_neg
        out = torch.einsum("bk,bkh->bh", w, h)
        # Switch-style load balance.
        mask = torch.zeros_like(logits).scatter_(1, topi, 1.0)
        f = mask.mean(dim=0)
        p = probs.mean(dim=0)
        lb = self.n_pairs * (f * p).sum()
        return out, lb


class HybridPoincareLM(nn.Module):
    def __init__(self, vocab: int, ctx: int, d_model: int = 64, d_hidden: int = 64,
                 n_pairs: int = 128, topk: int = 8, dropout: float = 0.1):
        super().__init__()
        self.ctx = ctx
        self.tok = nn.Embedding(vocab, d_model)
        self.pos = nn.Embedding(ctx, d_model)
        self.attn_score = nn.Linear(d_model, 1)
        self.ctx_proj = nn.Linear(2 * d_model, d_model)
        self.branch_proj = nn.Linear(d_model, 8)
        self.centroids = nn.Parameter(torch.zeros(4, 8))
        with torch.no_grad():
            self.centroids[0, 0] = 0.5
            self.centroids[1, 1] = 0.5
            self.centroids[2, 0] = -0.5
            self.centroids[3, 1] = -0.5
        self.router = nn.Linear(d_model + 4, d_model)

        # Geometry stack.
        self.head_proj = nn.Linear(d_model, 255)
        self.geom = TorchHeadGeometry()
        self.pgeom = PoincareTriheadLayer()
        geom_dim = 129 + POINCARE_OUT_DIM
        self.geom_bias1 = nn.Linear(geom_dim, n_pairs)
        self.geom_bias2 = nn.Linear(geom_dim, n_pairs)

        # Mirror-pair MoE.
        self.moe1 = PairMoE(d_model, d_hidden, n_pairs, topk)
        self.moe2 = PairMoE(d_model, d_hidden, n_pairs, topk)
        self.res1 = nn.Linear(d_hidden, d_model)
        self.ln1 = nn.LayerNorm(d_model)
        self.ln2 = nn.LayerNorm(d_model)
        self.out = nn.Linear(d_hidden, vocab)
        self.drop = nn.Dropout(dropout)
        self.apply(self._init)
        nn.init.normal_(self.tok.weight, mean=0.0, std=0.02)
        nn.init.normal_(self.pos.weight, mean=0.0, std=0.02)
        for gate in (self.geom_bias1, self.geom_bias2):
            nn.init.zeros_(gate.weight)
            nn.init.zeros_(gate.bias)

    @staticmethod
    def _init(m: nn.Module) -> None:
        if isinstance(m, nn.Linear):
            nn.init.xavier_uniform_(m.weight)
            if m.bias is not None:
                nn.init.zeros_(m.bias)

    def hyperbolic_branch(self, ctx_vec: torch.Tensor) -> torch.Tensor:
        u = torch.tanh(self.branch_proj(ctx_vec)) * 0.95
        c = self.centroids
        u2 = (u * u).sum(dim=-1, keepdim=True)
        c2 = (c * c).sum(dim=-1)
        diff2 = ((u[:, None, :] - c[None, :, :]) ** 2).sum(dim=-1)
        denom = torch.clamp((1 - u2) * (1 - c2)[None, :], min=1e-6)
        arg = torch.clamp(1 + 2 * diff2 / denom, min=1.0)
        dist = torch.acosh(arg)
        return F.softmax(-dist, dim=-1)

    def forward(self, tokens: torch.Tensor):
        b, t = tokens.shape
        e = self.tok(tokens) + self.pos(torch.arange(t, device=tokens.device).unsqueeze(0))
        # Last token + attended context (v23).
        scores = self.attn_score(self.drop(e)).squeeze(-1)
        attn = F.softmax(scores, dim=-1)
        attended = torch.einsum("bt,btd->bd", attn, e)
        ctx_vec = F.relu(self.ctx_proj(torch.cat([e[:, -1, :], attended], dim=-1)))
        branch = self.hyperbolic_branch(ctx_vec)
        routed = F.relu(self.router(torch.cat([ctx_vec, branch], dim=-1)))

        # Geometry features: heads -> triheads -> fields -> rails -> curvature,
        # plus the Poincare trihead branch.
        credits = self.head_proj(ctx_vec)
        geom_feats = self.geom(credits)
        pgeom_feats, paux = self.pgeom(credits)
        g = torch.cat([geom_feats, pgeom_feats], dim=-1)
        gb1 = self.geom_bias1(g)
        gb2 = self.geom_bias2(g)

        h1, lb1 = self.moe1(routed, gb1)
        h1 = self.ln1(routed + self.res1(self.drop(h1)))
        h2, lb2 = self.moe2(h1, gb2)
        h2 = self.ln2(h1 + self.drop(h2))
        logits = self.out(h2)
        aux = {
            "load_balance": lb1 + lb2,
            "mirror_loss": paux["mirror_loss"],
            "geom_load": paux["load_balance"],
            "curv_reg": paux["curv_reg"],
            "branch_mean": branch.mean(dim=0),
        }
        return logits, aux


# ---------------------------------------------------------------------------
# Train / eval
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sentences", type=int, default=1000)
    p.add_argument("--ctx", type=int, default=16)
    p.add_argument("--epochs", type=int, default=50)
    p.add_argument("--batch-size", type=int, default=128)
    p.add_argument("--lr", type=float, default=3e-3)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--dropout", type=float, default=0.1)
    p.add_argument("--d-model", type=int, default=64)
    p.add_argument("--d-hidden", type=int, default=64)
    p.add_argument("--pairs", type=int, default=128)
    p.add_argument("--topk", type=int, default=8)
    p.add_argument("--seed", type=int, default=3)
    p.add_argument("--target-accuracy", type=float, default=90.0)
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    p.add_argument("--amp", action="store_true", default=True)
    p.add_argument("--out", default="/kaggle/working" if Path("/kaggle/working").exists() else ".")
    args = p.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_float32_matmul_precision("high")
    device = torch.device(args.device)
    amp = bool(args.amp and device.type == "cuda")
    scaler = torch.amp.GradScaler("cuda") if amp else None

    sentences = build_sentences(args.sentences, seed=99)
    rng = random.Random(42)
    rng.shuffle(sentences)
    n_test = max(20, int(len(sentences) * 0.2))
    test_sents = sentences[:n_test]
    train_sents = sentences[n_test:]
    vocab, vocab_list = build_vocab(sentences)
    x_train, y_train = encode_sentences(train_sents, vocab, args.ctx)
    x_test, y_test = encode_sentences(test_sents, vocab, args.ctx)
    print(f"[data] vocab={len(vocab)} train={len(x_train)} test={len(x_test)} ctx={args.ctx}")

    model = HybridPoincareLM(
        len(vocab), args.ctx, args.d_model, args.d_hidden,
        args.pairs, args.topk, args.dropout,
    ).to(device)
    print(f"[model] params={sum(p.numel() for p in model.parameters()):,}")
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    xt = torch.from_numpy(x_train).long().to(device)
    yt = torch.from_numpy(y_train).long().to(device)
    xv = torch.from_numpy(x_test).long().to(device)
    yv = torch.from_numpy(y_test).long().to(device)

    best = 0.0
    best_metrics: dict = {}
    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    for epoch in range(args.epochs):
        model.train()
        perm = torch.randperm(len(xt), device=device)
        total = 0
        correct = 0
        loss_sum = 0.0
        for i in range(0, len(xt), args.batch_size):
            idx = perm[i : i + args.batch_size]
            xb, yb = xt[idx], yt[idx]
            opt.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", enabled=amp):
                logits, aux = model(xb)
                loss = F.cross_entropy(logits, yb)
                loss = loss + 0.01 * aux["load_balance"]
                loss = loss + 0.05 * aux["mirror_loss"]
                loss = loss + 0.001 * aux["geom_load"]
                loss = loss + 1e-4 * aux["curv_reg"]
            if scaler is not None:
                scaler.scale(loss).backward()
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(opt)
                scaler.update()
            else:
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
            loss_sum += float(loss.detach()) * len(idx)
            total += len(idx)
            correct += int((logits.argmax(-1) == yb).sum())
        model.eval()
        with torch.no_grad():
            vlogits, vaux = model(xv)
            vacc = (vlogits.argmax(-1) == yv).float().mean().item() * 100.0
            vloss = float(F.cross_entropy(vlogits, yv))
        if vacc > best:
            best = vacc
            best_metrics = {
                "epoch": epoch + 1,
                "test_accuracy": vacc,
                "test_loss": vloss,
                "branch_mean": vaux["branch_mean"].detach().cpu().tolist(),
            }
            torch.save(
                {"model": model.state_dict(), "vocab": vocab_list, "args": vars(args)},
                out_dir / "hybrid_poincare_best.pt",
            )
        if (epoch + 1) % 5 == 0 or epoch == 0:
            print(
                f"epoch {epoch + 1:3d}/{args.epochs} train_acc={correct / total * 100:6.2f}% "
                f"loss={loss_sum / total:.4f} test_acc={vacc:6.2f}% best={best:6.2f}% "
                f"branch={[round(float(x), 2) for x in vaux['branch_mean']]}"
            )

    result = {
        "best_accuracy": best,
        "target_accuracy": args.target_accuracy,
        "target_met": best >= args.target_accuracy,
        "vocab": len(vocab),
        "train_samples": len(x_train),
        "test_samples": len(x_test),
        "params": sum(p.numel() for p in model.parameters()),
        "elapsed_seconds": time.time() - t0,
        "best_metrics": best_metrics,
        "config": {
            "sentences": args.sentences,
            "ctx": args.ctx,
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "d_model": args.d_model,
            "d_hidden": args.d_hidden,
            "pairs": args.pairs,
            "topk": args.topk,
        },
    }
    (out_dir / "hybrid_poincare_result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if best < args.target_accuracy:
        print(f"TARGET_MISS best={best:.2f}% target={args.target_accuracy:.2f}%")
        return 1
    print(f"TARGET_MET best={best:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
