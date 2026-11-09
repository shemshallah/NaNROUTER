# Rounds 023–027 integration report

**Audit date:** 2026-11-08. **Sources:** `nan_mirror_round023.zip`, `nan_mirror_round024.zip`, `nan_recursive_round026.zip`, `nan_recursive_round027.zip`; transcript `session-ae652ebe-a058-43c0-9dda-29f40dbaaa39.md` (4.1 MB); `docs/MTH_UNIFIED_SYSTEM.md`; `docs/MTH_CROSS_REPO_SYNC_20261109.md`. The working tree also has an untracked field-level contract `docs/MIRROR_MEMORY_LAYOUT.md` (`mirror-memory/v1`, 296 lines); this report treats it as the proposed physical target, not a merged/CI-verified authority. No round is a live deployment, canonical merge, native NaN16 result, or generalization result.

## 1. Executive truth table

| Round | What it is | Strongest measured evidence | Not established |
|---|---|---|---|
| 023 | Native C++20 8 MiB mirror object | 65,280 directed mappings; Hodge 1.032382 ms; max divergence 8.841743693e-07 | Learning, language, NaN16, Android speed |
| 024 | Same root + external hyperedge arena | 200,002 hyperedges / 15,388 concepts / 600,006 links; root stable | Semantic concepts, taxonomy, recursive training |
| 025 | Corpus mapper; **no archive supplied** | Only downstream corpus contract in R026/R027 | 100k-sentence mapper, joint training, matched baselines |
| 026 | Pair-lane residual training + relation ingest | 3,713/578/801 split; mean CE 2.254254 plain vs 2.252887 pair; 30,000 relations | Generalization, capacity-matched gain, cycle benefit |
| 027 | Hyperedge-strength training | Train 100% @ 0.039507; untouched 50% @ 0.719144; gradient error ~0.000425 | Generalization, unseen-concept reasoning, merge |

One-sentence conclusion: **the geometry/storage lineage is real and testable; the learning lineage is a sequence of narrow, in-sample prototypes; the route view and physical view are two projections of one identity space, not one byte-overlay.**

## 2. Round 023 — 8 MiB mirror object

`mirror_object.cpp` is one `alignas(64)` 8,388,608-byte `Universe`: 256 heads × 128 B = 32,768 B; 32,640 pairs × 256 B = 8,355,840 B; two independently writable 128 B lanes per pair at `+0` and `+128`; `get(a,b)`/`get(b,a)` share a nonzero handle with swapped lane pointers; handle 0 is void; handles are 1..32,640. Pair index for `a < b` is `a*(511-a)/2 + (b-a-1)`, no pointer table. `fundamental_cycles_in_place` computes 32,385 root-0 triangle circulations and caches flux in the next 4 bytes, opposite sign in the mirror lane. `hodge_in_place` computes 256 divergences, removes the gradient component, preserves the symmetric part, O(256²) time / O(256) memory. `static_assert(sizeof(Universe) == 8*1024*1024)` is compiled in.

Measured (`results.json`, local CPU, float32): heads/pairs/directed = 256/32,640/65,280; bytes 8,388,608; mapping checks 65,280; void handle 0; Hodge 1.032382 ms; max divergence 8.841743693e-07; max gauge triangle delta and max cached flux delta both 2.384185791e-07.

**Non-claims:** one in-process timing, excludes allocation/init; not Android/Termux, not multi-seed. No IEEE-754 palindrome-bit identity, CPU NaN arithmetic, NaN16 execution, learning, corpus, optimizer, or language result. Head labels are abstract; cached flux is derived, not new information.

## 3. Round 024 — recursive hyperedges

The 8 MiB root is unchanged. An append-only external arena adds stable `Hyperedge {first,count,type,weight,parent}`, `Concept {first,defining_edge,parent,tag}`, and `MemberLink {hyperedge,next_member,next_incidence,Ref}`. Members may reference heads, pairs, or concepts. Pair membership is at `lane[0]+8`; head membership is in the first 4 bytes of the head record. Traversal is bounded; the fixed `penguin → bird → animal` two-hop test reaches `animal`. Growth uses vectors outside the root; IDs stay stable; no raw vector-element pointers persist; `mlock` is attempted after a page walk.

| Run | Root B | Hyperedges | Concepts | Links | Arena cap. | Append ms | 100k pair ms | 100k incid. ms | Checksum |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 50k | 8,388,608 | 50,002 | 3,850 | 150,006 | 4,085,600 | 9.2905 | 0.7997 | 4.0295 | 11,105,078,380 |
| 200k | 8,388,608 | 200,002 | 15,388 | 600,006 | 16,325,600 | 33.2045 | 0.7149 | 54.9582 | 111,441,442,720 |
| san 10k | 8,388,608 | 10,002 | 773 | 30,006 | 821,600 | 13.0888 | 2.2930 | 2.2944 | 571,765,021 |

`root_stable` and `mlock_succeeded` are true in all three JSONs. The 200k run reserved ~16.33 MB extra vector capacity plus the 8 MiB root, excluding allocator/code/OS/runtime overhead. ASAN/UBSAN 10k completed without reported errors.

**Non-claims:** "concepts" are allocated by `i % 13 == 0`, not learned semantic classes; relation types are numeric. No recursive training, transitive closure, taxonomy maintenance, contradiction handling, or concurrency. Single-threaded. `mlock` success on one Linux run is not Android/Termux or CPU-cache pinning. Round 024 writes membership at `lane[0]+8`, which collides with the later canonical residual slots 8..11.

## 4. Round 025 — corpus mapping (transcript-only)

No Round 025 zip was supplied. The transcript contains a **proposal**, not a measured mapper. R026/R027 reference `/mnt/data/nan_round025/corpus.jsonl`, which is absent from the four archives.

Downstream contract: R026 `train.py` reads JSONL `id`, `pos`, `lexfile`, `gloss`, `split`; `ingest_relations.py` reads `pointers`. It keeps nouns with lexfile 4..27; stratifies by lexfile/split; obtains **3,713 train / 578 validation / 801 test** across 24 lexfiles. R027 `experiment.py` keeps noun `@` hypernym pointers, builds up to 1,200 two-hop `(child,parent,grandparent)` triples, shuffles, selects **320**. R026 `ingest_relations.py` inserts **30,000** pointers of **11** relation types. This is a noun-hypernym projection, not full HW4.

Proposal acceptance targets: ≥100,000 UTF-8 sentences with provenance; stable concept IDs and sparse head activations; typed hyperedges with reversible membership; root updates without relocation; joint next-token/relation training; matched graph-only / cycle / cycle-ablated comparisons; throughput, recall, unseen-word inference, forgetting. Delivered: 5,092 R026 records, 320 R027 chains, no joint objective, no matched baseline, no unseen/forgetting test. **Non-claim:** Round 025 itself has no measured result in the supplied evidence; do not cite its targets as completed work.

## 5. Round 026 — pair-lane training and relation ingest

Layout: one page-aligned 8,388,608 B root; 256 × 128 B heads at `0..32767`; 32,640 × 256 B pairs at `32768..8388607`; pair id `1 + min(a,b)*(511-min(a,b))/2 + (max-min-1)`; 0 void; lane 0 at `+0`, lane 1 at `+128`. Lane 0's first **26 float32** are trainable class residuals; lane 1 is updated with opposite sign; the per-pair hyperedge head is at `lane0+112..115`; bytes 104..111 and 116..127 are unused by R026.

`train.py` gathers only active pair rows into a PyTorch leaf, computes cross entropy, backpropagates, and scatters with `root_step`. It is direct native-memory training, **not** a custom differentiable C++ kernel and not a gradient through discrete hyperedge topology.

WordNet classification: 3,713 train / 578 val / 801 test; 512-bin lexical hashing; 350 updates/seed; three seeds; test evaluated once.

| Seed | Plain CE | Pair-root CE | Permuted CE | Plain acc | Pair acc |
|---:|---:|---:|---:|---:|---:|
| 9 | 2.23523 | 2.23382 | 2.23508 | 0.40200 | 0.40200 |
| 19 | 2.27499 | 2.27365 | 2.27491 | 0.39576 | 0.39576 |
| 29 | 2.25255 | 2.25119 | 2.25244 | 0.39950 | 0.40075 |
| mean | 2.254254335172465 | 2.2528869241562877 | 2.254143640690429 | 0.3990844777361631 | 0.39950062421972526 |

The gain is tiny. Plain is not capacity-matched (34,522 parameters vs 34,523 plus a large pair table). Permuting pair IDs is a bijection, so the control is weak. Trained-memory ablation slightly worsened loss in all three runs. The `cycle` variant is only a scalar gate on logits; `train.py` has no cycle loss, Hodge term, or cycle-consistency objective. **"Cycle" is a name, not evidence of cycle-specific learning.**

Native measurements: 32,640 pair IDs; 100,000 hyperedges appended in 0.3020416130002559 s; root 8,388,608 B; root locked true (one Linux run); stable address true; mirror antisymmetry true; snapshot 10,388,644 B; restore true; generic softmax finite-difference max error 0.0008306801319122314. That last number is a three-element softmax check in `test_native.py`, **not** a native root gradient; R027 supplies the native-backed check. Across seeds, 970,372–970,580 floats changed and max pair weight was 0.05714–0.06838.

Relation ingest: 30,000 pointers, 11 types, 117,570 source synsets, 0.16156466899974475 s, stable root, locked true, 12,027 nonempty pair memberships. Relation metadata and lexical classifier are not jointly trained.

**Non-claims:** no capacity-matched gain, no cycle-specific benefit, no learned word senses (stable hashing to 256 heads), residuals are class logits not relational operators. `root_save`/`root_load` are raw same-platform format (no CRC/WAL/atomic rename/endian portability/concurrent-writer safety). Snapshot is not a merge candidate. R026 trains heads 0..255; canonical reserves head 0 as NANNET0 and trains 1..255 (§7).

## 6. Round 027 — hyperedge-strength training

R026 updated pair lanes. R027 gathers live `Hyperedge::strength` by stable ID, wraps strengths in PyTorch leaves, and scatters gradients through `root_step_hyperedges` into the same arena; it does not copy the whole graph into one autograd tensor. `root_step_hyperedges` validates every ID and every gradient for finiteness before mutating (one bad entry rejects the batch) and clamps strengths to `[-8,8]`. Root stays 8,388,608 B and does not move as the arena grows.

Experiment: Round 025 noun hypernyms; seed 27; shuffle; **320** two-hop chains. Each chain yields one positive `(a,b)+(b,c)` and one negative `(a,b)+(b,grandparent_distractor)`; the negative has its own record. **1,280** hyperedges; **640** queries; first **512** (256 groups) train; **128** (64 groups) untouched. Score = product of two sigmoid strengths. SGD, 300 full-batch iterations, lr 0.12, summed BCE. No learnable global semantic operator; topology unchanged. This is a synthetic path-label task, not language understanding.

| Metric | Value |
|---|---:|
| Initial loss / accuracy | 0.7191437482833862 / 0.5 |
| Trained-path loss / accuracy | 0.03950686752796173 / 1.0 |
| Untouched-path loss / accuracy | 0.7191439270973206 / 0.5 |
| Ablated loss (strengths zero) | 0.8369883298873901 |
| Native root address stable | true |
| Native hyperedges | 1,280 |
| Invalid-batch atomic | PASS |
| Snapshot/restore | PASS |
| Finite difference | -4.373490810394287e-05 |
| Autograd gradient | -4.3697753426386043e-05 |
| Relative gradient error | 0.00042495192193067727 |
| Runtime | 0.6831205199996475 s |

History: epoch 1 loss 0.695496, train acc 0.5; epoch 20 loss 0.406125, train acc 1.0; epoch 100 loss 0.121663; epoch 300 loss 0.039507. Untouched accuracy is **0.5 at every recorded epoch**.

Honest reading: **100% trained paths** means 1,280 scalar strengths fit 512 training queries in sample. **50% untouched paths** is chance on a balanced binary task; there is **no generalization**, because there is no feature-based mechanism to relate an unseen chain to a trained one. Zeroing strengths fails the training task (ablated 0.83699), so strengths are causally used, not semantic. The ~0.000425 error validates the native gradient path for one edge, not the representation.

**Non-claims:** no new-concept reasoning, language understanding, improvement over a conventional graph embedding, quantum effect, or canonical merge. `native_graph_round027.nan` is `NANR2601` + count + 8 MiB root + arena, a same-platform raw snapshot, not cross-platform or crash-safe.

## 7. The one 8 MiB layout reconciliation

### 7.1 Two views, one identity space

1. **Physical mirror view:** 256 head records × 128 B at `0..32767`, then 32,640 pair records × 256 B at `32768..8388607`.
2. **Route view:** 256 logical 32 KiB pages. Pages 0..254 are real heads 1..255; page 255 is head 0/NANNET0. Each real-head page reserves the last 256 words (3840..4095) as 128 two-word mirror-pair slots.

They are **not** the same byte layout. A raw copy of the physical root into route pages is wrong.

### 7.2 Page accounting

| View | Region | Bytes | Count |
|---|---|---:|---:|
| Physical | head region | 32,768 | 256 × 128 B |
| Physical | pair region | 8,355,840 | 32,640 × 256 B |
| Physical | **total** | **8,388,608** | 32,896 records |
| Route | 255 real-head pages | 8,355,840 | 255 × 32,768 B |
| Route | NANNET0 page | 32,768 | 1 × 32,768 B |
| Route | **total** | **8,388,608** | 256 pages |
| Route | MP slots | 522,240 | 255 × 128 × 16 B |
| Route | head points | 2,048 | 256 × 8 B |
| Route | relation-point bytes | 524,288 | 512 KiB |
| Route | page body/workspace | 7,864,320 | remainder |

The route gives each pair a **16-byte, two-word slot**; the physical view gives each pair a **256-byte, two-lane record**. That is a 16× payload difference. If route pages stored full 256 B records, pair payload alone would need 8,355,840 B, leaving 32,768 B for all 256 heads — 128 B/head packed, incompatible with one head per 32 KiB page. Therefore the route MP slot is an **address marker/descriptor**, not a copy of the physical pair.

Second arithmetic fact: 255 trainable heads give `C(255,2) = 32,385` pairs. The canonical profile retains **32,640** records to preserve exact byte geometry. The extra **255** are pairs involving head 0 (NANNET0): addressable/control, **not** trainable real-head pairs.

### 7.3 Head 0 / NANNET0

```text
head 0 = page 255 = ring position 255 = HW0:0 = NANNET0
real/trainable heads = 1..255
```

Physical head 0 is at byte `0`; route head 0 is at virtual page 255, word 0, byte `8,355,840`. Those differ. Overlaid on physical bytes, `8,355,840` is the start of physical pair record **32,513** (pair index 32,512). This is the concrete proof that a translator, not `memcpy`, is required.

Consequences: R023 uses head 0 as an ordinary head (and as fundamental-cycle root); R024 likewise; R026 hashes to 0..255. They are not NANNET0-compliant. The integration target freezes physical head 0 as NANNET0/control and trains 1..255, or explicitly keeps 256 computational heads and says `HW0:0` is a separate logical node. The canonical working-tree profile designates head 0 NANNET0, which entails the former; the training exclusion is not yet enforced by R026. NANNET0 page 255 has no mirror slots; the 32,640 MP slots live on the 255 real-head pages.

### 7.4 Pair IDs, ordinals, cells, routes

For `0 <= a < b <= 255`:

```text
ordinal n      = a*(511-a)/2 + (b-a-1)          # 0..32639
physical id p  = n + 1                         # 1..32640
canonical cell = 256 + n                       # 256..32895
route          = ...::HW0:MP<n>                # MP0..MP32639
physical byte  = 32768 + 256*n
route page     = n % 255
route word     = 3840 + 2*(n // 255)
route byte     = 32768*(n % 255) + 8*(3840 + 2*(n // 255))
```

| Pair | Ordinal/id | Physical byte | Route point | Route byte |
|---|---|---:|---|---:|
| `(0,1)` | 0 / 1 | 32,768 | MP0, page 0, word 3840 | 30,720 |
| `(254,255)` | 32,639 / 32,640 | 8,388,352 | MP32639, page 254, word 4094 | 8,355,824 |

Route `offset_bytes` is **not** the physical offset; equal values are accidental, never invariant.

### 7.5 Lane field map and round collisions

Canonical `mirror-memory/v1`: head `first_hyperedge` 0, `state` 4, `score` 8, `generation` 12, reserved 16..127. Pair lane 0: `residual[26]` 0..103, `relation_type` 104, `confidence` 108, `hyperedge_head` 112, `cycle_flux` 116, `generation` 120, `flags` 124. Lane 1: `residual[26]` 128..231, reserved 232..255.

| Field | R023 | R024 | R026/R027 |
|---|---|---|---|
| lane0 0..3 | scalar state (float) | phase (float) | residual[0] |
| lane0 4..7 | flux cache | residual[1] | residual[1] |
| lane0 8..11 | residual[2] | pair first hyperedge | residual[2] |
| lane0 104/108 | — | — | unused |
| lane0 112 | — | — | hyperedge head (match) |
| lane0 116 | — | — | unused |
| lane0 120/124 | — | — | unused |
| lane1 | mirrored flux at +132 | — | sign-opposite residuals |

Only offset **112** matches across R026/R027 and the canonical profile. R023's flux at `+4` collides with `residual[1]`; R024's membership at `+8` collides with `residual[2]`. Decode those rounds with their own version; never read them as `mirror-memory/v1`. R027 strengths are **not** in the pair lane: they live in the external `{pair_id,concept_id,relation_type,next,strength}` arena, linked by the lane0+112 head. Strength is a score, not canonical pair `confidence`.

### 7.6 Bridge rule

```text
route HW0:h (h=1..255)  -> physical head h
route HW0:0             -> physical head 0, control only
route HW0:MPn           -> physical pair n+1
route layer ::L0..L9    -> resolution qualifier, not a second pair
```

The physical lane payload stays in the native root. The route slot is a 16-byte address/descriptor, not a second 256-byte record, not a second writer. A route never authorizes a merge, truth claim, or native head update.

## 8. Mapping onto NaNROUTER / HERMES / NANNET / MTH

| Layer | R023–R027 supply | Maps to | Missing |
|---|---|---|---|
| NaNROUTER | Pair identity, geometry, route examples | Canonical cells, MP routes, physical profile | No training, no live route, no merge |
| HERMES | 256 heads/32,640 pairs/two rails; leaves, relations, hyperedges | Resident cells/relations; free-chat/WordNet ingestion | 256 MiB file ≠ 8 MiB root; chart placeholder; pair channel coarse |
| NANNET | HW4 evidence; BS0:0/HW2:0/HW4:0 routes | Read-only lexical evidence; lease/route admission | No corpus/trainer through NANNET; no Koyeb cutover; merge closed |
| MTH | 91 bundled kernels; 4 vector dispatchers; N16I | Catalog, fixture verification, typed vector execution | C++/torch are not NaN16; 87 kernels lack operand ABI; no proof |
| R025 corpus | Noun-hypernym JSONL | HW4 read path, lexfile labels, 320 chains | Not 100k, not full WordNet, no joint training |
| R026 lanes | 26 residual logits/pair | Canonical `residual[26]` | Not semantic operators; head 0 excluded; no matched gain |
| R027 strengths | Scalar hyperedge scores | HERMES relation/hyperedge score | Not calibrated confidence; no generalization |

Count reconciliation: **91** = HERMES bundled kernels/fixtures (4 dynamic, 87 fixture-only); **96** = NaNROUTER `origin/main` catalog observed in the cross-repo audit (94 runner fixtures); **148** = current unified catalog (148 CI-verified, 146 sources, 144 fixtures); **78** = registered HERMES tools; **1,447** = local Python tests, 30 skipped. The 91→112 increase is catalog expansion, not evidence of a general dynamic ABI.

Concrete bridges:

- **R025 → HW4:** JSONL `id`/`pos`/`lexfile`/`gloss`/`pointers` can be projected onto HW4 word/synset/relation leaves, but the delivered corpus is noun-hypernym only, not the 26-type sparse graph, and it writes no route or canonical leaf.
- **R026 → HERMES/NaNROUTER:** 26 lane floats map to canonical `residual[26]` slots; the pair is a computational address, not a concept ID; head 0 must be excluded from training. R026's measured classifier is not the resident universe's Q16.16 rail model. `HW0:MPn` addresses the pair; it does not encode the 26 residual values in the route slot.
- **R027 → HERMES/MTH:** strength is a scalar hyperedge score, not canonical pair confidence; the arena is outside the 8 MiB root. `HW0:MPn` addresses the pair, not the hyperedge ID, and no N16I kernel executes the C++/torch path.
- **All three → NANNET:** none writes a lease, route admission, receipt, or canonical commit. NANNET is the control/authority plane; these are local experimental artifacts.

Cross-repo blockers: HERMES/NaNLMind expect `mth.u32.add_checked`, `mth.u32.sub_checked`, and `/v1/hermes/leases/math`; NaNROUTER main lacks them. The unmerged `feat/native-hierarchy-router-hermes-bridge` supplies the contract; do not alias it to `mth.integer.checked.i32` without an ABI decision. N16PACK/N16SNAP are HERMES-owned (`universe_pack.py`, `chart_storage.py`, `native_head_checkpoint.py`, `universe_chart.py`), not nan0s-owned. Several pins (`24b3584`, `2d6ed9f`, `bb4598f`) are stale or not ancestors of observed `origin/main`; a pin is not CI. A provider artifact match is not live deployment or a semantic route check.

## 9. Transcript-only contributions

### 9.1 Permanent session contracts

Six packaged documents load at `register(ctx)` and persist as `state_dir/session/plugin_session_context.json`: `permanent-instructions` (SHA-256 `2e60237e...`), `nannet-architecture` (`78165027...`), `nannet-routing` (`afc9102b...`), `wordnet-hw4` (`f8cc534e...`), `free-chat-learning` (`1c90fac6...`), `mth-universal-runtime`. They are hashed, cached process-wide, given a stable generation, and injected into chat plus reflection/curriculum/CLOCKED/synthesis provider calls. A caller system prompt cannot remove them. This is process-lifetime contract, not user-editable memory.

### 9.2 WordNet HW4 sparse graph

Session contract: 82,192 synsets, 117,953 lemmas, 84,505 hypernym edges, 378,203 typed edges, 26 relation types. Local archive reported **117,458 synsets, 147,982 lemmas, 377,031 pointers** (`a=7,461`, `n=81,972`, `r=3,625`, `s=10,706`, `v=13,694`). Counts are archive-dependent; report `WordNetStore.stats()` for the archive in use.

Read path: word → lemma index → synset offsets → definitions/hypernyms/inherited categories/typed relations → L4/L5 scratch → `defined_as`/`kind_of`/`inherits` rows → optional conservative promotion. No dense per-word 256×256 matrix, no one-word-one-head. Unknown words fail closed; a gloss is a graph edge, not parsed prose understanding.

### 9.3 Free-chat learning loop

```text
user message -> provider/native answer -> durable transcript
 -> structured reflection of explicit evidence/relations
 -> L0-L9 observation (10 layers, 255 heads, paged 1 GiB scratch)
 -> concept matrix/relation rows
 -> optional conservative promotion (explicit approval)
 -> native relation-train for supported/refuted triples
 -> separate canonical merge gate (never bypassed by chat)
```

Native update is reported only when the runner confirms changed heads, mirror updates, hyperedges, and a changed digest. Missing runner reports failure, never fabricates. Layered scratch/reflection is derived until promotion/merge. Neutral or incomplete claims stay symbolic; questions/requests are not facts; assistant output is not independent evidence. Replaying a source-bound event is a no-op; later evidence is distinct; contradictions are retained. The deterministic parser supplements `X is Y` / `X can Y` without double-counting reflection.

Measured: 3-turn smoke → 10 layers/turn, 1/1/2 relations, 10/20/30 scratch records, active heads 177→222→240 of 255. Resident corpus run: 14,039 train/500 held-out; temporal NLL 6.7254→2.7400 (ppl 833.33→15.49), resident 5.5953→3.4229 (ppl 269.15→30.66), hybrid 5.8347→2.6042 (ppl 341.96→13.52); 13,911 leaves, 0 relations, 13,655 features, generation 13,762. These are local corpus runs, not free-chat generalization evidence.

### 9.4 Promotion and canonical-merge gates

Local promotion: group exact `(subject,predicate,object)` (later including polarity/confidence so supported/refuted don't collapse); `support >= 3` (`learning_min_support`); `confidence = support/(support+1) >= 0.6` (`learning_min_confidence`); at most 64 candidates; explicit `approved=true` when `learning_require_approval`; at most 100 promoted leaves; `learning_auto_sync` false. This writes **local HERMES derived state only**, not BS0/MC0.

Canonical merge needs generation CAS, six-runner generation barrier, audit, rollback, explicit operator approval — none exist in these rounds. `merge_enabled` and `canonical_merge_enabled` default false; `nanlm_learning_sync`, `learning_cycle`, `wordnet_ingest` promotion, and `memory_merge` must return `merge_disabled` while false. Export/intake is candidate staging with generation CAS and `canonical_commit=false`; it is not a merge.

### 9.5 Resident universe

A **separate 256 MiB-default, 1 GiB-hard memory-mapped file** (min 16 MiB), not a replacement for the 8 MiB root. One writer, append-only generation/digest, dual-slot checkpoint, journal, 256 heads, 32,640 pair cells with `s+`/`s-` rails, leaf tree, typed relations/hyperedges, quantized resonance rows, bounded export/intake. Chart section is a placeholder, not live `Chart8MiB`; the 2 GiB overbootstrap map is never copied. Measured: 188 resident tests and a 256 MiB create/ingest/query/reopen on Termux/aarch64.

### 9.6 N16I / MTH limits

91 bundled kernels, 91 CI-verified; 4 admitted float32 vector dispatchers; 87 fixture-only with no general operand ABI. N16I differential self-test: native 73,982 steps vs interpreted 3,343,783 steps, 2,640 identical serial bytes, no trap. A generic guest-image dispatcher runs assembled images (e.g. K256 Laplacian), but that is **image dispatch**, not typed operands for every kernel. Native MTH needs a C compiler and `gawk`/`mawk` (BusyBox awk rejected); cross-architecture is only locally exercised on aarch64. Catalog membership, fixture PASS, and N16I dispatch are not proof, authorization, lease, merge, or canonical commit.

### 9.7 Gemma evidence

Open-ended session: 12/12 calls, 9 tools, NANNET loopback paired, merge disabled; state 148 leaves (53 hubs, 91 kernels, 3 vectors, 1 relation), 227/255 active heads. Multi-session series: 15/15 calls, 12 tools, 100% task coverage; written quiz 76.1%→76.1%. A journal-conditioned probe reached 100% (in-context learning, not a weight update). These are tool-use results, not language learning.

### 9.8 NANNET / HW4 boundaries

`BS0:0` is the shared runner-ring port; `HW0:0` is the separate Bootstrap root. HW0 Bootstrap, HW1 Android, HW2 HERMES, HW3 CLOCKED, HW4 WordNet (permanently reserved), HW5–HW255 allocatable. Canonical HW4: `nan://GM0:SC0:MC0:BS0:0:HW4:0`; `nan://HW4:BS0:MC0:SC0:GM0` is compatibility only. `::synset/...`, `::word/...`, `::relation/...` are plugin-local typed extensions; NaNROUTER v1 does not yet register them. HERMES upstream is HW2:0 via NaN16DE/N16T; dispatch is at-most-once with a durable journal; guest execution is not canonical training commit.

## 10. Integration decisions

| Decision | Item | Reason / target |
|---|---|---|
| **Adopt** | Physical profile: 32 KiB heads + 8,355,840 B pairs | Exact 8,388,608; IDs 1..32640; lanes; head 0 NANNET0 |
| **Adopt** | Pair law and MP/cell mapping | Matches R023/R024/R026 and `MirrorRegister` |
| **Adopt** | R023 Hodge/flux audits as conformance tests | Real mapping/flux checks; not training |
| **Adopt** | R024 external stable-ID arena, parent links, bounded traversal | Grows hyperedges without moving root |
| **Adopt** | R026 lane0+112 hyperedge head | Only offset matching canonical profile |
| **Adopt** | R027 validation/clamp/snapshot tests | Good defensive pattern; prototype only |
| **Adopt** | Permanent session contracts, free-chat honesty rules | Prevent fabricated routes/commits/evidence |
| **Adopt** | Separate resident universe | 256 MiB default/1 GiB hard; no 2 GiB copy |
| **Adapt** | R024 +8 membership → +112 | +8 collides with residual[2] |
| **Adapt** | R023 +4 flux → canonical +116 | +4 collides with residual[1] |
| **Adapt** | R026 hashing 0..255 → 1..255 | Head 0 is NANNET0/control; 255 head-0 pairs control-only |
| **Adapt** | R026 26-float residual | Optional residual, not semantic relation; matched baseline |
| **Adapt** | R027 `[-8,8]` strength | Uncalibrated score, not canonical confidence |
| **Adapt** | R027 pairhash | Pair is computational address; concept ID separate |
| **Adapt** | Route MP slot | 16-byte descriptor, never 256-byte pair copy |
| **Adapt** | 91/96/112 counts | Version manifests; 4 dynamic, rest fixture-only |
| **Adapt** | N16I dispatch | Assembled guest images only; typed ABI separate |
| **Reject** | Route-over-physical byte overlay | Page 255 overlaps pair 32,513 |
| **Reject** | NANNET0 as trainable 256th head | Violates identity and slot accounting |
| **Reject** | R026 "cycle" as cycle training | No cycle loss/Hodge term in `train.py` |
| **Reject** | R027 generalization | 50% untouched; no feature transfer |
| **Reject** | R027 snapshot as merge | Raw same-platform; no CAS/six-runner |
| **Reject** | Native NaN16 claim for C++/torch | Ordinary f32/u32; no NaN16 guest |
| **Reject** | Live deployment/merge from archives | No lease, Koyeb cutover, or gate |

## 11. Priority-ordered next steps

**P0 — correctness/authority**

1. Verify `mirror-memory/v1` and make `spec/universe-map.json` the only route projection; test page-255/pair-32,513 and head-0 NANNET0.
2. Freeze head 0 as NANNET0/control; train 1..255; mark 255 head-0 pairs control-addressable. Do not shrink to 32,385 records without a new version.
3. Add a versioned lane decoder for R023 (+4), R024 (+8), R026/R027 (+112); reject unknown versions; never reinterpret residual bytes as metadata.
4. Define the hyperedge bridge: stable ID, pair handle, concept ID, relation type, strength, provenance, validated lane0+112 link; no raw pointers.
5. Keep `merge_enabled=false`; implement generation CAS, six-runner barrier, audit, rollback, dry-run before any canonical merge. R027 snapshots are artifacts, not candidates.

**P1 — learning/integration**

6. Expand Round 025 to ≥100,000 sentences, provenance, stable IDs, source-disjoint splits, typed hyperedges, full HW4 (not noun-only).
7. Capacity-matched baselines: ordinary graph vs pair-address vs cycle-ablated, same parameters/FLOPs/storage, multiple seeds, confidence intervals.
8. Implement a real cycle objective (Hodge/consistency) with a cycle-ablated control; stop calling the existing gate "cycle training".
9. Extend R027 to held-out link prediction, source-disjoint links, novel-definition QA, explicit traversal and conventional graph baselines. Require untouched accuracy above chance before saying "generalization".
10. Wire strengths into HERMES typed relations with separate `strength`, `confidence`, `polarity`; calibrate or mark uncalibrated.
11. Add typed operand ABIs and cross-architecture N16I evidence; keep only the four vector dispatchers dynamic until each new ABI has differential tests.
12. Replace the resident chart placeholder with live `Chart8MiB`, persist the feature index, add writer lock/LRU, benchmark RSS/page faults on Termux.

**P2 — operations**

13. Resolve `mth.u32.add_checked`/`sub_checked` and N16PACK ownership.
14. Add checksum/version/recovery/endian rules to snapshots; `NANR2601` is same-platform only.
15. Measure cache/memory bandwidth, `mlock` limits, and page-fault behavior on Android/Termux before runtime-suitability claims.

## 12. Explicit forbidden claims

1. **No live deployment.** No production NANNET route, lease, Koyeb cutover, or hardware allocation was performed.
2. **No canonical merge.** No BS0/MC0 state was merged/promoted; local promotion, candidate intake, and R027 restore are not merges.
3. **No native NaN16 claim for C++/torch prototypes.** R023–R027 use ordinary little-endian f32/u32 and host PyTorch; no NaN16 guest, NaN bit arithmetic, or native head-bank update.
4. **No generalization claim for R027.** 100% trained / 50% untouched is in-sample fit plus chance, not transfer.
5. **No cycle-learning claim for R026.** "Cycle" is a scalar gate; no cycle loss or Hodge objective is trained.
6. **No capacity-matched improvement claim for R026.** Plain is not matched; permuted-key is a bijection.
7. **No semantic-concept claim for R024.** Concepts are allocated by `i % 13 == 0`; the penguin chain is a fixed traversal test.
8. **No language-understanding, AGI, or quantum claim.**
9. **No physical-offset-equals-route-offset claim.** Page 255 at byte 8,355,840 is physical pair 32,513.
10. **No trainable-NANNET0 claim.** Head 0 is control; its pairs are control-addressable.
11. **No "all 112 kernels execute" claim.** Four vector kernels have a general dispatcher; the rest are fixture/catalog only.
12. **No "N16I runs arbitrary typed kernels" claim.** N16I runs assembled guest images; typed operand ABI per kernel is incomplete.
13. **No Android/Termux performance claim.** Round timings are local single-process Linux, not ARM/Termux.
14. **No "mlock guarantees cache residency" claim.** It does not pin CPU cache or registers.
15. **No "Round 025 met 100k sentences" claim.** No archive; downstream corpus is 5,092 records and 320 chains.

## 13. Evidence notes

R023: `mirror_object.cpp`, `results.json`, `README.md`, `SHA256.json`. R024: `recursive_memory.cpp`, `results_50k.json`, `results_200k.json`, `results_sanitized.json`, `README.md`, `SHA256SUMS`. R026: `root.cpp`, `train.py`, `test_native.py`, `ingest_relations.py`, `native_results.json`, `relation_ingest_results.json`, `summary.json`, `*.root8m`, `snapshot_round026.nan`, `SHA256SUMS`. R027: `root.cpp`, `experiment.py`, `results.json`, `test.log`, `native_graph_round027.nan`, `SHA256SUMS`.

All numbers are quoted from those files or the transcript's own output; transcript-only measurements are labeled. Design targets are never presented as measured.

**Out of scope:** a Round 028 archive/docs and an untracked host-side corpus mapper are present in the working tree; neither is part of the supplied 023–027 evidence, and neither changes the R027 no-generalization result.
