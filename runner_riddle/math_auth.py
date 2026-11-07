"""Typed math-control authorization policy (GAME_PLAN_:: §15).

This module is a **policy decision point**, not an authentication system.  The
caller must authenticate the principal (for example, through the existing
WaveService token path) before constructing a :class:`Principal`.

It owns no tokens, passwords, or durable secret.  It does not execute
mathematics and does not replace the validity engine, capability admission, or
ring authority.  A valid decision means only that this principal may attempt
the named control action.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Iterable, Mapping

SCHEMA = "nanrouter.math-authorization.v1"
DECISION_SCHEMA = "nanrouter.math-authorization-decision.v1"

PROPOSE = "rule.propose"
VALIDATE = "rule.validate"
TEST = "rule.test"
APPROVE = "rule.approve"
COMMIT = "rule.commit"
ACTIVATE = "rule.activate"
PROMOTE = "rule.promote"
PRUNE = "rule.prune"
EXECUTE = "math.execute"
LINK = "math.link"
READ = "math.read"
WRITE = "math.write"
GRANT = "math.grant"

ACTIONS = frozenset({
    PROPOSE, VALIDATE, TEST, APPROVE, COMMIT, ACTIVATE, PROMOTE, PRUNE,
    EXECUTE, LINK, READ, WRITE, GRANT,
})

ROLE_ACTIONS: dict[str, frozenset[str]] = {
    "proposer": frozenset({PROPOSE, READ, LINK}),
    "validator": frozenset({VALIDATE, READ, LINK}),
    "tester": frozenset({TEST, READ, LINK}),
    "approver": frozenset({APPROVE, READ, LINK}),
    "committer": frozenset({COMMIT, READ, LINK}),
    "activator": frozenset({ACTIVATE, READ, LINK}),
    "promoter": frozenset({PROMOTE, APPROVE, READ, LINK}),
    "pruner": frozenset({PRUNE, READ}),
    "executor": frozenset({EXECUTE, READ, LINK}),
    "store_writer": frozenset({WRITE, READ}),
    "admin": frozenset(ACTIONS),
    "supervisor": frozenset({READ, LINK, EXECUTE, PRUNE}),
}

# Actions that require a distinct principal from the proposal author.
SEPARATION_ACTIONS = frozenset({APPROVE, COMMIT, ACTIVATE, PROMOTE})
# Actions that require an explicit capability in addition to a role.
CAPABILITY_ACTIONS = {
    ACTIVATE: "rule.activate",
    PRUNE: "rule.prune",
    PROMOTE: "rule.promote",
    GRANT: "math.grant",
}


class MathAuthorizationError(ValueError):
    """Base error for malformed principals or policy requests."""


class AuthorizationDenied(MathAuthorizationError):
    """A principal is not allowed to attempt the requested action."""

    def __init__(self, reason: str, *, principal_id: str | None = None,
                 action: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.principal_id = principal_id
        self.action = action


def _text(value: Any, name: str, *, maximum: int = 160) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise MathAuthorizationError(f"{name} must be a non-empty string <= {maximum}")
    return value


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _digest(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Principal:
    """An already-authenticated control-plane identity."""

    principal_id: str
    roles: frozenset[str] = frozenset()
    capabilities: frozenset[str] = frozenset()
    epoch: int = 1
    revoked: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "principal_id", _text(self.principal_id, "principal_id")
        )
        roles = self.roles
        if isinstance(roles, str):
            roles = (roles,)
        capabilities = self.capabilities
        if isinstance(capabilities, str):
            capabilities = (capabilities,)
        roles = frozenset(_text(role, "role", maximum=64) for role in roles or ())
        capabilities = frozenset(
            _text(capability, "capability", maximum=160)
            for capability in capabilities or ()
        )
        unknown = roles - set(ROLE_ACTIONS)
        if unknown:
            raise MathAuthorizationError(
                f"unknown principal roles: {', '.join(sorted(unknown))}"
            )
        object.__setattr__(self, "roles", roles)
        object.__setattr__(self, "capabilities", capabilities)
        if not _is_int(self.epoch) or self.epoch < 0:
            raise MathAuthorizationError("principal epoch must be an integer >= 0")
        if not isinstance(self.revoked, bool):
            raise MathAuthorizationError("revoked must be a boolean")
        object.__setattr__(self, "attributes", dict(self.attributes or {}))

    @property
    def active(self) -> bool:
        return not self.revoked

    def has_role(self, role: str) -> bool:
        return role in self.roles or "admin" in self.roles

    def has_capability(self, capability: str) -> bool:
        return (
            capability in self.capabilities
            or "admin" in self.roles
            or "math.all" in self.capabilities
        )

    def digest(self) -> str:
        return _digest({
            "principal_id": self.principal_id,
            "roles": sorted(self.roles),
            "capabilities": sorted(self.capabilities),
            "epoch": self.epoch,
            "revoked": self.revoked,
        })


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    principal_id: str
    action: str
    reason: str = ""
    principal_digest: str = ""
    context_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise MathAuthorizationError("allowed must be a boolean")
        if not self.allowed and not self.reason:
            raise MathAuthorizationError("a denied decision requires a reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DECISION_SCHEMA,
            "allowed": self.allowed,
            "principal_id": self.principal_id,
            "principal_digest": self.principal_digest,
            "action": self.action,
            "reason": self.reason,
            "context_digest": self.context_digest,
        }


class MathAuthorizer:
    """Pure, deterministic authorization policy."""

    def __init__(
        self,
        *,
        role_actions: Mapping[str, Iterable[str]] | None = None,
        separation_actions: Iterable[str] = SEPARATION_ACTIONS,
        capability_actions: Mapping[str, str] | None = None,
    ) -> None:
        self.role_actions = {
            role: frozenset(actions)
            for role, actions in (role_actions or ROLE_ACTIONS).items()
        }
        unknown_actions = set().union(*self.role_actions.values()) - ACTIONS
        if unknown_actions:
            raise MathAuthorizationError(
                f"policy contains unknown actions: {', '.join(sorted(unknown_actions))}"
            )
        self.separation_actions = frozenset(separation_actions)
        self.capability_actions = dict(capability_actions or CAPABILITY_ACTIONS)

    def _decision(self, principal: Principal, action: str, *,
                  allowed: bool, reason: str = "",
                  context: Mapping[str, Any] | None = None) -> AuthorizationDecision:
        return AuthorizationDecision(
            allowed=allowed,
            principal_id=principal.principal_id,
            principal_digest=principal.digest(),
            action=action,
            reason=reason,
            context_digest=_digest(dict(context or {})),
        )

    def authorize(
        self,
        principal: Principal,
        action: str,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> AuthorizationDecision:
        """Return a typed decision; does not raise for a normal denial."""
        if not isinstance(principal, Principal):
            raise MathAuthorizationError("principal must be a Principal")
        action = _text(action, "action", maximum=64)
        if action not in ACTIONS:
            raise MathAuthorizationError(f"unknown action: {action!r}")
        if not principal.active:
            return self._decision(
                principal, action, allowed=False, reason="PRINCIPAL_REVOKED",
                context=context,
            )
        allowed = False
        for role in principal.roles:
            if action in self.role_actions.get(role, frozenset()):
                allowed = True
                break
        if "admin" in principal.roles:
            allowed = True
        if not allowed:
            return self._decision(
                principal, action, allowed=False, reason="ROLE_NOT_PERMITTED",
                context=context,
            )
        required_capability = self.capability_actions.get(action)
        if required_capability and not principal.has_capability(required_capability):
            return self._decision(
                principal, action, allowed=False, reason="CAPABILITY_REQUIRED",
                context=context,
            )
        if action in self.separation_actions and context:
            proposer = context.get("proposer_id") or context.get("principal_id")
            if isinstance(proposer, str) and proposer == principal.principal_id:
                return self._decision(
                    principal, action, allowed=False,
                    reason="SEPARATION_OF_DUTY_VIOLATION", context=context,
                )
        return self._decision(
            principal, action, allowed=True, context=context,
        )

    def require(
        self,
        principal: Principal,
        action: str,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> AuthorizationDecision:
        decision = self.authorize(principal, action, context=context)
        if not decision.allowed:
            raise AuthorizationDenied(
                decision.reason,
                principal_id=decision.principal_id,
                action=decision.action,
            )
        return decision


__all__ = [
    "ACTIONS", "APPROVE", "ACTIVATE", "AuthorizationDecision",
    "AuthorizationDenied", "COMMIT", "CAPABILITY_ACTIONS", "EXECUTE",
    "GRANT", "LINK", "MathAuthorizationError", "MathAuthorizer", "PROPOSE",
    "PROMOTE", "PRUNE", "Principal", "READ", "ROLE_ACTIONS", "SCHEMA",
    "SEPARATION_ACTIONS", "TEST", "VALIDATE", "WRITE",
]
