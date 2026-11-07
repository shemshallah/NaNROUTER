# Wave HTTP Adapter

`runner_riddle/wave_http.py` is a Python-standard-library HTTP transport for the
R8 wave control plane. It wraps an existing `WaveService` and its `WaveStore`
using `http.server`/`socketserver`; it has no third-party dependencies and does
not require a separate web framework.

The adapter is deliberately thin. It parses bounded JSON, reads a bearer token,
delegates role authorization to `WaveService`, and returns the record produced
by the existing facade/store. It performs no wave mathematics, owns no
persistence, and never writes credentials to a database or an access log.

## Construction and lifecycle

```python
from runner_riddle.wave_http import WaveHttpServer
from runner_riddle.wave_service import WaveService
from runner_riddle.wave_store import WaveStore

store = WaveStore("bs0db.sqlite3", "mc0db.sqlite3")
service = WaveService(
    store,
    submit_token=submit_token,
    worker_token=worker_token,
    admin_token=admin_token,
)
server = WaveHttpServer(service, host="127.0.0.1", port=0)
server.start()
print(server.base_url)   # http://127.0.0.1:<ephemeral-port>
try:
    ...
finally:
    server.stop()
```

`WaveHttpServer` also works as a context manager:

```python
with WaveHttpServer(service) as server:
    url = server.base_url
```

- `start(host=None, port=None)` binds the listener, starts a daemon serving
  thread, and returns the server. `port=0` selects an ephemeral port.
- `stop()` shuts down the listener and is idempotent.
- `port`, `address`, `server_address`, `base_url`/`url`, `httpd`/`server`, and
  `thread` expose lifecycle state. `service` and `store` expose the wrapped
  objects.
- `max_body_bytes` defaults to `MAX_BODY_BYTES` (1 MiB).
- `make_wave_handler(service)` builds the request handler for callers that want
  to supply their own `ThreadingHTTPServer`/`socketserver` instance.

The default listener is loopback on an ephemeral port, suitable for tests and
sidecars. For a public deployment, terminate TLS at a reverse proxy and bind an
explicit private host/port.

## Authentication

Every protected endpoint requires exactly one header:

```http
Authorization: Bearer <role-token>
```

The token is checked by `WaveService`; the adapter does not keep a second copy
of the credentials and does not implement its own token comparison.

| Endpoint | Required role |
|---|---|
| `GET /healthz` | none |
| `POST /v1/wave/jobs` | `submit` |
| `POST /v1/wave/lease` | `worker` |
| `POST /v1/wave/complete` | `worker` |
| `POST /v1/wave/capabilities` | `admin` |

- Missing, malformed, or unknown bearer tokens return `401` with
  `WWW-Authenticate: Bearer realm="wave"`.
- A valid token that lacks the endpoint's role returns `403`.
- Tokens are never echoed in a response, included in an error, written to a
  database, or emitted through the adapter's request logging (which is
  disabled entirely).
- Roles remain exactly the `WaveService` roles. For example, an admin token
  cannot submit or lease a job, and a submit token cannot register a
  capability.

`WaveService` intentionally has no public token-introspection method. To
distinguish an unknown token (`401`) from a known token with the wrong role
(`403`), the adapter calls the facade's internal `_authorize` check for "any
role". This does not bypass or duplicate the service's constant-time role
comparison, but it is the one private facade coupling in the adapter.

## Endpoints

### `GET /healthz`

No authentication. Returns `WaveService.health()` unchanged:

```json
{
  "schema": "nanrouter.wave-store-health.v1",
  "status": "green",
  "schema_version": 1,
  "stores": {"BS0DB": "ok", "MC0DB": "ok"},
  "jobs": {"queued": 0, "leased": 0, "done": 0, "failed": 0, "dead": 0},
  "leases": {"active": 0, "expired": 0, "completed": 0, "failed": 0},
  "native_verified_capabilities": 0
}
```

The report contains counts and store status only; it contains no credential
material.

### `POST /v1/wave/jobs`

Submit role. JSON body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `job_id` | string | yes | Store applies idempotency. |
| `universe_id` | string | yes | |
| `operator_digest` | string | yes | Lowercase SHA-256 hex, validated by the store. |
| `generation` | integer | yes | `>= 0`. |
| `payload` | any JSON value | no | Defaults to `{}` in the store. |
| `now_tick` | integer | no | Default `0`. |
| `kind` | string | no | Default `"wave"`. |
| `operator_id` | string | no | |
| `precision` | string | no | |
| `workspace` | integer | no | Default `0`. |

Success is `200` with `{"job": <job-record>}`. Re-submitting an identical
contract returns the existing job. A different contract for the same
generation, or a stale generation, returns `409`.

### `POST /v1/wave/lease`

Worker role. JSON body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `owner` | string | yes | Lease owner identifier. |
| `now_tick` | integer | no | Default `0`. |
| `lease_ticks` | integer | no | Default `64`; must be `>= 1`. |
| `expected_generation` | integer | no | Restricts leasing to one generation. |
| `max_attempts` | integer | no | Default `8`; must be `>= 1`. |
| `job_id` | string | no | Lease a specific job. |

Success is `200` with `{"job": <leased-job-record>}` or `{"job": null}` when no
job is ready. The leased record includes the opaque `lease_token` and
`lease_epoch` needed by `/complete`.

### `POST /v1/wave/complete`

Worker role. JSON body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `job_id` | string | yes | |
| `lease_token` | string | yes | Token returned by `/lease`. |
| `lease_epoch` | integer | yes | `>= 1`. |
| `result_digest` | string | yes | Lowercase SHA-256 hex, validated by the store. |
| `now_tick` | integer | no | Default `0`. |
| `result_generation` | integer | no | Defaults to the job generation. |
| `lease_owner` | string | no | Enforces owner affinity when supplied. |

Success is `200` with `{"job": <completed-job-record>}`. Stale lease tokens or
epochs, expired leases, unknown jobs, and result conflicts return `409`.

### `POST /v1/wave/capabilities`

Admin role. JSON body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `kernel_id` | string | yes | |
| `runner_id` | string | yes | |
| `verified_digest` | string | yes | Lowercase SHA-256 hex, validated by the store. |
| `precision` | string | yes | |
| `workspace` | integer | no | Default `0`. |
| `epoch` | integer | no | Default `1`; must be `>= 1`. |
| `status` | string | no | Default `"declared"`; store validates the enum. |
| `nanclock_tick` | integer | no | Default `0`. |

Success is `200` with `{"capability": <capability-record>}`. Older epochs or
the same epoch with a different contract return `409`.

## Request and response rules

- Protected endpoints require `Content-Type: application/json`; media-type
  parameters such as `charset=utf-8` are accepted.
- The body must be a UTF-8 JSON object with exactly one `Content-Length`.
  Chunked transfer encoding, content encodings, duplicate JSON keys, and
  non-finite JSON numbers are rejected.
- The default maximum body is 1 MiB (`MAX_BODY_BYTES`). Larger requests receive
  `400`; bodies only slightly over the limit are drained first so the client
  can read the response, while much larger bodies are not read.
- Success responses are always `200`. Endpoint payloads use a single-key
  envelope (`job` or `capability`); health is returned directly.
- Error responses are bounded JSON:

```json
{"error": "request body exceeds 1048576 bytes"}
```

  `429` responses additionally contain `"retryable": true` and a
  `Retry-After: 1` header. Error text is whitespace-collapsed and capped at 320
  characters. Unexpected exceptions never include a traceback, request body,
  headers, or exception message.
- All responses are sent with `Cache-Control: no-store`,
  `X-Content-Type-Options: nosniff`, and `Connection: close`.
- Each connection has a 15-second socket timeout.

## Status mapping

| Status | Meaning |
|---|---|
| `200` | Successful health check or operation. |
| `400` | Invalid content type, malformed/oversized JSON, missing field, wrong field type, or store validation error. |
| `401` | Missing, malformed, or unknown bearer token. |
| `403` | Valid bearer token without the endpoint's required role. |
| `404` | Unknown route. |
| `405` | Known route with the wrong HTTP method; `Allow` names the supported method. |
| `409` | Job/generation/capability conflict, stale or invalid lease state, or SQLite constraint conflict. |
| `429` | SQLite reports the store as locked/busy; retry later. |
| `500` | Unexpected internal failure, with a generic message. |

## Security notes

- The adapter emits no access log of its own. `log_message`/`log_error` are
  disabled because request lines and headers can contain credentials.
- `WaveHttpServer.__repr__` exposes host/port/running state only.
- Role authorization remains constant-time inside `WaveService`; every
  configured role is compared on each check.
- Request size, JSON depth failure (`RecursionError`), duplicate keys, and
  error-message length are bounded. Parser-level errors also use the bounded
  JSON envelope rather than the default HTML page.
- Lease tokens are opaque store-generated completion credentials, not service
  role tokens. They are returned to the worker that leased the job and should
  be treated as secrets by that worker.

## Limitations

- No TLS, client certificates, CORS, or HTTP/2. Use a TLS-terminating reverse
  proxy for untrusted networks.
- No request rate limiting or concurrency cap. `ThreadingHTTPServer` creates one
  thread per connection; `429` is only a store-busy backpressure signal.
- No token rotation, revocation, expiry, or per-universe ACL beyond the
  `WaveService` role tokens.
- No persistent audit log of authorization decisions or requests.
- Only the five routes above are exposed; evidence, fail, lease-expiry,
  operator, feedback, and read/list operations remain facade/store-only.
- No chunked or compressed request bodies.
- No graceful in-flight request drain on `stop()`; daemon handler threads may
  be interrupted during shutdown.
- The `401`/`403` distinction depends on the facade's internal `_authorize`
  method. If that method changes, this adapter must be updated.
- Health is unauthenticated and reveals aggregate job/lease/capability counts.
  Place it behind the reverse proxy if that metadata is sensitive.
- One SQLite store per process is assumed; the adapter adds no distributed
  locking or coordination.

## Tests

```sh
python3 -m unittest tests.test_wave_http -v
```

The suite uses a temporary BS0DB/MC0DB `WaveStore` and real HTTP requests over
an ephemeral loopback port. It covers unauthenticated token-free health, wrong
token rejection (`401`), role mismatch (`403`), the submit/lease/complete happy
path, admin capability registration, oversized and malformed bodies, unknown
routes and wrong methods, conflict (`409`), store-busy (`429`), generic
unexpected failure (`500`), and the absence of service tokens in responses,
health, and logs.
