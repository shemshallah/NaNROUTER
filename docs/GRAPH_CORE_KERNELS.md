# MTH graph core kernels

Status: the three kernels below are **native_verified locally** (2026-11-07) by
the canonical NaN16 assembler and `nan_cli` execution harness. They are
registered with `status: native_verified` and `ci_verified: false` in
`spec/wave-capabilities.json`; canonical CI has not executed this revision.
The filter is a bounded degree-2 polynomial prototype only. This document does
**not** claim D-01, D-02, D-03, D-04, or any RSS controller/filter-completion
gate.

## 1. Shared CSR descriptor

All three kernels consume the same bounded canonical CSR view already used by the
sparse graph Laplacian and connected-component kernels:

- `row_offsets`: 257 U32 words; `offsets[0] = 0`,
  `offsets[256] = edge_count`, monotone nondecreasing.
- `neighbors`: `edge_count` U32 words; each endpoint is a `Head` index
  `0..255`; each row is sorted, duplicate-free, and has no self-loop.
- `edge_count`: `0..65,280`; each row has at most 255 entries. A symmetric
  simple graph stores every undirected edge twice.
- The graph is immutable and bound to a graph digest. Symmetry and reciprocal
  equality are descriptor/runner obligations; the kernels independently
  preflight count bounds, offsets, endpoints, row ordering, self-loops, and
  their numeric fields.
- Input, output, and scratch spans must not overlap. All validation precedes
  the first output write, so rejected descriptors leave outputs unchanged.

This CSR is a derived operator view. It does not rewrite the directed relation
rails, `W`, `W_s`, `W_a`, hyperedges, or the semantic ledger.

## 2. `mth_graph_degree.nas`

Source: `mth/nan16/mth_graph_degree.nas`
Entry point: `mth_graph_degree_256`
Fixture: `mth/tests/mth_graph_degree_test.nas`
Manifest id: `mth.graph.degree.256.u32`
Workspace: 0 words (caller-owned pages only)

### Operator

For each `i` in `0..255`:

```
degree[i]          = |{ j : (i,j) in E }|
weighted_degree[i] = sum_{j in N(i)} w_ij
```

Weights are U8 integers `1..255`, scale exactly 1 (not Q0.8). For an
unweighted graph the caller supplies an all-ones weights page, so
`weighted_degree == degree`.

### ABI

| Register | Meaning |
|---|---|
| `r1` | `row_offsets`, 257 U32 words |
| `r2` | `neighbors`, `edge_count` U32 words |
| `r3` | `weights`, `edge_count` U32 storage words; upper 24 bits zero, low U8 in `[1,255]` |
| `r4` | `edge_count`, `0..65,280` |
| `r5` | `degree_out`, 256 U32 words |
| `r6` | `weighted_out`, 256 U32 words |
| `r13` | constant `1` |
| return | `r1 = 1` success, `r1 = 0` malformed count/CSR/weight descriptor |

Clobbers `r1-r12` and `r14`; leaf routine, no static scratch, no `CALL`s.

### Numeric bound

A row has at most 255 entries and a weight is at most 255:

```
0 <= weighted_degree[i] <= 255 * 255 = 65,025 < 2^16.
```

Both outputs are exact U32 integers. There is no rounding, saturation,
floating-point operation, or wide multiplication.

### Fixture evidence

The fixture passes locally under `nan_cli` with marker
`MTH GRAPH DEGREE 256 PASS` after 48,117 guest steps. It checks:

1. weighted path `0--1--2--3` with CSR-aligned weights `[2,2,3,3,5,5]`:
   degrees `[1,2,2,1]`, weighted degrees `[2,5,8,5]`;
2. isolated vertices `4..255` have exactly zero degree and weighted degree;
3. unit weights make weighted degree equal degree for all 256 vertices;
4. an empty graph (`edge_count = 0`) yields all-zero outputs;
5. a zero weight rejects with both output spans unchanged;
6. nonzero `offsets[0]` rejects with the output span unchanged.

## 3. `mth_graph_pattern.nas`

Source: `mth/nan16/mth_graph_pattern.nas`
Entry point: `mth_graph_pattern_256`
Fixture: `mth/tests/mth_graph_pattern_test.nas`
Manifest id: `mth.graph.pattern.256.u32`
Workspace: 512 caller-owned U32 words = 4,096 bytes (256 degree scratch +
256 BFS queue), far below the 2 MiB guest ceiling.

### Signature

For each vertex `i`:

```
signature[i] = (shell[i] << 24) | (degree[i] << 16) | neighbor_degree_sum[i]
```

- `degree[i]` is the row length, `0..255`.
- `neighbor_degree_sum[i] = sum_{j in N(i)} degree[j]`, bounded by
  `255 * 255 = 65,025`, which fits exactly in 16 bits.
- `shell[i]` is the BFS graph distance from the caller-supplied source,
  clamped to `0..254`; `255` means unreachable. The clamp deliberately avoids
  a collision between a legitimate distance of 255 and the unreachable
  sentinel. The signature is therefore lossy at the top shell only.
- The three fields are disjoint, so every signature is a bounded U32 and the
  top byte is exactly the shell field.

The signature is deterministic for identical CSR pages, source, kernel
version, and digest. It is a pattern fingerprint only; it never replaces the
exact source relations, graph digest, or semantic validation.

### ABI

| Register | Meaning |
|---|---|
| `r1` | `row_offsets`, 257 U32 words |
| `r2` | `neighbors`, `edge_count` U32 words |
| `r3` | `edge_count`, `0..65,280` |
| `r4` | source vertex, `0..255` |
| `r5` | `signature_out`, 256 U32 words |
| `r6` | `degree_scratch`, 256 caller-owned U32 words |
| `r7` | `queue_scratch`, 256 caller-owned U32 words |
| `r13` | constant `1` |
| return | `r1 = 1` success, `r1 = 0` malformed count/CSR/source |

Clobbers `r1-r12` and `r14`; leaf routine, no static scratch, no `CALL`s.
The kernel validates source range, edge count, offsets, endpoints, sorted
uniqueness, and self-loops before touching `signature_out`. BFS marks a vertex
when it is enqueued, so every vertex enters the queue at most once and the
256-word queue cannot overflow for a validated simple graph. The output page is
used as the temporary shell page and is fully packed on success.

### Fixture evidence

The fixture passes locally under `nan_cli` with marker
`MTH GRAPH PATTERN 256 PASS` after 56,063 guest steps. It checks:

1. path `0--1--2--3` plus 252 isolates, source `0`:
   signatures `0x00010002`, `0x01020003`, `0x02020003`, `0x03010002`, and
   exactly `0xFF000000` for every isolated vertex (bounded top byte);
2. the same path with source `2`: shell bits change while degree and
   neighborhood fields stay fixed;
3. triangle `0--1--2` plus isolates, source `0`: all triangle vertices have
   degree 2 and neighbor-degree sum 4, with shells `0,1,1`;
4. source `256` rejects before changing the output page;
5. nonzero `offsets[0]` rejects before changing the output page.

## 4. `mth_graph_filter.nas`

Source: `mth/nan16/mth_graph_filter.nas`
Entry point: `mth_graph_filter_poly2_q16_16`
Fixture: `mth/tests/mth_graph_filter_test.nas`
Manifest id: `mth.graph.filter.poly2.q16.16`
Workspace: 528 caller-owned words = 4,224 bytes (256-word `Lx` scratch +
256-word `L^2x` scratch + 16-word control frame), far below the 2 MiB ceiling.

### Operator

For each vertex `i`:

```
y_i = c0*x_i + c1*(Lx)_i + c2*(L^2 x)_i
```

`L` is the exact unweighted symmetric simple-graph Laplacian from the shared
canonical CSR descriptor. CSR was chosen over a precomputed `L`/`Lx` page
because the kernel can derive and bound both `Lx` and `L^2x` locally from the
same validated descriptor; a precomputed operator page would enlarge the ABI
and move the decisive validation to the caller. The filter is a declared
degree-2 polynomial in `L`; it does not form the 65,536 x 65,536
Kronecker/pair-space matrix and does not take a dense Laplacian. The `Lx` and
`L^2x` vectors are 256 words each. No Chebyshev recurrence, adjacency-only
polynomial, adaptive coefficient generation, or RSS `FILTER` verb controller
is implemented here.

### ABI

| Register | Meaning |
|---|---|
| `r1` | `row_offsets`, 257 U32 words |
| `r2` | `neighbors`, `edge_count` U32 words |
| `r3` | `x`, 256 signed I32 Q16.16 words, each in `[-4096,+4096]` |
| `r4` | coefficients, 3 signed I32 Q16.16 words, each in `[-65536,+65536]` |
| `r5` | `output`, 256 signed I32 Q16.16 words |
| `r6` | caller-owned `scratch_lx`, 256 signed I32 words |
| `r7` | caller-owned `scratch_l2x`, 256 signed I32 words |
| `r8` | `edge_count`, `0..65,280` |
| `r9` | caller-owned 16-word U32 control scratch frame |
| `r13` | constant `1` |
| return | `r1 = 1` success; `r1 = 0` invalid count/state/coefficient; `r1 = 2` invalid offsets/degree; `r1 = 3` invalid endpoint/order/self-loop |

Clobbers `r1-r12` and `r14`; preserves `r13`. The kernel uses two internal
`CALL` helpers and no static scratch. Input, output, and all scratch spans must
not overlap.

### Numeric contract

- `x` is Q16.16 in `[-4096,+4096]` (real `[-1/16,+1/16]`).
- Each row has at most 255 neighbors, so the exact signed-I32 bounds are:

  ```
  |(Lx)_i|   <= 255 * 2^13 = 2,088,960
  |(L^2x)_i| <= 255 * 2 * 2,088,960 = 255^2 * 2^14
             = 1,065,369,600 < 2^31
  ```

- Coefficients are Q16.16 in `[-1,+1]` (raw `[-65536,+65536]`).
- Each `c_k * v_k` product is formed exactly as a signed 64-bit
  two's-complement integer by a 17-step shift-and-add loop. The three Q32.32
  products sum to less than `2^48`.
- The 64-bit sum is shifted right by 16 with arithmetic truncation toward
  negative infinity and stored as I32 Q16.16. The declared bounds prove the
  final magnitude is at most `1,067,462,656 < 2^31`, so there is no rounding
  beyond that one truncation, no saturation, and no wrap.

### Validation and fail-closed behavior

The kernel validates the edge count, `offsets[0] = 0`, monotone offsets, final
offset equal to `edge_count`, row degree `<=255`, endpoint range, strictly
sorted unique neighbors, no self-loops, all 256 `x` words, and all three
coefficients. All validation finishes before the first vector-scratch or
output write. A rejected descriptor therefore leaves `output`, `scratch_lx`,
and `scratch_l2x` unchanged. The 16-word control frame is written first and may
be clobbered on rejection. Symmetry and reciprocal entries remain bound by the
caller/runner graph digest; the kernel itself does not prove symmetry.

### Fixture evidence

The fixture passes locally under `nan_cli` with marker
`MTH GRAPH FILTER Q16.16 PASS` after 621,536 guest steps. The graph is the path
`0--1--2--3` plus isolated vertices `4..255`, with
`x = [0,4096,2048,-4096,0,...]`. Exact hand-checkable vectors are:

```
Lx   = [ -4096,  6144, 4096, -6144, 0, ...]
L^2x = [-10240, 12288, 8192, -10240, 0, ...]
```

The fixture checks:

1. `c=[+1,+1/2,-1/4]` -> `y=[512,4096,2048,-4608,0,...]`;
2. `c=[+1,0,0]` -> `y=x`;
3. `c=[0,+1,0]` -> `y=Lx`;
4. `x[0]=4097` rejects with `r1=0` and leaves output plus both scratch
   vectors unchanged;
5. coefficient `65537` rejects with `r1=0` and output unchanged;
6. decreasing CSR offsets reject with `r1=2` and output unchanged;
7. a duplicate endpoint rejects with `r1=3` and output unchanged;
8. `edge_count=65281` rejects with `r1=0` and output unchanged.

An additional local randomized graph/coefficient cross-check against an
independent Python reference passed, but it is not part of the committed
fixture or CI evidence.

**Evidence boundary:** this is local `nan_cli` evidence only. The manifest row
keeps `ci_verified: false` until the canonical workflow executes this revision.
It verifies only the bounded unweighted Q16.16 degree-2 polynomial above. It
does not verify Chebyshev coefficients, adjacency polynomials, fractional edge
weights, dense/operator-free eigensystem filtering, coefficient generation, or
the RSS controller.

## 5. Evidence boundary and open graph work

- Local evidence is the exact command family in `tools/run_mth_fixtures.py`
  using the canonical `nan0s/tools/nmk.awk` assembler and
  `nan0s/aarch64/android/nan_cli`. It is not CI evidence. All three manifest
  rows keep `ci_verified: false` until the canonical workflow runs this
  revision.
- Native verification covers U32 degree/weighted-degree, the single-word
  degree/shell/neighborhood signature, and the bounded degree-2 polynomial
  filter. It does not verify fractional weights, directed motifs, connected
  components through these kernels, spectral signatures, epoch deltas,
  confidence metadata, Chebyshev recurrence, or adjacency filtering.
- `mth_rss_contract` and `mth_graph_laplacian` remain missing from the D-01
  registration set. `mth_graph_filter` now exists as the bounded polynomial
  prototype above, but D-02 remains incomplete because the Chebyshev/general
  polynomial contract and the RSS `FILTER` integration are not implemented.
  The RSS verb controller (D-04) remains unimplemented. No filter-completion
  or RSS-controller-completion claim is made here.
- The 2 MiB workspace ceiling is respected: degree uses no static workspace,
  pattern declares 512 words (4,096 bytes), and filter declares 528 words
  (4,224 bytes).
