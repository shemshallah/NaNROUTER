# Live Koyeb/NANNET0 deployment preflight

`runner_riddle/live_preflight.py` is the read-only gate that must pass before a
live Koyeb/NANNET0 deployment is treated as ready. It validates deployment
inputs, verifies the signed Koyeb volume registry with the existing
`runner_riddle.volume_registry` authority, and emits a deterministic JSON-safe
report.

The preflight does **not** mount, format, detach, snapshot, or migrate a Koyeb
volume. It does not write the registry, register a runner, or open a listener.
By default it performs **no network I/O at all**.

## API

```python
from runner_riddle.live_preflight import preflight_report

report = preflight_report()                    # offline gate
assert report["status"] in ("green", "blocked")
```

```python
from runner_riddle.live_preflight import LivePreflight

live = LivePreflight(probe=True, timeout=2.0)
report = live.report()
```

Public helpers:

| Name | Purpose |
|---|---|
| `preflight_report(environ=None, *, probe=False, ...)` | Build the deterministic report. |
| `LivePreflight(environ=None, *, probe=False, timeout=2.0, ...)` | Small wrapper; `.report()` and `.run()` return the report. |
| `load_signed_registry(path, key)` | Offline digest/signature verification only. |
| `verify_signed_registry(path, key, *, expected_generation=None, minimum_generation=None, now_tick=None, max_observation_age_ticks=None)` | Signature verification plus epoch/observation-age gates. |
| `LivePreflightError` | Fail-closed input/registry error with a stable `.code`. |
| `DeploymentConfig` | Redacting configuration value object. |

`preflight_report` never raises for missing or malformed environment values.
Each problem becomes an explicit failed check. Invalid registry material is
rejected by `load_signed_registry` / `verify_signed_registry`.

## Required inputs

Primary environment names are listed first; documented aliases are accepted.
Conflicting values across aliases fail closed.

| Input | Primary environment variable | Required value |
|---|---|---|
| Koyeb BS0DB URL | `KOYEB_BS0DB_URL` | `http`/`https` URL, no embedded credentials |
| Koyeb BS0DB token | `KOYEB_BS0DB_TOKEN` | non-empty, whitespace-free |
| Koyeb MC0DB URL | `KOYEB_MC0DB_URL` | `http`/`https` URL, no embedded credentials |
| Koyeb MC0DB token | `KOYEB_MC0DB_TOKEN` | non-empty, whitespace-free |
| NANNET0 endpoint | `NANNET0_ENDPOINT` | `http`/`https` endpoint |
| Volume registry path | `RIDDLE_VOLUME_REGISTRY_PATH` | absolute path to signed JSON |
| Volume registry key | `RIDDLE_VOLUME_HMAC_KEY` | at least 32 bytes |
| Volume key reference | `RIDDLE_VOLUME_KEY_ID` | optional safe label |
| Universe pages | `NANROUTER_UNIVERSE_PAGES` | `256` |
| Page bytes | `NANROUTER_PAGE_BYTES` | `32768` |
| Guest budget | `NANROUTER_GUEST_BUDGET_BYTES` | `1048576` (1 MiB) |
| Runner-ring policy | `RIDDLE_RING_ACTIVE_SLOT_POLICY` | `single-active` |
| Point-0 route | `NANROUTER_POINT0_ROUTE` | `nan://GM0:SC0:MC0:BS0:0:HW0:0` |

Short aliases include `BS0DB_URL`, `MC0DB_URL`, `NANNET0_URL`,
`VOLUME_REGISTRY_PATH`, `UNIVERSE_PAGES`, `PAGE_BYTES`,
`GUEST_BUDGET_BYTES`, `POINT0_ROUTE`, and the `KOYEB_BS0_URL` /
`KOYEB_MC0_URL` forms. `RIDDLE_RING_ACTIVE_SLOTS=1` may stand in for the
policy string when the count is stated explicitly. The point-0 wire identity
`BSR0` is accepted and normalized to the canonical address; direct
`MC0:0/R*` routes are rejected.

`preflight_report(..., registry_path=...)` and `registry_key=...` are accepted
as short aliases for the corresponding `volume_*` keyword arguments.

The budget values encode the current design:

```text
1 MiB guest      = 1,048,576 bytes = 131,072 NaN16 words = 32 pages
8 MiB universe   = 256 pages x 32 KiB
runner ring      = MC0:0/R0..R5, exactly one active slot
```

The last four values (`RIDDLE_RING_ACTIVE_SLOT_POLICY`,
`NANROUTER_POINT0_ROUTE`, and the page/guest constants) are architecture
invariants, but the gate still requires them to be stated explicitly so a
deployment cannot silently drift to the old 512 KiB target or a multi-active
ring.

## Report contract

```json
{
  "schema": "nanrouter.live-preflight.v1",
  "status": "green",
  "mode": "offline",
  "checks": [
    {
      "id": "volume.registry.signature",
      "status": "pass",
      "message": "volume registry digest and signature are valid",
      "evidence": {"registry_digest": "...", "generation": 1}
    }
  ],
  "summary": {"total": 20, "passed": 17, "failed": 0, "skipped": 3},
  "evidence": {
    "config_digest": "...",
    "config": {"koyeb": {"bs0db": {"url": "https://...", "token": {"length": 40, "digest": "..."}}}},
    "volume_registry": {"generation": 1, "health": "green", "registry_digest": "..."},
    "runtime": {"guest_budget_bytes": 1048576, "guest_pages": 32, "point0_route": "nan://GM0:SC0:MC0:BS0:0:HW0:0"}
  }
}
```

Check ids are stable:

- `koyeb.bs0db.url`, `koyeb.bs0db.token`
- `koyeb.mc0db.url`, `koyeb.mc0db.token`
- `nannet0.endpoint`
- `volume.registry.key`, `volume.registry.path`, `volume.registry.signature`
- `volume.registry.generation`, `volume.registry.health`
- `universe.pages`, `universe.page_bytes`, `universe.guest_budget`,
  `universe.budget_consistency`
- `runner_ring.active_slot_policy`, `runner_ring.slot_inventory`
- `point0.route`
- `probe.koyeb.bs0db`, `probe.koyeb.mc0db`, `probe.nannet0`
- `probe.timeout` only when an invalid probe timeout is supplied

`status` is `green` only when no check failed. A skipped probe keeps an offline
report green; an invalid required input, stale registry epoch, or non-green
registry blocks the gate.

The report contains no timestamps or random values. Identical inputs produce an
identical report, and `json.loads(json.dumps(report)) == report`.

## Signed volume registry gate

Verification reuses `runner_riddle.volume_registry.VolumeRegistry`; this module
does not define a second signature format or authority.

- Unsigned registries fail with `unsigned_registry`.
- A missing `registry_digest` fails with `missing_registry_digest`.
- A wrong digest or tampered volume record fails with `digest_mismatch`.
- A wrong signature fails with `signature_mismatch`.
- A registry generation below `minimum_generation`, or different from
  `expected_generation`, fails with `stale_generation`.
- With `max_observation_age_ticks`, every volume's `observed_at_tick` is checked
  against `now_tick`; old records fail with `stale_observation`.
- A clock earlier than an observation fails with `clock_regression`.
- A valid signature with `health != "green"` blocks the gate.

Staleness is only decided **after** the digest and signature are valid, so a
tampered document cannot talk its way past the epoch gate. Epoch controls can
be supplied directly:

```python
verify_signed_registry(
    "/data/volume-registry.json",
    key,
    expected_generation=7,
    now_tick=1234,
    max_observation_age_ticks=256,
)
```

or through the CLI flags. Environment equivalents are
`RIDDLE_VOLUME_EXPECTED_GENERATION`, `RIDDLE_VOLUME_MIN_GENERATION`,
`RIDDLE_VOLUME_MAX_AGE_TICKS`, and `NANCLOCK_TICK`.

## Optional network probe

`probe=False` is the default and performs no DNS lookup, socket, or HTTP call.
`probe=True` / `--probe` performs at most three requests:

```text
GET <BS0DB URL>/healthz
GET <MC0DB URL>/healthz
GET <NANNET0 endpoint>/healthz
```

Properties:

- GET only; no POST, PUT, mount, or mutation.
- Explicit timeout bounded to `0.1..10` seconds (default `2.0`).
- Response body bounded to 64 KiB; only status, body length, content type,
  body digest, and a sanitized `health` field are reported.
- Koyeb requests carry `Authorization: Bearer <token>`; the header is never
  copied into the report.
- Non-2xx responses, transport errors, and `degraded`/`unavailable` health
  values block the gate.
- Tests inject `probe_transport(url, headers, timeout, max_bytes)` and never
  require live network access.

The probe is liveness evidence only. It does not prove a volume is mounted,
that a runner acknowledged the registry, or that NANNET0 persisted a binding.

## Secret redaction

Tokens and the HMAC key are never emitted. Reports contain only:

- configured/not-configured state;
- byte length;
- a one-way SHA-256 secret fingerprint under a domain separator;
- a redacted URL (userinfo and query string removed, long path segments
  replaced).

`DeploymentConfig.__repr__` and `LivePreflight.__repr__` print `<redacted>` for
secret fields. An internal assertion rejects the report if a raw token or key
would ever appear in its serialized form.

## CLI

```sh
# Offline: validates configuration and the signed registry, no network
python3 -m runner_riddle.live_preflight --pretty

# Live liveness probes are opt-in
python3 -m runner_riddle.live_preflight --probe --timeout 2

# Enforce the signed epoch and observation age
python3 -m runner_riddle.live_preflight \
  --expected-generation 7 \
  --now-tick 1234 \
  --max-observation-age-ticks 256
```

Exit status is `0` for green and `2` for blocked. The JSON report is written to
stdout without secret material.

## Tests

```sh
python3 -m unittest tests.test_live_preflight -v
```

The suite covers missing environment inputs, invalid values, alias conflicts,
token/key/URL redaction, repr redaction, no-network default behavior, bounded
injected probes, unsigned registries, wrong digests, tampered volume records,
stale generations, stale observations, degraded volume health, valid offline
verification, and deterministic JSON-safe output.

## Live credential blocker

The repository contains no real Koyeb volume IDs, database URLs/tokens,
NANNET0 endpoint, or production signing key. A local green report therefore
proves the gate logic and registry contract only; it does **not** prove that a
live Koyeb deployment is healthy. A live green requires operator-supplied
secrets plus a registry signed from the four real Koyeb volume observations.
Until those exist, the deployment must be reported as unconfigured/blocked
rather than green.
