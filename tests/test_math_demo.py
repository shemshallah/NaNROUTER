from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from tools.run_math_demo import main, run_demo


class MathDemoTests(unittest.TestCase):
    def test_vertical_slice_runs_to_committed_with_output_feedback(self):
        with tempfile.TemporaryDirectory() as temp:
            report = run_demo(Path(temp))
        self.assertTrue(report["ok"])
        self.assertEqual(report["admission_verdict"], "VALID")
        self.assertEqual(report["execution_state"], "COMMITTED")
        self.assertEqual(report["job_state"], "done")
        self.assertTrue(report["committed"])
        self.assertEqual(report["kernel_ids"], ["mth.vector.dot256.f32"])
        self.assertEqual(
            report["feedback"]["leaf_id"], report["output_leaf_id"],
        )
        self.assertEqual(
            report["feedback"]["content_digest"], report["result_digest"],
        )
        self.assertIn("not a claimed numeric", report["note"])

    def test_cli_json_returns_success(self):
        with tempfile.TemporaryDirectory() as temp:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = main(["--root", temp, "--json"])
        self.assertEqual(code, 0)
        self.assertIn('"ok": true', output.getvalue())


if __name__ == "__main__":
    unittest.main()
