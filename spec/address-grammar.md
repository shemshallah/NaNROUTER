# NaN hierarchical address grammar

## Canonical network root

The persistent Bootstrap network gateway is:

    nan://GM0:SC0:MC0:BS0:0:HW0:0

GM0 is global mesh 0; SC0 is supercluster 0; MC0 is macrocluster 0; BS0:0 is Bootstrap service class 0, node 0; HW0:0 is hardware/head namespace 0, local head 0.

Koyeb hosts BS0:0 as the always-on ingress/egress node. The six-unit runner-controlled macrocluster is MC0:0. Its six BSR runner identities remain distinct members (wire BSR0–BSR5). Koyeb provides the persistent network socket and durable bridge; it does not own the runner heads or their learned map.

## Point 0 runner-ring ingress

The six-slot runner ring is addressed through **point 0** (`BS0:0` / `BSR0`). Clients do not address `R0..R5` directly. Point 0:

1. accepts a NaN16 frame;
2. translates it to a binary transport envelope;
3. routes it to whichever single runner slot is currently active;
4. receives the binary result;
5. translates it back to NaN16.

The active slot is internal and can rotate without changing the client address. Stale slot/epoch envelopes are rejected. Point 0 is an ingress/translation endpoint, not a head, a runner slot, or a second math owner.

## Grammar (v1)

    address       = "nan://" context ":" bootstrap ":" head-path
    context       = gm ":" sc ":" mc
    gm            = "GM" uint
    sc            = "SC" uint
    mc            = "MC" uint
    bootstrap     = "BS" uint ":" uint
    head-path     = head [selector]
    head          = "HW" uint ":" uint
    selector      = "::" selector-item { "::" selector-item }
    selector-item = head-list | object-ref
    head-list     = "HW" uint ":" uint { "," uint }
    object-ref    = object-kind uint
    object-kind   = "vector" | "hyperedge" | "rule" | "route" | "bin" | "temporal"
    uint          = digit { digit }

The grammar is structural. Commas are allowed only inside a head-list selector. The root and each selector are typed segments. Double-colon is a traversal boundary, not punctuation to discard. Every selector resolves through the committed route cache and ACL. An object identifier is a symbolic key, never a raw byte offset.

## Examples

Bootstrap's persistent network node and head 0:

    nan://GM0:SC0:MC0:BS0:0:HW0:0

From Bootstrap network head 0, select heads 1, 2, and 3 in hardware namespace 0. These remain separate permanent head records:

    nan://GM0:SC0:MC0:BS0:0:HW0:0::HW0:1,2,3

Traverse through head 1 and resolve vector object 1337 using its address-association table:

    nan://GM0:SC0:MC0:BS0:0:HW0:0::HW0:1::vector1337

Traverse through head 2 and resolve hyperedge object 1337 using its member/head/bin associations:

    nan://GM0:SC0:MC0:BS0:0:HW0:0::HW0:2::hyperedge1337

## BSR compatibility

Existing bridge route URIs encode BSR0–BSR5 as a final wire coordinate. Keep that wire representation stable. The new BS0:0 node address and MC0:0 six-unit runner cluster are higher-level routing context; they do not reinterpret the six-byte route frame. A translation table maps each runner's legacy BSR wire identity to its permanent MC0:0 member record.

## Resolution rules

1. Parse and type-check every segment before route lookup.
2. Resolve the root Bootstrap node through the master network cache.
3. Resolve each HW selector to a permanent head record; comma lists expand to multiple explicit head refs.
4. Resolve vectorN, hyperedgeN, and other object refs through typed association tables.
5. Verify route generation, target generation, permanence, lease, and ACL.
6. Reject stale, ambiguous, unregistered, or unauthorized paths. Never fall back to raw address interpretation.
7. Return a micro-routing definition packet containing the exact resolved path and provenance.

A node point, local head index, BSR runner identity, and memory-object identifier are four different namespaces. Never store them in one untyped integer field.
