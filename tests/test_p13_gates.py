from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
GATES = REPO / "spec" / "p13-gates.json"


class P13GateLedgerTests(unittest.TestCase):
    def test_every_p13_gate_is_explicitly_blocked(self):
        document = json.loads(GATES.read_text())
        self.assertEqual(document["schema"], "nanrouter.p13-gates.v1")
        gates = document["gates"]
        self.assertEqual(len(gates), 8)
        ids = {gate["id"] for gate in gates}
        self.assertEqual(
            ids,
            {
                "live-koyeb-nannet0",
                "signed-volume-registry",
                "production-mc0db",
                "frozen-model-lm-ablation",
                "r7-heldout",
                "capacity-vs-snr",
                "glt-2mib-enforcement",
                "native-numeric-executor",
            },
        )
        for gate in gates:
            self.assertEqual(gate["status"], "blocked", gate["id"])
            self.assertTrue(gate["reason"].strip(), gate["id"])
            self.assertTrue(gate["required_evidence"], gate["id"])
            self.assertNotIn("passed", gate["status"])

    def test_blocked_gates_have_no_fabricated_result_fields(self):
        document = json.loads(GATES.read_text())
        for gate in document["gates"]:
            for forbidden in ("result", "measurement", "score", "claim"):
                self.assertNotIn(forbidden, gate, gate["id"])


if __name__ == "__main__":
    unittest.main()
