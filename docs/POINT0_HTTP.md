# Point-0 HTTP ingress

`runner_riddle/point0_http.py` is a Python-standard-library HTTP adapter for the
stable point-0 runner ingress. It is a transport wrapper around the existing
`Point0Router` / `Point0Bridge` / `WaveRingScheduler` stack; it adds no routing,
scheduler, or mathematics logic.

The public route is always:

| Name | Value |
|---|---|
| canonical address | `nan://GM0:SC0:MC0:BS0:0:HW0:0` |
| wire identity | `BSR0` |
| point identity | `BS0:0` |
| HTTP endpoint | `POST /v1/point0` |

Clients never send `MC0:0/R0`..`MC0:0/R5`, `NANROUTER-0`..`NANROUTER-5`, or a
foreign/selector route. Those requests receive a bounded `400` response. The
active slot and epoch appear only as numeric evidence in successful responses;
they are never part of the route string and are never selected by the client.

## Files

| File | Role |
|---|---|
| `runner_riddle/point0_http.py` | injectable request adapter and optional bounded server |
| `tests/test_point0_http.py` | no-socket request tests plus one optional loopback test |
| `docs/POINT0_HTTP.md` | this document |

`runner_riddle/point0_bridge.py`, `runner_riddle/wave_ring_scheduler.py`,
`runner_riddle/wave_http.py`, and `runner_riddle/__init__.py` are not modified.
Import the adapter directly from `runner_riddle.point0_http`.

## Construction

The adapter takes an existing `Point0Router` and `WaveService`:

```python
from runner_riddle.point0_bridge import Point0Router
from runner_riddle.point0_http import Point0HttpAdapter, POINT0_PATH
from runner_riddle.wave_ring_scheduler import WaveRingScheduler
from runner_riddle.wave_service import WaveService

scheduler = WaveRingScheduler(cycle_ticks=64, now_tick=0)
scheduler.start(0)

router = Point0Router(scheduler, executor)   # existing bridge/router contract
adapter = Point0HttpAdapter(router, service)

response = adapter.handle(
    "POST",
    POINT0_PATH,
    {
        "Content-Type": "application/json",
        "Content-Length": "40",
        "Authorization": "Bearer <submit-token>",
    },
    b'{"request_id":1,"words":[1,2,3]}',
)
```

The constructor validates that:

- `router.submit(frame)` is callable;
- `router.scheduler.snapshot()` is callable;
- `service._authorize(token, roles)` is the existing `WaveService` check;
- `max_body_bytes` is between `1` and `MAX_BODY_BYTES`;
- `max_words` is between `0` and `MAX_WORDS` and does not exceed the router
  bridge's own bound.

The adapter stores no tokens and keeps no second token digest. Authentication
is delegated to the facade exactly as in `WaveService`.

## Authentication

Every request requires the existing bearer style:

```http
Authorization: Bearer <role-token>
```

The default required role is `submit`. A caller may construct the adapter with
`role="worker"` or `role="admin"` if a deployment uses a different facade role,
but the token is always checked by `WaveService._authorize`.

| Condition | Status | Notes |
|---|---|---|
| missing header | `401` | `WWW-Authenticate: Bearer realm="wave"` |
| malformed or duplicate header | `401` | same challenge |
| unknown token | `401` | same challenge |
| known token without the required role | `403` | role mismatch is distinct |

Tokens are never echoed in a response body or header, never written to a log,
and never included in `repr(adapter)`. The adapter emits no access log at all.

## JSON framing

Request `Content-Type: application/json` (media-type parameters such as
`charset=utf-8` are accepted). The body must be one UTF-8 JSON object with:

| Field | Type | Required | Notes |
|---|---|---|---|
| `route` | string | no | only `nan://GM0:SC0:MC0:BS0:0:HW0:0`, `BSR0`, `null`, or empty; default point 0 |
| `request_id` | integer | yes | unsigned 64-bit |
| `words` | array | yes | zero or more unsigned 64-bit integers |

Unknown fields are rejected. Client-supplied routing evidence fields
(`active_slot`, `slot`, `slot_id`, `runner`, `runner_id`, `alias`, `epoch`) are
rejected with `400` before the router is called. Duplicate JSON keys,
non-finite numbers, invalid UTF-8, and non-object bodies are also rejected.

The adapter constructs a `NanFrame` and calls `router.submit(frame)`. It does
not encode or choose a slot itself.

A successful JSON response is `200`:

```json
{
  "schema": "nanrouter.point0-http.v1",
  "route": "nan://GM0:SC0:MC0:BS0:0:HW0:0",
  "point_zero": "BS0:0",
  "wire": "BSR0",
  "request_id": 1,
  "words": [1, 2, 3],
  "word_count": 3,
  "active_slot": 0,
  "epoch": 1,
  "jahs": {
    "seal": "JAHS",
    "name": "Just A Handoff Seal",
    "epoch": 1
  },
  "request_digest": "<64 hex characters>",
  "result_digest": "<64 hex characters>"
}
```

`route` is always the stable point-0 address. `active_slot` and `epoch` are
numeric evidence only. `jahs` is copied from the scheduler snapshot, and the
adapter refuses to render a success if the snapshot no longer matches the
slot/epoch that actually executed the frame.

## Binary framing

Request `Content-Type: application/octet-stream` (also
`application/vnd.nan16.words` or `application/x-nan16`). The body is a raw
sequence of big-endian unsigned 64-bit words. Metadata travels in headers:

| Header | Required | Meaning |
|---|---|---|
| `X-NaN-Request-Id` | yes | unsigned 64-bit decimal request id |
| `X-NaN-Route` | no | point-0 address or `BSR0`; default point 0 |

The binary mode intentionally uses a raw word payload, not the slot-bearing
`BinaryEnvelope` v1 header. That keeps the client unable to supply
`active_slot` or `epoch`; the adapter internally builds an envelope to reuse
`Point0Bridge` validation, then submits a `NanFrame` through the router.
Client-supplied `X-NaN-Active-Slot`, `X-NaN-Epoch`, `X-NaN-Slot`,
`X-NaN-Alias`, and `X-NaN-Runner` headers are rejected with `400`.

A successful binary response is `200` with the result words as the body and
the same route/evidence in headers:

```text
Content-Type: application/octet-stream
X-NaN-Route: nan://GM0:SC0:MC0:BS0:0:HW0:0
X-NaN-Wire: BSR0
X-NaN-Request-Id: 1
X-NaN-Word-Count: 3
X-NaN-Active-Slot: 0
X-NaN-Epoch: 1
X-NaN-JAHS: JAHS
X-NaN-Request-Digest: <64 hex characters>
X-NaN-Result-Digest: <64 hex characters>
```

An empty binary body is a valid zero-word frame when `X-NaN-Request-Id` is
present.

## Bounds and framing rules

| Bound | Value |
|---|---:|
| `MAX_BODY_BYTES` / `MAX_REQUEST_BYTES` | `1_048_576` (1 MiB) |
| `MAX_WORDS` / `MAX_FRAME_WORDS` | `131_072` |
| `WORD_BYTES` | `8` |
| `MAX_PAYLOAD_BYTES` | `1_048_576` |

- Every request must carry exactly one decimal `Content-Length`; missing,
  duplicate, malformed, or mismatched values are `400`.
- A body larger than the configured HTTP bound is rejected before parsing.
  Binary bodies must also be a whole number of 8-byte words and are capped at
  `131_072` words.
- JSON arrays are capped at `131_072` words independently of the HTTP body
  size. The word limit is inclusive.
- Chunked transfer encoding and non-identity content encodings are rejected.
- Error text is whitespace-collapsed and capped at 320 characters. Responses
  carry `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`.

No host arithmetic is performed on frame words. They are range-checked,
packed, unpacked, hashed, and transported exactly as 64-bit values.

## Evidence and JAHS

After `router.submit()` returns, the adapter reads the scheduler snapshot once
for evidence:

- `active_slot` and `epoch` must equal the values that produced the result;
- `stale` must be false;
- `jahs.seal` must be exactly `"JAHS"` ("Just A Handoff Seal").

If the seal is missing, or the ring advanced between execution and response
rendering, the request fails with `409` (ring advanced) or `503` (no active
slot / missing seal). The router itself still owns active-slot selection,
epoch binding, and the JAHS gate; the adapter only refuses to present stale
evidence.

## Status mapping

| Status | Meaning |
|---|---|
| `200` | Frame executed and result rendered |
| `400` | invalid route, direct-slot addressing, client slot/epoch fields, bad content type, bad frame, oversized body, bad words |
| `401` | missing, malformed, or unknown bearer token |
| `403` | known token without the required role |
| `404` | unknown HTTP path |
| `405` | wrong method; `Allow: POST` |
| `409` | stale epoch/heartbeat, inactive slot, or ring advanced during the request |
| `429` | router busy; `Retry-After: 1` |
| `502` | active runner returned an invalid binary result |
| `503` | no active slot, missing JAHS seal, or unavailable scheduler snapshot |
| `500` | unexpected internal failure with a generic, token-free message |

## Optional server

`Point0HttpServer` is an optional lifecycle wrapper around a
`ThreadingHTTPServer`. It defaults to loopback and an ephemeral port:

```python
from runner_riddle.point0_http import Point0HttpServer

with Point0HttpServer(adapter) as server:
    print(server.base_url)   # http://127.0.0.1:<ephemeral-port>
```

`start(host=None, port=None)` returns the server; `stop()` is idempotent and
joins the daemon thread. `port`, `address`, `server_address`, `base_url`/`url`,
`httpd`/`server`, and `thread` expose lifecycle state. The server keeps the
same 1 MiB body bound and 15-second socket timeout. It is intended for tests,
sidecars, and a TLS-terminating reverse proxy, not for direct public exposure.

`make_point0_handler(adapter, max_body_bytes=None)` returns the handler class
for callers that already own a `ThreadingHTTPServer`/`socketserver` instance.

The pure `adapter.handle(method, path, headers, body)` core needs no socket and
is the recommended test seam.

## Security notes

- The adapter rejects direct slot routes and client-supplied slot/epoch
  evidence before dispatch.
- Service tokens are checked only by `WaveService`; the adapter keeps none.
- No response or log contains an `Authorization` value, service token, or
  request body. Unexpected exceptions become a generic `500`.
- Parser-level errors use the same bounded JSON error envelope instead of the
  default HTML page, so the raw request line is never echoed.
- Request logging is disabled because request lines and headers may contain
  credentials.
- The optional server binds loopback by default and has no TLS, CORS, HTTP/2,
  or rate limiting. Put a TLS-terminating reverse proxy in front of it for any
  non-local deployment.

## Tests

```sh
python3 -m unittest tests.test_point0_http -v
```

The suite uses a real `WaveService`, a real `WaveRingScheduler`, a real
`Point0Router`, and temporary SQLite BS0DB/MC0DB files. Most requests go
through `Point0HttpAdapter.handle` without opening a port. Coverage includes:

- a valid JSON round trip and the same point-0 route across a scheduler cycle;
- binary word framing and evidence headers;
- the exact 131,072-word and 1 MiB boundaries;
- direct `MC0:0/R*` / `NANROUTER-*` route rejection in the body, URL, and
  headers;
- client-supplied slot/epoch/alias field rejection;
- oversized bodies, oversized word arrays, bad content types, bad JSON,
  duplicate keys, bad lengths, and bad binary framing;
- missing, malformed, unknown, and wrong-role bearer tokens;
- stale epoch rejection before the executor is called;
- JAHS seal presence and missing-seal rejection;
- token-free rendered responses and an empty log stream;
- one optional loopback HTTP round trip.

Local result: `Ran 15 tests ... OK`.

## Limitations

- The adapter does not accept the slot-bearing `BinaryEnvelope` v1 wire body
  from clients. That envelope remains the internal bridge transport and the
  router's `dispatch()` retry path; exposing it over HTTP would let a client
  name a slot and is deliberately out of scope.
- The executor still stands in for the real active runner. The adapter can
  validate framing and binding, but cannot prove what a remote process ran.
- Scheduler state, active epochs, and request ids are not persisted across
  process restarts.
- There is no rate limiting, authentication token rotation, per-universe ACL,
  or audit log.
- The optional server is HTTP/1.1 only and relies on a reverse proxy for TLS.
- The package `__init__.py` is shared and was not modified, so this module is
  imported from `runner_riddle.point0_http`, not re-exported at package level.
