# NaNVerse zero-point translation fabric

Status: **implemented in `runner_riddle/point_fabric.py` and mounted on the
BS0:0 HTTP service.** It is a transport/control-plane fabric; it does not
evaluate NaN words, train a model, or replace the HERMES lease authority.

## Topology

```text
HW0:0   Bootstrap hardware root / network port
HW1:0   Android endpoint (paired-device only)
HW2:0   HERMES endpoint (paired-device only)
HW3:0   CLOCKED endpoint (paired-device only)
HW4:0   WordNet universe (reserved, never publicly allocated)
HW5:0..HW255:0   registered general hardware nodes
```

Each zero point runs one `PointTranslationModule`. The module has a bounded
inbox, receives exact NaN16DE words, records nanclock tick and frame evidence,
and either serves its local consumer or forwards the frame to the central
`CentralPointFabric`.

The central fabric monitors every registered zero point and routes frames in
NaN space. `HW0:0` is the network port: frames addressed to `HW0:0` are
egress, frames whose source is `HW0:0` are ingress. Frames to an unregistered
general point are durably pending and are replayed when that point registers.

## Address form

```text
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW2:0
```

The zero point is `HWn:0`. Local runner-ring heads are a separate selector:

```text
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0::HW0:1-255
```

See `spec/address-grammar.md` for the apex-layered grammar and the legacy
normalization rule.

## NaN16DE word

A frame carries one exact 8-byte NaN16DE word:

| Bytes | Field | Byte order |
|---|---|---|
| 0..1 | far NaN head | big-endian |
| 2..5 | payload | little-endian |
| 6..7 | near NaN head | little-endian |

Legal heads are `0x7FF1`, `0xFFF1`, `0x7FF8`, `0xFFF8`. The fabric validates
only the structural head/range rules and preserves the bytes exactly. Boolean
or arithmetic semantics remain with the native NaN16 guest that consumes the
word.

## Transport frame

The zero-point frame has a bounded binary form and a JSON adapter:

```text
magic "NPF1" | version u8 | source u8 | destination u8 | kind_len u8
| request_id u64 BE | nanclock_tick u64 BE | acl_digest 32 bytes
| NaN16DE word 8 bytes | kind (1..64 ASCII) | SHA-256 digest 32 bytes
```

The digest covers every preceding byte. A tampered, truncated, oversized, or
unknown-version frame is rejected before routing.

`acl_digest` is SHA-256 hex evidence of the caller's authorization context. It
is not a substitute for the portal token, pairing signature, lease, or route
ACL check.

## HTTP API

All endpoints require the worker token, a dedicated `RIDDLE_FABRIC_TOKEN`, or
(for `HW2:0` only) the existing HERMES portal delegation bearer.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/fabric/points` | central monitor: every point, queues, routes, journal |
| `GET` | `/v1/fabric/points/{hw}` | one zero-point monitor |
| `POST` | `/v1/fabric/intake` | intake a JSON frame at the central fabric |
| `POST` | `/v1/fabric/route` | alias of intake |
| `POST` | `/v1/fabric/points/{hw}/register` | register/activate a general point |
| `POST` | `/v1/fabric/points/{hw}/heartbeat` | liveness without discarding inbox |
| `POST` | `/v1/fabric/points/{hw}/drain` | pop up to `limit` frames for a point |

JSON frame:

```json
{
  "request_id": 11,
  "source_hw": 5,
  "destination_hw": 2,
  "nanclock_tick": 9,
  "kind": "hermes.nan",
  "acl_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "word_hex": "7ff112345678f8ff"
}
```

A `POST /v1/fabric/intake` response is either `central_status=delivered` (the
destination zero point inbox accepted it) or `central_status=pending` (the
destination is an unregistered general point). Reserved fixed points
`HW1:0`..`HW4:0` fail closed until their paired-device/WordNet activation is
explicitly granted.

Drain response:

```json
{
  "schema": "nanrouter.zero-point-drain.v1",
  "endpoint": "HW2:0",
  "count": 1,
  "frames": [
    {
      "frame_id": "<sha256>",
      "source_hw": 5,
      "destination_hw": 2,
      "kind": "hermes.nan",
      "word": {"raw_hex": "7ff112345678f8ff"},
      "frame_hex": "<full NPF1 frame>"
    }
  ]
}
```

## HERMES in/out

HERMES is the zero point `HW2:0`:

1. HERMES drains `POST /v1/fabric/points/2/drain` to receive NaN IN.
2. It submits a frame with `source_hw=2`, `destination_hw=0` to speak NaN OUT
   through the network port. Other destinations route to their registered
   zero points.
3. HERMES still obtains its per-installation lease/receipt from the existing
   `/v1/hermes/leases/*` authority. The fabric is a transport path, not a
   second lease issuer.

## Persistence

When `RIDDLE_FABRIC_DB` is set (default
`$RIDDLE_DATA_DIR/point-fabric.sqlite`), every pending/delivered frame is
journaled with SQLite WAL + `synchronous=FULL`. A restart restores pending
frames and replays them when the destination registers. Keep this file on the
persistent `/data` volume.

Disable the fabric with `RIDDLE_FABRIC_ENABLED=0`; the rest of the BS0:0
control plane continues to operate.

## Tests

```sh
python3 -m unittest tests.test_point_fabric tests.test_address_v2 -v
```

Coverage includes exact NaN16DE byte order, illegal heads, frame digest
tampering, per-point inbox bounds, HW5 -> HW2 delivery, HERMES -> HW0 egress,
pending-then-register delivery, reserved-point rejection, authorization, and
durable pending-frame recovery across a restart.
