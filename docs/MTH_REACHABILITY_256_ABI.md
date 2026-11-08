# MTH R5 reachability 256 ABI

Status: source-written and locally executed with the canonical NaN0S `nmk.awk` /
`nan_cli` toolchain on 2026-11-07. The fixture prints its PASS marker through
the `.nan` text loader. Canonical CI run 42395520794 executed it; no page-size
limit is claimed or enforced, and no shared registry/workflow change is claimed here.

This change owns only:

- `mth/nan16/mth_reachability_256.nas`
- `mth/tests/mth_reachability_256_test.nas`
- `docs/MTH_REACHABILITY_256_ABI.md`

## 1. Scope

This is the R5 graph-reachability primitive: given a dense 256x256 directed
adjacency matrix and one source vertex, it computes the number of vertices
reachable from that source and a 256-element visited mask. It is the
graph-topology half of the R5 observability/reachability gate.

It is not a numerical observability test. It does not compute the column space
of `M_wave`, a Kalman observability matrix, rank, eigenvalues, or a condition
number. Those remain the SVD/rank/aperture work. This kernel answers only
"which vertices can be reached by following nonzero directed edges from the
source?" on the fixed 256-vertex graph.

## 2. Kernel

Kernel: `mth/nan16/mth_reachability_256.nas`

`A` is row-major: `A[i,j]` is word `i*256 + j`. `A[i,j] != 0` means the
directed edge `i -> j` is present. The zero test is numeric, not a raw
all-bits-zero test:

```
payload << 1 == 0   iff payload is +0.0 or -0.0
```

`SHL` by one discards the sign bit. Therefore `+0.0` and `-0.0` are absent,
while every other float32 payload (finite nonzero, subnormal, Inf, NaN) is
present. No float arithmetic, FMA, host math, or lookup table is used.

### ABI

| Register | Meaning |
|---|---|
| `r1` | `A`, 65,536 float32 words, row-major 256x256 adjacency (read-only) |
| `r2` | source vertex index, `0..255` |
| `r3` | `visited_out`, 256 float32 words, written as `0.0` or `1.0` |
| `r4` | `queue_scratch`, at least 256 float32-width words |
| `r13` | constant `1` |
| return `r1` | reachable count in `1..256`, or `0` for invalid source/overflow |
| clobbers | `r1`, `r5`-`r12`, `r14`, flags |
| preserves | `r2`, `r3`, `r4`, `r13`, `r15` |

The kernel is a leaf: no `CALL`, no static scratch, no `r15` use. `A` is never
written. `visited_out`, `queue_scratch`, and `A` must not overlap each other.
`queue_scratch` holds raw `U32` vertex indices in its 32-bit words even though
the ABI describes the storage as float32.

`visited_out` words are exactly `0x00000000` (`0.0`) or `0x3F800000` (`1.0`).
No other bit pattern is written. After a valid call,
`queue_scratch[0..count-1]` contains the deterministic enqueue order; entries
at or beyond `count` are untouched. A caller must not depend on those stale
tail entries.

### Algorithm

```
validate source in 0..255           (reject before any output write)
visited_out[0..255] = 0.0
visited_out[source] = 1.0
queue[0] = source
head = 0; tail = 1; count = 1

while head < tail:
    i = queue[head]
    for j = 0..255 in increasing order:
        if A[i,j] is numerically nonzero and visited_out[j] == 0:
            queue[tail] = j
            tail += 1
            visited_out[j] = 1.0
            count += 1
    head += 1

return count
```

A vertex is marked visited when it is enqueued, not when it is dequeued. Thus
each vertex enters the queue at most once. A fully reachable 256-vertex graph
fills the queue exactly: `tail` reaches 256, never 257.

Order is deterministic: FIFO queue processing, source first, and columns
scanned in increasing `j`. Within one breadth layer, vertices appear in the
order their parents were dequeued, then in increasing `j`.

### Rejection and atomicity

The source check is the first operation. An invalid source (`>= 256`, using
the unsigned `CMP`) returns `r1 = 0` before `visited_out` or `queue_scratch` is
touched. The fixture poisons both arrays and verifies they are unchanged.

Two defensive overflow guards return `0`:

- a dequeued index is `>= 256`;
- a 257th enqueue would be required (`tail >= 256`).

For a valid, non-aliasing caller both are unreachable, because each of the 256
vertices is enqueued at most once. They exist only to bound a corrupted queue.
No atomicity claim is made for a guard that cannot be reached through the
declared ABI; aliasing or corrupted scratch is a contract violation.

## 3. Memory

| Object | NaN16 words | Bytes |
|---|---:|---:|
| `A` (256x256 float32) | 65,536 | 524,288 |
| `visited_out` | 256 | 2,048 |
| `queue_scratch` | 256 | 2,048 |
| **Kernel working set** | **66,048** | **528,384** |
| 1 MiB guest budget | 131,072 | 1,048,576 |
| Remaining for code | 65,024 | 520,192 |

The kernel itself has no static scratch, so its data working set is exactly
the caller-owned 66,048 words. This fits the 1 MiB guest budget with the whole
matrix resident, but not the historical 512 KiB (65,536-word) guest, because
`A` alone fills that budget.

The fixture image is 66,574 words (532,592 bytes) because it also contains the
test code, the two 256-word arrays, and the PASS/FAIL strings.

## 4. Fixture

`mth/tests/mth_reachability_256_test.nas` lays out:

| Label | Word address |
|---|---:|
| code, kernel, helpers | 0 |
| `A` | 512 |
| `visited_out` | 66,048 |
| `queue_scratch` | 66,304 |
| PASS/FAIL strings | 66,560 |

Checks:

1. **Directed chain** `0->1->...->255`, source `0`: count is exactly 256,
   every `visited_out` word is `0x3F800000`, and `queue_scratch[0..255]` is
   exactly `0,1,...,255`.
2. **Directed chain**, source `128`: count is exactly 128,
   `visited_out[0..127] == 0.0`, and `visited_out[128..255] == 1.0`. This
   distinguishes directed reachability from undirected connectivity.
3. **Valid upper source boundary**, source `255`: count is 1,
   `visited_out[254] == 0.0`, `visited_out[255] == 1.0`.
4. **Branching graph** `0->1, 0->2, 1->3, 1->4, 2->5`, source `0`: count is
   6, only vertices `0..5` are visited, and the queue is exactly
   `0,1,2,3,4,5`. A decreasing-`j` scan would produce `0,2,1,5,4,3`; a LIFO
   walk would produce a different prefix, so this pins FIFO plus increasing
   column order.
5. **Disconnected directed cycle** `4->5->6->7->4` plus isolated vertex `9`,
   source `4`: count is 4, vertices `4..7` are visited, and vertex `9` is not.
   Source `9` then gives count 1 with vertex `4` unvisited.
6. **Self-loop only** at vertex `3`, source `3`: count is 1, vertex `3` is
   visited, vertices `2` and `4` are not, and `queue_scratch[0] == 3`. The
   nonzero diagonal entry is not re-enqueued.
7. **Negative zero**: `A[3,4] = 0x80000000` (`-0.0`), source `3`: count is 1
   and vertex `4` is not visited, confirming the numeric-zero edge test.
8. **Invalid source 256**: `visited_out` is poisoned to `0x0000004D` (77) and
   `queue_scratch` to `0x00000063` (99) before the call. The call returns
   `r1 = 0`, all 256 visited words remain 77, and all 256 queue words remain
   99, verifying atomic rejection.

Success marker:

```
MTH REACHABILITY 256 PASS
```

## 5. Local canonical run

From the repository root:

```
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_reachability_256_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/mth_reachability_256.nan
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=check \
  /data/data/com.termux/files/usr/tmp/opencode/mth_reachability_256.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/mth_reachability_256.nan \
  --steps 10000000 --serial
```

Observed:

```
words 66574
check: 0 mismatches
[nan_cli] nan-text: 2489116 steps, rc=3, pc=371, trap=''
MTH REACHABILITY 256 PASS
exit=0
```

`rc=3` is `NAN_HALTED`; the trap string is empty and `nan_cli` exits `0`. The
10,000,000-step budget leaves substantial headroom over the 2,489,116 executed
steps.

Post-halt peeks of the final rejected call:

```
--peek 66048:3  ->  0000004D 0000004D 0000004D   (visited_out still 77)
--peek 66304:3  ->  00000063 00000063 00000063   (queue still 99)
```

Source-written hashes (not a substitute for a signed release digest):

```
3e65649de3219437623e7ef3e9d5fbf23a37d93aff09ab25031738f2917ce4b1  mth/nan16/mth_reachability_256.nas
eac10f27dd8a3cba863def596a31c424c0123962efcb6f66c2015105a976c60f  mth/tests/mth_reachability_256_test.nas
```

### Fixture sensitivity checks

Temporary copies outside the owned files were mutated and reassembled to
confirm that the fixture detects real defects:

| Mutation | Result |
|---|---|
| Source preflight `JMP[GE] @...invalid` -> `NOP` | `MTH REACHABILITY 256 FAIL` at the poisoned invalid-source case |
| Zero-edge branch `JMP[EQ] @...scan_next` -> `JMP[NE]` | `MTH REACHABILITY 256 FAIL` (zero entries become edges) |
| Numeric-zero test `SHL r11,r11,1` -> `NOP` | `MTH REACHABILITY 256 FAIL` at the `-0.0` case |

## 6. Limitations

- Fixed 256 vertices and one source per call. There is no arbitrary `n`,
  multi-source batch, CSR/weighted form, or transpose mode.
- The adjacency is dense and fully resident: 65,536 words. Sparse graphs pay
  the full dense scan; the kernel is not a sparse-CSR traversal.
- The result is graph reachability, not numerical observability or the
  reachable subspace of `M_wave`. It does not compute rank or a Kalman matrix.
- `A` is read-only but is not validated for shape, aliasing, or digest. The
  caller must bind the matrix and guarantee the declared spans.
- The visited mask stores `0.0` / `1.0`, not raw integer `0` / `1`. A caller
  comparing raw words must compare against `0x3F800000`.
- The overflow guards are defensive and cannot fire for a valid non-aliasing
  call. Rejection atomicity is proven and tested for invalid source only.
- A leading `-0.0` is treated as no edge. NaN and Inf payloads are treated as
  present edges because they are numerically nonzero bit patterns.
- Local execution uses the `.nan` text loader. The 66,574-word fixture is not
  evidence of a page-size limit (none is enforced).
- No CI registration, workflow edit, shared registry update, or commit is part
  of this change.
