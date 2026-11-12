#!/usr/bin/env python3
"""Poincare-disk / hyperbolic trihead geometry, distilled from poincare_lm.py.

Ideas taken from the supplied `~/meta/poincare_lm.py`:

  * 255 registers on a Poincare disk: 127 antipodal mirror pairs plus a center
    head (127); head 255 is the output/VOID channel.
  * mirror head 254-a = -u_a, so mirror pairs are antipodal and have large
    hyperbolic distance.
  * triheads are clustered by hyperbolic distance (center/general first, then
    nearest neighbours), and can be re-clustered after the disk moves.
  * each trihead has a learnable curvature and S+/S- polarity.
  * hotness is a learned confidence gate, not a cosine score.
  * top-K trihead routing, load balancing, mirror contrastive loss, and
    curvature regularisation.
  * curvature/polarity/hot are returned as features for the next layer
    ("curvature as information-abstraction storage").

This is a standalone module.  It does not import any NaN* repository code.
"""

from __future__ import annotations

import math

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

HEADS = 255          # trainable registers 0..254
DISK_HEADS = 255
CENTER_HEAD = 127
PAIR_HEADS = 127     # 0..126 paired with 254..128
TRIADS = 85
TOPK = 8
POINCARE_OUT_DIM = 18


def hyperbolic_distance_np(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Stable Poincare disk distance for arrays (..., 2)."""
    u = np.asarray(u, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    u2 = np.sum(u * u, axis=-1)
    v2 = np.sum(v * v, axis=-1)
    diff2 = np.sum((u - v) ** 2, axis=-1)
    denom = np.clip((1.0 - u2) * (1.0 - v2), 1e-9, None)
    arg = np.clip(1.0 + 2.0 * diff2 / denom, 1.0, 1e12)
    return np.arccosh(arg)


def hyperbolic_distance_torch(u: torch.Tensor, v: torch.Tensor) -> torch.Tensor:
    """Broadcasting Poincare distance for (..., 2)."""
    u2 = (u * u).sum(dim=-1)
    v2 = (v * v).sum(dim=-1)
    diff2 = ((u - v) ** 2).sum(dim=-1)
    denom = torch.clamp((1.0 - u2) * (1.0 - v2), min=1e-9)
    arg = torch.clamp(1.0 + 2.0 * diff2 / denom, min=1.0 + 1e-7, max=1e12)
    return torch.acosh(arg)


class PoincareDisk(nn.Module):
    """127 learnable antipodal pairs + center head on the Poincare disk."""

    def __init__(self, scale: float = 0.95):
        super().__init__()
        self.scale = scale
        rng = np.random.RandomState(3)
        raw = np.zeros((PAIR_HEADS, 2), dtype=np.float32)
        for a in range(PAIR_HEADS):
            angle = rng.uniform(0, 2 * math.pi)
            radius = rng.uniform(0.3, 0.8)
            raw[a] = [radius * math.cos(angle), radius * math.sin(angle)]
        self.raw = nn.Parameter(torch.from_numpy(raw))

    def coords(self) -> torch.Tensor:
        """Return (255,2) with u[254-a] = -u[a] and u[127] = 0."""
        z = torch.tanh(self.raw) * self.scale
        out = torch.zeros((HEADS, 2), device=z.device, dtype=z.dtype)
        out[:PAIR_HEADS] = z
        out[CENTER_HEAD] = 0.0
        out[CENTER_HEAD + 1 :] = -torch.flip(z, dims=[0])
        return out


def cluster_triads(disk_coords: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Greedy hyperbolic trihead clustering, copied in spirit from poincare_lm.py.

    Heads are visited from the center outward (general -> specific); each
    unassigned head takes its two nearest unassigned heads in hyperbolic
    distance.  255 = 3 * 85, so exactly 85 triads result.
    """
    coords = np.asarray(disk_coords, dtype=np.float64)
    if coords.shape != (HEADS, 2):
        raise ValueError("disk coords must be (255,2)")
    radii = np.linalg.norm(coords, axis=1)
    order = np.argsort(radii)
    unassigned = set(range(HEADS))
    triads: list[list[int]] = []
    for head in order:
        if head not in unassigned:
            continue
        unassigned.remove(head)
        picks: list[int] = []
        if unassigned:
            dists = sorted(
                (
                    float(hyperbolic_distance_np(coords[head], coords[other])),
                    other,
                )
                for other in unassigned
            )
            for _, other in dists[:2]:
                picks.append(other)
                unassigned.remove(other)
        while len(picks) < 2:
            picks.append(head)
        triads.append([head] + picks)
        if len(triads) == TRIADS:
            break
    # If greedy produced fewer (should not happen), fill with unused heads.
    if len(triads) < TRIADS:
        leftovers = sorted(unassigned)
        while len(triads) < TRIADS and len(leftovers) >= 3:
            triads.append(leftovers[:3])
            del leftovers[:3]
        while len(triads) < TRIADS:
            triads.append([CENTER_HEAD, CENTER_HEAD, CENTER_HEAD])
    triads_arr = np.asarray(triads[:TRIADS], dtype=np.int64)

    head_to_tri: dict[int, int] = {}
    for ti, tri in enumerate(triads_arr):
        for h in tri:
            head_to_tri[int(h)] = ti
    mirror = np.arange(TRIADS, dtype=np.int64)
    for ti, tri in enumerate(triads_arr):
        mirrored = [CENTER_HEAD if int(h) == CENTER_HEAD else 254 - int(h) for h in tri]
        mirror[ti] = head_to_tri.get(int(mirrored[0]), ti)
    return triads_arr, mirror


class PoincareTriheadLayer(nn.Module):
    """Hyperbolic trihead router + curvature/polarity storage features."""

    def __init__(self, topk: int = TOPK):
        super().__init__()
        self.topk = topk
        self.disk = PoincareDisk()
        triads, mirror = cluster_triads(self.disk.coords().detach().numpy())
        self.register_buffer("triads", torch.from_numpy(triads), persistent=True)
        self.register_buffer("mirror", torch.from_numpy(mirror), persistent=True)
        self.gate = nn.Linear(HEADS, TRIADS)
        self.hot_gate = nn.Linear(HEADS, TRIADS)
        self.query = nn.Linear(HEADS, 2)
        self.curvature = nn.Parameter(torch.zeros(TRIADS))
        self.polarity = nn.Parameter(torch.zeros(TRIADS))
        self.out_dim = POINCARE_OUT_DIM

    @torch.no_grad()
    def recluster(self) -> None:
        triads, mirror = cluster_triads(self.disk.coords().detach().cpu().numpy())
        self.triads.copy_(torch.from_numpy(triads).to(self.triads.device))
        self.mirror.copy_(torch.from_numpy(mirror).to(self.mirror.device))

    def forward(self, credits: torch.Tensor) -> tuple[torch.Tensor, dict]:
        # credits: (B,255) head-credit space.  The disk itself is a global
        # per-head geometry; the query is per-token.
        if credits.dim() != 2 or credits.shape[1] != HEADS:
            raise ValueError("credits must be (batch, 255)")
        b = credits.shape[0]
        dev = credits.device
        disk = self.disk.coords()  # (255,2)
        tri_disk = disk[self.triads].mean(dim=1)  # (85,2)

        query = torch.tanh(self.query(credits)) * 0.95  # (B,2)
        hyp = hyperbolic_distance_torch(
            query.unsqueeze(1), tri_disk.unsqueeze(0)
        )  # (B,85)

        gate_logits = self.gate(credits) - 0.1 * hyp
        gate_probs = F.softmax(gate_logits, dim=-1)
        hot = torch.sigmoid(self.hot_gate(credits))
        curv = 2.0 * self.curvature
        curv_factor = torch.clamp(1.0 + curv, 0.1, 3.0)
        polarity = torch.tanh(2.0 * self.polarity)
        s_plus = (1.0 + polarity) / 2.0

        weights = gate_probs * hot * curv_factor.unsqueeze(0) * s_plus.unsqueeze(0)
        top_vals, top_idx = torch.topk(weights, k=min(self.topk, TRIADS), dim=-1)
        top_w = F.softmax(top_vals, dim=-1)

        # Features: hyperbolic routing, curvature/polarity/hot storage.
        entropy = -(gate_probs * torch.log(gate_probs + 1e-9)).sum(dim=-1, keepdim=True)
        usage = torch.zeros((b, TRIADS), device=dev)
        usage.scatter_add_(
            1,
            top_idx,
            torch.ones_like(top_w),
        )
        usage_entropy = -(
            (usage / max(1, self.topk))
            * torch.log(usage / max(1, self.topk) + 1e-9)
        ).sum(dim=-1, keepdim=True)
        radii = torch.linalg.vector_norm(disk, dim=1)
        mirror_dist = hyperbolic_distance_torch(
            disk[:PAIR_HEADS], torch.flip(disk[CENTER_HEAD + 1 :], dims=[0])
        )
        feats = torch.cat(
            [
                hyp.mean(dim=1, keepdim=True),
                hyp.std(dim=1, unbiased=False, keepdim=True),
                entropy,
                hot.mean(dim=1, keepdim=True),
                hot.std(dim=1, unbiased=False, keepdim=True),
                curv.mean().expand(b, 1),
                curv.std(unbiased=False).expand(b, 1),
                polarity.mean().expand(b, 1),
                (polarity > 0).float().mean().expand(b, 1),
                (polarity < 0).float().mean().expand(b, 1),
                top_w.mean(dim=1, keepdim=True),
                top_w.max(dim=1).values.unsqueeze(1),
                radii.mean().expand(b, 1),
                radii.std(unbiased=False).expand(b, 1),
                radii.max().expand(b, 1),
                mirror_dist.mean().expand(b, 1),
                usage_entropy,
                (usage > 0).float().mean(dim=1, keepdim=True),
            ],
            dim=1,
        )

        # Mirror consistency: a trihead and its mirror trihead should carry
        # similar credit.  This is the contrastive idea from poincare_lm.py,
        # applied in head-credit space instead of the vocabulary logits.
        tri_credit = credits[:, self.triads].mean(dim=2)  # (B,85)
        mirror_credit = tri_credit[:, self.mirror]
        mirror_loss = F.mse_loss(tri_credit, mirror_credit)

        # Load balancing + curvature regularisation.
        load = (usage.mean(dim=0) * gate_probs.mean(dim=0)).sum() * TRIADS
        curv_reg = (curv * curv).mean()
        aux = {
            "mirror_loss": mirror_loss,
            "load_balance": load,
            "curv_reg": curv_reg,
            "hyp_mean": hyp.mean(),
            "curvature_mean": curv.mean(),
            "polarity_mean": polarity.mean(),
            "hot_mean": hot.mean(),
        }
        return feats, aux


__all__ = [
    "HEADS",
    "TRIADS",
    "TOPK",
    "POINCARE_OUT_DIM",
    "hyperbolic_distance_np",
    "hyperbolic_distance_torch",
    "PoincareDisk",
    "cluster_triads",
    "PoincareTriheadLayer",
]
