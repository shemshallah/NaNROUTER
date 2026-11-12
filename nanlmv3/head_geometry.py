#!/usr/bin/env python3
"""Palindromic head / trihead / field / rail / curvature geometry.

This module is the bridge between the c(256,2) address space and a trainable
language model.  It does not claim that the geometry is a finished model.  It
defines the measurements the user asked for:

    255 palindromic heads
      -> 85 triheads (triangles of heads)
      -> 2/3 and 3/3 hot/cold triangle votes
      -> 255-head field
      -> 32,640-pair mirror field
      -> S+ / S- temporal rail address pairs
      -> triangle -> mirror-pair address mapping
      -> signed triangle curvature
      -> a trainable curvature-codebook ("global fabric") feature

The hard geometry is CPU/numpy and deterministic.  `TorchHeadGeometry` is the
differentiable version used by the mixer: head credits are soft, the triad
votes are soft, and the curvature bucket assignment is a soft histogram so
gradients reach the head-credit projection.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import numpy as np

HEADS = 256
TRAINABLE_HEADS = 255
VOID_HEAD = 255
NANNET_HEAD = 0
NAN_HEADS = (124, 125, 126, 127, 252, 253, 254, 255)
TRIADS = 85
PAIRS = 32640

# Fixed 3t+s partition used by the native context-class path.  It covers
# heads 0..254 exactly once; head 255 is the VOID/global head.
FIXED_TRIADS = tuple(
    (3 * t, 3 * t + 1, 3 * t + 2) for t in range(TRIADS)
)


def rev8(value: int) -> int:
    out = 0
    for _ in range(8):
        out = (out << 1) | (value & 1)
        value >>= 1
    return out


def pal16(seed: int) -> int:
    """The 16-bit palindrome for a head seed: high byte, then reversed low byte."""
    if not 0 <= seed <= 255:
        raise ValueError("head seed must be 0..255")
    return (seed << 8) | rev8(seed)


def is_palindrome16(value: int) -> bool:
    return 0 <= value <= 0xFFFF and (value >> 8) == rev8(value & 0xFF)


def pair_id(a: int, b: int) -> int:
    """Canonical 1..32640 mirror-pair id for two distinct heads."""
    if not (0 <= a < HEADS and 0 <= b < HEADS):
        raise ValueError("head must be 0..255")
    if a == b:
        raise ValueError("a head does not pair with itself")
    if a > b:
        a, b = b, a
    return 1 + a * (2 * HEADS - 1 - a) // 2 + (b - a - 1)


def pair_heads(value: int) -> tuple[int, int]:
    if not 1 <= value <= PAIRS:
        raise ValueError("pair id must be 1..32640")
    # Binary search over the row starts.
    low, high = 0, HEADS - 2
    starts = [1 + a * (2 * HEADS - 1 - a) // 2 for a in range(HEADS - 1)]
    while low < high:
        mid = (low + high + 1) // 2
        if starts[mid] <= value:
            low = mid
        else:
            high = mid - 1
    a = low
    b = a + 1 + value - starts[a]
    return a, b


def rail_sign(head: int) -> int:
    """Deterministic S+/S- assignment for a head.

    A 16-bit palindrome always has an even number of set bits, so palindrome
    bit parity cannot split the rails.  We use a deterministic multiplicative
    hash of the head seed instead.  This is a convention, not a physical claim;
    it gives a balanced split and mixed 3/3, 2/3, 1/3 and 0/3 triangle classes.
    """
    mixed = (head * 2654435761) & 0xFFFFFFFF
    return 1 if mixed < 0x80000000 else -1


RAIL_SIGNS = np.array([rail_sign(h) for h in range(TRAINABLE_HEADS)], dtype=np.int8)
TRIAD_RAIL_SUM = np.array(
    [int(sum(RAIL_SIGNS[h] for h in triad)) for triad in FIXED_TRIADS],
    dtype=np.int8,
)


def hot_triads(head_credits: np.ndarray) -> tuple[tuple[int, int, int], ...]:
    """Group the 255 heads hot-first into 85 triads (native hot-trihead rule)."""
    credits = np.asarray(head_credits, dtype=np.float64).reshape(-1)
    if credits.size != TRAINABLE_HEADS:
        raise ValueError("expected 255 head credits")
    order = np.argsort(-credits, kind="stable")
    return tuple(
        (int(order[3 * t]), int(order[3 * t + 1]), int(order[3 * t + 2]))
        for t in range(TRIADS)
    )


def triad_votes(
    head_credits: np.ndarray,
    triads: Iterable[tuple[int, int, int]] = FIXED_TRIADS,
    threshold: float = 0.0,
) -> dict:
    """2/3 member votes and 43/85 field quorum for one head-credit vector."""
    credits = np.asarray(head_credits, dtype=np.float64).reshape(-1)
    triads = tuple(triads)
    masks = []
    accepted = 0
    hot = 0
    signed = []
    for a, b, c in triads:
        mask = (credits[a] > threshold) | ((credits[b] > threshold) << 1) | (
            (credits[c] > threshold) << 2
        )
        pop = int(mask.bit_count())
        masks.append(int(mask))
        accepted += int(pop >= 2)
        hot += int(pop == 3)
        signed.append(float(credits[a] + credits[b] + credits[c]))
    return {
        "masks": masks,
        "accepted": accepted,
        "hot": hot,
        "field_quorum": accepted >= 43,
        "accepted_fraction": accepted / TRIADS,
        "hot_fraction": hot / TRIADS,
        "signed": np.array(signed, dtype=np.float64),
    }


def head_field(head_credits: np.ndarray) -> dict:
    """The 255-head field summary."""
    x = np.asarray(head_credits, dtype=np.float64).reshape(-1)
    return {
        "mean": float(x.mean()),
        "std": float(x.std()),
        "l2": float(np.linalg.norm(x)),
        "positive_fraction": float((x > 0).mean()),
        "max": float(x.max()),
        "min": float(x.min()),
    }


def mirror_pair_field(head_credits: np.ndarray) -> dict:
    """Exact mean/std of the bilinear field over all 32,640 pairs.

    pair(a,b) = x[a] * x[b].  The sums are computed in O(255), not O(32,640):

        sum_{a<b} x_a x_b = ((sum x)^2 - sum x^2) / 2
        sum_{a<b} (x_a x_b)^2 = ((sum x^2)^2 - sum x^4) / 2
    """
    x = np.asarray(head_credits, dtype=np.float64).reshape(-1)
    s1 = float(x.sum())
    s2 = float((x * x).sum())
    s4 = float((x ** 4).sum())
    pair_sum = 0.5 * (s1 * s1 - s2)
    pair_sq_sum = 0.5 * (s2 * s2 - s4)
    mean = pair_sum / PAIRS
    var = max(0.0, pair_sq_sum / PAIRS - mean * mean)
    return {"mean": mean, "std": math.sqrt(var), "energy": pair_sq_sum}


def triangle_pair_ids(triad: tuple[int, int, int]) -> tuple[int, int, int]:
    a, b, c = triad
    return pair_id(a, b), pair_id(b, c), pair_id(c, a)


def triangle_rail_lanes(triad: tuple[int, int, int]) -> tuple[int, int, int]:
    """Lane 0 for a same-rail edge, lane 1 for a cross-rail edge."""
    a, b, c = triad
    ra, rb, rc = rail_sign(a), rail_sign(b), rail_sign(c)
    return (
        0 if ra * rb > 0 else 1,
        0 if rb * rc > 0 else 1,
        0 if rc * ra > 0 else 1,
    )


def triangle_curvature(
    values: np.ndarray,
    triad: tuple[int, int, int],
) -> dict:
    """Signed triangle curvature from a per-head scalar field.

    Bilinear edge values e_ab = x_a*x_b, circulation
    kappa = e_ab + e_bc + e_ca, normalized by the absolute edge sum.
    This is a discrete curvature/energy, not a claim of physical geometry.
    """
    x = np.asarray(values, dtype=np.float64).reshape(-1)
    a, b, c = triad
    e_ab, e_bc, e_ca = x[a] * x[b], x[b] * x[c], x[c] * x[a]
    circulation = e_ab + e_bc + e_ca
    abs_sum = abs(e_ab) + abs(e_bc) + abs(e_ca)
    kappa = circulation / (abs_sum + 1e-12)
    lengths = (abs(x[a] - x[b]), abs(x[b] - x[c]), abs(x[c] - x[a]))
    stretch = (max(lengths) - min(lengths)) / (max(lengths) + 1e-12)
    return {
        "circulation": float(circulation),
        "kappa": float(kappa),
        "stretch": float(stretch),
        "edge_values": (float(e_ab), float(e_bc), float(e_ca)),
    }


def geometry_stats(head_credits: np.ndarray, triads=FIXED_TRIADS) -> dict:
    """All deterministic hard-geometry measurements for one credit vector."""
    x = np.asarray(head_credits, dtype=np.float64).reshape(-1)
    votes = triad_votes(x, triads)
    curv = np.array(
        [triangle_curvature(x, t)["kappa"] for t in triads], dtype=np.float64
    )
    stretch = np.array(
        [triangle_curvature(x, t)["stretch"] for t in triads], dtype=np.float64
    )
    rail_sums = np.array(
        [int(sum(RAIL_SIGNS[h] for h in t)) for t in triads], dtype=np.int8
    )
    rail_hist = {
        "3/3": int((rail_sums == 3).sum()),
        "2/3": int((rail_sums == 1).sum()),
        "1/3": int((rail_sums == -1).sum()),
        "0/3": int((rail_sums == -3).sum()),
    }
    return {
        "head_field": head_field(x),
        "pair_field": mirror_pair_field(x),
        "triad_votes": {
            "accepted": votes["accepted"],
            "hot": votes["hot"],
            "field_quorum": votes["field_quorum"],
            "accepted_fraction": votes["accepted_fraction"],
            "hot_fraction": votes["hot_fraction"],
        },
        "curvature": {
            "mean": float(curv.mean()),
            "std": float(curv.std()),
            "positive_fraction": float((curv > 0).mean()),
            "abs_mean": float(np.abs(curv).mean()),
            "max": float(curv.max()),
            "min": float(curv.min()),
        },
        "stretch": {
            "mean": float(stretch.mean()),
            "std": float(stretch.std()),
            "stretched_fraction": float((stretch > 0.5).mean()),
        },
        "rail_histogram": rail_hist,
        "hot_triads": hot_triads(x) if x.size == TRAINABLE_HEADS else tuple(triads),
    }


# ---------------------------------------------------------------------------
# Differentiable geometry for the 10M mixer
# ---------------------------------------------------------------------------

try:
    import torch
    from torch import nn
    import torch.nn.functional as F

    _HAS_TORCH = True
except Exception:  # pragma: no cover - the numpy path still works
    _HAS_TORCH = False
    torch = None
    nn = None
    F = None


if _HAS_TORCH:

    class TorchHeadGeometry(nn.Module):
        """Soft, trainable head -> trihead -> field -> rail -> curvature map.

        Input:  head_credits (B, 255), produced by a learned projection.
        Output: a fixed-size feature vector (B, F) for the mixer:
          - head-field / pair-field scalar statistics,
          - soft 2/3 and 3/3 triad vote rates,
          - S+/S- rail balance and triangle-rail histogram,
          - curvature and stretch statistics,
          - a soft curvature-bucket "global fabric" codebook,
          - a soft hot-triad embedding.

        The 256^3 tensor is not materialized.  The pair field is an O(255)
        bilinear summary, and the triad/curvature path is O(85), so the module
        stays small enough for a mixer and can be sharded later.
        """

        N_BINS = 16

        def __init__(self, d_code: int = 64, d_triad: int = 16, d_wedge: int = 32):
            super().__init__()
            self.d_code = d_code
            self.d_triad = d_triad
            self.d_wedge = d_wedge
            self.register_buffer(
                "triad_index",
                torch.tensor(FIXED_TRIADS, dtype=torch.long),
                persistent=True,
            )
            self.register_buffer(
                "rail_signs",
                torch.tensor(RAIL_SIGNS.astype(np.float32)),
                persistent=True,
            )
            self.register_buffer(
                "triad_rail_sum",
                torch.tensor(TRIAD_RAIL_SUM.astype(np.float32)),
                persistent=True,
            )
            self.register_buffer(
                "bin_centers",
                torch.linspace(-1.0, 1.0, self.N_BINS),
                persistent=True,
            )
            # Curvature uses an oriented wedge edge:
            # e_ab = u_a . v_b - u_b . v_a, which is gauge invariant around a
            # closed triangle under additive vertex shifts of u or v.
            self.wedge = nn.Linear(1, 2 * d_wedge)
            # Global fabric: (triad, curvature bin, rail class) -> code vector.
            self.fabric = nn.Embedding(TRIADS * self.N_BINS * 4, d_code)
            self.triad_embed = nn.Embedding(TRIADS, d_triad)
            self.out_dim = (
                7 + 4 + 6 + 4 + 6 + 6 + self.N_BINS + d_code + d_triad
            )

        def forward(self, credits: torch.Tensor) -> torch.Tensor:
            if credits.dim() != 2 or credits.shape[1] != TRAINABLE_HEADS:
                raise ValueError("credits must be (batch, 255)")
            b = credits.shape[0]
            dev = credits.device
            v = torch.sigmoid(credits)

            # --- soft trihead votes -------------------------------------
            tv = v[:, self.triad_index]  # (B, 85, 3)
            p3 = tv.prod(dim=-1)
            p1, p2, p3m = tv[..., 0], tv[..., 1], tv[..., 2]
            p_at_least_2 = (
                p1 * p2 * (1 - p3m)
                + p1 * p3m * (1 - p2)
                + p2 * p3m * (1 - p1)
                + p3
            )
            accepted_fraction = p_at_least_2.mean(dim=1, keepdim=True)
            hot_fraction = p3.mean(dim=1, keepdim=True)
            field_quorum = torch.sigmoid((p_at_least_2.sum(dim=1) - 43.0) * 4.0).unsqueeze(1)
            vote_hist = torch.stack(
                [
                    ((p_at_least_2 < 0.25).float()).mean(dim=1),
                    ((p_at_least_2 >= 0.25) & (p_at_least_2 < 0.5)).float().mean(dim=1),
                    ((p_at_least_2 >= 0.5) & (p_at_least_2 < 0.75)).float().mean(dim=1),
                    (p_at_least_2 >= 0.75).float().mean(dim=1),
                ],
                dim=1,
            )

            # --- head field and exact bilinear mirror-pair field --------
            s1 = credits.sum(dim=1)
            s2 = (credits * credits).sum(dim=1)
            s4 = (credits ** 4).sum(dim=1)
            pair_mean = 0.5 * (s1 * s1 - s2) / PAIRS
            pair_sq_mean = 0.5 * (s2 * s2 - s4) / PAIRS
            pair_std = torch.sqrt(torch.clamp(pair_sq_mean - pair_mean * pair_mean, min=0.0))
            head_stats = torch.stack(
                [
                    credits.mean(dim=1),
                    credits.std(dim=1, unbiased=False),
                    torch.linalg.vector_norm(credits, dim=1),
                    (credits > 0).float().mean(dim=1),
                    (credits < 0).float().mean(dim=1),
                    credits.max(dim=1).values,
                    credits.min(dim=1).values,
                ],
                dim=1,
            )
            field_stats = torch.stack([pair_mean, pair_std, pair_sq_mean], dim=1)

            # --- S+/S- rails --------------------------------------------
            rail = credits * self.rail_signs
            rail_pos = F.relu(rail).sum(dim=1, keepdim=True)
            rail_neg = F.relu(-rail).sum(dim=1, keepdim=True)
            rail_balance = (rail_pos - rail_neg) / (rail_pos + rail_neg + 1e-6)
            rail_hist = torch.stack(
                [
                    torch.full((b,), float((self.triad_rail_sum == 3).float().mean()), device=dev),
                    torch.full((b,), float((self.triad_rail_sum == 1).float().mean()), device=dev),
                    torch.full((b,), float((self.triad_rail_sum == -1).float().mean()), device=dev),
                    torch.full((b,), float((self.triad_rail_sum == -3).float().mean()), device=dev),
                ],
                dim=1,
            )

            # --- oriented wedge curvature ------------------------------
            uv = self.wedge(credits.unsqueeze(-1))  # (B,255,2D)
            u, vv = uv[..., : self.d_wedge], uv[..., self.d_wedge :]
            tu = u[:, self.triad_index]  # (B, 85, 3, D)
            tvv = vv[:, self.triad_index]
            def edge(i: int, j: int):
                return (
                    (tu[:, :, i] * tvv[:, :, j]).sum(-1)
                    - (tu[:, :, j] * tvv[:, :, i]).sum(-1)
                )
            e_ab, e_bc, e_ca = edge(0, 1), edge(1, 2), edge(2, 0)
            curl = e_ab + e_bc + e_ca
            scale = e_ab.abs() + e_bc.abs() + e_ca.abs() + 1e-6
            kappa = torch.tanh(curl / scale)
            edges = torch.stack([e_ab.abs(), e_bc.abs(), e_ca.abs()], dim=-1)
            max_edge = edges.max(dim=-1).values
            min_edge = edges.min(dim=-1).values
            stretch = (max_edge - min_edge) / (max_edge + 1e-6)
            curv_stats = torch.stack(
                [
                    kappa.mean(dim=1),
                    kappa.std(dim=1, unbiased=False),
                    (kappa > 0).float().mean(dim=1),
                    kappa.abs().mean(dim=1),
                    kappa.abs().max(dim=1).values,
                    kappa.max(dim=1).values,
                    kappa.min(dim=1).values,
                ],
                dim=1,
            )
            stretch_stats = torch.stack(
                [
                    stretch.mean(dim=1),
                    stretch.std(dim=1, unbiased=False),
                ],
                dim=1,
            )

            # --- soft curvature-bin histogram --------------------------
            dist = (kappa.unsqueeze(-1) - self.bin_centers.view(1, 1, -1)) ** 2
            bin_w = F.softmax(-dist / 0.05, dim=-1)  # (B,85,16)
            bin_hist = bin_w.mean(dim=1)  # (B,16)

            # --- global fabric codebook --------------------------------
            # Index by triad, bin, and a 4-way rail class (0..3).
            rail_class = torch.bucketize(self.triad_rail_sum, torch.tensor([-2.0, 0.0, 2.0], device=dev))
            idx = (
                torch.arange(TRIADS, device=dev).view(1, TRIADS, 1) * (self.N_BINS * 4)
                + torch.arange(self.N_BINS, device=dev).view(1, 1, self.N_BINS) * 4
                + rail_class.view(1, TRIADS, 1)
            )  # (1,85,16)
            fabric = self.fabric(idx)  # (1,85,16,d_code)
            code = (bin_w.unsqueeze(-1) * fabric).sum(dim=(1, 2))  # (B,d_code)

            # --- soft hot-triad embedding ------------------------------
            triad_w = F.softmax(p_at_least_2 * 5.0, dim=-1)  # (B,85)
            triad_code = triad_w @ self.triad_embed.weight  # (B,d_triad)

            parts = [
                    head_stats,                 # 7
                    rail_pos, rail_neg, rail_balance,  # 3
                    field_stats,                # 3
                    accepted_fraction, hot_fraction, field_quorum,  # 3
                    vote_hist,                  # 4
                    curv_stats,                 # 7
                    stretch_stats,              # 2
                    rail_hist,                  # 4
                    bin_hist,                   # 16
                    code,                       # d_code
                    triad_code,                 # d_triad
                ]
            if __import__("os").environ.get("GEOM_DEBUG"):
                print("GEOM SHAPES", [tuple(t.shape) for t in parts], file=__import__("sys").stderr)
            return torch.cat(parts, dim=1)

    def geometry_param_count(d_code: int = 64, d_triad: int = 16, d_wedge: int = 32) -> int:
        return sum(
            p.numel()
            for p in TorchHeadGeometry(d_code, d_triad, d_wedge).parameters()
        )


__all__ = [
    "HEADS",
    "TRAINABLE_HEADS",
    "VOID_HEAD",
    "NANNET_HEAD",
    "NAN_HEADS",
    "TRIADS",
    "PAIRS",
    "FIXED_TRIADS",
    "RAIL_SIGNS",
    "TRIAD_RAIL_SUM",
    "rev8",
    "pal16",
    "is_palindrome16",
    "pair_id",
    "pair_heads",
    "rail_sign",
    "hot_triads",
    "triad_votes",
    "head_field",
    "mirror_pair_field",
    "triangle_pair_ids",
    "triangle_rail_lanes",
    "triangle_curvature",
    "geometry_stats",
    "TorchHeadGeometry",
    "geometry_param_count",
]
