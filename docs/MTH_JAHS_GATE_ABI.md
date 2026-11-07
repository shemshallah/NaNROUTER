# MTH JAHS handoff-seal gate

Status: source-written and locally executed with the canonical NaN0S toolchain on
2026-11-07. Native fixture passes; CI registration is outside this change.

## 1. Scope

JAHS is the owner's initials and a real runner-ring handoff gate, not a
cosmetic label. It expands to **Just A Handoff Seal**.

`mth/nan16/mth_jahs_gate.nas` is the tiny native check that a runner-side
handoff must pass before a slot may receive the next activation. The
control-plane checkpoint digest binds the same identifier as its domain
separator, so a checkpoint without the JAHS prefix is not a valid handoff
checkpoint.

This change owns only the gate, its native fixture, and this ABI document. The
control-plane integration points (`WaveRingScheduler`, `MthSystem`) are
described in section 5; they are not modified here.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | seal word: the 32-bit NaN16 payload of the canonical 64-bit seal |
| return `r1` | `1` iff the seal is exactly `0x4A414853`; otherwise `0` |
| clobbers | `r1`, `r2`, flags |
| preserves | `r3`-`r15` |

The routine is a leaf: it contains no `CALL`, performs no memory access, and
uses no host mathematics. It is seven instructions in total; callers must treat
`r2` and the flags as scratch.

### Seal constant

The canonical seal is the 64-bit data value:

```
0x000000004A414853
```

A conforming seal has zero high 32 bits. The low 32 bits are the ASCII
cartouche `JAHS`:

| Bits | Value | ASCII |
|---|---|---|
| 31..24 | `0x4A` | `J` |
| 23..16 | `0x41` | `A` |
| 15..8 | `0x48` | `H` |
| 7..0 | `0x53` | `S` |

The NaN16 register ABI carries the 32-bit payload in `r1`; a caller that
decodes a raw word must reject a nonzero high half while framing before it
presents the payload here. The gate then performs an exact 32-bit equality
test, so `0x4A414852` and `0x4A414854` are both rejected.

`0x4A414853` is the numeric ASCII cartouche. It is not the little-endian byte
dump of the string `JAHS`; the control-plane domain separator is the byte string
itself (section 5).

### Building the constant

The kernel builds the constant in `r2` with the two frozen NaN16 half-word
instructions:

```
MOVI  r2,0x4853    ; r2 = (r2 & 0xFFFF) | 0x00004853
MOVHI r2,0x4A41    ; r2 = (r2 & 0xFFFF) | 0x4A410000  -> 0x4A414853
```

`MOVI` writes the low 16 bits and `MOVHI` replaces the high 16 bits, as defined
by `aarch64/android/core/OPS.md` and used by the existing MTH kernels. A caller
builds the same value in `r1` immediately before the call:

```
MOVI  r1,0x4853
MOVHI r1,0x4A41
CALL  @mth_jahs_gate
CMP   r1,r13         ; r13 = 1 in the fixture convention
JMP[NE] @refuse_handoff
```

### Gate body

```
mth_jahs_gate:
  MOVI r2,0x4853
  MOVHI r2,0x4A41
  CMP r1,r2
  MOVI r1,0
  RET[NE]
  MOVI r1,1
  RET
```

`MOVI` does not modify the flags, so `RET[NE]` consumes the `CMP` result after
`r1` has been cleared for the reject path.

## 3. Fixture

`mth/tests/mth_jahs_gate_test.nas` calls the gate with four values and checks
the return exactly:

| Input | Expected |
|---|---|
| `0x4A414853` (`JAHS`) | `1` |
| `0x00000000` | `0` |
| `0x4A414852` (one below) | `0` |
| `0x4A414854` (one above) | `0` |

On success it prints:

```
MTH JAHS GATE PASS
```

The fixture itself uses `CALL` and the shared `PUTC` serial helper. The leaf
restriction applies to `mth_jahs_gate`, not to the test harness.

## 4. Local canonical run

From the repository root:

```
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_jahs_gate_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/jahs.nan
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=check \
  /data/data/com.termux/files/usr/tmp/opencode/jahs.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/jahs.nan \
  --steps 2000000 --serial
```

Observed:

```
words 56
check: 0 mismatches
[nan_cli] nan-text: 201 steps, rc=3, pc=31, trap=''
MTH JAHS GATE PASS
exit=0
```

`rc=3` is `NAN_HALTED`; the trap string is empty. The image is 56 NaN16 words
(2,203 bytes of emitted `.nan` text).

## 5. Runner-ring integration contract

### Handoff sequence

Every runner-ring handoff must perform the native check before activating the
next slot:

1. drain leases and release the old slot's working memory;
2. compute the checkpoint digest with the JAHS domain separator;
3. put `0x4A414853` in `r1` and call `mth_jahs_gate`;
4. activate the next slot only when `r1 == 1`;
5. on `r1 == 0`, refuse activation and keep the old slot drained/degraded
   according to the control-plane policy. A failed seal must not be logged and
   bypassed.

### Control-plane domain separator

The canonical domain separator is the four ASCII bytes `4A 41 48 53` followed
by a NUL byte, i.e. `b"JAHS\0"`. The checkpoint digest material is:

```
JAHS\0<slot_id>\0<epoch>\0<tick>\0<previous_checkpoint_digest>
```

encoded as UTF-8/ASCII and hashed with SHA-256 to lowercase hex. This matches
the control-plane implementation:

```python
material = f"JAHS\0{slot.slot_id}\0{self._epoch}\0{tick}\0{prior}".encode("utf-8")
digest = hashlib.sha256(material).hexdigest()
```

The scheduler snapshot exposes the seal as `jahs.seal == "JAHS"` and
`jahs.name == "Just A Handoff Seal"`; each `last_checkpoint` records
`jahs == "JAHS"`. `MthSystem.lease` rejects an active ring whose snapshot is
missing that seal. These are the shared control-plane integration points; this
change supplies the native gate they name.

The native numeric constant and the digest separator describe the same
identifier but are not interchangeable byte encodings: `r1` carries the numeric
ASCII cartouche `0x4A414853`, while the digest is prefixed with the literal
ASCII bytes `JAHS` and a NUL.

## 6. Limitations

- The gate is an exact equality check, not a MAC. It proves that the caller
  presented the handoff seal word; it does not authenticate the caller.
- The register ABI carries only the low 32 bits. A caller decoding a full
  64-bit word must enforce the zero high half and NaN word framing before the
  call; the gate cannot inspect bits it never receives.
- The gate does not inspect or canonicalize NaN face classes or any memory
  word. It seals the numeric handoff token only.
- The gate clobbers `r2` and the flags. A caller that needs either across the
  handoff check must save it first.
- No constant-time or side-channel claim is made. The check is a public
  domain-separated handoff gate, not a secret-key operation.
