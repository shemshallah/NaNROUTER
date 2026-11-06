# NaNROUTER

**Bootstrap logic, address mapping, and NaNNet routing control plane.**

NaNROUTER organizes the networking and learning-control layers around the existing NaNLMind single-universe model. It does not create a second topology or a second owner of memory. The canonical computational state remains the NaNLMind universe; this repository defines how Bootstrap observes it, learns its maps, routes through authorized bins, and proposes safe mapping changes.

## Current design boundary

- One 8 MiB Bootstrap universe, with 256 palindromic heads.
- One 2 GiB overbootstrap map hosted only by the Bootstrap runner; it is not copied to Android or peer nodes.
- Six BSR runner-ring identities, mapped to the user's point assignments in `spec/point-map.toml`.
- Point 1 is the permanently attached phone; point 2 is the Hermes demo; point 3 is the clocked demo.
- Points 9–255 are available for registration, subject to NANNET registration and authorization.
- Six BSR heads are reserved for ring/control work. The other 250 heads receive the continuous Boolean/NaN16 curriculum.
- Runner Riddle is the long-running NaN-source listener and mapping learner. It learns topology and address-to-head mappings before language.
- The ten mathematical mapping layers are all represented inside one universe. They are not ten independent minds.

## Important namespace rule

There are two separate 0–255 namespaces:

1. **Overbootstrap node points** identify attached systems and registered endpoints.
2. **Local head indices** identify the 256 palindromic heads inside each 8 MiB universe.

The six BSR head indices are `0,4,5,6,7,8`. The 250 remaining head indices are Boolean-learning heads. Node points 1–3 are phone/demo endpoints; they are not additional reserved BSR heads.

The BSR display labels are one-based (BSR1–BSR6). The existing NaNNet wire URI remains zero-based (BSR0–BSR5), so point 0 / BSR1 uses wire coordinate `BSR0`. This avoids breaking the established binary bridge protocol.

## Hard safety boundary

Runner Riddle is read-only against live maps by default. It may:
- read NaN source and permitted register bins;
- derive Boolean truth tables and NaN16 operation maps;
- learn permanent-head and bit-address relationships;
- build candidate hyperedges, vectors, route tables, and map deltas;
- emit signed, bounded learning traces.

It may not:
- write outside the exact bin/range ACL supplied by the Bootstrap/NANNET authority;
- allocate from unregistered, ephemeral, or unknown address ranges;
- overwrite permanent endpoint identities or BSR control heads;
- modify executable code, protocol definitions, or live route tables directly;
- merge a candidate map without validation, authorization, and a generation-checked commit.

Unknown or not-yet-imported ranges are **deny by default**. The machine-readable policies are in `spec/`.

## Network addressing and committed route cache

- Koyeb is the persistent gateway at `nan://GM0:SC0:MC0:BS0:0:HW0:0`.
- `MC0:0` is the six-unit runner-controlled macrocluster; the six BSR wire identities remain BSR0–BSR5.
- The `::` selector boundary addresses individual heads and typed objects such as `vector1337` and `hyperedge1337`.
- Every resolved path is compiled into a signed micro-routing packet and committed into a generation-chained master network cache.
- The master cache is the authoritative set of committed routes; candidate learning never edits it directly.

See `spec/address-grammar.md`, `spec/master-network-cache.schema.json`, `spec/route-record.schema.json`, and `spec/micro-route-packet.schema.json`. The router-owned Koyeb logical-volume registry is specified in `spec/volume-registry.md` and `spec/volume-registry.schema.json`; NaNLMind supplies the codec, while NaNROUTER owns provider bindings and health.

## Runner Riddle route engine

The `runner_riddle` package provides a typed address parser, a signed
generation-chained master route cache, a micro-route packet compiler, and a
read-only trace pattern miner.

```
nan://GM0:SC0:MC0:BS0:0:HW0:0::HW0:1,2,3
nan://GM0:SC0:MC0:BS0:0:HW0:0::HW0:1::vector1337
nan://GM0:SC0:MC0:BS0:0:HW0:0::HW0:2::hyperedge1337
```

The parser keeps node, head, and object namespaces distinct. The durable SQLite inbox deduplicates source bytes, leases work to supervised workers, recovers expired leases, stores provenance-bound traces, and queues candidate feedback back to Bootstrap MC0:0 for acknowledgement. The macro planner reserves six explicitly bound BSR control heads and assigns the remaining 250 heads to Boolean learning before ten-layer routing; all work is restricted to signed allocator ranges and candidate bins. Resolution uses
only committed cache entries and the cache-resident head/object association tables; callers cannot substitute an external map.
The master cache stores head associations and typed object associations alongside routes; permanent head identities cannot be overwritten, and ephemeral head entries require a live lease tick. Micro-route packets are digest-bound and HMAC-signed. Candidate learning never
writes the master cache; committing requires the route-commit capability and
an exact generation compare-and-swap. Trace mining emits pattern candidates,
not executable routes.

Run the standard-library tests with:

```
python -m unittest discover -s tests -v
```

This is the routing engine, not yet a deployed 24/7 Koyeb listener. N16T intake,
persistent worker supervision, and live service wiring remain the next stage.

## Ten mapping layers

| Layer | Mapping job | Primary representation |
|---|---|---|
| M0 | bit identity and Boolean truth | NaN16 bit/Boolean operations |
| M1 | byte and word composition | directed pair cells and token refs |
| M2 | head/address binding | permanent head IDs and address atlas |
| M3 | vector/bin mapping | BinRef, vector bins, point-to-bin map |
| M4 | temporal sequence | past/future rails and nanclock |
| M5 | hyperedge mapping | typed multi-head relations |
| M6 | logic/rule mapping | triples, truth, exceptions, proofs |
| M7 | route mapping | NANNET, BSR, endpoint and bridge routes |
| M8 | merge/consensus mapping | generation, provenance, idempotent deltas |
| M9 | meta-map and policy | cross-layer consistency, MC0 overbootstrap |

Every layer lives in the same universe and is addressed through the same atlas. Each layer has its own math and storage contract; no single optimizer is imposed across them.

## Runner Riddle

See [runner-riddle/README.md](runner-riddle/README.md). The listener is designed as a persistent service, not a short-lived scheduled GitHub Action. It continuously ingests permitted NaN source, learns Boolean and routing maps first, and emits bounded trace/delta records. Language learning is a later curriculum stage, disabled until the logic/routing gates pass.

## Integration targets

- `NaNLMind`: canonical universe, Boolean core, 8 MiB register, overbootstrap map, head store, vector bins, hyperedges, and merge semantics.
- `NaNLMind_android`: 8 MiB edge universe and phone endpoint; never receives the 2 GiB overbootstrap map.
- `NaNLMind_HERMES`: demonstration/training client at node point 2; not the owner of Bootstrap's logic curriculum.
- Koyeb/NANNET authority: registration, bridge transport, bounded merge ingress, and health/lease services.

## Status

This repository begins as the routing/control-plane specification and policy home. A manifest does not mean a 24/7 service is already deployed. The listener, storage adapter, integration tests, and persistent service deployment must be built and verified against the canonical NaNLMind APIs before live learning is enabled.

## CLOCKED service identity and HW3 selector (proposed)

The Rezolve.ai CLOCKED service is registered as the Clocked demo at Router node
point 3. HERMES reserves HW3 for the corresponding service/hardware identity.
These identifiers are separate namespaces and require an explicit signed
binding; point 3 must not be inferred to mean head 3 or BSR wire 3.

The proposed selector contract is:

- `HW3` — registered CLOCKED service identity;
- `HW3:0` — NANNET interface/control endpoint for handshake, capabilities,
  route resolution, task/scratch transport and receipts;
- `HW3:1..255` — logical head ports resolved through explicit Router
  head/object associations.

This is a proposed CLOCKED binding, not a currently deployed Router route.
The port table must map to existing internal head IDs and pair ranges without
renumbering the 256-head topology or the six reserved BSR heads. It must also
preserve the six-runner ownership map and generation-checked route cache.
HW3:0 is not an extra semantic head.

See the canonical NaNLMind CLOCKED architecture:
[docs/CLOCKED_HERMES_BRAINSTORM.md](https://github.com/shemshallah/NaNLMind/blob/main/docs/CLOCKED_HERMES_BRAINSTORM.md).
