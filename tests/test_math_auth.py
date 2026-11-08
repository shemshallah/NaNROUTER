from __future__ import annotations

import unittest

from runner_riddle.math_auth import (
    ACTIVATE,
    APPROVE,
    POLICY_CHANGE,
    PROPOSE,
    PRUNE,
    READ,
    AuthorizationDenied,
    ClassCPolicyTransition,
    MathAuthorizationError,
    MathAuthorizer,
    Principal,
    WorkerIdentityBinder,
)


class MathAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.policy = MathAuthorizer()
        self.proposer = Principal(
            "worker:alice", roles=frozenset({"proposer"})
        )
        self.approver = Principal(
            "worker:bob", roles=frozenset({"approver"})
        )
        self.activator = Principal(
            "worker:carol", roles=frozenset({"activator"}),
            capabilities=frozenset({"rule.activate"}),
        )

    def test_role_permissions_are_explicit(self):
        self.assertTrue(self.policy.authorize(self.proposer, PROPOSE).allowed)
        self.assertTrue(self.policy.authorize(self.approver, APPROVE).allowed)
        decision = self.policy.authorize(self.proposer, APPROVE)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "ROLE_NOT_PERMITTED")

    def test_revoked_principal_is_denied(self):
        revoked = Principal(
            "worker:alice", roles=frozenset({"proposer"}), revoked=True,
        )
        decision = self.policy.authorize(revoked, PROPOSE)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "PRINCIPAL_REVOKED")

    def test_activation_requires_explicit_capability(self):
        no_cap = Principal(
            "worker:carol", roles=frozenset({"activator"}),
        )
        decision = self.policy.authorize(no_cap, ACTIVATE)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "CAPABILITY_REQUIRED")
        self.assertTrue(self.policy.authorize(self.activator, ACTIVATE).allowed)

    def test_pruning_requires_explicit_capability(self):
        pruner = Principal("worker:pruner", roles=frozenset({"pruner"}))
        self.assertFalse(self.policy.authorize(pruner, PRUNE).allowed)
        with_cap = Principal(
            "worker:pruner", roles=frozenset({"pruner"}),
            capabilities=frozenset({"rule.prune"}),
        )
        self.assertTrue(self.policy.authorize(with_cap, PRUNE).allowed)

    def test_separation_of_duty_blocks_self_approval(self):
        decision = self.policy.authorize(
            self.approver, APPROVE,
            context={"proposer_id": "worker:bob"},
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "SEPARATION_OF_DUTY_VIOLATION")
        decision = self.policy.authorize(
            self.approver, APPROVE,
            context={"proposer_id": "worker:alice"},
        )
        self.assertTrue(decision.allowed)

    def test_admin_is_explicit_and_auditable(self):
        admin = Principal("worker:root", roles=frozenset({"admin"}))
        decision = self.policy.authorize(admin, ACTIVATE)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.principal_id, "worker:root")
        self.assertEqual(len(decision.principal_digest), 64)

    def test_require_raises_typed_denial(self):
        with self.assertRaises(AuthorizationDenied) as raised:
            self.policy.require(self.proposer, APPROVE)
        self.assertEqual(raised.exception.principal_id, "worker:alice")
        self.assertEqual(raised.exception.action, APPROVE)

    def test_unknown_principal_role_or_action_fails_closed(self):
        with self.assertRaises(MathAuthorizationError):
            Principal("worker:alice", roles=frozenset({"wizard"}))
        with self.assertRaises(MathAuthorizationError):
            self.policy.authorize(self.proposer, "math.teleport")

    def test_class_c_policy_transition_requires_separate_signers(self):
        proposer = Principal(
            "policy:alice", roles=frozenset({"policy_authority"}),
            capabilities=frozenset({"math.policy"}),
        )
        approver = Principal(
            "policy:bob", roles=frozenset({"policy_authority"}),
            capabilities=frozenset({"math.policy"}),
        )
        transition = ClassCPolicyTransition(
            transition_id="policy-change-1",
            change_kind="checker",
            old_policy_digest="a" * 64,
            new_policy_digest="b" * 64,
            proposed_by="policy:alice",
            approved_by="policy:bob",
            signature_digest="c" * 64,
            tick=7,
        )
        decision = self.policy.authorize_class_c(
            transition, proposer, approver,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.action, POLICY_CHANGE)
        self.assertEqual(len(transition.digest()), 64)
        self.assertFalse(transition.to_dict()["signature_verified"])

        with self.assertRaises(MathAuthorizationError):
            ClassCPolicyTransition(
                transition_id="policy-change-2",
                change_kind="checker",
                old_policy_digest="a" * 64,
                new_policy_digest="a" * 64,
                proposed_by="policy:alice",
                approved_by="policy:bob",
                signature_digest="c" * 64,
            )
        with self.assertRaises(MathAuthorizationError):
            ClassCPolicyTransition(
                transition_id="policy-change-3",
                change_kind="checker",
                old_policy_digest="a" * 64,
                new_policy_digest="b" * 64,
                proposed_by="policy:alice",
                approved_by="policy:alice",
                signature_digest="c" * 64,
            )
        with self.assertRaises(MathAuthorizationError):
            ClassCPolicyTransition(
                transition_id="policy-change-4",
                change_kind="unknown",
                old_policy_digest="a" * 64,
                new_policy_digest="b" * 64,
                proposed_by="policy:alice",
                approved_by="policy:bob",
                signature_digest="c" * 64,
            )

    def test_class_c_requires_policy_capability_and_matching_signers(self):
        proposer = Principal("policy:alice", roles=frozenset({"policy_authority"}))
        approver = Principal(
            "policy:bob", roles=frozenset({"policy_authority"}),
            capabilities=frozenset({"math.policy"}),
        )
        transition = ClassCPolicyTransition(
            transition_id="policy-change-5",
            change_kind="acl_root",
            old_policy_digest="a" * 64,
            new_policy_digest="b" * 64,
            proposed_by="policy:alice",
            approved_by="policy:bob",
            signature_digest="c" * 64,
        )
        self.assertFalse(
            self.policy.authorize_class_c(transition, proposer, approver).allowed
        )
        wrong = ClassCPolicyTransition(
            transition_id="policy-change-6",
            change_kind="acl_root",
            old_policy_digest="a" * 64,
            new_policy_digest="b" * 64,
            proposed_by="policy:alice",
            approved_by="policy:bob",
            signature_digest="c" * 64,
        )
        with self.assertRaises(AuthorizationDenied):
            self.policy.require_class_c(wrong, proposer, approver)

    def test_worker_identity_binder_stores_only_digests(self):
        binder = WorkerIdentityBinder()
        token = "worker-token-secret-000000"
        digest = binder.bind(token, "MC0:0/R0")
        self.assertEqual(len(digest), 64)
        self.assertTrue(binder.verify(token, "MC0:0/R0"))
        self.assertFalse(binder.verify(token, "MC0:0/R1"))
        self.assertFalse(binder.verify("wrong-token", "MC0:0/R0"))
        self.assertNotIn(token, str(binder.stats()))
        self.assertFalse(binder.stats()["raw_tokens_stored"])
        self.assertTrue(binder.unbind(token))
        self.assertFalse(binder.verify(token, "MC0:0/R0"))

    def test_worker_identity_binder_rejects_rebinding_another_owner(self):
        binder = WorkerIdentityBinder()
        binder.bind("token-a", "owner-a")
        with self.assertRaises(MathAuthorizationError):
            binder.bind("token-a", "owner-b")
        self.assertTrue(binder("token-a", "owner-a"))
        with self.assertRaises(MathAuthorizationError):
            binder.bind("", "owner-a")

    def test_decision_digest_is_stable_and_token_free(self):
        first = self.policy.authorize(self.proposer, READ)
        second = self.policy.authorize(self.proposer, READ)
        self.assertEqual(first.to_dict(), second.to_dict())
        rendered = str(first.to_dict()).lower()
        for secret in ("token", "password", "secret"):
            self.assertNotIn(secret, rendered)


if __name__ == "__main__":
    unittest.main()
