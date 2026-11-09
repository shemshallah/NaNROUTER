# Native bounded candidate path witness (NaN16)

The source `mth/nan16/mth_graph_path_witness.nas` extends the merged
single-edge NaN16 claim probe with **guest-side checking of a complete,
directed 1–8-hop candidate witness**. The witness is derived independently
by HERMES' read-only multihop graph navigation, but the guest checks the
precise ordered relationship sequence against its own input words.

## Guest ABI

- `r1`: at most 1024 current active candidate `[src,dst,layer,code]` U32
  records with canonical cell IDs 0–32895, L0–L9, code 1 supports / 2 refutes
- `r2`: record count 0–1024
- `r3`: a proposed path as 3-word hops `[src,dst,layer]`
- `r4`: hop count 1–8
- `r5`: caller-owned non-overlapping 8-word output buffer
- return `r1=1` only for a valid, fully covered directed path; otherwise 0

Every record and every hop is validated first, including unrelated records.
The guest then checks all hops exist without writing the output, and only
after complete success recomputes the relation masks into output words.
Each mask is **1 supports, 2 refutes, or 3 contested**. Reject paths (invalid
indices, broken chaining, absent hop, too many records or hops) leave the
output untouched. The source is pure NaN16 code; no host/Python traversal
opcode is provided.

The result establishes **candidate graph connectivity only**. Even a path of
`supports` or `isa` statements is not an entailment or mathematical proof.
No native model update, NANNET authorization, MathLeaf truth validation,
pinned Ed25519 check, durable nonce, or NMP receipt is implied. A future
trusted dispatcher must verify all those external preconditions and bind
input, witness, result, native guest image, chart generation, and rule epoch
before learning admission.

CI assembles and executes `mth/tests/mth_graph_path_witness_test.nas` using
a pinned canonical NaN0S toolchain. Tests check a 3-hop path with one
contested hop, then reject broken chaining, absent hops, irrelevant malformed
records, malformed nodes/layers and cap overflows with **atomic output**.
