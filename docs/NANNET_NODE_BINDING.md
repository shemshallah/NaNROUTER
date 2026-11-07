# Per-universe NANNET node binding

Status: binding contract and registry implemented; transport/HTTP integration is still pending.

## 1. Rule

Each universe has exactly **one** logical NANNET node:

```
255 local heads + 1 NANNET node = 256 ring positions
```

The NANNET node is not a head. It is the universe’s single network endpoint/port. It does not own wave state, compute mathematics, or receive a learning ACL.

## 2. Files

- `runner_riddle/wave_node.py` — `NannetNodeBinding` and `NannetNodeRegistry`.
- `spec/nannet-node.schema.json` — machine-readable binding.
- `tests/test_wave_node.py` — 8 tests.

## 3. Binding fields

| Field | Meaning |
|---|---|
| `universe_id` | The one universe owning this node. |
| `node_id` | Stable node identity. |
| `node_point` | 1..255 NANNET point; never a local head index. |
| `public_key_fingerprint` | 64 lowercase hex characters. |
| `generation` | Monotonic binding generation. |
| `status` | `declared`, `active`, `degraded`, or `revoked`. |
| `route` | Signed route envelope; empty when revoked. |

## 4. Registry guarantees

- One binding per `universe_id`.
- One binding per `node_id` and per `node_point`.
- Identical re-registration is idempotent.
- Revocation advances the generation and clears the route.
- No secret key material is stored in the binding.

## 5. Test evidence

```
python3 -m unittest tests.test_wave_node -v
Ran 8 tests
OK
```

## 6. Next gates

1. Persist bindings in MC0DB alongside the wave capability registry.
2. Add the authenticated NANNET HTTP handshake and in/out routes.
3. Join the binding to `spec/ring-255.json` port position 255.
4. Add Koyeb volume-registry health checks.
5. Keep the node outside head training and head ACLs.
