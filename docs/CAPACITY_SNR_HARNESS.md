# Synthetic capacity-versus-SNR harness

Status: synthetic harness only. No real model, real data, or real capacity
measurement is present. A passing report is **not** promotable evidence for a
capacity claim.

This document covers `runner_riddle/capacity_snr.py` and
`tests/test_capacity_snr.py`. It implements the synthetic portion of R5 /
`E-08` and `F-01`..`F-05`; `F-06`..`F-10` remain blocked on external evidence.

## 1. Purpose and non-claim

The harness exercises the six R5 gates against a deterministic synthetic
frozen-model stub. It is useful for checking the gate logic, metric
plumbing, controls, and reproducibility before real frozen-model/data
infrastructure exists.

Every report contains:

| Field | Value |
|---|---|
| `synthetic_only` | `true` |
| `real_model` | `false` |
| `real_data` | `false` |
| `real_capacity_supported` | `false` |
| `capacity_claim` | `false` |
| `promotable_as_real_capacity_result` | `false` |
| `promotion.allowed` | `false` |
| `promotion.status` | `blocked_synthetic_only` |
| `claim.real_capacity_claim` | `false` |

The report status is `synthetic_supported` when the six R5 gate checks pass.
The gate itself uses the R5 vocabulary: `supported`, `rejected`, or
`inconclusive`. `synthetic_supported` never means a real capacity result was
measured.

## 2. API

```python
from runner_riddle.capacity_snr import (
    CapacitySNRHarness,
    CapacitySNRSpec,
    SNRPoint,
    SNRSweep,
    SeedSet,
    SyntheticStubConfig,
    run_capacity_snr,
)

report = CapacitySNRHarness().run()
# or: report = run_capacity_snr()
```

### Typed configuration

- `SNRPoint(snr_db, definition=...)` defines one SNR point.
- `SNRSweep(points, signal_power=1.0, declared_range_db=None,
  noise_model=..., matched_variance_noise_model=...)` defines the measured
  sweep and the declared noise model.
- `SeedSet(seeds, min_seeds=2)` defines the seed manifest. Repeats are not
  substitutes for unique seeds.
- `CapacitySNRSpec(sweep=..., seeds=..., item_counts=..., repeats=...,
  dimension=..., bootstrap_samples=..., confidence=..., min_items=...,
  min_snr_points=..., min_effect=..., capacity_threshold=...,
  max_false_match_rate=..., null_query_count=...,
  match_similarity_threshold=...)` defines the full protocol and thresholds.
- `SyntheticStubConfig` defines the synthetic-only condition gains, shuffle
  shift, and AR(1) coefficient. These values are declared generator
  parameters, not physical measurements.

Defaults: SNR points `-12`, `-8`, `-4` dB; seeds `(0, 1)`; item counts
`(8, 16, 24)`; two repeats; dimension 32; 95% paired bootstrap CI; capacity
threshold 0.9; matched-similarity threshold 0.9.

### Explicit definitions

- SNR: `snr_db = 10 * log10(signal_power / noise_power)`, with
  `noise_power = signal_power / 10**(snr_db / 10)`.
- Held-out accuracy: top-1 associative retrieval accuracy over held-out
  synthetic item probes.
- Paired delta: mean per-block accuracy difference, where a block is one
  `(snr_db, item_count)` cell averaged over seeds and repeats. Intervals use a
  deterministic percentile bootstrap.
- False-match rate: fraction of null probes whose best normalized memory
  similarity reaches `match_similarity_threshold`.
- Capacity at fixed SNR: largest declared item count whose accuracy reaches
  `capacity_threshold`.
- Steps: one step is one synthetic dot-product comparison between a probe and
  a stored memory slot.
- Memory: `item_count * dimension * 4` bytes at the largest declared item
  count.

## 3. Synthetic frozen-model stub

`SyntheticFrozenModelStub` is deterministic and declares
`synthetic_only=True`, `real_model=False`, and `real_data=False`. It uses a
hash-seeded Rademacher codebook, declared Gaussian component noise, top-1
retrieval, and null probes for false-match measurement. It never loads or calls
a model, dataset, native process, or network service.

## 4. Conditions

| Condition ID | Role | Synthetic transformation |
|---|---|---|
| `matched_baseline` | baseline | zero-gain local memory |
| `coupled_candidate` | candidate | declared coupling gain in dB |
| `zero_coupling` | control | candidate path with zero gain |
| `random_coupling` | control | zero-gain path with random sign scrambling |
| `shuffled_memory` | control | candidate gain with shifted associations |
| `matched_variance_noise` | control | baseline with AR(1) colored noise whose stationary component variance matches the Gaussian variance |

The candidate and matched baseline receive the same codebook, probes, item
counts, steps, and active memory. The report verifies that reported steps and
memory are equal for those two conditions.

## 5. Metrics

`report["metrics"]` contains:

- `conditions`: accuracy, false-match rate, steps, memory bytes/words/MiB,
  accuracy by SNR and item count, and per-(SNR, item count) accuracy for each
  condition.
- `deltas`: candidate-versus-baseline and candidate-versus-each-control
  paired mean delta, CI bounds, per-seed deltas, per-SNR deltas, and status.
- `capacity_at_snr`: capacity per condition at each measured SNR, plus
  candidate-minus-matched-baseline capacity.
- `definitions`: the explicit metric definitions above.

## 6. R5 gate checks

All six checks must pass for `gate.status == "supported"`:

1. `r5_gate_1_candidate_beats_matched_baseline`: candidate held-out accuracy
   beats the matched baseline and candidate false-match rate is within
   `max_false_match_rate`.
2. `r5_gate_2_controls_do_not_reproduce_gain`: the candidate beats every
   control (`zero_coupling`, `random_coupling`, `shuffled_memory`,
   `matched_variance_noise`) with a positive paired delta and CI excluding
   zero.
3. `r5_gate_3_gain_persists_across_seeds_and_snr`: at least `min_seeds` and
   `min_snr_points` are present, and every declared seed and SNR point shows
   positive gain.
4. `r5_gate_4_uncertainty_interval_excludes_zero`: the candidate-versus-
   baseline CI lower bound exceeds `min_effect`.
5. `r5_gate_5_active_memory_and_steps_reported`: steps and active memory are
   reported and are matched between candidate and baseline.
6. `r5_gate_6_no_extrapolation_beyond_noise_model`: every measured SNR point
   lies inside `declared_range_db`; the report sets `extrapolation=False` and
   `extrapolation_allowed=False`.

An underpowered item sweep or a single SNR point is `inconclusive`, not
`rejected`. Fewer than `min_seeds` seeds is also `inconclusive`. A control
that reproduces the candidate's gain, or a measured SNR outside the declared
noise range, is `rejected`.

## 7. Limitations

- This is a synthetic gate exercise. It cannot establish a real capacity,
  model, data, or intelligence result.
- Coupling gain, noise, and associations are declared synthetic parameters.
- The matched-variance control matches the synthetic stationary component
  variance, not a physical noise source.
- The bootstrap interval covers only the declared synthetic blocks.
- Results are not extrapolated beyond the measured SNR points.
- Promotion requires real frozen-model state or digest-bound embeddings, real
  held-out data with provenance, live native/runner evidence, and signed
  registry evidence.

## 8. Tests

```sh
python3 -m unittest tests.test_capacity_snr -q
```

The 14 tests cover typed configuration and explicit SNR definitions,
deterministic stub behavior, byte-identical reruns, a synthetic six-gate pass,
accuracy/CI/false-match/steps/memory metrics, control gate failures,
insufficient seeds, underpowered sweeps, single-SNR sweeps, SNR points outside
the declared noise model, and the mandatory no-real-claim/promotion-blocked
fields.
