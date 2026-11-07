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

The existing Boolean exhibit establishes the class-nibble face-swap relation:

```
rot2(n) = ((n & 3) << 2) | (n >> 2)
```

This is a two-bit-half swap on the four-bit class nibble. It is a verified relation for the Boolean class-nibble behavior demonstrated by the NaN16 exhibit. Do not generalize it into an unqualified claim that every MTH data word is transformed by the same byte permutation: the exact full-word `BSWAPM` mapping must be taken from the canonical instruction implementation and tested separately.

The complete abstract class-nibble mapping is:

| n | rot2(n) | n | rot2(n) |
|---:|---:|---:|---:|
| 0 | 0 | 8 | 2 |
| 1 | 4 | 9 | 6 |
| 2 | 8 | 10 | 10 |
| 3 | 12 | 11 | 14 |
| 4 | 1 | 12 | 3 |
| 5 | 5 | 13 | 7 |
| 6 | 9 | 14 | 11 |
| 7 | 13 | 15 | 15 |

The fixed points are 0, 5, 10, and 15. The remaining twelve values form six two-element pairs. All 16 remain distinct encodings; the six pairs describe a transformation relationship, not duplicate values.

**MTH rule:** an encoding and its transformed encoding are distinct words with a known transformation between them. A caller may explicitly request reversal, compare the two, or prove a relation between them. No storage layer or optimizer may silently identify them.

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

### 2.5 Keep the three endian-related mechanisms separate

There are three related but distinct operations in the existing NaN16 work. MTH must not collapse them into one ambiguous "byte swap":

1. **BSWAPM full-word reversal.** The frozen NaN16 primitive reverses all eight bytes of a 64-bit word: it swaps the two NaN faces and reverses the byte order of the 32-bit payload. Its class-nibble transform is `rot2(n) = ((n & 3) << 2) | (n >> 2)`. Applying it twice restores the original word.
2. **Double-endian pair codec.** The existing `n16de` codec stores a chunk as a big-endian member and a byte-swapped little-endian member, each with its own tag. Decode validates both members and rejects disagreement. This redundant paired representation with voting/validation is not the same operation as BSWAPM.
3. **Other lane and object transforms.** Reversing a 32-bit payload independently, reversing a 16-bit lane, and changing multiword scalar/vector/tensor storage order are separate operations with their own contracts.

MTH must expose explicit operation IDs for each. The initial implementation wraps the existing BSWAPM and pair codec without changing their semantics. Tests must verify all eight output bytes, both face classes, payload order, inverse behavior, and pair-codec corruption rejection.

Every transform test must check exact input/output words, face classes, payload bytes, inverse behavior, and corruption handling where the format includes redundancy. Applying an involutive transform twice must restore the original bytes; a pair codec must also reject a mismatched pair rather than silently choose one member.

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
- the existing instruction predicate / Boolean truth-table patterns under the frozen ISA;
- ordered face-pair identity and face-swap relationships;
- explicitly declared data variants;
- orientation markers where a data format defines them;
- compact validity and variant checks;
- forward/reversed representation pairs.

Do not infer that the class nibble is a general-purpose opcode or a free-form data tag. Preserve the frozen instruction meaning first; assign data meanings only inside a versioned data format.

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

The first NaN16 source slice is now committed under `mth/`. The next work is implementation validation, not another architecture expansion:

1. Assemble every `mth/nan16/*.nas` module and its corresponding `mth/tests/*.nas` fixture with the canonical NaN16 assembler.
2. Run the fixtures in the canonical interpreter and native guest; record exact output, toolchain revision, and source digests.
3. Fix assembler/runtime discrepancies before adding more operators.
4. Convert the pair codec's static return-address slots to a caller-owned frame so it is safe for concurrent use.
5. Add signed integer operations and exact multiword integer add/subtract/multiply/divide.
6. Add typed vector descriptors and the first vector operations; then implement model-facing fixed-point/float operations only against the frozen float opcode semantics.
7. Compose dot-product → scale → mask → stable softmax → weighted-sum as the first attention fixture.
8. Integrate MTH requests through the existing authorized NaNROUTER task/result path without creating a second registry, runner ring, or task ledger.

Do not expand the catalogue while the current source cannot assemble and run. The first priority is a clean, reproducible NaN16 vertical slice.

**MTH is successful when NaNLMind can ask for a mathematical transformation, execute it in NaN16, inspect exactly what happened, and rely on the result at a clearly stated evidence level.**


---

## 17. Stage 0 implementation snapshot

The first native source slice now lives under `mth/`:

- `mth/nan16/mth_core.nas` contains NaN16 functions for ordered class rotation, near/far face extraction and packing, sign/quiet-bit extraction for all four face types, and the eight-byte `BSWAPM` wrapper.
- `mth/nan16/mth_bool.nas` contains a generic two-input Boolean transform that dynamically selects one of the frozen `BOOL.n` instruction classes and executes it as NaN16.
- `mth/nan16/mth_double_endian.nas` adapts the canonical NaN0S pair-voting codec into MTH names; it validates both tags, both class nibbles, and byte-swapped agreement.
- `mth/nan16/mth_integer.nas` implements checked unsigned 32-bit addition and subtraction with explicit overflow/underflow status.
- `mth/nan16/mth_bitwise.nas` implements native bitwise transforms, unsigned min/max, and comparison predicates.
- `mth/nan16/mth_shift.nas` implements checked variable-count logical left/right shifts using NaN16 instructions.
- `mth/nan16/mth_multiply.nas` implements full-width unsigned 32×32→64 multiplication using a NaN16 shift-and-add algorithm.
- `mth/nan16/mth_divide.nas` implements unsigned 32-bit divmod with a restoring-division loop and explicit divide-by-zero status.
- `mth/tests/mth_double_endian_test.nas` checks pair round-trip and deliberate corruption rejection.
- `mth/tests/mth_integer_test.nas` checks exact add/subtract cases and boundary overflow/underflow.
- `mth/tests/mth_bitwise_test.nas` checks Boolean bitwise functions and unsigned comparison/min/max results.
- `mth/tests/mth_shift_test.nas` checks shift counts 0–31, high-bit logical shifting, and invalid-count rejection.
- `mth/tests/mth_multiply_test.nas` checks small and full-width multiplication boundary vectors.
- `mth/tests/mth_divide_test.nas` checks quotient/remainder and divide-by-zero behavior.
- `mth/tests/mth_stage0_test.nas` checks all 16 ordered face pairs, four face-type sign/quiet mappings, class packing round trips, invalid class rejection, rotation involution, exact BSWAPM payload-byte reversal, and double-reversal restoration.
- `mth/tests/mth_bool2_test.nas` checks all 16 two-input Boolean truth-table classes against a fixed expected lane pattern.
- `mth/README.md` records the boundary between BSWAPM and the existing double-endian pair codec.

This is source committed to the repository, not a claim that it has assembled or passed in the canonical runtime. The test remains **unverified** until run with the current NaN16 assembler/interpreter. The original pair codec used shared static return-address slots. The current source has replaced those with caller-owned frames in r12; the updated ABI is still unverified until the canonical NaN16 toolchain executes it. The smoke test remains unverified until assembled and run.

### Stage 0 next gate

1. Assemble `mth/nan16/mth_core.nas` and `mth/tests/mth_stage0_test.nas` with the canonical NaN16 toolchain.
2. Run the smoke test and capture the guest output.
3. Add exhaustive checks for all 16 ordered face pairs, including every face class in both positions.
4. Run the pair-codec fixture, then add missing-member, wrong-class, wrong-tag, swapped-member, and resynchronization tests.
5. Add raw-word fixtures that verify payload bytes independently from face classes.
6. Record exact toolchain version, source digest, test digest, and result before marking Stage 0 passed.

The MTH source must remain NaN16. A host test runner may assemble, launch, and collect bytes, but may not calculate the expected mathematical result on behalf of the guest.


## 18. Use the 16 class nibbles as a data-space resource

The 16 class nibbles are not merely four neutral patterns plus twelve disposable mirror patterns. They are 16 ordered values. Under `rot2`, four are fixed (`0, 5, 10, 15`) and the remaining twelve form six reversible pairs:

| Pair | Reversal | Potential use (schema-defined, not hardwired) |
|---|---|---|
| 1 ↔ 4 | `rot2` | directed role pair |
| 2 ↔ 8 | `rot2` | forward/reverse transform family |
| 3 ↔ 12 | `rot2` | source/destination or input/output orientation |
| 6 ↔ 9 | `rot2` | ordered comparison / inverse relation |
| 7 ↔ 13 | `rot2` | paired record orientation |
| 11 ↔ 14 | `rot2` | implication / reversed implication family |

The four fixed values can be useful for orientation-invariant record tags, but they are not reserved exclusively for that purpose. Every one of the sixteen values remains available to a versioned MTH data schema. The table above suggests semantic families; it does not permanently assign meanings to class IDs.

A data stream declares its record family. In that context, the class nibble can select one of sixteen data variants while the 32-bit payload carries the compact value. The same raw word in an instruction stream retains the frozen NaN16 instruction meaning. Context is mandatory; code/data reinterpretation is never implicit.

For larger structures, each 64-bit word is one element or fragment in a typed multiword object. The object descriptor carries the full type, length, shape, stride/layout, version, and endianness policy. This lets MTH use the entire class/payload space without pretending that one 32-bit payload can hold every scalar or tensor value.

The key property is **orientation-preserving addressability**: a word and its BSWAPM image remain distinct, inspectable representations linked by a known involution. MTH may exploit that relation for paired fields, integrity checks, and transformations, but must not collapse the two encodings or assume that only palindromic words are useful.


---

## 19. Reentrant pair codec and first vector arithmetic slice

**Source status:** implemented in NaN16 source on branch `mth-reentrant-vector-kernel`.  
**Execution status:** unverified; the canonical assembler/interpreter has not yet run these fixtures.

### 19.1 Caller-owned frame replaces static codec state

The double-endian codec no longer stores return addresses, chunks, or destination pointers in shared labels.

- `mth_de_encode` now receives a caller-owned three-word frame in `r12`: saved return address, chunk, destination address.
- `mth_de_decode` receives a caller-owned one-word frame in `r12`: saved return address.
- The BSWAP16 helper remains leaf-only and uses no static storage.
- Two callers can use distinct frames without overwriting one another's saved state.
- The caller must not share one frame between overlapping invocations.

The fixture now uses two distinct frames and two output destinations, verifies both round trips, corrupts one member and verifies rejection, and checks wrong-class rejection.

**Gate:** assemble and execute the updated codec fixture; add wrong-tag, missing-member, wrong-second-class, and resynchronization cases before claiming full pair-codec validation.

### 19.2 First model-facing vector primitive

`mth/nan16/mth_vector.nas` adds `mth_u32_span_add_checked`, a contiguous unsigned-32 vector addition kernel.

ABI:
- `r1`: first input word address
- `r2`: second input word address
- `r3`: output word address
- `r4`: element count
- `r12`: caller-owned three-word scratch frame
- return `r1=1` on success, `r1=0` on unsigned overflow

The implementation performs a complete validation pass before writing any output. Overflow therefore leaves the output span unchanged. Zero-length spans succeed without memory access. The caller is responsible for valid spans and non-overlap between output and inputs.

This is deliberately a low-level contiguous U32 span primitive, **not yet the typed vector descriptor layer**. Shape/stride/type descriptors, alias analysis, dot product, norms, cosine similarity, and stable top-k remain future work. Do not claim those are implemented.

The NaN16 fixture covers:
- successful elementwise results;
- overflow rejection;
- output unchanged after overflow;
- zero-length success.

### 19.3 Evidence grade

Both new fixtures are source-level checks only. Until assembled and executed, their status is **DEFINED / SOURCE-WRITTEN**, not ASSEMBLED, EXECUTED, REGRESSION-TESTED, or PROMOTED. No source comment or game-plan status may imply otherwise.

### 19.4 Next implementation order

1. Run the full MTH source/test set with the canonical NaN16 assembler and interpreter; fix syntax/ABI discrepancies before expanding the kernel.
2. Add pair-codec wrong-tag, missing-member, wrong-second-class, and resynchronization tests.
3. Add typed vector descriptors with explicit element type, length, stride, and layout validation.
4. Add vector copy/fill, elementwise checked add/subtract, dot product with a two-word accumulator, squared norm, and normalization status.
5. Add exact rational primitives only after the integer kernel has differential fixtures.
6. Build attention from explicit dot-product, scale, mask, stable-softmax, and weighted-sum operations; do not add an opaque attention opcode.


---

## 20. Relational-spectral foundation for every 8 MiB universe-bin

**Architecture decision:** MTH is the native mathematical substrate for the shared Relational-Spectral Subsystem (RSS). The full mathematical and system contract is in [GRAPH_SPECTRAL_MTH_PLAN.md](GRAPH_SPECTRAL_MTH_PLAN.md), with the shared system-level specification in NaNLMind's docs/GRAPH_SPECTRAL_FOUNDATION.md.

### 20.1 Mathematical foundation

The 256 Heads and 32,640 unordered pair cells define the exact topology. The directed relation matrix W remains lossless and asymmetric when needed. A separately derived symmetric nonnegative coupling A defines D and L=D-A. For K256, L=256I-J, with spectrum 0 once and 256 with multiplicity 255.

Head-state wave dynamics use ü+c²Lu=0. Optional potential/source dynamics use ü+[c²L+V]u=f. Pair-indexed fields use L_pair=L⊗I+I⊗L and must be applied matrix-free as LU+ULᵀ. A 256×256 operator has 256 eigenvalues; the 65,536 pair-space state is a different operator and must not be conflated with it.

The void potential V_i=α/(r_i+ε)² is optional. Radius is a versioned graph-distance, embedding, or topology-shell coordinate. A central barrier, boundary ring, 256 antinodes, and tunneling-like transfer are hypotheses to measure, not guaranteed outcomes.

### 20.2 Structural invariants

- Keep directed W rails independent.
- Derive A/L as an explicit view; never overwrite W with its symmetric part.
- Address reversal is matrix transpose, not centrosymmetry.
- FOLD's 128+128 block reduction is allowed only after verifying J W J=W and the relevant symmetric/Hermitian condition.
- Never materialize a 65,536×65,536 dense operator.
- Every numeric kernel must declare signedness, Q format, intermediate width, overflow/saturation behavior, scratch budget, and caller-owned frame ABI.
- All mathematical kernels remain native NaN16 .nas; host languages may only orchestrate/transport/validate envelopes.

### 20.3 RSS operations and execution

The shared operations are ENCODE, QUERY, MATCH, FILTER, DRIVE, and FOLD. The kernel roadmap includes sparse degree, Laplacian apply, pair-space apply, energy, inverse-square potential, polynomial filters, deterministic Lanczos, wave stepping, verified symmetry transforms, and pattern-analysis primitives.

NaNNet runners advertise per-kernel capability and workspace. Only a capability marked native-verified after canonical assembler/interpreter execution is dispatchable. NaNLMind validates operator/topology/output digests and retains its existing single semantic ledger. Pattern analysis is a shared RSS consumer; a dedicated MC0 application is deferred.

### 20.4 Immediate gate

The canonical NaN16 assembler/interpreter is now located and exercised by CI. The first exact K256 U16-input matrix-free Laplacian kernel is native_verified; it checks all 256 inputs before writing and passes the impulse response plus invalid-input atomicity fixture. This baseline deliberately does not define the signed fixed-point ABI for waves.

Next: freeze a versioned signed fixed-point ABI (word width, Q format, rounding, overflow/saturation, scratch frame and workspace), then implement a sparse weighted-graph degree/Lx kernel against path-graph and disconnected-graph exact oracles. Only after those pass should the void potential, eigensolver/filter and wave stepper proceed. Keep the runner capability non-dispatchable until the kernel digest and workspace are registered in its manifest.

**Evidence:** K256 native kernel and fixture passed canonical NaN16 CI (workflow run #17); higher-level sparse, void, spectral and wave kernels remain unimplemented.
