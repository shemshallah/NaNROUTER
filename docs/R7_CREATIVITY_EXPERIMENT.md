# R7 — Tunneling and creative-insight experiment protocol

Status: protocol defined; no result claimed. Uses `mth/nan16/mth_graph_couple_128.nas` for the block-coupling primitive.

## 1. Hypothesis

Weak cross-region coupling (`0 < eta < 1`) can produce useful associations that a disconnected baseline (`eta=0`) and a fully mixed baseline (`eta=1`) do not. This is a hypothesis about task performance, not a claim of quantum tunneling or consciousness.

## 2. Conditions

| Condition | Coupling |
|---|---|
| D0 | `eta=0` disconnected baseline |
| D1 | `eta=0.05` weak tunneling analogue |
| D2 | `eta=0.25` moderate coupling |
| D3 | `eta=1.0` full mixing |
| R1 | random coupling with the same norm |
| S1 | shuffled geometry with the same edge count |
| P1 | phase-scrambled coupling |

## 3. Tasks

- Held-out analogical reasoning.
- Remote association with a known correct answer.
- Puzzle completion.
- Contradiction detection.
- Open-ended generation with human-rated novelty/usefulness.

## 4. Metrics

- Correct novel association rate.
- Factuality.
- Contradiction rate.
- Diversity / distinct-n.
- Repeatability under a fixed seed.
- Calibration.
- Latency and energy cost.
- Human-rated novelty and usefulness (for open-ended tasks).

## 5. Controls

Every functional claim needs parameter/compute-matched baselines:

- no module;
- graph diffusion;
- ordinary attention;
- parameter-matched MLP;
- random coupling;
- shuffled geometry;
- phase-invariant versus phase-sensitive matching.

## 6. Kill criteria

Reject the hypothesis if any of the following holds:

- No improvement over D0 or the matched baseline.
- Improvement only on training examples.
- High novelty but high falsehood.
- Unstable or irreproducible across seeds.
- Cost/latency not justified.
- Improvement disappears when the random-coupling or shuffled-geometry control is applied.

## 7. Evidence record

Each run records:

- universe ID, topology digest, operator digest, coupling `eta`;
- precision, seed, step count, clock tick;
- task IDs and held-out split digest;
- metrics and confidence intervals;
- trace envelope digest;
- result status (`supported`, `rejected`, `inconclusive`).

No “creative” claim is made from unusual output alone.
