# MTH ring256 Laplacian and graph-H wave energy

Status: source-written and locally executed with the canonical NaN0S toolchain
on 2026-11-07. This is local execution evidence, not a CI claim.

## 1. Scope

This document freezes:

- `mth/nan16/mth_ring256_laplacian.nas` — exact C256 cycle Laplacian;
- `mth/nan16/mth_negate256_f32.nas` — exact float32 sign negation;
- `mth/tests/mth_ring256_laplacian_test.nas` — operator oracle;
- `mth/tests/mth_ring_wave_energy_test.nas` — four-step graph-H energy fixture.

The ring is the undirected cycle over all 256 positions:

```text
0 - 1 - ... - 254 - 255 - 0
```

Positions are flat NaN16 word addresses with unit increment `r13 = 1`. Every
scalar is one IEEE binary32 value in the 32-bit payload of one word. No host
math, no Q16.16 scaling, no allocation, no fused multiply-add, and no
reordering are used.

## 2. Ring256 Laplacian ABI

Kernel: `mth_ring256_laplacian_f32`.

```text
(Lu)[i] = 2*u[i] - u[(i-1) mod 256] - u[(i+1) mod 256]
```

| Register | Meaning |
|---|---|
| `r1` | `u`, 256 float32 words (input) |
| `r2` | `out`, 256 float32 words (output) |
| `r13` | `1` |
| `r1` on return | `1` |

The caller supplies non-overlapping input and output spans. The kernel is a
leaf routine: it makes no calls and uses no static scratch. It clobbers
`r3-r8`, preserves `r13`, and does not use `r15`.

Implementation order:

1. boundary vertex 0: `2*u[0] - u[1] - u[255]`;
2. interior vertices 1..254 in increasing order;
3. boundary vertex 255: `2*u[255] - u[254] - u[0]`.

All arithmetic is `FADD`/`FSUB` performed by the NaN16 float unit with normal
binary32 IEEE round-to-nearest-even behavior. No host math is involved.

### 2.1 Fixture

`mth/tests/mth_ring256_laplacian_test.nas` checks:

- impulse at vertex 0 -> `[2,-1,0,...,0,-1]`, including the wrapped
  neighbor at index 255 and zero at index 254;
- constant `1.0` state -> exactly zero at all 256 positions;
- impulse at interior vertex 128 -> `2` at 128, `-1` at 127 and 129, and `0`
  at vertex 0.

## 3. Negate256 ABI

Kernel: `mth_negate256_f32`.

```text
out[i] = -in[i]
```

| Register | Meaning |
|---|---|
| `r1` | `in`, 256 float32 words (input) |
| `r2` | `out`, 256 float32 words (output) |
| `r13` | `1` |
| `r1` on return | `1` |

Negation is an exact IEEE sign-bit flip implemented with `BOOL.6` (XOR) against
`0x80000000`, not an arithmetic subtraction. It flips the sign of signed zeros
and NaN payloads without changing the remaining bits. The kernel is leaf,
clobbers `r3-r7`, preserves `r13`, and uses no static scratch. The caller
supplies non-overlapping spans.

This kernel is used by the energy fixture to form `a = -L u` from the
Laplacian output.

## 4. Graph-H wave energy fixture

`mth/tests/mth_ring_wave_energy_test.nas` includes:

- `mth_ring256_laplacian.nas`
- `mth_negate256_f32.nas`
- `mth_graph_wave.nas` (`mth_graph_wave_step_f32`)
- `mth_graph_step_energy_256.nas` (`mth_graph_step_energy_256_f32`)

### 4.1 Initial state

```text
u = [1, 0, 0, ..., 0]      (unit impulse at position 0)
v = 0
dt = 0.1                    (0x3DCCCCCD)
gamma = 0
```

For this impulse:

```text
L u = [2, -1, 0, ..., 0, -1]
E0  = 0.5*u^T L u = 0.5 * 1 * 2 = 1.0
```

The fixture computes `Lu`, `a = -Lu`, and the step energy before the loop and
requires the initial total to be exactly `1.0` (`0x3F800000`).

### 4.2 Four composed steps

Each step performs, in order:

1. `Lu = mth_ring256_laplacian_f32(u)`;
2. `a = mth_negate256_f32(Lu)`;
3. `(u_next, v_next) = mth_graph_wave_step_f32(u, v, a, dt, gamma)`;
4. `mth_ring_wave_copy256` copies `u_next -> u` and `v_next -> v`.

The copy helper is a fixed 256-word loop using `r1=source`, `r2=destination`.
All state arrays are fixed `.org` regions:

| Region | Base word |
|---|---|
| `u` | 1024 |
| `v` | 2048 |
| `Lu` | 3072 |
| `a` | 4096 |
| `u_next` | 5120 |
| `v_next` | 6144 |
| energy (3 words) | 7168 |
| `dt`, `gamma`, `steps` | 7232, 7233, 7234 |

The five 256-word wave-step spans are pairwise disjoint, satisfying the
velocity-Verlet kernel's layout preflight.

### 4.3 Final energy and tolerance

After the fourth step the fixture recomputes `Lu`, `a = -Lu`, and calls
`mth_graph_step_energy_256_f32`:

```text
kinetic   = 0.5 * sum_i v[i]^2
potential = 0.5 * sum_i u[i] * (-a[i]) = 0.5 * u^T L u
total     = kinetic + potential
```

The final total must lie in `[0.9, 1.1]`, i.e. within `0.1` of the initial
`1.0`. The bounds are exact binary32 constants:

| Bound | Bits |
|---|---|
| lower `0.9` | `0x3F666666` |
| upper `1.1` | `0x3F8CCCCD` |

Observed final energy words from the canonical run:

| Quantity | Bits | Approximate value |
|---|---|---|
| kinetic | `0x3EDA3BF8` | 0.42623878 |
| potential | `0x3F17E5CF` | 0.59335035 |
| total | `0x3F8281E6` | 1.01958919 |

The measured drift is about `0.0196`, well inside the allowed `0.1`.

### 4.4 Predicate semantics used

On this canonical `nan_cli`/`nmk` toolchain, `JMP[GT]` after `FCMP A,B`
executes when `A > B`. This was verified with a tiny probe before writing the
fixture: integer `1` vs `2` and float `1.0` vs `2.0` did not branch, while the
reversed pairs did. The fixture therefore checks:

```text
FCMP total, upper ; JMP[GT] fail     ; reject total > 1.1
FCMP lower, total ; JMP[GT] fail     ; reject total < 0.9
```

Anyone porting this fixture to another toolchain should re-verify the
predicate convention rather than rely on the mnemonic name.

## 5. Evidence

Commands and exact output (step budget 20,000,000 in both runs):

```sh
cd /data/data/com.termux/files/home/NaNROUTER
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_ring256_laplacian_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/ring256_laplacian.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/ring256_laplacian.nan \
  --steps 20000000 --serial
```

```text
words 2062
[nan_cli] nan-text: 19736 steps, rc=3, pc=150, trap=''
MTH RING256 LAPLACIAN PASS
```

```sh
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_ring_wave_energy_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/ring_wave_energy.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/ring_wave_energy.nan \
  --steps 20000000 --serial
```

```text
words 7310
[nan_cli] nan-text: 86374 steps, rc=3, pc=326, trap=''
MTH RING WAVE ENERGY PASS
```

`rc=3` is the harness HALT result used by the existing MTH fixtures; the
process exit status was `0`, the serial output contains `PASS`, and no trap was
reported. `--peek 7168:3` on the energy image returned
`3EDA3BF8 3F17E5CF 3F8281E6`.

## 6. Limitations

- Fixed length 256, contiguous word-index spans. No stride, tiling, paging,
  variable vertex count, or non-unit increment.
- The two leaves trust the caller's layout contract (non-overlapping spans).
  They do not preflight addresses or return a layout error.
- Float32 payloads are not validated. NaN and infinity propagate through IEEE
  arithmetic; the ring operator does not sanitize them.
- The graph-H fixture is exactly one impulse, one `dt = 0.1`, `gamma = 0`, and
  four steps. It is not a CFL/stability sweep and does not establish universal
  energy conservation.
- The `0.1` tolerance applies only to this fixture. Float32 drift grows with
  longer runs and with other initial states or time steps.
- The final potential uses `a = -L u` recomputed at the final state, as
  required by the step-energy metric; it is not a running accumulator.
- The initial energy is checked exactly because the impulse makes it exactly
  representable. The final energy is checked as an interval, not bitwise.
- Negation is a sign-bit flip; callers that need arithmetic `0 - x` semantics
  for NaN/signed-zero corner cases should not substitute this kernel blindly.
- Local `nan_cli` evidence only. No CI workflow, digest registry, capability
  registry, or dispatch claim is made here.
