# Canonical physical mirror-memory layout

Status: field-level contract for the canonical physical mirror-memory profile,
`mirror-memory/v1`. It defines bytes, offsets and invariants. It does not by
itself claim a native implementation, a committed format, or a second authority.

The profile is one fixed **8,388,608-byte** (8 MiB) root: 256 fixed head records
and 32,640 unordered mirror-pair records. The pair record is shared by `(a,b)`
and `(b,a)`; the two directions are two 128-byte lanes in the same 256-byte
record.

One universe is represented by several views: this document defines the physical
byte layout; `spec/universe-map.json` is the generated virtual route view; the
C++ and PyTorch round prototypes are experiments over the same identities.
These views do not create a second universe, a second pair table, or a second
writer. The native guest remains the only authority permitted to mutate physical
cells. The route directory is a read-only projection; prototypes are not
canonical state.

## 1. Top-level geometry

| Region | Byte range (inclusive) | Size | Record | Count |
|---|---:|---:|---:|---:|
| head region | `0..32767` | 32,768 B | 128 B | 256 |
| pair region | `32768..8388607` | 8,355,840 B | 256 B | 32,640 |
| **total** | `0..8388607` | **8,388,608 B** | — | 32,896 records |

The regions are adjacent and exhaustive. There is no header, trailer, pointer
table, hyperedge arena, or variable-length payload inside the 8 MiB root.

```text
0x00000000  +--------------------------------------------------+
            | head 0      128 B                                 |
            | ...                                               |
0x00007F80  | head 255    128 B                                 |
0x00008000  +--------------------------------------------------+
            | pair id 1   256 B  (lane 0 | lane 1)             |
            | ...                                               |
0x007FFF00  | pair id 32640 256 B                               |
0x00800000  +--------------------------------------------------+
```

A head `h` starts at `head_offset(h) = 128 * h` for `h = 0..255`. A pair with
physical id `p` starts at `pair_offset(p) = 32768 + 256 * (p - 1)` for
`p = 1..32640`. The last pair starts at `0x007FFF00` and ends exactly at
`0x00800000`.

### Pair identity

For distinct heads `a` and `b`, with `a < b`:

```text
pair_id(a,b) = 1 + a * (511 - a) / 2 + (b - a - 1)
```

The division is exact integer arithmetic. Equivalently, with `N = 256`:
`pair_id(a,b) = 1 + a * (2*N - a - 1) / 2 + (b - a - 1)`.

Properties: `pair_id(a,b)` is in `1..32640`; `pair_id(a,b) = pair_id(b,a)`;
`pair_id(a,a)` is undefined because a diagonal is a fixed head, not a pair; `0`
is the void/sentinel id and is never a valid pair address.

The route view uses the zero-based *mirror-pair ordinal*
`mp = pair_id - 1` (`0..32639`) and the canonical cell
`canonical_cell = 256 + mp = 256 + pair_id - 1`.

## 2. Head record (128 bytes)

Each head record is 128 bytes, begins 8-byte aligned, and all multibyte fields
are little-endian. Fields do not cross record boundaries.

```text
byte 0                              byte 16                    byte 127
+---------+---------+---------+---------+---------------------------+
| first_  | state   | score   | genera- | reserved (112 bytes, zero) |
| hyper-  | u32     | f32     | tion    |                           |
| edge u32|         |         | u32     |                           |
+---------+---------+---------+---------+---------------------------+
  +0        +4        +8        +12       +16
```

| Offset | Size | Field | Type | Meaning |
|---:|---:|---|---|---|
| 0 | 4 | `first_hyperedge` | u32 | 0 = empty; otherwise a 1-based id in the external hyperedge arena |
| 4 | 4 | `state` | u32 | Opaque per-head state word; no bit assignment in v1 |
| 8 | 4 | `score` | f32 | Finite head score; interpretation is model-defined |
| 12 | 4 | `generation` | u32 | 0 = uninitialized; otherwise monotonic head generation |
| 16 | 112 | `reserved` (`identity` in the JSON schema) | bytes | Must be zero in v1; ignored on read |

`first_hyperedge` is an arena id, **not** an offset or pointer into the 8 MiB
profile. Head 0 is the NANNET0/control head in the route view; its record still
exists at offset 0. Role and access control are outside this layout.

## 3. Pair record (256 bytes)

Each pair record is 256 bytes, begins 8-byte aligned, and contains two
independently addressable 128-byte lanes.

```text
pair base + 0                                                       + 255
+--------------------------------+----------------------------------+
| lane 0: 128 bytes              | lane 1: 128 bytes                |
| low head -> high head          | high head -> low head            |
+--------------------------------+----------------------------------+
```

For canonical unordered pair `(a,b)` with `a < b`, lane 0 is the `a -> b`
orientation and lane 1 is the `b -> a` orientation. Both orientations use the
same record, id and metadata. A caller asking for `(b,a)` reads lane 1 first but
does not allocate a second record.

### 3.1 Lane 0 (`pair base + 0`)

| Offset | Size | Field | Type | Meaning |
|---:|---:|---|---|---|
| 0 | 104 | `residual[26]` | 26 x f32 | Learned residual vector, elements 0..25 |
| 104 | 4 | `relation_type` | u32 | 0 = untyped; otherwise a registry-defined relation type |
| 108 | 4 | `confidence` | f32 | Finite confidence; 0.0 means unset |
| 112 | 4 | `hyperedge_head` | u32 | 0 = empty; otherwise 1-based external arena id |
| 116 | 4 | `cycle_flux` | f32 | Finite root-0 fundamental circulation for this pair |
| 120 | 4 | `generation` | u32 | 0 = uninitialized; monotonic pair-record generation |
| 124 | 4 | `flags` | u32 | Bitmask; bit assignments are versioned; zero on a fresh record |

`residual[26]` means exactly 26 IEEE-754 binary32 values in declaration order.
The profile fixes their count, width and offsets; it does not fix a training
objective, class meaning, or normalization. Round 26 used these slots as
trainable class residuals; Round 27 reuses the root but trains hyperedge
strengths in the external arena. That is prototype semantics, not a new
authority.

`relation_type`, `confidence`, `generation` and `flags` describe the unordered
pair and are stored once, in lane 0, not duplicated in lane 1. `cycle_flux` is
stored once with the low-to-high sign convention; the high-to-low reading is
`-cycle_flux`.

### 3.2 Lane 1 (`pair base + 128`)

| Offset | Size | Field | Type | Meaning |
|---:|---:|---|---|---|
| 128 | 104 | `residual[26]` | 26 x f32 | Mirror residual vector, elements 0..25 |
| 232 | 24 | `reserved` | bytes | Must be zero in v1; ignored on read |

For an initialized pair, `lane1.residual[j] == -lane0.residual[j]` for
`j = 0..25`. The mirror is sign-opposite, not a byte-for-byte copy: a gradient
update that adds `-d` to lane 0 adds `+d` to lane 1. Lane 1 has no relation
type, confidence, hyperedge head, cycle flux, generation or flags of its own.

### 3.3 Pair field non-overlap

Within one pair record the defined intervals are disjoint and gapless:

```text
lane 0 residuals [0,104)   lane 0 metadata [104,128)
lane 1 residuals [128,232) lane 1 reserved [232,256)
```

No field may be widened into a reserved interval without a new profile version.

## 4. Alignment, endianness and word mapping

- Every head and pair record begins at an address divisible by 8.
- Every scalar field begins at an address divisible by 4; there are no 64-bit
  scalar fields in this profile.
- All u32 values are unsigned 32-bit little-endian (`0x01020304` is stored as
  `04 03 02 01`).
- All f32 values are IEEE-754 binary32, little-endian (`1.0f` is stored as
  `00 00 80 3F`).
- Unaligned multi-byte access is not part of the profile; consumers use
  record-relative fixed offsets. Stronger cache-line alignment is allowed but
  not required.

The physical profile is byte-addressed and does not interpret its bytes as NaN16
8-byte words. The virtual route view is word-addressed, so a pair record and a
virtual pair slot are different objects:

```text
physical pair p:  byte base = 32768 + 256 * (p - 1), size = 256 bytes
virtual mp = p - 1: page = mp % 255, word = 3840 + 2 * (mp // 255)
                    byte = 8 * (page * 4096 + word), slot = 2 words = 16 bytes
```

The virtual `offset_bytes` is **not** the physical offset. The virtual slot is an
address marker in the route map, not a 16-byte copy of the 256-byte record. The
shared identity is the pair ordinal, endpoint heads and canonical cell, not a
byte offset. For example, `(0,1)` is physical id 1 at byte 32768 but virtual
`mp` 0 at page 0/word 3840/byte 30720. `(254,255)` is physical id 32640 at byte
8388352 but virtual `mp` 32639 at page 254/word 4094/byte 8355824.

Head mapping is also view-specific: head `h` is at physical `128*h`, while head
1 is at virtual page 0/word 0, head 255 at page 254/word 0, and head 0 at page
255/word 0. Equal physical and virtual offsets are accidental, never invariant.

## 5. One universe, alternative views, no second authority

| View | Encoding | What it defines | Authority |
|---|---|---|---|
| Physical profile | bytes, fixed offsets | head/pair records, lanes, fields | this document; mutation only through the native guest |
| Virtual route view | 256 x 32 KiB pages, 8-byte words | 256 head points, 32,640 MP points, routes and canonical cells | generated read-only projection (`spec/universe-map.json`, `runner_riddle/universe_map.py`) |
| C++ prototypes | dense root plus external arenas | experimental mirror geometry, hyperedges, gradients | non-authoritative experiment |
| PyTorch prototypes | host tensors over selected native rows | differentiable loss on gathered slices | non-authoritative experiment; gradients scattered back through native calls |

`spec/universe-map.json` is generated by `tools/gen_universe_map.py`. It records
256 page descriptors and a relation-point summary: 256 fixed heads, 32,640
mirror pairs, 32,896 total points, with `head 0 = page 255 = ring 255 = HW0:0`.
Its SHA-256 is `9a836c5523b8fe356a14fb663eb7ffa5d08b7ee0975a01dd9844b59b07b389c4`
for the current directory. The exhaustive resolver remains
`runner_riddle/universe_map.py`; the JSON is a projection, not the physical map.

The C++/PyTorch prototypes do not define the canonical profile:

- Round 23 uses the same 8 MiB geometry but only the first f32 of each lane and
  a cached flux at lane offset 4; it has no canonical metadata block.
- Round 24 writes the first hyperedge/membership link at lane-0 offset 8, not
  the canonical offset 112.
- Round 26 stores 26 trainable f32 residuals in lane 0 and mirrors them in lane
  1, and writes a hyperedge head at offset 112. It does not exercise relation
  type 104, confidence 108, canonical flux 116, generation 120 or flags 124.
- Round 27 adds differentiable hyperedge strengths in an external arena; it
  still does not make the canonical metadata block a persisted contract.
- The PyTorch layers are host-side training wrappers. They do not own a second
  root and do not create a second pair table.

## 6. Round 23/24/26/27 capability status

Measurements below are from the external round archives, not a NaNROUTER CI run;
they are local single-process prototype results.

| Round | Capability | Measured evidence | Design-only or limit |
|---|---|---|---|
| 23 | 8 MiB head/pair geometry | `sizeof(Universe) == 8,388,608`; 32,640 pair ids; 65,280 directed mappings checked; handle 0 void | no canonical 104..127 metadata; only first lane f32 used |
| 23 | flux and Hodge geometry | 32,385 root-0 circulations; Hodge 1.032382 ms; max divergence `8.841743693e-07`; gauge/flux deltas `2.384185791e-07` | one local CPU run; not Android/Termux; derived values, not new information |
| 24 | recursive hyperedges | 200,002 hyperedges, 15,388 concepts, 600,006 member links; 8 MiB root stable; append 33.2045 ms; 100k pair lookups 0.7149 ms; 100k incidence walks 54.9582 ms; 16,325,600 B arena | arena outside the 8 MiB root; single writer; +8 link is not canonical +112 |
| 26 | native residual training | 26 f32 residuals; 100,000 hyperedges in 0.302041613 s; `mlock` success; snapshot 10,388,644 B; restore pass; 30,000 WordNet pointers / 11 relation types | residuals are hashed class logits; tiny non-capacity-matched loss change; no joint relation training |
| 26 | three-seed WordNet result | 3,713 train / 578 validation / 801 test; mean CE plain 2.254254, cycle 2.252887, hashcontrol 2.254144; 350 updates/seed | not a learning-gain claim; no held-out semantic generalization established |
| 27 | native hyperedge-strength training | 1,280 hyperedges; 512 train / 128 untouched queries; train 100% / 0.03951 loss; untouched 50% / 0.71914; ablated 0.83699; relative gradient error `4.2495e-04`; invalid batch atomic; snapshot restore | synthetic path labels; no untouched-path generalization; single writer |
| 23–27 | canonical 104..127 metadata | only offset 112..115 was exercised by R26/R27 | type, confidence, canonical flux, generation and flags are profile design, not measured prototype capability |

## 7. Invariants

1. `sizeof(profile) == 8,388,608`; every byte belongs to exactly one region.
2. Head region is `[0,32768)`, pair region is `[32768,8388608)`, adjacent.
3. Exactly 256 head records of 128 bytes and 32,640 pair records of 256 bytes.
4. Pair ids are exactly `1..32640`; id 0 is a void sentinel and never decoded.
5. `pair_id(a,b) = pair_id(b,a)`; the inverse decode returns the same unordered endpoints and a valid `a < b` ordering.
6. A pair record's lane 0 is the `a < b` direction and lane 1 the `b < a` direction.
7. Head fields occupy `[0,16)`; head `[16,128)` is reserved zero.
8. Lane 0 fields occupy `[0,128)`; lane 1 fields occupy `[128,256)`; the intervals in section 3.3 do not overlap.
9. Every initialized pair satisfies `lane1.residual[j] == -lane0.residual[j]` for `j = 0..25`.
10. `relation_type`, `confidence`, `hyperedge_head`, `cycle_flux`, `generation` and `flags` are stored once per pair, in lane 0.
11. `hyperedge_head == 0` means empty; a nonzero value is a validated external arena id, never a raw pointer.
12. `generation == 0` means uninitialized; otherwise mutations advance it monotonically and never wrap silently.
13. All reserved bytes are zero on write and ignored on read.
14. All u32/f32 fields are little-endian; f32 is IEEE-754 binary32.
15. Physical offsets and virtual route offsets are independent projections of the same 256/32,640 identity space.

## 8. Validation checklist

Use this as a conformance test, not as evidence that a runtime exists.

- [ ] Static size: `8,388,608` total; `32,768 + 8,355,840` region sum.
- [ ] Static records: head `128`, pair `256`, lane `128`.
- [ ] Static fields: every offset/size in sections 2 and 3 matches; no field crosses `128` or `256`.
- [ ] Alignment: every record base is `% 8 == 0`; every scalar is `% 4 == 0`.
- [ ] Endianness: known u32 and f32 round trips produce section 4 byte order.
- [ ] Exhaustive pair ids: all 32,640 unordered pairs produce unique ids `1..32640`; all ids decode back; no id 0 is produced.
- [ ] Symmetry: `pair_id(a,b) == pair_id(b,a)` for all `a < b`.
- [ ] Orientation: `(a,b)` exposes lane 0 forward and lane 1 reverse; `(b,a)` exposes the same record with the lanes swapped.
- [ ] Offsets: `pair_offset(p) = 32768 + 256*(p-1)`; last pair ends at `8,388,608`; `head_offset(h) = 128*h`; last head ends at `32,768`.
- [ ] Mirror: after an update, lane 1 residuals are the exact sign negatives of lane 0 residuals; metadata is unchanged.
- [ ] Metadata: relation type 0 is untyped; confidence is finite; generation is monotonic; flags reserve unassigned bits.
- [ ] Arena: every nonzero `first_hyperedge` / `hyperedge_head` id is validated against the external arena before dereference; zero is empty.
- [ ] Route view: for each `mp`, `pair_id = mp + 1`, canonical cell = `256 + mp`, virtual page = `mp % 255`, virtual word = `3840 + 2*(mp // 255)`; no virtual offset is used as a physical offset.
- [ ] Projection: regenerate `spec/universe-map.json` with `python3 tools/gen_universe_map.py --check`; 256 pages, 32,896 points.
- [ ] Reserved: all reserved bytes are zero in a fresh root and remain zero after normal updates.
- [ ] One writer: no two writers mutate the same record without an external generation/CAS protocol; torn records are rejected.

## 9. Non-claims

- This document does not claim that the canonical 104..127 metadata block is implemented, persisted, or accepted by the native guest.
- It does not claim that the C++ or PyTorch prototypes are the canonical format, a second authority, or a production runtime.
- It does not claim that physical offsets and virtual route offsets coincide.
- The Round 23/24/26/27 numbers are local prototype measurements, not Android, Termux, multi-seed, or CI performance claims.
- No prototype result establishes language understanding, semantic generalization, or a benefit over a capacity-matched ordinary graph.
- No result claims physical quantum behavior, quantum speedup, or NaN arithmetic; the profile stores ordinary little-endian f32/u32 values.
- No confidence value is claimed calibrated, and no relation-type ontology is defined here.
- No claim is made about crash safety, concurrency, cross-platform portability, or snapshot durability of the prototypes.
- No claim is made that `mlock` succeeds on Android or that the 8 MiB root is pinned in CPU cache.
- The route view executes no mathematics and does not make a relation true, authorized, or native-verified.

## 10. References

- `docs/MIRROR_POINT_REGISTER.md` — 256 heads, 32,640 MP microtables, rank/unrank.
- `docs/MTH_UNIFIED_SYSTEM.md` — full 8 MiB virtual universe map and route law.
- `spec/universe-map.json` — generated 256-page route directory.
- `runner_riddle/universe_map.py` — exhaustive virtual point resolver.
- `runner_riddle/mirror_point_register.py` — pair identity and topology digest.
- Round 23/24/26/27 archives — C++/PyTorch prototype sources and results; not
  part of the canonical runtime.
