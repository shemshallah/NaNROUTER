# Point-0 NaN-to-binary-to-NaN bridge and active-runner router

`runner_riddle/point0_bridge.py` implements the stable runner-ring ingress
required by the single-active six-slot design.

Clients address **point 0**, never `MC0:0/R0` through `MC0:0/R5`. Point 0
translates a NaN16 frame to a bounded binary transport envelope, routes the
payload to whichever runner slot the scheduler currently reports as active,
receives the binary result payload, and translates it back to a NaN16 frame.
The active slot and epoch are returned as non-address evidence.

The bridge is a distinct object from the address parser and from the scheduler.
The scheduler chooses the slot; the bridge only frames, validates, and
translates.

## Stable identity

| Name | Value | Meaning |
|---|---|---|
| `POINT_ZERO_ADDRESS` | `nan://GM0:SC0:MC0:BS0:0:HW0:0` | Canonical point-0 root |
| `POINT_ZERO_WIRE` | `BSR0` | Existing zero-based bridge wire identity |
| `POINT_ZERO_LABEL` | `point-0` | Documentation label |

`BSR0` is the existing wire coordinate. The human/display label for point 0 is
`BSR1`; the bridge keeps the zero-based wire identity stable. Point 0 is the
Koyeb `BS0:0` ingress, not another runner slot and not a local head.

The public route string never contains an active-slot identity. A successful
result still has `route == POINT_ZERO_ADDRESS`; the slot and epoch appear only
as separate evidence fields.

## NaN frame

```python
NanFrame(
    words=(...),              # exact unsigned 64-bit integers
    request_id=...,           # unsigned 64-bit integer
    route=POINT_ZERO_ADDRESS,
    provenance=(("source", "bootstrap"),),
)
```

- `words` is normalized to an immutable tuple. Every word must be in
  `0..2**64-1`; booleans, negatives, and values wider than 64 bits are rejected.
- `request_id` must be an unsigned 64-bit integer and is preserved end to end.
- `route` accepts the canonical point-0 address, `BSR0`, `None`, or the empty
  string. `BSR0` and the empty forms normalize to `POINT_ZERO_ADDRESS`. Direct
  `MC0:0/R*` and `NANROUTER-*` routes and foreign roots are rejected.
- `provenance` is local evidence metadata, not transported by the binary
  envelope. It is excluded from frame equality. Decoding adds point-0
  provenance (wire, active slot, epoch).

The v1 bridge accepts only the point-0 root as the route. Address selectors
(`::HW0:1`, object references, and similar) belong to the address resolver and
are not interpreted here; putting a selector in `route` is rejected so that it
cannot smuggle a runner-slot identity into the public route.

## Binary envelope v2

All integers use network byte order (`WIRE_ENDIAN == "big"`), independent of
the host.

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | magic: `b"N16B"` |
| 4 | 1 | version: `2` |
| 5 | 1 | active slot: `0..5`, unsigned byte |
| 6 | 8 | request id: unsigned 64-bit |
| 14 | 8 | epoch: unsigned 64-bit |
| 22 | 4 | `nan_word_count`: number of 64-bit NaN16 words |
| 26 | 1 | `result_status`: bounded status code |
| 27 | 5 | `point_zero`: `b"BS0:0"` stable ingress identity |
| 32 | 32 | SHA-256 digest |
| 64 | N | payload: `N / 8` exact 64-bit words |

The digest is:

```text
SHA-256(
    magic || version || active_slot || request_id_be64 || epoch_be64 ||
    nan_word_count_be32 || result_status_u8 || point_zero_5bytes || payload
)
```

It binds the transport metadata, point-0 identity, word count, result status,
and every payload byte. The bridge rejects a wrong magic, unsupported version,
payload that is not a whole number of 64-bit words, a `nan_word_count` that does
not equal the payload length, a non-canonical point-0 identity, an unknown
status code, an out-of-range slot/epoch, and any digest mismatch. It also
rejects truncated envelopes and envelopes with trailing bytes.

`result_status` is one of:

```text
ok, invalid_descriptor, bad_domain, overflow, saturation, nonconvergence,
insufficient_workspace, stale_generation, unauthorized, cancelled,
budget_exhausted
```

`success`, `invalid`, `stale`, and `budget` are accepted as input aliases and
normalize to their canonical names. A request envelope uses `ok` as its neutral
default; a result envelope carries the executor's actual status.

The hard length bound is `MAX_FRAME_WORDS == 262144` (2 MiB / 8 bytes), therefore
`MAX_PAYLOAD_BYTES == 2097152`. A custom bridge may use a smaller `max_words`
bound. This is a per-frame payload bound, not the guest address space: the
guest maps the full 8 MiB / 1,048,576-word universe and all 32,896 relation
points (`docs/MTH_UNIFIED_SYSTEM.md`).

### Legacy v1 compatibility

Version 1 envelopes remain decodable. The v1 layout is unchanged:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | magic: `b"N16B"` |
| 4 | 1 | version: `1` |
| 5 | 1 | active slot: `0..5` |
| 6 | 8 | request id |
| 14 | 8 | epoch |
| 22 | 4 | payload length in bytes |
| 26 | 32 | SHA-256 digest |
| 58 | N | payload: `N / 8` exact 64-bit words |

A decoded v1 envelope is upgraded in memory with `point_zero="BS0:0"`,
`nan_word_count=length/8`, and `result_status="ok"`. Re-serializing it keeps the
v1 wire layout and the original v1 digest. New envelopes always use v2 unless a
caller explicitly requests `version=LEGACY_VERSION`.

The envelope is a point-0 transport profile. It does not redefine the address
grammar, the six runner slots, or the existing `BSR0` wire coordinate.

## Bridge API

```python
import hashlib

from runner_riddle.point0_bridge import NanFrame, Point0Bridge

bridge = Point0Bridge()
frame = NanFrame(words=(0x0102030405060708,), request_id=42)

envelope = bridge.encode(frame, active_slot=2, epoch=7)
assert envelope.payload == bytes.fromhex("0102030405060708")
assert envelope.length == 8

decoded = bridge.decode(
    envelope,
    expected_active_slot=2,
    expected_epoch=7,
    expected_request_id=42,
    expected_output_digest=hashlib.sha256(envelope.payload).digest(),
)
assert decoded.words == frame.words
assert decoded.request_id == 42
assert decoded.route == "nan://GM0:SC0:MC0:BS0:0:HW0:0"
```

`encode()` defaults to slot `0`, epoch `0`, `result_status="ok"`, and the v2
wire version for standalone codec use. The router always supplies the current
scheduler slot and epoch; a request envelope never accepts them from a client.

`decode()` accepts either a `BinaryEnvelope` or its bytes. The optional
`expected_active_slot`, `expected_epoch`, and `expected_request_id` arguments
turn decoding into a binding check. A mismatched epoch raises
`StaleEnvelopeError`; a mismatched slot raises `InactiveSlotError`.

`expected_result_digest` checks the full result-envelope digest.
`expected_output_digest` checks SHA-256 over the exact result payload (the
output words). Both accept a 32-byte digest or 64-character hex and raise
`ResultDigestMismatchError` on mismatch. `Point0Result.verify_output(...)` and
`Point0Result.output_digest` expose the same output check after routing.

`BinaryEnvelope.create(...)` builds an envelope and computes its digest from the
exact header and payload. `to_bytes()` and `from_bytes()` provide the wire
representation; `from_bytes()` validates before returning. Pass
`version=LEGACY_VERSION` only when a legacy v1 envelope is required.

No host arithmetic is performed on frame words. The bridge only range-checks,
packs, unpacks, and hashes bytes.

## Router API

```python
from runner_riddle.wave_ring_scheduler import WaveRingScheduler
from runner_riddle.point0_bridge import NanFrame, Point0Router


def executor(active_slot, epoch, binary_payload):
    # Stand-in for the active runner's binary transport.  It must return the
    # binary result payload, not a slot or epoch.
    return binary_payload


scheduler = WaveRingScheduler(cycle_ticks=64, now_tick=0)
scheduler.start(0)

router = Point0Router(executor=executor, scheduler=scheduler)
result = router.submit(NanFrame(words=(1, 2, 3), request_id=9))
assert result.route == "nan://GM0:SC0:MC0:BS0:0:HW0:0"
assert (result.active_slot, result.epoch) == (0, 1)

scheduler.cycle(1)
result = router.submit(NanFrame(words=(1, 2, 3), request_id=9))
assert result.route == "nan://GM0:SC0:MC0:BS0:0:HW0:0"
assert (result.active_slot, result.epoch) == (1, 2)
```

`Point0Router` accepts `Point0Router(bridge, scheduler, executor)` or the
convenience form `Point0Router(scheduler, executor)` with a default bridge.

### Executor contract

The executor receives exactly:

```text
(active_slot: int, epoch: int, binary_payload: bytes)
```

`binary_payload` is the envelope payload: a whole number of big-endian 64-bit
words. The return value must be the binary result payload, also a whole number
of big-endian 64-bit words. The router constructs the result envelope itself,
so the executor cannot choose a slot or epoch.

An executor exception propagates unchanged. A non-bytes result, a result that
is not a whole number of words, or an oversized result is rejected. The router
resets its in-flight guard and remains usable after either kind of failure.

### Submission rules

`submit(frame)`:

1. Rejects an oversized frame before the executor is called.
2. Reads the scheduler snapshot and requires `started == true`, exactly one
   active slot, exactly one active slot entry in the inventory, a live epoch,
   and a non-stale heartbeat.
3. Encodes with the current slot and epoch. The caller cannot supply either.
4. Re-reads the scheduler immediately before dispatch. If the epoch or slot
   changed, the envelope is stale and the executor is not called.
5. Calls the executor with the current `(slot, epoch, payload)`.
6. Re-reads the scheduler after the call. If a handoff happened, the result is
   discarded as stale.
7. Builds and validates a result envelope, then returns a `Point0Result`.

`dispatch(envelope)` is the binary retry path for an envelope that already
crossed point 0. It validates the envelope, compares its slot and epoch with
the current scheduler state, and refuses stale or inactive envelopes **before**
calling the executor. It cannot target an inactive slot; it can only succeed
when the envelope names the one current active slot. This is still not a
client-facing slot-selection API; clients use `submit(frame)` and point 0.

Errors:

| Error | Cause |
|---|---|
| `FrameError` | Invalid word, request id, route, or metadata |
| `FrameTooLargeError` | More than `max_words` or `max_payload_bytes` |
| `EnvelopeFormatError` | Bad magic/version/length/digest/layout |
| `StaleEnvelopeError` | Old epoch, stale heartbeat, or no live epoch |
| `InactiveSlotError` | Envelope slot is not the current active slot |
| `NoActiveSlotError` | Scheduler not started, no slot, or not exactly one |
| `RouterBusyError` | Recursive/nested dispatch in the same router |
| `ExecutorResultError` | Executor returned a non-binary or partial word payload |

All are `ValueError` subclasses through `Point0BridgeError`. `StaleEpochError`
and `OversizedFrameError` are aliases for compatibility.

### Result evidence

`Point0Result` exposes:

- `frame` and convenience `words`, `word_count`, `nan_word_count`,
  `request_id`, `route`, `address`, `provenance`;
- `active_slot` and `epoch` as non-address evidence;
- `point_zero`, `result_status`, and `output_digest` (SHA-256 of the exact
  output payload);
- `request_digest` and `result_digest` (32-byte SHA-256 values; `result_digest`
  covers the full result envelope);
- `verify_output(...)` to check an expected output digest;
- `to_dict()` for JSON-safe evidence.

`submit(frame)` and `dispatch(envelope)` accept keyword-only
`expected_result_digest` and/or `expected_output_digest` checks. An executor may
return bytes (status `ok`) or a `Point0ExecutorResult(payload, result_status)`
to report one of the bounded statuses.

`to_dict()["route"]` remains `POINT_ZERO_ADDRESS`. The slot is in
`to_dict()["active_slot"]`, not in the route. There is no `R0..R5` or
`NANROUTER-*` substring in the public route. Envelope evidence contains no
bearer token, API key, or private key material.

## NANNET0 binding persistence

`WaveStore` adds two MC0DB tables without changing `wave_schema=1`:

- `wave_nannet_node` — the current binding per `universe_id`;
- `wave_nannet_node_version` — immutable generation history.

```python
node = store.register_nannet_node(
    universe_id="universe-0",
    node_id="nannet-0",
    node_point=17,                    # 1..255, never a head index
    public_key_fingerprint=fingerprint,
    generation=1,
    status="active",
    route="nan://GM0:SC0:MC0:BS0:0:HW0:0",
    route_digest=route_digest,
    signature=signature_digest,
    nanclock_tick=10,
)
assert store.require_nannet_node("universe-0")["generation"] == 1
assert store.get_nannet_node("universe-0", generation=1)["status"] == "active"
```

The API also provides `get_nannet_node_by_node_id`, `nannet_node_history`,
`list_nannet_nodes`, and `revoke_nannet_node`. Generations are monotonic;
same-generation replay is idempotent only for an identical contract; stale,
conflicting, or duplicate live `node_id`/`node_point` registrations are
rejected. Revocation clears the route. Only public fingerprints and bounded
signature digests are stored — no secret key material.

This table is version/evidence metadata only. It does not create jobs, leases,
capabilities, routes, or a second routing authority; the ring scheduler and
point-0 router remain the only dispatch path.

## Invariants

1. Point 0 is the only public ring address.
2. A client never supplies a slot. `submit` has no slot parameter.
3. Exactly one active slot is required; zero, multiple, draining, or degraded
   active state is refused.
4. A handoff changes the epoch. Old epoch envelopes are rejected, including on
   the binary retry path.
5. An envelope for a non-current slot is rejected before execution.
6. The same point-0 address works before and after a scheduler cycle; only the
   evidence slot/epoch changes.
7. Frame words and request ids round-trip exactly in 64-bit big-endian form.
8. The envelope digest covers the header and payload, so metadata cannot be
   changed without detection.
9. The bridge performs no host mathematics and the router does not compute a
   mathematical result.

## Tests

```sh
python3 -m unittest tests.test_point0_bridge -v
```

The suite covers 0/1/262144-word round trips, boundary lengths, big-endian v2
layout, v1 legacy decode/re-serialize, point-0 identity, `nan_word_count`,
bounded result statuses, bad magic/version/length/digest, truncation/trailing
bytes, expected result/output digests, stable point-0 identity, active-slot
routing, a scheduler cycle reaching the new slot through the same point-0
address, stale/inactive rejection before executor calls, no-slot rejection,
request-id preservation, route-string slot leakage, and secret non-leakage.

## Limitations

- This is an in-process bridge and router. It does not open a socket, authenticate
  a remote client, or deploy Koyeb. The caller's executor stands in for the real
  binary transport to the active runner.
- The executor must obey the `(slot, epoch)` it receives and must return only
  binary result words. The router validates binding and framing, but cannot
  prove what a remote process actually executed.
- The router does not reserve scheduler memory or take a scheduler lease. It
  re-reads the scheduler before and after the executor call and rejects a result
  if the ring moved. A separate supervisor should still prevent a real handoff
  while remote work is live.
- Scheduler state and envelope retry state are not persisted across process
  restarts. Recovery must rebuild the ring and re-submit work with a fresh
  request id.
- The wire envelope is a point-0 profile, not a new replacement for the
  canonical NANNET N16B codec. When that codec is integrated, this envelope
  should remain the point-0 transport wrapper or gain an explicit adapter.
- `NanFrame.provenance` is local evidence; it is not carried in the v1 envelope.
  The route is restricted to the point-0 root; selectors/object resolution stay
  with the address resolver.
- There is no cross-process fencing token. In a multi-process deployment, the
  durable store or runner supervisor must enforce the same epoch binding.
