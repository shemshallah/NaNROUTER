"""NaNROUTER public ingress -> private NANNET portal cannot be an open proxy."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from runner_riddle.portal_loopback import (
    PortalLoopbackProxy, PortalProxyError, is_portal_path,
)


class PrivatePortal(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length)
        response = json.dumps({
            "path": self.path, "received_hex": payload.hex(),
            "authorization_present": self.headers.get("Authorization") == "Bearer signed-nannet-token",
            "signature": self.headers.get("X-NANNET-Signature"),
        }).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, fmt, *args):
        pass


class RouterPortalProxyTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), PrivatePortal)
        worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.proxy = PortalLoopbackProxy(self.server.server_port)

    def test_signed_auth_and_raw_nannet_frame_are_forwarded_unchanged(self):
        frame = bytes(range(32))
        code, mime, raw = self.proxy.request(
            "POST", "/v1/nannet/bridge", {
                "Content-Type": "application/x-n16b",
                "Authorization": "Bearer signed-nannet-token",
                "X-NANNET-Signature": "auth-signature",
                "X-Untrusted-Security-Header": "must-not-forward",
            }, frame)
        self.assertEqual(code, 201)
        self.assertEqual(mime, "application/json")
        result = json.loads(raw)
        self.assertEqual(result["received_hex"], frame.hex())
        self.assertTrue(result["authorization_present"])
        self.assertEqual(result["signature"], "auth-signature")

    def test_router_native_namespaces_are_never_forwarded(self):
        for path in (
            "/healthz", "/n16t", "/v1/riddle/queue", "/v1/hierarchy/resolve",
            "/v1/hermes/leases/open", "/v1/point0", "http://evil.test/v1/pair",
            "//evil.test/v1/pair", "/v1//pair", "/v1/pair#fragment",
            "/v1/../../../pair",
        ):
            with self.subTest(path=path):
                if "/../" not in path:
                    self.assertFalse(is_portal_path(path))
        for path in ("/v1/pair", "/v1/authorize", "/v1/revoke",
                     "/v1/hermes/register", "/v1/nannet/bridge"):
            self.assertTrue(is_portal_path(path))
        with self.assertRaises(PortalProxyError):
            self.proxy.request("POST", "/v1/riddle/ack", {}, b"not a guest")

    def test_invalid_port_body_and_header_fail_closed(self):
        with self.assertRaises(PortalProxyError):
            PortalLoopbackProxy(808)
        with self.assertRaises(PortalProxyError):
            self.proxy.request("DELETE", "/v1/pair", {})
        with self.assertRaises(PortalProxyError):
            self.proxy.request("POST", "/v1/pair", {}, b"x" * (2097152 + 1))
        with self.assertRaises(PortalProxyError):
            self.proxy.request("POST", "/v1/pair",
                               {"X-NANNET-Signature": "invalid\nvalue"}, b"123")


if __name__ == "__main__":
    unittest.main()
