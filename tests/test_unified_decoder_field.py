from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "spec" / "unified-decoder-field.v1.json"


class UnifiedDecoderFieldTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(SPEC.read_text(encoding="utf-8"))

    def test_255_heads_plus_fixed_nannet_port(self):
        field = self.document["field"]
        self.assertEqual(field["real_heads"], 255)
        self.assertEqual(field["nannet_position"], 255)
        self.assertEqual(field["ring_positions"], 256)
        self.assertEqual(field["head_state_channels"], 16)
        self.assertEqual(field["field_vector_words"], 255 * 16)

    def test_no_dense_three_way_tensor(self):
        field = self.document["field"]
        self.assertTrue(field["dense_three_way_tensor_forbidden"])
        tensors = self.document["tensors"]
        self.assertIn("no dense 255^3", tensors["rule"])
        self.assertIn("sparse", " ".join(tensors["shapes"]))

    def test_decoder_is_a_shared_field_not_255_models(self):
        decoder = self.document["decoder"]
        self.assertTrue(decoder["shared_trunk"])
        self.assertIn("not a full copy", decoder["per_head_adapter"])
        self.assertIn("sum_h", decoder["mixture"])
        self.assertIn("never a trainable head", decoder["nannet_rule"])

    def test_trig_and_gradient_roles_are_explicit(self):
        trig = self.document["trigonometry"]
        self.assertIn("RoPE-style relative phase", trig["uses"])
        gradients = self.document["gradients"]
        self.assertIn("cycle.train_step delta rule", gradients["native_mechanisms"])
        self.assertIn("not implemented", gradients["open"])

    def test_open_gates_and_non_claims(self):
        gates = " ".join(self.document["open_gates"])
        for phrase in (
            "255 x 255 tiled head-to-head field attention",
            "native backward pass",
            "joint training",
            "natural-prose evaluation",
            "fluency evaluation",
        ):
            self.assertIn(phrase, gates)
        nonclaims = " ".join(self.document["non_claims"])
        self.assertIn("No 255 independent models", nonclaims)
        self.assertIn("No fluent open-domain decoder", nonclaims)
        self.assertFalse(self.document["native_integration"]["production_authority"])


if __name__ == "__main__":
    unittest.main()
