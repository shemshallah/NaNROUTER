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
