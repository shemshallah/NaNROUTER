"""Fail-closed, single-writer HW5:0 Gutenberg archive stream receiver.

The authenticated portal's existing POST /v1/ring/submit carries the NaN16DE
point frame plus a bounded opaque archive chunk. HW5 consumes these frames
only while holding the existing runner-ring lease. The immutable C(256,2)
root is installed only after verifying the pinned complete archive and all
individual generated artifacts. No learning or NaN16 opcode is implemented
here: this is a transport-to-reference driver.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import threading
import zlib

from .hw5_release_bootstrap import ARCHIVE_SHA256, bootstrap
from .point_fabric import PointFrame

SCHEMA = "nanrouter.hw5-gutenberg-live-stream.v1"
KIND = "hw5.gutenberg.c256.archive.v1"
QUERY_KIND = "hw5.gutenberg.c256.query.v1"
CHUNK_BYTES = 131072
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
SEAL_REQUEST = 0xFFFFFFFF
SEAL_WORD = 0xC2560001


class HW5StreamError(ValueError):
    """Rejected or stale archive transaction; never a successful upload."""


def _strict_object(value: object, expected: set[str]) -> dict:
    if type(value) is not dict or set(value) != expected:
        raise HW5StreamError("invalid HW5 stream envelope fields")
    return value


def _atomic_json(path: Path, payload: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, sort_keys=True, separators=(",", ":"))
        fp.write("\n")
        fp.flush()
        os.fsync(fp.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _safe_path(path: Path) -> Path:
    resolved = path.resolve(strict=False)
    if "bs0db" in resolved.parts or not resolved.is_absolute():
        raise HW5StreamError("HW5 corpus import cannot use BS0 storage")
    if path.is_symlink():
        raise HW5StreamError("HW5 stream paths cannot be symbolic links")
    return resolved


class HW5PortalStream:
    """One pinned release stream, resumable across ring lease handoffs.

    Acknowledgment is issued only after data and its cursor are fsynced.
    Repeated chunks are verified byte-for-byte. A mismatching replay cannot
    silently overwrite the immutable store.
    """

    def __init__(self, spool: str | Path, store: str | Path,
                 *, archive_sha256: str = ARCHIVE_SHA256, installer=bootstrap):
        if (type(archive_sha256) is not str or len(archive_sha256) != 64
                or any(c not in "0123456789abcdef" for c in archive_sha256)):
            raise HW5StreamError("archive digest must be lowercase SHA-256")
        self.spool = _safe_path(Path(spool))
        self.store = _safe_path(Path(store))
        if self.spool == self.store or self.spool in self.store.parents or self.store in self.spool.parents:
            raise HW5StreamError("stream spool and immutable store must be separate")
        self.expected = archive_sha256
        self.installer = installer
        self.lock = threading.RLock()
        self.statefile = self.spool / "cursor.json"
        self.payload = self.spool / "pinned-archive.tar.gz"
        self.receiptfile = self.spool / "sealed-receipt.json"

    def _state(self) -> dict | None:
        if not self.statefile.exists():
            return None
        state = json.loads(self.statefile.read_text(encoding="utf-8"))
        if (type(state) is not dict or state.get("schema") != SCHEMA
                or state.get("archive_sha256") != self.expected
                or type(state.get("size")) is not int
                or type(state.get("received")) is not int
                or not 0 < state["size"] <= MAX_ARCHIVE_BYTES
                or not 0 <= state["received"] <= state["size"]):
            raise HW5StreamError("stream cursor is corrupt or from another release")
        if self.payload.is_symlink() or not self.payload.is_file():
            raise HW5StreamError("stream payload is missing or symbolic")
        actual = self.payload.stat().st_size
        if actual < state["received"]:
            raise HW5StreamError("stream payload is truncated")
        return state

    def status(self) -> dict:
        with self.lock:
            state = self._state()
            receipt = None
            if self.receiptfile.exists():
                receipt = json.loads(self.receiptfile.read_text(encoding="utf-8"))
                if receipt.get("archive_sha256") != self.expected:
                    raise HW5StreamError("sealed receipt digest mismatch")
            return {
                "schema": SCHEMA,
                "configured": True,
                "archive_sha256": self.expected,
                "received_bytes": 0 if state is None else state["received"],
                "total_bytes": 0 if state is None else state["size"],
                "sealed": receipt is not None,
                "root_sha256": None if receipt is None else receipt["root_sha256"],
                "corpus_sha256": None if receipt is None else receipt["corpus_sha256"],
            }

    def receive(self, frame: PointFrame, envelope: object) -> dict:
        if (not isinstance(frame, PointFrame) or frame.source_hw != 0
                or frame.destination_hw != 5 or frame.kind != KIND
                or frame.origin != "zero-point"):
            raise HW5StreamError("HW5 import requires a routed HW0:0 to HW5:0 point frame")
        if type(envelope) is not dict or envelope.get("schema") != SCHEMA:
            raise HW5StreamError("invalid HW5 stream schema")
        if envelope.get("archive_sha256") != self.expected:
            raise HW5StreamError("the requested archive is not pinned")
        op = envelope.get("operation")
        with self.lock:
            if op == "begin":
                item = _strict_object(envelope, {"schema", "archive_sha256", "operation", "size"})
                size = item["size"]
                if (type(size) is not int or not 0 < size <= MAX_ARCHIVE_BYTES
                        or frame.request_id != 0 or frame.word.payload != size):
                    raise HW5StreamError("invalid beginning archive size/NaN16 word")
                state = self._state()
                if state is None:
                    self.spool.mkdir(parents=True, exist_ok=True)
                    if self.payload.exists() or self.statefile.exists():
                        raise HW5StreamError("orphaned stream state requires operator repair")
                    with self.payload.open("xb") as fp:
                        fp.flush()
                        os.fsync(fp.fileno())
                    state = {"schema": SCHEMA, "archive_sha256": self.expected,
                             "size": size, "received": 0}
                    _atomic_json(self.statefile, state)
                elif state["size"] != size:
                    raise HW5StreamError("archive length changed in a replay")
                return self._ack(state, "begun")
            if op == "chunk":
                item = _strict_object(envelope, {
                    "schema", "archive_sha256", "operation", "offset",
                    "chunk_b64", "chunk_sha256",
                })
                state = self._state()
                if state is None:
                    raise HW5StreamError("chunk received before begin")
                offset = item["offset"]
                encoded = item["chunk_b64"]
                digest = item["chunk_sha256"]
                if (type(offset) is not int or offset < 0 or offset % CHUNK_BYTES
                        or type(encoded) is not str or len(encoded) > 2 * CHUNK_BYTES
                        or type(digest) is not str or len(digest) != 64):
                    raise HW5StreamError("invalid chunk offset or bounds")
                try:
                    raw = base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise HW5StreamError("invalid base64 archive chunk") from exc
                if (not raw or len(raw) > CHUNK_BYTES
                        or offset + len(raw) > state["size"]
                        or hashlib.sha256(raw).hexdigest() != digest
                        or frame.request_id != 1 + offset // CHUNK_BYTES
                        or frame.word.payload != zlib.crc32(raw)):
                    raise HW5StreamError("archive chunk digest, range or frame mismatch")
                if offset < state["received"]:
                    if offset + len(raw) > state["received"]:
                        raise HW5StreamError("partial overlapping chunk is not idempotent")
                    with self.payload.open("rb") as fp:
                        fp.seek(offset)
                        if fp.read(len(raw)) != raw:
                            raise HW5StreamError("conflicting replayed archive bytes")
                    return self._ack(state, "duplicate")
                if offset != state["received"]:
                    raise HW5StreamError("out-of-order archive chunk")
                with self.payload.open("r+b") as fp:
                    fp.truncate(offset)  # discard unacknowledged crash tail
                    fp.seek(offset)
                    fp.write(raw)
                    fp.flush()
                    os.fsync(fp.fileno())
                state["received"] += len(raw)
                _atomic_json(self.statefile, state)
                return self._ack(state, "accepted")
            if op == "seal":
                _strict_object(envelope, {"schema", "archive_sha256", "operation"})
                if frame.request_id != SEAL_REQUEST or frame.word.payload != SEAL_WORD:
                    raise HW5StreamError("seal NaN16 word is invalid")
                state = self._state()
                if state is None or state["received"] != state["size"]:
                    raise HW5StreamError("cannot seal an incomplete archive")
                if self.receiptfile.exists():
                    receipt = json.loads(self.receiptfile.read_text(encoding="utf-8"))
                    if receipt.get("archive_sha256") != self.expected:
                        raise HW5StreamError("existing receipt is not pinned")
                    return dict(receipt, result="already_sealed")
                if self.payload.stat().st_size != state["size"]:
                    raise HW5StreamError("unacknowledged archive tail before seal")
                checksum = hashlib.sha256()
                with self.payload.open("rb") as fp:
                    for part in iter(lambda: fp.read(1024 * 1024), b""):
                        checksum.update(part)
                if checksum.hexdigest() != self.expected:
                    raise HW5StreamError("complete Gutenberg archive digest mismatch")
                installed = self.installer(self.store, archive_path=self.payload)
                manifest = installed["manifest"]
                if (manifest["root_bytes"] != 8388608 or
                        manifest["mirror_pairs"] != 32640):
                    raise HW5StreamError("installed root does not match C(256,2) geometry")
                receipt = {
                    "schema": SCHEMA, "result": "sealed",
                    "archive_sha256": self.expected,
                    "root_sha256": manifest["artifacts"]["gutenberg-c256.root"]["sha256"],
                    "corpus_sha256": manifest["artifacts"]["all.txt"]["sha256"],
                    "corpus_bytes": manifest["corpus_bytes"],
                    "book_count": len(manifest["books"]),
                    "root_bytes": manifest["root_bytes"],
                    "mirror_pairs": manifest["mirror_pairs"],
                    "remote_verified": True,
                }
                _atomic_json(self.receiptfile, receipt)
                return receipt
            raise HW5StreamError("unsupported stream operation")

    @staticmethod
    def _ack(state: dict, result: str) -> dict:
        return {"schema": SCHEMA, "result": result,
                "archive_sha256": state["archive_sha256"],
                "received_bytes": state["received"],
                "total_bytes": state["size"],
                "remote_verified": False}
