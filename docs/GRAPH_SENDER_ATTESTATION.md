# Detached graph sender attestation — verification, not admission

The graph source projection remains **unsigned** by default. Read-only
`NanLayerGraph.master_graph_page` supplies a canonical commitment covering the
L0–L9 current state SHA-256 and the complete revision-history SHA-256, pinned to
the topology, parent chart root and chart generation. The
`runner_riddle.graph_sender_attestation.sign_graph_attestation` helper creates a
**separate**, Ed25519-signed envelope for exactly that already computed
commitment. It never changes the source graph or the resident 8 MiB chart.

A trusted router operator must inject a real configured Ed25519 private key and
stable `router_id`/`key_id`. No user- or network-provided key may silently
become an authority. The signed canonical JSON message, prefixed by the domain
`nanrouter.graph-sender-ed25519/1\0`, binds:

- the complete `graph_commitment_sha256`, `history_sha256`, topology digest,
  parent root, chart generation;
- `router_id` and `key_id` (for independently pinned public-key lookup);
- 128-bit random nonce and issued-at Unix timestamp.

The detached envelope has schema `nanrouter.graph-sender-attestation/1` and
`signature_hex`. Its `signed_by_router` flag applies only to the *detached
envelope*, never to the graph state page. `native_mth_receipt` and
`mathematical_truth_promoted` remain **false**.

## Receiving-side requirements

1. Independently verify the complete paged state and history digests against
   the same resident HERMES chart/epoch. No sender signature can replace replay.
2. Resolve the exact expected router identity and key ID from **trusted
   configuration**, independently of the envelope. Verify Ed25519 against the
   pinned public key and domain-separated canonical message.
3. Enforce a strict maximum timestamp age and future skew with a trusted clock;
   reject missing/malformed signatures, retired keys, wrong chart generations
   or changed commitments. Nonce replay resistance requires an authenticated
   durable replay ledger, **not** just a nonce field.
4. Even a valid signed replay does **not** authorize a model update. Trusted
   evidence-leaf revalidation, N16T/MTH native execution, lease authority,
   transactional learning journal, and separate canonical NANNET promotion
   must each establish their own verifiable gate.

The producer has no network endpoint or key-management API. It does not mint
remote learning or write capabilities and is safe to keep alongside existing
unsigned graph projections.
