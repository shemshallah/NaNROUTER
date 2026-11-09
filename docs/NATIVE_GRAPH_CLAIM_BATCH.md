# NaN16 native bounded graph claim batch (non-authorizing)

The actual guest `mth/nan16/mth_graph_claim_batch.nas` evaluates up to **16
independent directed L0–L9 queries** over one verified snapshot of at most
**1024 active candidate records**, covering 32,896 canonical head and
mirror-pair cells. It executes all relation operations as NaN16 instructions;
the host only stages words and validates outer authentication and evidence.

Input records are `[src,dst,layer,relation]`, with relation code 1 supporting
or 2 refuting. Input queries are `[src,dst,layer]`; output is one U32 per
query: 0 absent, 1 supports, 2 refutes, 3 both. Multiple opposing records
are kept, never silently collapsed. Distinct layers and reverse directions
remain distinct, and absence is **not** treated as refutation.

ABI with r0=0 and r13=1: r1 pointer to up to 1024 four-word records; r2
record count 0..1024; r3 pointer to three-word query tuples; r4 query count
1..16; r5 output pointer to q result words, nonaliasing with inputs.
Returns r1=1 on success or 0 if invalid. Clobbers r1, r6-r12, r14 and
flags, preserves r2-r5, r13, r15. Caller guarantees valid memory spans,
non-overlap and immutable inputs for the duration of execution.

**Fail-closed atomicity:** every record and every query is validated before
the first write, including irrelevant records and the last query. Invalid
counts, canonical IDs, L10, and illegal relation codes fail without changing
any output. A valid snapshot with zero records returns zero for every query.

This primitive does not verify Ed25519, historical graph replay, MathLeaf
references, guest-image measurement, leases, replay nonces, or training
admission; those are separate HERMES obligations. It also does not infer
transitivity, deductive truth, a mathematical theorem, or evidence promotion.
It is listed as a separately CI-gated **non-authorizing native guest** in
`spec/nan-native-boundary.json`, not registered as a promoted mathematical
MTH capability.

Dedicated CI assembles and runs the actual NaN16 image with pinned NaN0S,
asserts all four masks in one call, verifies that malformed last queries,
unrelated invalid records and oversized counts leave outputs unchanged, and
checks the zero-record absent case. No Python relation implementation is
substituted for the guest kernel.
