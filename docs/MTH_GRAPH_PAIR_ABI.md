# MTH 128x128 pair-space actions (NaN16 float32)

This document covers two separate kernels:

1. `mth/nan16/mth_graph_pair.nas` — the full dense 128x128 pair-space action
   `U' = L U + U L^T`.
2. `mth/nan16/mth_graph_pair_rank1_128.nas` — the earlier bounded rank-1
   prototype. It is unchanged and is documented in section 2.

Both use only NaN16 float32 arithmetic (`FADD`/`FSUB`/`FMUL`); there is no
host math, no FMA, no reassociation, and no fast-math mode.

## 1. Full dense 128x128 pair-space action

### 1.1 Scope

`mth/nan16/mth_graph_pair.nas` computes

```text
U' = L U + U L^T
```

for dense 128x128 row-major float32 `L` and `U`:

```text
U'[i,j] = sum(k=0..127) L[i,k]*U[k,j]
        + sum(k=0..127) U[i,k]*L[j,k]
```

All three matrices are dense. This is one bounded 128x128 action, not the
256x256 pair space.

### 1.2 ABI

Call with `r13=1`:

| Register | Meaning |
| --- | --- |
| `r1` | `L`, 16,384 float32 payloads (128x128, row-major) |
| `r2` | `U`, 16,384 float32 payloads (128x128, row-major) |
| `r3` | output `U'`, 16,384 float32 payloads (128x128, row-major) |
| `r13` | 1 |
| return | `r1=1` |

Register effects: `r0`–`r12` and `r14` are clobbered; `r13` remains 1;
`r15` is preserved, so ordinary `CALL`/`RET` works. The kernel is leaf-only:
it makes no `CALL` and uses no static slots. `r0` is set to 0 on entry and
restored to 0 before return.

### 1.3 Layout, overlap precondition, and memory bound

Each matrix is a contiguous span of 16,384 words. Element `(i,j)` is at

```text
base + 128*i + j          i,j in 0..127
```

The three spans must be pairwise non-overlapping. This is a caller
precondition; the kernel does not detect overlap or aliasing. `L` and `U`
are read-only. The output need not be initialized because every word is
written. In particular, the output span may not overlap either input span.

Memory: `3 * 16,384 = 49,152` words, which fits the 65,536-word guest. The
kernel itself needs no additional matrix-sized scratch. The committed
fixture places the arrays at:

| Array | Base word | Span |
| --- | ---: | --- |
| `L` | 1,024 | 1,024..17,407 |
| `U` | 17,408 | 17,408..33,791 |
| output | 33,792 | 33,792..50,175 |

Those addresses are a fixture choice, not part of the ABI.

### 1.4 Deterministic accumulation order

All arithmetic is float32 round-to-nearest-even with separate rounded
operations. The kernel uses two term accumulators, each advanced in
increasing `k`; there is no interleaving and no reordering:

```text
Pass 1 (increasing i, then increasing j):
    P[i,j] = +0.0f
    for k = 0..127:
        P[i,j] = P[i,j] + L[i,k]*U[k,j]
    output[i,j] = P[i,j]

Pass 2 (increasing i, then increasing j):
    Q[i,j] = +0.0f
    for k = 0..127:
        Q[i,j] = Q[i,j] + U[i,k]*L[j,k]
    output[i,j] = P[i,j] + Q[i,j]
```

Each product is one rounded `FMUL`; each accumulator update is one rounded
`FADD`; the two term sums are combined by one final rounded `FADD`. There
is no FMA, compensated summation, or extended precision. `L[j,k]` in pass 2
is the transpose access that forms `U L^T`; it is not a separate transpose
copy.

This is the allowed "two accumulators" variant: each term sum is accumulated
over `k=0..127` in order, and the only combination of the two sums is the
single final `FADD`. It does not compute a 256-term running sum in one
accumulator.

### 1.5 Fixture

`mth/tests/mth_graph_pair_test.nas` builds the required fixture
programmatically:

- `L = 2*I`: zero all 16,384 words, then write `2.0` at the 128 diagonal
  positions (word stride 129).
- `U = 0` except for five `1.0` entries at `(0,0)`, `(1,2)`, `(17,5)`,
  `(64,64)`, and `(127,127)`.
- Since `L=2I`, `U' = 2U + 2U = 4U`. The fixture checks all five seeded
  entries equal `4.0` and checks three untouched entries
  (`(0,1)`, `(2,2)`, `(127,0)`) equal `+0.0`.
- The fixture then zeros `U` again, reruns the kernel, and verifies every one
  of the 16,384 output words is `+0.0`.

The fixture also spot-checks the constructed `L` at `(0,0)`, `(0,1)`,
`(1,1)`, and `(127,127)`.

Exact command and observed result:

```sh
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=emit mth/tests/mth_graph_pair_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/pairfull.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/pairfull.nan \
  --steps 100000000 --serial
```

```text
words 50192
[nan_cli] nan-text: 68195822 steps, rc=3, pc=202, trap=''
MTH GRAPH PAIR FULL 128 PASS
```

`rc=3` is `NAN_HALTED`; `trap=''`. The run used 68,195,822 of the
100,000,000-step budget. `nmk -v CMD=check` on the emitted image reports
0 mismatches.

### 1.6 Independent cross-check

A temporary harness outside the repository filled `L` and `U` with
non-symmetric small-integer patterns:

```text
L[i,j] = (3*i + 5*j) mod 7 - 3
U[i,j] = (11*i + 13*j) mod 9 - 4
```

It ran one kernel call and left the output in guest memory. The host-side
check read all 16,384 output words with `--peek` and compared them bit-for-bit
with an independent NumPy float32 reference that performs the same two
accumulations in increasing `k` and the same final `FADD`. Result: all
16,384 words matched. That one-call run used 34,279,198 steps. This
cross-check is evidence for indexing/transpose correctness on a
non-symmetric input, but it is not part of the committed fixture.

### 1.7 Evidence status and limitations

- **Verified:** the committed fixture assembles and runs to `PASS` on the
  stated toolchain within the 100,000,000-step budget.
- **Verified:** `L=2I` gives `4U` for the five seeded entries, untouched
  entries are `+0.0`, and zero `U` gives an all-zero output.
- **Verified:** a temporary non-symmetric integer-pattern run matched an
  independent NumPy float32 simulation bit-for-bit for all 16,384 words.
- **Not verified:** general random float32 inputs with rounding stress
  against an independent reference. The committed fixture is exact-power-of-
  two arithmetic, and the cross-check used small integers; neither exercises
  accumulated rounding error or extreme exponents.
- **Not covered:** NaN/Inf input policy beyond normal NaN16 FP propagation,
  array-overlap detection, concurrency/reentrancy stress with shared static
  state (there is none), and performance beyond the measured step count.
- **Not covered:** 256x256 full pair space. Four dense 65,536-word matrices
  (`L`, `U`, output, and any transpose/temporary copy) would need at least
  262,144 words, far beyond one 65,536-word guest. A 256x256 action must be
  paged/tiled, with each tile fitting the guest and accumulation order
  preserved across pages; this kernel does not attempt that.

## 2. Rank-1 128-head prototype (separate kernel)

Status: source-written and locally executed with the canonical NaN0S
toolchain; CI promotion pending. This prototype is unchanged by the full
dense action above.

### 2.1 Scope

`mth/nan16/mth_graph_pair_rank1_128.nas` implements the bounded rank-1
action of the product-graph Laplacian:

```text
U = L (u v^T) + (u v^T) L^T
  = (Lu) v^T + u (Lv)^T
U[i,j] = Lu[i]*v[j] + u[i]*Lv[j]
```

where `L` is the C128 ring Laplacian:

```text
(Lx)[i] = 2*x[i] - x[(i-1) mod 128] - x[(i+1) mod 128]
```

This is the 128-head prototype. Full 256x256 pair-space state must be
paged; it is never materialized as one dense guest object.

### 2.2 ABI

All scalars are float32 payloads. `r13=1`.

| Register | Meaning |
| --- | --- |
| `r1` | u, 128 float32 |
| `r2` | v, 128 float32 |
| `r3` | output U, 128x128 float32, row-major (16,384 words) |
| `r4` | caller-owned scratch, 256 float32 (`Lu[0..127]`, `Lv[0..127]`) |
| `r13` | 1 |
| return | `r1=1` success |

Input and output spans must not overlap. The kernel is leaf-only: no
`CALL`, no static slots, no host math. It uses `FADD`, `FSUB`, `FMUL` in
increasing `i,j` order.

Memory: 128 + 128 + 16,384 + 256 = 16,896 words, well inside the
65,536-word guest.

### 2.3 Fixture

`mth/tests/mth_graph_pair_rank1_128_test.nas` uses:

- `u[0]=1.0`, all other `u=0`;
- `v=1.0` everywhere;
- expected `Lu=[2,-1,0,...,0,-1]`, `Lv=0`;
- therefore `U[i,j]=Lu[i]`.

Checks: `U[0,0]=2`, `U[0,1]=2`, `U[1,0]=-1`, `U[127,0]=-1`,
`U[127,1]=-1`, `U[2,0]=0`.

Local canonical run:

```text
MTH GRAPH PAIR RANK1 128 PASS
252,060 steps, rc=3/HALT
```

### 2.4 Limitations

- Only C128 ring Laplacian; general sparse `L` and 255/256-head versions
  are separate.
- Only rank-1 factors; a general U needs the full matrix-free or paged
  operator (the dense 128x128 kernel in section 1 covers one bounded dense
  case).
- No overlap validation; caller precondition.
- No low-rank coupling term `sum_r B_r ⊗ C_r` yet.
- The full 65,536-mode product space is not verified by this fixture; this
  is one bounded action.
