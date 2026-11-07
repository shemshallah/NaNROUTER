# N16T HTTP worker handoff

Android's N16T transport posts the guest-built binary frame to `POST /n16t`
using `Content-Type: application/x-n16t`. This route is distinct from both
`/v1/point0` (N16B 64-bit-word envelopes) and the JSON NMP routes.

The wire frame is owned by the NaN16 guest:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | ASCII `N16T` magic |
| 4 | 2 | version (little-endian; version 1) |
| 6 | 2 | message type (little-endian) |
| 8 | 16 | opaque session identifier |
| 24 | 4 | sequence number (little-endian) |
| 28 | 4 | payload length (little-endian) |
| 32 | N | payload |
| 32+N | 4 | CRC-32/IEEE (little-endian) |

The fixed header plus CRC is 36 bytes; the Android guest permits a maximum
payload of 65,536 bytes, so the transport frame limit is 65,572 bytes.

## Persistent NaN16 execution

`N16TGuestPool` loads the canonical NaN16 C execution core, a compiled
`n16t_android_guest.nas` image, and its assembler label map. Each active
128-bit session is assigned a persistent VM. The host uses the session bytes
only as an opaque VM-affinity key; CRC, replay, session ownership, message type,
logical routing, and state transitions are validated by the guest entry
`n16_server_exchange`.

The pool supports bounded concurrent sessions. Each VM serializes its own
state transitions; different sessions can execute in parallel. At capacity, the pool refuses new sessions rather than evicting a live
protocol state and erasing its replay cursor. A guest-validated CLOSE response
signals the pool to destroy that session VM and reclaim its slot. The HTTP adapter passes the exact request bytes to this guest pool
and returns the exact guest-built response bytes.

Configure the runtime artifacts with:

- `NAN16_LIBRARY`: path to the shared library built from the NaN0S
  `aarch64/android/core` C sources.
- `N16T_GUEST_IMAGE`: `nan-text` image assembled from
  `src/nannet/n16t_android_guest.nas`.
- `N16T_GUEST_LABELS`: label map emitted by the same assembler invocation.

Example server wiring:

```python
from runner_riddle import N16TGuestPool, N16THttpAdapter, WaveHttpServer

guest_pool = N16TGuestPool.from_env(max_sessions=8)
n16t = N16THttpAdapter(guest_pool.exchange)
server = WaveHttpServer(service, n16t_adapter=n16t)
try:
    server.start()
    # Run the service's normal wait/shutdown loop here.
finally:
    server.stop()
    guest_pool.close()
```

The guest currently implements the server-side HELLO/CAPABILITIES handshake
and CLOSE response. CAPABILITIES carries logical portal point 1 in its first
two little-endian bytes; the remaining six bytes are reserved and zero. This
does **not** advertise corpus ingestion, training, candidate evaluation, or
merge capabilities. Other message types fail closed until their NaN16 guest
handlers and NMP worker handoff are implemented.

## HTTP security and protocol boundaries

The route requires the existing submit-role bearer token, rejects non-N16T
media types and out-of-range frames, disables request logging, and fails with
503 when no worker is configured. A guest failure or malformed response
returns a bounded 502. The callback receives no bearer token.

No host-side N16T parser, Python state machine, NMP JSON reinterpretation, or
point-0 N16B bridge is used. The N16T guest runtime is now executable and
covered by a native-runtime CI job; the remote training worker and N16T-to-NMP
corpus/job handoff remain unfinished.
