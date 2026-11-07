"""Adversarial tests for the P9 safe rule-discovery lifecycle.

Coverage:

* proposal -> hash -> validate -> test -> approve -> commit -> activate;
* level-0 immutability and level-3 isolation;
* self-validation/self-approval/self-promotion denial;
* contradiction blocking without last-writer-wins;
* stale generation CAS, duplicate proposal, negative memory;
* rollback through the MathStore mapping pointer;
* experiment outcomes as utility-only evidence;
* append-only audit/evidence and proof-status discipline.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing

from runner_riddle.math_learning import (
    AuditError,
    ContradictionError,
    DuplicateProposalConflict,
    ExperimentPromotionDenied,
    InconclusiveEvidence,
    Level0ImmutableError,
    Level3IsolationError,
    LifecycleStateError,
    MathLearningService,
    NegativeMemoryError,
    ProposalRejected,
    RuleProposal,
    SelfApprovalDenied,
    StaleGenerationError,
    TestFailure,
)
from runner_riddle.math_objects import MathRule, canonical_json, sha256_text
from runner_riddle.math_store import MathReferenceError, MathStore


PROPOSER = "learning:boolean-head-7"
VALIDATOR = "validity:engine-1"
TESTER = "experiment:r7-1"
APPROVER = "owner:policy-1"
COMMITTER = "lifecycle:commit-1"
ACTIVATOR = "lifecycle:activate-1"


class MathLearningLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bs0_path = self.tmp.name + "/bs0db.sqlite3"
        self.mc0_path = self.tmp.name + "/mc0db.sqlite3"
        self.store = MathStore(self.bs0_path, self.mc0_path)
        self.service = MathLearningService(
            self.store, trusted_checkers={"checker:trusted"},
        )
        self.rule_id = "math.rule.vector.assoc"

    # -- helpers ------------------------------------------------------------

    def proposal(self, rule_id=None, *, level=1, claims=None, scope=None,
                 **kwargs):
        return RuleProposal(
            rule_id=self.rule_id if rule_id is None else rule_id,
            level=level,
            contract={"claims": {"associative": True}}
            if claims is None else {"claims": dict(claims)},
            scope={"function_ids": ["math.vector.add"]}
            if scope is None else dict(scope),
            claim_class=kwargs.pop("claim_class", "rewrite"),
            **kwargs,
        )

    def to_tested(self, rule_id=None, *, proposer=PROPOSER,
                  validator=VALIDATOR, tester=TESTER, cases=None,
                  level=1, claims=None, scope=None):
        rule_id = self.rule_id if rule_id is None else rule_id
        self.service.propose(
            self.proposal(rule_id, level=level, claims=claims, scope=scope),
            proposer=proposer,
        )
        self.service.hash_proposal(rule_id, actor=proposer)
        self.service.validate(rule_id, validator=validator)
        return self.service.test(
            rule_id,
            tester=tester,
            harness="harness:bounded-1",
            cases=[{"outcome": "pass"}, {"outcome": "pass"}]
            if cases is None else cases,
        )

    def to_committed(self, rule_id=None, *, level=1, claims=None, scope=None,
                     proposer=PROPOSER, validator=VALIDATOR, tester=TESTER,
                     approver=APPROVER, committer=COMMITTER):
        rule_id = self.rule_id if rule_id is None else rule_id
        self.service.propose(
            self.proposal(rule_id, level=level, claims=claims, scope=scope),
            proposer=proposer,
        )
        self.service.hash_proposal(rule_id, actor=proposer)
        self.service.validate(rule_id, validator=validator)
        self.service.test(
            rule_id, tester=tester, harness="harness:bounded-1",
            cases=[{"outcome": "pass"}, {"outcome": "pass"}],
        )
        self.service.approve(rule_id, approver=approver)
        return self.service.commit(rule_id, actor=committer)

    def to_active(self, rule_id=None, **kwargs):
        rule_id = self.rule_id if rule_id is None else rule_id
        isolated = kwargs.pop("isolated", False)
        activator = kwargs.pop("activator", ACTIVATOR)
        self.to_committed(rule_id, **kwargs)
        return self.service.activate(
            rule_id, actor=activator, isolated=isolated,
        )

    def rule_digest(self, rule_id, version):
        rule = self.store.get_rule(rule_id, version)
        return sha256_text(canonical_json(rule.to_dict()))

    # -- lifecycle ----------------------------------------------------------

    def test_full_lifecycle_and_orthogonal_axes(self):
        proposal = self.proposal(claimed_validity="V3")
        first = self.service.propose(proposal, proposer=PROPOSER)
        self.assertEqual(first.state, "proposed")
        self.assertEqual(first.version, 1)
        self.assertEqual(first.rule.status, "proposed")
        self.assertEqual(first.axes.validity["claimed"], "V3")
        self.assertEqual(first.axes.validity["earned"], "V0")
        self.assertEqual(first.axes.proof["status"], "none")
        self.assertEqual(first.axes.truth["status"], "unknown")

        hashed = self.service.hash_proposal(self.rule_id, actor=PROPOSER)
        self.assertEqual(hashed.state, "hashed")
        self.assertEqual(hashed.version, 2)

        validated = self.service.validate(self.rule_id, validator=VALIDATOR)
        self.assertEqual(validated.state, "validated")
        self.assertEqual(validated.version, 3)
        self.assertEqual(validated.axes.validity["earned"], "V1")
        # The client's V3 claim was never used as authority.
        self.assertEqual(validated.axes.validity["claimed"], "V3")
        self.assertEqual(validated.axes.proof["status"], "none")
        self.assertEqual(validated.axes.truth["status"], "unknown")

        tested = self.service.test(
            self.rule_id, tester=TESTER, harness="harness:bounded-1",
            cases=[{"outcome": "pass"}, {"outcome": "pass"}],
        )
        self.assertEqual(tested.state, "tested")
        self.assertEqual(tested.version, 4)
        self.assertEqual(tested.axes.validity["earned"], "V2")
        # A bounded test is not a proof and does not set truth.
        self.assertEqual(tested.axes.proof["status"], "none")
        self.assertEqual(tested.axes.truth["status"], "unknown")
        self.assertEqual(tested.rule.proof_status, "none")

        approved = self.service.approve(self.rule_id, approver=APPROVER)
        self.assertEqual(approved.state, "approved")
        self.assertEqual(approved.version, 5)

        committed = self.service.commit(self.rule_id, actor=COMMITTER)
        self.assertEqual(committed.state, "committed")
        self.assertEqual(committed.version, 6)
        self.assertEqual(committed.rule.status, "proposed")

        active = self.service.activate(self.rule_id, actor=ACTIVATOR)
        self.assertEqual(active.state, "active")
        self.assertEqual(active.version, 7)
        self.assertEqual(active.rule.status, "active")
        self.assertEqual(active.active_version, 7)
        self.assertIsNotNone(active.mapping)
        self.assertEqual(active.mapping["current_version"], 7)
        self.assertEqual(active.mapping["status"], "active")
        self.assertEqual(
            self.store.get_rule_meta(self.rule_id)["generation"], 7,
        )

        active_rules = self.service.active_rules()
        self.assertEqual(
            [(rule.rule_id, rule.version) for rule in active_rules],
            [(self.rule_id, 7)],
        )
        self.assertTrue(self.service.rule_snapshot_id().startswith("rsn:"))

        axes = self.service.axes(self.rule_id)
        self.assertEqual(set(axes.to_dict()), {
            "truth", "validity", "proof", "lifecycle", "utility",
        })

    def test_no_new_database_tables_are_created(self):
        with closing(sqlite3.connect(self.mc0_path)) as db:
            before = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.to_active()
        with closing(sqlite3.connect(self.mc0_path)) as db:
            after = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertEqual(before, after)

    # -- level 0 ------------------------------------------------------------

    def test_level0_rules_are_immutable_to_learning(self):
        level0 = MathRule(
            rule_id="math.rule.core.types",
            level=0,
            contract={"claims": {"types": "closed"}},
            status="active",
            proof_status="axiom",
        )
        self.store.put_rule(level0)
        before_meta = self.store.get_rule_meta("math.rule.core.types")

        with self.assertRaises(Level0ImmutableError):
            self.service.propose(
                self.proposal("math.rule.core.types", level=1),
                proposer=PROPOSER,
            )
        with self.assertRaises(Level0ImmutableError):
            self.service.propose(
                self.proposal("math.rule.new.level0", level=0),
                proposer=PROPOSER,
            )
        with self.assertRaises(Level0ImmutableError):
            self.service.promote(
                "math.rule.core.types", 1, actor=ACTIVATOR,
            )

        after_meta = self.store.get_rule_meta("math.rule.core.types")
        self.assertEqual(
            before_meta["current_version"], after_meta["current_version"],
        )
        self.assertEqual(before_meta["generation"], after_meta["generation"])
        self.assertEqual(
            self.store.get_rule("math.rule.core.types").level, 0,
        )

    def test_registered_level0_baseline_is_also_immutable(self):
        baseline = MathRule(
            rule_id="math.rule.core.pinned",
            level=0,
            contract={},
            status="active",
            proof_status="axiom",
        )
        service = MathLearningService(
            self.store, level0_rules=(baseline,),
        )
        with self.assertRaises(Level0ImmutableError):
            service.propose(
                self.proposal("math.rule.core.pinned", level=2),
                proposer=PROPOSER,
            )

    # -- level 3 ------------------------------------------------------------

    def test_level3_is_isolation_only(self):
        committed = self.to_committed(
            "math.rule.experimental.add", level=3,
            claims={"experimental": True},
            scope={"function_ids": ["math.vector.add"]},
        )
        self.assertEqual(committed.state, "committed")

        with self.assertRaises(Level3IsolationError):
            self.service.activate(
                "math.rule.experimental.add", actor=ACTIVATOR,
            )
        self.assertEqual(
            self.service.lifecycle("math.rule.experimental.add")["state"],
            "committed",
        )

        active = self.service.activate(
            "math.rule.experimental.add", actor=ACTIVATOR, isolated=True,
        )
        self.assertEqual(active.state, "active")
        self.assertTrue(active.axes.lifecycle["isolated"])

        production = {
            rule.rule_id for rule in self.service.active_rules()
        }
        isolated = {
            rule.rule_id
            for rule in self.service.active_rules(include_isolated=True)
        }
        self.assertNotIn("math.rule.experimental.add", production)
        self.assertIn("math.rule.experimental.add", isolated)
        self.assertNotEqual(
            self.service.rule_snapshot_id(),
            self.service.rule_snapshot_id(include_isolated=True),
        )

    def test_non_level3_cannot_claim_isolation(self):
        self.to_committed("math.rule.production", level=1)
        with self.assertRaises(Level3IsolationError):
            self.service.activate(
                "math.rule.production", actor=ACTIVATOR, isolated=True,
            )

    def test_promotion_is_separate_and_proof_gated(self):
        rule_id = "math.rule.promote"
        proposal = RuleProposal(
            rule_id=rule_id,
            level=3,
            contract={"claims": {"promotion": True}},
            scope={"function_ids": ["math.vector.add"]},
            claim_class="theorem",
            proof_digest="f" * 64,
            checker="checker:trusted",
        )
        self.service.propose(proposal, proposer=PROPOSER)
        self.service.hash_proposal(rule_id, actor=PROPOSER)
        self.service.validate(rule_id, validator=VALIDATOR)
        self.service.test(
            rule_id, tester=TESTER, harness="harness:bounded-1",
            cases=[{"outcome": "pass"}],
        )
        self.service.approve(rule_id, approver=APPROVER)
        self.service.commit(rule_id, actor=COMMITTER)
        active = self.service.activate(
            rule_id, actor=ACTIVATOR, isolated=True,
        )
        self.assertEqual(active.rule.level, 3)
        self.assertNotIn(
            rule_id, {rule.rule_id for rule in self.service.active_rules()},
        )
        before = self.service.axes(rule_id)

        with self.assertRaises(SelfApprovalDenied):
            self.service.promote(rule_id, 2, actor=PROPOSER)

        promoted = self.service.promote(rule_id, 2, actor=ACTIVATOR)
        self.assertEqual(promoted.rule.level, 2)
        self.assertEqual(promoted.state, "active")
        self.assertFalse(promoted.axes.lifecycle["isolated"])
        after = self.service.axes(rule_id)
        self.assertEqual(before.truth, after.truth)
        self.assertEqual(before.validity, after.validity)
        self.assertEqual(before.proof, after.proof)
        self.assertIn(
            rule_id, {rule.rule_id for rule in self.service.active_rules()},
        )

    def test_deprecate_revoke_archive_transitions(self):
        deprecated_id = "math.rule.deprecated"
        self.to_active(deprecated_id)
        deprecated = self.service.deprecate(
            deprecated_id, actor=ACTIVATOR, reason="superseded",
        )
        self.assertEqual(deprecated.state, "deprecated")
        self.assertEqual(deprecated.rule.status, "deprecated")
        self.assertEqual(
            [rule.rule_id for rule in self.service.active_rules()], [],
        )
        archived = self.service.archive(
            deprecated_id, actor=ACTIVATOR, reason="retention",
        )
        self.assertEqual(archived.state, "archived")
        self.assertEqual(archived.rule.status, "revoked")
        self.assertEqual(
            self.store.get_mapping(
                "rule:" + deprecated_id)["current_version"],
            archived.version,
        )

        revoked_id = "math.rule.revoked"
        self.to_active(revoked_id)
        content = self.store.get_rule(
            revoked_id, 1,
        ).contract["proposal"]["content_digest"]
        revoked = self.service.revoke(
            revoked_id, actor=ACTIVATOR, reason="refuted",
        )
        self.assertEqual(revoked.state, "revoked")
        self.assertEqual(revoked.rule.status, "revoked")
        self.assertEqual(
            [rule.rule_id for rule in self.service.active_rules()], [],
        )
        self.assertIn(content, self.service.negative_memory())
        with self.assertRaises(NegativeMemoryError):
            self.service.propose(
                self.proposal(revoked_id), proposer=PROPOSER,
            )
        revoked_archive = self.service.archive(
            revoked_id, actor=ACTIVATOR,
        )
        self.assertEqual(revoked_archive.state, "archived")
        actions = [
            event["action"]
            for event in self.service.audit(revoked_id)["events"]
        ]
        self.assertIn("revoke", actions)
        self.assertIn("archive", actions)

    # -- self approval ------------------------------------------------------

    def test_self_validation_and_self_promotion_are_denied(self):
        self.service.propose(self.proposal(), proposer=PROPOSER)
        self.service.hash_proposal(self.rule_id, actor=PROPOSER)

        with self.assertRaises(SelfApprovalDenied):
            self.service.validate(self.rule_id, validator=PROPOSER)
        self.assertEqual(self.service.lifecycle(self.rule_id)["state"], "hashed")

        self.service.validate(self.rule_id, validator=VALIDATOR)
        with self.assertRaises(SelfApprovalDenied):
            self.service.test(
                self.rule_id, tester=VALIDATOR, harness="harness:bounded-1",
                cases=[{"outcome": "pass"}],
            )
        self.assertEqual(self.service.lifecycle(self.rule_id)["state"], "validated")

        self.service.test(
            self.rule_id, tester=TESTER, harness="harness:bounded-1",
            cases=[{"outcome": "pass"}],
        )
        with self.assertRaises(SelfApprovalDenied):
            self.service.approve(self.rule_id, approver=TESTER)
        self.assertEqual(self.service.lifecycle(self.rule_id)["state"], "tested")

        self.service.approve(self.rule_id, approver=APPROVER)
        with self.assertRaises(SelfApprovalDenied):
            self.service.commit(self.rule_id, actor=PROPOSER)
        self.assertEqual(self.service.lifecycle(self.rule_id)["state"], "approved")

        self.service.commit(self.rule_id, actor=COMMITTER)
        with self.assertRaises(SelfApprovalDenied):
            self.service.activate(self.rule_id, actor=PROPOSER)
        self.assertEqual(self.service.lifecycle(self.rule_id)["state"], "committed")

        actions = [
            event["action"]
            for event in self.service.audit(self.rule_id)["events"]
        ]
        for denied in (
            "denied_validate", "denied_test", "denied_approve",
            "denied_commit", "denied_activate",
        ):
            self.assertIn(denied, actions)

    # -- contradiction ------------------------------------------------------

    def test_contradiction_blocks_without_last_writer(self):
        self.to_active(
            "math.rule.vector.assoc", claims={"associative": True},
        )
        contradictory = "math.rule.vector.not_assoc"
        self.service.propose(
            self.proposal(contradictory, claims={"associative": False}),
            proposer="learning:boolean-head-8",
        )
        self.service.hash_proposal(contradictory, actor="learning:boolean-head-8")

        with self.assertRaises(ContradictionError) as raised:
            self.service.validate(contradictory, validator="validity:engine-2")
        self.assertEqual(
            set(raised.exception.affected),
            {"math.rule.vector.assoc", contradictory},
        )
        self.assertEqual(
            self.service.lifecycle(contradictory)["state"], "blocked",
        )
        self.assertEqual(
            [(rule.rule_id, rule.version)
             for rule in self.service.active_rules()],
            [("math.rule.vector.assoc", 7)],
        )

        # The contradiction is remembered; unchanged rediscovery is rejected.
        content = self.store.get_rule(
            contradictory, 1,
        ).contract["proposal"]["content_digest"]
        self.assertIn(content, self.service.negative_memory())
        with self.assertRaises(NegativeMemoryError):
            self.service.propose(
                self.proposal(contradictory, claims={"associative": False}),
                proposer="learning:boolean-head-9",
            )

    def test_explicit_contradicts_target_blocks(self):
        self.to_active("math.rule.target", claims={"base": True})
        proposal = RuleProposal(
            rule_id="math.rule.attacker",
            level=1,
            contract={
                "contradicts": [{"rule_id": "math.rule.target"}],
            },
            scope={"function_ids": ["math.vector.add"]},
        )
        self.service.propose(proposal, proposer=PROPOSER)
        self.service.hash_proposal("math.rule.attacker", actor=PROPOSER)
        with self.assertRaises(ContradictionError):
            self.service.validate("math.rule.attacker", validator=VALIDATOR)
        self.assertEqual(
            self.service.lifecycle("math.rule.attacker")["state"], "blocked",
        )

    # -- CAS / duplicates / negative memory --------------------------------

    def test_stale_generation_is_rejected_without_mutation(self):
        self.service.propose(self.proposal(), proposer=PROPOSER)
        self.service.hash_proposal(self.rule_id, actor=PROPOSER)

        with self.assertRaises(StaleGenerationError):
            self.service.validate(
                self.rule_id, validator=VALIDATOR, expected_generation=1,
            )
        self.assertEqual(self.service.lifecycle(self.rule_id)["state"], "hashed")
        self.assertEqual(self.store.get_rule_meta(self.rule_id)["generation"], 2)

        self.service.validate(
            self.rule_id, validator=VALIDATOR, expected_generation=2,
        )
        self.service.test(
            self.rule_id, tester=TESTER, harness="harness:bounded-1",
            cases=[{"outcome": "pass"}],
        )
        self.service.approve(self.rule_id, approver=APPROVER)
        self.service.commit(self.rule_id, actor=COMMITTER)

        with self.assertRaises(StaleGenerationError):
            self.service.activate(
                self.rule_id, actor=ACTIVATOR, expected_generation=5,
            )
        self.assertEqual(
            self.service.lifecycle(self.rule_id)["state"], "committed",
        )
        active = self.service.activate(self.rule_id, actor=ACTIVATOR)
        self.assertEqual(active.state, "active")

    def test_duplicate_proposal_is_deduplicated(self):
        first = self.service.propose(self.proposal(), proposer=PROPOSER)
        second = self.service.propose(self.proposal(), proposer="learning:other")
        self.assertFalse(first.duplicate)
        self.assertTrue(second.duplicate)
        self.assertEqual(first.version, second.version)
        self.assertEqual(self.store.get_rule_meta(self.rule_id)["current_version"], 1)

        with self.assertRaises(DuplicateProposalConflict):
            self.service.propose(
                self.proposal(claims={"associative": False}),
                proposer=PROPOSER,
            )
        self.assertEqual(
            self.store.get_rule_meta(self.rule_id)["current_version"], 1,
        )

    def test_negative_memory_blocks_unchanged_rediscovery(self):
        rule_id = "math.rule.negative"
        self.service.propose(self.proposal(rule_id), proposer=PROPOSER)
        self.service.hash_proposal(rule_id, actor=PROPOSER)
        self.service.validate(rule_id, validator=VALIDATOR)
        with self.assertRaises(TestFailure):
            self.service.test(
                rule_id, tester=TESTER, harness="harness:bounded-1",
                cases=[{"outcome": "pass"}, {"outcome": "fail"}],
            )
        self.assertEqual(self.service.lifecycle(rule_id)["state"], "rejected")
        content = self.store.get_rule(
            rule_id, 1,
        ).contract["proposal"]["content_digest"]
        memory = self.service.negative_memory()
        self.assertIn(content, memory)

        with self.assertRaises(NegativeMemoryError):
            self.service.propose(self.proposal(rule_id), proposer=PROPOSER)

        # A changed evidence digest and an explicit supersedes allow a retry.
        retry = self.service.propose(
            RuleProposal(
                rule_id=rule_id,
                level=1,
                contract={"claims": {"associative": True}},
                scope={"function_ids": ["math.vector.add"]},
                claim_class="rewrite",
                supersedes=content,
                new_evidence_digest="e" * 64,
            ),
            proposer="learning:new-head",
        )
        self.assertEqual(retry.state, "proposed")
        self.assertFalse(retry.duplicate)
        self.assertGreater(retry.version, 1)

    # -- rollback -----------------------------------------------------------

    def test_rollback_restores_previous_active_version(self):
        active = self.to_active("math.rule.rollback", claims={"roll": True})
        first_active_version = active.version
        first_digest = self.rule_digest("math.rule.rollback", first_active_version)

        # A utility experiment creates a newer active head and advances the
        # mapping pointer without changing any mathematical axis.
        experiment = self.service.record_experiment(
            "math.rule.rollback",
            {
                "source": "r7",
                "outcome": "supported",
                "sample_size": 32,
                "data_digest": "a" * 64,
            },
            actor="experiment:r7-2",
        )
        self.assertEqual(experiment.state, "active")
        self.assertGreater(experiment.version, first_active_version)
        self.assertEqual(
            self.store.get_mapping("rule:math.rule.rollback")["current_version"],
            experiment.version,
        )

        rolled = self.service.rollback(
            "math.rule.rollback", actor=ACTIVATOR,
            target_version=first_active_version,
        )
        self.assertEqual(rolled.state, "rolled_back")
        self.assertEqual(rolled.active_version, first_active_version)
        self.assertIsNotNone(rolled.mapping)
        self.assertEqual(
            rolled.mapping["current_version"], first_active_version,
        )
        self.assertEqual(rolled.mapping["status"], "rolled_back")
        self.assertEqual(
            rolled.mapping["target_digest"], first_digest,
        )
        self.assertEqual(
            self.store.get_rule(
                "math.rule.rollback", first_active_version,
            ).status,
            "active",
        )
        self.assertEqual(
            [(rule.rule_id, rule.version)
             for rule in self.service.active_rules()],
            [("math.rule.rollback", first_active_version)],
        )
        # All versions remain recoverable; nothing was rewritten.
        self.store.get_rule("math.rule.rollback", experiment.version)

        # Idempotent: no new version and no new pointer move.
        head_before = self.store.get_rule_meta("math.rule.rollback")
        repeated = self.service.rollback(
            "math.rule.rollback", actor=ACTIVATOR,
            target_version=first_active_version,
        )
        self.assertTrue(repeated.duplicate)
        head_after = self.store.get_rule_meta("math.rule.rollback")
        self.assertEqual(head_before["current_version"], head_after["current_version"])
        self.assertEqual(head_before["generation"], head_after["generation"])

        audit = self.service.audit("math.rule.rollback")
        self.assertIn(
            "rollback", [event["action"] for event in audit["events"]],
        )
        self.assertGreaterEqual(audit["mapping_event_count"], 1)

        with self.assertRaises(LifecycleStateError):
            self.service.rollback(
                "math.rule.rollback", actor=ACTIVATOR,
                target_version=2,  # hashed, never active
            )

    # -- experiments --------------------------------------------------------

    def test_experiment_outcome_is_utility_only(self):
        tested = self.to_tested("math.rule.utility", claims={"u": True})
        before = self.service.axes("math.rule.utility")
        before_meta = self.store.get_rule_meta("math.rule.utility")

        supported = self.service.record_experiment(
            "math.rule.utility",
            {
                "source": "r7",
                "outcome": "supported",
                "sample_size": 64,
                "seeds": [1, 2, 3],
                "data_digest": "b" * 64,
            },
            actor="experiment:r7-2",
        )
        after = self.service.axes("math.rule.utility")
        self.assertEqual(after.utility["status"], "supported")
        self.assertEqual(
            after.utility["outcomes"][-1]["outcome"], "supported",
        )
        # No mathematical axis changed.
        self.assertEqual(before.truth, after.truth)
        self.assertEqual(before.validity, after.validity)
        self.assertEqual(before.proof, after.proof)
        self.assertEqual(before.lifecycle["state"], after.lifecycle["state"])
        self.assertEqual(tested.state, "tested")
        self.assertEqual(supported.state, "tested")
        self.assertGreater(
            self.store.get_rule_meta("math.rule.utility")["generation"],
            before_meta["generation"],
        )

        # Requesting promotion from an experiment is explicitly forbidden and
        # writes nothing.
        version_before = self.store.get_rule_meta(
            "math.rule.utility")["current_version"]
        with self.assertRaises(ExperimentPromotionDenied):
            self.service.record_experiment(
                "math.rule.utility",
                {
                    "source": "r7",
                    "outcome": "supported",
                    "sample_size": 64,
                    "data_digest": "b" * 64,
                },
                actor="experiment:r7-2",
                request_promotion=True,
            )
        self.assertEqual(
            self.store.get_rule_meta(
                "math.rule.utility")["current_version"],
            version_before,
        )
        with self.assertRaises(ExperimentPromotionDenied):
            self.service.promote_by_experiment(
                "math.rule.utility", actor="experiment:r7-2",
            )

        # Synthetic/underpowered support is downgraded to inconclusive.
        downgraded = self.service.record_experiment(
            "math.rule.utility",
            {
                "source": "lm_ablation",
                "outcome": "ablation_passed",
                "sample_size": 8,
                "data_digest": "c" * 64,
                "synthetic": True,
            },
            actor="experiment:lm-1",
        )
        latest = downgraded.axes.utility["outcomes"][-1]
        self.assertEqual(latest["outcome"], "inconclusive")
        self.assertEqual(latest["requested_outcome"], "ablation_passed")
        self.assertIn("synthetic", latest["inconclusive_reasons"])
        after_downgrade = self.service.axes("math.rule.utility")
        self.assertEqual(before.truth, after_downgrade.truth)
        self.assertEqual(before.validity, after_downgrade.validity)
        self.assertEqual(before.proof, after_downgrade.proof)

        # The experiment did not bypass activation: the rule is still only
        # tested and must complete approve/commit/activate.
        with self.assertRaises(LifecycleStateError):
            self.service.activate(
                "math.rule.utility", actor=ACTIVATOR,
            )
        self.service.approve("math.rule.utility", approver=APPROVER)
        self.service.commit("math.rule.utility", actor=COMMITTER)
        active = self.service.activate(
            "math.rule.utility", actor=ACTIVATOR,
        )
        self.assertEqual(active.state, "active")
        self.assertEqual(active.axes.validity["earned"], "V2")
        self.assertEqual(active.axes.proof["status"], "none")
        self.assertEqual(active.axes.truth["status"], "unknown")

    # -- proof discipline ---------------------------------------------------

    def test_trusted_proof_only_earns_v3_and_theorem(self):
        proposal = RuleProposal(
            rule_id="math.rule.proved",
            level=1,
            contract={"claims": {"proved": True}},
            scope={"function_ids": ["math.vector.add"]},
            claim_class="theorem",
            proof_digest="d" * 64,
            checker="checker:trusted",
        )
        self.service.propose(proposal, proposer=PROPOSER)
        self.service.hash_proposal("math.rule.proved", actor=PROPOSER)
        validated = self.service.validate(
            "math.rule.proved", validator=VALIDATOR,
        )
        self.assertEqual(validated.axes.proof["status"], "checked")
        self.assertTrue(validated.axes.proof["trusted"])
        self.assertEqual(validated.axes.validity["earned"], "V3")
        self.assertEqual(validated.axes.truth["status"], "theorem")

        untrusted = RuleProposal(
            rule_id="math.rule.untrusted",
            level=1,
            contract={"claims": {"untrusted": True}},
            scope={"function_ids": ["math.vector.add"]},
            claim_class="theorem",
            proof_digest="e" * 64,
            checker="checker:unknown",
        )
        self.service.propose(untrusted, proposer=PROPOSER)
        self.service.hash_proposal("math.rule.untrusted", actor=PROPOSER)
        valid = self.service.validate(
            "math.rule.untrusted", validator=VALIDATOR,
        )
        self.assertEqual(valid.axes.proof["status"], "candidate")
        self.assertFalse(valid.axes.proof["trusted"])
        self.assertEqual(valid.axes.validity["earned"], "V1")
        self.assertEqual(valid.axes.truth["status"], "unknown")
        tested = self.service.test(
            "math.rule.untrusted", tester=TESTER,
            harness="harness:bounded-1",
            cases=[{"outcome": "pass"}],
        )
        self.assertEqual(tested.axes.validity["earned"], "V2")
        self.assertEqual(tested.axes.proof["status"], "candidate")
        self.assertEqual(tested.axes.truth["status"], "unknown")

    def test_client_set_authority_axes_are_rejected(self):
        for contract in (
            {"validity": {"earned": "V3"}},
            {"truth_status": "theorem"},
            {"proof_status": "verified"},
            {"lifecycle": {"state": "active"}},
            {"axes": {"validity": {"earned": "V3"}}},
            {"self_promoted": True},
        ):
            rule_id = "math.rule.client." + sha256_text(
                canonical_json(contract))[:16]
            with self.assertRaises(ProposalRejected):
                self.service.propose(
                    RuleProposal(
                        rule_id=rule_id,
                        level=1,
                        contract=contract,
                    ),
                    proposer=PROPOSER,
                )

    # -- audit --------------------------------------------------------------

    def test_audit_is_ordered_append_only_and_verifiable(self):
        self.to_active("math.rule.audited")
        audit = self.service.audit("math.rule.audited")
        actions = [event["action"] for event in audit["events"]]
        self.assertEqual(actions, [
            "propose", "hash", "validate", "test", "approve", "commit",
            "activate",
        ])
        self.assertEqual(
            [event["state"] for event in audit["events"]],
            [
                "proposed", "hashed", "validated", "tested", "approved",
                "committed", "active",
            ],
        )
        for event in audit["events"]:
            self.assertIsNotNone(event["evidence_id"])
            self.assertEqual(event["proposal_digest"],
                             audit["events"][0]["proposal_digest"])
            self.assertIsNotNone(event["actor"])
        self.assertTrue(self.service.verify_audit("math.rule.audited"))
        self.assertTrue(self.service.verify_audit(
            "math.rule.audited", expected_digest=audit["audit_digest"],
        ))
        with self.assertRaises(AuditError):
            self.service.verify_audit(
                "math.rule.audited", expected_digest="0" * 64,
            )
        # The digest is deterministic for an unchanged append-only chain.
        self.assertEqual(
            audit["audit_digest"],
            self.service.audit("math.rule.audited")["audit_digest"],
        )

        # Event storage is append-only at the SQLite layer.
        with closing(sqlite3.connect(self.bs0_path)) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "UPDATE math_event SET actor='tamper' WHERE object_id=?",
                    ("math.rule.audited",),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "DELETE FROM math_event WHERE object_id=?",
                    ("math.rule.audited",),
                )

    def test_inconclusive_tests_do_not_advance_or_promote(self):
        self.service.propose(self.proposal("math.rule.inconclusive"),
                             proposer=PROPOSER)
        self.service.hash_proposal("math.rule.inconclusive", actor=PROPOSER)
        self.service.validate("math.rule.inconclusive", validator=VALIDATOR)
        meta_before = self.store.get_rule_meta("math.rule.inconclusive")

        with self.assertRaises(InconclusiveEvidence):
            self.service.test(
                "math.rule.inconclusive", tester=TESTER,
                harness="harness:bounded-1",
                cases=[{"outcome": "inconclusive"}],
            )
        meta_after = self.store.get_rule_meta("math.rule.inconclusive")
        self.assertEqual(
            meta_before["current_version"], meta_after["current_version"],
        )
        self.assertEqual(
            self.service.lifecycle("math.rule.inconclusive")["state"],
            "validated",
        )
        self.assertEqual(
            self.service.axes("math.rule.inconclusive").validity["earned"],
            "V1",
        )


if __name__ == "__main__":
    unittest.main()
