# NaNLMind wave adapter contract (R9)

Status: typed adapter descriptor and validation implemented; no model adapter is enabled and no LM benefit is claimed.

## 1. Purpose

The R9 adapter is the only boundary between the wave subsystem and a language model. It is deliberately small:

```
h_combined = h_base + beta * C u
```

where `h_base` is the frozen base model state, `u` is the bounded ring/readout state, `C` is a typed decode map, and `beta` is a small residual scale. The adapter contract validates whether such a module may be enabled; it does not compute the residual and does not claim an improvement.

## 2. Files

- `runner_riddle/wave_adapter.py` — `WaveAdapterConfig` validation and JSON round trip.
- `spec/wave-adapter.schema.json` — machine-readable descriptor.
- `tests/test_wave_adapter.py` — 7 tests.

## 3. Required fields

| Field | Meaning |
|---|---|
| `adapter_id` | Stable adapter identity. |
| `universe_id` | The universe that owns the state. |
| `base_model_id` | Frozen base model identity. |
| `readout_dim` | 1..256; the ring has 255 heads + 1 NANNET port. |
| `residual_scale` | `beta` in `[0,1]`. |
| `mode` | `spectral_filter`, `ring_readout`, `memory_match`, or `product_residual`. |
| `enabled` | Default false. |
| `evidence_level` | Declared through promoted; only `ablation_passed` may enable. |
| `ablations` | Required experiment labels: void, ring, product, real/complex, phase/magnitude, fold. |
| `operator_digest` | Optional 64-hex operator digest. |

## 4. Safety rules

1. Disabled by default.
2. An enabled adapter requires `evidence_level="ablation_passed"` and a nonzero `residual_scale`.
3. No adapter is enabled by a training-loss claim alone.
4. The adapter does not own the base model, the canonical universe, or the route cache.
5. A missing or unknown schema/mode/ablation is rejected.
6. The adapter contract computes no host mathematics; the residual operation must be composed from verified NaN16 kernels.

## 5. Test evidence

```
python3 -m unittest tests.test_wave_adapter -v
Ran 7 tests
OK
```

## 6. Next gates

1. Implement the bounded residual composition as a NaN16 operation graph.
2. Run the frozen-base ablation matrix with parameter/compute-matched baselines.
3. Enable only if held-out improvement is reproducible and the cost is justified.
4. Record the adapter digest and evidence level in MC0DB.
