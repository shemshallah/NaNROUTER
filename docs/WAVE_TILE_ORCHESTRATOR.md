# Wave tile orchestrator: 256-tile page window and atomic publication

Status: implemented in `runner_riddle/wave_tile_orchestrator.py`.
This is a pure Python host control plane for the R6 dense pair action. It
executes no NaN16 kernel, performs no host matrix mathematics, allocates no
dense matrix, and adds no database schema.

## 1. Why this layer exists

The bounded K16 pair-tile ABI computes one 16x16 tile of

```text
Y = L U + U L^T
```

per tile, with 16 K slices per tile. A complete 256x256 result is 256 tiles in
a deterministic 16x16 grid. The native kernels are already verified; what was
missing was the host-side contract that

- derives the 256 tile origins row-major,
- describes each tile through an existing K16/block16 descriptor,
- keeps the host page window to one input tile plus one accumulator/output
  tile plus one live descriptor,
- rejects a partial, duplicated, reordered, or stale publication, and
- produces one canonical manifest/digest only after all 256 tiles are present.

`runner_riddle/wave_tile_orchestrator.py` owns that contract. The caller still
owns the actual executor callback and the native call.

## 2. Files

| File | Role |
|---|---|
| `runner_riddle/wave_tile_orchestrator.py` | grid, page window, evidence, atomic publication |
| `tests/test_wave_tile_orchestrator.py` | deterministic grid, window, happy path, missing/duplicate/out-of-order/wrong-generation/executor-failure tests |
| `docs/WAVE_TILE_ORCHESTRATOR.md` | this document |

Existing modules (`mth_registry.py`, `wave_store.py`, `wave_service.py`,
`mth_system.py`, `runner_riddle/__init__.py`) are not modified.

## 3. Deterministic 16x16 tile grid

`TileGrid()` builds exactly 256 immutable `TileDescriptor` objects for one
256x256 operand:

```text
index = tile_row * 16 + tile_col       for tile_row, tile_col = 0..15
i_base = tile_row * 16
j_base = tile_col * 16
```

The order is row-major. Every descriptor is 16x16, has `word_count == 256`, and
carries the kernel ABI identifier plus its K-slice count. The default is the
bounded streaming ABI:

```text
mth.graph.pair.tile16.k16.f32   k_slices=16   guest workspace 1,542 words
```

Two additional descriptors are selectable through `kernel_id`. The supported
set is:

| Kernel ID | ABI entry | K slices | Guest workspace |
|---|---|---:|---:|
| `mth.graph.pair.tile16.k16.f32` | `mth_graph_pair_tile16_k16_accum_f32` | 16 | 1,542 words |
| `mth.graph.pair.tile16.f32` | `mth_graph_pair_tile16_f32` | 1 | 73,990 words |
| `mth.matvec256.block16.f32` | `mth_matvec256_block16` | 1 | 4,368 words |

The descriptor contains only origins and metadata. It does not contain tile
values, and the orchestrator never reads or writes a matrix.

`TileGrid.digest` is SHA-256 over the canonical JSON of the grid document.
Building the same grid twice yields the same digest.

## 4. Bounded host page window

`TilePageWindow` describes the host-side live window:

| Live object | Bound |
|---|---:|
| one 16x16 input window | 256 NaN16 words |
| one 16x16 accumulator/output window | 256 NaN16 words |
| one tile descriptor | 1 word (conservative accounting) |
| **`window_words`** | **513 words** |
| **`window_bytes`** | **4,104 bytes** |

The default guest budget is:

```text
1 MiB = 1,048,576 bytes = 131,072 NaN16 words
```

`window_words` is asserted against that budget by `TilePageWindow`,
`AtomicTilePublication`, and `TileOrchestrator`. The constructors raise
`TileWindowBudgetError` rather than relying on an `assert` statement.

This is the **host page window**, not the K16 guest working set. The K16 kernel
holds four 16x16 input blocks, two 16x16 accumulators, and six scratch words
inside the guest call (1,542 words total); that is the executor's contract.
The orchestrator also does not use the 7 GiB active-runner ceiling from
`wave_ring_scheduler`. The 1 MiB guest budget is the relevant bound here.

## 5. API

### Grid

```python
from runner_riddle.wave_tile_orchestrator import TileGrid

grid = TileGrid()                 # default bounded K16 descriptor
grid = TileGrid.build()
grid = TileGrid(kernel_id="mth.graph.pair.tile16.k16.f32")
first = grid[0]                   # TileDescriptor
assert len(grid) == 256
assert first.i_base == 0 and first.j_base == 0
assert grid[17].i_base == 16 and grid[17].j_base == 16
assert len(grid.digest) == 64
```

### Window

```python
from runner_riddle.wave_tile_orchestrator import TilePageWindow

window = TilePageWindow()
assert window.window_words == 513
assert window.window_bytes == 4104
assert window.guest_budget_bytes == 1024 * 1024
assert window.within_guest_budget
window.assert_within_guest_budget()
```

### Publication

```python
from runner_riddle.wave_tile_orchestrator import (
    AtomicTilePublication, TileEvidence, TileGrid,
)

grid = TileGrid()
publication = AtomicTilePublication(
    grid=grid,
    generation=7,
    plan_digest=grid.digest,       # or an external plan digest
)

for index in range(256):
    publication.add_tile(index, tile_digest[index])
    # Optional explicit provenance:
    # publication.add_tile(TileEvidence(
    #     tile_index=index,
    #     digest=tile_digest[index],
    #     generation=7,
    #     plan_digest=grid.digest,
    #     kernel_id=grid[index].kernel_id,
    #     k_slices=grid[index].k_slices,
    # ))

manifest = publication.publish()
assert manifest.tile_count == 256
assert manifest.digest == manifest.manifest_digest
document = manifest.to_dict()      # includes "manifest_digest"
```

Evidence must arrive in row-major order starting at tile 0. "Duplicate" means a
repeated tile index; identical digests at different tile indices are allowed
because distinct tiles may legitimately have equal output. The publication
rejects:

| Condition | Error |
|---|---|
| missing tile at `publish()` | `MissingTileError` |
| repeated tile index | `DuplicateTileError` |
| non-row-major tile index | `OutOfOrderTileError` |
| wrong generation | `GenerationMismatchError` |
| wrong plan digest | `PlanMismatchError` |
| wrong kernel or K-slice count | `KernelMismatchError` |
| evidence added after publish | `PublicationClosedError` |

A failed condition never yields a manifest. `publication.manifest` stays
`None`, `publication.published` stays `False`, and `publish()` raises again
while evidence is incomplete.

### Orchestrator

The orchestrator walks the grid in row-major order and calls the caller's
executor once per descriptor:

```python
from runner_riddle.wave_tile_orchestrator import TileOrchestrator

def executor(descriptor):
    # Caller-owned native bridge. It does not live in this module.
    # Return a 64-hex tile digest, raw output bytes, TileEvidence, or a
    # mapping with a "digest" key.
    return run_k16_tile_and_digest(descriptor.i_base, descriptor.j_base)

orchestrator = TileOrchestrator()
manifest = orchestrator.execute(
    executor,
    generation=7,
    plan_digest=orchestrator.digest,
)
```

The orchestrator does not inspect matrix values. If the executor raises, the
exception propagates unchanged and the publication remains open and
incomplete. In that case `publish()` cannot produce a partial manifest. A
later `execute(..., publication=publication)` call resumes at the first missing
tile instead of re-submitting evidence that is already present.

`TileOrchestrator.new_publication()` can be used to create the publication
before execution, then passed back through `execute(..., publication=...)`.
The orchestrator checks that the publication is bound to the same grid digest,
kernel, generation, and plan digest.

## 6. Canonical manifest

The final document is deterministic JSON with sorted keys and compact
separators, hashed with SHA-256. The example below is abridged after tile 0;
a real manifest contains all 256 tile entries.

```json
{
  "schema": "nanrouter.atomic-tile-publication.v1",
  "version": 1,
  "plan_digest": "<64 hex>",
  "generation": 7,
  "grid_digest": "<64 hex>",
  "kernel_id": "mth.graph.pair.tile16.k16.f32",
  "tile_count": 256,
  "tiles": [
    {
      "tile_index": 0,
      "tile_row": 0,
      "tile_col": 0,
      "digest": "<64 hex>",
      "generation": 7,
      "plan_digest": "<64 hex>",
      "kernel_id": "mth.graph.pair.tile16.k16.f32",
      "k_slices": 16,
      "note": ""
    }
  ],
  "window_words": 513,
  "window_bytes": 4104
}
```

`manifest.digest` is SHA-256 over `manifest.payload()`, which is this document
without the `manifest_digest` field. `manifest.to_dict()` adds the field.

## 7. Integration and boundaries

- The manifest digest is a suitable `result_digest` for
  `WaveService.complete_job(...)` or an evidence digest for
  `WaveService.store_seal(...)` / `store_signature(...)`. This module does not
  call the store or service itself.
- The module is not exported from `runner_riddle/__init__.py` because that is a
  shared file outside this change. Import it directly from
  `runner_riddle.wave_tile_orchestrator` until a shared-file integration pass
  adds the export.
- The executor callback is the only bridge to the native kernel. This module
  does not assemble or run `.nas` sources, manage native memory, fetch L row
  windows, or write output pages. Those remain caller/executor duties.
- No cancellation protocol is implemented. A caller that stops early simply
  leaves an incomplete publication that cannot publish.
- No new BS0DB/MC0DB table is defined. Published manifests are ordinary
  evidence payloads if the caller chooses to persist them.
- The K16 executor must still enforce increasing global K-slice order
  (0, 16, ..., 240) for each tile; the orchestrator enforces only tile order.

## 8. Tests

Run:

```bash
python -m unittest discover -s tests -p 'test_wave_tile_orchestrator.py' -v
```

The test file covers:

- exactly 256 row-major 16x16 descriptors and stable grid digest;
- alternate K16/full-U/block16 descriptor selection;
- one input window, one accumulator/output window, one descriptor, and the
  513-word / 4,104-byte host window inside the 1 MiB guest budget;
- the 256-tile happy path and canonical SHA-256 manifest digest;
- missing tile;
- duplicate tile;
- out-of-order tile;
- wrong generation and wrong plan digest;
- executor failure leaving no partial publication;
- post-publish closure and keyword/mapping evidence forms.
