# R5 capacity-versus-SNR experiment plan

Status: test plan only. No capacity benefit is claimed. Native primitives exist;
a real experiment still needs a frozen model/data harness and a live runner.

## 1. Question

Does the wave/aperture memory increase useful capacity or retrieval quality at a
fixed SNR, compared with a parameter- and compute-matched local baseline? A
capacity claim is valid only if it survives held-out tasks, matched controls,
and a declared noise model.

## 2. Inputs

- A frozen, digest-bound embedding or model state source; no training inside
  this experiment.
- A validated 256×256 aperture (or its versioned pages) with role
  `memory`, `filter`, or `covariance`.
- A deterministic colored-noise generator: `mth_colored_noise_256.nas`.
- Native primitives: `dot256`, `norm256`, `cosine256`, `topk256`, the aperture
  matvec/SVD path, and the DRIVE source.
- A declared SNR sweep and seed set fixed before the run.

## 3. Conditions

| Condition | Purpose |
|---|---|
| local-only matched baseline | parameter/compute control |
| coupled aperture candidate | treatment |
| aperture with zero/random coupling | coupling control |
| phase-scrambled or shuffled memory | phase/association control |
| colored noise at matched variance | noise robustness |

The baseline and candidate must receive the same inputs, token budget, and
number of native calls, or the comparison must declare the mismatch.

## 4. Metrics

- held-out top-1/top-k retrieval or association accuracy;
- paired delta versus each baseline with a confidence interval;
- capacity at fixed SNR (items retained before accuracy falls below threshold);
- false-match rate on null/shuffled signatures;
- phase-coherence ratio from `mth_phase_coherence_128.nas`;
- native steps and active memory per condition.

## 5. Gates

A capacity claim is `supported` only when all of the following hold:

1. the candidate beats the matched baseline on held-out data;
2. the zero/random-coupling and shuffled controls do not reproduce the gain;
3. the gain persists across at least two seeds and the declared SNR range;
4. the uncertainty interval excludes zero;
5. active memory and steps are reported;
6. no result is extrapolated beyond the measured noise model.

Otherwise the result is `rejected` or `inconclusive`. Novelty, unusual output,
or a single seed is never evidence.

## 6. Not yet run

The experiment requires a real frozen model/data set, signed registry evidence,
and a live runner. The local repository contains the native noise, reachability,
top-k, aperture, and phase primitives but does not bundle that data. This plan
does not claim a capacity or intelligence result.
