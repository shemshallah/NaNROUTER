# MTH 1 MiB guest-budget migration

Status: design target; canonical toolchain verification pending.

## 1. New budget

The owner reports that GLT is increasing the guest page limit to **1 MiB**:

```
1 MiB = 131,072 NaN16 words = 32 pages of 32 KiB
```

The old 512 KiB / 65,536-word ceiling is historical. Existing evidence at 512 KiB remains valid for those exact kernels; any fixture above the old limit is marked **pending 1 MiB toolchain** until the canonical NaN16 harness executes it.

## 2. What changes

| Object | Old 512 KiB | New 1 MiB |
|---|---|---|
| 256×256 float32 matrix | fits alone | fits with vectors/scratch |
| 256×256 matrix + eigenvectors | tight/over | fits, with ~512 KiB scratch |
| 256×256 complex float32 | full guest | fits with ~512 KiB scratch |
| Full 256 matvec A+x+y (66,048 words) | not with code | fits |
| Full 256 SVD top pair (~66,305 words) | no | fits |
| Full 256 ENCODE/DECODE W+vectors (~66,304) | no | fits |
| Full-U pair-tile reference (73,990 words) | not dispatchable | fits |
| U + L + output full pair (196,608 words) | no | still no |
| 65,536² dense product (16 GiB) | forbidden | still forbidden |

The 8 MiB universe still has 256 × 32 KiB pages: 255 head pages + 1 NANNET node page. The 1 MiB guest holds 32 of those pages, not 16.

## 3. New kernel opportunities

- full 256×256 matvec;
- full 256×256 top singular pair;
- full 256×256 ENCODE/DECODE;
- full 255×255 odd certificate (65,025 words);
- full-U 16×16 pair-tile reference (73,990 words);
- full 256×256 matrix + eigenvectors for a paged eigensolver.

## 4. What does not change

- `65,536 × 65,536` dense product remains 16 GiB and is never materialized.
- `U + L + output` full pair remains over 1 MiB; use K16/tile streaming.
- The active-runner ceiling remains **7 GiB**, one active runner at a time.
- BS0DB/MC0DB remain durable control/evidence, not the canonical universe.
- The 8 MiB universe remains the persistent page store.

## 5. Implemented 1 MiB kernels (local execution, CI pending)

| Kernel | Local evidence | Working set |
|---|---|---|
| `mth_matvec256_full` | 2,978,362 steps PASS | 66,048 words |
| `mth_svd_top256` | 11,002,235 steps PASS | ~66,305 words |
| `mth_svd_top2_256` | 40,216,927 steps PASS | ~68,878-word image |
| `mth_encode256_full` / `mth_decode256_full` | 1,655,853 steps PASS | 66,304 words |
| `mth_adapter_residual_256_full` | 2,839,172 steps PASS | 66,304 words |
| `mth_centrosymmetry_255_full` | 2,700,726 steps PASS | 65,025-word input |
| `mth_topk_256` | 1,158,106 steps PASS | 1,024 words |

The runner facade now defaults to an adjustable 1 MiB guest budget, exposes
`guest_budget_words`/`guest_budget_pages`, and still allows a caller to set a
larger or smaller budget. The 1 MiB default is policy, not a claim that the GLT
page-limit harness has already enforced it.

## 6. Required gates

1. Canonical NaN16 CI reports a 131,072-word guest.
2. A >65,536-word fixture assembles, loads, and executes.
3. The 1 MiB page count is exposed to MthSystem and plan validation.
4. Old 512 KiB plan limits are not silently retained.
5. The full-U pair-tile reference is promoted only after execution at 1 MiB.
6. Every new kernel gets a fixture, ABI, manifest entry, and CI evidence.
