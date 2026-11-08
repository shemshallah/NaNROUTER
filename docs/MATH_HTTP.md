# Math HTTP ingress (Track F)

Status: implemented in `runner_riddle/math_http.py`; tests in
`tests/test_math_http.py` (30 tests, no `MathRuntime` or bridge changes).

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

`POST /v1/math/execute` is a prepared-packet/lease execution route. The
transport never prepares a packet, acquires a lease, performs host arithmetic,
or calls the NMP/ring control plane directly. Production callers bind a
`PreparedMathExecutionService` around an existing `MathExecutionBridge`:

```python
service = PreparedMathExecutionService(
    bridge,                    # MathExecutionBridge
    {"handle-1": lease},       # bounded handle -> prepared MathExecutionLease
    max_handles=256,
)
adapter = MathHttpAdapter(runtime, service=service)
```

Handles can also be added with `service.register(...)`, optionally with a
server-owned executor, an explicit `deadline_tick`, or an `owner` label. The
registry rejects duplicate handle IDs and registrations beyond `max_handles`;
it never silently replaces a live lease. `service.remove(handle_id)` (aliases
`revoke`/`unregister`) drops a handle and its cached result, while
`prune_expired(now_tick)` removes handles whose lease deadline has passed.

Accepted request fields:

| Field | Meaning |
|---|---|
| `handle_id` | Required prepared handle ID; aliases `handle`, `lease_id`, `lease`, `packet_id` (exactly one) |
| `result_digest` | Caller-supplied result digest; aliases `digest`, `output_digest`; required when the handle has no server executor |
| `result_status` | Optional bounded result status string; alias `status` |
| `output_leaf_id` | Optional bounded output leaf reference; aliases `leaf_id`, `output` |
| `commit` | Boolean; commit the completed packet, default `false` |
| `now_tick` | Integer `>= 0`, default `0` |
| `evidence` | Optional JSON object, bounded at 16 KiB |

The service resolves the server-owned handle, checks its lease deadline, and
calls `bridge.execute(lease, executor, ...)`. The executor is either the
executor stored with the handle or a callback returning the request's
`result_digest`; the digest is result metadata, never a lease or worker token.
A successful response is token-free and typed:

```json
{
  "schema": "nanrouter.math-http.v1",
  "route": "/v1/math/execute",
  "execution": {
    "schema": "nanrouter.math-execution-result.v1",
    "handle_id": "handle-1",
    "packet_id": "nmp:...",
    "status": "COMMITTED",
    "outcome": "COMMITTED",
    "result_digest": "...",
    "committed": true,
    "duplicate": false
  }
}
```

Successful terminal results are cached by handle ID. Replaying the same
execute or commit request returns the same result with `"duplicate": true`
without invoking the executor or bridge again. A later `commit: true` upgrades
an already completed result to committed without re-execution. A replay whose
`result_digest`, `result_status`, or `output_leaf_id` conflicts with the cached
result is rejected as `409 BINDING_REJECTED`. The cache is bounded; when an old
cache entry is evicted its handle is removed too, so replay fails closed rather
than executing twice.

When no service is configured, the route fails closed with an explicit typed
result instead of inventing state:

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
with reason `execute_service_missing_execute`. Prepared-service failures add
these typed cases:

| Condition | Status | Error code / reason |
|---|---|---|
| Unknown handle | 404 | `HANDLE_NOT_FOUND` / `unknown_handle` |
| Expired lease deadline | 409 | `STATE_REJECTED` |
| Raw lease/worker token field | 400 | `RAW_SECRET_NOT_PERMITTED` / `raw_secret_not_permitted` |
| Missing digest with no executor | 400 | `RESULT_DIGEST_REQUIRED` / `result_digest_required` |
| Replay conflicts with cached result | 409 | `BINDING_REJECTED` |
| Unsupported request field | 400 | `UNSUPPORTED_FIELD` |

Execution transport errors keep their typed meaning:

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
names) are replaced with `[REDACTED]`, while deliberate one-way `*_digest`
fields (for example `lease_token_digest`) are preserved. Every known caller
credential is also scrubbed from string values. The prepared execution service
separately scrubs the lease token and the bridge's configured worker/submit
tokens before its result reaches the adapter. Health output passes through the
same redaction. Access logging is disabled so headers cannot reach process
logs.

## Handler and server

`MathHttpAdapter.handle(method, path, headers, body)` is the pure,
socket-free core. `make_math_handler(adapter)` builds a bounded
`BaseHTTPRequestHandler`; `MathHttpServer(adapter)` is an optional
loopback/ephemeral-port lifecycle wrapper. The handler again enforces the body
bound before invoking the adapter.

## Limitations

- The execute route is an ingress seam, not a packet/lease factory. The
  prepared service must be populated server-side with `MathExecutionLease`
  objects from the existing bridge; this repository does not add an HTTP route
  that prepares packets or acquires leases.
- The handle registry and idempotence cache are process-local and in-memory.
  They are not durable across restart; recovery must re-register leases from
  the authoritative WaveStore rows. Duplicate suppression is per process, not
  cluster-wide.
- A handle ID is an opaque capability. Unless a deployment binds it to an
  authenticated caller at a higher layer, anyone holding the ID can submit
  result metadata for that lease.
- `result_digest` is caller-supplied completion evidence. The transport does
  not recompute or verify numerical results; that remains the bridge/kernel
  authority boundary.
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
behavior, typed execution state errors, prepared-handle success, unknown
handles, expired leases, raw-token rejection and token non-leakage, duplicate
execute/commit idempotence, conflicting-result rejection, prepared-service
health, WaveService auth reuse, token redaction, routing/method errors, and an
optional loopback round trip.
