# Native graph/contract operations

Status: **local `nan_cli` evidence only**. The two NaN16 sources and their
fixtures in this change were assembled with the canonical `nan0s/tools/nmk.awk`
source assembler and executed with `nan0s/aarch64/android/nan_cli` on the
development host. They are **not** claimed as CI-verified or manifest-registered.
No `spec/` or capability-manifest row was changed. Until the canonical GitHub
Actions workflow assembles and executes these exact revisions, the capability
state remains `source_written`.

This document covers:

- `mth/nan16/mth_graph_laplacian_csr.nas`
- `mth/tests/mth_graph_laplacian_csr_test.nas`
- `mth/nan16/mth_rss_contract.nas`
- `mth/tests/mth_rss_contract_test.nas`

## 1. `mth_graph_laplacian_csr`

### 1.1 Operator

For the symmetric simple graph with unit edge weights represented by canonical
CSR:

\[
(Lx)_i=\sum_{j\in N(i)}(x_i-x_j)=d_i x_i-\sum_{j\in N(i)}x_j .
\]

The kernel never materializes the dense `256 x 256` Laplacian or the
`65,536 x 65,536` Kronecker/pair-space operator. It reads the 257-word CSR
offset page, the bounded neighbor/weight edge lists, one 256-word state vector,
and writes one 256-word output vector.

This is the unweighted operator. Every stored weight word must be exactly `1`.
A graph with integer weights other than one is rejected rather than silently
treated as unweighted; weighted action remains the separately versioned
`mth_sparse_weighted_graph_laplacian_v2.nas` contract.

### 1.2 Numeric ABI

| Field | Representation |
|---|---|
| State `x` | signed two's-complement I32, Q16.16 |
| State raw range | `[-2^22,+2^22]` = real `[-64,+64]` |
| Edge weight | U32 storage word; upper 24 bits zero; low U8 exactly `1` |
| Degree | at most 255 |
| Output | signed two's-complement I32, Q16.16 |
| Scale | exactly 1 in Q16.16; no rescaling |
| Rounding | none |
| Saturation/wrap | neither; the bounds prove signed-I32 safety |
| Vertices | exactly 256 |
| Directed CSR entries | `0..65,280`, every undirected edge stored twice |
| Workspace | none; caller-owned pages only |

For valid states, `|x_i-x_j| <= 2^23`. A row has at most 255 neighbors, so:

\[
|(Lx)_i|\le255\cdot2^{23}=2{,}139{,}095{,}040<2^{31}.
\]

Every subtraction and row accumulation is therefore an exact signed-I32
operation. No host arithmetic is used.

### 1.3 Native entry point

`mth_graph_laplacian_csr_q16_16`

| Register | Meaning |
|---|---|
| `r1` | `row_offsets`, 257 U32 words; `offsets[0]=0`, `offsets[256]=edge_count` |
| `r2` | `neighbors`, `edge_count` U32 words; endpoints `0..255` |
| `r3` | `weights`, `edge_count` U32 storage words; low U8 exactly `1` |
| `r4` | `x`, 256 signed I32 Q16.16 words |
| `r5` | `output`, 256 signed I32 Q16.16 words |
| `r6` | `edge_count`, `0..65,280` |
| `r13` | constant `1` |
| return | `r1` status code below |

The routine is leaf-only: no `CALL`, no static scratch, preserves `r13` and
`r15`, and clobbers `r1-r12` and `r14`. Input and output spans must not overlap.

Status codes:

| `r1` | Meaning |
|---|---|
| `1` | success |
| `0` | invalid edge count or out-of-range state |
| `2` | invalid offsets, degree bound, final offset, or `offsets[0]` |
| `3` | invalid endpoint encoding, row order, duplicate, or self-loop |
| `4` | invalid weight encoding or non-unit weight |
| `5` | non-reciprocal edge list |

Validation order is: edge-count bound, all 256 state words, all 257 offsets,
every row's endpoint encoding/order/self-loop, every weight word, then full
reciprocal-edge symmetry. All validation finishes before the first output
write, so every rejection leaves the 256-word output page unchanged.

The full symmetry pass is deterministic: for each row `i`, only neighbors
`j > i` are searched in row `j`; the strictly increasing row order lets the
search stop at the first endpoint greater than `i`. This proves every directed
entry has a reciprocal entry. Reciprocal weight equality is automatic because
the operator accepts unit weights only.

### 1.4 Fixture evidence

Command family:

```sh
awk -f "$NAN0S/tools/nmk.awk" -v CMD=emit \
  mth/tests/mth_graph_laplacian_csr_test.nas > lap.nan
"$NAN0S/aarch64/android/nan_cli" --img lap.nan --steps 20000000 --serial
```

Observed local result:

- marker: `MTH GRAPH LAPLACIAN CSR PASS`
- guest steps: `197,118`
- terminal status: `rc=3` (`HALT`)
- assembler image: 2,546 words

The fixture covers:

1. unit-weight path `0--1--2--3`, `x=[0,1,4,9]` Q16.16,
   output `[-65536,-131072,-131072,327680]` (`[-1,-2,-2,+5]`);
2. constant state `x=1`, output zero (constant nullspace);
3. disconnected graph `(0--1)+(2--3)`, output
   `[-65536,+65536,-327680,+327680]` (`[-1,+1,-5,+5]`);
4. triangle `0--1--2`, `x=[0,1,4]`, output
   `[-327680,-131072,458752,0]` (`[-5,-2,+7,0]`);
5. empty graph, all-zero output;
6. out-of-range state rejection with unchanged output;
7. weight `2`, zero weight, and weight with nonzero high bits each reject with
   status `4` and unchanged output;
8. duplicate endpoint, self-loop, and endpoint with nonzero high bits reject
   with status `3` and unchanged output;
9. nonmonotone offsets and nonzero `offsets[0]` reject with status `2` and
   unchanged output;
10. a one-direction edge with no reciprocal rejects with status `5` and
    unchanged output;
11. `edge_count=65,281` rejects with status `0` and unchanged output.

## 2. `mth_rss_contract`

### 2.1 Purpose

`mth_rss_contract_check` validates a typed RSS operation request against a
caller-owned contract. It is an admission/deny gate only:

- it does not execute the operation;
- it does not read or write any payload;
- it does not mutate the descriptor or contract;
- it does not allocate pages or grant ACL/lease authority.

It checks operation identity, kinds, domain, dimensions, shape rule, declared
payload capacities, scale policy, policy flags, and numeric bounds.

### 2.2 Native entry point

`mth_rss_contract_check`

| Register | Meaning |
|---|---|
| `r1` | descriptor pointer, 16 U32 words |
| `r2` | contract pointer, 16 U32 words |
| `r13` | constant `1` |
| return | `r1=1` allow, `r2=0`; or `r1=0` deny, `r2=reason code` |

The routine is leaf-only, clobbers `r1-r12` and `r14`, and preserves `r13` and
`r15`. A null `r1` or `r2` denies with reason `1` before any dereference.

### 2.3 Descriptor layout

| Word | Field |
|---|---|
| 0 | `version`, must be `1` |
| 1 | `operation_id` |
| 2 | `input_kind` |
| 3 | `output_kind` |
| 4 | `domain_id` |
| 5 | `input_dim0` |
| 6 | `input_dim1` |
| 7 | `output_dim0` |
| 8 | `output_dim1` |
| 9 | `input_words` |
| 10 | `output_words` |
| 11 | `scale_policy` |
| 12 | `policy_flags` |
| 13 | input bound magnitude |
| 14 | output bound magnitude |
| 15 | reserved, must be `0` |

Operation IDs follow `docs/GRAPH_SPECTRAL_MTH_PLAN.md` section 6 and its
compatible lower-level names:

| ID | Operation |
|---|---|
| 1 | ENCODE |
| 2 | QUERY |
| 3 | MATCH |
| 4 | FILTER |
| 5 | DRIVE |
| 6 | FOLD |
| 7 | PROPAGATE |
| 8 | PROJECT |
| 9 | DECODE |

Kinds:

| ID | Kind |
|---|---|
| 0 | scalar |
| 1 | vector |
| 2 | matrix |
| 3 | CSR graph |
| 4 | operation descriptor |

Domains:

| ID | Domain |
|---|---|
| 0 | abstract |
| 1 | real |
| 2 | Q16.16 |
| 3 | integer |
| 4 | float32 |

Scale policies:

| ID | Policy |
|---|---|
| 0 | exact Q16.16 |
| 1 | exact integer scale 1 |
| 2 | float32 |
| 3 | reserved/extension; allowed only if the contract mask permits it |

Policy flag bits (declared by the contract, not interpreted numerically here):

| Bit | Meaning |
|---|---|
| 0 | immutable input |
| 1 | atomic output |
| 2 | deterministic |
| 3 | canonical CSR |
| 4 | no dense pair materialization |
| 5 | bounded workspace |

### 2.4 Contract layout

| Word | Field |
|---|---|
| 0 | `version`, must be `1` |
| 1 | `operation_id` |
| 2 | `input_kind` |
| 3 | `output_kind` |
| 4 | `domain_id` |
| 5 | `max_dim0`, `1..65,535` |
| 6 | `max_dim1`, `0..65,535` |
| 7 | `max_input_words`, `1..1,048,576` |
| 8 | `max_output_words`, `1..1,048,576` |
| 9 | allowed scale-policy mask, nonzero, bits `0..3` only |
| 10 | required policy flags, at most `0x3F` |
| 11 | forbidden policy flags, at most `0x3F` |
| 12 | maximum bound magnitude, nonzero |
| 13 | shape rule, `0..5` |
| 14 | reserved, must be `0` |
| 15 | reserved, must be `0` |

Required and forbidden flag masks must be disjoint; otherwise the contract is
malformed. Contract dimensions and word caps are checked before descriptor
comparisons so multiplication and shift calculations cannot overflow.

Shape rules:

| Rule | Meaning | Required input words | Required output words |
|---|---|---|---|
| 0 | scalar `->` scalar; kinds `0/0`, all dimensions zero | 1 | 1 |
| 1 | vector `->` vector; kinds `1/1`, nonempty equal lengths | `dim0` | `out_dim0` |
| 2 | matrix `(m,n)` `->` vector `(m)`; kinds `2/1`, `m,n>0` | `m*n` | `m` |
| 3 | matrix `(m,n)` `->` matrix `(m,n)`; kinds `2/2`, `m,n>0` | `m*n` | `m*n` |
| 4 | CSR 256-vertex `->` vector 256; kinds `3/1`, `E=dim1<=65,280` | `257+2E` | 256 |
| 5 | bounded-any rectangular shapes | `dim0*dim1` or `dim0` if `dim1=0` | analogous |

For every rule, `required <= declared <= contract maximum` must hold for both
input and output word counts. Declared bound magnitudes are U32 absolute
magnitudes and must not exceed contract word 12.

### 2.5 Reason codes

| `r2` | Meaning |
|---|---|
| 0 | allow |
| 1 | null descriptor/contract |
| 2 | unsupported version |
| 3 | unknown or mismatched operation ID |
| 4 | kind mismatch |
| 5 | domain mismatch |
| 6 | dimension exceeds contract bound |
| 7 | shape-rule violation |
| 8 | payload capacity violation |
| 9 | unsupported scale policy |
| 10 | policy-flag violation (missing required or forbidden present) |
| 11 | numeric bound violation |
| 12 | malformed descriptor/contract structure |

### 2.6 Fixture evidence

Command family:

```sh
awk -f "$NAN0S/tools/nmk.awk" -v CMD=emit \
  mth/tests/mth_rss_contract_test.nas > rss.nan
"$NAN0S/aarch64/android/nan_cli" --img rss.nan --steps 2000000 --serial
```

Observed local result:

- marker: `MTH RSS CONTRACT PASS`
- guest steps: `6,504`
- terminal status: `rc=3` (`HALT`)
- assembler image: 3,023 words

The fixture covers:

1. allow a CSR(256 vertices, 6 edges) `->` vector(256) QUERY descriptor with
   Q16.16 scale and exact bounds;
2. allow a vector(128) `->` vector(128) FILTER descriptor with integer scale 1;
3. deny a null descriptor (reason `1`);
4. deny descriptor version mismatch (reason `2`);
5. deny operation-ID mismatch (reason `3`);
6. deny kind mismatch (reason `4`);
7. deny domain mismatch (reason `5`);
8. deny dimension above contract maximum (reason `6`);
9. deny CSR shape mismatch (reason `7`);
10. deny undersized input payload (reason `8`);
11. deny undersized output payload (reason `8`);
12. deny unsupported scale policy (reason `9`);
13. deny missing required policy flag (reason `10`);
14. deny forbidden policy flag present (reason `10`);
15. deny bound above contract maximum (reason `11`);
16. deny malformed contract with `max_dim0=0` (reason `12`).

## 3. Evidence boundary and limitations

- **Not CI-verified.** The results above are local canonical assembler and
  `nan_cli` runs on this revision. They are not a GitHub Actions run, not a
  `native_verified` manifest row, and not a capability registration.
- The Laplacian verifies only the exact unweighted unit-weight Q16.16/I32
  contract with full local CSR symmetry validation. It does not verify
  fractional or integer-weighted action (use the separate v2 kernel), graph
  energy, connected components/nullity, pair-space action, void potential,
  filters, Lanczos, or wave evolution.
- The symmetry pass is worst-case `O(E * degree)` and has not been benchmarked
  on a dense 256-vertex graph. No dense 256 x 256 or 65,536 x 65,536 matrix is
  ever materialized.
- The Laplacian does not inspect input/output span overlap; the caller/runner
  must enforce the non-overlap contract.
- The RSS checker validates declared metadata only. It does not verify the
  actual payload contents, CSR structure, numeric values, graph digest,
  operator digest, epoch, cancellation, workspace availability, or ACL/lease
  authority. Those remain runner/NAN-RSS-1 responsibilities.
- The scale policy is declarative. The checker accepts or denies the declared
  policy but performs no conversion.
- No host-language implementation of the mathematical operators is present in
  these files. The fixtures only orchestrate native calls, compare exact
  expected words, and emit markers.
