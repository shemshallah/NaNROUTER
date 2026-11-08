"""Guest-backed NMP native admission receipt production regressions."""
from __future__ import annotations

import json
import unittest

from runner_riddle import nmp
from runner_riddle.math_objects import digest_object
from runner_riddle.n16t_guest import (
    N16TGuestExecutionMetadata,
    N16TGuestPool,
    N16TGuestRuntimeError,
    N16TNativeAdmissionReceipt,
    N16TNativeAdmissionReceiptError,
    build_native_admission_receipt,
    validate_guest_native_admission_receipt,
)

SNAP = "snp:" + "a" * 64
RULES = "rs:" + "c" * 64
PREFLIGHT = "d" * 64
FUNCTION = "math.vector.dot.v1"
CANDIDATE = "cnd:" + "b" * 64
INPUTS = (
    {"leaf_id": "nml:U0:vector:1", "version": 1, "digest": "1" * 64},
    {"leaf_id": "nml:U0:vector:2", "version": 1, "digest": "2" * 64},
)


def make_packet(**overrides):
    fields = {
        "snapshot_id": SNAP,
        "base_generation": 7,
        "lane_id": 3,
        "universe_id": "U0",
        "function_id": FUNCTION,
        "function_version": 1,
        "candidate_id": CANDIDATE,
        "inputs": INPUTS,
        "admission_verdict": "VALID",
        "preflight_digest": PREFLIGHT,
        "preflight_result": "VALID",
        "ruleset_id": "math.rules.core.v1",
        "ruleset_version": 1,
        "ruleset_snapshot_id": RULES,
        "capability_set": ({
            "required": "vector.dot",
            "workspace": 256,
            "precision": "float32",
        },),
        "capability_epoch": 1,
        "guest_words": 256,
        "ring_incarnation": "ring-inc-1",
        "ring_epoch": 1,
        "jahs": nmp.JAHS_SEAL,
        "state": nmp.PROPOSED,
        "metadata": {"native_admission_required": True},
    }
    fields.update(overrides)
    return nmp.NmpPacket(**fields)


def guest_metadata(packet, **overrides):
    metadata = {
        "packet_id": packet.packet_id,
        "candidate_digest": digest_object({
            "candidate_id": packet.candidate_id,
            "function_id": packet.function_id,
            "function_version": packet.function_version,
        }),
        "snapshot_id": packet.snapshot_id,
        "ruleset_snapshot_id": packet.ruleset_snapshot_id,
        "rule_epoch": 7,
        "rule_digest": "a" * 64,
        "preflight_digest": packet.preflight_digest,
        "input_digest": digest_object([
            nmp._input_identity(item) for item in packet.inputs
        ]),
        "capability_digest": packet.capability_set_digest,
        "generation": packet.generation,
        "program_id": 79,
        "guest_status": 0,
        "producer": "nan16_guest",
    }
    metadata.update(overrides)
    return metadata


def execution_evidence(packet, *, program_id=79, output_digest="e" * 64):
    return {
        "schema": "nanrouter.native-kernel-execution.v1",
        "packet_id": packet.packet_id,
        "function_id": packet.function_id,
        "program_id": program_id,
        "output_kind": 3,
        "dimension": 4,
        "output_count": 1,
        "output_digest": output_digest,
        "guest_steps": 4096,
        "guest_image_digest": "b" * 64,
        "guest_source_digest": "c" * 64,
        "lease_epoch": 1,
        "lease_owner": "worker-A",
    }


class NativeAdmissionReceiptBuildTests(unittest.TestCase):
    def test_valid_receipt_is_packet_bound_and_marks_preflight(self):
        packet = make_packet()
        receipt = build_native_admission_receipt(
            packet, guest_metadata(packet), expected_program_id=79
        )

        self.assertEqual(receipt["schema"], nmp.NATIVE_ADMISSION_RECEIPT_SCHEMA)
        self.assertEqual(receipt["producer"], "nan16_guest")
        self.assertEqual(receipt["guest_status"], 0)
        self.assertEqual(receipt["packet_id"], packet.packet_id)
        body = {key: value for key, value in receipt.items() if key != "receipt_digest"}
        self.assertEqual(receipt["receipt_digest"], digest_object(body))
        self.assertEqual(
            nmp.validate_native_admission_receipt(receipt, packet), receipt
        )
        self.assertEqual(
            validate_guest_native_admission_receipt(
                receipt, packet, expected_program_id=79
            ),
            receipt,
        )

        preflighted = packet.mark_preflight(
            result="VALID",
            digest=packet.preflight_digest,
            admission_receipt=receipt,
        )
        self.assertEqual(preflighted.state, nmp.PREFLIGHTED)
        self.assertEqual(preflighted.admission_receipt, receipt)

    def test_typed_entry_points_and_pool_boundary_agree(self):
        packet = make_packet()
        metadata = N16TGuestExecutionMetadata.from_mapping(
            guest_metadata(packet)
        )
        first = N16TNativeAdmissionReceipt.from_guest_execution(
            packet, metadata, expected_program_id=79
        )
        second = N16TNativeAdmissionReceipt.from_execution(
            packet, guest_metadata(packet), expected_program_id=79
        )
        self.assertEqual(first, second)

        pool = N16TGuestPool("unused-library", "unused-image", "unused-labels")
        try:
            third = pool.build_native_admission_receipt(
                packet, guest_metadata(packet), expected_program_id=79
            )
            self.assertEqual(first, third)
            self.assertEqual(
                pool.native_admission_receipt(
                    packet, guest_metadata(packet), expected_program_id=79
                ),
                first,
            )
        finally:
            pool.close()

    def test_closed_pool_refuses_receipt_production(self):
        packet = make_packet()
        pool = N16TGuestPool("unused-library", "unused-image", "unused-labels")
        pool.close()
        with self.assertRaisesRegex(N16TGuestRuntimeError, "closed"):
            pool.build_native_admission_receipt(
                packet, guest_metadata(packet), expected_program_id=79
            )

    def test_mapping_packet_and_identity_fields_are_supported(self):
        packet = make_packet()
        metadata = {
            key: value
            for key, value in guest_metadata(packet).items()
            if key
            not in {
                "candidate_digest",
                "input_digest",
                "capability_digest",
                "preflight_digest",
            }
        }
        metadata.update({
            "candidate_id": packet.candidate_id,
            "function_id": packet.function_id,
            "function_version": packet.function_version,
            "inputs": [dict(item) for item in packet.inputs],
            "capability_set": [dict(item) for item in packet.capability_set],
            "preflight": {"digest": packet.preflight_digest},
        })
        receipt = build_native_admission_receipt(
            packet.to_dict(), metadata, expected_program_id=79
        )
        self.assertEqual(receipt["packet_id"], packet.packet_id)

    def test_optional_output_binding_is_preserved_and_checked(self):
        packet = make_packet()
        descriptor_digest = digest_object([3, 0, 1, 1, 1, 9000, 3, 0])
        metadata = guest_metadata(
            packet,
            output_generation=packet.generation + 1,
            output_descriptor_digest=descriptor_digest,
        )
        receipt = build_native_admission_receipt(
            packet, metadata, expected_program_id=79
        )
        self.assertEqual(receipt["output_generation"], packet.generation + 1)
        self.assertEqual(
            receipt["output_descriptor_digest"], descriptor_digest
        )
        self.assertEqual(
            validate_guest_native_admission_receipt(receipt, packet), receipt
        )

        with self.assertRaisesRegex(
            N16TNativeAdmissionReceiptError, "generation \\+ 1"
        ):
            build_native_admission_receipt(
                packet,
                guest_metadata(
                    packet, output_generation=packet.generation + 2
                ),
                expected_program_id=79,
            )

    def test_execution_evidence_and_output_digest_are_cross_checked(self):
        packet = make_packet()
        metadata = guest_metadata(
            packet,
            guest_image_digest="b" * 64,
            guest_source_digest="c" * 64,
        )
        receipt = build_native_admission_receipt(
            packet,
            metadata,
            expected_program_id=79,
            execution_evidence=execution_evidence(packet),
            result_digest="e" * 64,
        )
        self.assertEqual(receipt["guest_image_digest"], "b" * 64)
        self.assertEqual(receipt["guest_source_digest"], "c" * 64)
        self.assertNotIn("output_digest", receipt)

        with self.assertRaisesRegex(
            N16TNativeAdmissionReceiptError, "output digest"
        ):
            build_native_admission_receipt(
                packet,
                metadata,
                expected_program_id=79,
                execution_evidence=execution_evidence(packet),
                result_digest="f" * 64,
            )


class NativeAdmissionReceiptRejectionTests(unittest.TestCase):
    def test_missing_binding_fails_closed(self):
        packet = make_packet()
        for field in (
            "packet_id",
            "candidate_digest",
            "snapshot_id",
            "ruleset_snapshot_id",
            "rule_epoch",
            "rule_digest",
            "preflight_digest",
            "input_digest",
            "capability_digest",
            "generation",
            "program_id",
            "guest_status",
        ):
            with self.subTest(field=field):
                metadata = guest_metadata(packet)
                metadata.pop(field)
                with self.assertRaisesRegex(
                    N16TNativeAdmissionReceiptError, field
                ):
                    build_native_admission_receipt(
                        packet, metadata, expected_program_id=79
                    )

        with self.assertRaisesRegex(
            N16TNativeAdmissionReceiptError, "must be an object"
        ):
            build_native_admission_receipt(
                packet, "not-metadata", expected_program_id=79
            )

    def test_packet_without_authoritative_binding_fails_closed(self):
        for field, value in (
            ("ruleset_snapshot_id", ""),
            ("preflight_digest", None),
        ):
            with self.subTest(field=field):
                packet = make_packet(**{field: value})
                with self.assertRaises(N16TNativeAdmissionReceiptError):
                    build_native_admission_receipt(
                        packet,
                        guest_metadata(packet),
                        expected_program_id=79,
                    )

        packet = make_packet()
        without_packet_id = dict(packet.to_dict())
        without_packet_id["packet_id"] = ""
        with self.assertRaises(N16TNativeAdmissionReceiptError):
            build_native_admission_receipt(
                without_packet_id,
                guest_metadata(packet),
                expected_program_id=79,
            )

    def test_wrong_packet_and_candidate_are_rejected(self):
        packet = make_packet()
        other = make_packet(candidate_id="cnd:" + "e" * 64)
        with self.assertRaisesRegex(
            N16TNativeAdmissionReceiptError, "does not match the packet"
        ):
            build_native_admission_receipt(
                packet, guest_metadata(other), expected_program_id=79
            )

        metadata = guest_metadata(packet, candidate_digest="f" * 64)
        with self.assertRaisesRegex(
            N16TNativeAdmissionReceiptError, "candidate_digest"
        ):
            build_native_admission_receipt(
                packet, metadata, expected_program_id=79
            )

    def test_wrong_program_is_rejected(self):
        packet = make_packet()
        with self.assertRaisesRegex(
            N16TNativeAdmissionReceiptError, "expected program"
        ):
            build_native_admission_receipt(
                packet, guest_metadata(packet), expected_program_id=78
            )

        with self.assertRaisesRegex(
            N16TNativeAdmissionReceiptError, "program_id"
        ):
            build_native_admission_receipt(
                packet,
                guest_metadata(packet),
                expected_program_id=79,
                execution_evidence=execution_evidence(packet, program_id=78),
            )

    def test_guest_denied_status_cannot_produce_a_receipt(self):
        packet = make_packet()
        for status in (1, 2, -1, True):
            with self.subTest(status=status):
                with self.assertRaisesRegex(
                    N16TNativeAdmissionReceiptError, "ALLOW|guest_status"
                ):
                    build_native_admission_receipt(
                        packet,
                        guest_metadata(packet, guest_status=status),
                        expected_program_id=79,
                    )
        with self.assertRaisesRegex(
            N16TNativeAdmissionReceiptError, "ALLOW"
        ):
            build_native_admission_receipt(
                packet,
                guest_metadata(packet, guest_allow=False),
                expected_program_id=79,
            )

    def test_wrong_producer_is_rejected(self):
        packet = make_packet()
        with self.assertRaisesRegex(
            N16TNativeAdmissionReceiptError, "producer"
        ):
            build_native_admission_receipt(
                packet,
                guest_metadata(packet, producer="host"),
                expected_program_id=79,
            )

    def test_digest_mismatch_is_rejected(self):
        packet = make_packet()
        for field in ("input_digest", "preflight_digest", "snapshot_id"):
            with self.subTest(field=field):
                value = "f" * 64 if field.endswith("_digest") else "snp:" + "f" * 64
                with self.assertRaisesRegex(
                    N16TNativeAdmissionReceiptError, field
                ):
                    build_native_admission_receipt(
                        packet,
                        guest_metadata(packet, **{field: value}),
                        expected_program_id=79,
                    )

        receipt = build_native_admission_receipt(
            packet, guest_metadata(packet), expected_program_id=79
        )
        tampered = dict(receipt)
        tampered["rule_digest"] = "b" * 64
        with self.assertRaisesRegex(
            N16TNativeAdmissionReceiptError, "digest does not match"
        ):
            validate_guest_native_admission_receipt(tampered, packet)

        bad_receipt_digest = dict(receipt)
        bad_receipt_digest["receipt_digest"] = "0" * 64
        with self.assertRaisesRegex(
            N16TNativeAdmissionReceiptError, "digest does not match"
        ):
            validate_guest_native_admission_receipt(bad_receipt_digest, packet)

    def test_result_digest_requires_execution_evidence(self):
        packet = make_packet()
        with self.assertRaisesRegex(
            N16TNativeAdmissionReceiptError, "requires native execution evidence"
        ):
            build_native_admission_receipt(
                packet,
                guest_metadata(packet),
                expected_program_id=79,
                result_digest="e" * 64,
            )


class NativeAdmissionReceiptSecretBoundaryTests(unittest.TestCase):
    def test_metadata_and_evidence_tokens_never_leak_into_the_receipt(self):
        packet = make_packet()
        secret = "bearer-secret-that-must-not-leak"
        metadata = guest_metadata(packet)
        metadata.update({
            "token": secret,
            "lease_token": secret,
            "authorization": "Bearer " + secret,
            "password": secret,
            "nested": {"token": secret},
        })
        evidence = execution_evidence(packet)
        evidence.update({
            "lease_token": secret,
            "authorization": "Bearer " + secret,
        })
        receipt = build_native_admission_receipt(
            packet,
            metadata,
            expected_program_id=79,
            execution_evidence=evidence,
            result_digest="e" * 64,
        )
        serialized = json.dumps(receipt, sort_keys=True)
        self.assertNotIn(secret, serialized)
        for field in ("token", "lease_token", "authorization", "password"):
            self.assertNotIn(field, receipt)

    def test_error_messages_do_not_echo_metadata_secrets(self):
        packet = make_packet()
        secret = "bearer-secret-that-must-not-leak"
        metadata = guest_metadata(packet)
        metadata["token"] = secret
        metadata.pop("packet_id")
        with self.assertRaises(N16TNativeAdmissionReceiptError) as caught:
            build_native_admission_receipt(
                packet, metadata, expected_program_id=79
            )
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn("packet_id", str(caught.exception).replace(
            "missing packet_id", ""
        ))


if __name__ == "__main__":
    unittest.main()
