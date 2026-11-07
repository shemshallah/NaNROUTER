from __future__ import annotations

import unittest

from runner_riddle.math_auth import (
    ACTIVATE,
    APPROVE,
    PROPOSE,
    PRUNE,
    READ,
    AuthorizationDenied,
    MathAuthorizationError,
    MathAuthorizer,
    Principal,
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

    def test_decision_digest_is_stable_and_token_free(self):
        first = self.policy.authorize(self.proposer, READ)
        second = self.policy.authorize(self.proposer, READ)
        self.assertEqual(first.to_dict(), second.to_dict())
        rendered = str(first.to_dict()).lower()
        for secret in ("token", "password", "secret"):
            self.assertNotIn(secret, rendered)


if __name__ == "__main__":
    unittest.main()
