# MTH typed mathematical preflight ABI v1

Status: native-verified by canonical CI run 42405649076 (typed preflight, operand-alias regressions, and linker-to-preflight fixtures; 132 steps).

## Ownership

The operator/function registry remains the single authority for operator identity, signatures, semantics, and contract versions. NaN0S `math_registry.nas` stores the immutable 10-word applicability contract under the existing operator ID; `nmr_resolve` returns its descriptor pointer in r6. The MTH preflight guest consumes that exact pointer and two concrete leaf descriptors. It does not register, discover, or redefine functions.

This keeps three responsibilities separate:

- NaNLMind/MC0 registry: mathematical identity and the versioned contract.
- NaNROUTER MTH preflight: applicability of that contract to the actual input leaves and runner capabilities.
- NaN16 kernel: numerical or symbolic execution after successful preflight.

## Descriptor layout

All fields are 64-bit NaN16 words carrying bounded integer values or word addresses.

Object descriptor, 8 words:

| Offset | Field |
|---:|---|
| 0 | object kind |
| 1 | rank (0–2 in v1) |
| 2 | dimension 0 |
| 3 | dimension 1 |
| 4 | scalar domain ID |
| 5 | payload word address |
| 6 | payload capacity in words |
| 7 | flags (bit 0 = finite values) |

Operator contract, 10 words:

| Offset | Field |
|---:|---|
| 0–2 | left kind, right kind, output kind |
| 3–5 | left rank, right rank, output rank |
| 6 | scalar domain ID |
| 7 | shape rule |
| 8 | required capability bitset |
| 9 | precondition bitset |

The output descriptor has the object layout. Its payload address and capacity must be reserved before preflight. On success the gate writes output kind, rank, dimensions, domain, and flags; it preserves the reserved payload pointer/capacity. On every rejection the complete output descriptor remains unchanged.

## Shape rules

| ID | Inputs | Output |
|---:|---|---|
| 0 | Equal rank and dimensions | Same shape |
| 1 | Vector × vector, equal dimensions | Scalar |
| 2 | Matrix × vector, left columns = vector length | Vector of left rows |
| 3 | Matrix × matrix, left columns = right rows | Matrix of left rows × right columns |
| 4 | Scalar × scalar | Scalar |

V1 supports ranks 0, 1, and 2. Higher ranks require a separately versioned descriptor and shape-rule extension; they are not silently flattened.

## Preconditions

| Bit | Meaning |
|---:|---|
| 0 | Right operand's first payload word is nonzero (for contracts such as division) |
| 1 | Output payload does not alias either input payload |
| 2 | Both inputs assert the finite-values flag |
| 3 | Non-scalar input dimensions are nonzero |

These bits are executable predicates, not advisory labels. A contract may set only predicates that have defined semantics for its operation.

## ABI and status

`mth_preflight`:

- r1 = left descriptor address
- r2 = right descriptor address
- r3 = resolved operator contract address
- r4 = available capability bitset
- r5 = reserved output descriptor address
- r12 = caller-owned 39-word scratch frame
- r13 = constant one

Returns r1 = 0 on success, otherwise:

| Code | Meaning |
|---:|---|
| 1 | Missing descriptor or scratch pointer |
| 2 | Missing payload |
| 3 | Kind mismatch |
| 4 | Rank mismatch or unsupported rank |
| 5 | Domain mismatch |
| 6 | Shape mismatch |
| 7 | Required execution capability unavailable |
| 8 | Declared precondition failed |
| 9 | Payload capacity insufficient |

A capability rejection is not a mathematical null. A failed precondition is not necessarily mathematical undefinedness: the contract determines whether it means undefined input or an inapplicable execution context. Numerical execution errors are reported by the selected kernel, not this gate.

## Evidence boundary

The fixture checks representative success and rejection paths, including output-descriptor atomicity. It is not a theorem prover, a general tensor-shape engine, or a proof of all operator contracts. The canonical NaN16 workflow must assemble and execute the fixture before the source is marked native-verified.


## Linker integration

`mth/tests/mth_linker_preflight_test.nas` exercises the canonical route-expression parser with an actual `nan://...::op:77::nan://...` expression. The parser resolves both leaf IDs, the operator ID, the output/program mapping, and the exact contract pointer returned by NaN0S `nmr_expr_resolve` (r10). That pointer is passed unchanged to `mth_preflight`; the router fixture does not reconstruct a contract record. The native MTH workflow assembles and executes this integration fixture separately from the preflight-only regression.


## Payload range safety

When precondition bit 1 is set, output and input payloads are compared as half-open word ranges using descriptor capacities. Partial overlap is rejected even when base pointers differ. Address-plus-capacity wrap is rejected as a malformed descriptor before output metadata is committed. The regression deliberately places a full-capacity output range one word inside the left input range, ensuring the test reaches the alias predicate rather than failing earlier on output capacity.
