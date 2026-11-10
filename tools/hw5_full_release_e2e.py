#!/usr/bin/env python3
"""Replay the actual published Gutenberg C256 archive through the HW5 receiver.

This is a local end-to-end real-data verification, NOT a live Koyeb receipt.
It uses precisely the same pinned archive, stream envelopes, and immutable
installer as the deployed path, then reads physical pairs and triples.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import zlib

from runner_riddle.hw5_gutenberg import MountedHW5
from tests.test_hw4_portal_resident import Authority, portal_module
from runner_riddle.hw5_portal_stream import (
    CHUNK_BYTES, KIND, QUERY_KIND, SCHEMA, SEAL_REQUEST, SEAL_WORD, HW5PortalStream,
)
from runner_riddle.hw5_release_bootstrap import ARCHIVE_SHA256
from runner_riddle.point_fabric import Nan16DEWord, PointFrame

CORPUS_BYTES = 20597424
BOOKS = 21
ROOT_BYTES = 8388608
PAIRS = 32640


def check(condition: bool, label: str) -> None:
    if not condition:
        raise RuntimeError("HW5 full-release invariant: " + label)


def word_frame(request_id: int, payload: int, *, kind: str = KIND) -> PointFrame:
    return PointFrame(
        request_id=request_id, source_hw=0, destination_hw=5,
        nanclock_tick=17, kind=kind,
        acl_digest="c" * 64,
        word=Nan16DEWord(0x7FF8, 0xFFF8, payload),
    )


def input_row(operation: str, **kwargs) -> dict:
    return {
        "schema": SCHEMA,
        "archive_sha256": ARCHIVE_SHA256,
        "operation": operation,
        **kwargs,
    }


def run(archive: Path) -> dict:
    size = archive.stat().st_size
    check(0 < size <= 64 * 1024 * 1024, "source compressed archive bounds")
    sha = hashlib.sha256()
    with archive.open("rb") as source:
        for piece in iter(lambda: source.read(1024 * 1024), b""):
            sha.update(piece)
    check(sha.hexdigest() == ARCHIVE_SHA256, "published release SHA256")

    with tempfile.TemporaryDirectory(prefix="hw5-c256-full-") as tmp:
        spool = Path(tmp) / "incoming"
        store = Path(tmp) / "immutable"
        receiver = HW5PortalStream(spool, store)
        first = receiver.receive(
            word_frame(0, size), input_row("begin", size=size))
        check(first["received_bytes"] == 0, "initial cursor")

        replayed = False
        resumed = False
        chunks = 0
        offset = 0
        with archive.open("rb") as source:
            while offset < size:
                piece = source.read(min(CHUNK_BYTES, size - offset))
                check(len(piece) > 0, "truncated published archive")
                envelope = input_row(
                    "chunk",
                    offset=offset,
                    chunk_b64=base64.b64encode(piece).decode("ascii"),
                    chunk_sha256=hashlib.sha256(piece).hexdigest(),
                )
                point = word_frame(1 + offset // CHUNK_BYTES, zlib.crc32(piece))
                ack = receiver.receive(point, envelope)
                check(ack["result"] == "accepted", "durable chunk acknowledgment")
                check(ack["received_bytes"] == offset + len(piece), "cursor movement")
                if not replayed:
                    again = receiver.receive(point, envelope)
                    check(again["result"] == "duplicate", "identical chunk replay")
                    replayed = True
                offset += len(piece)
                chunks += 1
                if not resumed and offset >= size // 2:
                    # Simulate a new ring lease owner / process; the cursor
                    # must come exclusively from the previous durable /data.
                    receiver = HW5PortalStream(spool, store)
                    rebegun = receiver.receive(
                        word_frame(0, size), input_row("begin", size=size))
                    check(rebegun["received_bytes"] == offset, "lease handoff cursor")
                    resumed = True
        check(resumed and replayed, "restart/replay exercise")
        receipt = receiver.receive(
            word_frame(SEAL_REQUEST, SEAL_WORD), input_row("seal"))
        check(receipt["remote_verified"] is True, "local strict installer")
        check(receipt["root_bytes"] == ROOT_BYTES, "full C256 root bytes")
        check(receipt["mirror_pairs"] == PAIRS, "full physical mirror geometry")
        check(receipt["corpus_bytes"] == CORPUS_BYTES, "entire Gutenberg text")
        check(receipt["book_count"] == BOOKS, "whole-book source count")

        with MountedHW5(store) as mounted:
            status = mounted.status()
            triple = mounted.triple(ord("t"), ord("h"), ord("e"))
            forward = mounted.pair(ord("t"), ord("h"))
            inverse = mounted.pair(ord("h"), ord("t"))
            check(status["root_bytes"] == ROOT_BYTES, "mmap size")
            check(status["corpus_bytes"] == CORPUS_BYTES, "mounted exact text size")
            check(status["books"] == BOOKS, "mounted full book count")
            check(triple["exact_ordered"] and triple["count"] > 0,
                  "physical exact ordered triple the")
            check(forward["adjacent_count"] > 0,
                  "physical forward t->h mirror count")
            check(forward["pair_id"] == inverse["pair_id"],
                  "two logical directions share one physical pair")
            check(forward["lane_direction"] != inverse["lane_direction"],
                  "distinct directed NaN16 pair lanes")
            check(status["source_sha256"] == receipt["corpus_sha256"],
                  "physical readback corpus checksum")
            check(
                mounted.manifest["artifacts"]["gutenberg-c256.root"]["sha256"]
                == receipt["root_sha256"], "physical readback root checksum")
            check(mounted.manifest["projection"]["unique_triples"] == 36983,
                  "exact ordered triple types")

        check(receiver.status()["sealed"] is True, "persistent receipt")
        return {
            "archive_bytes": size,
            "archive_sha256": ARCHIVE_SHA256,
            "chunks": chunks,
            "lease_handoff_resumed": resumed,
            "duplicate_replayed": replayed,
            "corpus_bytes": receipt["corpus_bytes"],
            "books": receipt["book_count"],
            "root_bytes": receipt["root_bytes"],
            "mirror_pairs": receipt["mirror_pairs"],
            "root_sha256": receipt["root_sha256"],
            "corpus_sha256": receipt["corpus_sha256"],
            "exact_triple_the": triple["count"],
            "forward_th": forward["adjacent_count"],
            "reverse_ht": inverse["adjacent_count"],
            "verified_location": "GitHub runner local temporary directory",
            "koyeb_live": False,
        }



def _portal_frame(frame: PointFrame) -> dict:
    return {
        "request_id": frame.request_id,
        "source_hw": frame.source_hw,
        "destination_hw": frame.destination_hw,
        "nanclock_tick": frame.nanclock_tick,
        "kind": frame.kind,
        "acl_digest": frame.acl_digest,
        "word_hex": frame.word.pack().hex(),
    }


def run_full_portal_route(archive: Path) -> dict:
    """Prove the entire real release traverses PortalRingNode.submit.

    This executes the real portal router with a local in-process lease stub
    and a real immutable C256 verifier; it is not production Koyeb traffic.
    """
    size = archive.stat().st_size
    with tempfile.TemporaryDirectory(prefix="hw5-portal-route-full-") as root:
        folder = Path(root)
        store = folder / "immutable"
        spool = folder / "incoming"
        env = {"RIDDLE_HW5_STORE": str(store),
               "RIDDLE_HW5_STREAM_DIR": str(spool),
               "RIDDLE_HW5_RING": "NaNROUTER/MC0:0"}
        portal = portal_module()
        authority = Authority()
        database = str(folder / "ring.sqlite")
        with patch.dict(os.environ, env, clear=True):
            node = portal.PortalRingNode(
                authority, token="x" * 40,
                endpoint="http://127.0.0.1:1", database=database,
            )
            with node._lock:
                node._activate_locked({"lease_id": "local-a", "epoch": 1})
            check(node.status()["ring_endpoint"] == "HW5:0",
                  "actual portal ring identity")
            def submit(frame: PointFrame, row: dict | None = None) -> dict:
                body = {"frame": _portal_frame(frame)}
                if row is not None:
                    body["hw5_corpus"] = row
                return node.submit(body)

            start = submit(word_frame(0, size), input_row("begin", size=size))
            check(start["central_status"] == "hw5_object_consumed",
                  "begin consumed by HW5 object not generic inbox")
            chunks = 0
            offset = 0
            swapped = False
            with archive.open("rb") as stream:
                while offset < size:
                    raw = stream.read(min(CHUNK_BYTES, size - offset))
                    check(bool(raw), "routed stream archive truncated")
                    point = word_frame(
                        1 + offset // CHUNK_BYTES, zlib.crc32(raw))
                    envelope = input_row(
                        "chunk", offset=offset,
                        chunk_b64=base64.b64encode(raw).decode("ascii"),
                        chunk_sha256=hashlib.sha256(raw).hexdigest(),
                    )
                    ack = submit(point, envelope)
                    check(ack["central_status"] == "hw5_object_consumed",
                          "routed chunk object consumer receipt")
                    check(ack["received_bytes"] == offset + len(raw),
                          "durable HW5 portal cursor")
                    offset += len(raw)
                    chunks += 1
                    if not swapped and offset >= size // 2:
                        with node._lock:
                            node._step_down_locked("simulated-lease-handoff")
                        check(not node.active, "previous portal lease released")
                        successor = portal.PortalRingNode(
                            authority, token="x" * 40,
                            endpoint="http://127.0.0.1:1", database=database,
                        )
                        with successor._lock:
                            successor._activate_locked({
                                "lease_id": "local-b", "epoch": 2,
                            })
                        node = successor
                        restored = submit(
                            word_frame(0, size),
                            input_row("begin", size=size))
                        check(restored["received_bytes"] == offset,
                              "stream cursor survived actual portal node handoff")
                        swapped = True
            check(swapped, "portal route simulated a real lease handoff")
            seal = submit(word_frame(SEAL_REQUEST, SEAL_WORD),
                          input_row("seal"))
            check(seal["remote_verified"] is True,
                  "portal received real immutable C256 generation")
            check(seal["central_status"] == "hw5_object_consumed",
                  "seal routed to HW5 object")
            status = node.status()
            check(status["hw5_gutenberg_reference"]["mounted"] is True,
                  "live-process immutable root mmap")
            check(status["hw5_gutenberg_reference"]["root_sha256"]
                  == seal["root_sha256"],
                  "mounted root digest after routed seal")
            check(status["hw5_corpus_stream"]["sealed"] is True,
                  "sealed stream after real portal routed import")
            check(node.fabric.monitor()["queued"] == 0,
                  "no corpus data treated as generic NaN frame delivery")
            triple = submit(word_frame(
                2, (ord("t") << 16) | (ord("h") << 8) | ord("e"),
                kind=QUERY_KIND))
            check(triple["schema"] == "nanrouter.hw5-gutenberg-readback.v1",
                  "routed triple readback schema")
            check(triple["root_sha256"] == seal["root_sha256"],
                  "routed byte triple belongs to sealed root")
            check(triple["result"]["count"] == 245592,
                  "physically routed full-gutenberg 'the' count")
            pair = submit(word_frame(
                1, (ord("t") << 16) | (ord("h") << 8), kind=QUERY_KIND))
            check(pair["result"]["adjacent_count"] == 391106,
                  "routed real t->h mirror count")
            node.hw5.close()
            return {
                "route": "HW0:0 -> HW5:0",
                "full_release_chunks": chunks,
                "lease_epoch_before": 1,
                "lease_epoch_after": 2,
                "root_sha256": seal["root_sha256"],
                "corpus_sha256": seal["corpus_sha256"],
                "exact_the_triple": triple["result"]["count"],
                "directed_th_count": pair["result"]["adjacent_count"],
                "generic_point_frames_queued": 0,
                "koyeb_live": False,
            }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    receipt = run(args.archive)
    routed = run_full_portal_route(args.archive)
    check(routed["root_sha256"] == receipt["root_sha256"],
          "direct receiver and routed portal must seal identical C256 roots")
    check(routed["corpus_sha256"] == receipt["corpus_sha256"],
          "direct receiver and routed portal must seal identical source corpus")
    receipt["portal_route_full_release"] = routed
    print("HW5_FULL_RELEASE_E2E_PASS " + json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
