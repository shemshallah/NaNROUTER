# Round 042 — joint dialogue, two-lane evidence, and causal memory

**Status:** external C++20/PyTorch experiment. Not native NaN16 production
math and not a fluent open-domain model.
Release archive: `nan_recursive_round042-1.zip`
SHA-256: `d2480eaf68233da41a5952251cc82c962c137914403171d1f373ba5e0d4ffe28`.
Machine-readable record: `spec/round042-joint-dialogue.v1.json`.

## What changed

Round 041 supplied the generator with a proof-status token. Round 042 removes
that shortcut:

```text
prose facts -> learned relation writer
           -> native 8 MiB support/refute pair lanes
           -> differentiable propagation
           -> continuous evidence state
           -> autoregressive response decoder
```

The language loss is part of the joint path. The primary decoder uses 54
function-word/role tokens plus concept names copied from slots. Entity
boundaries and constrained relation forms are supplied.

The bridge exposes an analytical straight-through identity Jacobian for the
exact write/read interface. It is not a learned backpropagator, and the native
C++ root is not NaN16 production execution.

## Results

Three seeds 17/29/43, 650 steps, 180 test examples per seed.

| Experiment | Correct |
|---|---:|
| Unseen two-to-four-hop questions | **540/540** |
| Same after gauge disturbance | **540/540** |
| Five-hop questions beyond training depth | **525/540** |
| Causal native-edge deletion -> abstention | **240/240** |
| Restoration after deletion | **240/240** |
| Causal gauge outputs unchanged | **480/480** |
| Causal permuted node indices unchanged | **480/480** |
| Four-state neural responses | **480/480** |
| Four-state responses after gauge | **480/480** |
| Few-shot new phrase classes | **3/3** |
| Old phrase classes retained | **16/16** |
| New-phrase source-disjoint QA | **180/180** |
| Language-loss-only training | **90/180** (0 positive, 90 negative) |

The conventional signed-adjacency memory and an independently retrained
conventional bridge both score **540/540** on clean inputs. The geometry is a
working representation, not a demonstrated clean-input advantage.

The five-hop failure mode is broken-chain negatives. The language-only run
did not bootstrap reasoning: it collapsed to always abstaining. The corrected
evaluator no longer counts the word “conclusion” in an abstention as a positive
answer.

## Two evidence lanes

The support lane is channel 0; explicit refutation is channel 1. They are
independent, so both can coexist. The four states are:

```text
unknown  = neither lane positive
support  = support lane positive
refute   = refutation lane positive
both     = both lanes positive
```

This is a paraconsistent representation: refutation does not overwrite
support, and `both` does not imply arbitrary conclusions. The four-state
speaker is a second bounded-grammar network; it is not a fluent dialogue
model.

## Native additions in this integration

| Kernel | Role |
|---|---|
| `mth.vector.logsoftmax256.f32` | Stable native log-softmax for language losses |
| `mth.lm.cross_entropy256.f32` | Native 256-way cross-entropy from log-softmax/logsumexp |
| `mth.mirror.evidence.cycle_state.f32` | Read support/refute triangle lanes and classify unknown/support/refute/both |

The evidence kernel reads the physical 8 MiB pair geometry, not a host copy.
It returns both continuous lane values and the four-state code.

Existing cycle train/read, contradiction, retention, trig, attention mixing,
and angular ring primitives remain the composition base.

## Non-claims

- No fluent open-domain language.
- No solved arbitrary prose parsing; entity boundaries are supplied.
- No geometric accuracy advantage over a matched conventional memory.
- No language-only acquisition: token loss alone collapsed to abstention.
- No claim that gauge invariance equals natural distribution robustness.
- No transactional or cryptographically secure snapshot claim.
- No NaN16 production, live deployment, or general dialogue claim.

## Next gate

The next scientific gate is the one Round 042 identifies: remove the constrained
parser and auxiliary proof supervision without collapse, then compare native and
conventional memory on naturally occurring prose with real next-token
likelihood, retention, contradiction, and causal ablation.
