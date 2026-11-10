# HW4 WordNet 3.1 on the NaNROUTER ring

**Status:** full-corpus dense reference and read-only router attachment tested in CI. GitHub Actions is NOT proof of deployment to a remote Koyeb/runner service.

## Identity and allocation

- Logical route: nan://GM0:SC0:MC0:BS0:0:HW4:0
- Runtime owner: NaNROUTER/MC0:0 (existing router ring and point fabric)
- No NaNLMind/BS0 main-ring writes, ownership, training, or promotion
- A verified image stays memory-mapped read-only inside the existing NaNROUTER process, while its exact SQLite ledger is opened read-only. Neither creates another LLM.
- HW4:0 is an existing reserved WordNet point on the NANNET fabric, activated only after mounting verified data.

## WordNet source and geometry

Input is the original wn3.1.dict.zip, including four data files (noun, verb, adjective, adverb) and index.sense. CI verifies all five extracted file SHA256 values against the actual user Library ZIP before building. Outer ZIP metadata may differ, but the dictionary bytes are identical.

| Metric | Verified result |
|---|---:|
| Synsets | 117,791 |
| Sense-index entries | 207,235 |
| Directed pointers | 378,203 |
| Unresolved pointers | 0 |
| Same-head source pointers kept in exact overlay | 1,384 |
| Canonical pairs allocated | 32,640 |
| Canonical pairs with evidence | 32,475 |
| Empty canonical pairs | 165 |
| Dense reference image bytes | 8,388,608 |

Dense image geometry is 256 * 128-byte head records plus 32,640 * 256-byte pair records. Pair ID is 1+a*(511-a)/2+(b-a-1) after normalizing a<b. Physical pair byte offset is 32768+(pair_id-1)*256. Forward and reverse counts share the same physical pair record but remain distinct. Each record stores direction-specific counts, a 16-category relation mask, 16 uint32 lane counts in each direction, and reserved bytes. This reference count matrix does not falsely treat antonymy as refuting truth evidence.

Mapping follows the existing NaNROUTER WordNet SHA256 concept key hash. Exact keys, POS, lexical indices, relation symbols, source lines and polysemous senses remain in SQLite, so hash collisions do not erase identity.

This is a **reference projection**, not a bitwise mountable NaN0S guest image. The NaNROUTER 32 KiB-page guest layout is different; mapping must use a native bridge rather than overlaying this image onto the active guest.

## Verified immutable generation and release

Full reference store includes generation-00000001/wordnet-c256.root (8 MiB), generation-00000001/wordnet-exact.sqlite3, generation-00000001/manifest.json, and CURRENT.json. The pointer and root/SQLite SHA256 values are checked on every mount.

Release: https://github.com/shemshallah/NaNROUTER/releases/tag/hw4-wordnet31-full-g1

Asset: hw4-wordnet31-full-reference.tar.gz
Size: 33,328,874 bytes
Pinned SHA256: 87dbcdd2d209db95e8d15be68109ef3642e78ef540ea12ad71f3b04982876695

The bootstrapping code refuses incorrect archive digests, path traversal, unsupported tar entries, and attempts to write to BS0DB.

## NaNROUTER deployment

Set these configuration variables on the existing router service, not in NaNLMind main training workers:

    RIDDLE_HW4_STORE=/mc0db/hw4-wordnet31
    RIDDLE_HW4_RING=NaNROUTER/MC0:0
    RIDDLE_HW4_RELEASE_BOOTSTRAP=1

The existing deploy/start_router.sh installs the pinned release into the designated persistent MC0 volume when absent. After verification, the normal router HTTP service holds the immutable image and exact ledger open and activates existing HW4:0 fabric role. On restart the generation is reused without a rebuild.

Alternatively, provide RIDDLE_HW4_WORDNET_ZIP=/path/to/wn3.1.dict.zip on a router-accessible volume with RIDDLE_HW4_STORE, omitting release bootstrap. The corpus builder generates a new immutable version only when source ZIP bytes change.

The remote service still requires an attached persistent MC0 volume and deployment of this branch; GitHub Actions cannot establish those live conditions. Without a persisted mount, keep-instantiated is not achieved.

## Runtime verification

- GET /healthz keeps its stable public status schema; mounting is visible through the authenticated HW4 status and existing fabric monitor.
- Authenticated worker-token GET /v1/riddle/hw4/status: immutable generation, digest, counts, route, ring ownership.
- Authenticated GET /v1/riddle/hw4/pair?a=0&b=1: direction-preserving pair record.
- Authenticated GET /v1/riddle/hw4/exact?synset=00001740-n: exact source pointers, not inferred semantic similarity.
- Existing fabric monitor: HW4:0 / wordnet-universe / active.

The HTTP attachment has no mutation API or main-ring trainer integration, and boot rejects explicitly configured missing or corrupted generations.

CI workflow: https://github.com/shemshallah/NaNROUTER/actions/workflows/hw4-full31.yml

Next gates: native NaN16/MTH read ABI (with explicit layout translation), clock and digest receipts, remote live health verification, memory/latency benchmarking, and source-disjoint use as a reference for mathematical sensor universes. WordNet is not a forced output pattern.
