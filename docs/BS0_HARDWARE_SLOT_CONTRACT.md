# Shared BS0:0 ring-port / HW0:0 hardware-node contract

The canonical Bootstrap NANNET **port** is `BS0:0`. The attached
Bootstrap hardware-node **coordinate** is `HW0:0`. They are separate
coordinates, not aliases and not the same resource:

- `nan://GM0:SC0:MC0:BS0:0` identifies the port/control-plane route.
- `nan://GM0:SC0:MC0:BS0:0:HW0:0` identifies the BS0:0 port
  followed by a typed root HW0:0 hardware-node selector.
- Legacy `nan://GM0:SC0:MC0:BS0:HW0` identifies HW0 within BS0.
  Treat it as a versioned compatibility identity, not as proof a lease
  or route is active.

The **BS0 runner ring is shared**. R0–R5 / BSR0–BSR5 are internal
worker identifiers and do not occupy HW5..HW8, nor reserve separate
hardware nodes. HW numbers denote hardware nodes, not model heads.
The BSR head indices 0,4,5,6,7,8 inside one local topology remain
*local head indices*; their numerical values do not reserve same-numbered
global HW hardware addresses.

## BS0 fixed endpoints

| HW node | Function | May public portal allocate? |
|---|---|---|
| HW0 | Bootstrap hardware root | No |
| HW1 | Android hardware endpoint | No |
| HW2 | HERMES hardware endpoint | No |
| HW3 | CLOCKED endpoint | No |
| HW4 | WordNet universe hardware node | **Never** |
| HW5–HW255 | General registered hardware nodes | Yes (251 slots) |

The six CPU worker repositories are an implementation of the BS0
runner ring, not extra HW reservations. Other bootstrap classes
BS1..BS255 have *independent* HW0..HW255 address namespaces;
this table does not preallocate every other bootstrap.

## Local node point, head index and lease binding

The current NANNET portal endpoint format maps HWn to 1-based local
point n+1, including HW255 to point 256. This is a translation
function for native overbootstrap addressing, **not** a substitution
of the HW coordinate by a runner index. Use the signed route table to
recover the full BS/GM/SC/MC context.

An attached 8 MiB native universe has its own local computational
heads; the 255+1 NANNET ring model reserves exactly one network port
inside that universe. Its local port is not BS0:0 or HW4; these live
in *different* namespaces.

## Allocation and migration

NANNET currently allocates HW node identities. Until the portal is
fully migrated from NaNLMind to NaNROUTER, the old Koyeb NANNET portal
remains the allocation authority. Never create parallel issuers or
lease writers.

Existing mistaken allocations in HW4 must be explicitly migrated
to HW5+ without silently losing durable evidence, held route
generations or device credentials. Fail closed on an unmigrated
reserved-slot bearer. Do not repurpose a live HW4 lease as WordNet
without safely relocating and reconciling it.
