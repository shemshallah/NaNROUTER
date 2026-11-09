"""Detached graph-source attestation: real Ed25519 signatures, no promotion."""
import hashlib
import unittest

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.exceptions import InvalidSignature
except ImportError:  # optional local dependency; CI installs cryptography
    Ed25519PrivateKey = None
    InvalidSignature = None

from runner_riddle.graph_sender_attestation import (
    GraphSenderAttestationError, sign_graph_attestation, canonical,
    _DOMAIN,
)


@unittest.skipUnless(
    Ed25519PrivateKey is not None, "cryptography package is not installed"
)
class AttestationTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        header = dict(
            schema="nanrouter.nan-layer-master-commitment/1",
            topology_sha256="a" * 64,
            parent_root_sha256="b" * 64,
            chart_generation=3,
            total_edges=1,
            candidate_edges=1,
            retracted_edges=0,
            layer_counts=[0, 1] + [0] * 8,
            state_sha256="c" * 64,
            history_sha256="d" * 64,
        )
        self.page = {
            **header,
            "graph_commitment_sha256": hashlib.sha256(
                b"nanrouter.nan-layer-commitment/1\0" + canonical(header)).hexdigest(),
            "snapshot_consistent": True,
            "signed_by_router": False,
            "native_mth_receipt": False,
            "mathematical_truth_promoted": False,
        }

    def issue(self, **params):
        options = dict(router_id="nanrouter-0", key_id="router-signing-v1",
                       private_key=self.key, nonce="5" * 32,
                       issued_at=1730000000)
        options.update(params)
        return sign_graph_attestation(self.page, **options)

    def test_real_signature_binds_sender_history_and_epoch(self):
        att = self.issue()
        body = {k: v for k, v in att.items() if k not in (
            "signature_hex", "signed_by_router", "native_mth_receipt",
            "mathematical_truth_promoted",
        )}
        self.key.public_key().verify(
            bytes.fromhex(att["signature_hex"]), _DOMAIN + canonical(body))
        self.assertEqual(att["history_sha256"], self.page["history_sha256"])
        self.assertEqual(att["chart_generation"], 3)
        self.assertTrue(att["signed_by_router"])
        self.assertFalse(att["native_mth_receipt"])
        self.assertFalse(att["mathematical_truth_promoted"])
        for changed in (
            {**body, "router_id": "wrong"},
            {**body, "chart_generation": 4},
            {**body, "history_sha256": "0" * 64},
            {**body, "graph_commitment_sha256": "0" * 64},
        ):
            with self.subTest(changed=changed), self.assertRaises(InvalidSignature):
                self.key.public_key().verify(
                    bytes.fromhex(att["signature_hex"]),
                    _DOMAIN + canonical(changed))

    def test_bad_header_and_untrusted_falsy_fields_rejected(self):
        for field, value in (
            ("graph_commitment_sha256", "e" * 64),
            ("native_mth_receipt", True),
            ("signed_by_router", True),
            ("mathematical_truth_promoted", True),
            ("history_sha256", "broken"),
            ("chart_generation", True),
            ("snapshot_consistent", False),
        ):
            with self.subTest(field=field):
                modified = dict(self.page, **{field: value})
                with self.assertRaises(GraphSenderAttestationError):
                    sign_graph_attestation(
                        modified, router_id="nanrouter-0",
                        key_id="signing-v1", private_key=self.key)

    def test_invalid_keys_sender_nonce_and_timestamp(self):
        for update in (
            {"router_id": ""},
            {"key_id": "../invalid"},
            {"private_key": object()},
            {"nonce": "not-a-nonce"},
            {"issued_at": True},
            {"issued_at": 0},
        ):
            with self.subTest(update=update), self.assertRaises(
                    GraphSenderAttestationError):
                self.issue(**update)


if __name__ == "__main__":
    unittest.main()
