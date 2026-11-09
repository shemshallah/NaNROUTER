# Rounds 038–039 — unrestricted subword generation and native-cycle audit

**Status:** external C++20/PyTorch experiments. Not native NaN16 production
math and not a fluent language model.
Archive SHA-256: `392cd775605fe829787ccee0354ad7c2fda4f6798b5d22948a03d5ad36f43f87`.
Machine-readable record: `spec/rounds-038-039-free-generation.v1.json`.

The Round 039 archive includes the Round 038 sources; no separate Round 038
archive was present. Round 038's 1,200-update results are retained only as
superseded evidence because its windowing protocol repeated short definitions.

## What became real

- A learned 2,048-subword vocabulary, sampled token by token.
- No answer templates and no copied stored definition during generation.
- About **463,984 parameters** in the 96-channel model.
- A 16×16 native cycle adapter whose 256 coefficients are physically stored
  as directed three-edge triangle circulations in the 8 MiB root.
- Gradient updates into the native pair lanes, native snapshot/restore, and
  additive vertex-gauge perturbation.
- A matched dense 16×16 tensor control with the same random seeds, stream,
  and nominal degrees of freedom.

## Round 038 preliminary result

| Model | Held-out perplexity | Next-token accuracy |
|---|---:|---:|
| Conventional recurrent | 183.3 | 14.18% |
| Native mirror-cycle | 186.8 | 14.81% |

Removing the learned native cycle readout raised perplexity to **262.2**.
Gauge changes left predictions effectively unchanged. This was a real
memory-dependent generative prototype, but the result came from the later
corrected-out repeated-definition windowing protocol.

## Round 039 corrected paired result

240 updates, batch 8, context 32, 300 untouched test definitions,
7,863 next-token targets. The optimizers are **not strictly matched**: the
native adapter used plain gradient steps at lr=0.02; the dense control used
AdamW at lr=0.002.

| Model | Full perplexity | No memory | Shuffled memory | Top-1 |
|---|---:|---:|---:|---:|
| Dense 17 | **251.845** | 263.653 | 272.506 | 12.998% |
| Native 17 | 255.613 | 259.791 | 260.785 | 12.972% |
| Dense 29 | **257.546** | 270.900 | 276.711 | 12.603% |
| Native 29 | 261.806 | 266.747 | 264.897 | 12.578% |

The dense control wins perplexity by **3.77** and **4.26** points. Every model
degrades when its learned memory is removed or shuffled. Native gauge
round-trips are below **1.13 × 10⁻⁶** maximum cycle change in both seeds.

The samples remain malformed and incomplete. This is a genuine unrestricted
generator prototype, not fluency, not a general reasoner, and not evidence of a
geometric language-model advantage.

## What the result rules out

Simply enlarging the fixed learned cycle-weight adapter is not the next useful
experiment. The adapter behaves mostly like a durable alternative parameter
store. The next architecture must make the memory state depend on the current
content:

```text
M(t+1) = Write(M(t), h(t), x(t))
h(t+1) = Reason(h(t), CycleRead(M(t+1)))
```

That requires sparse, persistent, gated writes driven by tokens or episodes,
and a readout that changes the next state rather than only adding a fixed
linear term.

## Native NaN16 additions in this integration

| Kernel | Role |
|---|---|
| `mth.mirror.cycle.train_step.f32` | Content-gated delta-rule write: prediction, error, SSE, three-edge mirrored update |
| `mth.mirror.cycle.predict16.f32` | Native 16×16 CycleRead forward pass |
| `mth.trig.sincos.f32` | In-guest sine/cosine for phase, rotation, and spectral use |

The training step leases a 16-pair bank inside the one 8 MiB universe
(base head 1..223). It is not a second universe, store, or learning authority.
The native fixture trains a one-hot mapping for nine steps, requires strictly
decreasing SSE, checks that all predictions exceed 0.8, verifies the physical
lane mirror, and exercises domain rejection.

## Non-claims

- No perplexity or accuracy win over the matched dense control.
- No claim that gauge invariance improves language prediction.
- No claim that the external C++ adapter is NaN16 execution.
- No fluent generation, open-domain learning, or general reasoning.
- No canonical checkpoint, live deployment, or production model.
- No claim that 256 geometry coefficients exploit most of the 8 MiB geometry.

## Next gate

The next experiment should compare, on natural unnormalized prose:

1. content-dependent sparse writes with learned gates;
2. the same writes with a conventional dense episode memory;
3. the same gauge-invariant features with an equally informed baseline;
4. free-text perplexity, multi-hop recall, retention after new writes, and
   gauge drift reported as separate outcomes.

The geometry should have to improve learning, not merely preserve storage.
