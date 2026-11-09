# Native candidate relationship probe (NaN16)

`mth/nan16/mth_graph_claim_probe.nas` is a **guest-implemented**, read-only L0–L9 contradiction-preserving lookup. It accepts at most 1,024 active candidate relations in a flat array of four NaN16 U32 payloads per record:

```
[src_canonical_cell, dst_canonical_cell, layer, relation_code]
```

- Canonical cell IDs: 0–255 are heads; 256–32,895 are mirror-pair cells. Inputs outside this range fail closed.
- Layer is an integer 0–9. Relation code 1 denotes `supports`, 2 denotes `refutes`; no other relation is accepted by this kernel.
- The query matches **directed** `(src, dst, layer)`, and returns a bitmask in one caller-owned word: 0 = no candidate found; 1 = supports; 2 = refutes; 3 = both. A path or candidate is never mathematical proof.
- Invalid query, record, or count yields status 0 and does not modify output; valid query yields status 1. The **entire** record batch is validated before the lookup, including unrelated records.
- All records are read-only; no chart, MathStore, graph, training, or model state is modified. No host-language operator implements the guest lookup.

**Trust boundary:** the kernel intentionally does *not* verify historical graph revisions, SHA-256, MathLeaf evidence, Ed25519, ACL, nonces, or native admission policies. The caller must supply a complete, immutable **snapshot** from independently verified NaNROUTER graph pages, authenticated in HERMES against the resident chart and revision-history commitment. The 4-word record wire format has no cryptographic binding of its own. There is **no** warrant to dispatch a learning operation from this result. Promotion requires a separately verified, bound native admission receipt and authorization.

**Cross-repository integration pending:** map only authenticated, active candidate `supports` / `refutes` records from the graph verifier into this wire format; reject mixed chart generations and incomplete history, preserve the original evidence IDs/digests in the surrounding verified envelope, and verify a native receipt bound to the exact input digest and rule epoch. Do not infer `isa`/logical transitivity from relation labels; future inference should return explicit candidate status with provenance.

The canonical CI workflow `native-graph-claim-probe` assembles the source with pinned NaN0S and executes `mth/tests/mth_graph_claim_probe_test.nas` inside the native guest. The fixture covers all four output masks, conflicting claims, layer separation, invalid canonical addresses, invalid relation codes, over-capacity requests, and untouched outputs on failure.
