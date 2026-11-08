# L0-L9 versioned NaN relationship matrix

The topology is **256 fixed heads + 32,640 canonical mirror pairs**. Every
relationship is an edge between canonical cells, not an extra 16-bit NaN
address. The 65,536 directional addresses resolve through the immutable MP
microtables. The same cell may participate in multiple layer-indexed edges.

`NanLayerGraph` is an additive MC0DB index over the existing `MathStore`.
A proposed edge contains a source cell, destination cell, L0-L9 coordinate,
relation type, existing immutable MathLeaf evidence version and digest,
source head, generation and tick. Only a real endpoint head can propose
the edge. A stale generation, invalid evidence or invalid layer fails closed.
Each accepted revision appends an immutable history record.

The L0-L9 coordinates are currently **neutral storage coordinates**, not
ten invented mathematical operators. MTH must separately define and validate
the transformation associated with each layer, establish sound proof rules,
and produce native execution receipts. The graph stores candidate claims;
it does not equate storage with mathematical truth.

An iterative refinement protocol can compare graph proposals on held-out
tasks, record evidence and counterexamples, and promote only those that pass
independent MTH/NMP verification. `neighbors` provides bounded, digestable
pages for routing and introspection; no uncontrolled full-matrix expansion.

## CAS retraction and stable master commitment

NanLayerGraph.retract(edge_id, source_head, expected_generation, tick) tombstones
a candidate while retaining its immutable evidence and all append-only MC0DB
nan_layer_edge_history versions. Only the original proposing real head can
retract; stale generations, backward ticks and attempts to overwrite an
existing claim's endpoints or original head are rejected. A newer CAS
generation can reactivate the same canonical endpoints.

master_graph_page(parent_root_sha256, chart_generation, offset, limit)
returns at most 100 records, plus an offset-independent SHA-256 commitment
over ALL current candidate and tombstone records and their ordered histories.
The commitment domain-binds the canonical topology digest, HERMES chart
parent root and chart generation as supplied by the caller. Records and
digests come from one SQLite read transaction. Missing or discontinuous
history, and current rows differing from their latest history, fail closed.

This is an unsigned local commitment, NOT an authenticated router/HERMES
handshake, MTH verdict, native execution receipt or head-bank mutation.
A receiver must independently verify the chart root/generation and trusted
sender before accepting it. If the commitment changes between pages, the
reader must restart its pagination at a stable snapshot.
