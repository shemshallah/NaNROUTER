# MTH graph fold ABI

Status: source-written and **native_verified** by a local NaN16 `nan_cli` run on
2026-11-06. Evidence and limitations are in sections 5 and 6. This is not a CI
claim.

## 1. Scope

This ABI defines the exact, unnormalized fold/unfold vector transforms for the
even 256-position ring and the odd 255-head aperture.

Every scalar is one IEEE binary32 value stored in the 32-bit payload of one
NaN16 word. There is no Q16.16 state, scaling, saturation, hidden allocation, or
host-side arithmetic. Float32 is used because sums of Q16.16 values can overflow
the fixed raw range and because the wave/readout lane is already float32.

The transforms are algebraically exact inverses:

- the 256 transform pairs `i` with `255-i`;
- the 255 transform pairs `i` with `254-i` and leaves index `127` fixed.

In binary32 the only rounding is the normal IEEE round-to-nearest-even behavior
of `FADD`/`FSUB`/`FMUL`. Multiplication by the unnormalized inverse constant
`0.5` is exact. A round trip is therefore bit-exact whenever each forward sum
and difference is itself exactly representable. The fixture uses small integers
for that reason.

## 2. Entry points

All addresses are NaN16 word indices. `r13` must be `1`. Spans must be readable
or writable as declared and must not overlap. The kernels do not validate
addresses, NaNs, infinities, or aliasing; those are caller/runner
preconditions. Under those preconditions each entry point returns `r1=1`.
There is no partial-output or failure return.

### 2.1 `mth_graph_fold_256_vector`

| Register | Meaning |
|---|---|
| `r1` | input `x[256]`, float32 |
| `r2` | plus output `p[128]`, float32 |
| `r3` | minus output `m[128]`, float32 |
| `r13` | `1` |

For `i=0..127`:

```text
p[i] = x[i] + x[255-i]
m[i] = x[i] - x[255-i]
```

Returns `r1=1`. Clobbers `r1-r10`; leaves `r11-r15` unchanged.

### 2.2 `mth_graph_fold_255_vector`

| Register | Meaning |
|---|---|
| `r1` | input `x[255]`, float32 |
| `r2` | plus output `p[128]`, float32 |
| `r3` | minus output `m[127]`, float32 |
| `r13` | `1` |

For `i=0..126`:

```text
p[i] = x[i] + x[254-i]
m[i] = x[i] - x[254-i]
p[127] = x[127]
```

The middle head belongs only to the plus block; the minus block has exactly 127
entries. Returns `r1=1`. Clobbers `r1-r10`; leaves `r11-r15` unchanged.

### 2.3 `mth_graph_fold_256_unfold`

| Register | Meaning |
|---|---|
| `r1` | plus input `p[128]`, float32 |
| `r2` | minus input `m[128]`, float32 |
| `r3` | output `x[256]`, float32 |
| `r13` | `1` |

For `i=0..127`:

```text
x[i]     = (p[i] + m[i]) * 0.5
x[255-i] = (p[i] - m[i]) * 0.5
```

The multiplier is the exact binary32 constant `0.5` (`0x3F000000`).
Returns `r1=1`. Clobbers `r1-r12`; leaves `r13-r15` unchanged.

No 255-entry unfold entry point is provided by this ABI. If one is added later,
its inverse is:

```text
x[i]     = (p[i] + m[i]) * 0.5, i=0..126
x[254-i] = (p[i] - m[i]) * 0.5, i=0..126
x[127]   = p[127]
```

## 3. Unnormalized basis

The forward and inverse operators here use the **unnormalized** pair basis:

```text
p_i = x_i + x_j
m_i = x_i - x_j
x_i = (p_i + m_i) / 2
x_j = (p_i - m_i) / 2
```

where `j=255-i` for the even transform and `j=254-i` for the odd transform.

The normalized basis in the graph-spectral plan is:

```text
q_i+ = (e_i + e_j) / sqrt(2)
q_i- = (e_i - e_j) / sqrt(2)
```

Its forward coefficients carry a `1/sqrt(2)` factor and its inverse needs a
`sqrt(1/2)` multiplier, not `0.5`. **Normalized q+/- coefficients must not be
passed to this unfold kernel**, and normalized coefficients must not be
reconstructed with it. `sqrt(1/2)` is irrational and would not preserve the
bit-exact fixture behavior; the normalized basis is deliberately not used here.

## 4. Authorization caveat

A mathematical symmetry is not an authorization symmetry.

The 256-position transform includes every ring position, including the NANNET
port at index `255`, and it may pair that port or a learning head with a
reserved BSR control head. The six BSR control heads are `0,4,5,6,7,8`; they are
read-only for wave writes. The 255-head transform excludes the NANNET port but
its mirror pairs can still cross a reserved BSR control head.

Therefore:

- these kernels are readout/transform arithmetic only;
- a fold result does not grant write authority to any head;
- if a mirror pair maps a learning head to a reserved control head, the fold is
  read-only or excluded for writes;
- write authorization must be reconciled by the signed head atlas, not by the
  mathematical `J` operator.

The 256 fold is a ring/readout optimization. The 255 fold is the head-only
aperture, but it is still governed by the same pair-crossing caveat.

## 5. Certificate status

A 256x256 centrosymmetry certificate (`M_ij = M_{255-i,255-j}`) is **deferred**;
no certificate entry point is present in this source.

Reasons:

1. A certificate is a property of the operator, not of these vector transforms.
   Checking `M_ij = M_{255-i,255-j}` without assuming the conclusion requires
   access to the paired entries across the full matrix.
2. In this NaN16 layout each float32 coefficient occupies one 8-byte word.
   A full 256x256 float32 matrix is 65,536 coefficients = 524,288 bytes of word
   storage, which is the entire declared 512 KiB guest working set before any
   code, vectors, or scratch is added. A test that materializes the full matrix
   cannot honor that budget.
3. A faithful fast-path certificate needs a paged/streaming or digest-bound
   descriptor ABI that can attest both paired blocks without storing an
   unguarded dense copy. That is a separate interface and is not required by
   the vector fold ABI.

Adding a certificate later does not change these three entry points.

## 6. Evidence

Owned files:

- `mth/nan16/mth_graph_fold.nas`
  SHA-256 `f9c54a02e8a9036b55954cd47ae453f448db60545cbd4dac0cc0dc017c76e928`
- `mth/tests/mth_graph_fold_test.nas`
  SHA-256 `4a0d2dd9ea970b3f3e41a0fd75cd5237db7cd03f01834ed402444bbaac01a589`
- `docs/MTH_GRAPH_FOLD_ABI.md`

Assembly:

```sh
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=emit mth/tests/mth_graph_fold_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/fold.nan
```

The generated image reports `words 2318`; `CMD=check` reports
`check: 0 mismatches`.

Execution:

```sh
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/fold.nan \
  --steps 4000000 --serial
```

Observed output:

```text
[nan_cli] nan-text: 9281 steps, rc=3, pc=187, trap=''
MTH GRAPH FOLD VECTOR PASS
```

`rc=3` is the native HALT return in this harness; there is no trap.

The fixture covers:

- 256 fold with `x[0]=1.0`, `x[255]=2.0` giving `plus[0]=3.0` and
  `minus[0]=-1.0`;
- 256 fold with `x[1]=4.0`, `x[254]=6.0` giving `plus[1]=10.0` and
  `minus[1]=-2.0`;
- the last even pair `i=127` and untouched sentinels at `plus[128]` and
  `minus[128]`;
- exact unfold round trip over all 256 words;
- 255 fold with `x[0]=1.0`, `x[254]=2.0` giving `plus[0]=3.0` and
  `minus[0]=-1.0`, all 127 pair outputs checked in a loop;
- fixed middle `x[127]=7.0` giving `plus[127]=7.0`;
- 255 count checks: `plus[128]` and `minus[127]` remain untouched `77`
  sentinels.

## 7. Limitations

- No 255-entry unfold entry point is included.
- No centrosymmetry certificate or matrix fold is included (section 5).
- No NaN/Inf validation: IEEE NaN payload behavior follows the NaN16 FPU rules.
  Finite wave data must be supplied by the caller if finite output is required.
- No overlap/alias support is promised. Callers must provide disjoint spans.
- Round trips are bit-exact only when the forward sum and difference are
  exactly representable in binary32; for general float32 inputs the transform
  has ordinary IEEE rounding, and no error-bound proof is claimed here.
- The kernels enforce no authorization policy. The runner and signed atlas must
  enforce reserved BSR heads and the NANNET port boundary.
- These are standalone kernels; they are not yet integrated into the wave
  engine, router, or eigen-solver path.
- No throughput or latency claim is made.
