# MTH graph core kernels

Status: the two kernels below are **native_verified locally** (2026-11-07) by
the canonical NaN16 assembler and `nan_cli` execution harness. They are
registered with `status: native_verified` and `ci_verified: false` in
`spec/wave-capabilities.json`; canonical CI has not executed this revision.
This document does **not** claim D-01, D-02, D-03, D-04, or any RSS
controller/filter completion.

## 1. Shared CSR descriptor

Both kernels consume the same bounded canonical CSR view already used by the
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

## 4. Evidence boundary and open graph work

- Local evidence is the exact command family in `tools/run_mth_fixtures.py`
  using the canonical `nan0s/tools/nmk.awk` assembler and
  `nan0s/aarch64/android/nan_cli`. It is not CI evidence. Both manifest rows
  keep `ci_verified: false` until the canonical workflow runs this revision.
- Native verification covers U32 degree/weighted-degree and the single-word
  degree/shell/neighborhood signature only. It does not verify fractional
  weights, directed motifs, connected components through this kernel,
  spectral signatures, epoch deltas, or confidence metadata.
- `mth_rss_contract` and `mth_graph_laplacian` remain missing from the D-01
  registration set. `mth_graph_filter` (D-02) and the RSS verb controller
  (D-04) remain unimplemented. No filter or RSS controller completion is
  claimed here.
- The 2 MiB workspace ceiling is respected: degree uses no static workspace,
  and pattern declares 512 words (4,096 bytes).
