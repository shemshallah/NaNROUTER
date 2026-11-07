# Point-0 NaN↔binary↔NaN bridge

Status: implemented with 10 tests; this is the stable runner-ring ingress.

## 1. Contract

Clients address **point 0** (`BS0:0` / wire `BSR0` / `nan://GM0:SC0:MC0:BS0:0:HW0:0`). They do not address `R0..R5`. Point 0:

1. accepts a NaN16 frame;
2. encodes a binary transport envelope;
3. asks the single-active ring scheduler for the current slot/epoch;
4. routes to that slot;
5. receives binary result bytes;
6. decodes them back to NaN16.

## 2. Files

- `runner_riddle/point0_bridge.py`
- `tests/test_point0_bridge.py`

## 3. Binary envelope

| Field | Meaning |
|---|---|
| `magic` / `version` | `N0P0` / 1 |
| `request_id` | Unsigned 64-bit idempotency key |
| `word_count` | Number of 64-bit NaN words |
| `payload` | 8 bytes per word, big-endian |
| `digest` | SHA-256 over the v1 header + payload |
| `active_slot` / `epoch` | Internal routing evidence (0..5, epoch ≥ 1) |

The decoder rejects bad magic/version, length mismatch, digest mismatch, invalid epoch, and invalid slot. The public route remains point 0; active slot/epoch are evidence only.

## 4. Tests

```
python3 -m unittest tests.test_point0_bridge -v
Ran 10 tests
OK
```

Covered: exact 64-bit roundtrip; empty/1/65,536-word frames; binary wire roundtrip; corrupt envelope rejection; point-0-only route; router follows the active slot; router follows a cycle to the next slot; no active slot; bad executor bytes; invalid words.

## 5. Limitations

- The bridge frames and routes; it does not execute native math.
- `provenance` is local evidence only; it is not transported in the binary envelope.
- The executor callback is an internal boundary; no TLS/transport is included.
- Slot/epoch routing is only as strong as the scheduler snapshot at call time.
