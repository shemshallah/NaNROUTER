# MTH native top-k selector for 256 float32 scores

Status: source-written and locally executed PASS with the canonical NaN0S
`nmk.awk` assembler and `nan_cli` on 2026-11-07. The kernel image is 324
NaN16 words; the committed fixture image is 2,058 words and executes the
full PASS sequence in 1,158,106 guest steps. No shared harness, workflow,
or registry file was edited; canonical CI run 42395520794 executed it and GLT enforcement is pending.

## 1. Scope

`mth/nan16/mth_topk_256.nas` selects the `k` largest values from a
256-element float32 score span and returns their original indices and
values in descending value order. Equal values are ordered by the smaller
original index first, so the result is stable and deterministic.

The kernel is a leaf: it contains no `CALL`, uses no host mathematics,
and performs no allocation. Selection is a partial selection sort over
the original array. The input scores are read-only, and the only private
storage is a static 256-word selected-index flag span.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | `scores`, 256 float32 payloads (read-only) |
| `r2` | `k`, integer 1..256 |
| `r3` | `indices_out`, `k` words: selected original indices |
| `r4` | `values_out`, `k` float32 payloads: selected score values |
| `r13` | must be `1` |
| return `r1` | validated `k` on success (`1..256`); `0` on rejection |
| clobbers | `r1`-`r11`, flags |
| preserves | `r12`, `r14`, `r15` |

On success exactly `k` words are written to `indices_out` and exactly `k`
words are written to `values_out`. `indices_out[j]` is the original index
of the `j`-th largest value and `values_out[j]` is that value's exact
float32 payload. The returned `r1` equals the input `k`; the kernel still
returns an actual count so callers can use the same check for bounded and
future variable-length variants.

Rejection is atomic with respect to both output spans:

- `k == 0` is rejected;
- `k > 256` is rejected (the unsigned `CMP` also rejects a negative `k`
  word);
- any NaN score is rejected.

On rejection `r1=0` and neither output span is written. The rejection
checks complete before the first output store.

## 3. Ordering and tie-break

The ordering is defined by the native float32 `FCMP` result:

1. greater value first;
2. equal values keep the smaller original index first.

The scan is:

```
candidate > best                       -> take candidate
candidate == best and i < best_index   -> take candidate
otherwise                              -> keep best
```

The scan runs over increasing original index, so equal candidates that
appear after the current best normally fail the index test. The explicit
index comparison pins the rule rather than relying only on scan order.

`-0.0` compares equal to `+0.0`; the smaller index wins that tie and the
original payload bits are preserved in `values_out`. Positive and
negative infinities are ordered and accepted. NaN is not ordered: the
preflight checks every score with `FCMP x,x`, where an ordered value is
either `EQ` or `NE`, while unordered NaN matches no ordinary predicate
and reaches the invalid return. The kernel does not canonicalize or
propagate NaN because it never enters selection.

No FMA, reductions, host math, or arithmetic approximations are used.
The kernel only compares score payloads and copies them; it never
arithmetically transforms a score.

## 4. Algorithm and cost

For each of the `k` output slots the kernel scans all 256 scores and
skips indices already selected. The worst case (`k=256`) performs

```
256 * 256 = 65,536 candidate scans
```

with one native float comparison per unselected candidate. The selected
flags are cleared once per call. There is no recursion, no sorting of a
copy, and no dependence on input value magnitude.

Static state:

- `mth_topk_256_selected`: 256 words of selected flags.

The kernel is therefore non-reentrant and non-concurrent; callers must
serialize invocations. The flags are cleared at the start of every valid
call and carry no state across calls.

## 5. Memory budget

| Object | NaN16 words | Bytes |
|---|---:|---:|
| `scores` (input, read-only) | 256 | 2,048 |
| `mth_topk_256_selected` (private) | 256 | 2,048 |
| `indices_out` (`k=256`, caller) | 256 | 2,048 |
| `values_out` (`k=256`, caller) | 256 | 2,048 |
| **Caller-visible working set** | **1,024** | **8,192** |

The kernel text is 68 words and the complete kernel image including the
static flag span is 324 words. The committed fixture image is 2,058
words = 16,464 bytes, below both the historical 65,536-word / 512 KiB
ceiling and the 131,072-word / 1 MiB guest target.
`indices_out`, `values_out`, `scores`, and the kernel's private flag
span must be distinct; the kernel does not detect aliasing.

## 6. Fixture

`mth/tests/mth_topk_256_test.nas` builds

```
scores[i] = (float)(i - 128)          for i = 0..255
```

then overwrites eight entries to create a designed mix:

| Index | Value | Purpose |
|---:|---:|---|
| 0 | 100.0 | four-way duplicate with 50, 228, 255 |
| 50 | 100.0 | duplicate tie |
| 255 | 100.0 | duplicate tie |
| 10 | 127.0 | maximum, distinct |
| 20 | -128.0 | negative minimum |
| 30 | -77.0 | duplicate with 51 |
| 40 | 0.0 | duplicate with 128 |
| 60 | -100.0 | duplicate with 28 |

The fixture checks:

1. `k=1`: return `1`, index `10`, value bit-exactly `127.0`.
2. `k=32`: exact 32-entry order, crossing the four-way `100.0` tie at
   slots 27..30 in index order `0, 50, 228, 255`.
3. `k=256`: exact 256-entry order, including all duplicate groups and
   negative values.
4. For every selected slot, `values_out[j]` equals
   `scores[indices_out[j]]` bit-exactly.
5. `k=0`, `k=257`, and `k=-1` (`0xFFFFFFFF`): return `0`, both full
   output spans unchanged (all 512 words still the sentinel
   `0xDEADBEEF`).
6. A canonical NaN score (`0x7FC00000`) temporarily placed at index 10:
   return `0`, both full output spans unchanged.
7. Restoring `scores[10]=127.0` recovers the `k=1` result, proving the
   static flag span is cleared per call.

The exact expected index table is fixed fixture data. It was derived
independently from the dataset as descending value with ties by smaller
index, and it is compared word-for-word with the kernel output.

The fixture ends with:

```
MTH TOPK 256 PASS
```

An additional temporary, uncommitted fixture (not part of this change)
cross-checked a seeded 256-value dataset containing duplicates,
negatives, `-0.0`/`+0.0`, and an all-equal array, including `k=1` and
`k=256`; it printed `TOPK EXTRA PASS`. A second temporary fixture mixed
`+inf`, `-inf`, `+0.0`, and `-0.0` into a 256-value dataset and checked
the full exact order; it printed `TOPK INF PASS`.

## 7. Local canonical run

From the repository root:

```
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=emit mth/tests/mth_topk_256_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/topk256.nan
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=check /data/data/com.termux/files/usr/tmp/opencode/topk256.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/topk256.nan \
  --steps 20000000 --serial
```

Observed:

```
words 2058
check: 0 mismatches
[nan_cli] nan-text: 1158106 steps, rc=3, pc=490, trap=''
MTH TOPK 256 PASS
```

Kernel-only assembly check:

```
words 324
check: 0 mismatches
```

`rc=3` is `NAN_HALTED` with an empty trap string. The fixture harness
`tools/run_mth_fixtures.py` is outside this change's owned file set and
was not modified, so this fixture is not yet registered there.

## 8. Limitations

- Exactly 256 input scores and `k` in `1..256`; there is no shorter span
  or dynamic length parameter.
- NaN scores are rejected rather than ordered; the caller must handle
  non-finite input policy.
- The kernel does not validate pointer overlap, alignment, or unreadable
  spans. Inputs and both outputs must be distinct, writable where
  required, and backed by at least the documented word counts.
- Static selected flags make the kernel non-reentrant and non-concurrent.
- Worst-case cost is `O(k*256)`, not a heap or quickselect bound. For
  this fixed 256-element contract the bounded 65,536-scan ceiling is the
  intended deterministic trade-off.
- No CI workflow, fixture-harness entry, manifest, or capability file was
  edited in this change.
