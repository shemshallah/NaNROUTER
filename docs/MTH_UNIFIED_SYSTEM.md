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
| `hermes.runtime` | N16ROOT1, N16SNAP1, head-bank transport, L0–L9 layers |
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

The generated catalog explicitly records:

```json
{"claims_ci_verified": false, "claims_live_deployment": false}
```

## 7. Current evidence

| Evidence | Result |
|---|---|
| Host universe map | 256 pages, 1,048,576 words, 32,896 points, coverage 1.0 |
| Native universe-map fixture | PASS, 12,916,386 steps, no trap |
| Unified catalog | 112 kernels, 112 CI-verified, 0 local-only, 110 sources, 109 fixtures |
| Provider contracts | green against worktree or fetched `origin/main` |
| Local Python tests | 1,248 tests, 29 skipped, OK |
| Canonical native runner | 110/110 fixtures PASS with NaN0S f31143e; pinned VM commit fe63617 differs only in a CI workflow |
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
