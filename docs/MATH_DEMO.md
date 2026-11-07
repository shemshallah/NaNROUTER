# End-to-end math demo (P12)

Status: implemented in `tools/run_math_demo.py`; tested by
`tests/test_math_demo.py`.

Run from the repository root:

```bash
python3 tools/run_math_demo.py
python3 tools/run_math_demo.py --json
python3 tools/run_math_demo.py --root /path/to/stores
```

The demo uses two persisted 256-vector leaves, the `::` linker, typed
preflight, the compiled `mth.vector.dot256.f32` plan, NMP packet admission, the
active runner-ring lease, completion, commit, and output-leaf feedback.

The output leaf is stored and bound to the committed packet. The `--json`
report includes the candidate, admission verdict, preflight digest, packet/job
IDs, execution state, result digest, output leaf, and mapping version.

## Honesty boundary

This demo is a **control-plane** demonstration. It does not compute a numerical
dot product in Python. The executor callback returns a deterministic evidence
digest derived from the candidate, admission, plan, and input digests, and the
report explicitly labels it as not a claimed numeric result. A production
runner replaces that callback with the native NaN16 executor while keeping the
same admission, JAHS, lease, NMP, and commit path.

The demo therefore proves state-machine integration, not numerical correctness
of a dot product.
