import unittest

from runner_riddle.n16t_http import (
    MAX_FRAME_BYTES,
    N16THttpAdapter,
    N16TWorkerError,
)


class N16THttpAdapterTests(unittest.TestCase):
    def test_hands_exact_opaque_frame_to_worker_and_returns_peer_frame(self):
        request = b"N16T" + bytes(range(32))
        response = b"N16T" + bytes(reversed(range(32)))
        calls = []
        adapter = N16THttpAdapter(lambda frame: calls.append(frame) or response)

        self.assertEqual(adapter.exchange(request), response)
        self.assertEqual(calls, [request])

    def test_rejects_short_or_oversized_frames_before_worker(self):
        calls = []
        adapter = N16THttpAdapter(lambda frame: calls.append(frame) or b"N16T" + bytes(32))
        with self.assertRaises(ValueError):
            adapter.exchange(b"N16T" + bytes(31))
        with self.assertRaises(ValueError):
            adapter.exchange(b"x" * (MAX_FRAME_BYTES + 1))
        self.assertEqual(calls, [])

    def test_worker_failure_and_bad_response_fail_closed(self):
        adapter = N16THttpAdapter(lambda frame: (_ for _ in ()).throw(RuntimeError("secret")))
        with self.assertRaises(N16TWorkerError) as caught:
            adapter.exchange(b"N16T" + bytes(32))
        self.assertNotIn("secret", str(caught.exception))

        bad_response = N16THttpAdapter(lambda frame: b"not-a-frame")
        with self.assertRaises(N16TWorkerError):
            bad_response.exchange(b"N16T" + bytes(32))


if __name__ == "__main__":
    unittest.main()
