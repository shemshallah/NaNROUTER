# Mirror points: HW0 heads, HW0:MP microtables and one native 8 MiB universe

**Implemented in NaNROUTER**: `runner_riddle/mirror_point_register.py` and `runner_riddle/address.py`. This extends the canonical `docs/GAME_PLAN_::.md §4.4a` 16-bit space without allocating fake extra NaN16 cells or treating every MP as a hardware head.

## Four synchronized planes

| Plane | Address / owner | State | Purpose |
| --- | --- | --- | --- |
| 0: topology | NaNROUTER process-resident algebra | immutable | 256 fixed heads + C(256,2) mirror pairs |
| 1: leaf directory | MC0DB existing `math_mapping`, BS0DB immutable leaf versions | versioned / CAS | MP ordinal → typed data leaf, provenance and generation |
| 2: master scratch projection | router-generated bounded digest pages; HERMES chart scratch recipient | derived, non-authoritative | distribute MP→head→leaf associations |
| 3: physical universe | existing one native 8 MiB `Chart8MiB` / GlobalTopology | canonical-guest owned | NaN dual rails, per-head scratch, physical cells |

This is **not four minds**. It is four views of **one universe** with deliberately different writers. NaNROUTER creates topology by math, not by a 32,640-file JSON dump. A head may propose a new binding for an MP it belongs to; NaNROUTER/MC0DB validates current mapping CAS and the leaf's prior existence. Only the native guest may mutate head scratch; mathematical rules still require MTH/NMP preflight and independent promotion.

## Frozen route syntax

```text
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0::HW0:7
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0::HW0:MP123
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0::HW0:7::HW0:MP123
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0::HW0:MP0-32639
```

`HW0:0` in the root is the **network/boot port**, not a trainable 256th head. A selector `HW0:7` is a writable learning head, whereas `HW0:MP123` is a **mirror-pair leaf-routing node**. Range `MP0-32639` is a symbolic address range, **not a request to eagerly retrieve 32,640 leaves**; retrieval must be paginated. A head-prefixed MP route is accepted only when the head is one of the pair's actual endpoints. A bare MP route resolves both directions. An MP pointer is not a `math://` linker operation.

## Exact microtable

For `MPn`, invert the lexicographic unordered-pair rank: `n = a(511-a)/2 + (b-a-1)` with `0 <= a < b <= 255`. Then the two directional NaN16 addresses are:

```text
forward  = (a << 8) | reverse8(b)
mirror   = (b << 8) | reverse8(a) = reverse16(forward)
canonical_cell = 256 + n
canonical_address = forward
optional leaf = existing MC0DB mapping("palpair:v1:%05d" % n)
```

The in-memory 65,536-entry `uint16` index takes **128 KiB**, plus 32,896-entry inverse `uint16` canonical map (**65,792 bytes**). It covers 256 palindrome fixed cells exactly once and each of the 32,640 mirror pairs twice, i.e. `256+2×32640=65536`. All 256 fixed heads have their own microtable and palindromic NaN address, distinct from leaf-bearing MPs. 0 cannot request native head mutation. No 8 MiB duplicate.

A linked leaf is **not stored directly in the 16-bit address**: the MP microtable points at a versioned `MathLeaf` identity in MC0DB/BS0DB. Two directions link to the same leaf pointer but preserve head-specific route/ACL. To update a learned association, submit a source-head proposal with current expected mapping version/generation. MathStore checks that the leaf exists and digest matches, applies CAS and retains events. Changing the leaf's semantics requires a legitimate versioned MathLeaf update, never silent overwrite of cell bytes.

## Scratch distribution

`MirrorLeafDirectory.master_page` prepares up to 100 MP microtable bindings per page, with per-head link counts, chart parent root and generation, topology SHA-256 and SHA-256 page integrity. **This is a projection**, not a signed native receipt. The recipient HERMES master-scratch register must check canonical parent, generation, topology digest and the router-authenticated delivery/lease before it stages the bytes; it cannot use the projection to bypass NaN16 guest `nh_get`/`nh_put`. The 8 MiB universe stays source of the physical cells and their NaN faces.

## Verification

Tests cover all 65,536 ordered raw address routes and all 32,640 MP rank/unrank microtables, parser normalization/range and ACL rejection, one leaf binding shared between both directions, stale CAS failure, NANNET0 denial and bounded read-only master projection. Run `python -m unittest tests.test_mirror_point_register` and existing `tests.test_address_v2`; CI remains authoritative.
