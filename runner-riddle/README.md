# Runner Riddle

Runner Riddle is the persistent NaN-source listener and mapping learner for Bootstrap. Its first responsibility is to learn the structure of NaN16 and the universe's address/head/routing map. Natural-language learning is deliberately later.

## Runtime contract

- Persistent listener with reconnect, bounded queues, leases, health endpoint, and checkpoint recovery.
- Reads authorized NaN source feeds and register bins; no unrestricted filesystem or memory scan.
- Uses the canonical NaN16DE codec and NANNET binary bridge.
- Trains only the 250 Boolean-learning heads. The six BSR control heads are immutable to this learner.
- Writes candidate deltas only to the dedicated training bins granted by the authority.
- Submits route/merge proposals with source digest, base generation, nanclock tick, and ACL digest.
- Does not run on Android with a 2 GiB overbootstrap mapping; Android remains an 8 MiB edge universe.

## Service states

`OFF -> OBSERVE -> LEARN_BOOLEAN -> LEARN_ROUTING`

`LANGUAGE_DEMO` is a later opt-in state and is not the default.

## Required endpoints/adapters

- `GET /healthz`: process, lease, checkpoint, and intake status; no secrets.
- `POST /v1/riddle/control`: signed learning-stage trigger.
- `POST /v1/riddle/source`: bounded NaN16 source intake.
- `GET /v1/riddle/trace`: authenticated trace cursor.
- `POST /v1/riddle/candidate`: bounded candidate-delta submission.
- N16B bridge: use the existing NANNET frame format and route validation; do not invent a second transport.

## Deployment

The production listener should run as a persistent Koyeb service (or an always-on authorized runner) with durable checkpoint storage and a bounded queue. GitHub Actions is for CI and release packaging, not a fake 24/7 daemon.

## Not yet implemented

This directory is currently the runtime contract. The listener implementation, exact allocator-backed bin ACL import, source adapters, and persistent deployment must be completed and tested before enabling live learning.

## Router-owned Koyeb volume registry

The four canonical shard-zero identities and provider-binding rules are defined
in [../spec/volume-registry.md](../spec/volume-registry.md). The registry is
read-only at runtime: it does not create, mount, detach, format, snapshot, or
migrate provider volumes. Missing registry configuration reports health as
unknown; green requires both a signed green observation and verified mount.

## MC0:0 six-runner reconciliation

The ring has six fixed identities, `MC0:0/R0` through `MC0:0/R5`. Each
runner acknowledges the current signed volume-registry generation and digest
through `POST /v1/riddle/ring/heartbeat`. The router persists the latest
heartbeat in SQLite and reports `in_sync`, `waiting`, `stale`, or `drift` per
slot. The ring is green only when all six slots acknowledge the same current
registry and are within `RIDDLE_RING_STALE_TICKS` (default 256 NaN-clock ticks).
This is control-plane convergence, not a claim that every remote runner mounts
Koyeb storage directly. Volume mount health remains independently verified.
