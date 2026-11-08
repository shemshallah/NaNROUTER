# File-backed universe pages

Status: implemented in `runner_riddle/math_page_files.py`; tests in
`tests/test_math_page_files.py` (11 tests).

This is the byte-storage companion to the durable page records in
`runner_riddle/math_store.py` (`docs/MATH_PAGE_RECORDS.md`). The store owns page
identity, immutable leaf binding, generations, and the page-map digest. This
module owns one fixed 32 KiB file per page and verifies the file against the
record before returning bytes.

## Format

Each page is exactly `32768` bytes. The canonical filename is:

```
page-<page_id:03d>-<leaf_digest>-<content_digest>.page
```

| Component | Meaning |
|---|---|
| `page_id` | Fixed universe position `0..255` |
| `leaf_digest` | Immutable `leaf_digest` from the durable page record |
| `content_digest` | SHA-256 of the exact 32 KiB file bytes |

Both digests are 64 lowercase hexadecimal characters. Page 255 is the NANNET0
node page; pages 0..254 are head pages. The page id is not a lane, runner slot,
or head index for page 255.

The filename is validated, not trusted. A read also checks that:

- the file is exactly 32 KiB;
- the SHA-256 of the bytes equals the `content_digest` in the filename;
- the page id and leaf digest match the caller's record or filter;
- the path is a direct child of the configured root and is not a symlink.

Malformed names, out-of-range page ids, traversal components, uppercase or
short digests, corrupt content, truncation, oversize files, symlinks, and
missing files fail closed with typed errors.

## API

```python
from runner_riddle.math_page_files import MathPageFileProvider

provider = MathPageFileProvider(root)
```

`root` is caller-supplied and is only created on a write. Read-only loads do not
create or repair the directory.

```python
provider.page_filename(page_id, leaf_digest, content_digest) -> str
provider.page_path(page_id, leaf_digest, content_digest) -> Path

provider.write_page(page_id, data, *, leaf_digest, digest=None) -> dict
provider.pin_page_record(record, data, *, digest=None) -> dict
provider.read_page(page_id, digest, *, leaf_digest=None) -> bytes
provider.load_page(page_id, digest, *, leaf_digest=None) -> dict
provider.read_page_record(record) -> bytes
provider.load_page_record(record) -> dict

provider.list_page_files() -> list[dict]
provider.find_page_files(page_id, *, leaf_digest=None,
                         content_digest=None) -> list[dict]
provider.verify_page_map(store, *, expected_digest=None,
                         strict_files=True) -> dict
```

`MathPageFileStore` is an alias for `MathPageFileProvider`.

`write_page` accepts `bytes`, `bytearray`, or `memoryview`, requires exactly
32 KiB, and rejects a caller-supplied `digest` if it is not the SHA-256 of the
data. `pin_page_record` validates the record's `page_id`, `kind`, `page_key`,
`leaf_digest`/`digest`, and optional `page_digest`, then writes the file bound
to the record's leaf digest. `read_page_record` and `load_page_record` locate
the unique file for that page/leaf binding and verify it before returning.

The returned file record has schema `nanrouter.math-page-file.v1` and includes
`page_id`, `page_key`, `kind`, `leaf_digest`, `content_digest`, `size_bytes`,
`filename`, `path`, and `reused`. A replay of the same page/leaf/content returns
`reused=True`. The same page and leaf binding with different bytes is rejected
as a conflict and the original file remains readable.

## Atomic publication

A write:

1. validates the page id, leaf digest, size, and optional content digest;
2. checks whether the page/leaf binding already exists;
3. writes to a temporary file in the same directory;
4. flushes and `fsync`s the temporary file;
5. publishes with `os.replace`;
6. `fsync`s the containing directory.

A failure before `os.replace` leaves no canonical page file. The temporary file
is removed in all paths. Readers only see a complete destination file.

## Page-map verification

`verify_page_map(store, expected_digest=...)` loads the live
`MathStore.page_map()` document, recomputes its canonical digest, optionally
compares it to `expected_digest`, and verifies the file for every non-empty page
slot. It returns schema `nanrouter.math-page-file-set.v1` with the verified page
map digest, page ids, page count, NANNET0 identity, page size, and file records.

With `strict_files=True` (the default), every page file under the root must be
bound by a page in the current map. A stale file left after the page map changed
its leaf binding, or a file for a page absent from the map, is rejected. This
makes the file set and the content-scoped page-map digest agree.

Operational page churn (pin, release, state change) does not change the
page-map digest or file names. Binding a different leaf or operator version
does, which is the intended cache-invalidation hook.

## Errors

All errors derive from `MathPageFileError`, which derives from
`MathPageError`. Bounds errors also derive from `MathPageBoundsError`, and
missing-file errors also derive from `MathReferenceError`.

| Error | Cause |
|---|---|
| `MathPageFileBoundsError` | Page id outside `0..255`, including booleans and non-integers |
| `MathPageFileDigestError` | Malformed digest, digest mismatch, or corrupt bytes |
| `MathPageFileMapDigestError` | Page-map document or expected digest mismatch |
| `MathPageFileSizeError` | File or supplied data is not exactly 32 KiB |
| `MathPageFileMissingError` | Root or page file is unavailable |
| `MathPageFileConflictError` | Ambiguous files, immutable page/leaf rebinding, or stale/unbound files |

## Non-claims and limitations

- This is not a provider-mounted 8 MiB universe, filesystem formatter, or
  distributed volume. The caller owns the root and its storage policy.
- Page bytes are opaque. The module never parses, evaluates, executes, or
  performs host arithmetic on them. It does not allocate guest memory.
- The file content digest does not prove that a page is numerically correct; it
  only proves that the stored bytes are the bytes that were published under that
  digest.
- A page file is bound to the page record's leaf digest, not to the record's
  `page_digest` snapshot digest. `verify_page_map` checks the live page-map
  bindings, not the historical generation snapshot.
- Publication is atomic per file. It does not publish a 256-file set in one
  transaction and does not coordinate with a concurrent `MathStore` mutation.
  A caller that needs a cross-store barrier should use the existing commit
  intent protocol and verify the page map after the store transaction.
- No secrets, credentials, signatures, or encryption keys are stored or read.
