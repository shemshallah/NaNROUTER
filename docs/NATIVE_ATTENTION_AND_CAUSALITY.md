# Native attention projection and causal pair knockout

**Status:** native NaN16 sources and fixtures verified locally; CI promotion is
the next step. This document records the two new primitives and their limits.

## 1. Causal pair knockout / restore

`mth.mirror.pair.knockout.f32` operates on one canonical mirror pair:

```text
mode 0: backup lane 0/1 residuals -> zero both residual lanes
mode 1: restore both residual lanes from the backup
```

ABI:

| Register | Meaning |
|---|---|
| `r1` | pair id, 1..32640 |
| `r2` | backup, 52 float32 words |
| `r3` | mode 0 or 1 |

The kernel touches only:

```text
lane 0 residual words  base + 0..25
lane 1 residual words  base + 32..57
```

It never touches lane-0 metadata words `26..31`, the lane-1 reserved tail, or
any other pair. This is a physical evidence intervention for causal audits;
it is not semantic truth or an authorization operation.

The fixture seeds both lanes and metadata, saves/zeros/restores, checks exact
transport, verifies metadata locality, tests boundary pair 32640, and rejects
bad ids/modes. Observed: **6,617 steps PASS**.

## 2. Reusable 16→16 projection

`mth.attention.project16.f32` computes one affine projection:

```text
out[p] = bias[p] + sum(d=0..15) W[p*16+d] * x[d]
```

This is the Q/K/V projection seam. A caller invokes it three times with
different weight/bias sets. It is **not** a full attention block: it does not
compute scores, softmax, masking, or value aggregation.

The kernel preflights `x`, `W`, and `bias` for finiteness, accumulates each
output in caller scratch, rejects a non-finite projection before publishing,
and only then copies scratch to `out`. That makes rejection atomic.

Fixture coverage: identity, bias, a non-identity row, NaN `x/W/bias`, overflow,
output atomicity, and recovery. Observed: **45,779 steps PASS**.

## 3. How this connects to Round 042 and fluency

Round 042's causal audit deletes one indispensable native pair and requires the
model to abstain; restoration restores the answer. The knockout primitive gives
that intervention a native, metadata-local implementation.

The projection primitive is the next missing arithmetic seam for an attention
decoder. The native stack now has:

```text
projection (this kernel)
  -> optional Q/K/V calls
  -> score/softmax/log-softmax (softmax/log-softmax exist)
  -> candidate/value mixing (mix16 exists)
  -> cross-entropy (exists)
```

Still missing for a real attention block: native score formation, masking,
multi-head layout, and a jointly trained decoder contract.

## 4. Non-claims

- Knockout is not semantic deletion and does not enforce an ACL.
- Restore assumes the backup is valid and caller-owned.
- Projection is one affine layer, not full attention.
- No claim that these primitives improve language quality yet.
- Local fixtures are not CI verification or a live deployment.
