# Head → Trihead → Global → Meta: causal hierarchical attention v1

**Status: design contract only. Not implemented, trained, deployed, or Transformer-comparable yet.**

Objective: add hierarchical attention as a trainable residual to the **existing 43M hybrid** rather than create a second language model. Freeze the original 43M checkpoint, retain its forward/reverse character and known-word paths, and prove causal credit assignment before unfreezing shared state.

## 1. Physical and role invariants

- A chart has exactly 8,388,608 physical bytes: 256 fixed head records and 32,640 mirror pairs. Preserve layout, identities, both directional lanes, and canonical permissions. No in-root K/V allocation, extra writer, or second physical pair space.
- NaNLMind's current TriadField describes **85 triads over heads 0..254 and head 255 as the field aggregate**. NaNROUTER's documented independent control policy reserves **0,4,5,6,7,8**, leaving 250 curriculum-eligible heads. A future 240/16 role split is a separate **versioned logical policy**, NOT something already shared by those repos. Reject incompatible mappings at integration; don't silently repurpose control heads.
- Temporary attention activations and 16-entry K/V history buffers are ephemeral. Durable hyperedges, route summaries and training changes follow existing native guest authorization, epochs, digest and snapshot/manifest gates. Distributed charts are linked pages of one logical state, not independent minds.

## 2. Four levels and a causal return loop

All levels operate on a frozen snapshot for token t, with a fixed logical schedule and explicit stage boundaries. Let d=16 be the native projected block width, expandable to eight blocks (128 features). Feature width, number of heads, sequence length, and training-event count are distinct quantities.

**Head**: Project Q_h(t), K_h(s), V_h(s) from current head/byte/word context. Attend causally over B<=16 committed recent or explicitly retrieved positions, with scaled dot product, stable softmax and a mask for future, inaccessible, missing or stale entries. Head residual is x_h + gate_h * attended_h. Pair-lane directional scores and phase can be gated biases, never proof of language usefulness.

**Trihead**: For each permitted (a,b,c), attend over head states and canonical pair projections. The existing 85 physical triads are an adapter starting point; a future policy may select nonlocal hyperedges as sparse candidates. Use trainable low-rank *third-order* interaction: T_abc = U_a(x_a) elementwise-multiplied by U_b(x_b) and U_c(x_c), with gated pair and hyperedge evidence. Pair-only mixing is a mandatory ablation. Avoid materializing all C(256,3)=2,763,520 possible triples.

**Global**: One field-level query sparsely attends to available trihead readouts and selected heads, with fallbacks for unknown evidence. Aggregate a bounded number of groups with a learned output residual into the **existing** decoder. Any field-head write is separately admitted; attention readout is not a new state authority.

**Meta**: Attend to **previously committed** global summaries and typed remote chart memories, keyed by address, epoch, generation, provenance and causal-parent digest. Missing or invalid remote state is masked; remote memory cannot overwrite the root. Meta's feedback is a bounded routing bias and/or decoder gate for the *next* token/epoch.

**Return**: head[t] → trihead[t] → global[t] → meta[t] → head[t+1]. Do not run an uncontrolled instantaneous feedback cycle (head[t] → ... → head[t]) or permit future-token leakage. Optional multiple microsteps must have a finite, explicit fuel and same-epoch frozen-snapshot semantics.

Readout: logits_hybrid[t] = logits_43M[t] + W_out(gated_head + gated_triad + gated_global + gated_meta). Preserve a **zero-gate identity** mode with bit-for-bit old decoder outputs. For trainability, initialize the residual gate small but nonzero during the separate adapter experiment, and record its exact initial value.

## 3. Necessary learning mechanism

The Q/K/V projections, triad low-rank contraction, sparse selectors, global/meta gates and output projection must receive verifiable gradients from causal next-token cross-entropy, with native-equivalent backward and optimizer checkpoint recovery. Votes/counts/softmax alone do not constitute trained attention. Protect 43M from regression: first freeze original decoder and train only adapter; permit shared decoder updates only after development-set rollback tests. Ensure no control-head starvation, bounded routing, input-finite checks and atomic publication.

## 4. Existing native execution seam

NaNROUTER docs describe locally tested native project16, head16 over 16 keys, mask16, and memory.condition16 kernels. This is **not** evidence of a trained multi-level attention stack, full dispatch availability, CI promotion or a live NANNET route. The older attention-controller capability document marks the full composition UNAVAILABLE. Reconcile native registry/CI and provide missing differentiable kernels and a validated ABI. If a stage is unavailable, return typed UNAVAILABLE; never insert a hidden host-language math fallback.

Implementation sequence: (1) native causal masked head + deterministic replay; (2) canonical pair/low-rank third-order trihead; (3) sparse field/global selection and gated hybrid-decoder readout; (4) epoch-checked cross-chart meta and return path; (5) native backward/optimization, tests and training.

## 5. Acceptance gates / benchmark

1. Preserve canonical root layout and writes; identical zero-gate logits to 43M checkpoint; no unauthorized writes; finite checked, atomic rejected outputs; deterministic replay.
2. Change future token, not-yet-committed runner message and stale remote epoch: all earlier logits remain identical. Test all-masked and same-epoch cases.
3. Nonzero gradients to *all* four learning levels; prove causal pair knockout changes hybrid logits when appropriate and restoration reverses it. If not, geometric contribution remains unproven.
4. Train/evaluate on a new, locked document-level held-out corpus, independent of previously reused R7–R21 test sets; compare 43M frozen, head only, head+trihead, +global, +meta, and a small causal Transformer with comparable parameter, token-exposure, compute and vocabulary budgets.
5. Primary cross-tokenizer metric bits per byte. Additional: valid exact-word (including OOV) perplexity, mapped-vocabulary perplexity (clearly separate), exact next-word accuracy, long-context recall, coherence, CPU/GPU latency, peak RAM and checkpoint size. Test context 16/128/512/2048 where supported.
6. Claim *comparable* or *exceeding* only with independently replicated matched-budget results, not from the geometric topology alone.

With H active heads, B memory slots, dimension d, R active triads and k sparse global/meta candidates, bounded attention contraction is approximately O(H*B*d + R*d + k*d) plus Q/K/V projections, retrieval and network costs. This is a hypothesized efficiency route, not a measured advantage.

References: NaNLMind include/nanlm/hypermatrix.hpp and src/hypermatrix.cpp; NaNROUTER docs/MIRROR_MEMORY_LAYOUT.md, docs/HEAD_ROLE_NAMESPACE_CONTRACT.md, docs/NATIVE_ATTENTION_AND_CAUSALITY.md, docs/ATTENTION_CONTROLLER.md.
