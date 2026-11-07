# Math HTTP ingress (Track F)

Status: implemented in `runner_riddle/math_http.py`; tests in
`tests/test_math_http.py` (21 tests, no `MathRuntime` or bridge changes).

This module is a thin standard-library transport around the existing math
control plane. It does not perform host arithmetic, prepare NMP packets, create
execution state, acquire leases, or introduce a second authority.

## Routes

| Method | Path | Body | JAHS header | Auth |
|---|---|---|---|---|
| `GET` / `HEAD` | `/v1/math/health` | none | not required | not required |
| `POST` | `/v1/math/link` | JSON | `X-NaN-JAHS: JAHS` | optional (delegated) |
| `POST` | `/v1/math/execute` | JSON | `X-NaN-JAHS: JAHS` | optional (delegated) |

The request body is bounded at exactly 2 MiB (`MAX_BODY_BYTES = 2,097,152`).
A declared `Content-Length` above the bound returns `413 BODY_TOO_LARGE`
without reading the body. Chunked bodies and non-identity content encodings
are rejected. POST bodies must be `application/json`; JSON objects must be
UTF-8, must not contain duplicate keys, and must not contain non-finite
numbers.

`X-NaN-JAHS` must contain the existing `JAHS_SEAL` value (`JAHS`). Missing and
wrong values return `403 JAHS_REQUIRED` and `403 JAHS_INVALID` respectively.

## Health

`GET /v1/math/health` returns a deterministic report assembled only from
existing health providers:

```json
{
  "schema": "nanrouter.math-http.v1",
  "route": "/v1/math/health",
  "health": {
    "status": "green",
    "healthy": true,
    "issues": [],
    "body_limit_bytes": 2097152,
    "jahs_required": true,
    "execute": {
      "available": false,
      "reason": "execute_service_not_configured"
    },
    "rule_snapshot_id": "",
    "components": {
      "functions": {"healthy": true, "...": "..."}
    }
  }
}
```

`components` may also include `store` (`MathStore.math_health()`), `system`
(`MthSystem.health()`), `linker`, `rule_provider`, and `execute` when those
providers are bound. A missing provider is not fabricated as zero or green;
provider failures are reported as `unhealthy` with the exception type only.
The overall `status` is `green`, `degraded`, or `red`. An unavailable execute
route does not by itself degrade the math runtime; it is reported separately.

## Link

`POST /v1/math/link` delegates to `MathRuntime.propose(...)` and returns the
existing `LinkResult.to_dict()` unmodified under `link`:

```json
{
  "schema": "nanrouter.math-http.v1",
  "route": "/v1/math/link",
  "link": {
    "schema": "nanrouter.math-candidate-set.v1",
    "candidates": [],
    "candidate_count": 0,
    "execution": "not_performed",
    "authorization": "not_granted"
  }
}
```

Accepted request fields:

| Field | Meaning |
|---|---|
| `operands` / `refs` | Array of pinned leaf references (`nml:...@vN`, leaf mappings, or `math://...`) |
| `query` | Raw `A :: B` expression accepted only by this explicit math endpoint |
| `mode` | `conjoin` (default) or `transform` |
| `objective` | Linker objective string |
| `max_candidates` | Integer `0..256` (default `8`) |
| `bounds` | `{max_depth, max_fanout, fuel}`; bounded at `8`, `256`, `65536` |
| `goal` | Optional transform goal |
| `snapshot_id` | Optional caller snapshot ID, at most 512 characters |
| `allow_scratch` | Boolean, default `false` |

Exactly one of `query`, `operands`, or `refs` is required. Any `execute` field
is rejected with `EXECUTION_NOT_PERMITTED`; arbitrary linker keywords such as
`registry`, `leaves`, `rules`, `capabilities`, or `aliases` are rejected as
unsupported fields. References are validated with the linker's own
`parse_ref` before resolution, then resolved through `MathRuntime.leaf(...)`
so `nml:` and `math://.../leaf/...` forms agree and client-supplied leaf
content cannot bypass the authority. `nan://...` input returns
`ADDRESS_CONTEXT_MISMATCH` rather than being treated as a leaf lookup or a
mathematical operation; a missing pinned leaf returns a typed
`LINK_REJECTED` with reason `unknown_leaf`.

The linker remains proposal-only: the response always reports
`"execution": "not_performed"` and `"authorization": "not_granted"`.

## Execute

`POST /v1/math/execute` deliberately does not prepare a packet or acquire a
lease. Execution state is caller-owned: the adapter requires a service object
that already owns the prepared packet/lease and exposes:

```python
service.execute(request: dict) -> dict | None
```

`request` is the parsed JSON body; the returned mapping is rendered under
`execution`. A returned `None` becomes `{"status": "ACCEPTED"}`. The adapter
never calls `MathExecutionBridge.prepare_packet`, `submit`, `lease`, or
`execute` itself, and a bare `MathExecutionBridge` is rejected by the
constructor so a caller cannot accidentally hand over an unbound bridge.

When no such service is configured, the route fails closed with an explicit
typed result instead of inventing state:

```json
{
  "schema": "nanrouter.math-http-error.v1",
  "error": {
    "code": "UNAVAILABLE",
    "message": "math execute route is unavailable",
    "reason": "execute_service_not_configured"
  }
}
```

A service that exposes `health()` but no `execute()` yields the same status
with reason `execute_service_missing_execute`. Execution transport errors keep
their typed meaning:

| Condition | Status | Error code |
|---|---|---|
| Gate unavailable | 503 | `UNAVAILABLE` |
| Gate unauthorized | 403 | `UNAUTHORIZED` |
| Stale gate/snapshot | 409 | `STALE` |
| Other gate rejection | 409 | `GATE_REJECTED` |
| Ring unavailable | 503 | `RING_UNAVAILABLE` |
| Plan/binding/state rejection | 409 | `PLAN_REJECTED`, `BINDING_REJECTED`, `STATE_REJECTED` |
| Store unavailable | 503 | `STORE_UNAVAILABLE` |

## Errors

Every error uses the same typed envelope:

```json
{
  "schema": "nanrouter.math-http-error.v1",
  "error": {
    "code": "INVALID_JSON",
    "message": "request must be valid UTF-8 JSON",
    "reason": "optional_machine_reason",
    "retryable": true
  }
}
```

`message` is whitespace-collapsed and length-bounded. Unexpected exceptions
render as `500 INTERNAL_ERROR` without their text. Linker failures preserve
`reason` (for example `address_context_mismatch`), while the transport `code`
stays stable.

## Authentication and secret hygiene

Bearer authentication is optional and never reimplemented. When `auth=` is
supplied it must expose the existing `WaveService._authorize(token, roles)`
method; the adapter reuses that check and returns `401 UNAUTHORIZED` or
`403 FORBIDDEN`. Production deployments should bind a `WaveService` authorizer.

The adapter never includes request headers or request bodies in responses.
Token-like result keys (`token`, `secret`, `password`, `api_key`, and related
names) are replaced with `[REDACTED]`, and every known caller credential is
also scrubbed from string values. Health output passes through the same
redaction. Access logging is disabled so headers cannot reach process logs.

## Handler and server

`MathHttpAdapter.handle(method, path, headers, body)` is the pure,
socket-free core. `make_math_handler(adapter)` builds a bounded
`BaseHTTPRequestHandler`; `MathHttpServer(adapter)` is an optional
loopback/ephemeral-port lifecycle wrapper. The handler again enforces the body
bound before invoking the adapter.

## Limitations

- The execute route is an ingress seam, not an executor. It intentionally
  requires a caller-owned prepared/leased service. This repository does not
  define that wrapper here because doing so would duplicate `MathExecutionBridge`
  packet/lease authority.
- There is no built-in token store. Authentication is delegated to
  `WaveService` when provided; without it, only the JAHS gate and any
  service-level checks apply.
- The route set is intentionally limited to health, link, and execute. It does
  not add submit/lease/complete HTTP routes or a durable NMP packet ledger.
- Health is a composition of existing health providers; it does not perform
  preflight or execution probes.

## Tests

```sh
python3 -m unittest tests.test_math_http -q
```

Coverage includes the exact 2 MiB bound and oversized rejection, missing and
invalid JAHS, invalid JSON/content types, unknown fields and execute flags,
link candidate output, raw `::` expressions, `math://` operands, address
context and unknown-leaf rejection, execute unavailable and delegated
behavior, typed execution state errors, WaveService auth reuse, token
redaction, routing/method errors, and an optional loopback round trip.
