# MTH native preflight gate

Status: source-written and locally executed PASS (336 steps); dedicated CI
workflow `.github/workflows/native-preflight-gate.yml` added.

## ABI

`mth/nan16/mth_preflight_gate.nas` is the NaN16 execution-authorization gate.
It does not perform host semantic evaluation.

| Register | Meaning |
|---|---|
| `r1` | candidate descriptor, 22 words |
| `r2` | authoritative rule descriptor, 17 words |
| `r3` | result word, written on every exit |
| return | `0=ALLOW`; nonzero typed denial |

Candidate words: ABI, rule epoch, lhs/rhs/out type, lhs/rhs domain, lhs/rhs
dimension, candidate rule epoch, required/available capabilities, proof level,
enabled, and an **8-word (256-bit) rule digest** (words 14..21).

Rule words: ABI, epoch, lhs/rhs/out type, domain, shape policy
(`0=any`, `1=equal dimensions`), minimum proof level, enabled, and an
**8-word digest** (words 9..16).

Statuses: `0 ALLOW`, `1 ABI`, `2 STALE_EPOCH`, `3 SIGNATURE`, `4 DOMAIN`,
`5 SHAPE`, `6 CAPABILITY`, `7 PROOF`, `8 DISABLED`, `9 RULE_DIGEST`.

Capability check is `(required & available) == required`. A successful gate is
scoped to the exact rule epoch and full 256-bit digest; the caller must bind
the status and digest into NMP/lease admission. The gate does not replace ACL,
numerical definedness, proof verification, or runner capacity.

## Fixture

`mth/tests/mth_preflight_gate_test.nas` checks acceptance, ABI/type/domain/
shape/capability/proof/disabled/digest paths, and stale-epoch rejection.

Local canonical run:

```
MTH PREFLIGHT GATE PASS
336 steps, rc=3/HALT
```

The dedicated workflow assembles and runs the fixture with the canonical NaN0S
toolchain. The unified native workflow also executes it; the unified 124-step
run is pending.
