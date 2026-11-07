import contextlib
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from runner_riddle.point0_bridge import (
    MAX_FRAME_WORDS,
    POINT_ZERO_ADDRESS,
    POINT_ZERO_WIRE,
    NanFrame,
    Point0Bridge,
    Point0Router,
)
from runner_riddle.point0_http import (
    BINARY_CONTENT_TYPE,
    MAX_BODY_BYTES,
    MAX_WORDS,
    POINT0_PATH,
    SCHEMA,
    Point0HttpAdapter,
    Point0HttpServer,
    make_point0_handler,
)
from runner_riddle.wave_ring_scheduler import JAHS_SEAL, WaveRingScheduler
from runner_riddle.wave_service import WaveService
from runner_riddle.wave_store import WaveStore

UINT64_MAX = (1 << 64) - 1


class RecordingExecutor:
    def __init__(self, transform=None):
        self.calls = []
        self.transform = transform

    def __call__(self, active_slot, epoch, binary_payload):
        self.calls.append((active_slot, epoch, binary_payload))
        if self.transform is not None:
            return self.transform(binary_payload)
        return binary_payload


class Point0HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = WaveStore(root / "bs0db.sqlite3", root / "mc0db.sqlite3")
        self.submit_token = "point0-submit-token-0000000000"
        self.worker_token = "point0-worker-token-1111111111"
        self.admin_token = "point0-admin-token-2222222222"
        self.wrong_token = "point0-wrong-token-99999999999"
        self.service = WaveService(
            self.store,
            self.submit_token,
            self.worker_token,
            self.admin_token,
        )
        self.scheduler = WaveRingScheduler(cycle_ticks=10, now_tick=0)
        self.scheduler.start(0)
        self.executor = RecordingExecutor()
        self.router = Point0Router(self.scheduler, self.executor)
        self.adapter = Point0HttpAdapter(self.router, self.service)

    # -- Helpers --------------------------------------------------------------

    def call(self, adapter=None, *, method="POST", path=POINT0_PATH,
             body=None, raw=None, token=None, content_type="application/json",
             headers=None, include_length=True):
        adapter = self.adapter if adapter is None else adapter
        if raw is None and body is not None:
            raw = json.dumps(
                body, separators=(",", ":"), ensure_ascii=False,
            ).encode("utf-8")
        if raw is None:
            raw = b""
        request_headers = {}
        if include_length:
            request_headers["Content-Length"] = str(len(raw))
        if content_type is not None:
            request_headers["Content-Type"] = content_type
        if token is not None:
            request_headers["Authorization"] = "Bearer " + token
        request_headers.update(headers or {})
        return adapter.handle(method, path, request_headers, raw)

    def frame_body(self, *, route=None, request_id=1, words=(1, 2, 3)):
        body = {"request_id": request_id, "words": list(words)}
        if route is not None:
            body["route"] = route
        return body

    def assert_no_token(self, response, tokens):
        rendered = response.body + json.dumps(
            response.headers, sort_keys=True,
        ).encode("utf-8")
        for token in tokens:
            self.assertNotIn(token.encode("utf-8"), rendered)

    # -- Valid round trips ----------------------------------------------------

    def test_valid_json_round_trip_and_stable_route_across_cycle(self):
        words = (0, 1, 0x9E3779B97F4A7C15, UINT64_MAX)
        response = self.call(
            body=self.frame_body(
                route=POINT_ZERO_WIRE, request_id=42, words=words,
            ),
            token=self.submit_token,
        )
        self.assertEqual(response.status, 200)
        document = response.json()
        self.assertEqual(document["schema"], SCHEMA)
        self.assertEqual(document["route"], POINT_ZERO_ADDRESS)
        self.assertEqual(document["point_zero"], "BS0:0")
        self.assertEqual(document["wire"], POINT_ZERO_WIRE)
        self.assertEqual(document["request_id"], 42)
        self.assertEqual(document["words"], list(words))
        self.assertEqual(document["word_count"], len(words))
        self.assertEqual(document["active_slot"], 0)
        self.assertEqual(document["epoch"], 1)
        self.assertEqual(document["jahs"]["seal"], JAHS_SEAL)
        self.assertEqual(document["jahs"]["name"], "Just A Handoff Seal")
        self.assertEqual(document["jahs"]["epoch"], 1)
        self.assertEqual(len(document["request_digest"]), 64)
        self.assertEqual(len(document["result_digest"]), 64)
        self.assertNotIn("/R", document["route"])
        self.assertNotIn("NANROUTER", document["route"])

        self.assertEqual(len(self.executor.calls), 1)
        slot, epoch, payload = self.executor.calls[0]
        self.assertEqual((slot, epoch), (0, 1))
        expected = Point0Bridge().encode(
            NanFrame(words=words, request_id=42),
            active_slot=0,
            epoch=1,
        ).payload
        self.assertEqual(payload, expected)

        # The same public route reaches whatever slot is active after a cycle.
        self.scheduler.cycle(1)
        second = self.call(
            body=self.frame_body(request_id=43, words=words),
            token=self.submit_token,
        )
        self.assertEqual(second.status, 200)
        evidence = second.json()
        self.assertEqual(evidence["route"], POINT_ZERO_ADDRESS)
        self.assertEqual(evidence["active_slot"], 1)
        self.assertEqual(evidence["epoch"], 2)
        self.assertEqual(evidence["words"], list(words))
        self.assertEqual(evidence["jahs"]["seal"], JAHS_SEAL)
        self.assertEqual(
            [(slot, epoch) for slot, epoch, _ in self.executor.calls],
            [(0, 1), (1, 2)],
        )

    def test_binary_word_framing_round_trip_and_evidence_headers(self):
        words = (0x0102030405060708, 0, UINT64_MAX)
        payload = struct.pack(f">{len(words)}Q", *words)
        response = self.call(
            raw=payload,
            token=self.submit_token,
            content_type=BINARY_CONTENT_TYPE,
            headers={
                "X-NaN-Route": POINT_ZERO_WIRE,
                "X-NaN-Request-Id": "77",
            },
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(response.header("Content-Type"), BINARY_CONTENT_TYPE)
        self.assertEqual(response.body, payload)
        self.assertEqual(response.header("X-NaN-Route"), POINT_ZERO_ADDRESS)
        self.assertEqual(response.header("X-NaN-Wire"), POINT_ZERO_WIRE)
        self.assertEqual(response.header("X-NaN-Request-Id"), "77")
        self.assertEqual(response.header("X-NaN-Word-Count"), str(len(words)))
        self.assertEqual(response.header("X-NaN-Active-Slot"), "0")
        self.assertEqual(response.header("X-NaN-Epoch"), "1")
        self.assertEqual(response.header("X-NaN-JAHS"), JAHS_SEAL)
        self.assertEqual(len(response.header("X-NaN-Request-Digest")), 64)
        self.assertEqual(len(response.header("X-NaN-Result-Digest")), 64)
        self.assertEqual(
            self.executor.calls,
            [(0, 1, payload)],
        )

    def test_word_limit_boundary_is_accepted(self):
        words = [0] * MAX_WORDS
        response = self.call(
            body=self.frame_body(request_id=5, words=words),
            token=self.submit_token,
        )
        self.assertEqual(response.status, 200)
        document = response.json()
        self.assertEqual(document["word_count"], MAX_WORDS)
        self.assertEqual(len(document["words"]), MAX_WORDS)

    def test_binary_body_limit_boundary_is_accepted(self):
        payload = b"\x00" * (MAX_WORDS * 8)
        response = self.call(
            raw=payload,
            token=self.submit_token,
            content_type=BINARY_CONTENT_TYPE,
            headers={"X-NaN-Request-Id": "6"},
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, payload)
        self.assertEqual(response.header("X-NaN-Word-Count"), str(MAX_WORDS))

    # -- Direct slot rejection ------------------------------------------------

    def test_direct_slot_routes_are_rejected_everywhere(self):
        routes = (
            "MC0:0/R0",
            "MC0:0/R5",
            "NANROUTER-0",
            "NANROUTER-5",
            "nan://GM1:SC0:MC0:BS0:0:HW0:0",
        )
        for route in routes:
            with self.subTest(route=route):
                response = self.call(
                    body=self.frame_body(route=route),
                    token=self.submit_token,
                )
                self.assertEqual(response.status, 400)
                error = response.json()["error"].lower()
                self.assertTrue(
                    "route" in error or "point-0" in error,
                    error,
                )
                self.assertNotIn(route, response.body.decode("utf-8"))

        for path in (
            POINT0_PATH + "/MC0:0/R0",
            POINT0_PATH + "/NANROUTER-0",
            POINT0_PATH + "?route=MC0:0/R5",
        ):
            with self.subTest(path=path):
                response = self.call(
                    path=path,
                    body=self.frame_body(),
                    token=self.submit_token,
                )
                self.assertEqual(response.status, 400)
                error = response.json()["error"].lower()
                self.assertIn("runner-slot", error)

        payload = struct.pack(">Q", 1)
        response = self.call(
            raw=payload,
            token=self.submit_token,
            content_type=BINARY_CONTENT_TYPE,
            headers={
                "X-NaN-Route": "NANROUTER-0",
                "X-NaN-Request-Id": "1",
            },
        )
        self.assertEqual(response.status, 400)
        self.assertIn("route", response.json()["error"].lower())
        self.assertEqual(self.executor.calls, [])

    def test_client_supplied_slot_epoch_or_alias_is_rejected(self):
        cases = {
            "active_slot": 3,
            "epoch": 9,
            "slot": 2,
            "slot_id": "MC0:0/R3",
            "runner": "MC0:0/R3",
            "runner_id": "MC0:0/R3",
            "alias": "NANROUTER-3",
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                body = self.frame_body()
                body[field] = value
                response = self.call(body=body, token=self.submit_token)
                self.assertEqual(response.status, 400)
                self.assertIn(
                    "routing evidence",
                    response.json()["error"].lower(),
                )

        payload = struct.pack(">Q", 1)
        for header, value in (
            ("X-NaN-Active-Slot", "3"),
            ("X-NaN-Epoch", "9"),
            ("X-NaN-Slot", "2"),
            ("X-NaN-Alias", "NANROUTER-2"),
        ):
            with self.subTest(header=header):
                response = self.call(
                    raw=payload,
                    token=self.submit_token,
                    content_type=BINARY_CONTENT_TYPE,
                    headers={
                        "X-NaN-Request-Id": "1",
                        header: value,
                    },
                )
                self.assertEqual(response.status, 400)
                self.assertIn(
                    "routing evidence",
                    response.json()["error"].lower(),
                )
        self.assertEqual(self.executor.calls, [])

    # -- Bounds and framing ---------------------------------------------------

    def test_oversized_body_and_word_count_are_rejected(self):
        raw = b'{"padding":"' + b"x" * MAX_BODY_BYTES + b'"}'
        response = self.call(raw=raw, token=self.submit_token)
        self.assertEqual(response.status, 400)
        self.assertIn("exceeds", response.json()["error"])
        self.assertLess(len(response.body), 1024)

        words = [0] * (MAX_WORDS + 1)
        response = self.call(
            body=self.frame_body(words=words),
            token=self.submit_token,
        )
        self.assertEqual(response.status, 400)
        self.assertIn("limit", response.json()["error"].lower())

        payload = b"\x00" * (MAX_WORDS * 8 + 8)
        response = self.call(
            raw=payload,
            token=self.submit_token,
            content_type=BINARY_CONTENT_TYPE,
            headers={"X-NaN-Request-Id": "1"},
        )
        self.assertEqual(response.status, 400)
        self.assertIn("exceeds", response.json()["error"])
        self.assertEqual(self.executor.calls, [])

    def test_bad_json_content_type_and_lengths_are_rejected(self):
        cases = [
            (
                "wrong content type",
                dict(body=self.frame_body(), content_type="text/plain"),
            ),
            (
                "malformed json",
                dict(raw=b"{", content_type="application/json"),
            ),
            (
                "not an object",
                dict(raw=b"[]", content_type="application/json"),
            ),
            (
                "duplicate key",
                dict(
                    raw=b'{"request_id":1,"request_id":2,"words":[]}',
                    content_type="application/json",
                ),
            ),
            (
                "unknown field",
                dict(
                    body={"request_id": 1, "words": [], "payload": {}},
                ),
            ),
            (
                "missing request id",
                dict(body={"words": [1]}),
            ),
            (
                "missing words",
                dict(body={"request_id": 1}),
            ),
            (
                "empty json body",
                dict(raw=b"", content_type="application/json"),
            ),
            (
                "gzip content encoding",
                dict(
                    body=self.frame_body(),
                    headers={"Content-Encoding": "gzip"},
                ),
            ),
            (
                "chunked transfer",
                dict(
                    body=self.frame_body(),
                    headers={"Transfer-Encoding": "chunked"},
                ),
            ),
            (
                "missing content length",
                dict(body=self.frame_body(), include_length=False),
            ),
            (
                "duplicate content length",
                dict(
                    raw=b"{}",
                    headers={"Content-Length": ["2", "3"]},
                ),
            ),
        ]
        for label, kwargs in cases:
            with self.subTest(label):
                response = self.call(token=self.submit_token, **kwargs)
                self.assertEqual(response.status, 400)
                self.assertIn("error", response.json())
                self.assertLess(len(response.body), 1024)
        self.assertEqual(self.executor.calls, [])

    def test_bad_words_and_binary_framing_are_rejected(self):
        for words in (
            [-1],
            [UINT64_MAX + 1],
            [1.5],
            [True],
            "not-a-list",
            {"0": 1},
        ):
            with self.subTest(words=words):
                response = self.call(
                    body={"request_id": 1, "words": words},
                    token=self.submit_token,
                )
                self.assertEqual(response.status, 400)

        payload = b"\x00" * 7
        cases = [
            (
                "partial word",
                dict(
                    raw=payload,
                    headers={
                        "X-NaN-Request-Id": "1",
                        "X-NaN-Route": POINT_ZERO_WIRE,
                    },
                ),
            ),
            (
                "missing request id",
                dict(raw=payload[:0], headers={}),
            ),
            (
                "bad request id",
                dict(
                    raw=struct.pack(">Q", 1),
                    headers={"X-NaN-Request-Id": "abc"},
                ),
            ),
            (
                "request id overflow",
                dict(
                    raw=struct.pack(">Q", 1),
                    headers={"X-NaN-Request-Id": str(UINT64_MAX + 1)},
                ),
            ),
        ]
        for label, kwargs in cases:
            with self.subTest(label):
                response = self.call(
                    token=self.submit_token,
                    content_type=BINARY_CONTENT_TYPE,
                    **kwargs,
                )
                self.assertEqual(response.status, 400)
                self.assertIn("error", response.json())
        self.assertEqual(self.executor.calls, [])

    # -- Authentication -------------------------------------------------------

    def test_missing_bad_and_wrong_role_auth_are_rejected(self):
        body = self.frame_body()
        response = self.call(body=body)
        self.assertEqual(response.status, 401)
        self.assertEqual(
            response.header("WWW-Authenticate"), 'Bearer realm="wave"'
        )
        self.assertIn("bearer", response.json()["error"].lower())

        response = self.call(body=body, token=self.wrong_token)
        self.assertEqual(response.status, 401)
        self.assertEqual(
            response.header("WWW-Authenticate"), 'Bearer realm="wave"'
        )

        response = self.call(
            body=body,
            headers={"Authorization": "Basic not-a-bearer"},
        )
        self.assertEqual(response.status, 401)

        for token in (self.worker_token, self.admin_token):
            with self.subTest(role=token):
                response = self.call(body=body, token=token)
                self.assertEqual(response.status, 403)
                self.assertIn("role", response.json()["error"].lower())
        self.assertEqual(self.executor.calls, [])

        for token in (
            self.submit_token, self.worker_token, self.admin_token,
            self.wrong_token,
        ):
            self.assertNotIn(token.encode("utf-8"), response.body)

    # -- Stale epoch and JAHS -------------------------------------------------

    def test_stale_epoch_is_rejected_before_executor(self):
        scheduler = self.scheduler

        class CyclingBridge(Point0Bridge):
            def encode(self, frame, *, active_slot=0, epoch=0):
                envelope = super().encode(
                    frame, active_slot=active_slot, epoch=epoch,
                )
                # Simulate a handoff between encode and dispatch.
                scheduler.cycle(1)
                return envelope

        router = Point0Router(CyclingBridge(), scheduler, self.executor)
        adapter = Point0HttpAdapter(router, self.service)
        response = self.call(
            adapter=adapter,
            body=self.frame_body(request_id=8),
            token=self.submit_token,
        )
        self.assertEqual(response.status, 409)
        error = response.json()["error"].lower()
        self.assertTrue("stale" in error or "epoch" in error, error)
        self.assertEqual(self.executor.calls, [])

    def test_jahs_handoff_seal_is_present_and_required(self):
        response = self.call(
            body=self.frame_body(),
            token=self.submit_token,
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.json()["jahs"],
            {"seal": "JAHS", "name": "Just A Handoff Seal", "epoch": 1},
        )

        class MissingJahsScheduler(WaveRingScheduler):
            def snapshot(self, now_tick=None):
                snapshot = super().snapshot(now_tick)
                snapshot.pop("jahs", None)
                return snapshot

        scheduler = MissingJahsScheduler(cycle_ticks=10, now_tick=0)
        scheduler.start(0)
        executor = RecordingExecutor()
        router = Point0Router(scheduler, executor)
        adapter = Point0HttpAdapter(router, self.service)
        response = self.call(
            adapter=adapter,
            body=self.frame_body(),
            token=self.submit_token,
        )
        self.assertEqual(response.status, 503)
        error = response.json()["error"].lower()
        self.assertTrue("jahs" in error or "handoff seal" in error, error)
        self.assertEqual(executor.calls, [])

    # -- Routing errors -------------------------------------------------------

    def test_unknown_route_and_wrong_method_are_rejected(self):
        response = self.call(
            path="/v1/unknown",
            body=self.frame_body(),
            token=self.submit_token,
        )
        self.assertEqual(response.status, 404)
        self.assertIn("not found", response.json()["error"].lower())

        response = self.call(
            method="GET",
            body=None,
            token=self.submit_token,
        )
        self.assertEqual(response.status, 405)
        self.assertEqual(response.header("Allow"), "POST")

    # -- Secret hygiene -------------------------------------------------------

    def test_no_service_tokens_in_rendered_responses_or_logs(self):
        tokens = (
            self.submit_token, self.worker_token, self.admin_token,
            self.wrong_token,
        )
        responses = []
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            responses.append(self.call(
                body=self.frame_body(), token=self.submit_token,
            ))
            responses.append(self.call(body=self.frame_body()))
            responses.append(self.call(
                body=self.frame_body(), token=self.wrong_token,
            ))
            responses.append(self.call(
                body=self.frame_body(), token=self.worker_token,
            ))
            responses.append(self.call(
                body=self.frame_body(route="MC0:0/R1"),
                token=self.submit_token,
            ))
            responses.append(self.call(
                raw=b'{"padding":"' + b"x" * MAX_BODY_BYTES + b'"}',
                token=self.submit_token,
            ))
            responses.append(self.call(
                method="GET", body=None, token=self.submit_token,
            ))
        for response in responses:
            self.assert_no_token(response, tokens)
        self.assertEqual(log.getvalue(), "")
        self.assertNotIn(self.submit_token, repr(self.adapter))

    # -- Optional loopback server --------------------------------------------

    def test_optional_loopback_server_round_trip(self):
        raw = json.dumps(
            self.frame_body(request_id=11, words=(4, 5, 6)),
            separators=(",", ":"),
        ).encode("utf-8")
        with Point0HttpServer(self.adapter) as server:
            request = Request(
                server.base_url + POINT0_PATH,
                data=raw,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + self.submit_token,
                },
                method="POST",
            )
            with urlopen(request, timeout=10) as response:
                status = response.status
                document = json.loads(response.read())
        self.assertEqual(status, 200)
        self.assertEqual(document["route"], POINT_ZERO_ADDRESS)
        self.assertEqual(document["request_id"], 11)
        self.assertEqual(document["words"], [4, 5, 6])
        self.assertEqual(document["jahs"]["seal"], JAHS_SEAL)
        handler = make_point0_handler(self.adapter)
        self.assertEqual(handler.server_version, "NaNROUTER-Point0/1")
        self.assertEqual(handler.protocol_version, "HTTP/1.1")


if __name__ == "__main__":
    unittest.main()
