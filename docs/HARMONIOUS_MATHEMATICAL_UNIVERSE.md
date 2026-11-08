# Harmonious mathematical universe — integration audit and executable path
## Scope

This is a cross-repository work map built against `GAME_PLAN_::.md`, `GAME_PLAN_MTH.md`, `game_plan_deep.md`, `game_plan_foundations.md`, `DEEP_PLAN_CONT.md`, the native NaN0S head bank and the HERMES chart/teacher architecture. It distinguishes **implemented**, **proposed**, **native tested**, and **live verified**, avoiding a second universe or a second mathematical truth authority.

**Architectural center:** NANNET0 is point 0; HW0:1..255 are logical head coordinates. Six `NANROUTER-0..5` runner slots are **time-multiplexed** (one active at once), not a six-model swarm. The 8 MiB local chart is a view/byte overlay, not 255 independent model checkpoints. Math work is governed by the canonical typed MTH registry and NMP preflight, not a Python mathematical implementation.

## The real learning loop

```text
user/teacher -> HERMES clocked observation
   -> source identity + immutable event + confidence/provenance + L0..L9
   -> mandatory Boolean/logic foundation checkpoint (once)
   -> routed sparse candidate (not a proved fact)
   -> typed object/leaf and math:// identity via MC0DB
   -> :: linker proposes transform/function; ranked but NOT executable yet
   -> math validity preflight + authorization + runner capability
   -> point 0 NMP lease -> one active runner ring slot
   -> pinned NaN16 guest, native MTH calculation OR observation-only head score
   -> native result and generation receipt -> at-most-once journal
   -> SHA256 chart bank byte transport -> local atomic checkpoint
   -> negative/positive evidence and utility update (not rule promotion)
   -> held-out evaluation -> separate review/promotion gate
   -> HERMES response and next curriculum proposal
```

A **scoreboard observation** can record native `nhr_observe` evidence without claiming MTH numerical execution. A **mathematical transform** must pass MTH/NMP full preflight, independent validity and capability. The two kinds cannot share an “approved” shortcut. Native scoreboard updates do not grant truth.

## Exact storage geometry and identity seams

- NaN0S native bank: 255 heads × (2 slots × (5 header + 128 words)), plus 8-word header = **67,838 words / 542,704 bytes**.
- HERMES opaque chart reserved `0x640000..0x6C47F0` exclusive, guest word offset `0xC8000`; 8 MiB chart remains exactly 8,388,608 bytes.
- HERMES native bank window is **distinct** from existing `NLMLEAF1` one-KiB-in-each-head summarized scratch and from the `NLMHEAD1` aggregate projection.
- Native `nh_open`, `nh_choose`, `nh_put`, `nh_get` implement slot validity, generation and NaN class checks. HERMES moves bytes without recomputing those decisions.
- Persistent chart snapshots use their own SHA256 + canonical parent root. Native `nh_hash` is not cryptographic. Both protections are needed.
- Physical head 0 represents NANNET0. The HERMES 256-head routing prior and the native 255 writable head slots must not be silently conflated.
- The NaNROUTER MTH guest default is **2 MiB** with no page-size limit. The native bank fits the budget in isolation, but this is NOT proof the same guest can map the full HERMES 8 MiB chart; implement a bounded bank window into the VM explicitly. Do not allocate a full 8 MiB contiguous guest when the active guest budget is 2 MiB.

## Missing bridge inventory (in priority order)

1. **Guest memory mounting** — introduce a native VM bank-window import/export mapping into the HERMES reserved region. Validate the same word/payload/class semantics using native `nh_open`. The HERMES PR is a storage transport, *not* a VM mount.
2. **Authenticated native evidence** — associate one pinned guest image, HERMES installation/universe ID, active NANNET lease, ring epoch, operation ID, before/after bank SHA and head generation. Reserve in `HermesDispatchJournal` before native invocation; ambiguous crash requires inspection, not blind retry. `head_bank_handoff.py` validates **structure only** and cannot attest a guest.
3. **Training vs math authority** — split `observation-scoreboard`, `typed-relation`, and `math-transform`. For `math-transform` enforce MathValidityEngine → NMP preflight → capability → lease → native operator → evidence. Empirical utility only updates utility; V3 requires trusted proof checker.
4. **Functional MTH coverage** — many manifest kernels are fixture-verified but not dynamically callable by HERMES. Current `hermes_mth_tools.py` explicitly lists four native dispatch ABIs. Extend explicit per-kernel shape/domain/workspace and native dispatch receipts without bypassing preflight.
5. **Real learning objective** — the 128-count-per-head scoreboard is an **online signal**, not trainable weights with gradient feedback. Add a native, persistently versioned predictive state (e.g., counts with time decay plus typed relation scoring) and a held-out next-symbol/next-word and relation-polarity evaluator. Make all levels' train/eval metrics separate.
6. **Sparse specialization** — HERMES `HEAD_POPULATION` reports rank collapse with 255 active heads (effective rank 1). Freeze head0, route sparsely, measure head load, entropy, effective rank, noise/control and diversity. Head addressing is not head ownership of a word.
7. **Unsupported-answer gate** — `MTH_LAYERS` records structured relation candidate improvements yet unsupported yes/no still confabulate. Add calibrated abstention and provenance-based retrieval. Disagreements become two retained claims, never overwrite/merge-by-averaging.
8. **Cross-resolution language loop** — share L0..L9 alignment IDs across phonetic/morpheme/lexical/sentence/paragraph/narrative routing; capture evidence from chat, keep native mutations and SQLite ledger provenance coherent, and avoid asserting semantic understanding from byte-perfect Boolean tests.
9. **P13 experiment bar** — real frozen model/corpus, data split + leakage controls, gain over majority/bigram/template baselines, ablations for geometry, MTH, head score and context; reproducible seeds/checkpoint/root/CI; explicit rejection if no significant held-out improvement.
10. **Recovery under updates** — replay/duplicate, stale lease, abort and torn native slot, lost chart checkpoint, direct head0 writes, swapped canonical roots, invalid NaN class, float payload, ring epoch rollover, concurrent writers and reattachment. A crash must never turn scratch into canonical math truth.

## Parallel lane work packets

| Lane | Owner | Deliverable | Verification |
|:--|:--|:--|:--|
| A | NaN0S | native bank attach/read/observe, recover and guards | guest VM PASS with class nibble preserved |
| B | HERMES | SHA256 chart-bank transport, generation fence, recovery | isolated 8 MiB snapshot tests |
| C | NaNROUTER | binding of lease/generation/native receipt | reject cross-head/cross-root/stale replay |
| D | NaNROUTER MTH | dynamic dispatch widening, real native execution | typed admission + native receipt + golden numerical oracle |
| E | HERMES | teacher/user clocked guided search, curriculum and chat updates | train/test leakage control, bounded free chat after logic |
| F | LM eval | foundation vs chat and untrained baseline, sparse router | paired held-out data, pre/post metrics and ablations |
| G | NANNET0 | preflight-bound single-active ring and byte window | fail closed on wrong epoch, capability, lease and memory |
| H | evidence | provenance/negative memory/rule lifecycle | replay, contradiction retention, integrity and independent promotion |

Lanes A/B/C can change independently; lane G must not advertise a live trained bank until A/B/C and the VM window agree. Parallel exploration is fine; authoritative canonical commits remain serialized and event sourced.

## Critical distinction

`native_guest_attached=false` is currently the truthful inspection state for HERMES. A chart carrying bytes and an attested guest sharing a mounted bank are different. A native head learning counter increasing is measurable state change, not proof of newly acquired linguistic, mathematical or general intelligence. No quantum-computation claim follows from the palindromic addressing or NaN four-face encoding; any such hypothesis needs explicit classical control and statistically valid experiments.

See machine-readable `spec/native-head-integration-seams-v1.json`, `runner_riddle/head_bank_handoff.py`, and the NaN0S/HERMES PR fixtures for the next integration gates.
