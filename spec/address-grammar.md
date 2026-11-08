# NaN hierarchical address grammar (v2, apex-layered)

## Apex stack

The address is an apex-ordered stack. Every layer is
`TYPE<namespace>:<instance>` and every layer boundary is `::`:

```text
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0
      │      │      │      │      └── HW0:0  Bootstrap hardware-node / network port
      │      │      │      └───────── BS0:0  Bootstrap service class 0, node 0
      │      │      └──────────────── MC0:0  macrocluster 0, instance 0
      │      └─────────────────────── SC0:0  supercluster 0, instance 0
      └────────────────────────────── GM0:0  global mesh 0 (apex)
```

`GM0:0` is the global-mesh apex. It is not optional and it is not the same
coordinate as `MC0:0` or `SC0:0`.

## Runner-ring heads and leaf objects

The Bootstrap port `HW0:0` is followed by the local runner-ring head block
`HW0:1-255`. A leaf object is introduced by a single `:` after the head
block. Object identity uses `#`; an optional child relation uses
`:subrelation(...)`:

```text
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0::HW0:1-255
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0::HW0:1-255:vector#1337
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0::HW0:1:vector#1337:subrelation(42)
```

A head selector accepts a comma list, a contiguous range, or a combination:

```text
HW0:1,2,3
HW0:1-255
HW0:1-8,16-24,255
```

Head selectors are local computational head indices. They are **not** global
hardware-node numbers, BSR runner-slot numbers, node points, or object IDs.
The six BSR members of macrocluster `MC0:0` remain internal wire identities;
they do not reserve `HW4`..`HW8`.

## Canonical Bootstrap coordinates

| Coordinate | Meaning |
|---|---|
| `GM0:0` | global mesh 0, instance 0 (apex) |
| `SC0:0` | supercluster 0, instance 0 |
| `MC0:0` | macrocluster 0, instance 0 (six-runner ring) |
| `BS0:0` | Bootstrap service class 0, node 0 — the persistent network port |
| `HW0:0` | Bootstrap hardware node 0 / attached network root |
| `HW0:1-255` | local runner-ring heads inside the `HW0` topology |

Koyeb hosts `BS0:0`. The public ingress is the apex stack

```text
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0
```

The Bootstrap service port and the attached hardware root are separate
coordinates. `BS0:0` identifies the port; `HW0:0` identifies the hardware
node reached through it.

## Fixed BS0 hardware-node roles

| HW node | Role | Public allocation |
|---|---|---|
| `HW0:0` | Bootstrap hardware root / network port | no |
| `HW1:0` | Android endpoint | paired device only |
| `HW2:0` | HERMES endpoint | paired device only |
| `HW3:0` | CLOCKED endpoint | paired device only |
| `HW4:0` | WordNet universe | never |
| `HW5:0`..`HW255:0` | general registered hardware nodes | yes (251 slots) |

The `:0` suffix is the zero point of each hardware instance. A translation
module may run at each zero point and relay NaN frames to the central
Bootstrap fabric. Zero points are hardware-node coordinates, not heads.

## Legacy spelling

The pre-v2 Bootstrap spelling

```text
nan://GM0:SC0:MC0:BS0:0:HW0:0
nan://GM0:SC0:MC0:BS0:0:HW0:0::HW0:1,2,3::vector1337
```

is accepted only while persisted records and older peers are migrated. It is
normalized to the apex-layered form on parse. A legacy spelling does not
create a second authority, and new code must emit only v2.

## Resolution rules

1. Parse and type-check every layer and selector before any lookup.
2. Normalize a legacy root to the v2 canonical root; never retain the legacy
   spelling as an identity.
3. Resolve `GM0:0` through the global mesh map, then `SC0:0`, `MC0:0`,
   `BS0:0`, and finally the `HW` root.
4. Expand head ranges to explicit local head references. Reject duplicate,
   descending, or out-of-range heads.
5. Resolve `kind#id` and `subrelation(...)` through the typed association
   tables for the selected head.
6. Verify route generation, target generation, permanence, lease, and ACL.
7. Reject stale, ambiguous, unregistered, or unauthorized paths. Never fall
   back to raw byte offsets or silently reinterpret a layer.
8. Return a micro-routing packet containing the normalized path and
   provenance.

## Examples

Bootstrap network port:

```text
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0
```

All runner-ring heads under the Bootstrap hardware root:

```text
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0::HW0:1-255
```

Vector 1337 on head 1:

```text
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0::HW0:1:vector#1337
```

Child relation 42 of that vector:

```text
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0::HW0:1:vector#1337:subrelation(42)
```
