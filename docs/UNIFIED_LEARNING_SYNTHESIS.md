# Unified learning synthesis — Rounds 023–042

**Status:** architecture synthesis and native integration ledger. It separates
what is already implemented from what is still proposed. The external
C++/PyTorch experiments are evidence inputs, not native NaN16 claims.

## 1. The one-sentence synthesis

Keep the 8 MiB mirror universe as the durable relational object, replace the
fixed cycle adapter with **content-gated, error-driven writes**, add native
**phase/rotation** primitives so memory can be addressed and combined
oscillatorically, and judge the result only against an equally informed
conventional memory on natural prose.

## 2. Good points harvested from the rounds

| Round | Useful result | Failure or boundary |
|---|---|---|
| 023 | Native pair map, triangle circulation, gauge-invariant transport | Address/data layout only; no learning by itself |
| 024 | Hyperedge strength storage | Strength is not truth |
| 025 | Transcript-only semantic proposal | No shipped corpus; not reproducible as a corpus claim |
| 026 | 26-slot mirrored root step | Gradient step only; not a complete optimizer |
| 027 | Typed relation operators and hyperedge paths | Deterministic, caller-resolved composition |
| 028 | Shared-composition experiment | External evidence; no native shared matrix |
| 032 | 250k exact retrieval, stored two-hop | Hash is faster than the geometric path in the tested setting |
| 033 | 886/900 exact copies, gauge-invariant copies, copy gate | Free-form LM tied with control; not fluent |
| 034 | Copy-or-abstain router | Degrades under untrained corruption |
| 035 | Recursive 3-hop composition (120/120) | Raw-edge baseline 60/120; 4-hop/contradiction weak |
| 036 | Neural multi-source generation with entity slots | Restricted vocabulary; not free prose |
| 037 | Prose → typed writer → mirror → multi-hop → decoder | Entity boundaries supplied; controlled paraphrases |
| 038 | 2,048-subword free sampling; memory-ablation effect | Superseded repeated-definition windowing |
| 039 | Corrected paired audit; native gradient writes; gauge invariance | Dense control wins perplexity; malformed samples |
| 042 | Joint writer → native two-lane memory → differentiable propagation → decoder; causal deletion; four-state dialogue | Conventional memory ties clean inputs; restricted vocabulary; language-only collapses to abstention |
| 043 | Frozen byte LM + native 3-byte associative cache; 5.67% lower loss; post-gauge online writes | Flat cache ties; generated text still incoherent; not end-to-end or multi-hop |

## 3. The failure pattern

The failures share one shape:

```text
neural learner        geometry             decoder
     |                   |                   |
  learns once       stores evidence       reads once
     |                   |                   |
     +--------- mostly fixed after training ---------+
```

The geometry is excellent at **storage and invariant transport**, but in the
tested systems it is not yet part of the learning loop. Enlarging a fixed
16×16 cycle adapter just creates a different parameter store. That is why the
dense control is a fair and necessary baseline.

## 4. The architecture that should replace it

```text
token / episode x(t)
        |
        v
native route + relation writer
        |
        v
gate(t) = content and phase dependent
        |
        v
M(t+1) = Write(M(t), x(t), error(t), gate(t))
        |
        v
CycleRead(M(t+1)) -> h(t+1)
        |
        v
decoder / reasoner -> next token or answer
        |
        v
audit: mirror, gauge, retention, ablation
```

The key is that `Write` is not a fixed outer product. It is a **gated delta
rule** driven by the current prediction error and content:

```text
prediction[c] = sum_d x[d] * CycleFlux(d,c)
error[c]      = target[c] - prediction[c]
delta(d,c)    = lr * gate[c] * error[c] * x[d]
```

`mth.mirror.cycle.train_step.f32` implements this in NaN16. It writes the
same amount to `(0,a)` and `(a,b)` and the opposite amount to `(0,b)`, in both
physical lanes. The native circuit therefore changes by exactly `delta`, and
the mirror invariant is preserved.

## 5. Native loop, stage by stage

| Stage | Native status | Primitive / gap |
|---|---|---|
| Address 8 MiB universe | Implemented | pair map, slot map, universe map |
| Store typed evidence | Implemented | pair lane I/O, relation class, definition slots |
| Compose paths | Implemented | hyperedge path/incidence, relation operator |
| Gauge-invariant read | Implemented | triangle recover, gauge check |
| Content-gated write | Implemented | `mth.mirror.cycle.train_step.f32` |
| Cycle readout | Implemented | `mth.mirror.cycle.predict16.f32` |
| Phase / rotation | Implemented | `mth.trig.sincos.f32`, `mth.trig.rotate.f32` |
| Snapshot / restore | Implemented | block checksum, root snapshot host seam |
| Tokenizer / embedding | Not native | Host-side model runtime; do not claim native |
| Attention / log-softmax | Partly native | softmax/logsumexp exist; full attention projection does not |
| Natural-language parser | Not native | Entity boundaries were supplied in Round 037 |
| Joint writer/decoder training | Not implemented | Central open gate |
| Contradiction-preserving reasoning | Not implemented | Central open gate |
| Retention after new writes | Demonstrated externally | Needs native long-run test |

## 6. Trigonometry as a first-class native layer

Trigonometry is not decoration here. It supplies the operations the
geometry lacks:

1. **Rotation instead of additive position.** RoPE-style query/key rotation
   changes dot products by relative position and preserves norm.
2. **Complex circulation.** A real circulation plus a phase becomes a phasor;
   writes can interfere constructively or destructively.
3. **Native twiddles.** The DFT/wave path no longer needs a host sin/cos table.
4. **Oscillatory gates.** `gate[c] = 0.5*(1+sin(omega[c]*t+phi[c]))` gives
   content-independent write windows, which can be compared against learned
   gates.
5. **Phase closure.** A loop of phases can test consistency without forcing
   every cycle to zero; this is the right direction for preserving
   contradictory evidence.
6. **Ring addressing.** A rotation of the 255-lane ring is an angular address
   map, while NANNET0 stays fixed at ring position 255.

The implemented layer is deliberately small: a scalar sincos and a plane
rotation, with exact rejection outside the declared angle domain. It is enough
to build the next experiments without host math. See
`docs/TRIG_NATIVE_SYNTHESIS.md`.

## 7. What "truly learning" must mean operationally

A system is not learning merely because it stores a fact. The next experiment
must show all of the following:

1. **Acquisition:** error on new episodes decreases with additional native
   writes.
2. **Generalization:** held-out combinations of the same relations improve,
   not just memorized strings.
3. **Retention:** old answers survive new writes and additional training.
4. **Memory dependence:** removing or shuffling the native memory degrades
   performance.
5. **Gauge robustness:** an additive gauge change does not damage predictions.
6. **Matched control:** an equally informed conventional memory sees the same
   episodes, copied evidence, and feature treatment.
7. **Natural input:** unnormalized prose, model-produced entity boundaries,
   multiple sentences, and 500+ tokens of intervening noise.
8. **Contradiction:** conflicting evidence remains representable; the system
   does not silently force closure.
9. **Cost:** report geometry time/space against the conventional baseline.
10. **Retention after adaptation:** new writer/decoder training does not erase
    old episodic knowledge.

## 8. Training curriculum for the next gate

```text
phase 1  synthetic typed relations, supplied boundaries       (current)
phase 2  natural paraphrase, model-produced boundaries
phase 3  multi-sentence episodes, distant evidence
phase 4  contradictory and uncertain sources
phase 5  new episodes after training, retention audit
phase 6  free-form generation from recovered evidence
```

At every phase, keep two memories:

- native mirror memory;
- conventional indexed memory with identical evidence and capacity budget.

Run ablations: no memory, shuffled memory, gauge-perturbed native memory,
fixed-adapter native memory, and content-gated native memory. The comparison
that matters is content-gated native versus the same gate on conventional
dense memory. If they tie, the geometry is a storage choice, not a learning
advantage.

## 9. Native next kernels

The first batch is now implemented and locally verified:

| Primitive | Status |
|---|---|
| `mth.mirror.cycle.phase_gate16.f32` | implemented: clamped oscillatory gates |
| phase bind | implemented as `mth.trig.rotate.f32`; bank-level bind is caller composition |
| `mth.trig.twiddle256.f32` | implemented: native 256-point twiddle table |
| `mth.mirror.cycle.retain.f32` | implemented: gated bank consolidation |
| candidate competition | implemented at the readout seam as `mth.attention.mix16.f32` |
| `mth.mirror.cycle.contradiction.f32` | implemented: support/oppose/conflict/balance without collapse |
| `mth.mirror.evidence.cycle_state.f32` | implemented: two-lane support/refute → unknown/support/refute/both |
| `mth.vector.logsoftmax256.f32` | implemented: stable native log-softmax |
| `mth.lm.cross_entropy256.f32` | implemented: native 256-way language loss |
| `mth.byte.assoc3_reserve.u32` | implemented: 3-byte context → 128 reserved rows |
| `mth.byte.memory_mix256.f32` | implemented: base/memory probability interpolation |
| `mth.attention.project16.f32` | implemented: one affine 16→16 Q/K/V-style projection; full attention block still open |
| `mth.attention.head16.f32` | implemented: one 16-key score/softmax/value-mix head; multi-head block still open |
| `mth.attention.mask16.f32` | implemented: 16-position boolean score mask with empty-mask rejection |
| `mth.field.mix255x16.f32` | implemented: all 255 real heads mixed into one 16-channel field vector; NANNET0 excluded |
| `mth.memory.condition16.f32` | implemented: gated residual `h + gate*m` memory injection |
| `mth.mirror.pair.knockout.f32` | implemented: metadata-local causal pair deletion/restoration |
| `mth.ring.angular_map.u32` | implemented: 255 real lanes, NANNET0 fixed at 255 |
| `mth.attention.project.f32` | not implemented: full Q/K/V projection remains open |
| `mth.mirror.cycle.contradiction` phase closure | not implemented: numeric conflict pair exists; loop phase closure is still proposed |
| `mth.graph.path_competition.f32` | partially addressed: weighted candidate readout exists, learned path search does not |

The next honest engineering gate is full native Q/K/V projection with a fixed
model contract, followed by a matched geometric-versus-conventional training
comparison. The new primitives are ingredients, not a fluent model.

## 9b. Round 042 addendum

Round 042 removes the supplied proof-status token and trains the writer,
native two-lane memory, differentiable propagation, and response decoder
jointly. It adds independent support and refutation lanes, causal physical
deletion/restoration, and a four-state speaker. The conventional signed
adjacency ties clean-input accuracy. Language-token loss alone collapses to
abstention (90/180), while joint supervision succeeds. The native additions
here are log-softmax, 256-way cross-entropy, and two-lane evidence state
classification; full open-domain fluency remains unproven.

## 9c. Round 043 addendum

A frozen SO(72) byte model plus a native 3-byte associative cache lowered mean
held-out loss from **1.744586** to **1.645717** nats/byte (5.67%) across three
seeds, with post-gauge writes/deletion/restoration and a previously unseen
3-byte online context moving from probability 0 to 0.953869. The flat
conventional cache ties numerically; generated samples remain incoherent; the
cache is not the multi-hop graph reasoner. The native seam added here is
reserved-row hashing plus base/memory probability interpolation. The next gate
is a shared next-token loss connecting the trained relation memory to the
free-running decoder, trained end-to-end and compared on natural prose.

## 10. Guardrails

- One 8 MiB universe; no second universe, ring, store, or math authority.
- 255 logical lanes plus NANNET0 at ring position 255.
- Six ring slots, one active runner, 7 GiB active ceiling.
- All runtime mathematics in NaN16; no host numerical substitution.
- Missing native operations return typed `UNAVAILABLE`.
- Local fixture evidence is not CI verification; CI is not a live deployment.
- External C++/PyTorch evidence is not native NaN16 production evidence.
- A gauge invariant is not a language-model advantage.
- A memory ablation is not proof of understanding.
- A matched conventional baseline is mandatory before any geometry claim.
