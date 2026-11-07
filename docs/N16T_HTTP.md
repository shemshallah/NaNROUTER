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

The fixed header plus CRC is 36 bytes; the current Android guest permits a
maximum payload of 65,536 bytes, so the transport frame limit is 65,572 bytes.

## Worker wiring

`N16THttpAdapter` is a bounded opaque handoff. It passes the exact request
bytes to an injected persistent NaN16 worker callback and returns the exact
peer-frame bytes. It does not parse the magic, version, type, session, sequence,
payload, CRC, or state transitions. Those operations must run in the
`n16t_android_guest.nas` / `train_protocol.nas` guest, not in Python.

```python
from runner_riddle import N16THttpAdapter, WaveHttpServer

# n16_guest_exchange must call the persistent NaN16 protocol guest.
n16t = N16THttpAdapter(n16_guest_exchange)
server = WaveHttpServer(service, n16t_adapter=n16t)
server.start()
```

The route requires the existing submit-role bearer token, rejects non-N16T
media types and out-of-range frames, disables request logging, and fails with
503 when no worker is configured. A worker failure or malformed response
returns a bounded 502. The callback receives no bearer token.

The callback must be a real persistent NaN16 guest execution boundary. A
host-side parser, a Python state machine, an NMP JSON adapter, or a point-0
N16B bridge is not a substitute. This HTTP handoff does not claim that a
production NaN16 worker process or remote training service is deployed.
