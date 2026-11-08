from __future__ import annotations

import unittest

from runner_riddle.execution_evidence import (
    NATIVE_SCHEMA,
    ExecutionEvidence,
    ExecutionEvidenceError,
)


def evidence(**overrides):
    values = {
        "packet_id": "nmp:" + "a" * 64,
        "job_id": "job:" + "b" * 64,
        "kernel_id": "mth.vector.dot256.f32",
        "runner_id": "MC0:0/R0",
        "result_digest": "c" * 64,
        "precision": "float32",
        "output_leaf_id": "nml:U0:scalar:dot",
        "output_digest": "c" * 64,
        "residual": 0,
        "error_bound": 1,
        "saturation": 0,
        "iterations": 256,
        "guest_source_digest": "d" * 64,
        "guest_image_digest": "e" * 64,
        "lease_epoch": 3,
        "ring_incarnation": "ring:test",
        "ring_epoch": 2,
        "jahs": "JAHS",
        "numerical_policy": {"precision": "float32"},
        "provenance": {"program_id": 900},
    }
    values.update(overrides)
    return ExecutionEvidence(**values)


class ExecutionEvidenceTests(unittest.TestCase):
    def test_roundtrip_and_binding_validation(self):
        record = evidence()
        self.assertEqual(record.to_dict()["schema"], "nanrouter.execution-evidence.v1")
        record.validate_binding(
            packet_id=record.packet_id, job_id=record.job_id,
            kernel_id=record.kernel_id, lease_epoch=3,
        )
        self.assertEqual(len(record.digest()), 64)

    def test_mismatched_binding_is_rejected(self):
        record = evidence()
        for kwargs in (
            {"packet_id": "nmp:" + "f" * 64},
            {"job_id": "job:" + "f" * 64},
            {"kernel_id": "mth.other.f32"},
            {"lease_epoch": 4},
        ):
            with self.subTest(**kwargs):
                with self.assertRaises(ExecutionEvidenceError):
                    record.validate_binding(**kwargs)

    def test_required_digests_and_positive_epochs_are_enforced(self):
        with self.assertRaises(ExecutionEvidenceError):
            evidence(result_digest="not-a-digest")
        with self.assertRaises(ExecutionEvidenceError):
            evidence(guest_source_digest="short")
        with self.assertRaises(ExecutionEvidenceError):
            evidence(lease_epoch=0)
        with self.assertRaises(ExecutionEvidenceError):
            evidence(iterations=-1)

    def test_secret_keys_are_rejected_recursively(self):
        with self.assertRaises(ExecutionEvidenceError):
            evidence(provenance={"lease_token": "secret"})
        with self.assertRaises(ExecutionEvidenceError):
            evidence(numerical_policy={"nested": {"password": "x"}})

    def test_native_mapping_is_converted_without_host_math(self):
        native = {
            "schema": NATIVE_SCHEMA,
            "packet_id": "nmp:" + "a" * 64,
            "job_id": "job:" + "b" * 64,
            "function_id": "mth.vector.dot256.f32",
            "lease_owner": "MC0:0/R0",
            "output_digest": "c" * 64,
            "guest_steps": 4096,
            "guest_source_digest": "d" * 64,
            "guest_image_digest": "e" * 64,
            "lease_epoch": 2,
            "program_id": 900,
        }
        record = ExecutionEvidence.from_native_mapping(native)
        self.assertEqual(record.iterations, 4096)
        self.assertEqual(record.provenance["program_id"], 900)
        with self.assertRaises(ExecutionEvidenceError):
            ExecutionEvidence.from_native_mapping(
                dict(native, schema="nanrouter.unknown.v1")
            )


if __name__ == "__main__":
    unittest.main()
