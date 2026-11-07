# Parallel page-backed MTH pair generation executor

Status: source-written; Python adapter contract and fake-boundary tests are added. Native end-to-end page-store integration is not yet verified.

## Responsibilities

`runner_riddle/mth_pair_tile_executor.py` binds the already-native-verified
16-slice guest driver to page storage, full-U reference execution, and the
existing 256-tile atomic publication manifest.

The host is strictly a transport and verification coordinator:
- pin one immutable operator snapshot (generation, operator digest, L/U
  digests, and input page-set digest);
- stage four strips for each output tile, each strip holding all sixteen
  consecutive 16x16 K blocks;
- invoke the NaN16 K16 driver and its explicit finalizer through a supplied
  guest adapter;
- invoke the separate full-U native tile reference against the same snapshot;
- compare output tile bytes exactly, hash each verified tile, and stream it to
  an unpublished candidate page set;
- seal the canonical 256-tile manifest and ask the page store to publish using
  an expected-generation compare-and-swap.

No host matrix arithmetic, dense operator allocation, or canonical page writes
are performed by this module.

## Strip geometry

For output tile `(i,j)`, where each coordinate is a 16-row/column block:
- `L_IK`: L rows `16*i..16*i+15`, all 256 K columns;
- `U_KJ`: all 256 K rows, U columns `16*j..16*j+15`;
- `U_IK`: U rows `16*i..16*i+15`, all 256 K columns;
- `L_JK`: L rows `16*j..16*j+15`, all 256 K columns.

Each strip is 16×256 or 256×16 NaN16 words = 4,096 words = 32 KiB.
The four strips total 16,384 words = 128 KiB. The driver workspace
(17,170 words) includes those strips, two accumulators, output tile, scratch,
and private frame.

Every returned strip must match the pinned snapshot's generation, operator
digest, relevant L/U matrix digest, and input page-set digest. A mismatch aborts
the candidate.

## Parallel budget

The dense full-U reference requires 73,990 words. Reference calls run on the
coordinator thread one at a time. K16 guest calls use a worker pool. At the
1 MiB / 131,072-word budget, three K16 workers plus one dense reference fit:
`3*17,170 + 73,990 = 125,500` words. A fourth worker is rejected. This is
an aggregate admission calculation, not a physical VM memory fence; the
runtime must supply independent worker slots consistent with this budget.

## Atomic publication

The executor writes only into an unpublished candidate generation. It keeps
only compact tile evidence in memory, not a full 256×256 result matrix.
Publication requires:
1. all 256 tile results;
2. exact byte equality against the full-U guest reference for every tile;
3. one plan digest binding the same immutable operator snapshot and K16 ABI;
4. a SHA-256 digest of the complete candidate output page set;
5. a storage-layer atomic compare-and-swap from the pinned base generation to
   the next generation.

Any staging, execution, comparison, digest, or publication error discards the
unpublished candidate. The `CandidatePageStore` implementation is responsible
for the final atomic pointer switch and stale-generation rejection.

## Adapter contracts

- `PairTilePageSource.pin_snapshot()` returns a stable `OperatorSnapshot`.
- `PairTilePageSource.read_strip()` returns a `PageStrip` with all provenance
  fields populated and the exact expected byte count.
- `NativePairTileGuest.run_k16_driver()` executes the 16-slice guest driver
  plus finalizer and returns 256 NaN16 words.
- `NativePairTileGuest.run_full_u_reference()` executes the independent
  full-U guest reference and returns the same output encoding.
- `CandidatePageStore` creates, fills, hashes, publishes, or discards candidate
  output pages. Its `publish_candidate()` operation must be atomic.

The repository currently contains no concrete canonical matrix-page provider
or candidate output-page implementation implementing these protocols. The
fake-backed tests verify orchestration and failure semantics only; they do not
claim native 256-tile execution or durable atomic publication.
