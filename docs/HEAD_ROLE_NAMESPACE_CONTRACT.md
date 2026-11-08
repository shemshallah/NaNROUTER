# Palindrome head capacity vs BSR control roles

**One chart, one topology, three distinct counts.**

| Count | Meaning | Source |
| ---: | --- | --- |
| **256** | Immutable fixed-point addresses/physical palindrome head cells | `C(256,2)` mirror topology |
| **255** | Head indices eligible to originate MC0DB MP microtable writes (excluding network/root head 0) | Existing `MirrorRegister` / HERMES `writable_heads` |
| **250** | Head indices eligible for the continuous Boolean/NaN16 curriculum after six internal BSR control-head reservations | NaNROUTER ring allocation policy |

Reserved **local head indices** `0,4,5,6,7,8` represent internal
BSR0–BSR5 control roles. The head-to-internal-slot mapping is
`0→BSR0, 4→BSR1, 5→BSR2, 6→BSR3, 7→BSR4, 8→BSR5`.
The mapping **does not allocate six HW nodes** and does not alias global
`BS0:0` (ring port), `HW0:0` (hardware-node root), or global `HW5:0`
(runner ring hardware coordinate). Those are separate namespaces.

The 256 topology heads continue to exist, and each nonfixed mirror pair
continues to hold one canonical cell and two directional addresses.
The 255 MP pairs involving root head 0 have one eligible writer (their
nonroot endpoint); the other 32,385 MP pairs have two eligible writers.
All 32,640 MP microtables retain existing access rules.

## Additive versioned read-only contract

`runner_riddle/head_role_contract.py` reports `describe_head(head)`
and `role_summary()` with deterministic `role_contract_sha256`.
`MirrorRegister.status()` now includes the schema, digest and counts.
This contract **only describes allocation**. It grants no permissions,
reassigns no root head, alters no NaN16 chart bytes, creates no independent
universe, and promotes no candidate relation. MathStore, NANNET, NMP and
native MTH retain all their existing authority and gates.

A GitHub Actions parity workflow checks all **256** fixed-point heads and
**32,640** MP microtables against HERMES independently, including exact
canonical addresses, topology digest and writable-head lists, on both
Python 3.10 and 3.12. All changes are additive and no source learning
threshold or native writer ACL is silently loosened.

## Distinguish semantic layers

The NaNLMind core project correctly states that all 256 fixed points are
present; that is a *topological* statement, not a promise of 256 independently
writable curriculum workers. At the control-plane layer head 0 is reserved
and five more indices are reserved for BSR tasks. A future change to their
writer or training roles must be an explicit versioned policy migration,
not inferred from a count in a README.
