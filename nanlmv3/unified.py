#!/usr/bin/env python3
"""Unified hybrid model for the branch curriculum and the 100M text corpus.

One model class, one training path:

  * synthetic mode: branches 1..4, word tokens, 90% accuracy gate
  * text mode: BPE 32k, 100M corpus, real bits/token / top-1 / top-5 metrics

The model merges the two earlier implementations:

  poincare.py v23 / hybrid_poincare.py:
    last+attended context, hyperbolic branch gate, 128 mirror-pair MoE,
    top-8 routing, load balance

  frontier_model.py:
    causal trunk, 255-head -> 85-trihead -> head field / mirror-pair field,
    S+/S- rails, triangle curvature, Poincare trihead branch, S- head

The geometry is a learned bias on the MoE expert gate.  Both modes instantiate
the same `UnifiedHybridLM`; only the tokenizer, data sampler, and metrics
differ.
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

from frontier_model import CausalTrunk
from head_geometry import TorchHeadGeometry
from hybrid_poincare import PairMoE, build_sentences, build_vocab, encode_sentences
from poincare_geometry import PoincareTriheadLayer, POINCARE_OUT_DIM


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class UnifiedHybridLM(nn.Module):
    def __init__(
        self,
        vocab: int,
        ctx: int,
        d_model: int = 64,
        d_hidden: int = 64,
        n_pairs: int = 128,
        topk: int = 8,
        n_branches: int = 4,
        trunk_layers: int = 0,
        trunk_heads: int = 4,
        trunk_ff: int = 256,
        dropout: float = 0.1,
        use_geometry: bool = True,
        use_prev: bool = False,
    ):
        super().__init__()
        self.ctx = ctx
        self.n_branches = n_branches
        self.use_geometry = use_geometry
        self.use_prev = use_prev
        self.tok = nn.Embedding(vocab, d_model)
        self.pos = nn.Embedding(ctx, d_model)
        self.trunk = (
            CausalTrunk(d_model, trunk_layers, trunk_heads, trunk_ff, dropout, ctx)
            if trunk_layers > 0
            else None
        )
        self.attn_score = nn.Linear(d_model, 1)
        self.ctx_proj = nn.Linear(2 * d_model, d_model)
        self.branch_proj = nn.Linear(d_model, 8)
        self.centroids = nn.Parameter(torch.zeros(n_branches, 8))
        with torch.no_grad():
            for i in range(n_branches):
                angle = 2.0 * math.pi * i / max(1, n_branches)
                self.centroids[i, 0] = 0.5 * math.cos(angle)
                self.centroids[i, 1] = 0.5 * math.sin(angle)
        self.router = nn.Linear(d_model + n_branches, d_model)

        if use_geometry:
            self.head_proj = nn.Linear(d_model, 255)
            self.geom = TorchHeadGeometry()
            self.pgeom = PoincareTriheadLayer()
            geom_dim = 129 + POINCARE_OUT_DIM
            self.geom_bias = nn.Linear(geom_dim, n_pairs)
        else:
            self.head_proj = None
            self.geom = None
            self.pgeom = None
            self.geom_bias = None

        self.moe = PairMoE(d_model, d_hidden, n_pairs, topk)
        self.res = nn.Linear(d_hidden, d_model)
        self.ln = nn.LayerNorm(d_model)
        self.out_proj = nn.Linear(d_hidden, d_model)
        self.prev_proj = nn.Linear(d_model, d_model) if use_prev else None
        self.drop = nn.Dropout(dropout)
        self.apply(self._init)
        nn.init.normal_(self.tok.weight, mean=0.0, std=0.02)
        nn.init.normal_(self.pos.weight, mean=0.0, std=0.02)
        if self.geom_bias is not None:
            nn.init.zeros_(self.geom_bias.weight)
            nn.init.zeros_(self.geom_bias.bias)

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
        return F.softmax(-torch.acosh(arg), dim=-1)

    def forward(self, tokens: torch.Tensor):
        b, t = tokens.shape
        e = self.tok(tokens) + self.pos(torch.arange(t, device=tokens.device).unsqueeze(0))
        if self.trunk is not None:
            e = self.trunk(e)
        scores = self.attn_score(self.drop(e)).squeeze(-1)
        attn = F.softmax(scores, dim=-1)
        attended = torch.einsum("bt,btd->bd", attn, e)
        ctx_vec = F.relu(self.ctx_proj(torch.cat([e[:, -1, :], attended], dim=-1)))
        branch = self.hyperbolic_branch(ctx_vec)
        routed = F.relu(self.router(torch.cat([ctx_vec, branch], dim=-1)))

        aux: dict[str, torch.Tensor] = {"branch_mean": branch.mean(dim=0)}
        gb = None
        if self.use_geometry:
            credits = self.head_proj(ctx_vec)
            gfeat = self.geom(credits)
            pfeat, paux = self.pgeom(credits)
            g = torch.cat([gfeat, pfeat], dim=-1)
            gb = self.geom_bias(g)
            aux["field_quorum"] = gfeat[:, 15].mean()
            aux["geom_curvature"] = gfeat[:, 20].mean()
            aux.update(paux)

        h, lb = self.moe(routed, gb)
        z = self.ln(routed + self.res(self.drop(h)))
        logits = self.out_proj(z) @ self.tok.weight.T
        prev_logits = (self.prev_proj(z) @ self.tok.weight.T) if self.prev_proj is not None else None
        aux["load_balance"] = lb
        return logits, prev_logits, aux


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def synthetic_data(branches: int, sentences: int, ctx: int, seed: int = 3):
    sents = build_sentences(sentences, seed=99, branches=branches)
    rng = random.Random(42)
    rng.shuffle(sents)
    n_test = max(20, int(len(sents) * 0.2))
    test_s = sents[:n_test]
    train_s = sents[n_test:]
    vocab, _ = build_vocab(sents)
    x_train, y_train = encode_sentences(train_s, vocab, ctx)
    x_test, y_test = encode_sentences(test_s, vocab, ctx)
    return vocab, x_train, y_train, x_test, y_test


def text_data(corpus: str, tokenizer, ctx: int, train_fraction: float, max_bytes: int = 0):
    text = Path(corpus).read_text(encoding="utf-8", errors="ignore")
    if max_bytes > 0:
        text = text[:max_bytes]
    ids = tokenizer.encode(text)
    if len(ids) < ctx + 64:
        raise SystemExit("corpus too small")
    split = int(len(ids) * train_fraction)
    split = max(ctx + 32, min(split, len(ids) - 64))
    return ids, split


def text_batch(ids, split, ctx, batch, rng: np.random.Generator, train: bool):
    lo = ctx
    hi = split if train else len(ids) - 1
    if not train:
        lo = max(split, ctx)
    pos = rng.integers(lo, hi, size=batch)
    xs = np.stack([ids[p - ctx : p] for p in pos]).astype(np.int64)
    ys = np.array([ids[p] for p in pos], dtype=np.int64)
    prev_pos = pos - ctx - 1
    valid = prev_pos >= 0
    yp = np.zeros(batch, dtype=np.int64)
    yp[valid] = ids[prev_pos[valid]]
    pm = valid.astype(np.float32)
    return (
        torch.from_numpy(xs), torch.from_numpy(ys),
        torch.from_numpy(yp), torch.from_numpy(pm),
    )


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["synthetic", "text"], required=True)
    p.add_argument("--out", default=str(Path.home() / "meta" / "unified_out"))
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    p.add_argument("--amp", action="store_true", default=True)
    p.add_argument("--seed", type=int, default=3)
    p.add_argument("--threads", type=int, default=4)
    # Model.
    p.add_argument("--ctx", type=int, default=16)
    p.add_argument("--d-model", type=int, default=64)
    p.add_argument("--d-hidden", type=int, default=64)
    p.add_argument("--pairs", type=int, default=128)
    p.add_argument("--topk", type=int, default=8)
    p.add_argument("--branches", type=int, default=4)
    p.add_argument("--trunk-layers", type=int, default=0)
    p.add_argument("--trunk-heads", type=int, default=4)
    p.add_argument("--trunk-ff", type=int, default=256)
    p.add_argument("--dropout", type=float, default=0.1)
    p.add_argument("--no-geometry", action="store_true")
    p.add_argument("--prev", action="store_true")
    # Synthetic.
    p.add_argument("--sentences", type=int, default=1000)
    p.add_argument("--epochs", type=int, default=50)
    p.add_argument("--target-accuracy", type=float, default=90.0)
    # Text.
    p.add_argument("--corpus", default=None)
    p.add_argument("--bpe-model", default=None)
    p.add_argument("--tokenizer", choices=["bpe", "bytes"], default="bpe")
    p.add_argument("--steps", type=int, default=20000)
    p.add_argument("--eval-every", type=int, default=1000)
    p.add_argument("--eval-batches", type=int, default=32)
    p.add_argument("--train-fraction", type=float, default=0.95)
    # Optim.
    p.add_argument("--batch-size", type=int, default=128)
    p.add_argument("--lr", type=float, default=3e-3)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--warmup", type=int, default=100)
    p.add_argument("--grad-clip", type=float, default=1.0)
    p.add_argument("--prev-weight", type=float, default=0.1)
    p.add_argument("--aux-load", type=float, default=0.01)
    p.add_argument("--aux-mirror", type=float, default=0.05)
    p.add_argument("--aux-curv", type=float, default=1e-4)
    args = p.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_float32_matmul_precision("high")
    torch.set_num_threads(args.threads)
    device = torch.device(args.device)
    amp = bool(args.amp and device.type == "cuda")
    scaler = torch.amp.GradScaler("cuda") if amp else None
    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    tokenizer = None
    if args.mode == "synthetic":
        vocab, xtr, ytr, xte, yte = synthetic_data(args.branches, args.sentences, args.ctx, args.seed)
        vocab_size = len(vocab)
        xt = torch.from_numpy(xtr).long().to(device)
        yt = torch.from_numpy(ytr).long().to(device)
        xv = torch.from_numpy(xte).long().to(device)
        yv = torch.from_numpy(yte).long().to(device)
        print(f"[data] synthetic branches={args.branches} vocab={vocab_size} train={len(xt)} test={len(xv)}")
    else:
        if not args.corpus:
            raise SystemExit("text mode needs --corpus")
        if args.tokenizer == "bpe":
            if not args.bpe_model:
                raise SystemExit("BPE mode needs --bpe-model")
            from tokenizers import Tokenizer
            tokenizer = Tokenizer.from_file(args.bpe_model)
            vocab_size = tokenizer.get_vocab_size()

            class Tok:
                def encode(self, s):
                    return np.asarray(tokenizer.encode(s).ids, dtype=np.int32)
        else:
            vocab_size = 256

            class Tok:
                def encode(self, s):
                    return np.frombuffer(s.encode("utf-8", errors="replace"), dtype=np.uint8).astype(np.int32)

        ids, split = text_data(args.corpus, Tok(), args.ctx, args.train_fraction)
        print(f"[data] text tokenizer={args.tokenizer} vocab={vocab_size} tokens={len(ids)} train_end={split} ctx={args.ctx}")

    model = UnifiedHybridLM(
        vocab_size, args.ctx, args.d_model, args.d_hidden, args.pairs, args.topk,
        args.branches, args.trunk_layers, args.trunk_heads, args.trunk_ff,
        args.dropout, not args.no_geometry, args.prev,
    ).to(device)
    print(f"[model] params={sum(p.numel() for p in model.parameters()):,}")
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    rng = np.random.default_rng(args.seed)
    t0 = time.time()
    best = 0.0 if args.mode == "synthetic" else float("inf")
    best_record: dict = {}
    history: list[dict] = []

    def loss_and_metrics(logits, prev_logits, aux, y, yp=None, pm=None):
        loss = F.cross_entropy(logits, y)
        if prev_logits is not None and yp is not None and pm is not None and pm.sum() > 0:
            mask = pm.bool()
            loss = loss + args.prev_weight * F.cross_entropy(prev_logits[mask], yp[mask])
        zero = torch.zeros((), device=device)
        loss = loss + args.aux_load * aux.get("load_balance", zero)
        loss = loss + args.aux_mirror * aux.get("mirror_loss", zero)
        loss = loss + args.aux_curv * aux.get("curv_reg", zero)
        return loss

    def eval_text(batches=32):
        model.eval()
        total = 0
        correct = 0
        correct5 = 0
        prev_correct = 0
        prev_total = 0
        loss_sum = 0.0
        with torch.no_grad():
            for _ in range(batches):
                xb, yb, ypb, pmb = text_batch(ids, split, args.ctx, args.batch_size, rng, False)
                xb, yb, ypb, pmb = xb.to(device), yb.to(device), ypb.to(device), pmb.to(device)
                logits, prev_logits, aux = model(xb)
                loss_sum += float(F.cross_entropy(logits, yb, reduction="sum"))
                correct += int((logits.argmax(-1) == yb).sum())
                top5 = logits.topk(5, dim=-1).indices
                correct5 += int((top5 == yb.unsqueeze(-1)).any(-1).sum())
                if prev_logits is not None:
                    mask = pmb.bool()
                    if mask.any():
                        prev_correct += int((prev_logits[mask].argmax(-1) == ypb[mask]).sum())
                        prev_total += int(mask.sum())
                total += yb.numel()
        model.train()
        return {
            "loss": loss_sum / max(1, total),
            "bits_per_token": (loss_sum / max(1, total)) / math.log(2),
            "accuracy": correct / max(1, total),
            "top5": correct5 / max(1, total),
            "prev_accuracy": prev_correct / prev_total if prev_total else None,
            "tokens": total,
        }

    def eval_synth():
        model.eval()
        with torch.no_grad():
            logits, _, aux = model(xv)
            acc = (logits.argmax(-1) == yv).float().mean().item() * 100.0
            loss = float(F.cross_entropy(logits, yv))
        model.train()
        return {"accuracy": acc, "loss": loss, "branch_mean": aux["branch_mean"].detach().cpu().tolist()}

    if args.mode == "synthetic":
        for epoch in range(args.epochs):
            model.train()
            perm = torch.randperm(len(xt), device=device)
            loss_sum = 0.0
            correct = 0
            for i in range(0, len(xt), args.batch_size):
                idx = perm[i : i + args.batch_size]
                xb, yb = xt[idx], yt[idx]
                opt.zero_grad(set_to_none=True)
                with torch.amp.autocast("cuda", enabled=amp):
                    logits, prev_logits, aux = model(xb)
                    loss = loss_and_metrics(logits, prev_logits, aux, yb)
                if scaler is not None:
                    scaler.scale(loss).backward()
                    scaler.unscale_(opt)
                    torch.nn.utils.clip_grad_norm_(model.parameters(), args.grad_clip)
                    scaler.step(opt)
                    scaler.update()
                else:
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), args.grad_clip)
                    opt.step()
                loss_sum += float(loss.detach()) * len(idx)
                correct += int((logits.argmax(-1) == yb).sum())
            ev = eval_synth()
            history.append({"epoch": epoch + 1, **ev})
            if ev["accuracy"] > best:
                best = ev["accuracy"]
                best_record = {"epoch": epoch + 1, **ev}
                torch.save({"model": model.state_dict(), "args": vars(args)}, out_dir / "best.pt")
            if (epoch + 1) % 5 == 0 or epoch == 0:
                print(
                    f"epoch {epoch + 1:3d}/{args.epochs} train_acc={correct / len(xt) * 100:6.2f}% "
                    f"test_acc={ev['accuracy']:6.2f}% best={best:6.2f}%"
                )
        result = {
            "mode": "synthetic",
            "branches": args.branches,
            "best_accuracy": best,
            "target_accuracy": args.target_accuracy,
            "target_met": best >= args.target_accuracy,
            "params": sum(p.numel() for p in model.parameters()),
            "train_samples": len(xt),
            "test_samples": len(xv),
            "elapsed": time.time() - t0,
            "best_record": best_record,
        }
    else:
        for step in range(args.steps):
            xb, yb, ypb, pmb = text_batch(ids, split, args.ctx, args.batch_size, rng, True)
            xb, yb, ypb, pmb = xb.to(device), yb.to(device), ypb.to(device), pmb.to(device)
            lr = args.lr * min(1.0, (step + 1) / max(1, args.warmup))
            if step > args.warmup:
                prog = (step - args.warmup) / max(1, args.steps - args.warmup)
                lr = args.lr * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(1.0, prog))))
            for g in opt.param_groups:
                g["lr"] = lr
            opt.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", enabled=amp):
                logits, prev_logits, aux = model(xb)
                loss = loss_and_metrics(logits, prev_logits, aux, yb, ypb, pmb)
            if scaler is not None:
                scaler.scale(loss).backward()
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(model.parameters(), args.grad_clip)
                scaler.step(opt)
                scaler.update()
            else:
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), args.grad_clip)
                opt.step()
            if (step + 1) % 50 == 0:
                print(f"step {step + 1:6d}/{args.steps} loss={float(loss):.4f} lr={lr:.2e}")
            if (step + 1) % args.eval_every == 0 or step + 1 == args.steps:
                ev = eval_text(args.eval_batches)
                history.append({"step": step + 1, **ev})
                print(
                    f"  EVAL step {step + 1}: loss={ev['loss']:.4f} bits={ev['bits_per_token']:.3f} "
                    f"top1={ev['accuracy'] * 100:.2f}% top5={ev['top5'] * 100:.2f}% "
                    f"prev={ev['prev_accuracy']}"
                )
                if ev["loss"] < best:
                    best = ev["loss"]
                    best_record = {"step": step + 1, **ev}
                    torch.save({"model": model.state_dict(), "args": vars(args)}, out_dir / "best.pt")
        final = eval_text(args.eval_batches)
        result = {
            "mode": "text",
            "best_val_loss": best,
            "best_record": best_record,
            "final": final,
            "params": sum(p.numel() for p in model.parameters()),
            "steps": args.steps,
            "vocab_size": vocab_size,
            "tokens": len(ids),
            "train_tokens": int(split),
            "val_tokens": int(len(ids) - split),
            "elapsed": time.time() - t0,
        }

    result["config"] = vars(args)
    (out_dir / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.mode == "synthetic" and best < args.target_accuracy:
        print(f"TARGET_MISS best={best:.2f}% target={args.target_accuracy:.2f}%")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
