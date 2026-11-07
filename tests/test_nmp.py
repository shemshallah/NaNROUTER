from __future__ import annotations

import inspect
import json
import unittest

from runner_riddle import nmp
from runner_riddle.native_preflight_receipt import (
    NativePreflightLeaseBinding,
    NativePreflightReceipt,
    NativePreflightReceiptError,
)
from runner_riddle.wave_ring_scheduler import WaveRingScheduler
from runner_riddle.math_objects import (
    MathAdmission,
    MathCandidate,
    admission_id_for,
    candidate_id_for,
    canonical_json,
)

SNAP = "snp:" + "a" * 64
OTHER_SNAP = "snp:" + "b" * 64
RULES = "rs:" + "c" * 64
OTHER_RULES = "rs:" + "e" * 64
PREFLIGHT = "d" * 64
OTHER_PREFLIGHT = "9" * 64
RESULT = "e" * 64
FUNCTION = "math.vector.dot.v1"
INPUTS = (
    {"leaf_id": "nml:U0:vector:1", "version": 1, "digest": "1" * 64},
    {"leaf_id": "nml:U0:vector:2", "version": 1, "digest": "2" * 64},
)
CID = candidate_id_for(SNAP, INPUTS, FUNCTION, 1)
AID = admission_id_for(CID, SNAP, "VALID", RULES)


def make_candidate(candidate_id: str = CID, snapshot_id: str = SNAP) -> MathCandidate:
    return MathCandidate(
        candidate_id=candidate_id,
        inputs=INPUTS,
        function_id=FUNCTION,
        function_version=1,
        snapshot_id=snapshot_id,
    )


def make_admission(
    *,
    verdict: str = "VALID",
    candidate_id: str = CID,
    snapshot_id: str = SNAP,
    ruleset_snapshot_id: str = RULES,
    preflight_digest: str = PREFLIGHT,
) -> MathAdmission:
    return MathAdmission(
        admission_id=admission_id_for(
            candidate_id, snapshot_id, verdict, ruleset_snapshot_id,
        ),
        candidate_id=candidate_id,
        verdict=verdict,
        snapshot_id=snapshot_id,
        rule_snapshot_id=ruleset_snapshot_id,
        preflight_digest=preflight_digest,
    )


def make_capability(**overrides):
    row = {
        "kernel_id": "vector.dot",
        "runner_id": "MC0:0/R0",
        "verified_digest": "f" * 64,
        "workspace": 1024,
        "precision": "float32",
        "status": "native_verified",
        "epoch": 1,
    }
    row.update(overrides)
    return row


def make_packet(*, state: str = nmp.CREATED, candidate_id: str = CID, **overrides):
    fields = {
        "snapshot_id": SNAP,
        "base_generation": 7,
        "lane_id": 3,
        "universe_id": "U0",
        "function_id": FUNCTION,
        "function_version": 1,
        "candidate_id": candidate_id,
        "inputs": INPUTS,
        "admission_id": AID,
        "admission_verdict": "VALID",
        "preflight_digest": PREFLIGHT,
        "preflight_result": "VALID",
        "ruleset_id": "math.rules.core.v1",
        "ruleset_version": 1,
        "ruleset_snapshot_id": RULES,
        "capability_set": (
            {"required": "vector.dot", "workspace": 256, "precision": "float32"},
        ),
        "capability_epoch": 1,
        "guest_words": 256,
        "ring_incarnation": "ring-inc-1",
        "ring_epoch": 1,
        "jahs": nmp.JAHS_SEAL,
        "state": state,
        "job_id": "job-1" if state in {nmp.QUEUED, nmp.EXECUTING} else None,
        "lease_epoch": 1 if state == nmp.EXECUTING else None,
    }
    if state in {nmp.COMPLETED, nmp.COMMITTED}:
        fields["result_digest"] = RESULT
        fields["result_status"] = "OK"
        fields["output_leaf_id"] = "nml:U0:scalar:9"
    if state == nmp.COMMITTED:
        fields["provenance"] = {"job_id": "job-1", "leaf_id": "nml:U0:scalar:9"}
    fields.update(overrides)
    return nmp.NmpPacket(**fields)


def gate(packet, **overrides):
    inputs = {
        "admission": make_admission(),
        "preflight": {
            "result": "VALID",
            "digest": PREFLIGHT,
            "rule_snapshot_id": RULES,
        },
        "capability": make_capability(),
        "ring_incarnation": "ring-inc-1",
        "ring_epoch": 1,
    }
    inputs.update(overrides)
    return nmp.execution_gate(packet, **inputs)


def child_inputs(index: int):
    return INPUTS + (
        {"leaf_id": f"nml:U0:vector:child-{index}", "version": 1,
         "digest": (str(index) * 64)[:64]},
    )


def committed_child(index: int):
    return make_packet(
        state=nmp.COMMITTED,
        candidate_id=f"cnd:child-{index}",
        inputs=child_inputs(index),
        result_digest=(str(index) * 64)[:64],
        provenance={"job_id": f"job-{index}"},
        output_leaf_id=f"nml:U0:scalar:{index}",
    )


class StateTransitionTests(unittest.TestCase):
    def test_happy_path_and_history(self):
        packet = make_packet()
        packet = packet.resolve()
        packet = packet.classify()
        packet = packet.propose()
        packet = packet.mark_preflight()
        self.assertEqual(packet.state, nmp.PREFLIGHTED)
        self.assertEqual(len(packet.history), 4)

        decision = gate(packet)
        self.assertTrue(decision.ok, decision.reason)
        packet = packet.queue(gate=decision)
        self.assertEqual(packet.state, nmp.QUEUED)

        decision = gate(packet)
        self.assertTrue(decision.ok, decision.reason)
        packet = packet.start_execution(gate=decision, job_id="job-1", lease_epoch=1)
        self.assertEqual(packet.state, nmp.EXECUTING)

        packet = packet.complete(RESULT, output_leaf_id="nml:U0:scalar:9")
        self.assertEqual(packet.state, nmp.COMPLETED)
        packet = packet.commit(provenance={"job_id": "job-1"})
        self.assertEqual(packet.state, nmp.COMMITTED)
        self.assertEqual(packet.result_digest, RESULT)
        self.assertEqual([entry["to"] for entry in packet.history][-4:-1],
                         [nmp.QUEUED, nmp.EXECUTING, nmp.COMPLETED])

    def test_proposed_cannot_jump_to_executing(self):
        packet = make_packet(state=nmp.PROPOSED)
        self.assertFalse(packet.can_transition(nmp.EXECUTING))
        self.assertFalse(packet.can_transition(nmp.QUEUED))
        self.assertTrue(packet.can_transition(nmp.PREFLIGHTED))
        with self.assertRaises(nmp.NmpTransitionError):
            packet.transition(nmp.EXECUTING)
        with self.assertRaises(nmp.NmpTransitionError):
            packet.transition(nmp.QUEUED)
        with self.assertRaises(nmp.NmpTransitionError):
            packet.transition(nmp.COMPLETED)
        self.assertEqual(packet.state, nmp.PROPOSED)

    def test_committed_requires_digest_provenance_and_jahs(self):
        no_digest = make_packet(state=nmp.COMPLETED, result_digest=None,
                                output_leaf_id="nml:U0:scalar:9")
        with self.assertRaises(nmp.NmpTransitionError):
            no_digest.commit(provenance={"job_id": "job-1"})

        no_provenance = make_packet(state=nmp.COMPLETED, output_leaf_id=None)
        with self.assertRaises(nmp.NmpTransitionError):
            no_provenance.commit()

        no_jahs = make_packet(state=nmp.COMPLETED, jahs=None)
        with self.assertRaises(nmp.NmpTransitionError):
            no_jahs.commit(provenance={"job_id": "job-1"})

        with self.assertRaises(nmp.NmpValidationError):
            make_packet(state=nmp.COMMITTED, provenance={}, output_leaf_id=None)

    def test_terminal_states_have_no_outgoing_edges(self):
        for state in sorted(nmp.REQUIRED_TERMINAL_STATES):
            packet = make_packet(
                state=state,
                failure_class=state,
                result_digest=None,
                output_leaf_id=None,
            )
            self.assertTrue(packet.is_terminal)
            with self.assertRaises(nmp.NmpTransitionError):
                packet.transition(nmp.COMMITTED, provenance={"job_id": "job-1"})

    def test_failed_null_and_cancelled_are_distinct(self):
        packets = {
            state: make_packet(
                state=state,
                failure_class=state,
                result_digest=None,
                output_leaf_id=None,
            )
            for state in (nmp.NULL, nmp.UNDEFINED, nmp.FAILED, nmp.CANCELLED)
        }
        self.assertNotEqual(packets[nmp.NULL].state, packets[nmp.UNDEFINED].state)
        self.assertNotEqual(packets[nmp.NULL].state, packets[nmp.FAILED].state)
        self.assertNotEqual(packets[nmp.FAILED].state, packets[nmp.CANCELLED].state)
        self.assertIsNone(packets[nmp.CANCELLED].result_digest)

    def test_cancelled_cannot_carry_a_result(self):
        with self.assertRaises(nmp.NmpValidationError):
            make_packet(state=nmp.CANCELLED, result_digest=RESULT)

    def test_batch_parent_cannot_be_queued(self):
        parent = make_packet(is_batch_parent=True)
        with self.assertRaises(nmp.NmpTransitionError):
            parent.transition(nmp.RESOLVED).transition(nmp.CLASSIFIED).transition(
                nmp.PROPOSED
            ).transition(nmp.PREFLIGHTED).transition(nmp.QUEUED)

    def test_lane_255_is_nannet0_not_a_lane(self):
        self.assertEqual(nmp.MAX_LANE, 254)
        self.assertEqual(nmp.NANNET0_LANE, 255)
        self.assertFalse(nmp.is_valid_lane(255))
        self.assertTrue(nmp.is_valid_lane(254))
        with self.assertRaises(nmp.NmpValidationError):
            make_packet(lane_id=255)
        with self.assertRaises(nmp.NmpValidationError):
            make_packet(lane_id=-1)
        with self.assertRaises(nmp.NmpValidationError):
            make_packet(lane_id=256)


class DedupeTests(unittest.TestCase):
    def test_dedupe_key_is_content_based_and_ignores_request_evidence(self):
        first = make_packet(request_id="request-a")
        second = make_packet(request_id="request-b", updated_tick=99)
        self.assertEqual(first.dedupe_key, second.dedupe_key)
        self.assertEqual(first.operation_id, second.operation_id)

        table = nmp.NmpInFlightTable()
        first_result = table.put(first)
        second_result = table.put(second)
        self.assertFalse(first_result.duplicate)
        self.assertTrue(second_result.duplicate)
        self.assertEqual(second_result.existing.packet_id, first.packet_id)
        self.assertIn(first.packet_id, second_result.subscribers)
        self.assertIn(second.packet_id, second_result.subscribers)
        self.assertEqual(len(table), 1)

    def test_request_id_is_not_an_idempotency_key(self):
        candidate_a = "cnd:" + "a" * 64
        candidate_b = "cnd:" + "b" * 64
        different_inputs = INPUTS + (
            {"leaf_id": "nml:U0:vector:3", "version": 1, "digest": "3" * 64},
        )
        first = make_packet(candidate_id=candidate_a, request_id="same")
        second = make_packet(
            candidate_id=candidate_b,
            inputs=different_inputs,
            request_id="same",
        )
        self.assertNotEqual(first.dedupe_key, second.dedupe_key)
        self.assertNotEqual(first.packet_id, second.packet_id)

    def test_candidate_name_is_not_operation_content(self):
        first = make_packet(candidate_id="cnd:" + "a" * 64)
        second = make_packet(candidate_id="cnd:" + "b" * 64)
        self.assertEqual(first.dedupe_key, second.dedupe_key)

    def test_snapshot_ruleset_and_policy_are_distinct_operations(self):
        base = make_packet()
        other_snapshot = make_packet(snapshot_id=OTHER_SNAP)
        other_ruleset = make_packet(ruleset_snapshot_id=OTHER_RULES)
        other_policy = make_packet(numerical_policy={"rounding": "nearest"})
        self.assertNotEqual(base.dedupe_key, other_snapshot.dedupe_key)
        self.assertNotEqual(base.dedupe_key, other_ruleset.dedupe_key)
        self.assertNotEqual(base.dedupe_key, other_policy.dedupe_key)

    def test_commutative_operand_order_is_canonicalised_only_when_declared(self):
        reversed_inputs = tuple(reversed(INPUTS))
        ordered = make_packet(inputs=INPUTS)
        reversed_ordered = make_packet(inputs=reversed_inputs)
        self.assertNotEqual(ordered.dedupe_key, reversed_ordered.dedupe_key)

        commutative = make_packet(inputs=INPUTS, commutative=True)
        commutative_reversed = make_packet(inputs=reversed_inputs, commutative=True)
        self.assertEqual(commutative.dedupe_key, commutative_reversed.dedupe_key)

    def test_in_flight_table_is_memory_only(self):
        table = nmp.NmpInFlightTable()
        self.assertFalse(table.durable)
        self.assertFalse(table.owns_jobs)
        self.assertEqual(len(table), 0)
        table.put(make_packet())
        self.assertEqual(len(table), 1)
        self.assertTrue(table.lookup(make_packet()).packet_id)


class BatchTests(unittest.TestCase):
    def _batch(self, size=3):
        parent = make_packet(is_batch_parent=True)
        children = tuple(
            make_packet(
                candidate_id=f"cnd:child-{index}",
                inputs=child_inputs(index),
            )
            for index in range(size)
        )
        return nmp.NmpBatch(parent, children)

    def test_parent_has_no_lease_and_children_are_independent(self):
        batch = self._batch()
        self.assertIsNone(batch.parent_lease)
        self.assertIsNone(batch.parent.job_id)
        with self.assertRaises(nmp.NmpBatchError):
            batch.lease_parent()
        self.assertEqual([child.batch_index for child in batch.children], [0, 1, 2])
        self.assertEqual(batch.parent.child_packet_ids,
                         tuple(child.packet_id for child in batch.children))

        advanced = batch.children[0].resolve().classify()
        updated = batch.replace_child(advanced)
        self.assertEqual(updated.children[0].state, nmp.CLASSIFIED)
        self.assertEqual(updated.children[1].state, nmp.CREATED)
        self.assertEqual(updated.children[2].state, nmp.CREATED)
        self.assertEqual(batch.children[0].state, nmp.CREATED)

        with self.assertRaises(nmp.NmpTransitionError):
            batch.parent.transition(nmp.QUEUED)

    def test_seal_requires_all_children_and_never_leases_parent(self):
        batch = self._batch()
        self.assertIsNone(batch.try_seal())
        with self.assertRaises(nmp.NmpSealError):
            batch.seal()

        updated = batch
        for index in range(len(batch.children)):
            updated = updated.replace_child(committed_child(index))
        self.assertTrue(updated.finished)
        seal = updated.seal(tick=12)
        self.assertEqual(seal.batch_id, updated.batch_id)
        self.assertEqual(seal.parent_packet_id, updated.parent.packet_id)
        self.assertFalse(seal.promotion_eligible)
        self.assertIsNone(seal.parent_lease)
        self.assertEqual(seal.jahs, nmp.JAHS_SEAL)
        self.assertEqual(len(seal.child_digests), 3)
        self.assertEqual(len(seal.digest), 64)
        self.assertEqual(seal.to_dict()["parent_lease"], None)

    def test_child_failure_and_cancellation_are_terminal_for_seal(self):
        batch = self._batch(2)
        failed = make_packet(
            state=nmp.FAILED,
            candidate_id="cnd:child-0",
            inputs=child_inputs(0),
            failure_class="EXECUTION_FAILED",
            result_digest=None,
            output_leaf_id=None,
        )
        cancelled = make_packet(
            state=nmp.CANCELLED,
            candidate_id="cnd:child-1",
            inputs=child_inputs(1),
            failure_class=nmp.CANCELLED,
            result_digest=None,
            output_leaf_id=None,
        )
        batch = batch.replace_child(failed).replace_child(cancelled)
        self.assertTrue(batch.finished)
        seal = batch.seal()
        self.assertEqual(seal.child_states, (nmp.FAILED, nmp.CANCELLED))

    def test_candidate_names_make_distinct_child_packets_but_share_operation(self):
        parent = make_packet(is_batch_parent=True)
        children = (
            make_packet(candidate_id="cnd:" + "a" * 64),
            make_packet(candidate_id="cnd:" + "b" * 64),
        )
        batch = nmp.NmpBatch(parent, children)
        self.assertEqual(len({child.packet_id for child in batch.children}), 2)
        self.assertEqual(len({child.dedupe_key for child in batch.children}), 1)

    def test_batch_parent_cannot_be_an_execution_state_or_hold_a_job(self):
        with self.assertRaises(nmp.NmpValidationError):
            make_packet(is_batch_parent=True, job_id="job-1")
        with self.assertRaises(nmp.NmpBatchError):
            nmp.NmpBatch(make_packet(state=nmp.EXECUTING), (make_packet(),))


class GateTests(unittest.TestCase):
    def test_valid_gate_queues_and_checks_are_side_effect_free(self):
        packet = make_packet(state=nmp.PREFLIGHTED)
        before = packet.to_dict()
        decision = gate(packet)
        self.assertTrue(decision.ok, decision.reason)
        self.assertEqual(decision.from_state, nmp.PREFLIGHTED)
        self.assertEqual(decision.packet_id, packet.packet_id)
        self.assertTrue(decision.checks["admission"])
        self.assertTrue(decision.checks["capability"])
        self.assertTrue(decision.checks["ring"])
        self.assertEqual(packet.to_dict(), before)

        queued = packet.queue(gate=decision)
        self.assertEqual(queued.state, nmp.QUEUED)
        self.assertEqual(queued.evidence["gate"]["ok"], True)

    def test_invalid_preflight_cannot_be_bypassed(self):
        packet = make_packet(state=nmp.PREFLIGHTED, preflight_result="INVALID")
        decision = gate(packet)
        self.assertFalse(decision.ok)
        self.assertEqual(decision.failure, nmp.REJECTED)
        with self.assertRaises(nmp.NmpGateError):
            packet.queue(gate=decision)

    def test_missing_preflight_digest_blocks_gate(self):
        packet = make_packet(state=nmp.PREFLIGHTED, preflight_digest=None)
        decision = gate(packet)
        self.assertFalse(decision.ok)
        self.assertEqual(decision.failure, nmp.REJECTED)

    def test_gate_requires_valid_admission_and_preserves_typed_verdicts(self):
        no_admission = make_packet(
            state=nmp.PREFLIGHTED, admission_id=None, admission_verdict=None,
        )
        self.assertEqual(gate(no_admission, admission=None).failure, nmp.REJECTED)

        undefined = make_packet(state=nmp.PREFLIGHTED, admission_verdict="UNDEFINED")
        self.assertEqual(gate(undefined).failure, nmp.UNDEFINED)

        unauthorized = make_packet(
            state=nmp.PREFLIGHTED, admission_verdict="UNAUTHORIZED",
        )
        self.assertEqual(gate(unauthorized).failure, nmp.UNAUTHORIZED)

    def test_stale_admission_snapshot_ruleset_and_preflight_are_rejected(self):
        packet = make_packet(state=nmp.PREFLIGHTED)
        stale_snapshot = gate(packet, admission={
            "verdict": "VALID",
            "candidate_id": CID,
            "snapshot_id": OTHER_SNAP,
            "preflight_digest": PREFLIGHT,
        })
        self.assertEqual(stale_snapshot.failure, nmp.STALE)

        stale_ruleset = gate(packet, admission={
            "verdict": "VALID",
            "candidate_id": CID,
            "snapshot_id": SNAP,
            "rule_snapshot_id": OTHER_RULES,
            "preflight_digest": PREFLIGHT,
        })
        self.assertEqual(stale_ruleset.failure, nmp.STALE)

        stale_preflight = gate(packet, preflight={
            "result": "VALID",
            "digest": OTHER_PREFLIGHT,
            "rule_snapshot_id": RULES,
        })
        self.assertEqual(stale_preflight.failure, nmp.STALE)

    def test_ruleset_snapshot_is_required_on_the_packet(self):
        packet = make_packet(state=nmp.PREFLIGHTED, ruleset_snapshot_id="")
        decision = gate(packet)
        self.assertEqual(decision.failure, nmp.STALE)

    def test_capability_unavailable_is_not_null(self):
        packet = make_packet(state=nmp.PREFLIGHTED)
        missing = gate(packet, capability=None)
        self.assertEqual(missing.failure, nmp.UNAVAILABLE)
        self.assertNotEqual(missing.failure, nmp.NULL)

        revoked = gate(packet, capability=make_capability(status="revoked"))
        self.assertEqual(revoked.failure, nmp.UNAVAILABLE)

        too_small = gate(packet, capability=make_capability(workspace=64))
        self.assertEqual(too_small.failure, nmp.UNAVAILABLE)

        no_workspace = gate(make_packet(state=nmp.PREFLIGHTED, guest_words=0))
        self.assertEqual(no_workspace.failure, nmp.UNAVAILABLE)

    def test_capability_semantic_name_matches_kernel_implementation(self):
        packet = make_packet(
            state=nmp.PREFLIGHTED,
            capability_set=({"required": "vector.dot", "workspace": 256},),
        )
        decision = gate(
            packet,
            capability=make_capability(kernel_id="mth.vector.dot256.f32"),
        )
        self.assertTrue(decision.ok, decision.reason)
        self.assertEqual(decision.checks["capability"], True)

    def test_capability_epoch_and_precision_are_checked(self):
        packet = make_packet(state=nmp.PREFLIGHTED, capability_epoch=2)
        decision = gate(packet, capability=make_capability(epoch=1))
        self.assertEqual(decision.failure, nmp.STALE)

        wrong_precision = gate(
            packet,
            capability=make_capability(precision="float64", epoch=2),
        )
        self.assertEqual(wrong_precision.failure, nmp.UNAVAILABLE)

    def test_ring_binding_is_required_and_must_match(self):
        unbound = make_packet(
            state=nmp.PREFLIGHTED, ring_incarnation=None, ring_epoch=None,
        )
        self.assertEqual(gate(unbound).failure, nmp.STALE)

        bad_hero = gate(make_packet(state=nmp.PREFLIGHTED), ring_incarnation="other")
        self.assertEqual(bad_hero.failure, nmp.STALE)

        bad_epoch = gate(make_packet(state=nmp.PREFLIGHTED), ring_epoch=2)
        self.assertEqual(bad_epoch.failure, nmp.STALE)

    def test_newer_cancel_epoch_supersedes_the_gate(self):
        packet = make_packet(state=nmp.PREFLIGHTED, cancel_epoch=1)
        decision = gate(packet, cancel_epoch=2)
        self.assertEqual(decision.failure, nmp.CANCELLED)

    def test_job_payload_cancel_epoch_supersedes_the_gate(self):
        packet = make_packet(state=nmp.PREFLIGHTED, cancel_epoch=1)
        decision = gate(
            packet,
            job={
                "job_id": "job-1",
                "state": "queued",
                "generation": 7,
                "payload_json": json.dumps({"cancel_epoch": 2}),
            },
        )
        self.assertEqual(decision.failure, nmp.CANCELLED)

    def test_gate_rejects_wrong_state(self):
        decision = gate(make_packet(state=nmp.PROPOSED))
        self.assertFalse(decision.ok)
        self.assertEqual(decision.failure, nmp.REJECTED)


class CancellationTests(unittest.TestCase):
    def test_cancel_before_execution_is_immediate_and_cooperative(self):
        packet = make_packet(state=nmp.PREFLIGHTED)
        result = packet.cancel(reason="operator request")
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.state, nmp.CANCELLED)
        self.assertEqual(result.cancel_epoch, 1)
        self.assertTrue(result.cooperative)
        self.assertTrue(result.plan_step_granularity)
        self.assertFalse(result.hard_preemption)
        self.assertIsNone(result.packet.result_digest)

    def test_cancel_queued_job_is_cancelled_without_claiming_running(self):
        packet = make_packet(state=nmp.QUEUED)
        result = packet.cancel(job={"state": "queued"})
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.action, "cancel_queued_job")
        self.assertEqual(result.state, nmp.CANCELLED)

    def test_cancel_executing_is_pending_until_plan_step_ack(self):
        packet = make_packet(state=nmp.EXECUTING)
        result = packet.cancel(job={"state": "leased"},
                               lease={"state": "active"})
        self.assertEqual(result.status, "requested")
        self.assertEqual(result.state, nmp.EXECUTING)
        self.assertEqual(result.cancel_epoch, 1)
        self.assertFalse(result.hard_preemption)
        self.assertTrue(result.packet.cancel_requested)
        self.assertTrue(result.packet.metadata["cancel_requested"])

        acknowledged = result.packet.acknowledge_cancel(plan_step=4)
        self.assertEqual(acknowledged.status, "cancelled")
        self.assertEqual(acknowledged.state, nmp.CANCELLED)
        self.assertIsNone(acknowledged.packet.result_digest)

    def test_cancel_done_is_too_late_and_preserves_result(self):
        completed = make_packet(state=nmp.COMPLETED)
        result = completed.cancel(job={"state": "done"})
        self.assertTrue(result.too_late)
        self.assertEqual(result.action, "result_stands")
        self.assertEqual(result.state, nmp.COMPLETED)
        self.assertEqual(result.packet.result_digest, RESULT)
        self.assertEqual(result.cancel_epoch, 0)

        committed = make_packet(state=nmp.COMMITTED)
        result = committed.cancel()
        self.assertTrue(result.too_late)
        self.assertEqual(result.state, nmp.COMMITTED)
        self.assertEqual(result.packet.result_digest, RESULT)

    def test_cancelled_is_not_failed_or_null(self):
        cancelled = make_packet(
            state=nmp.CANCELLED, failure_class=nmp.CANCELLED,
            result_digest=None, output_leaf_id=None,
        )
        failed = make_packet(
            state=nmp.FAILED, failure_class="EXECUTION_FAILED",
            result_digest=None, output_leaf_id=None,
        )
        null = make_packet(
            state=nmp.NULL, failure_class=nmp.NULL,
            result_digest=None, output_leaf_id=None,
        )
        self.assertNotEqual(cancelled.state, failed.state)
        self.assertNotEqual(cancelled.state, null.state)
        self.assertIsNone(cancelled.result_digest)
        self.assertTrue(cancelled.is_failure_terminal)


class ProjectionTests(unittest.TestCase):
    def _job(self, state: str, **overrides):
        job = {
            "job_id": "job-1",
            "state": state,
            "generation": 7,
            "lease_epoch": 1,
            "result_digest": RESULT if state == "done" else None,
            "result_generation": 7 if state == "done" else None,
            "payload_json": json.dumps({}),
        }
        job.update(overrides)
        return job

    def test_control_states_without_a_job_are_supported_but_execution_is_not(self):
        proposed = make_packet(state=nmp.PROPOSED)
        projection = nmp.project_packet(proposed)
        self.assertEqual(projection.state, nmp.PROPOSED)
        self.assertTrue(projection.supported)

        executing = make_packet(state=nmp.EXECUTING)
        projection = nmp.project_packet(executing)
        self.assertIsNone(projection.state)
        self.assertFalse(projection.supported)
        with self.assertRaises(nmp.NmpProjectionError):
            projection.to_packet(executing)

    def test_restart_projection_from_leased_and_done_job_rows(self):
        packet = make_packet(state=nmp.QUEUED)
        leased = nmp.project_packet(
            packet,
            job=self._job("leased"),
            lease={"state": "active", "lease_token": None, "lease_epoch": 1,
                   "deadline_tick": 100},
            now_tick=1,
        )
        self.assertTrue(leased.supported)
        self.assertEqual(leased.state, nmp.EXECUTING)
        self.assertEqual(leased.job_id, "job-1")

        rebuilt = nmp.reconstruct_packet(
            packet,
            job=self._job("done"),
            lease={"state": "completed", "lease_epoch": 1},
        )
        self.assertEqual(rebuilt.state, nmp.COMPLETED)
        self.assertEqual(rebuilt.result_digest, RESULT)
        self.assertEqual(rebuilt.job_id, "job-1")
        self.assertEqual(rebuilt.history[-1]["reason"],
                         "projection from job/lease rows")

    def test_projection_does_not_accept_a_claim_ahead_of_job_evidence(self):
        packet = make_packet(state=nmp.EXECUTING)
        projection = nmp.project_packet(packet, job=self._job("queued"))
        self.assertEqual(projection.state, nmp.QUEUED)
        self.assertFalse(projection.supported)
        with self.assertRaises(nmp.NmpProjectionError):
            projection.to_packet(packet)

    def test_projection_rejects_stale_generations_and_snapshots(self):
        packet = make_packet(state=nmp.EXECUTING)
        newer = nmp.project_packet(packet, job=self._job("leased", generation=8))
        self.assertEqual(newer.state, nmp.STALE)
        self.assertFalse(newer.supported)

        result_newer = nmp.project_packet(
            packet,
            job=self._job("done", result_generation=8),
        )
        self.assertEqual(result_newer.state, nmp.STALE)

        other_snapshot = nmp.project_packet(
            packet,
            job=self._job(
                "leased",
                payload_json=json.dumps({"snapshot_id": OTHER_SNAP}),
            ),
        )
        self.assertEqual(other_snapshot.state, nmp.STALE)

        direct_snapshot = nmp.project_packet(
            packet,
            job=self._job("leased", snapshot_id=OTHER_SNAP),
        )
        self.assertEqual(direct_snapshot.state, nmp.STALE)

    def test_projection_maps_failed_and_cancelled_jobs_distinctly(self):
        packet = make_packet(state=nmp.EXECUTING)
        failed = nmp.project_packet(
            packet,
            job=self._job("failed", error="kernel trap"),
        )
        self.assertEqual(failed.state, nmp.FAILED)

        cancelled = nmp.project_packet(
            packet,
            job=self._job("failed", error="cancelled by plan-step boundary"),
        )
        self.assertEqual(cancelled.state, nmp.CANCELLED)
        self.assertNotEqual(failed.state, cancelled.state)

    def test_expired_lease_projects_stale(self):
        packet = make_packet(state=nmp.EXECUTING)
        projection = nmp.project_packet(
            packet,
            job=self._job("leased", deadline_tick=5),
            lease={"state": "active", "lease_epoch": 1, "deadline_tick": 5},
            now_tick=5,
        )
        self.assertEqual(projection.state, nmp.STALE)
        self.assertTrue(projection.supported)

    def test_projection_from_store_uses_public_get_job_only(self):
        class FakeStore:
            def __init__(self):
                self.calls = []

            def get_job(self, job_id):
                self.calls.append(job_id)
                return {
                    "job_id": job_id,
                    "state": "done",
                    "generation": 7,
                    "result_digest": RESULT,
                    "result_generation": 7,
                    "lease_epoch": 1,
                }

        store = FakeStore()
        packet = make_packet(state=nmp.EXECUTING)
        projection = nmp.project_packet(packet, store=store)
        self.assertEqual(projection.state, nmp.COMPLETED)
        self.assertEqual(store.calls, ["job-1"])

    def test_projection_treats_cancel_epoch_as_cooperative_request(self):
        packet = make_packet(state=nmp.EXECUTING)
        job = self._job(
            "leased",
            payload_json=json.dumps({"cancel_epoch": packet.cancel_epoch + 1}),
        )
        projection = nmp.project_packet(
            packet,
            job=job,
            lease={"state": "active", "lease_epoch": 1, "deadline_tick": 100},
            now_tick=1,
        )
        self.assertEqual(projection.state, nmp.EXECUTING)
        self.assertTrue(projection.supported)
        self.assertTrue(projection.evidence["cancel_requested"])

    def test_done_cancellation_epoch_does_not_erase_completed_result(self):
        packet = make_packet(state=nmp.COMPLETED)
        projection = nmp.project_packet(
            packet,
            job=self._job(
                "done",
                payload_json=json.dumps({"cancel_epoch": packet.cancel_epoch + 1}),
            ),
        )
        self.assertEqual(projection.state, nmp.COMPLETED)
        self.assertEqual(projection.result_digest, RESULT)
        self.assertTrue(projection.supported)

    def test_accepts_result_enforces_snapshot_and_generation_binding(self):
        packet = make_packet(state=nmp.COMPLETED)
        self.assertTrue(packet.accepts_result(
            snapshot_id=SNAP,
            ruleset_snapshot_id=RULES,
            result_digest=RESULT,
            result_generation=7,
            generation=7,
        ))
        self.assertFalse(packet.accepts_result(snapshot_id=OTHER_SNAP))
        self.assertFalse(packet.accepts_result(
            ruleset_snapshot_id=OTHER_RULES,
        ))
        self.assertFalse(packet.accepts_result(result_generation=8))
        self.assertFalse(packet.accepts_result(generation=8))
        self.assertFalse(packet.accepts_result(result_digest="f" * 64))

    def test_committed_projection_requires_job_and_commit_evidence(self):
        committed = make_packet(state=nmp.COMMITTED)
        projection = nmp.project_packet(committed, job=self._job("done"))
        self.assertEqual(projection.state, nmp.COMMITTED)
        self.assertTrue(projection.supported)

        no_job = nmp.project_packet(committed)
        self.assertIsNone(no_job.state)
        self.assertFalse(no_job.supported)

    def test_module_owns_no_private_durable_state(self):
        source = inspect.getsource(nmp)
        self.assertNotIn("sqlite3", source)
        self.assertNotIn("CREATE TABLE", source)
        self.assertNotIn("wave_store", source)
        self.assertNotIn("mth_system", source)
        self.assertFalse(nmp.NmpInFlightTable.durable)
        self.assertFalse(nmp.NmpInFlightTable.owns_jobs)
        self.assertFalse(hasattr(nmp.NmpPacket, "save"))
        self.assertFalse(hasattr(nmp.NmpPacket, "persist"))

    def test_module_imports_no_executor_or_host_math(self):
        import ast

        tree = ast.parse(inspect.getsource(nmp))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        self.assertNotIn("math", imported)
        for name in imported:
            self.assertNotIn("executor", name)
            self.assertNotIn("mth_system", name)
            self.assertNotIn("wave_store", name)


class MathObjectIntegrationTests(unittest.TestCase):
    def test_prepare_from_math_objects_reaches_preflighted(self):
        candidate = make_candidate()
        admission = make_admission()
        packet = nmp.prepare(
            candidate,
            {
                "result": "VALID",
                "digest": PREFLIGHT,
                "rule_snapshot_id": RULES,
            },
            snapshot_id=SNAP,
            admission=admission,
            capability_set=({"required": "vector.dot", "workspace": 256},),
            resources={"guest_words": 256},
            ring_incarnation="ring-inc-1",
            ring_epoch=1,
            base_generation=7,
        )
        self.assertEqual(packet.state, nmp.PREFLIGHTED)
        self.assertEqual(packet.candidate_id, CID)
        self.assertEqual(packet.admission_id, admission.admission_id)
        self.assertEqual(packet.function_id, FUNCTION)
        self.assertEqual(packet.snapshot_id, SNAP)
        self.assertEqual(packet.admission_verdict, "VALID")
        self.assertEqual(packet.preflight_digest, PREFLIGHT)
        self.assertEqual(packet.capability_set_digest,
                         nmp.digest_object(list(packet.capability_set)))
        canonical_json(packet.to_dict())

        self.assertTrue(gate(packet).ok)
        queued = packet.queue(gate=gate(packet))
        self.assertEqual(queued.state, nmp.QUEUED)

    def test_prepare_maps_non_valid_preflight_to_typed_failures(self):
        candidate = make_candidate()
        expected = {
            "UNDEFINED": nmp.UNDEFINED,
            "NULL": nmp.NULL,
            "INVALID": nmp.REJECTED,
            "UNSUPPORTED": nmp.REJECTED,
            "UNAVAILABLE": nmp.UNAVAILABLE,
            "UNAUTHORIZED": nmp.UNAUTHORIZED,
            "STALE": nmp.STALE,
        }
        for verdict, state in expected.items():
            packet = nmp.prepare(
                candidate,
                {
                    "result": verdict,
                    "digest": PREFLIGHT,
                    "rule_snapshot_id": RULES,
                },
                snapshot_id=SNAP,
                admission=make_admission(verdict=verdict),
                resources={"guest_words": 256},
            )
            self.assertEqual(packet.state, state, verdict)
            self.assertNotEqual(packet.state, nmp.COMMITTED)

    def test_canonical_packet_fields_are_present(self):
        packet = make_packet(state=nmp.COMMITTED)
        record = packet.to_dict()
        for key in (
            "packet_id", "state", "status", "snapshot_id", "base_generation",
            "generation", "lane_id", "parent_packet_id", "batch_id",
            "batch_index", "batch_count", "function_id", "function_version",
            "candidate_id", "admission_id", "admission_verdict", "preflight",
            "ruleset", "capability", "resources", "cancel_epoch", "output",
            "evidence", "plan_digest",
        ):
            self.assertIn(key, record)
        self.assertEqual(record["lane_id"], 3)
        self.assertEqual(record["resources"]["guest_words"], 256)
        self.assertEqual(record["preflight"]["digest"], PREFLIGHT)
        self.assertEqual(record["ruleset"]["snapshot_id"], RULES)
        self.assertEqual(record["capability"]["set"][0]["required"], "vector.dot")
        self.assertEqual(record["evidence"]["ring_incarnation"], "ring-inc-1")
        self.assertEqual(record["evidence"]["ring_epoch"], 1)
        self.assertEqual(record["evidence"]["jahs"], nmp.JAHS_SEAL)
        self.assertEqual(record["output"]["digest"], RESULT)
        self.assertEqual(record["status"], nmp.COMMITTED)
        self.assertEqual(record["cancel_epoch"], 0)

    def test_prepare_uses_admission_verdict_for_typed_failure(self):
        candidate = make_candidate()
        packet = nmp.prepare(
            candidate,
            {
                "result": "VALID",
                "digest": PREFLIGHT,
                "rule_snapshot_id": RULES,
            },
            snapshot_id=SNAP,
            admission=make_admission(verdict="UNAUTHORIZED"),
            resources={"guest_words": 256},
        )
        self.assertEqual(packet.state, nmp.UNAUTHORIZED)
        self.assertEqual(packet.preflight_result, "VALID")
        self.assertEqual(packet.admission_verdict, "UNAUTHORIZED")

    def test_packet_identity_is_stable_across_state_changes(self):
        packet = make_packet()
        packet_id = packet.packet_id
        dedupe_key = packet.dedupe_key
        for state_call in (
            lambda p: p.resolve(),
            lambda p: p.classify(),
            lambda p: p.propose(),
            lambda p: p.mark_preflight(),
        ):
            packet = state_call(packet)
            self.assertEqual(packet.packet_id, packet_id)
            self.assertEqual(packet.dedupe_key, dedupe_key)

    def test_canonical_record_round_trips_for_restart_evidence(self):
        packet = make_packet(state=nmp.PREFLIGHTED)
        rebuilt = nmp.NmpPacket.from_dict(packet.to_dict())
        self.assertEqual(rebuilt, packet)
        self.assertEqual(rebuilt.to_dict(), packet.to_dict())
        self.assertEqual(rebuilt.dedupe_key, packet.dedupe_key)

    def test_gate_and_projector_aliases(self):
        packet = make_packet(state=nmp.PREFLIGHTED)
        decision = nmp.gate(
            packet,
            admission=make_admission(),
            preflight={"result": "VALID", "digest": PREFLIGHT,
                       "rule_snapshot_id": RULES},
            capability=make_capability(),
            ring_incarnation="ring-inc-1",
            ring_epoch=1,
        )
        self.assertTrue(decision.ok)
        self.assertTrue(nmp.can_execute(
            packet,
            admission=make_admission(),
            preflight={"result": "VALID", "digest": PREFLIGHT,
                       "rule_snapshot_id": RULES},
            capability=make_capability(),
            ring_incarnation="ring-inc-1",
            ring_epoch=1,
        ))
        projector = nmp.NmpProjector()
        self.assertFalse(projector.durable)
        projection = projector.project(packet)
        self.assertEqual(projection.state, nmp.PREFLIGHTED, projection.reason)
        with self.assertRaises(nmp.NmpGateError):
            packet.assert_executable()


class NativePreflightReceiptTests(unittest.TestCase):
    def make_proposed_packet(self):
        return make_packet(
            preflight_digest=None,
            preflight_result=None,
            admission_id=None,
            admission_verdict=None,
        ).resolve().classify().propose()

    def make_receipt(self, packet):
        return NativePreflightReceipt.from_guest_result(
            packet,
            {
                "status": 0,
                "rule_epoch": 7,
                "rule_digest_words": [
                    0x01020304, 0x11121314, 0x21222324, 0x31323334,
                    0x41424344, 0x51525354, 0x61626364, 0x71727374,
                ],
                "output_descriptor": [3, 0, 1, 1, 1, 9000, 3, 0],
            },
            guest_source_digest="a" * 64,
            guest_image_digest="b" * 64,
        )

    def test_prepare_can_defer_to_guest_then_attach_native_receipt(self):
        candidate = make_candidate()
        packet = nmp.prepare(
            candidate,
            snapshot_id=SNAP,
            base_generation=7,
            capability_set=(
                {"required": "vector.dot", "workspace": 256, "precision": "float32"},
            ),
            capability_epoch=1,
            ruleset_snapshot_id=RULES,
            ring_incarnation="ring-inc-1",
            ring_epoch=1,
            defer_preflight=True,
        )
        self.assertEqual(packet.state, nmp.PROPOSED)
        receipt = self.make_receipt(packet)
        preflighted = packet.mark_preflight(
            receipt=receipt,
            admission=make_admission(preflight_digest=receipt.receipt_digest),
        )
        self.assertEqual(preflighted.state, nmp.PREFLIGHTED)
        self.assertEqual(preflighted.admission_verdict, "VALID")

    def test_native_receipt_binds_packet_and_survives_canonical_round_trip(self):
        packet = self.make_proposed_packet()
        receipt = self.make_receipt(packet)
        preflighted = packet.mark_preflight(receipt=receipt, admission=make_admission(preflight_digest=receipt.receipt_digest))
        self.assertEqual(preflighted.state, nmp.PREFLIGHTED)
        self.assertTrue(preflighted.metadata["native_preflight_required"])
        self.assertEqual(preflighted.preflight_digest, receipt.receipt_digest)
        rebuilt = nmp.NmpPacket.from_dict(preflighted.to_dict())
        self.assertEqual(rebuilt, preflighted)
        self.assertEqual(
            NativePreflightReceipt.from_dict(
                rebuilt.evidence["native_preflight_receipt"]
            ),
            receipt,
        )

    def test_receipt_rejects_changed_inputs_generation_and_guest_denial(self):
        packet = self.make_proposed_packet()
        receipt = self.make_receipt(packet)
        changed_inputs = nmp.replace(
            packet, inputs=({"leaf_id": "nml:U0:vector:changed",
                             "version": 1, "digest": "f" * 64},)
        )
        with self.assertRaises(NativePreflightReceiptError):
            receipt.verify_packet(changed_inputs)
        changed_generation = nmp.replace(packet, generation=8)
        with self.assertRaises(NativePreflightReceiptError):
            receipt.verify_packet(changed_generation)
        denied = {
            "status": 8,
            "rule_epoch": 7,
            "rule_digest_words": [1] * 8,
            "output_descriptor": [0] * 8,
        }
        with self.assertRaises(NativePreflightReceiptError):
            NativePreflightReceipt.from_guest_result(
                packet, denied,
                guest_source_digest="a" * 64,
                guest_image_digest="b" * 64,
            )

    def test_native_receipt_is_checked_by_nmp_queue_gate(self):
        packet = self.make_proposed_packet()
        receipt = self.make_receipt(packet)
        preflighted = packet.mark_preflight(receipt=receipt, admission=make_admission(preflight_digest=receipt.receipt_digest))
        admission = make_admission(preflight_digest=receipt.receipt_digest)
        preflight = {
            "result": "VALID",
            "digest": receipt.receipt_digest,
            "rule_snapshot_id": RULES,
        }
        live_ruleset = {
            "snapshot_id": RULES,
            "rule_epoch": receipt.rule_epoch,
            "rule_digest": receipt.rule_digest,
        }
        decision = nmp.execution_gate(
            preflighted,
            admission=admission,
            preflight=preflight,
            capability=make_capability(),
            ruleset_snapshot=live_ruleset,
            ring_incarnation="ring-inc-1",
            ring_epoch=1,
        )
        self.assertTrue(decision.ok, decision.reason)
        stale_epoch = nmp.execution_gate(
            preflighted,
            admission=admission,
            preflight=preflight,
            capability=make_capability(),
            ruleset_snapshot={"snapshot_id": RULES, "rule_epoch": 8},
            ring_incarnation="ring-inc-1",
            ring_epoch=1,
        )
        self.assertFalse(stale_epoch.ok)
        self.assertIn("rule epoch", stale_epoch.reason)
        stale_digest = nmp.execution_gate(
            preflighted,
            admission=admission,
            preflight=preflight,
            capability=make_capability(),
            ruleset_snapshot={"snapshot_id": RULES, "rule_epoch": 7, "rule_digest": "f" * 64},
            ring_incarnation="ring-inc-1",
            ring_epoch=1,
        )
        self.assertFalse(stale_digest.ok)
        self.assertIn("rule digest", stale_digest.reason)
        queued = preflighted.queue(gate=decision)
        tampered_evidence = dict(queued.evidence)
        tampered_evidence.pop("native_preflight_receipt")
        tampered = nmp.replace(queued, evidence=tampered_evidence)
        denied = nmp.execution_gate(
            tampered,
            admission=admission,
            preflight=preflight,
            capability=make_capability(),
            ruleset_snapshot=live_ruleset,
            ring_incarnation="ring-inc-1",
            ring_epoch=1,
        )
        self.assertFalse(denied.ok)
        self.assertIn("native preflight receipt", denied.reason)

    def test_native_receipt_must_be_bound_to_active_lease_before_execution(self):
        packet = self.make_proposed_packet()
        receipt = self.make_receipt(packet)
        preflighted = packet.mark_preflight(receipt=receipt, admission=make_admission(preflight_digest=receipt.receipt_digest))
        admission = make_admission(preflight_digest=receipt.receipt_digest)
        preflight = {
            "result": "VALID",
            "digest": receipt.receipt_digest,
            "rule_snapshot_id": RULES,
        }
        live_ruleset = {
            "snapshot_id": RULES,
            "rule_epoch": receipt.rule_epoch,
            "rule_digest": receipt.rule_digest,
        }
        queued = preflighted.queue(
            admission=admission,
            preflight=preflight,
            capability=make_capability(),
            ruleset_snapshot=live_ruleset,
            ring_incarnation="ring-inc-1",
            ring_epoch=1,
        )
        scheduler = WaveRingScheduler(cycle_ticks=10, now_tick=0)
        scheduler.start(0)
        ring = scheduler.snapshot()
        lease = {
            "job_id": "job-1",
            "state": "active",
            "lease_epoch": 1,
            "lease_owner": ring["active_slot_id"],
            "lease_token": "c" * 64,
        }
        job = {"job_id": "job-1", "state": "leased", "generation": 7}
        with self.assertRaises(nmp.NmpGateError):
            queued.start_execution(
                admission=admission,
                preflight=preflight,
                capability=make_capability(),
                ruleset_snapshot=live_ruleset,
                ring_incarnation="ring-inc-1",
                ring_epoch=1,
            )
        bound = queued.bind_native_lease(
            job, lease, ring, ring_incarnation="ring-inc-1"
        )
        binding = NativePreflightLeaseBinding.from_dict(
            bound.evidence["native_preflight_lease_binding"]
        )
        self.assertEqual(binding.receipt_digest, receipt.receipt_digest)
        gate = nmp.execution_gate(
            bound,
            admission=admission,
            preflight=preflight,
            capability=make_capability(),
            ruleset_snapshot=live_ruleset,
            ring_incarnation="ring-inc-1",
            ring_epoch=1,
            job=job,
            lease=lease,
        )
        self.assertTrue(gate.ok, gate.reason)
        executing = bound.start_execution(
            gate=gate,
            job_id="job-1",
            lease_epoch=1,
            ring_incarnation="ring-inc-1",
            ring_epoch=1,
        )
        self.assertEqual(executing.state, nmp.EXECUTING)
        self.assertEqual(executing.job_id, "job-1")
        self.assertEqual(executing.lease_epoch, 1)
        self.assertEqual(executing.ring_epoch, 1)
        with self.assertRaises(nmp.NmpGateError):
            bound.start_execution(
                gate=gate,
                lease_epoch=2,
                job_id="job-1",
                ring_incarnation="ring-inc-1",
                ring_epoch=1,
            )
        cancelled = nmp.replace(bound, cancel_epoch=1)
        with self.assertRaises(nmp.NmpGateError):
            cancelled.start_execution(
                gate=gate,
                job_id="job-1",
                lease_epoch=1,
                ring_incarnation="ring-inc-1",
                ring_epoch=1,
            )

    def test_native_lease_binding_rejects_wrong_ring_epoch_and_owner(self):
        packet = self.make_proposed_packet()
        receipt = self.make_receipt(packet)
        preflighted = packet.mark_preflight(receipt=receipt, admission=make_admission(preflight_digest=receipt.receipt_digest))
        queued = preflighted.transition(nmp.QUEUED)
        scheduler = WaveRingScheduler(cycle_ticks=10, now_tick=0)
        scheduler.start(0)
        ring = scheduler.snapshot()
        lease = {
            "job_id": "job-1",
            "state": "active",
            "lease_epoch": 1,
            "lease_owner": "MC0:0/R1",
            "lease_token": "c" * 64,
        }
        job = {"job_id": "job-1", "state": "leased", "generation": 7}
        with self.assertRaises(NativePreflightReceiptError):
            NativePreflightLeaseBinding.from_live_lease(
                queued, receipt, job, lease, ring, ring_incarnation="ring-inc-1"
            )


if __name__ == "__main__":
    unittest.main()
