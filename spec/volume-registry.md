# Router-owned Koyeb volume registry

The four persistent Koyeb volumes are registered here, not in NaNLMind's
computational core. NaNLMind provides the NaN word/address codec; NaNROUTER
owns the logical-to-physical binding and exposes read-only status to the
runner ring and authorized universe clients.

## Ownership

- **NaNROUTER** owns the signed registry, logical identities, generation chain,
  mount verification state, and health aggregation.
- **The six-unit MC0:0 runner ring** coordinates work and observes/reconciles
  registry state through authorized control-plane interfaces.
- **Koyeb BS0:0** remains the persistent ingress/egress gateway. It hosts the
  listener and persistent data mounts; it does not own runner heads or the
  master route cache.
- **NaNLMind** remains the canonical computational universe and supplies the
  reusable NaN word/address representation.

## Canonical shard-zero identities

| Tier | Logical identity | Mount root | Database file |
|---|---|---|---|
| BS0 | `0x7FF14E1100E8F17F` | `/0x7FF14E1100E8F17F` | `bs0db.sqlite3` |
| MC0 | `0x7FF14E1200D7F17F` | `/0x7FF14E1200D7F17F` | `mc0db.sqlite3` |
| SC0 | `0x7FF14E1300C2F17F` | `/0x7FF14E1300C2F17F` | `sc0db.sqlite3` |
| GM0 | `0x7FF14E1400A9F17F` | `/0x7FF14E1400A9F17F` | `gm0db.sqlite3` |

These are stable logical addresses, not Koyeb filesystem paths. The current
physical mount destinations remain `/bs0db`, `/mc0db`, `/sc0db`, and `/gm0db`
from the existing four-volume deployment. Koyeb provider-generated volume IDs,
mount destinations, region, mount verification, and observed health are
physical deployment bindings. Replacing a physical volume must not change its
logical NaN address. Never invent provider IDs or mark a volume green from
configuration alone.

## Registry contract

The signed document uses `nanrouter.volume-registry.v1` and carries a
monotonic generation, previous digest, canonical SHA-256 digest, and HMAC-SHA256
signature. The HMAC key is supplied only through
`RIDDLE_VOLUME_HMAC_KEY`; it is never stored in Git or returned by the API.

Every canonical tier must have shard 0. Additional shards may use 1..255 and
must have unique logical addresses, provider IDs, and mount roots. Shard IDs
must never be recycled while references may exist.

A volume is green only when its signed observation says `health=green` AND
`mount_verified=true`. Missing registry means `unknown`, not green. The
registry verifier is read-only: it does not mount, format, detach, snapshot,
copy, or migrate Koyeb data.

## Runtime

- Registry path: `RIDDLE_VOLUME_REGISTRY_PATH` (default
  `/data/volume-registry.json`)
- Signing key: `RIDDLE_VOLUME_HMAC_KEY` (32+ bytes, independent from other keys)
- `GET /healthz` includes a safe aggregate `volume_registry` summary.
- Authenticated runner-ring clients may read `GET /v1/riddle/volumes`.
- There is no API to mutate provider bindings or claim live Koyeb health.

The first production registry must be populated from the four real Koyeb
volume IDs and verified mount observations. Until then the software reports
unconfigured/unknown and does not alter the existing volumes.

## MC0:0 runner-ring reconciliation

Six reserved runner identities `MC0:0/R0` through `MC0:0/R5` acknowledge
the exact signed registry generation and digest. The router persists each
heartbeat and exposes a convergence snapshot. Green requires all six slots to
be in sync and fresh under `RIDDLE_RING_STALE_TICKS` (default 256). The runner
ring observes registry convergence; it does not claim direct mounts on remote
runners. Physical Koyeb mount verification is a separate volume observation.

- `POST /v1/riddle/ring/heartbeat` — authenticated runner acknowledgement
- `GET /v1/riddle/ring?nanclock_tick=N` — authenticated reconciliation snapshot
- `GET /healthz` — includes runner-ring convergence status
