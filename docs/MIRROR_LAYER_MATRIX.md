# A single nan:// universe: L0–L9 sparse information matrix

This continues `docs/MIRROR_POINT_REGISTER.md` and `docs/GAME_PLAN_::.md`.
It is a **candidate relation index**, not a native MTH executor or a new
SQLite database. Routing is now:

```text
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0                -- canonical universe port
  ::HW0:7::L3                                           -- fixed head, conceptual resolution
  ::HW0:MP123::L3                                       -- canonical mirror pair and its layer
  ::HW0:7::HW0:MP123::L3                                -- endpoint-constrained view
```

The addressing algebra is a resident 128 KiB + 65,792 B constant lookup
structure. No 256x32640 materialized edge matrix and no copy of the 8 MiB
physical NaN chart are created. The head-to-MP incidence graph already follows
from `C(256,2)`; a fixed head has 255 incident MPs, a given MP has two
endpoints. A singular `nan://` URI cannot manufacture a `math://` leaf
or bypass head 0's NANNET0-only role.

## The four strata of one information universe

1. **Physical chart:** `N16ROOT1` + `NLMCHRT1` in the same 8 MiB HERMES page, immutable fixed-point/mirror geometry and original NaN faces. The guest owns hardware mutation.
2. **Structural directory:** `MirrorRegister` calculates the complete 32,896-cell topology; no database row per fixed cell is required.
3. **Versioned leaf and relation matrix:** `MC0DB` indexes `nan_mp_binding` and `nan_layer_relation`. `BS0DB` stores immutable, content-addressed typed leaves. Each learned relationship has a root/MP/level/target/type identity, explicit direction, Q16.16 strength, signed polarity, source head, evidence digest, CAS generation and immutable revisions. One typed leaf may be bound by multiple MPs.
4. **Master scratch:** paginated, content-hashed read-through projections (one parent root and chart generation). HERMES and the native head bank may consume evidence only through authenticated runner handoffs; the `MasterScratch` projection is never a second math authority.

`L0..L9` are **resolution coordinates**, not ten duplicate models. The
relations `abstracts_to` and `refines` move exactly one adjacent level;
other typed relations are same-level, so iterative experimentation cannot
arbitrarily skip semantic granularity. Full graph-walk defaults to depth 2
and is bounded to depth <=4, <=128 visited nodes, with bounded 64-result
pages. Cycles terminate via visited identity `(kind,id,layer)`.

## Learning protocol

A proposed edge must be sourced from the corresponding real head endpoint
(1..255), cite an evidence digest and a current CAS generation, and never
target the NANNET0 head. The store refuses stale edits; prior confidence,
polarity and evidence are available in immutable `nan_layer_relation_history`.
Contradictions are retained rather than silently taken as proof or collapsed
into a single universal "truth". A root digest scopes data to one parent
chart and the globally constant topology hash.

A `propose` invocation only records a candidate. It does NOT execute native
NaN16 or MTH, attest the guest, perform mathematical validity preflight,
confirm a corpus trained, or promote any theorem. Those actions require the
existing authenticated `HermesDispatchJournal`, `MathValidityEngine`,
`NMP` and actual NaN16 executor.

## Storage and packing

Keep live SQLite WAL files **outside** the binary root. A single portable
snapshot can later be exported as `.n16pack` containing one chart byte
image, an SQLite online-backup image and content-addressed leaf blobs under
a generation-checked manifest. Editing an embedded *live* SQLite filesystem
inside NaN16 would violate both commit protocols. This one logical universe
need not be one mutable file.

## Test gates

`tests/test_mirror_layer_matrix.py` verifies L0–L9 route grammar, no eager
MP expansion, implicit structural incidence, sparse many-to-many relations,
CAS rejection, root scoping, immutable negative-memory generations, directed
two-hop abstraction/refinement and bounded traversal. Numerical learning
improvements require a separate native training and frozen held-out corpus
experiment.
