"""Immutable file-backed 32 KiB universe page files.

The durable page-record layer in :mod:`runner_riddle.math_store` owns page
identity, leaf binding, generations, and the page-map digest.  This module adds
the missing byte storage without replacing or reinterpreting that layer:

* one fixed-size ``32768`` byte page file per stored page;
* the filename binds the page position (0..255), the page record's immutable
  leaf digest, and the SHA-256 digest of the file bytes;
* publication is a temp-file write, ``fsync``, and ``os.replace`` in the same
  directory, so a reader never observes a partial page;
* loading is read-only and re-verifies size, filename binding, and content
  digest before returning bytes.

This is deliberately *not* a provider mount, a formatter, a scheduler, or an
executor.  The caller supplies a root directory on the desired storage tier.
Page bytes are opaque: they are never parsed, evaluated, executed, or used for
host arithmetic.  No token, credential, or secret is written or read here.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import os
import re
import tempfile
from typing import Any, Mapping

from .math_objects import canonical_json, sha256_text
from .math_store import (
    DEFAULT_PAGE_BYTES,
    HEAD_PAGE_COUNT,
    NANNET0_PAGE_ID,
    PAGE_COUNT,
    PAGE_MAP_SCHEMA,
    MathPageBoundsError,
    MathPageError,
    MathReferenceError,
)

PAGE_FILE_SCHEMA = "nanrouter.math-page-file.v1"
PAGE_FILE_SET_SCHEMA = "nanrouter.math-page-file-set.v1"
PAGE_FILE_BYTES = DEFAULT_PAGE_BYTES
PAGE_FILE_PREFIX = "page-"
PAGE_FILE_SUFFIX = ".page"
PAGE_FILE_PATTERN = re.compile(
    r"^page-([0-9]{3})-([0-9a-f]{64})-([0-9a-f]{64})\.page$"
)


class MathPageFileError(MathPageError):
    """Base error for file-backed universe page storage."""


class MathPageFileBoundsError(MathPageFileError, MathPageBoundsError):
    """A page position is outside the fixed 0..255 universe page map."""


class MathPageFileDigestError(MathPageFileError):
    """A page file digest is malformed or does not match its bytes."""


class MathPageFileMapDigestError(MathPageFileDigestError):
    """A page map or page-map digest does not match the stored file set."""


class MathPageFileSizeError(MathPageFileError):
    """A page file is not exactly one 32 KiB universe page."""


class MathPageFileMissingError(MathPageFileError, MathReferenceError):
    """A page file is missing from the configured root."""


class MathPageFileConflictError(MathPageFileError):
    """A page binding already names different bytes or an unbound file exists."""


def _require_page_id(name: str, value: Any) -> int:
    if (isinstance(value, bool) or not isinstance(value, int)
            or value < 0 or value >= PAGE_COUNT):
        raise MathPageFileBoundsError(
            f"{name} must be an integer in 0..{PAGE_COUNT - 1} "
            "(255 is the NANNET0 page, not a lane)"
        )
    return value


def _require_digest(name: str, value: Any) -> str:
    if (not isinstance(value, str) or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)):
        raise MathPageFileDigestError(
            f"{name} must be 64 lowercase hexadecimal characters"
        )
    return value


def _page_kind(page_id: int) -> str:
    return "nannet0" if page_id == NANNET0_PAGE_ID else "head"


def _page_key(page_id: int) -> str:
    return f"page:{page_id:03d}"


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _validate_record(record: Mapping[str, Any]) -> tuple[int, str, str, str | None]:
    """Validate a MathStore page record or page-map slot."""
    if not isinstance(record, Mapping):
        raise MathPageFileError("page record must be a mapping")
    if "page_id" not in record:
        raise MathPageFileError("page record requires page_id")
    page_id = _require_page_id("page_id", record["page_id"])
    leaf_digest = record.get("leaf_digest")
    alias_digest = record.get("digest")
    if leaf_digest is None:
        leaf_digest = alias_digest
    if leaf_digest is None:
        raise MathPageFileError("page record requires leaf_digest")
    leaf_digest = _require_digest("leaf_digest", leaf_digest)
    if alias_digest is not None:
        alias_digest = _require_digest("digest", alias_digest)
        if alias_digest != leaf_digest:
            raise MathPageFileConflictError(
                "page record leaf_digest and digest disagree"
            )
    kind = _page_kind(page_id)
    declared_kind = record.get("kind")
    if declared_kind is not None and declared_kind != kind:
        raise MathPageFileConflictError(
            f"page {_page_key(page_id)} is {kind!r}, not {declared_kind!r}"
        )
    declared_key = record.get("page_key")
    if declared_key is not None and declared_key != _page_key(page_id):
        raise MathPageFileConflictError(
            f"page_id {page_id} does not match page_key {declared_key!r}"
        )
    page_digest = record.get("page_digest")
    if page_digest is not None:
        page_digest = _require_digest("page_digest", page_digest)
    return page_id, leaf_digest, kind, page_digest


class MathPageFileProvider:
    """Read/write fixed 32 KiB page files under a caller-supplied root.

    Filename format::

        page-000-<leaf_digest>-<content_digest>.page

    The zero-padded page id is the fixed universe position, ``leaf_digest`` is
    the immutable digest from the durable page record, and ``content_digest``
    is SHA-256 over the exact ``32768`` file bytes.  Both digests are lowercase
    hexadecimal.  No caller-controlled path segment is accepted.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)

    # -- naming / validation -------------------------------------------------

    @staticmethod
    def page_filename(page_id: int, leaf_digest: str,
                      content_digest: str) -> str:
        """Return the canonical filename for one bound page file."""
        page_id = _require_page_id("page_id", page_id)
        leaf_digest = _require_digest("leaf_digest", leaf_digest)
        content_digest = _require_digest("content_digest", content_digest)
        return (
            f"{PAGE_FILE_PREFIX}{page_id:03d}-{leaf_digest}-"
            f"{content_digest}{PAGE_FILE_SUFFIX}"
        )

    def page_path(self, page_id: int, leaf_digest: str,
                  content_digest: str) -> Path:
        """Return the canonical path, validating every filename component."""
        return self.root / self.page_filename(
            page_id, leaf_digest, content_digest,
        )

    @staticmethod
    def _parse_filename(name: str) -> tuple[int, str, str]:
        match = PAGE_FILE_PATTERN.fullmatch(name)
        if match is None:
            raise MathPageFileError(
                f"page file name {name!r} is not canonical"
            )
        page_id = int(match.group(1))
        if page_id >= PAGE_COUNT:
            raise MathPageFileBoundsError(
                f"page file name {name!r} has page id {page_id} outside "
                f"0..{PAGE_COUNT - 1}"
            )
        return page_id, match.group(2), match.group(3)

    @staticmethod
    def _file_record(path: Path, page_id: int, leaf_digest: str,
                     content_digest: str) -> dict[str, Any]:
        return {
            "schema": PAGE_FILE_SCHEMA,
            "page_id": page_id,
            "page_key": _page_key(page_id),
            "kind": _page_kind(page_id),
            "leaf_digest": leaf_digest,
            "content_digest": content_digest,
            "size_bytes": PAGE_FILE_BYTES,
            "filename": path.name,
            "path": str(path),
        }

    def _contained_path(self, path: Path) -> Path:
        """Reject symlinks and any path that escapes the configured root."""
        if path.is_symlink():
            raise MathPageFileError(
                f"page file {path.name!r} must not be a symlink"
            )
        try:
            root = self.root.resolve(strict=True)
        except OSError as exc:
            raise MathPageFileMissingError(
                "page file root is unavailable"
            ) from exc
        resolved = path.resolve(strict=False)
        if resolved.parent != root:
            raise MathPageFileError(
                f"page file {path.name!r} escapes the configured root"
            )
        return resolved

    # -- discovery -----------------------------------------------------------

    def list_page_files(self) -> list[dict[str, Any]]:
        """List canonical page files without reading their contents."""
        if not self.root.exists():
            return []
        if not self.root.is_dir():
            raise MathPageFileError("page file root is not a directory")
        files: list[dict[str, Any]] = []
        for entry in sorted(self.root.iterdir(), key=lambda item: item.name):
            if not entry.name.startswith(PAGE_FILE_PREFIX):
                continue
            if not entry.name.endswith(PAGE_FILE_SUFFIX):
                continue
            page_id, leaf_digest, content_digest = self._parse_filename(
                entry.name
            )
            files.append(self._file_record(
                entry, page_id, leaf_digest, content_digest,
            ))
        return files

    def find_page_files(self, page_id: int, *,
                        leaf_digest: str | None = None,
                        content_digest: str | None = None) -> list[dict[str, Any]]:
        """Find files matching a page id and optional digest bindings."""
        page_id = _require_page_id("page_id", page_id)
        if leaf_digest is not None:
            leaf_digest = _require_digest("leaf_digest", leaf_digest)
        if content_digest is not None:
            content_digest = _require_digest(
                "content_digest", content_digest,
            )
        matches = []
        for record in self.list_page_files():
            if record["page_id"] != page_id:
                continue
            if (leaf_digest is not None
                    and record["leaf_digest"] != leaf_digest):
                continue
            if (content_digest is not None
                    and record["content_digest"] != content_digest):
                continue
            matches.append(record)
        return matches

    # -- verified read -------------------------------------------------------

    def _read_verified(self, path: Path, *, page_id: int,
                       leaf_digest: str,
                       content_digest: str) -> tuple[bytes, dict[str, Any]]:
        parsed_id, parsed_leaf, parsed_content = self._parse_filename(path.name)
        if parsed_id != page_id:
            raise MathPageFileConflictError(
                f"page file {path.name!r} belongs to page {parsed_id}, "
                f"not {page_id}"
            )
        if parsed_leaf != leaf_digest:
            raise MathPageFileConflictError(
                f"page file {path.name!r} is bound to a different leaf digest"
            )
        if parsed_content != content_digest:
            raise MathPageFileConflictError(
                f"page file {path.name!r} has a different content digest"
            )
        resolved = self._contained_path(path)
        try:
            data = resolved.read_bytes()
        except FileNotFoundError as exc:
            raise MathPageFileMissingError(
                f"page file {path.name!r} is missing"
            ) from exc
        except OSError as exc:
            raise MathPageFileError(
                f"page file {path.name!r} cannot be read"
            ) from exc
        if len(data) != PAGE_FILE_BYTES:
            raise MathPageFileSizeError(
                f"page file {path.name!r} has {len(data)} bytes; "
                f"expected exactly {PAGE_FILE_BYTES}"
            )
        actual = hashlib.sha256(data).hexdigest()
        if actual != parsed_content:
            raise MathPageFileDigestError(
                f"page file {path.name!r} content digest mismatch: {actual}"
            )
        record = self._file_record(
            path, parsed_id, parsed_leaf, parsed_content,
        )
        return data, record

    def _single_file(self, page_id: int, *, leaf_digest: str | None = None,
                     content_digest: str | None = None) -> dict[str, Any]:
        matches = self.find_page_files(
            page_id, leaf_digest=leaf_digest, content_digest=content_digest,
        )
        if not matches:
            raise MathPageFileMissingError(
                f"page {_page_key(page_id)} has no matching page file"
            )
        if len(matches) != 1:
            raise MathPageFileConflictError(
                f"page {_page_key(page_id)} has {len(matches)} ambiguous "
                "page files"
            )
        return matches[0]

    def read_page(self, page_id: int, digest: str, *,
                  leaf_digest: str | None = None) -> bytes:
        """Read and verify one page file.

        ``digest`` is the expected SHA-256 of the exact 32 KiB file bytes.
        ``leaf_digest`` optionally narrows the binding to the page record's
        immutable leaf digest.  Missing, ambiguous, corrupt, oversized,
        undersized, or symlinked files raise a typed error.
        """
        page_id = _require_page_id("page_id", page_id)
        content_digest = _require_digest("digest", digest)
        if leaf_digest is not None:
            leaf_digest = _require_digest("leaf_digest", leaf_digest)
        record = self._single_file(
            page_id, leaf_digest=leaf_digest,
            content_digest=content_digest,
        )
        data, _ = self._read_verified(
            Path(record["path"]),
            page_id=page_id,
            leaf_digest=record["leaf_digest"],
            content_digest=content_digest,
        )
        return data

    def load_page(self, page_id: int, digest: str, *,
                  leaf_digest: str | None = None) -> dict[str, Any]:
        """Read one page file and return its verified metadata plus bytes."""
        page_id = _require_page_id("page_id", page_id)
        content_digest = _require_digest("digest", digest)
        if leaf_digest is not None:
            leaf_digest = _require_digest("leaf_digest", leaf_digest)
        record = self._single_file(
            page_id, leaf_digest=leaf_digest,
            content_digest=content_digest,
        )
        data, verified = self._read_verified(
            Path(record["path"]),
            page_id=page_id,
            leaf_digest=record["leaf_digest"],
            content_digest=content_digest,
        )
        verified["data"] = data
        return verified

    # -- page-record binding -------------------------------------------------

    def write_page(self, page_id: int, data: bytes | bytearray | memoryview, *,
                   leaf_digest: str,
                   digest: str | None = None) -> dict[str, Any]:
        """Atomically publish one 32 KiB page file bound to ``leaf_digest``.

        ``digest`` is an optional expected SHA-256 of ``data``; a mismatch is
        rejected before anything is written.  An existing page/leaf binding is
        immutable: the same bytes are reused, different bytes are a conflict.
        """
        page_id = _require_page_id("page_id", page_id)
        leaf_digest = _require_digest("leaf_digest", leaf_digest)
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise MathPageFileError("page data must be bytes")
        blob = bytes(data)
        if len(blob) != PAGE_FILE_BYTES:
            raise MathPageFileSizeError(
                f"page data has {len(blob)} bytes; expected exactly "
                f"{PAGE_FILE_BYTES}"
            )
        content_digest = hashlib.sha256(blob).hexdigest()
        if digest is not None:
            digest = _require_digest("digest", digest)
            if digest != content_digest:
                raise MathPageFileDigestError(
                    f"declared page digest {digest} does not match content "
                    f"digest {content_digest}"
                )

        existing = self.find_page_files(
            page_id, leaf_digest=leaf_digest,
        )
        if existing:
            if len(existing) != 1:
                raise MathPageFileConflictError(
                    f"page {_page_key(page_id)} leaf binding has "
                    f"{len(existing)} files"
                )
            record = existing[0]
            if record["content_digest"] != content_digest:
                raise MathPageFileConflictError(
                    f"page {_page_key(page_id)} leaf binding is immutable "
                    "and already names different bytes"
                )
            self._read_verified(
                Path(record["path"]),
                page_id=page_id,
                leaf_digest=leaf_digest,
                content_digest=content_digest,
            )
            record["reused"] = True
            return record

        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise MathPageFileError("page file root is not a directory")
        destination = self.root / self.page_filename(
            page_id, leaf_digest, content_digest,
        )
        fd, temporary_name = tempfile.mkstemp(
            prefix=".math-page-", suffix=".tmp", dir=self.root,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(blob)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            _fsync_directory(self.root)
        finally:
            if temporary.exists():
                temporary.unlink()
        record = self._file_record(
            destination, page_id, leaf_digest, content_digest,
        )
        record["reused"] = False
        return record

    def pin_page_record(self, record: Mapping[str, Any],
                        data: bytes | bytearray | memoryview, *,
                        digest: str | None = None) -> dict[str, Any]:
        """Pin a MathStore page record's leaf digest to one page file."""
        page_id, leaf_digest, _, page_digest = _validate_record(record)
        published = self.write_page(
            page_id, data, leaf_digest=leaf_digest, digest=digest,
        )
        if page_digest is not None:
            published["page_digest"] = page_digest
        return published

    def read_page_record(self, record: Mapping[str, Any]) -> bytes:
        """Read the verified page file bound to a MathStore page record."""
        page_id, leaf_digest, _, _ = _validate_record(record)
        ref = self._single_file(page_id, leaf_digest=leaf_digest)
        data, _ = self._read_verified(
            Path(ref["path"]),
            page_id=page_id,
            leaf_digest=leaf_digest,
            content_digest=ref["content_digest"],
        )
        return data

    def load_page_record(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Read and return verified file metadata for a MathStore page record."""
        page_id, leaf_digest, _, page_digest = _validate_record(record)
        ref = self._single_file(page_id, leaf_digest=leaf_digest)
        data, verified = self._read_verified(
            Path(ref["path"]),
            page_id=page_id,
            leaf_digest=leaf_digest,
            content_digest=ref["content_digest"],
        )
        verified["data"] = data
        if page_digest is not None:
            verified["page_digest"] = page_digest
        return verified

    # -- page-map verification ----------------------------------------------

    def verify_page_map(self, store: Any, *,
                        expected_digest: str | None = None,
                        strict_files: bool = True) -> dict[str, Any]:
        """Verify files against the live MathStore page map and its digest.

        ``store`` is a :class:`runner_riddle.math_store.MathStore` (or any
        object exposing the same ``page_map()`` contract).  When
        ``expected_digest`` is supplied, the live page-map digest must match
        it.  With ``strict_files`` every file under the root must correspond to
        a page binding in the current map, so stale or unbound pages fail
        closed.
        """
        if expected_digest is not None:
            expected_digest = _require_digest(
                "expected_digest", expected_digest,
            )
        try:
            document = store.page_map()
        except Exception as exc:
            raise MathPageFileError(
                "MathStore page map is unavailable"
            ) from exc
        if (not isinstance(document, Mapping)
                or document.get("schema") != PAGE_MAP_SCHEMA):
            raise MathPageFileError("unsupported MathStore page map")
        pages = document.get("pages")
        if not isinstance(pages, list) or len(pages) != PAGE_COUNT:
            raise MathPageFileError(
                f"page map must contain exactly {PAGE_COUNT} slots"
            )
        digest = _require_digest("page map digest", document.get("digest"))
        core = {key: value for key, value in document.items()
                if key != "digest"}
        try:
            actual = sha256_text(canonical_json(core))
        except Exception as exc:
            raise MathPageFileMapDigestError(
                "page map is not canonical JSON"
            ) from exc
        if actual != digest:
            raise MathPageFileMapDigestError(
                "page map digest does not match its document"
            )
        if expected_digest is not None and digest != expected_digest:
            raise MathPageFileMapDigestError(
                f"page map digest {digest} does not match expected "
                f"{expected_digest}"
            )

        bound: dict[int, str] = {}
        page_files: list[dict[str, Any]] = []
        for index, page in enumerate(pages):
            if page is None:
                continue
            if not isinstance(page, Mapping):
                raise MathPageFileError(
                    f"page map slot {index} is not a page record"
                )
            page_id, leaf_digest, kind, _ = _validate_record(page)
            if page_id != index:
                raise MathPageFileError(
                    f"page map slot {index} names page {page_id}"
                )
            ref = self._single_file(page_id, leaf_digest=leaf_digest)
            _, verified = self._read_verified(
                Path(ref["path"]),
                page_id=page_id,
                leaf_digest=leaf_digest,
                content_digest=ref["content_digest"],
            )
            if verified["kind"] != kind:
                raise MathPageFileConflictError(
                    f"page {_page_key(page_id)} kind mismatch"
                )
            bound[page_id] = leaf_digest
            page_files.append(verified)

        if strict_files:
            for ref in self.list_page_files():
                page_id = int(ref["page_id"])
                if bound.get(page_id) != ref["leaf_digest"]:
                    raise MathPageFileConflictError(
                        f"page file {ref['filename']!r} is not bound by the "
                        "current page map"
                    )

        return {
            "schema": PAGE_FILE_SET_SCHEMA,
            "status": "verified",
            "page_map_digest": digest,
            "page_count": PAGE_COUNT,
            "head_page_count": HEAD_PAGE_COUNT,
            "nannet0_page": NANNET0_PAGE_ID,
            "page_bytes": PAGE_FILE_BYTES,
            "verified_pages": len(bound),
            "page_ids": sorted(bound),
            "files": page_files,
        }


# A short alias for callers that prefer the store vocabulary.
MathPageFileStore = MathPageFileProvider


__all__ = [
    "MathPageFileBoundsError",
    "MathPageFileConflictError",
    "MathPageFileDigestError",
    "MathPageFileError",
    "MathPageFileMapDigestError",
    "MathPageFileMissingError",
    "MathPageFileProvider",
    "MathPageFileSizeError",
    "MathPageFileStore",
    "PAGE_FILE_BYTES",
    "PAGE_FILE_SCHEMA",
    "PAGE_FILE_SET_SCHEMA",
]
