# Unified MTH system — full 8 MiB guest map and cross-repo catalog

**Status:** implemented locally. The host map is exhaustive over all 256 pages
and all 32,896 relation points; the native NaN16 fixture passes in 12,916,386
guest steps. The unified catalog is green against the fetched `origin/main`
contracts of the sibling NaN repositories. This is not a CI-verification claim
for the new kernel and not a live NANNET0 deployment claim.

## 1. The correction

There is no page-size limit. The guest address space maps the **entire 8 MiB
universe**:

```text
8 MiB = 256 logical pages x 32 KiB
      = 1,048,576 NaN16 words (8 bytes each)
```

The `guest_budget` (2 MiB / 262,144 words by default) is a **workspace
admission budget**, not the guest's addressable span and not a page-size cap.
The 32 KiB page is the logical unit of the fixed 8 MiB universe. A deployment
may choose a smaller workspace budget without shrinking the universe map; the
1 MiB and 512 KiB profiles remain compatibility modes.

The earlier P13 "GLT page-limit enforcement" gate was removed. It described a
limit that does not exist.

## 2. Canonical page map

| Guest pages | Content |
|---|---|
| `0..254` | canonical real heads `1..255` (ring head index `0..254`) |
| `255` | canonical head `0`, the single NANNET0 control point |

NANNET0 has one identity and three explicit aliases:

```text
head 0 = page 255 = ring position 255 = HW0:0
```

The page descriptor covers all 4,096 words of every page, including pages that
do not currently hold relation records.

## 3. Relation points and NANNET routing

There are 32,896 canonical relation points:

```text
256 fixed heads        = heads 0..255
32,640 mirror pairs    = canonical cells 256..32,895
```

The mapping law is deterministic:

```text
head 0          -> page 255, word 0
head 1..255     -> page head-1, word 0
mirror pair n   -> page n % 255,
                   word 3840 + 2*(n // 255)
guest word      = page * 4096 + word
```

Each real-head page reserves words `3840..4095` for 128 two-word mirror-pair
records. That is exactly `255 x 128 = 32,640` records; the NANNET0 page holds
no mirror records. Every page and every relation point is addressable through
the same route root:

```text
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0
  ::HW0:0                 NANNET0
  ::HW0:7                 fixed head
  ::HW0:MP123             mirror pair
  ::HW0:MP123::L3         layer-qualified relation point
```

The route is an address, not a truth claim. It does not execute a kernel,
authorize a merge, or prove a relation.

## 3.1 Physical mirror-memory profile

The same 8 MiB universe also has a physical mirror profile:
`spec/mirror-memory.v1.json`.

```text
bytes 0..32767      256 head records x 128 B (head 0 = NANNET0)
bytes 32768..8388607 32,640 pair records x 256 B
pair id 1..32640    1 + a*(511-a)/2 + (b-a-1), a < b
lane 0 +0          26 f32 residuals + typed fields
lane 1 +128        mirror residual lane
```

This is not a second universe and not a second allocation. The route view in
`spec/universe-map.json` and the physical mirror profile are two projections of
the same 8 MiB object. Round 023/026/027 use the physical profile; NANNET point
addressing uses the route view. A deployment must select one physical writer
profile and never overlay both writers simultaneously.

See `docs/MIRROR_MEMORY_LAYOUT.md` and
`docs/ROUNDS_023_027_INTEGRATION.md`. Round 028’s external shared-composition
experiment is recorded separately in `docs/ROUND_028_SEMANTIC_LEARNING.md`; it
is not a native production kernel. Round 032’s sparse retrieval experiment is
recorded in `docs/ROUND_032_RETRIEVAL.md`; its conventional hash index is
faster, so the mirror geometry remains a directional/cycle state substrate,
not a universal lookup replacement. Round 033’s episodic copy result is recorded in
`docs/ROUND_033_GENERATIVE_RETRIEVAL.md`: exact retrieval-and-copy reaches
886/900 held-out episodes, while matched free-form byte LMs remain tied at
about 3.6748 bits/byte and incoherent. The geometry is therefore being used as
gauge-invariant episodic transport, not as a proven replacement for the
generative decoder.

Rounds 034–036 are recorded in `docs/ROUNDS_034_036_GENERATION.md`:
copy-or-abstain reaches 99% accept/abstain but degrades under untrained
6-character corruption; recursive typed composition is exact on the tested
3-hop paths; and the neural multi-source generator is restricted to normalized
entity slots, with contradiction and four-hop stress failures. None is a
fluent language-model or unique NaN-geometry claim.

Round 037 is recorded in `docs/ROUND_037_PROSE_MEMORY.md`: the writer learns
four typed relation classes from controlled paraphrases, the native 8 MiB root
stores the evidence, and matched 2/3-hop queries remain exact after gauge
changes. The native additions are the 32,385 lexical slot map and the writer
class codec. It is still a controlled pipeline, not unrestricted prose
understanding or a unique geometry advantage.

Rounds 029–031 are recorded in `docs/ROUNDS_029_031_NATIVE_LEARNING.md`:
the true cycle observable ties the conventional invariant exactly, the native
root trains a classifier but the conventional control is equal or better, and
the resident byte LM loses bits per byte to the dense 16×16 control. These
rounds establish gauge invariance and native training mechanics, not a general
language advantage.

Round 043 is recorded in `docs/ROUND_043_ASSOCIATIVE_MEMORY.md`: a frozen
byte LM plus a native 3-byte associative cache reduces mean held-out loss from
1.744586 to 1.645717 nats/byte (5.67%), while the flat conventional cache ties
it numerically. The native additions are a 128-row reserve hash and byte
probability interpolation. Generated text remains largely incoherent.

The native attention/causality seam is recorded in
`docs/NATIVE_ATTENTION_AND_CAUSALITY.md`: a metadata-local pair knockout/restore
for causal audits and a reusable 16→16 affine projection for Q/K/V. The latter
is one projection layer, not a full attention block.

Round 042 is recorded in `docs/ROUND_042_JOINT_DIALOGUE.md`: a learned
relation writer, native two-lane support/refutation memory, differentiable
propagation, and an autoregressive decoder form a joint dialogue path without a
supplied proof-status token. The conventional memory ties clean-input accuracy,
the language-only run collapses to abstention, and the restricted vocabulary
remains the boundary.

Rounds 038–039 are recorded in `docs/ROUNDS_038_039_FREE_GENERATION.md`:
the model samples a learned 2,048-subword vocabulary with about 464k
parameters and a native 16×16 triangle-circulation adapter. In the corrected
two-seed comparison the dense control wins test perplexity (251.845 vs 255.613
and 257.546 vs 261.806). All models degrade without memory or with shuffled
memory, and the native gauge round-trip stays below 1.13e-6. This is a real
unrestricted generator prototype, not fluency or a geometry advantage.

The integration adds `mth.mirror.cycle.train_step.f32` (content-gated
delta-rule write with mirrored lanes and SSE readout),
`mth.mirror.cycle.predict16.f32` (native CycleRead), and the native
trigonometric layer `mth.trig.sincos.f32` / `mth.trig.rotate.f32`. The trig
design space, including phase-coded memory, RoPE-style rotations, native
twiddles, and oscillatory gates, is documented in
`docs/TRIG_NATIVE_SYNTHESIS.md`. The next fair test must give the conventional
baseline the same episode memory and evidence before claiming a geometric
learning advantage.

## 4. Native kernel

`mth/nan16/mth_universe_map.nas` implements the address law in NaN16:

- input cell `0..32,895`, layer `0..9`;
- output page, word, guest word, point kind, ordinal/head, layer;
- rejects cell `32,896` and layer `10`;
- uses an inlined 32-bit restoring division so it never nests `CALL`/`RET`
  through the single `r15` link register.

Fixture: `mth/tests/mth_universe_map_test.nas`.

```text
PASS steps=12,916,386 marker="MTH UNIVERSE MAP PASS"
```

The fixture walks all 256 heads and all 32,640 mirror pairs, checks page/slot
coverage with guest-maintained counters, checks both ends of the universe, and
tests layer echo and rejection boundaries. The step count is local `nan_cli`
evidence.

## 5. Host map

`runner_riddle/universe_map.py` provides the same mapping to the control plane:

| Function | Contract |
|---|---|
| `page(id)` | page descriptor, byte/word offset, head, slots, route |
| `head(id)` | fixed-head relation point |
| `mirror_pair(n)` | mirror-pair relation point |
| `point(cell)` | canonical cell `0..32,895` |
| `from_raw(raw)` | 16-bit double-endian address through `MirrorRegister` |
| `route(cell, layer)` | NANNET route, optionally layer-qualified |
| `validate()` | exhaustive page/point coverage report |
| `page_directory_document()` | deterministic `spec/universe-map.json` |

`MthSystem.health()` now includes the `universe_map` coverage report, and
`MthSystem.universe_route(cell, layer)` resolves one relation point. The host
performs no mathematics.

Generated artifact: `spec/universe-map.json` (256 page descriptors, 32,896
relation points, deterministic `page_directory_sha256`).

Regenerate/check:

```sh
python3 tools/gen_universe_map.py
python3 tools/gen_universe_map.py --check
```

## 6. Unified cross-repo catalog

`spec/mth-unified-system.v1.json` binds the components without creating a
second authority:

| Provider | Role |
|---|---|
| `nanrouter.control` | NMP, point 0, six-slot ring, kernel manifest, universe map |
| `nan0s.vm` | native NaN16 VM, `NH_WORDS=67838` head bank, N16T transport |
| `hermes.runtime` | N16ROOT1, N16SNAP1, N16PACK1, head-bank transport, L0–L9 layers |
| `nanlmind.android` | N16T client and native NMP receipt path |
| `nanlmind.core` | universe identity / ring integration reference |
| `nanlm.experiment` | LM mixer experiment only, never a math authority |
| `nanlmind.clocked` | CLOCKED/HW3 demonstration service, not a second universe |

`runner_riddle/mth_unified.py` builds one catalog over the 103-kernel manifest
and the universe map. The catalogued graph-claim probe is a bounded candidate
query kernel; the separate multihop path-witness guest is intentionally outside
the numerical MTH ledger and keeps its own native CI gate. Each catalogued
kernel has:

```text
kernel_id, family, status, ci_verified
execution_mode: native_dispatch_abi | native_fixture_only
control_provider: nanrouter.control
executor_provider: nan0s.vm
route: math://GM0:SC0:MC0:BS0:0/function/<kernel_id>@v1
source/fixture SHA-256
```

The provider audit reads the local worktree first and falls back to the fetched
`origin/main` blob when the worktree is behind or dirty. It never fetches,
checks out, resets, or rewrites a sibling repository. This is how the current
audit sees new NaN0S/HERMES/Android contracts while leaving the user's
uncommitted work untouched.

Commands:

```sh
python3 tools/mth_unified.py --check
python3 tools/mth_unified.py --check --scan-repositories
python3 tools/mth_unified.py --write build/mth/unified-catalog.json --scan-repositories
```

The `.github/workflows/mth-unified-audit.yml` workflow runs the universe-map
check, the unified-catalog check, and the two focused test modules on every
change to those contracts.

Known cross-repo gap: HERMES and NaNLMind still expect the checked-u32
`mth.u32.add_checked` / `mth.u32.sub_checked` route and
`/v1/hermes/leases/math`, while NaNROUTER main has neither. The unmerged
`feat/native-hierarchy-router-hermes-bridge` branch supplies that contract.
See `docs/MTH_CROSS_REPO_SYNC_20261109.md`; do not alias it to the i32 kernel
without an ABI decision.

The generated catalog explicitly records:

```json
{"claims_ci_verified": false, "claims_live_deployment": false}
```

## 7. Current evidence

| Evidence | Result |
|---|---|
| Host universe map | 256 pages, 1,048,576 words, 32,896 points, coverage 1.0 |
| Native universe-map fixture | PASS, 12,916,386 steps, no trap |
| Unified catalog | 153 kernels, 153 CI-verified, no local-only, 151 sources, 149 fixtures |
| Provider contracts | green against worktree or fetched `origin/main` |
| Local Python tests | 1,452 tests, 30 skipped, OK |
| Canonical native runner | 150/150 fixtures PASS with NaN0S f31143e; pinned VM commit fe63617 differs only in a CI workflow |
| Unified audit workflow | green in run `42542831186` |

The 29 local skips include the upstream Ed25519 attestation class because the
optional `cryptography` package is absent in Termux; the canonical workflow
installs it and runs those tests.

## 8. Non-claims

- The native fixture was executed locally first and then in canonical run
  `42539617226`; the CI result is separate from the local step-count evidence.
- Provider source presence is not a live service or routing claim.
- Address coverage is not mathematical truth, proof, authorization, or a
  native head-bank update.
- A relation route does not bypass NMP preflight, capability, lease, or JAHS.
- The 2 MiB workspace budget is not the guest address space and is not a
  page-size limit.
