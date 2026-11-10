#!/usr/bin/env python3
"""Stream the exact pinned HW5 Gutenberg release through LIVE Koyeb NaNNet.

This is an explicit operator action. It refuses to send any archive bytes
until the authenticated remote ring reports active HW5:0 and a configured
C(256,2) importer. It never prints bearer tokens or raw corpus bytes.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zlib

from runner_riddle.hw5_portal_stream import (
    CHUNK_BYTES, KIND, QUERY_KIND, SCHEMA, SEAL_REQUEST, SEAL_WORD, MAX_ARCHIVE_BYTES,
)
from runner_riddle.hw5_release_bootstrap import RELEASE_URL, ARCHIVE_SHA256
from runner_riddle.point_fabric import Nan16DEWord, PointFrame

PORTAL = "https://nannet.apps.mistral.run"
CORPUS_BYTES = 20597424
# Independently measured from the exact publicly pinned g1 release in CI.
# A live portal must return THESE physical commitments, not merely an
# internally consistent self-reported receipt from an untrusted release.
EXPECTED_ROOT_SHA256 = "5199b69b17cb70c19e142340dffe38d1a85ea2ffd307f4ed305d7d46664b23bc"
EXPECTED_CORPUS_SHA256 = "044ba606977039729f4077e666ed50250a380d473ccdb7d20d1149f10e04566f"
EXPECTED_THE_TRIPLES = 245592
EXPECTED_TH_ADJACENT = 391106
EXPECTED_HT_ADJACENT = 26403


class HW5UploadError(RuntimeError):
    pass


class _NeverRedirectCredentials(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # urllib's default redirect handling may forward sensitive headers.
        # Never send a live ring bearer to a secondary origin.
        raise HW5UploadError("authenticated NANNET endpoint redirected")


def _get_json(base: str, token: str, path: str, body: dict | None = None) -> dict:
    if base != PORTAL:
        raise HW5UploadError("only the pinned production HTTPS NANNET portal is permitted")
    url = base + path
    headers = {"Authorization": "Bearer " + token,
               "Accept": "application/json",
               "User-Agent": "nanrouter-hw5-gutenberg-stream/1"}
    if body is None:
        req = urllib.request.Request(url, headers=headers)
    else:
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        if len(raw) > 2_097_152:
            raise HW5UploadError("NaNNet stream request exceeds portal bound")
        req = urllib.request.Request(
            url, headers={**headers, "Content-Type": "application/json"},
            data=raw, method="POST")
    try:
        # Authentication is sent only to the exact verified HTTPS origin.
        with urllib.request.build_opener(
                _NeverRedirectCredentials()).open(req, timeout=45) as response:
            if urllib.parse.urlsplit(response.url).netloc != "nannet.apps.mistral.run":
                raise HW5UploadError("credential-bearing request crossed origins")
            data = response.read(262145)
            if len(data) > 262144:
                raise HW5UploadError("portal response exceeds bound")
    except urllib.error.HTTPError as exc:
        raise HW5UploadError("NANNET rejected request (HTTP %d)" % exc.code) from None
    except urllib.error.URLError as exc:
        raise HW5UploadError("NANNET TLS transport unavailable (%s)" % exc.__class__.__name__) from None
    try:
        payload = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HW5UploadError("portal returned invalid JSON") from exc
    if type(payload) is not dict:
        raise HW5UploadError("portal returned non-object JSON")
    return payload


def _clock(token: str) -> int:
    """Reserve a real atomic, globally monotonic tick on the Koyeb authority.

    No wall-clock timestamps are invented as substitute nanclock ticks.
    """
    live = _get_json(PORTAL, token, "/v1/ring/clock")
    tick = live.get("nanclock_tick")
    if (type(tick) is not int or not 0 <= tick <= 0xFFFFFFFFFFFFFFFF
            or live.get("active") is not True):
        raise HW5UploadError("live runner ring did not allocate an active nanclock tick")
    return tick


def _frame(token: str, request_id: int, payload: int, *,
           kind: str = KIND, tick: int) -> dict:
    word = Nan16DEWord(0x7FF8, 0xFFF8, payload)
    frame = PointFrame(request_id=request_id, source_hw=0, destination_hw=5,
                       nanclock_tick=tick, kind=kind,
                       acl_digest=hashlib.sha256(
                           ("hw5/corpus/import/v1:" + token).encode()).hexdigest(),
                       word=word)
    return {
        "request_id": frame.request_id,
        "source_hw": frame.source_hw,
        "destination_hw": frame.destination_hw,
        "nanclock_tick": frame.nanclock_tick,
        "kind": frame.kind,
        "acl_digest": frame.acl_digest,
        "word_hex": frame.word.pack().hex(),
    }


def _submit(token: str, envelope: dict, request_id: int, payload: int) -> dict:
    response = _get_json(PORTAL, token, "/v1/ring/submit",
                         {"frame": _frame(token, request_id, payload, tick=_clock(token)),
                          "hw5_corpus": envelope})
    if response.get("schema") != SCHEMA or response.get("endpoint") != "HW5:0":
        raise HW5UploadError("remote HW5:0 did not acknowledge this stream")
    if response.get("archive_sha256") != ARCHIVE_SHA256:
        raise HW5UploadError("remote archive digest does not match pinned release")
    return response


def _download(path: Path) -> tuple[int, str]:
    total = 0
    digest = hashlib.sha256()
    with urllib.request.urlopen(RELEASE_URL, timeout=60) as res, path.open("xb") as out:
        for chunk in iter(lambda: res.read(1024 * 1024), b""):
            total += len(chunk)
            if total > MAX_ARCHIVE_BYTES:
                raise HW5UploadError("release archive exceeds 64 MiB")
            out.write(chunk)
            digest.update(chunk)
        out.flush()
        os.fsync(out.fileno())
    if not total or digest.hexdigest() != ARCHIVE_SHA256:
        raise HW5UploadError("pinned HW5 release failed source-integrity verification")
    return total, digest.hexdigest()


def upload(archive: Path, *, token: str, archive_size: int) -> dict:
    if not token or len(token) < 32:
        raise HW5UploadError("NANROUTER_RING_TOKEN (32+ bytes) is required")
    initial = _get_json(PORTAL, token, "/v1/ring/status")
    if (initial.get("ring_endpoint") != "HW5:0" or
            initial.get("active") is not True or
            (initial.get("hw5_corpus_stream") or {}).get("configured") is not True):
        raise HW5UploadError("the live HW5 ring does not advertise a ready corpus importer")
    common = {"schema": SCHEMA, "archive_sha256": ARCHIVE_SHA256}
    begin = _submit(token, dict(common, operation="begin", size=archive_size), 0, archive_size)
    offset = begin.get("received_bytes")
    if type(offset) is not int or not 0 <= offset <= archive_size or (offset % CHUNK_BYTES and offset != archive_size):
        raise HW5UploadError("remote resume cursor is invalid")
    with archive.open("rb") as fp:
        fp.seek(offset)
        while offset < archive_size:
            raw = fp.read(min(CHUNK_BYTES, archive_size - offset))
            if not raw:
                raise HW5UploadError("archive ended before the declared size")
            row = dict(common, operation="chunk", offset=offset,
                       chunk_b64=base64.b64encode(raw).decode("ascii"),
                       chunk_sha256=hashlib.sha256(raw).hexdigest())
            ack = _submit(token, row, 1 + offset // CHUNK_BYTES, zlib.crc32(raw))
            if ack.get("result") not in ("accepted", "duplicate") or ack.get("received_bytes") != offset + len(raw):
                raise HW5UploadError("remote chunk receipt does not match stream position")
            offset += len(raw)
    sealed = _submit(token, dict(common, operation="seal"), SEAL_REQUEST, SEAL_WORD)
    if (sealed.get("remote_verified") is not True or
            sealed.get("root_bytes") != 8388608 or
            sealed.get("mirror_pairs") != 32640 or
            sealed.get("corpus_bytes") != CORPUS_BYTES or
            sealed.get("root_sha256") != EXPECTED_ROOT_SHA256 or
            sealed.get("corpus_sha256") != EXPECTED_CORPUS_SHA256):
        # Require matching out-of-band release commitments. A portal that
        # uploads the wrong root must never be counted as a real HW5 seal.
        raise HW5UploadError("remote C(256,2) object failed full integrity checks")
    after = _get_json(PORTAL, token, "/v1/ring/status")
    root = after.get("hw5_gutenberg_reference") or {}
    stream = after.get("hw5_corpus_stream") or {}
    if (root.get("mounted") is not True or
            root.get("root_bytes") != sealed["root_bytes"] or
            root.get("root_sha256") != sealed["root_sha256"] or
            root.get("source_sha256") != sealed["corpus_sha256"] or
            stream.get("sealed") is not True or
            stream.get("root_sha256") != sealed["root_sha256"]):
        raise HW5UploadError("live remote readback disagrees with verified seal")
    # Do not settle for a metadata receipt: query real byte relations in the
    # sealed mapped root/ordered-triple ledger through the NaN16DE point route.
    triple_query = _get_json(PORTAL, token, "/v1/ring/submit", {
        "frame": _frame(token, 2, (ord("t") << 16) | (ord("h") << 8) | ord("e"),
                        kind=QUERY_KIND, tick=_clock(token))
    })
    exact = triple_query.get("result") or {}
    if (triple_query.get("schema") != "nanrouter.hw5-gutenberg-readback.v1"
            or triple_query.get("root_sha256") != sealed["root_sha256"]
            or triple_query.get("endpoint") != "HW5:0"
            or triple_query.get("query") != "triple"
            or exact.get("exact_ordered") is not True
            or exact.get("a") != ord("t") or exact.get("b") != ord("h")
            or exact.get("c") != ord("e")
            or type(exact.get("count")) is not int
            or exact["count"] != EXPECTED_THE_TRIPLES):
        raise HW5UploadError("native routed HW5 ordered-triple readback failed")
    result = {key: sealed[key] for key in (
        "archive_sha256", "root_sha256", "corpus_sha256",
        "corpus_bytes", "root_bytes", "mirror_pairs", "book_count"
    )}
    # Check both physical directions of a mirror-pair, not just an
    # exact ordered-triple ledger count or root receipt.
    pair_counts = {}
    for first, second, expected in (
            (ord("t"), ord("h"), EXPECTED_TH_ADJACENT),
            (ord("h"), ord("t"), EXPECTED_HT_ADJACENT)):
        response = _get_json(PORTAL, token, "/v1/ring/submit", {
            "frame": _frame(token, 1, (first << 16) | (second << 8),
                            kind=QUERY_KIND, tick=_clock(token))
        })
        physical = response.get("result") or {}
        if (response.get("schema") != "nanrouter.hw5-gutenberg-readback.v1"
                or response.get("endpoint") != "HW5:0"
                or response.get("query") != "pair"
                or response.get("root_sha256") != EXPECTED_ROOT_SHA256
                or physical.get("a") != first
                or physical.get("b") != second
                or physical.get("adjacent_count") != expected):
            raise HW5UploadError("directed physical HW5 mirror readback differs from release")
        pair_counts["%s_to_%s" % (chr(first), chr(second))] = expected
    result["exact_the_count"] = exact["count"]
    result["directed_pair_counts"] = pair_counts
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true",
                        help="explicitly authorize writing the pinned archive to live Koyeb")
    args = parser.parse_args()
    if not args.send:
        raise SystemExit("refusing live upload without --send")
    token = os.environ.get("NANROUTER_RING_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("live upload blocked: protected ring credential is absent")
    with tempfile.TemporaryDirectory(prefix="hw5-c256-") as folder:
        path = Path(folder) / "archive.tar.gz"
        size, digest = _download(path)
        result = upload(path, token=token, archive_size=size)
        print("HW5_LIVE_GUTENBERG_SEALED " +
              json.dumps({"verified": True, **result, "source_archive_bytes": size,
                          "source_archive_sha256": digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
