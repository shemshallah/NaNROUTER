# File-backed MTH pair matrix pages

Status: local storage adapter implemented; tests exercise immutable input pages,
strip reconstruction, candidate output writes, digest verification, and
compare-and-swap publication. It is not yet connected to a deployed runner or
a real NaN16 guest process.

## Storage format

A 256×256 matrix is stored as 256 row-major 16×16 page files. Each page is
exactly 2,048 bytes: 256 little-endian 64-bit NaN16 words. An operator consists
of two matrices, L and U, plus an immutable JSON manifest containing every
page digest, matrix digest, page-set digest, and generation. Its operator
digest is SHA-256 over the canonical manifest core. Operator directories are
content-addressed and cannot be overwritten.

Layout:

```
<root>/
  CURRENT_OPERATOR.json
  operators/<operator-digest>/
    operator.json
    L/r000_c000.n16 ... r015_c015.n16
    U/r000_c000.n16 ... r015_c015.n16
  outputs/
    CURRENT_OUTPUT.json
    .publish.lock
    staging/<candidate-id>/tiles/
    generations/g00000000000000000005/
      generation.json
      tiles/r000_c000.n16 ... r015_c015.n16
```

The adapter is deliberately not wired to the existing Koyeb volume registry.
The caller chooses a root on a verified storage tier; the module never mounts,
formats, or mutates provider volumes.

## Read path

`pin_snapshot()` verifies the operator manifest and all 512 page files.
Each later `read_strip()` rechecks the relevant page hashes, so a page changed
after pinning aborts the execution. A row strip is assembled by joining the
sixteen 16×16 pages across each local row; a column strip concatenates the
sixteen row pages. Returned metadata binds every strip to the same generation,
operator digest, L/U matrix digest, and input page-set digest.

## Write and publication path

Output tiles are written only below `outputs/staging/<candidate-id>`.
The page-set digest covers all 256 row-major tile indices and their verified
content digests. Before publication, the adapter checks the complete tile
manifest and every tile digest. Under an exclusive filesystem lock it checks
the expected current generation, renames the complete candidate directory
into an immutable generation directory, then atomically replaces
`CURRENT_OUTPUT.json`. A stale publisher cannot advance the pointer.
Unpublished candidates can be discarded without touching the canonical head.

The output head must be initialized explicitly with
`initialize_output_head(generation=..., page_set_digest=...)` before the first
derived generation. This is an intentional guard against assuming an
unverified existing generation.

## Limits

This is a concrete local filesystem adapter, not an assertion that the
production matrices already exist in this format. The 64-bit word encoding
and page layout are now an explicit v1 interchange contract. The NaN16 guest
adapter still needs to load the staged strips into the documented guest
addresses and launch the K16 driver and full-U reference. Native 256-tile
execution remains unverified until that bridge is implemented and run.
