# Unified decoder field — 255 heads, triadic relations, and the role of tensors

**Status:** architecture contract and native integration ledger. The field
mixture primitive is implemented; full 255-head training, a multi-head
decoder, and a native backward pass are not.

## 1. The shape of the system

Do not build 255 independent language models. Build one shared decoder field
with 255 individually addressable heads:

```text
shared token/byte embedding
        |
        v
255 head states: h_h in R^16, phase theta_h, gate g_h
        |
        v
per-head low-rank adapters + rotations + q/k/v attention
        |
        v
field mixture: out = sum_h g_h * head_value_h
        |
        v
pair -> triadic hyperedge -> relation-of-relations abstraction
        |
        v
next-token / next-byte distribution
```

NANNET0 remains the boundary port at ring position 255. It is **not** head 255
and never rotates with the real 255-head field.

## 2. Why 255 heads fit

The expensive object is not the head state. It is dense head-to-head attention.

```text
255 x 16 head state        = 4,080 float32 words = 16 KiB
255 x 255 field tile       = 65,025 float32 words = 254 KiB
16 x 16 per-head adapter    = 256 float32 words
```

The 256×256 field tile fits the existing 2 MiB guest budget and the existing
256-point matrix/Laplacian/DFT kernels. It does not require a second universe.
Three-way relations are **sparse**, not a dense 255³ tensor.

## 3. The head decoder

Each head h has:

| Component | Meaning |
|---|---|
| `h_h` | 16-channel state vector |
| `theta_h` | phase from ring position, token position, and content |
| `g_h` | gate from phase coherence, evidence confidence, and learned weight |
| `W_h^q/W_h^k/W_h^v` | low-rank adapters on the shared trunk |
| `hyper_h` | incident triadic hyperedges |
| `logits_h` | optional per-head vocabulary/logit correction |

The shared trunk prevents 255× full-model cost. The per-head adapters make each
head an individual decoder component. The field mixture combines them.

Implemented native seams:

- `mth.attention.project16.f32` — affine projection;
- `mth.attention.head16.f32` — score/softmax/value head;
- `mth.attention.mask16.f32` — causal/boolean masking;
- `mth.memory.condition16.f32` — `h + gate*memory`;
- `mth.field.mix255x16.f32` — all 255 heads into one 16-channel field vector;
- `mth.vector.logsoftmax256.f32` and `mth.lm.cross_entropy256.f32` — output loss.

## 4. Trigonometry and rotation

Trigonometry is the address and phase language of the field:

1. **Ring address:** head h sits at angle `2*pi*h/255`; NANNET0 is outside the
   rotating set.
2. **Relative phase:** rotate q/k vectors by token-relative phase so dot
   products depend on relative position.
3. **Complex circulation:** support/refute lanes can be phase-bound rather than
   only additively combined.
4. **Oscillatory gates:** `gate_h = 0.5*(1+sin(omega_h*t+phi_h))`; testable,
   not assumed beneficial.
5. **Spectral field:** native twiddles turn the 255-head ring into a modal
   field; graph Laplacian/DFT modes are field abstractions.
6. **Gauge:** additive vertex gauge is cancelled by triangle circulation;
   phase closure is a separate, stronger invariant for loops.

## 5. Three-way relations and abstraction

A pair relation is an oriented mirror-pair triangle. A triadic relation is a
typed 3-vertex simplex, not merely three independent pairs:

```text
triad = (a, b, c, type, phase, strength, support, refute)
```

The boundary of the triad has three oriented pair edges; its interior carries
a cycle/phase invariant. This is why a 3-way relation can encode composition
that a set of pair scores cannot.

Abstraction ladder:

```text
L0 token/byte
L1 head state
L2 pair relation (mirror triangle)
L3 triadic hyperedge (typed simplex)
L4 hyperedge-of-hyperedges (relation IDs as vertices)
L5 field mode / gated abstraction
```

L4 is the "further abstraction" step: a hyperedge ID can be a vertex in a
higher incidence layer. The same 8 MiB universe stores the sparse incidence
records; no second graph is created.

## 6. Where tensors come in

A tensor is only a typed array with shape and indexing rules. The field uses:

| Tensor | Shape | Storage |
|---|---|---|
| head state | 255 × 16 | dense tile |
| field operator | 256 × 256 | tiled dense matrix |
| adapter | 16 × 16 | dense per head/tile |
| pair relations | sparse | 32,640 mirror records |
| triadic relations | sparse | typed incidence records |
| relation-of-relations | sparse | higher incidence records |

Do **not** allocate a dense 255³ tensor. The sparse hyperedge layer is the
point. A `255×255` field tile is acceptable; a `255×255×255` tensor is not.

## 7. Where gradients come in

Gradients are local correction fields, not a second hidden math authority.

The output loss is next-token cross entropy. For a token distribution over
heads:

```text
p(next) = sum_h g_h * p_h(next)
dL/dz_h = g_h * (p_h - target)        (mixture gradient)
```

For each head path, the derivative flows through:

- the gate (`dL/dg_h`);
- the rotation phase (`dL/dtheta_h`);
- the projection (`dL/dW_h`, `dL/dh_h`);
- the memory readout (`dL/dmemory`);
- the hyperedge type/strength (discrete or continuous).

Current native mechanisms:

- `mth.field.mix255x16_backward.f32` — full field-mixture reverse:
  `d_weight[h]` and `d_value[h][c]` for every one of the 255 heads;
- `mth.field.gate255.f32` / `mth.field.gate255_backward.f32` — 255-head softmax
  gate forward and full softmax Jacobian reverse;
- `mth.mirror.cycle.train_step.f32` — gated delta write;
- `mth.mirror.cycle.retain.f32` — consolidation;
- analytic derivative for affine projection and rotation;
- straight-through or score-function updates for discrete hyperedge choices.

A native in-place field-training step, `mth.field.train_step255x16_f32`, now
applies the mixture gradients:

```text
weight[h]   -= lr * d_weight[h]
value[h][c] -= lr * d_value[h][c]
```

for all 255 heads. It is one SGD step, not a full model optimizer.

Still open: internal attention-head Q/K/V reverse and a full joint field-training
loop. The field mixture, 255-head gate reverse, and one field SGD step are
implemented.

PyTorch-style autograd is an external research tool, not a runtime authority.
A full native backward pass for the 255-head field remains open.

## 8. Training and evaluation gates

1. **Field smoke test:** 255-head mixture reduces to one-hot/uniform cases.
2. **Paired head attention:** 255×255 tile, causal mask, phase gates.
3. **Joint memory/decoder loss:** token CE + relation/proof + hyperedge
   reconstruction + gauge/mirror residual.
4. **Natural prose:** source-disjoint held-out text, not only WordNet glosses.
5. **Matched control:** same head count, memory information, parameters, and
   training budget in a conventional field.
6. **Ablations:** no memory, shuffled memory, phase-gate off, rotation off,
   hyperedge layer off.
7. **Fluency:** human/token metrics and generated samples reported separately
   from accuracy.

## 9. Implemented now vs open

| Component | Status |
|---|---|
| 255×16 field mixture | **implemented** `mth.field.mix255x16.f32` |
| 16-key single head | implemented |
| 16-position mask | implemented |
| memory conditioning | implemented |
| log-softmax / cross-entropy | implemented |
| 255×255 head-to-head attention | open |
| multi-head packing | open |
| native backward for field | open |
| triadic sparse hyperedge layer | partially existing, not integrated |
| joint field training | open |
| natural-prose/fluency comparison | open |

The next concrete native step is a tiled `255×255` field-attention kernel with
masking and phase gates, followed by a sparse triadic incidence layer whose
edges reference head IDs. The field mixture already fixes the aggregation
contract: all 255 heads contribute, NANNET0 does not.
