# MTH — NaN-Native Mathematical Substrate
## Game plan and implementation contract

**Status:** architecture/game plan; not an implementation or a claim that the gates below already pass  
**Canonical source language:** NaN16  
**Canonical word:** 64-bit dual-ended NaN word  
**Repository home:** NaNROUTER  
**Purpose:** provide the mathematical operations a language model needs, implemented natively in NaN language

---

## 1. The objective

MTH is the mathematical substrate for NaNLMind. It is not intended to become an encyclopaedia of every mathematical field, a conventional calculator, or a second execution universe.

Its job is narrower and more useful:

1. Represent the mathematical values and structures a language model actually works with.
2. Execute the transformations needed to learn, compare, predict, reason, and generate.
3. Make those transformations composable, inspectable, reproducible, and testable.
4. Preserve exactness when exactness is available; make approximation and error visible when it is not.
5. Allow the model to discover and propose new transformations without silently granting an unverified candidate authority.
6. Implement every mathematical function in NaN language. The mathematical implementation is NaN16 source, not a host-language library hidden behind a NaN interface.

MTH is a capability of the one canonical NaNLMind universe. It does not create a separate math service, runner universe, model, or owner of state. NaNROUTER provides the authorized route to the existing execution fabric; it does not become the owner of mathematical truth or the mathematical implementation.

### The completion criterion

Do not measure MTH by the number of names in an operator catalogue. Measure it by whether the system can:

- represent the values and structures used by the model;
- execute the essential operations correctly;
- compose operations into larger transformations;
- state the domain and preconditions of each operation;
- produce evidence for results;
- detect unsupported operations and invalid inputs;
- compare implementations under real resource constraints;
- improve its implementations without changing their semantics.

"Complete" means a closed, reliable core plus a mechanism for defining, composing, testing, and promoting extensions. It does not mean that every mathematical theorem or every computable function has been prewritten.

---

## 2. The NaN word is the design centre

### 2.1 Existing 64-bit word: preserve the real NaN16 contract

MTH uses the existing 64-bit NaN16 instruction/data word. It must not invent a new IEEE-754 layout or infer a byte diagram from the phrase "double endian." The canonical encoding is the one implemented by the NaN16 assembler, interpreter, loader, and current guest libraries.

The repository's existing double-ended carrier implementation (`n16de.nas`) establishes concrete conventions that MTH must preserve:

- the carrier uses NaN16 class `10` for its data/delimiter/resynchronization records;
- class `11` is used for its control record;
- the 32-bit payload is divided into a 16-bit tag in bits 31..16 and a 16-bit chunk in bits 15..0;
- tag `0` identifies the big-endian member and tag `1` identifies the byte-swapped member;
- a chunk is emitted as a pair, and the decoder checks the pair rather than silently trusting one half;
- a disagreement is a decode failure that allows the caller to resynchronize.

These are facts about the existing carrier format, not proof that every MTH object must use this same pair-vote encoding. MTH should reuse the established format where it fits and define new, versioned record formats where it does not.

The four NaN types and their exact bit patterns must be imported from the canonical NaN16 specification and interpreter implementation before MTH assigns them new semantic roles. In particular, do not assume that a conventional IEEE binary16 NaN bit diagram describes the custom NaN16 word.

**Freeze rule:** the actual word width, face/lane ordering, class decoding, payload positions, and `BSWAPM` transformation must be read from the canonical NaN16 implementation and captured in machine-readable fixtures. Until that audit is complete, this document intentionally does not publish a speculative byte-by-byte diagram or new opcode allocation.

### 2.1.1 The four NaN types and the 16 ordered pairs

MTH must expose all four existing NaN types as distinct native values. Where the machine presents two independently typed ends/faces, the ordered pair is meaningful: `(A,B)` is not automatically equivalent to `(B,A)`.

The 16 ordered combinations are a complete 4-by-4 pair space. They are not limited to mirror pairs, palindromes, or the four self-paired cases. MTH must enumerate and test every combination, including non-mirror pairs, and retain both orientations.

Do not assign the four types meanings such as "data," "instruction," "error," or "control" globally. A record family may define such roles locally, but the underlying NaN type remains visible and inspectable.

### 2.2 Use all 16 combinations

MTH must preserve all 16 class nibbles as distinct encodings. It must not canonicalize a word merely because its faces can be swapped, and it must not restrict data to neutral/palindromic words.

The existing byte-reversal law is:

```
rot2(n) = ((n & 3) << 2) | (n >> 2)
```

A full-word double-endian reversal swaps the faces and reverses the payload bytes. It therefore changes the ordered class nibble in a defined way. Four nibbles are fixed under this rotation (0, 5, 10, 15); the other twelve form six two-element orbits. Those six pairs are useful relationships, not permission to discard either member.

**MTH rule:** an encoding and its reversed encoding are distinct words with a known transformation between them. A caller may explicitly request reversal, compare the two, or prove a relation between them. No storage layer or optimizer may silently identify them.

### 2.3 What the NaN space buys us

With four legal face classes at each end, there are 16 ordered face combinations. With a 32-bit payload, the present dual-ended format has up to:

```
16 × 2^32
```

structural word patterns before applying operation-specific validity rules.

That is a large structured space, but it is not a license to pretend that every pattern is already a valid MTH object. MTH assigns meaning through versioned instruction, data, and record contracts. Unknown combinations remain unknown until specified.

The four face types should be treated as a native alphabet:

- **sign** is a real semantic distinction, not decoration;
- **quiet/signaling** is a real semantic distinction, not a generic valid/invalid bit;
- **near/far position** is a real semantic distinction;
- **ordered pairs** are retained as ordered pairs;
- **payload** carries the operation-specific value, operand, index, or compact record field.

Do not assign a universal meaning such as "signaling always means error" or "quiet always means data" without a per-format contract. Those meanings can be useful in a particular MTH record family, but they must not override the frozen machine semantics.

### 2.4 Instruction words and data words

MTH uses the same native 64-bit word substrate for both instructions and data, but their interpretation is determined by the containing stream/object contract.

**Instruction word**
- Uses the frozen NaN16 instruction layout.
- The ordered class nibble retains the existing Boolean truth-table / instruction-predication semantics.
- The payload retains the frozen opcode and operand layout.
- Undefined opcodes trap. They do not become extensions by accident.

**Data word**
- Uses an explicitly declared MTH data format.
- The two face classes and payload are interpreted by that format's versioned contract.
- Data must not be executed merely because its bits happen to resemble an instruction.
- An instruction must not be reinterpreted as a scalar merely because its payload is numerically convenient.

**Object/stream metadata**
- Declares whether a word stream is code, scalar data, vector data, a matrix/tensor block, an index stream, a proof/evidence record, or another registered object.
- Declares format version, element type, length/shape, and byte/word order.
- Does not require a new native execution owner.

The exact MTH data-word allocation is an implementation gate. Do not freeze a new bitfield until the NaN16 assembler, interpreter, loader, and existing word tests have been checked together. The first design should reuse known-good NaN16 operations and add explicit format descriptors, not invent a second incompatible ISA.

### 2.5 Double-endian is a first-class operation

The existing `BSWAPM` behavior is a core mathematical and data operation, not just a serialization trick.

MTH should expose explicit operations for:

- reverse all eight bytes of a 64-bit word;
- swap the near and far faces;
- reverse the 32-bit payload bytes;
- reverse a 16-bit payload lane;
- convert a declared multiword scalar between little- and big-endian order;
- convert vector/matrix/tensor storage order without changing logical indices;
- inspect both orientations and report whether a format is invariant under reversal.

These must be separate, testable operations. A full-word reversal is not the same thing as reversing a payload lane or changing the logical order of a vector.

A reversal test must verify both the transformed bytes and the transformed semantic class. It must also test the reverse operation and confirm that applying it twice returns the original word.

---

## 3. MTH's essential mathematical scope

The scope is selected by usefulness to language learning and reasoning. Advanced mathematics belongs in later packages only when a concrete model task needs it.

### Tier 0 — bit logic and machine arithmetic

This is the foundation. Everything else depends on it.

Required:
- all 16 two-input Boolean functions;
- NOT, AND, OR, XOR, XNOR, NAND, NOR, implication, equivalence;
- bit masks, shifts, rotations, population count, leading/trailing zero count;
- equality and ordered comparisons;
- add, subtract, multiply, divide, remainder;
- signed and unsigned interpretations;
- carry, borrow, overflow, and divide-by-zero reporting;
- bounded-width arithmetic and explicit arbitrary-precision integer objects;
- byte/word extraction, packing, reversal, and double-endian transforms;
- min, max, clamp, absolute value, sign, select;
- reductions: sum, product, min, max, any, all.

No arithmetic operation may silently wrap unless the declared integer type says it wraps. Checked, saturating, wrapping, and unbounded arithmetic are distinct modes.

### Tier 1 — exact scalar mathematics

Required:
- integers and natural numbers;
- normalized rational numbers;
- exact comparisons and ordering;
- greatest common divisor and least common multiple;
- integer powers and roots where exact;
- quotient/remainder and Euclidean division;
- rational addition, subtraction, multiplication, division, reduction;
- exact finite-domain values and finite-field operations when the field parameters are valid.

A rational is a numerator/denominator pair with a normalized sign and gcd-reduced representation. Division by zero is an explicit domain failure. Modular arithmetic must distinguish a general residue ring from a field; a modulus is not assumed prime.

### Tier 2 — vectors and language-model arrays

This is the first major MTH workload after the scalar core.

Required:
- create, index, slice, concatenate, gather, scatter;
- elementwise add/subtract/multiply/divide;
- scalar broadcast and shape-checked broadcasting;
- dot product;
- sum/mean reductions;
- squared norm, Euclidean norm, normalization;
- cosine similarity;
- distance and similarity measures;
- argmin/argmax and stable top-k;
- masking and selection;
- permutation and gather/scatter transforms;
- prefix sums and cumulative products.

Vectors must have explicit shape, element type, and layout. A vector is not merely a pointer plus an assumed length.

### Tier 3 — matrices and tensor primitives

Required:
- matrix creation, indexing, transpose, reshape, slice, concatenate;
- matrix-vector and matrix-matrix multiplication;
- elementwise matrix operations;
- reductions along declared axes;
- diagonal extraction/construction;
- identity and zero matrices;
- row/column normalization;
- triangular operations;
- small-matrix determinant and inverse where defined;
- tensor indexing, reshape, transpose/permutation, broadcast, contraction, and reduction.

The first implementation should prioritize correct dense operations and small working sets. Sparse and tiled layouts follow when the model's real memory profile justifies them.

### Tier 4 — probability and numerical functions for generation

These functions are directly useful to language-model inference and learning:

- stable maximum and log-sum-exp;
- softmax and log-softmax;
- sigmoid;
- tanh;
- ReLU and common piecewise activations;
- exponential and logarithm;
- square root and reciprocal square root;
- normalization primitives;
- categorical normalization and sampling;
- entropy and cross-entropy;
- KL divergence where both distributions satisfy the required conditions;
- cumulative distribution and inverse-CDF sampling;
- deterministic pseudo-random generation with explicit seed/state.

Numerical functions must declare their accuracy class and domain. A fast approximation is not an exact function. It must return or make available an error bound, precision mode, or documented maximum error.

For softmax, use the stable form: subtract the maximum logit before exponentiation, accumulate with a declared precision, and normalize only after validating the denominator. Empty input, all-masked input, infinities, and NaNs require explicit policies.

### Tier 5 — learning and optimization primitives

Only the operations needed to train and improve the language model belong in the first learning tier:

- loss calculation;
- gradient accumulation;
- elementwise derivative functions;
- vector/matrix gradient operations;
- parameter update primitives;
- clipping and norm constraints;
- moving averages;
- momentum and Adam-style update arithmetic;
- finite-difference checks for test fixtures;
- deterministic reduction and accumulation modes.

MTH supplies the mathematics. The training system decides when and where to apply it. MTH must not own the model's canonical parameter store or invent a second learner.

### Tier 6 — symbolic and structural reasoning

Useful after the executable core:

- expression trees and directed acyclic graphs;
- substitution and simplification;
- equality/inequality predicates;
- relation composition;
- graph traversal and reachability;
- set membership and finite-set operations;
- Boolean satisfiability for bounded formulas;
- polynomial representation and basic operations;
- transformation composition;
- invariants and proof/evidence records.

Do not start with a large theorem prover. Start with a small exact kernel whose claims are independently checkable.

---

## 4. The model-facing operation set

MTH should be designed around actual language-model workloads, not a catalogue organized only by school mathematics.

### Token and sequence operations

- map token IDs to embedding rows;
- gather embedding vectors;
- position-index and positional transforms;
- sequence slicing, padding, masking, and packing;
- rolling/windowed reductions;
- causal and non-causal index masks;
- sequence comparison and edit-distance primitives where useful;
- n-gram and frequency-count operations for corpus statistics.

### Embedding and representation operations

- vector lookup and accumulation;
- dot product and cosine similarity;
- distance and nearest-neighbor scoring;
- normalization;
- projection and matrix multiplication;
- elementwise gating;
- vector addition and residual combination;
- low-rank and tiled matrix operations when implemented and verified.

### Attention operations

- query-key dot products;
- scaling by the declared head dimension;
- causal/padding masks;
- stable softmax;
- weighted value accumulation;
- head concatenation and projection;
- shape and mask validation.

An attention implementation is a composition of MTH operations, not a magical opaque opcode. Fused implementations may be added later, but they must be semantically equivalent to a reference composition within the declared numerical tolerance.

### Output and sampling operations

- logits scaling;
- temperature transform;
- repetition/frequency penalties only when explicitly requested by the model policy;
- top-k and top-p/nucleus selection;
- stable probability normalization;
- seeded categorical sampling;
- greedy argmax;
- deterministic tie-breaking.

Sampling must be reproducible from an explicit PRNG state. No hidden host randomness.

### Training and evaluation operations

- cross-entropy and negative log likelihood;
- batch/sequence reductions;
- gradient and optimizer arithmetic;
- accuracy and exact-match counters;
- perplexity from a well-defined mean negative log likelihood;
- calibration and entropy summaries;
- clipping and parameter norm checks.

MTH does not decide whether a candidate model is good. It computes the declared metrics and emits evidence for the evaluator.

---

## 5. Type system: make invalid mathematics difficult to express

Every MTH value has a declared type. At minimum, distinguish:

- Boolean and bit-vector;
- unsigned and signed fixed-width integer;
- arbitrary-precision integer;
- rational;
- finite-field element with its field parameters;
- fixed-point value with scale;
- approximate real with precision/error metadata;
- vector, matrix, tensor with element type and shape;
- probability/distribution;
- index, mask, permutation;
- expression, relation, graph;
- proof/evidence and execution result.

Types include dimensions and units where relevant. A 3-element vector cannot be multiplied by a 4-element vector through an operation that requires equal lengths. A matrix product must validate inner dimensions. A probability distribution must declare its support and normalization status.

### Exact, approximate, invalid, and undefined are different

Each operation must distinguish:
- exact result;
- approximate result with declared error information;
- valid result with a warning or exceptional value;
- invalid input/type/shape;
- undefined operation or domain failure;
- resource exhaustion or execution-budget stop.

Do not turn every failure into NaN. Do not silently coerce an exact rational into a floating approximation. Do not silently turn a signaling NaN into a quiet NaN and continue.

The four NaN face classes are part of the machine's encoding alphabet. They are not a replacement for the MTH semantic status model.

---

## 6. The MTH transformation contract

Every mathematical function is a NaN16 implementation and a registered transformation definition.

A transformation record should describe:

1. **Identity:** stable operation ID and version.
2. **Signature:** input and output types, shapes, dimensions, and layout constraints.
3. **Domain:** valid input domain and explicit preconditions.
4. **Semantics:** exact mathematical meaning, including overflow, rounding, NaN, infinity, and exceptional cases.
5. **Implementation:** one or more NaN16 program versions.
6. **Postconditions:** invariants that must hold after execution.
7. **Evidence:** tests, known-answer vectors, proofs, counterexamples, and independent checks.
8. **Cost:** measured latency, memory/scratch, operation count, and hardware provenance.
9. **Lineage:** source definition, derivation, prior implementation, and candidate status.

Separate the mathematical operation from its implementation. For example, matrix multiplication is one operation with multiple implementations: simple reference, blocked, sparse, low-memory, and hardware-tuned. All must implement the same declared semantics.

### Composition

MTH operations compose into typed graphs:

```
input objects
   -> validated operations
   -> intermediate typed objects
   -> further operations
   -> result + derivation/evidence
```

The graph supports:
- shared subexpressions;
- dependency ordering;
- safe parallel branches;
- reusable intermediate results;
- incremental recomputation;
- resource accounting;
- proof/evidence propagation.

A fused implementation may replace a graph segment only after its output behavior is checked against the reference composition at the appropriate evidence level.

---

## 7. How MTH should use the NaN encoding space

The encoding should serve the model and the execution substrate, not become a puzzle that makes ordinary math harder.

### 7.1 Three independent questions

For every word, keep these questions separate:

1. **What are the raw bits?** The exact 64-bit pattern and both face classes.
2. **What record is this part of?** Instruction stream, scalar block, vector, tensor, index stream, or evidence record.
3. **What does the record mean?** The declared type and operation semantics.

This separation prevents the class nibble from being overloaded as a universal type tag, opcode, error state, and numerical value all at once.

### 7.2 Ordered face pairs are resources

The near and far classes can support:
- distinct instruction predicate patterns under the frozen ISA;
- ordered data subformats;
- explicit orientation and byte-order markers;
- typed control/data distinctions where the record contract defines them;
- compact validity and variant checks;
- independent cross-check channels;
- forward/reversed representation pairs.

The mapping must be versioned and documented. Do not assume all 16 class combinations are equally appropriate for every record family. Some are instruction semantics; some may be useful data variants; some may be reserved by a particular format. Reserve explicitly rather than leaving accidental ambiguity.

### 7.3 Payload is a 32-bit field, not a universal scalar

The payload may represent:
- a 32-bit immediate or operand;
- an index, offset, or compact identifier;
- a packed pair of 16-bit lanes;
- a fixed-point fragment;
- a bit-vector fragment;
- a compact tag/value field;
- part of a larger multiword scalar or tensor element.

Large integers, rationals, and high-precision values use multiword objects. A 32-bit payload must never be mistaken for a universal numeric precision limit.

### 7.4 Do not spend the encoding space prematurely

Before assigning a new class/payload pattern:
- list all existing NaN16 uses;
- identify whether the word is code or data;
- check both-end legality;
- test all 16 ordered class combinations;
- test full-word reversal;
- test double reversal;
- test serialization round trips;
- test old NaN16 images and existing guests;
- record reserved values and format version.

The frozen NaN16 ISA remains backward-compatible. MTH data formats can evolve without silently changing the meaning of existing instructions.

---

## 8. Runtime and ownership boundaries

MTH is a native NaN16 library and transformation catalogue inside the canonical NaNLMind universe.

- **NaN16:** language and implementation format for every MTH mathematical function.
- **MTH:** type contracts, mathematical definitions, NaN16 implementations, composition, and mathematical evidence.
- **NaNLMind:** learning, model state, and discovery that consumes MTH capabilities.
- **NaNROUTER / NaNLMROUTER:** authorized task and result routing; no duplicate math authority or private runner dispatch.
- **HW0::BS0:** canonical execution topology and ownership boundary.
- **R0–R5:** internal execution capacity under the existing topology, not six independent math systems.
- **Hermes:** a client for requesting, inspecting, and orchestrating approved MTH operations; not the owner of the operator registry, evaluator, or mathematical state.

MTH must not create its own runner ring, lease ledger, endpoint registry, or model parameter store. A mathematical task is routed through the existing authorized task path with owner, participant, lease/epoch, replay, and result checks intact.

### Bounded execution

Every execution request declares:
- operation and version;
- typed inputs;
- resource/fuel budget;
- scratch requirements or limits;
- determinism/precision mode;
- expected result contract.

A bounded run may stop because it exhausted its budget. That is not a mathematical proof of nontermination. A completed result must be validated before it is accepted. A candidate implementation cannot certify itself.

---

## 9. Numerical policy

Language models need both exact operations and fast approximate operations. MTH must make the distinction explicit.

### Exact lane
Use for integer logic, indices, dimensions, rational fixtures, finite Boolean functions, and exact algebraic identities where representable.

### Fixed-point lane
Use where bounded precision and predictable cost are useful. Every fixed-point type declares scale, rounding, saturation/wrap policy, and overflow behavior.

### Approximate lane
Use for model-facing transcendental functions and tensor arithmetic when needed. Every implementation declares:
- input domain;
- output range;
- precision;
- rounding mode;
- error bound or measured error envelope;
- exceptional-value policy;
- deterministic behavior.

### Stable numerical algorithms first

Prioritize algorithms that avoid avoidable overflow/underflow:
- max-subtracted softmax/log-sum-exp;
- pairwise or compensated reductions where cost-effective;
- explicit accumulation precision;
- safe normalization with zero-norm handling;
- stable variance/mean updates;
- clamped or domain-checked logarithms.

Do not optimize a numerically unstable reference into a faster unstable implementation and call it progress.

---

## 10. Evidence and promotion

Evidence levels must never be conflated:

1. **Defined:** signature and semantics have been written.
2. **Assembled:** NaN16 source assembles.
3. **Executed:** a known fixture ran.
4. **Regression-tested:** a meaningful test suite passed.
5. **Differentially checked:** an independent implementation or interpreter agrees.
6. **Property-tested:** invariants hold over a declared input space or sample.
7. **Proved:** a proof object/checker establishes the stated theorem under explicit assumptions.
8. **Promoted:** policy accepts the implementation for normal use.

A passing test suite is not a proof of universal correctness. A bounded search that found no counterexample is not a proof of equivalence.

### Required evidence per operation

- boundary values;
- invalid types and shapes;
- zero and one cases where meaningful;
- overflow/underflow cases;
- NaN/signaling/quiet and both-face cases where relevant;
- reversed-word and round-trip cases for endian operations;
- deterministic repeatability;
- resource-exhaustion behavior;
- known-answer vectors;
- comparison against an independent reference where feasible.

Candidate discovery may propose an implementation, derive an optimization, or find a new identity. It cannot write directly into the trusted implementation catalogue. It must pass the same checks as any other candidate.

---

## 11. Minimal architecture

Keep the implementation small and layered.

| Layer | Responsibility | Must be NaN16? |
|---|---|---|
| L0 | Existing NaN16 execution and legal-word gate | Yes, guest semantics |
| L1 | MTH word/object descriptors and memory access | Yes |
| L2 | Scalar types, exact arithmetic, status handling | Yes |
| L3 | Vector and matrix primitives | Yes |
| L4 | Numerical/probability functions for language models | Yes |
| L5 | Composition, cost, and optimization selection | Yes |
| L6 | Evidence, equivalence fixtures, and candidate validation | Yes |
| L7 | Discovery and extension proposals | Yes |

The only permitted non-NaN boundary is the already-existing minimal machine/transport/build substrate required to execute the NaN16 guest. It must not contain mathematical semantics. A host-side test driver may launch a guest or compare bytes, but the actual operation under test is implemented in NaN16.

No Python, C, C++, JavaScript, Kotlin, or other host-language math implementation may be substituted for an MTH operation.

---

## 12. Build order: the actual game plan

### Stage 0 — freeze the contract

- Import the current NaN16 word/ISA specification as the baseline.
- Record the four face classes and all 16 ordered class nibbles.
- Add a complete ordered-pair table, including the reversal mapping.
- Document instruction-word versus data-word interpretation.
- Define MTH object descriptors and versioning without changing the existing ISA.
- Add a raw-word inspection and round-trip fixture in NaN16.

**Gate:** every legal class pair is accepted; every illegal face is rejected; no pair is silently canonicalized; double reversal restores the exact original word.

### Stage 1 — Boolean and integer kernel

- all 16 two-input Boolean functions;
- masks, shifts, rotations, comparisons;
- add/subtract/multiply/divide/remainder;
- signed and unsigned behavior;
- overflow/carry/borrow reporting;
- checked, saturating, and wrapping modes;
- multiword integer arithmetic.

**Gate:** exhaustive truth-table checks; small-width exhaustive arithmetic; boundary and divide-by-zero tests; native/interpreter agreement.

### Stage 2 — exact scalar and data structures

- normalized rationals;
- gcd/lcm and Euclidean algorithms;
- fixed-point representation;
- typed scalar and array descriptors;
- indexing, slicing, shape checks, reductions;
- explicit endian conversion for multiword values.

**Gate:** exact rational fixtures, normalization invariants, shape-failure tests, and serialization round trips.

### Stage 3 — vector and matrix kernel

- vector operations and reductions;
- dot products and norms;
- matrix transpose and multiplication;
- broadcasting and masking;
- stable top-k;
- reference implementations before optimized variants.

**Gate:** known-answer fixtures, dimension validation, independent small-matrix comparisons, and deterministic output.

### Stage 4 — model numerics

- stable softmax/log-softmax;
- exp/log/sqrt approximation contracts;
- normalization;
- entropy and cross-entropy;
- seeded sampling;
- loss and gradient primitives.

**Gate:** numerical error envelopes, extreme-logit fixtures, masked/empty cases, deterministic seeded sampling, and gradient checks.

### Stage 5 — language-model compositions

- embedding gather;
- positional transforms;
- attention composition;
- output projection;
- logits and sampling;
- batch/sequence losses;
- optimizer arithmetic.

**Gate:** small deterministic end-to-end fixtures with every intermediate shape, operation version, and numerical mode recorded.

### Stage 6 — optimization and discovery

- cost vectors and measured profiles;
- operation fusion with reference equivalence checks;
- tiled/sparse implementations where justified;
- candidate synthesis and counterexample search;
- proof/evidence propagation;
- promotion lifecycle.

**Gate:** no optimized implementation is selected unless it satisfies the semantic contract and has evidence at the required level.

---

## 13. First vertical slice: prove the design before expanding it

Do not begin by coding dozens of unrelated mathematical domains. Build one complete, useful vertical slice:

1. Inspect and decode every one of the 16 ordered NaN face combinations.
2. Execute the existing 16 Boolean functions without changing their semantics.
3. Implement explicit full-word double-endian reversal and its inverse.
4. Implement checked 32-bit integer add/subtract and bitwise operations.
5. Add multiword integer add/subtract.
6. Define typed vector descriptors and implement vector add, dot product, and norm.
7. Implement stable max-subtracted softmax over a small vector.
8. Compose dot-product → scale → mask → softmax → weighted-sum as a tiny attention fixture.
9. Emit a deterministic trace of inputs, operation versions, outputs, and evidence status.

This vertical slice is small enough to debug and large enough to prove that MTH can support a real language-model computation.

---

## 14. What MTH deliberately does not do first

To keep the system useful rather than sprawling, defer:

- full symbolic algebra;
- general theorem proving;
- arbitrary calculus and differential geometry;
- broad statistics packages;
- physics and engineering formula catalogues;
- general-purpose optimization solvers;
- quantum mathematics;
- automatic invention of unbounded new primitive opcodes;
- architecture-specific fused kernels before reference semantics exist.

These are not forbidden forever. They are simply not prerequisites for a useful language-model mathematical core.

---

## 15. Non-negotiable invariants

1. Every mathematical function is implemented in NaN16.
2. The existing NaN16 word and instruction semantics are not silently changed.
3. All 16 ordered face-class combinations remain distinct and inspectable.
4. Byte reversal is an explicit transformation, never an equivalence shortcut.
5. Instruction words and data words have explicit interpretation contexts.
6. Exact and approximate results are never silently mixed.
7. Shapes, dimensions, units, and domains are checked.
8. Undefined operations and invalid inputs produce explicit outcomes.
9. Every implementation has a version and evidence record.
10. Optimizations must preserve declared semantics.
11. Candidates cannot self-promote.
12. MTH does not create a second owner, universe, runner ring, or task ledger.
13. Host code may provide the minimal execution/build boundary, but may not implement MTH mathematics.
14. A documented plan is not an implementation; a passing fixture is not a universal proof.

---

## 16. Immediate next actions

1. Add this plan to the NaNROUTER documentation.
2. Cross-check the MTH Stage 0 encoding table against the frozen NaN16 specification and the actual NaN16 interpreter.
3. Create the NaN16 MTH source directory and a minimal manifest only after confirming the repository's canonical source/build conventions.
4. Implement the Stage 0 word inspection and double-endian tests in NaN16.
5. Implement the Boolean/integer kernel next.
6. Do not add a large operator catalogue until the first vertical slice runs and is independently checked.

**MTH is successful when NaNLMind can ask for a mathematical transformation, execute it in NaN16, inspect exactly what happened, and rely on the result at a clearly stated evidence level.**
