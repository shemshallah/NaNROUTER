from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from runner_riddle.math_execution import MathExecutionStateError
from runner_riddle.math_http import (
    EXECUTE_PATH,
    HEALTH_PATH,
    JAHS_HEADER,
    LINK_PATH,
    MAX_BODY_BYTES,
    SCHEMA,
    MathHttpAdapter,
    MathHttpServer,
    make_math_handler,
)
from runner_riddle.math_registry import MathFunctionRegistry
from runner_riddle.math_runtime import MathRuntime
from runner_riddle.mth_registry import MthRegistry
from runner_riddle.wave_ring_scheduler import JAHS_SEAL
from runner_riddle.wave_service import WaveService
from runner_riddle.wave_store import WaveStore

from tests.test_math_end_to_end import REPO, make_leaf

SUBMIT_TOKEN = "math-submit-token-0000000000"
WORKER_TOKEN = "math-worker-token-1111111111"
ADMIN_TOKEN = "math-admin-token-22222222222"
WRONG_TOKEN = "math-wrong-token-999999999999"


class RecordingExecuteService:
    """Caller-supplied service that already owns prepared packet/lease state."""

    def __init__(self):
        self.calls = []

    def execute(self, request):
        self.calls.append(dict(request))
        return {
            "status": "COMPLETED",
            "result_digest": "a" * 64,
            "packet_id": request.get("packet_id"),
        }


class HealthOnlyService:
    def health(self):
        return {"status": "green", "prepared_packets": 0}


class TokenEchoExecuteService:
    def __init__(self, token):
        self.token = token
        self.calls = []

    def execute(self, request):
        self.calls.append(dict(request))
        return {
            "status": "COMPLETED",
            "result_digest": "b" * 64,
            "lease_token": self.token,
            "note": f"service used {self.token}",
        }


class StateRejectingExecuteService:
    def execute(self, request):
        raise MathExecutionStateError("packet is not leased")


class MathHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.native = MthRegistry.load(REPO / "spec" / "wave-capabilities.json")
        cls.functions = MathFunctionRegistry.load(
            REPO / "spec" / "math-functions.v1.json",
            implementations=cls.native,
        )

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.a = make_leaf(1, "a")
        self.b = make_leaf(2, "b")
        self.runtime = MathRuntime(
            self.functions,
            leaves={self.a.leaf_id: self.a, self.b.leaf_id: self.b},
        )
        self.adapter = MathHttpAdapter(self.runtime)
        self.auth_service = WaveService(
            WaveStore(
                root / "wave-bs.sqlite3", root / "wave-mc.sqlite3",
            ),
            SUBMIT_TOKEN,
            WORKER_TOKEN,
            ADMIN_TOKEN,
        )

    # -- Helpers --------------------------------------------------------------

    def call(
        self,
        adapter=None,
        *,
        method="POST",
        path=LINK_PATH,
        body=None,
        raw=None,
        token=None,
        jahs=JAHS_SEAL,
        content_type="application/json",
        headers=None,
        include_length=True,
    ):
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
        if jahs is not None:
            request_headers[JAHS_HEADER] = jahs
        request_headers.update(headers or {})
        return adapter.handle(method, path, request_headers, raw)

    def link_body(self, **kwargs):
        body = {
            "operands": [f"{self.a.leaf_id}@v1", f"{self.b.leaf_id}@v1"],
            "snapshot_id": "snp:" + "a" * 64,
        }
        body.update(kwargs)
        return body

    def assert_no_tokens(self, response, tokens):
        rendered = response.body + json.dumps(
            response.headers, sort_keys=True,
        ).encode("utf-8")
        for token in tokens:
            self.assertNotIn(token.encode("utf-8"), rendered)

    # -- Health ---------------------------------------------------------------

    def test_health_needs_no_auth_or_jahs_and_reports_execute_availability(self):
        response = self.call(
            method="GET", path=HEALTH_PATH, jahs=None, content_type=None,
        )
        self.assertEqual(response.status, 200)
        document = response.json()
        self.assertEqual(document["schema"], SCHEMA)
        self.assertEqual(document["route"], HEALTH_PATH)
        health = document["health"]
        self.assertEqual(health["status"], "green")
        self.assertTrue(health["healthy"])
        self.assertTrue(health["jahs_required"])
        self.assertEqual(health["body_limit_bytes"], MAX_BODY_BYTES)
        self.assertEqual(health["components"]["functions"]["healthy"], True)
        self.assertEqual(health["execute"]["available"], False)
        self.assertEqual(
            health["execute"]["reason"], "execute_service_not_configured"
        )
        self.assertNotIn("Authorization", response.headers)

    def test_health_reports_a_caller_supplied_execute_service(self):
        adapter = MathHttpAdapter(
            self.runtime, service=HealthOnlyService(),
        )
        response = self.call(
            adapter, method="GET", path=HEALTH_PATH, jahs=None,
            content_type=None,
        )
        self.assertEqual(response.status, 200)
        health = response.json()["health"]
        self.assertEqual(health["status"], "green")
        self.assertEqual(health["components"]["execute"]["status"], "green")
        self.assertEqual(health["execute"]["available"], False)
        self.assertEqual(
            health["execute"]["reason"], "execute_service_missing_execute"
        )

    # -- Bounds and parsing ---------------------------------------------------

    def test_oversized_body_is_rejected_with_a_typed_error(self):
        raw = b'{"padding":"' + b"x" * MAX_BODY_BYTES + b'"}'
        response = self.call(raw=raw)
        self.assertEqual(response.status, 413)
        error = response.json()["error"]
        self.assertEqual(error["code"], "BODY_TOO_LARGE")
        self.assertIn("exceeds", error["message"])
        self.assertLess(len(response.body), 1024)

    def test_exact_body_bound_is_not_rejected_for_size(self):
        raw = b"{" + b" " * (MAX_BODY_BYTES - 2) + b"}"
        response = self.call(raw=raw)
        # When JSON parsing is reached, the transport has accepted the exact
        # 2 MiB bound; the empty object is rejected by request validation.
        self.assertEqual(response.status, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")

    def test_missing_or_invalid_jahs_is_rejected_for_link_and_execute(self):
        for path in (LINK_PATH, EXECUTE_PATH):
            with self.subTest(path=path, case="missing"):
                response = self.call(path=path, body={}, jahs=None)
                self.assertEqual(response.status, 403)
                self.assertEqual(
                    response.json()["error"]["code"], "JAHS_REQUIRED"
                )
            with self.subTest(path=path, case="invalid"):
                response = self.call(path=path, body={}, jahs="JAHS2")
                self.assertEqual(response.status, 403)
                self.assertEqual(
                    response.json()["error"]["code"], "JAHS_INVALID"
                )

    def test_invalid_json_and_content_type_are_typed(self):
        cases = (
            ("malformed", b"{", "application/json", "INVALID_JSON"),
            ("not-object", b"[]", "application/json", "INVALID_JSON"),
            (
                "duplicate-key",
                b'{"operands":[],"operands":[]}',
                "application/json",
                "INVALID_JSON",
            ),
            ("empty", b"", "application/json", "EMPTY_BODY"),
            (
                "wrong-content-type",
                b"{}",
                "text/plain",
                "UNSUPPORTED_MEDIA_TYPE",
            ),
        )
        for label, raw, content_type, code in cases:
            with self.subTest(label):
                response = self.call(raw=raw, content_type=content_type)
                self.assertEqual(response.status, 400 if code != "UNSUPPORTED_MEDIA_TYPE" else 415)
                self.assertEqual(response.json()["error"]["code"], code)
                self.assertLess(len(response.body), 1024)

    def test_unknown_fields_and_execute_flag_are_rejected(self):
        response = self.call(body=self.link_body(payload={"x": 1}))
        self.assertEqual(response.status, 400)
        self.assertEqual(
            response.json()["error"]["code"], "UNSUPPORTED_FIELD"
        )

        body = self.link_body()
        body["execute"] = True
        response = self.call(body=body)
        self.assertEqual(response.status, 400)
        self.assertEqual(
            response.json()["error"]["code"], "EXECUTION_NOT_PERMITTED"
        )

    # -- Link ----------------------------------------------------------------

    def test_link_returns_candidate_output_without_execution(self):
        response = self.call(body=self.link_body())
        self.assertEqual(response.status, 200)
        self.assertEqual(response.header("X-NaN-JAHS"), JAHS_SEAL)
        self.assertEqual(response.header("X-NaN-Math-Route"), LINK_PATH)
        document = response.json()
        self.assertEqual(document["schema"], SCHEMA)
        self.assertEqual(document["route"], LINK_PATH)
        link = document["link"]
        self.assertEqual(link["schema"], "nanrouter.math-candidate-set.v1")
        self.assertGreaterEqual(link["candidate_count"], 1)
        self.assertIn(
            "math.vector.dot",
            [candidate["function_id"] for candidate in link["candidates"]],
        )
        self.assertEqual(link["execution"], "not_performed")
        self.assertEqual(link["authorization"], "not_granted")
        self.assertEqual(link["snapshot_id"], "snp:" + "a" * 64)
        self.assertEqual(
            response.header("X-NaN-Math-Candidate-Count"),
            str(link["candidate_count"]),
        )

    def test_link_accepts_an_explicit_math_expression(self):
        response = self.call(
            body={
                "query": f"{self.a.leaf_id}@v1 :: {self.b.leaf_id}@v1",
                "snapshot_id": "snp:" + "b" * 64,
            }
        )
        self.assertEqual(response.status, 200)
        link = response.json()["link"]
        self.assertIn(
            "math.vector.dot",
            [candidate["function_id"] for candidate in link["candidates"]],
        )

    def test_link_accepts_math_uri_operands(self):
        prefix = "math://GM0:SC0:MC0:BS0:0/leaf/"
        response = self.call(
            body={
                "operands": [
                    prefix + f"{self.a.leaf_id}@v1",
                    prefix + f"{self.b.leaf_id}@v1",
                ],
                "snapshot_id": "snp:" + "c" * 64,
            }
        )
        self.assertEqual(response.status, 200)
        link = response.json()["link"]
        self.assertIn(
            "math.vector.dot",
            [candidate["function_id"] for candidate in link["candidates"]],
        )

    def test_link_unknown_leaf_is_typed_and_does_not_execute(self):
        response = self.call(
            body={
                "operands": [
                    "nml:U0:vector:missing@v1",
                    f"{self.b.leaf_id}@v1",
                ],
            }
        )
        self.assertEqual(response.status, 400)
        error = response.json()["error"]
        self.assertEqual(error["code"], "LINK_REJECTED")
        self.assertEqual(error["reason"], "unknown_leaf")

    def test_nan_route_in_link_is_a_typed_address_context_error(self):
        response = self.call(
            body={
                "operands": [
                    "nan://GM0:SC0:MC0:BS0:0/HW0:123::BS0:0/HW0:124",
                    f"{self.b.leaf_id}@v1",
                ],
            }
        )
        self.assertEqual(response.status, 400)
        error = response.json()["error"]
        self.assertEqual(error["code"], "ADDRESS_CONTEXT_MISMATCH")
        self.assertEqual(error["reason"], "address_context_mismatch")

    # -- Execute -------------------------------------------------------------

    def test_execute_is_unavailable_with_an_explicit_reason(self):
        response = self.call(
            path=EXECUTE_PATH,
            body={"packet_id": "nmp:test"},
        )
        self.assertEqual(response.status, 503)
        error = response.json()["error"]
        self.assertEqual(error["code"], "UNAVAILABLE")
        self.assertEqual(
            error["reason"], "execute_service_not_configured"
        )
        self.assertFalse(error.get("retryable", False))

    def test_execute_delegates_to_caller_supplied_service(self):
        service = RecordingExecuteService()
        adapter = MathHttpAdapter(self.runtime, service=service)
        response = self.call(
            adapter,
            path=EXECUTE_PATH,
            body={"packet_id": "nmp:test", "now_tick": 7},
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(response.header("X-NaN-JAHS"), JAHS_SEAL)
        execution = response.json()["execution"]
        self.assertEqual(execution["status"], "COMPLETED")
        self.assertEqual(execution["packet_id"], "nmp:test")
        self.assertEqual(
            service.calls,
            [{"packet_id": "nmp:test", "now_tick": 7}],
        )

    def test_execute_service_typed_state_error_is_preserved(self):
        adapter = MathHttpAdapter(
            self.runtime, service=StateRejectingExecuteService(),
        )
        response = self.call(
            adapter, path=EXECUTE_PATH, body={"packet_id": "nmp:test"},
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(
            response.json()["error"]["code"], "STATE_REJECTED"
        )

    def test_bare_execution_bridge_is_not_accepted_as_a_service(self):
        # The constructor accepts wrapper-shaped services only; a bare bridge
        # type is rejected explicitly before any request can be dispatched.
        from runner_riddle.math_execution import MathExecutionBridge

        class BridgeLike(MathExecutionBridge):
            def __init__(self):  # deliberately bypasses bridge composition
                pass

        with self.assertRaises(TypeError):
            MathHttpAdapter(self.runtime, service=BridgeLike())

    # -- Authentication and secret hygiene -----------------------------------

    def test_auth_reuses_wave_service_and_never_echoes_tokens(self):
        adapter = MathHttpAdapter(
            self.runtime, auth=self.auth_service,
        )
        body = self.link_body()
        responses = [
            self.call(adapter, body=body),
            self.call(adapter, body=body, token=WRONG_TOKEN),
            self.call(adapter, body=body, token=WORKER_TOKEN),
            self.call(adapter, body=body, token=SUBMIT_TOKEN),
        ]
        self.assertEqual(
            [response.status for response in responses],
            [401, 401, 403, 200],
        )
        for response in responses:
            self.assert_no_tokens(
                response,
                (SUBMIT_TOKEN, WORKER_TOKEN, ADMIN_TOKEN, WRONG_TOKEN),
            )

        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            self.call(adapter, body=body, token=SUBMIT_TOKEN)
        self.assertEqual(log.getvalue(), "")
        self.assertNotIn(SUBMIT_TOKEN, repr(adapter))

    def test_execute_response_redacts_tokens_even_if_service_echoes_them(self):
        service = TokenEchoExecuteService(SUBMIT_TOKEN)
        adapter = MathHttpAdapter(
            self.runtime, service=service, auth=self.auth_service,
        )
        response = self.call(
            adapter,
            path=EXECUTE_PATH,
            body={"packet_id": "nmp:test"},
            token=SUBMIT_TOKEN,
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.json()["execution"]["lease_token"], "[REDACTED]"
        )
        self.assert_no_tokens(
            response, (SUBMIT_TOKEN, WORKER_TOKEN, ADMIN_TOKEN, WRONG_TOKEN)
        )

    # -- Routing and handler --------------------------------------------------

    def test_routing_and_method_errors_are_typed(self):
        response = self.call(method="GET", path=LINK_PATH, jahs=None)
        self.assertEqual(response.status, 405)
        self.assertEqual(response.header("Allow"), "POST")

        response = self.call(path=HEALTH_PATH, body={})
        self.assertEqual(response.status, 405)
        self.assertEqual(response.header("Allow"), "GET")

        response = self.call(path="/v1/math/unknown", body={})
        self.assertEqual(response.status, 404)
        self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")

    def test_handler_is_constructible_without_a_live_socket(self):
        handler = make_math_handler(self.adapter)
        self.assertEqual(handler.server_version, "NaNROUTER-Math/1")
        self.assertEqual(handler.protocol_version, "HTTP/1.1")

    def test_optional_loopback_server_round_trip(self):
        raw = json.dumps(self.link_body()).encode("utf-8")
        with MathHttpServer(self.adapter) as server:
            request = Request(
                server.base_url + LINK_PATH,
                data=raw,
                headers={
                    "Content-Type": "application/json",
                    JAHS_HEADER: JAHS_SEAL,
                },
                method="POST",
            )
            with urlopen(request, timeout=10) as response:
                status = response.status
                document = json.loads(response.read())
        self.assertEqual(status, 200)
        self.assertEqual(document["schema"], SCHEMA)
        self.assertGreaterEqual(document["link"]["candidate_count"], 1)


if __name__ == "__main__":
    unittest.main()
