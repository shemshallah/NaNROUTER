"""Safe rule-discovery lifecycle for GAME_PLAN_:: (P9).

This module is the learning/rule-proposal authority.  It does not evaluate
mathematics, execute a kernel, or grant execution authority.  It turns a
proposal into an append-only, digest-bound lifecycle record and uses
:class:`runner_riddle.math_store.MathStore` for persistence:

* immutable rule versions (``math_rule`` / ``math_rule_version``);
* transactional version/generation CAS (``put_rule``);
* explicit active-pointer CAS and rollback (``set_mapping`` /
  ``rollback_mapping``);
* append-only evidence (``math_event``).

No new database tables are introduced.

The orthogonal axes required by GAME_PLAN_:: §3.3 are never collapsed:

``truth``, ``validity``, ``proof``, ``lifecycle``, and ``utility``.

Only a trusted proof checker may raise truth to ``theorem`` or validity to
``V3``.  A numerical test can earn bounded validity ``V2``; it is not a proof.
Boolean-head, R7, and LM-ablation outcomes may update ``utility`` only.  They
can never set truth, validity, or proof.

Lifecycle::

    proposed -> hashed -> validated -> tested -> approved -> committed
             -> active -> deprecated / revoked / archived
             -> rolled_back (active pointer moves to an earlier version)

Level 0 rules are immutable and cannot be proposed, validated, promoted, or
activated by this service.  Level 3 proposals are isolation-only: activation
requires ``isolated=True`` and they are excluded from production snapshots.

An optional :class:`runner_riddle.math_auth.MathAuthorizer` plus an
already-authenticated :class:`runner_riddle.math_auth.Principal` can gate every
store-mutating lifecycle action.  Authorization is a separate policy decision:
it fails closed before any write, and it never substitutes for validity, proof,
or capability admission.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Iterable, Mapping

from .math_auth import (
    ACTIVATE,
    APPROVE,
    COMMIT,
    PROPOSE,
    PROMOTE,
    PRUNE,
    TEST,
    VALIDATE,
    AuthorizationDecision,
    AuthorizationDenied,
    MathAuthorizer,
    Principal,
)
from .math_objects import (
    MathObjectError,
    MathRule,
    canonical_json,
    digest_object,
    sha256_text,
)
from .math_store import (
    MathReferenceError,
    MathStore,
    MathStoreError,
    StaleGenerationError,
)
from .math_validity import (
    MathSnapshot,
    MathSnapshotError,
    MathValidityEngine,
    MathValidityError,
)

LEARNING_SCHEMA = "nanrouter.math-learning.v1"
# MathStore has one stable mapping per (object_type, object_id); the rule
# mapping is the single transactional active pointer.
ACTIVE_MAPPING_PREFIX = "rule:"

LIFECYCLE_STATES = frozenset({
    "proposed", "hashed", "validated", "tested", "approved", "committed",
    "active", "deprecated", "revoked", "rolled_back", "archived",
    "blocked", "rejected",
})
NEGATIVE_STATES = frozenset({"blocked", "rejected", "revoked", "archived"})
TERMINAL_STATES = frozenset({"revoked", "archived", "rejected"})
PRE_ACTIVE_STATES = frozenset({
    "proposed", "hashed", "validated", "tested", "approved", "committed",
})

CLAIM_CLASSES = frozenset({
    "definition", "theorem", "rewrite", "heuristic", "empirical_claim",
})
TRUTH_CLAIMS = frozenset({
    "definitional", "theorem", "open", "independent", "unknown",
})
VALIDITY_LEVELS = ("V0", "V1", "V2", "V3")
PROOF_AXIS_STATES = frozenset({
    "none", "sketch", "candidate", "checked", "refuted", "stale",
    "quarantined",
})
EXPERIMENT_SOURCES = frozenset({"boolean_head", "r7", "lm_ablation"})
EXPERIMENT_OUTCOMES = frozenset({
    "supported", "ablation_passed", "inconclusive", "rejected",
})
_TERMINAL_NEGATIVE_SOURCES = frozenset({
    "blocked", "rejected", "revoked", "archived",
})

# Contract keys owned by this authority.  A caller may not pre-populate them:
# the client may *claim* a validity level but only the validator earns one.
_RESERVED_CONTRACT_KEYS = frozenset({
    "axes", "proposal", "lifecycle", "learning_evidence",
    "earned_validity", "validity", "validity_level", "validity_status",
    "truth_status", "proof_status", "self_promoted", "self_promotion",
    "promote_self", "promote_to_level", "promoted_to_level", "promoted_level",
    "level_override", "acts_as_level", "authority_level", "requested_level",
    "target_level", "claimed_level", "effective_level", "production",
    "authoritative", "promote_to_production",
})

_INITIAL_VALIDITY_BASIS = ("schema", "digest", "provenance")
_TEST_OUTCOMES = frozenset({"pass", "fail", "inconclusive"})

_UNSET = object()


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------


class MathLearningError(ValueError):
    """Base error for the rule-discovery lifecycle."""


class LearningConfigError(MathLearningError):
    """The service was constructed with an invalid policy or store."""


class LifecycleStateError(MathLearningError):
    """A transition was requested from the wrong lifecycle state."""


class ProposalRejected(MathLearningError):
    """A proposal failed structural, scope, policy, or evidence checks."""

    def __init__(self, message: str, *, record: "LifecycleRecord | None" = None,
                 reason: str = "") -> None:
        super().__init__(message)
        self.record = record
        self.reason = reason or message


class DuplicateProposalConflict(MathLearningError):
    """The same stable rule identity was proposed with different content."""


class NegativeMemoryError(ProposalRejected):
    """An unchanged, previously rejected proposal was rediscovered."""


class SelfApprovalDenied(MathLearningError):
    """The proposer attempted to validate, test, approve, or promote itself."""


class Level0ImmutableError(MathLearningError):
    """Learning attempted to touch a level-0 (axiom/type-safety) rule."""


class Level3IsolationError(MathLearningError):
    """A level-3 rule was activated without isolation or used as production."""


class ContradictionError(ProposalRejected):
    """The candidate contradicts a live rule; promotion is blocked."""

    def __init__(self, message: str, *, record: "LifecycleRecord | None" = None,
                 affected: tuple[str, ...] = ()) -> None:
        super().__init__(message, record=record)
        self.affected = tuple(affected)


class TestFailure(ProposalRejected):
    """A deterministic, bounded test reported a failure."""


class InconclusiveEvidence(ProposalRejected):
    """Evidence is missing, synthetic, underpowered, or undecidable."""


class ExperimentPromotionDenied(MathLearningError):
    """An experiment outcome was used where validity/proof is required."""


class AuditError(MathLearningError):
    """The append-only evidence chain could not be verified."""


class LearningAuthorizationDenied(MathLearningError, AuthorizationDenied):
    """A lifecycle action is not authorized for the configured principal.

    This is deliberately both a learning error and the authorization policy's
    typed denial, so callers may catch either layer.  Authorization denials are
    raised before a lifecycle version, mapping, or evidence row is written.
    """

    def __init__(self, reason: str, *, principal_id: str | None = None,
                 action: str | None = None,
                 decision: AuthorizationDecision | None = None) -> None:
        MathLearningError.__init__(self, reason)
        self.reason = reason
        self.principal_id = principal_id
        self.action = action
        self.decision = decision


# Both names are exported for callers that prefer the shorter or longer form.
LearningAuthorizationError = LearningAuthorizationDenied
MathLearningAuthorizationError = LearningAuthorizationDenied


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _require_text(value: Any, name: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise MathLearningError(f"{name} must be a non-empty string <= {maximum}")
    return value


def _require_int(value: Any, name: str, *, minimum: int = 0,
                 maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MathLearningError(f"{name} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise MathLearningError(f"{name} must be <= {maximum}")
    return value


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise MathLearningError(f"{name} must be a boolean")
    return value


def _require_digest(value: Any, name: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise MathLearningError(f"{name} must be 64 lowercase hex characters")
    text = value[7:] if value.startswith("sha256:") else value
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise MathLearningError(f"{name} must be 64 lowercase hex characters")
    return text


def _contains_float(value: Any) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, Mapping):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, (tuple, list, set, frozenset)):
        return any(_contains_float(item) for item in value)
    return False


def _canonical_copy(value: Any, name: str) -> Any:
    """Deep-copy through canonical JSON; reject floats/non-JSON values."""
    if _contains_float(value):
        raise MathLearningError(f"{name} must not contain host floats")
    try:
        return json.loads(canonical_json(value))
    except (MathObjectError, TypeError, ValueError) as exc:
        raise MathLearningError(f"{name} is not canonical JSON") from exc


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MathLearningError(f"{name} must be an object")
    copied = _canonical_copy(dict(value), name)
    if not isinstance(copied, dict):
        raise MathLearningError(f"{name} must be an object")
    return copied


def _axes_document(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MathLearningError("rule contract axes are missing")
    axes = _canonical_copy(dict(value), "rule contract axes")
    required = ("truth", "validity", "proof", "lifecycle", "utility")
    for key in required:
        if not isinstance(axes.get(key), dict):
            raise MathLearningError(f"rule axis {key!r} is missing")
    return axes


def _rule_digest(rule: MathRule) -> str:
    return sha256_text(canonical_json(rule.to_dict()))


def _scope_ids(scope: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for key in ("function_ids", "functions", "applies_to"):
        raw = scope.get(key)
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, (tuple, list)):
            values.extend(item for item in raw if isinstance(item, str))
    raw = scope.get("function_id")
    if isinstance(raw, str):
        values.append(raw)
    return tuple(dict.fromkeys(values))


def _claims(rule: MathRule) -> dict[str, Any]:
    raw = rule.contract.get("claims")
    if raw is None:
        raw = rule.contract.get("asserts")
    result: dict[str, Any] = {}
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            result[str(key)] = value
    elif isinstance(raw, (tuple, list)):
        for entry in raw:
            if not isinstance(entry, Mapping):
                continue
            key = entry.get("key", entry.get("name"))
            if isinstance(key, str):
                result[key] = entry.get("value")
    return result


def _tokens(rule: MathRule, key: str) -> tuple[str, ...]:
    raw = rule.contract.get(key)
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, (tuple, list)):
        return tuple(item for item in raw if isinstance(item, str))
    if isinstance(raw, Mapping):
        return tuple(str(item) for item in raw)
    return ()


def _scopes_overlap(left: MathRule, right: MathRule) -> bool:
    left_ids = set(_scope_ids(left.scope))
    right_ids = set(_scope_ids(right.scope))
    if left_ids and right_ids:
        return bool(left_ids & right_ids)
    for rule in (left, right):
        if rule.scope.get("global") is True or rule.scope.get("all") is True:
            return True
    left_family = left.scope.get("family")
    right_family = right.scope.get("family")
    if isinstance(left_family, str) and isinstance(right_family, str):
        return left_family == right_family
    # An unscoped rule is global within its authority domain.
    if not left_ids and not isinstance(left_family, str):
        return True
    if not right_ids and not isinstance(right_family, str):
        return True
    return False


def _proof_status_for(proof: Mapping[str, Any]) -> str:
    status = proof.get("status")
    if status == "checked":
        return "verified"
    if status in {"refuted", "quarantined"}:
        return "rejected"
    if status in {"sketch", "candidate", "stale"}:
        return "stated"
    return "none"


def _rule_status_for(state: str) -> str:
    if state == "active":
        return "active"
    if state == "deprecated":
        return "deprecated"
    if state in {"revoked", "archived"}:
        return "revoked"
    if state in {"blocked", "rejected"}:
        return "blocked"
    # Proposed/hashed/validated/tested/approved/committed/rolled_back are
    # intentionally "proposed": a snapshot must not be able to use a rule
    # that has not been activated by this authority.
    return "proposed"


def _initial_axes(*, level: int, truth_claim: str, claimed_validity: str,
                  content_digest: str, proposer: str, tick: int) -> dict[str, Any]:
    return {
        "truth": {
            "status": "unknown",
            "claim": truth_claim,
            "basis": [],
        },
        "validity": {
            "claimed": claimed_validity,
            "earned": "V0",
            "basis": list(_INITIAL_VALIDITY_BASIS),
            "stale": False,
        },
        "proof": {
            "status": "none",
            "proof_digest": None,
            "checker_digest": None,
            "trusted": False,
        },
        "lifecycle": {
            "state": "proposed",
            "version": 1,
            "generation": 1,
            "isolated": level == 3,
            "active_version": None,
            "rollback_to": None,
            "proposal_digest": content_digest,
            "proposer": proposer,
            "validator": None,
            "tester": None,
            "approver": None,
            "committer": None,
            "activator": None,
            "updated_tick": tick,
        },
        "utility": {
            "status": "unknown",
            "score": None,
            "outcomes": [],
            "scope": None,
        },
    }


# ---------------------------------------------------------------------------
# public value records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleProposal:
    """A proposal is content-addressed; provenance and time are excluded."""

    rule_id: str
    level: int
    contract: dict[str, Any]
    scope: dict[str, Any] = field(default_factory=dict)
    claim_class: str = "heuristic"
    statement: dict[str, Any] = field(default_factory=dict)
    theory: dict[str, Any] = field(default_factory=dict)
    truth_claim: str = "open"
    claimed_validity: str = "V0"
    proof_digest: str | None = None
    checker: str | None = None
    supersedes: str | None = None
    new_evidence_digest: str | None = None


@dataclass(frozen=True)
class ExperimentOutcome:
    """Utility-only evidence.  It is never a validity or proof record."""

    source: str
    outcome: str
    scope: dict[str, Any] = field(default_factory=dict)
    sample_size: int = 0
    seeds: tuple[str, ...] = ()
    data_digest: str | None = None
    evidence_digest: str | None = None
    synthetic: bool = False
    underpowered: bool = False
    score: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "outcome": self.outcome,
            "scope": dict(self.scope),
            "sample_size": self.sample_size,
            "seeds": list(self.seeds),
            "data_digest": self.data_digest,
            "evidence_digest": self.evidence_digest,
            "synthetic": self.synthetic,
            "underpowered": self.underpowered,
            "score": self.score,
        }


@dataclass(frozen=True)
class RuleAxes:
    truth: dict[str, Any]
    validity: dict[str, Any]
    proof: dict[str, Any]
    lifecycle: dict[str, Any]
    utility: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "truth": dict(self.truth),
            "validity": dict(self.validity),
            "proof": dict(self.proof),
            "lifecycle": dict(self.lifecycle),
            "utility": dict(self.utility),
        }

    @property
    def state(self) -> str:
        return str(self.lifecycle.get("state", ""))


@dataclass(frozen=True)
class LifecycleRecord:
    """One stable view over an immutable rule version plus its evidence."""

    rule: MathRule
    axes: RuleAxes
    evidence: dict[str, Any]
    duplicate: bool = False
    mapping: dict[str, Any] | None = None

    @property
    def rule_id(self) -> str:
        return self.rule.rule_id

    @property
    def version(self) -> int:
        return self.rule.version

    @property
    def state(self) -> str:
        return self.axes.state

    @property
    def active_version(self) -> int | None:
        value = self.axes.lifecycle.get("active_version")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": LEARNING_SCHEMA,
            "rule": self.rule.to_dict(),
            "axes": self.axes.to_dict(),
            "evidence": dict(self.evidence),
            "duplicate": self.duplicate,
            "mapping": None if self.mapping is None else dict(self.mapping),
        }


# ---------------------------------------------------------------------------
# service
# ---------------------------------------------------------------------------


class MathLearningService:
    """Rule discovery, validation, promotion, and evidence authority."""

    def __init__(self, store: MathStore, *,
                 trusted_checkers: Iterable[str] = (),
                 level0_rules: Iterable[MathRule] = (),
                 max_test_cases: int = 4096,
                 authorizer: MathAuthorizer | None = None,
                 principal: Principal | None = None) -> None:
        if not isinstance(store, MathStore):
            raise LearningConfigError("store must be a MathStore")
        if authorizer is not None and not isinstance(authorizer, MathAuthorizer):
            raise LearningConfigError(
                "authorizer must be a MathAuthorizer or None"
            )
        if principal is not None and not isinstance(principal, Principal):
            raise LearningConfigError("principal must be a Principal or None")
        self.store = store
        self.authorizer = authorizer
        self.principal = principal
        checkers = set()
        for checker in trusted_checkers:
            checkers.add(_require_text(checker, "trusted checker", maximum=256))
        self.trusted_checkers = frozenset(checkers)
        self.max_test_cases = _require_int(
            max_test_cases, "max_test_cases", minimum=1, maximum=65536,
        )
        self._level0: dict[str, dict[str, Any]] = {}
        if isinstance(level0_rules, MathRule):
            level0_rules = (level0_rules,)
        for rule in level0_rules:
            self.register_level0(rule)

    # -- authorization ------------------------------------------------------

    def _authorize(self, action: str,
                   context: Mapping[str, Any] | None = None, *,
                   actor: str | None = None
                   ) -> AuthorizationDecision | None:
        """Fail closed before a lifecycle mutation when policy is configured.

        With no authorizer the service keeps its legacy behavior and returns
        ``None``.  With an authorizer, a missing/revoked/denied principal raises
        :class:`LearningAuthorizationDenied` before any version, mapping, or
        event is written.
        """
        if self.authorizer is None:
            return None
        if self.principal is None:
            raise LearningAuthorizationDenied(
                "PRINCIPAL_REQUIRED", action=action,
            )
        request_context = dict(context or {})
        if actor is not None:
            request_context.setdefault("actor", actor)
        decision = self.authorizer.authorize(
            self.principal, action, context=request_context,
        )
        if not decision.allowed:
            raise LearningAuthorizationDenied(
                decision.reason,
                principal_id=decision.principal_id,
                action=decision.action,
                decision=decision,
            )
        return decision

    # -- level-0 baseline ---------------------------------------------------

    def register_level0(self, rule: MathRule) -> MathRule:
        """Pin an existing level-0 rule digest without mutating the store."""
        if not isinstance(rule, MathRule):
            raise LearningConfigError("level0_rules entries must be MathRule")
        if rule.level != 0:
            raise Level0ImmutableError("registered level-0 rules must be level 0")
        baseline = {
            "version": rule.version,
            "digest": digest_object(rule.to_dict()),
        }
        existing = self._level0.get(rule.rule_id)
        if existing is not None and existing != baseline:
            raise Level0ImmutableError(
                f"level-0 rule {rule.rule_id!r} is already pinned"
            )
        self._level0[rule.rule_id] = baseline
        return rule

    def level0_baseline(self, rule_id: str) -> dict[str, Any] | None:
        return None if rule_id not in self._level0 else dict(self._level0[rule_id])

    def _assert_not_level0(self, rule_id: str) -> None:
        if rule_id in self._level0:
            raise Level0ImmutableError(
                f"level-0 rule {rule_id!r} is immutable"
            )
        try:
            meta = self.store.get_rule_meta(rule_id)
        except MathReferenceError:
            return
        for version in range(1, int(meta["current_version"]) + 1):
            rule = self.store.get_rule(rule_id, version)
            if rule.level == 0:
                raise Level0ImmutableError(
                    f"level-0 rule {rule_id!r} is immutable"
                )

    # -- small reads --------------------------------------------------------

    def _head(self, rule_id: str) -> tuple[MathRule, dict[str, Any]]:
        _require_text(rule_id, "rule_id", maximum=160)
        try:
            meta = self.store.get_rule_meta(rule_id)
        except MathReferenceError as exc:
            raise MathLearningError(f"unknown rule {rule_id!r}") from exc
        rule = self.store.get_rule(rule_id, int(meta["current_version"]))
        return rule, meta

    def _history(self, rule_id: str) -> list[MathRule]:
        try:
            meta = self.store.get_rule_meta(rule_id)
        except MathReferenceError:
            return []
        rules: list[MathRule] = []
        for version in range(1, int(meta["current_version"]) + 1):
            try:
                rules.append(self.store.get_rule(rule_id, version))
            except MathReferenceError:
                continue
        return rules

    @staticmethod
    def _axes_of(rule: MathRule) -> RuleAxes:
        axes = _axes_document(rule.contract.get("axes"))
        try:
            return RuleAxes(
                truth=_canonical_copy(axes["truth"], "truth"),
                validity=_canonical_copy(axes["validity"], "validity"),
                proof=_canonical_copy(axes["proof"], "proof"),
                lifecycle=_canonical_copy(axes["lifecycle"], "lifecycle"),
                utility=_canonical_copy(axes["utility"], "utility"),
            )
        except MathLearningError:
            raise
        except (TypeError, ValueError) as exc:
            raise MathLearningError("rule axes are malformed") from exc

    @staticmethod
    def _proposal_of(rule: MathRule) -> dict[str, Any] | None:
        raw = rule.contract.get("proposal")
        if not isinstance(raw, Mapping):
            return None
        digest = raw.get("content_digest")
        if not isinstance(digest, str):
            return None
        return dict(raw)

    def _record(self, rule: MathRule, evidence: dict[str, Any], *,
                duplicate: bool = False,
                mapping: dict[str, Any] | None = None) -> LifecycleRecord:
        return LifecycleRecord(
            rule=rule,
            axes=self._axes_of(rule),
            evidence=evidence,
            duplicate=duplicate,
            mapping=mapping,
        )

    def axes(self, rule_id: str, version: int | None = None) -> RuleAxes:
        rule = self.store.get_rule(rule_id, version)
        return self._axes_of(rule)

    def lifecycle(self, rule_id: str, version: int | None = None) -> dict[str, Any]:
        return dict(self.axes(rule_id, version).lifecycle)

    def active_mapping_id(self, rule_id: str) -> str:
        return ACTIVE_MAPPING_PREFIX + rule_id

    def _active_mappings(self) -> list[dict[str, Any]]:
        mappings = self.store.list_mappings(object_type="rule", limit=65536)
        return [
            mapping for mapping in mappings
            if str(mapping.get("mapping_id", "")).startswith(
                ACTIVE_MAPPING_PREFIX
            )
        ]

    def active_rules(self, *, include_isolated: bool = False
                     ) -> tuple[MathRule, ...]:
        """Rules whose explicit active pointer resolves to an active version."""
        active: list[MathRule] = []
        for mapping in self._active_mappings():
            rule = self.store.get_rule(
                str(mapping["object_id"]), int(mapping["current_version"]),
            )
            if self._proposal_of(rule) is None:
                # A rule stored by another authority (for example an
                # immutable level-0 axiom) is not a lifecycle-managed rule.
                continue
            if rule.status != "active":
                continue
            axes = self._axes_of(rule)
            if axes.lifecycle.get("state") != "active":
                continue
            if rule.level == 3 and not include_isolated:
                continue
            active.append(rule)
        active.sort(key=lambda item: (item.rule_id, item.version))
        return tuple(active)

    def rule_snapshot_id(self, *, include_isolated: bool = False) -> str:
        snapshot = MathSnapshot(
            snapshot_id="snp:learning-active",
            rules=self.active_rules(include_isolated=include_isolated),
        )
        return snapshot.rule_snapshot_id

    # -- proposal normalization --------------------------------------------

    def _normalise_proposal(self, proposal: RuleProposal, proposer: str,
                            tick: int) -> dict[str, Any]:
        if not isinstance(proposal, RuleProposal):
            raise MathLearningError("proposal must be a RuleProposal")
        _require_text(proposal.rule_id, "rule_id", maximum=160)
        if isinstance(proposal.level, bool) or proposal.level not in (0, 1, 2, 3):
            raise MathLearningError("level must be one of 0, 1, 2, 3")
        if proposal.level == 0:
            raise Level0ImmutableError("level-0 rules cannot be learned")
        if not isinstance(proposal.claim_class, str) or \
                proposal.claim_class not in CLAIM_CLASSES:
            raise MathLearningError(
                f"claim_class must be one of: {', '.join(sorted(CLAIM_CLASSES))}"
            )
        if not isinstance(proposal.truth_claim, str) or \
                proposal.truth_claim not in TRUTH_CLAIMS:
            raise MathLearningError(
                f"truth_claim must be one of: {', '.join(sorted(TRUTH_CLAIMS))}"
            )
        if proposal.claimed_validity not in VALIDITY_LEVELS:
            raise MathLearningError("claimed_validity must be V0..V3")

        contract = _mapping(proposal.contract, "contract")
        reserved = sorted(_RESERVED_CONTRACT_KEYS & set(contract))
        if reserved:
            raise ProposalRejected(
                "client may not set authority axis key(s): "
                + ", ".join(reserved)
            )
        if proposal.statement and "statement" in contract:
            raise ProposalRejected("statement must be passed explicitly or in contract")
        if proposal.theory and "theory" in contract:
            raise ProposalRejected("theory must be passed explicitly or in contract")

        scope = _mapping(proposal.scope, "scope")
        statement = _mapping(proposal.statement, "statement") \
            if proposal.statement else {}
        theory = _mapping(proposal.theory, "theory") if proposal.theory else {}
        proof_digest = _require_digest(
            proposal.proof_digest, "proof_digest", allow_none=True,
        )
        checker = proposal.checker
        if checker is not None:
            _require_text(checker, "checker", maximum=256)
        if (proof_digest is None) != (checker is None):
            raise ProposalRejected(
                "proof_digest and checker must be supplied together"
            )
        supersedes = _require_digest(
            proposal.supersedes, "supersedes", allow_none=True,
        )
        new_evidence = _require_digest(
            proposal.new_evidence_digest, "new_evidence_digest",
            allow_none=True,
        )

        content = {
            "schema": LEARNING_SCHEMA,
            "rule_id": proposal.rule_id,
            "level": proposal.level,
            "claim_class": proposal.claim_class,
            "contract": contract,
            "scope": scope,
            "statement": statement,
            "theory": theory,
            "truth_claim": proposal.truth_claim,
            "claimed_validity": proposal.claimed_validity,
        }
        content_digest = digest_object(content)
        return {
            "proposal": proposal,
            "rule_id": proposal.rule_id,
            "level": proposal.level,
            "claim_class": proposal.claim_class,
            "contract": contract,
            "scope": scope,
            "statement": statement,
            "theory": theory,
            "truth_claim": proposal.truth_claim,
            "claimed_validity": proposal.claimed_validity,
            "proof_digest": proof_digest,
            "checker": checker,
            "supersedes": supersedes,
            "new_evidence_digest": new_evidence,
            "content": content,
            "content_digest": content_digest,
            "statement_digest": (
                digest_object(statement) if statement else None
            ),
            "proposer": proposer,
            "tick": tick,
        }

    def _initial_rule(self, normalised: Mapping[str, Any], *,
                      version: int, generation: int) -> MathRule:
        contract = dict(normalised["contract"])
        if normalised["statement"]:
            contract["statement"] = dict(normalised["statement"])
        if normalised["theory"]:
            contract["theory"] = dict(normalised["theory"])
        axes = _initial_axes(
            level=normalised["level"],
            truth_claim=normalised["truth_claim"],
            claimed_validity=normalised["claimed_validity"],
            content_digest=normalised["content_digest"],
            proposer=normalised["proposer"],
            tick=normalised["tick"],
        )
        axes["lifecycle"]["version"] = version
        axes["lifecycle"]["generation"] = generation
        proposal_record = {
            "schema": LEARNING_SCHEMA,
            "content_digest": normalised["content_digest"],
            "statement_digest": normalised["statement_digest"],
            "claim_class": normalised["claim_class"],
            "truth_claim": normalised["truth_claim"],
            "claimed_validity": normalised["claimed_validity"],
            "proposer": normalised["proposer"],
            "supersedes": normalised["supersedes"],
            "new_evidence_digest": normalised["new_evidence_digest"],
        }
        if normalised["proof_digest"] is not None:
            proposal_record["proof_candidate"] = {
                "proof_digest": normalised["proof_digest"],
                "checker": normalised["checker"],
            }
        contract["proposal"] = proposal_record
        contract["axes"] = axes
        contract["lifecycle"] = _canonical_copy(axes["lifecycle"], "lifecycle")
        try:
            return MathRule(
                rule_id=normalised["rule_id"],
                version=version,
                level=normalised["level"],
                contract=contract,
                proof_status=_proof_status_for(axes["proof"]),
                status="proposed",
                scope=dict(normalised["scope"]),
            )
        except MathObjectError as exc:
            raise ProposalRejected(f"invalid rule proposal: {exc}") from exc

    # -- event helpers ------------------------------------------------------

    def _append_learning_event(self, rule: MathRule, *, action: str,
                               actor: str, state: str, tick: int,
                               generation: int, event_type: str = "rule",
                               reason: str = "",
                               payload_extra: Mapping[str, Any] | None = None
                               ) -> dict[str, Any]:
        axes = self._axes_of(rule)
        payload = {
            "layer": LEARNING_SCHEMA,
            "action": action,
            "state": state,
            "proposal_digest": axes.lifecycle.get("proposal_digest"),
            "rule_version": rule.version,
            "generation": generation,
            "actor": actor,
            "truth": axes.truth.get("status"),
            "validity_earned": axes.validity.get("earned"),
            "proof": axes.proof.get("status"),
            "isolated": axes.lifecycle.get("isolated"),
            "reason": reason,
        }
        if payload_extra:
            payload.update(_canonical_copy(dict(payload_extra), "event payload"))
        return self.store.append_event(
            event_type,
            "rule",
            rule.rule_id,
            version=rule.version,
            generation=generation,
            digest=_rule_digest(rule),
            actor=actor,
            payload=payload,
            tick=tick,
        )

    def _evidence_view(self, event: Mapping[str, Any]) -> dict[str, Any]:
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            payload = {}
        return {
            "evidence_id": event.get("event_id"),
            "event_seq": event.get("event_seq"),
            "event_type": event.get("event_type"),
            "action": payload.get("action"),
            "state": payload.get("state"),
            "actor": payload.get("actor"),
            "rule_version": payload.get("rule_version"),
            "generation": payload.get("generation"),
            "proposal_digest": payload.get("proposal_digest"),
            "reason": payload.get("reason"),
            "truth": payload.get("truth"),
            "validity_earned": payload.get("validity_earned"),
            "proof": payload.get("proof"),
            "isolated": payload.get("isolated"),
        }

    def _learning_events(self, rule_id: str) -> list[dict[str, Any]]:
        events = self.store.list_events(
            object_type="rule", object_id=rule_id, limit=65536,
        )
        matches = []
        for event in events:
            payload = event.get("payload")
            if isinstance(payload, Mapping) and \
                    payload.get("layer") == LEARNING_SCHEMA:
                matches.append(event)
        return matches

    def _deny(self, rule_id: str, *, action: str, actor: str, reason: str,
              tick: int) -> None:
        """Audit a denied attempt without changing lifecycle state."""
        try:
            head, meta = self._head(rule_id)
            axes = self._axes_of(head)
            self._append_learning_event(
                head, action="denied_" + action, actor=actor,
                state=axes.state, tick=tick,
                generation=int(meta["generation"]), reason=reason,
            )
        except MathReferenceError:
            return
        except MathLearningError:
            return

    # -- transition core ----------------------------------------------------

    def _transition(self, rule_id: str, *, action: str, actor: str,
                    state: str, tick: int,
                    expected_generation: int | None = None,
                    event_type: str = "rule",
                    status: str | None = None,
                    level: int | None = None,
                    axes_mutator: Any = None,
                    lifecycle_mutator: Any = None,
                    contract_mutator: Any = None,
                    certificate_digest: Any = _UNSET,
                    reason: str = "",
                    payload_extra: Mapping[str, Any] | None = None
                    ) -> tuple[MathRule, dict[str, Any], int]:
        head, meta = self._head(rule_id)
        if expected_generation is not None:
            _require_int(expected_generation, "expected_generation")
            if expected_generation != int(meta["generation"]):
                raise StaleGenerationError(
                    f"rule {rule_id!r} is at generation {meta['generation']}, "
                    f"not {expected_generation}"
                )
        contract = _mapping(head.contract, "rule contract")
        axes = _axes_document(contract["axes"])
        new_version = head.version + 1
        new_generation = int(meta["generation"]) + 1
        if axes_mutator is not None:
            axes_mutator(axes)
        lifecycle = axes["lifecycle"]
        lifecycle.update({
            "state": state,
            "version": new_version,
            "generation": new_generation,
            "updated_tick": tick,
        })
        if lifecycle_mutator is not None:
            lifecycle_mutator(axes, lifecycle, new_version, new_generation)
        axes["lifecycle"] = lifecycle
        contract["axes"] = axes
        contract["lifecycle"] = _canonical_copy(lifecycle, "lifecycle")
        if contract_mutator is not None:
            contract_mutator(contract)
        new_level = head.level if level is None else level
        new_status = _rule_status_for(state) if status is None else status
        new_certificate = head.certificate_digest
        if certificate_digest is not _UNSET:
            new_certificate = _require_digest(
                certificate_digest, "certificate_digest", allow_none=True,
            )
        try:
            rule = MathRule(
                rule_id=head.rule_id,
                version=new_version,
                level=new_level,
                contract=contract,
                proof_status=_proof_status_for(axes["proof"]),
                status=new_status,
                scope=head.scope,
                certificate_digest=new_certificate,
            )
            stored = self.store.put_rule(
                rule,
                expected_version=head.version,
                expected_generation=int(meta["generation"]),
                tick=tick,
            )
        except StaleGenerationError:
            raise
        except MathObjectError as exc:
            raise ProposalRejected(f"invalid lifecycle rule: {exc}") from exc
        except MathStoreError as exc:
            raise MathLearningError(str(exc)) from exc
        evidence = self._append_learning_event(
            stored, action=action, actor=actor, state=state, tick=tick,
            generation=new_generation, event_type=event_type, reason=reason,
            payload_extra=payload_extra,
        )
        return stored, evidence, new_generation

    # -- active mapping -----------------------------------------------------

    def _set_active_mapping(self, rule: MathRule, *, tick: int,
                            expected_generation: int | None = None
                            ) -> dict[str, Any]:
        mapping_id = self.active_mapping_id(rule.rule_id)
        try:
            current = self.store.get_mapping(mapping_id)
        except MathReferenceError:
            expected_version = 0
            expected_generation = 0
        else:
            if expected_generation is not None and \
                    int(current["generation"]) != expected_generation:
                raise StaleGenerationError(
                    f"active mapping {mapping_id!r} is at generation "
                    f"{current['generation']}, not {expected_generation}"
                )
            expected_version = int(current["current_version"])
            expected_generation = int(current["generation"])
        return self.store.set_mapping(
            mapping_id,
            object_type="rule",
            object_id=rule.rule_id,
            version=rule.version,
            digest=_rule_digest(rule),
            expected_version=expected_version,
            expected_generation=expected_generation,
            tick=tick,
        )

    def _try_sync_active_mapping(self, rule: MathRule, *, tick: int
                                 ) -> dict[str, Any] | None:
        """Move an existing active pointer to a new active/terminal version."""
        try:
            current = self.store.get_mapping(self.active_mapping_id(rule.rule_id))
        except MathReferenceError:
            return None
        return self._set_active_mapping(
            rule, tick=tick,
            expected_generation=int(current["generation"]),
        )

    # -- contradiction ------------------------------------------------------

    @staticmethod
    def _contradiction(candidate: MathRule, active: Iterable[MathRule]
                       ) -> dict[str, Any] | None:
        candidate_isolated = candidate.level == 3
        live = [
            rule for rule in active
            if rule.rule_id != candidate.rule_id
            and (rule.level == 3) == candidate_isolated
            and _scopes_overlap(candidate, rule)
        ]
        live.sort(key=lambda item: (item.rule_id, item.version))
        if not live:
            return None
        claims: dict[str, list[tuple[MathRule, Any]]] = {}
        requires: dict[str, list[MathRule]] = {}
        forbids: dict[str, list[MathRule]] = {}
        for rule in [candidate, *live]:
            for key, value in _claims(rule).items():
                claims.setdefault(key, []).append((rule, value))
            for token in _tokens(rule, "requires"):
                requires.setdefault(token, []).append(rule)
            for token in _tokens(rule, "forbids"):
                forbids.setdefault(token, []).append(rule)
        for key, values in claims.items():
            first = values[0][1]
            for rule, value in values[1:]:
                if value != first:
                    affected = sorted({values[0][0].rule_id, rule.rule_id})
                    return {
                        "reason": "CONTRADICTION:" + ",".join(affected),
                        "rule_ids": affected,
                        "claim": key,
                    }
        for token in sorted(set(requires) & set(forbids)):
            affected = sorted({
                requires[token][0].rule_id,
                forbids[token][0].rule_id,
            })
            return {
                "reason": "CONTRADICTION:" + ",".join(affected),
                "rule_ids": affected,
                "token": token,
            }
        by_key = {(rule.rule_id, rule.version): rule for rule in live}
        for rule in [candidate, *live]:
            targets = rule.contract.get("contradicts")
            if targets is None:
                continue
            if isinstance(targets, (str, Mapping)):
                targets = [targets]
            if not isinstance(targets, (tuple, list)):
                continue
            for target in targets:
                target_id = target.get("rule_id", target.get("id")) \
                    if isinstance(target, Mapping) else target
                if not isinstance(target_id, str):
                    continue
                target_version = target.get("version") \
                    if isinstance(target, Mapping) else None
                matches = [
                    item for (rule_id, version), item in by_key.items()
                    if rule_id == target_id
                    and (target_version is None or version == target_version)
                ]
                if matches:
                    affected = sorted({rule.rule_id, target_id})
                    return {
                        "reason": "CONTRADICTION:" + ",".join(affected),
                        "rule_ids": affected,
                        "explicit": True,
                    }
        return None

    def _candidate_rule(self, head: MathRule, *,
                        state: str = "validated") -> MathRule:
        contract = _mapping(head.contract, "rule contract")
        axes = _axes_document(contract["axes"])
        axes["lifecycle"]["state"] = state
        contract["axes"] = axes
        contract["lifecycle"] = _canonical_copy(axes["lifecycle"], "lifecycle")
        return MathRule(
            rule_id=head.rule_id,
            version=head.version + 1,
            level=head.level,
            contract=contract,
            proof_status=head.proof_status,
            status="proposed",
            scope=head.scope,
            certificate_digest=head.certificate_digest,
        )

    def _validate_snapshot(self, candidate: MathRule) -> str:
        active = [
            rule for rule in self.active_rules(include_isolated=True)
            if rule.rule_id != candidate.rule_id
        ]
        try:
            snapshot = MathSnapshot(
                snapshot_id="snp:learning-validation",
                rules=tuple(active + [candidate]),
            )
            MathValidityEngine(snapshot)
        except (MathSnapshotError, MathValidityError, MathObjectError) as exc:
            raise ProposalRejected(
                f"structural validation failed: {exc}"
            ) from exc
        return snapshot.rule_snapshot_id

    # -- propose / hash -----------------------------------------------------

    def propose(self, proposal: RuleProposal, *, proposer: str,
                expected_generation: int | None = None,
                tick: int = 0) -> LifecycleRecord:
        _require_text(proposer, "proposer", maximum=128)
        _require_int(tick, "tick")
        context_rule_id = proposal.rule_id \
            if isinstance(proposal, RuleProposal) else None
        self._authorize(
            PROPOSE,
            {
                "rule_id": context_rule_id,
                "proposer_id": proposer,
            },
            actor=proposer,
        )
        normalised = self._normalise_proposal(proposal, proposer, tick)
        rule_id = normalised["rule_id"]
        self._assert_not_level0(rule_id)

        history = self._history(rule_id)
        if history:
            head = history[-1]
            meta = self.store.get_rule_meta(rule_id)
            head_proposal = self._proposal_of(head)
            if head_proposal is None:
                raise DuplicateProposalConflict(
                    f"rule {rule_id!r} already exists outside the learning "
                    "lifecycle"
                )
            head_digest = str(head_proposal["content_digest"])
            head_axes = self._axes_of(head)

            if head_digest == normalised["content_digest"]:
                prior_evidence = head_proposal.get("new_evidence_digest")
                if head_axes.state in NEGATIVE_STATES:
                    allowed_retry = (
                        normalised["supersedes"] == normalised["content_digest"]
                        and normalised["new_evidence_digest"] is not None
                        and normalised["new_evidence_digest"] != prior_evidence
                    )
                    if not allowed_retry:
                        self._deny(
                            rule_id, action="propose", actor=proposer,
                            reason="NEGATIVE_MEMORY", tick=tick,
                        )
                        events = self._learning_events(rule_id)
                        raise NegativeMemoryError(
                            f"unchanged proposal {rule_id!r} was previously "
                            f"{head_axes.state}",
                            record=self._record(
                                head, events[-1] if events else {},
                            ),
                            reason="NEGATIVE_MEMORY",
                        )
                else:
                    # Exact duplicate: no new immutable version is written.
                    evidence = self._append_learning_event(
                        head, action="duplicate_proposal", actor=proposer,
                        state=head_axes.state, tick=tick,
                        generation=int(meta["generation"]),
                        reason="DUPLICATE_CONTENT",
                    )
                    return self._record(
                        head, evidence, duplicate=True,
                        mapping=self._mapping_if_present(rule_id),
                    )
            else:
                if head_axes.state not in {
                    "deprecated", "revoked", "archived", "rejected",
                    "blocked", "rolled_back",
                }:
                    self._deny(
                        rule_id, action="propose", actor=proposer,
                        reason="RULE_ID_CONTENT_CONFLICT", tick=tick,
                    )
                    raise DuplicateProposalConflict(
                        f"rule {rule_id!r} already names different content "
                        f"and is {head_axes.state}"
                    )
                if normalised["supersedes"] != head_digest:
                    raise DuplicateProposalConflict(
                        f"superseding {rule_id!r} requires supersedes="
                        f"{head_digest}"
                    )
                if normalised["level"] != head.level:
                    raise SelfApprovalDenied(
                        "level changes require the separate promote operation"
                    )
            expected_version = head.version
            expected_generation = (
                int(meta["generation"]) if expected_generation is None
                else _require_int(expected_generation, "expected_generation")
            )
            if expected_generation != int(meta["generation"]):
                raise StaleGenerationError(
                    f"rule {rule_id!r} is at generation {meta['generation']}, "
                    f"not {expected_generation}"
                )
            version = head.version + 1
            generation = int(meta["generation"]) + 1
        else:
            expected_version = 1
            expected_generation = (
                1 if expected_generation is None
                else _require_int(expected_generation, "expected_generation")
            )
            if expected_generation not in (0, 1):
                raise StaleGenerationError(
                    "a new rule CAS must expect generation 0 or 1"
                )
            version = 1
            generation = 1

        rule = self._initial_rule(
            normalised, version=version, generation=generation,
        )
        try:
            stored = self.store.put_rule(
                rule,
                expected_version=expected_version,
                expected_generation=expected_generation,
                tick=tick,
            )
        except StaleGenerationError:
            raise
        except MathStoreError as exc:
            raise MathLearningError(str(exc)) from exc
        evidence = self._append_learning_event(
            stored, action="propose", actor=proposer, state="proposed",
            tick=tick, generation=generation, event_type="propose",
        )
        return self._record(
            stored, evidence,
            mapping=self._mapping_if_present(rule_id),
        )

    def hash_proposal(self, rule_id: str, *, actor: str | None = None,
                      expected_generation: int | None = None,
                      tick: int = 0) -> LifecycleRecord:
        head, _ = self._head(rule_id)
        axes = self._axes_of(head)
        actor = actor or str(axes.lifecycle.get("proposer") or "")
        _require_text(actor, "actor", maximum=128)
        self._authorize(
            PROPOSE,
            {
                "rule_id": rule_id,
                "proposer_id": axes.lifecycle.get("proposer"),
            },
            actor=actor,
        )
        if axes.state != "proposed":
            raise LifecycleStateError(
                f"rule {rule_id!r} is {axes.state}, not proposed"
            )
        stored, evidence, _ = self._transition(
            rule_id, action="hash", actor=actor, state="hashed", tick=tick,
            expected_generation=expected_generation,
            lifecycle_mutator=lambda axes, lifecycle, version, generation: (
                lifecycle.update({"proposal_hash": axes["lifecycle"].get(
                    "proposal_digest")})
            ),
        )
        return self._record(stored, evidence)

    # -- validate / test / approve / commit / activate ----------------------

    def validate(self, rule_id: str, *, validator: str,
                 expected_generation: int | None = None,
                 proof_digest: str | None = None,
                 checker: str | None = None,
                 tick: int = 0) -> LifecycleRecord:
        _require_text(validator, "validator", maximum=128)
        _require_int(tick, "tick")
        head, _ = self._head(rule_id)
        self._assert_not_level0(rule_id)
        axes = self._axes_of(head)
        self._authorize(
            VALIDATE,
            {
                "rule_id": rule_id,
                "proposer_id": axes.lifecycle.get("proposer"),
                "validator_id": validator,
            },
            actor=validator,
        )
        if axes.state != "hashed":
            raise LifecycleStateError(
                f"rule {rule_id!r} is {axes.state}, not hashed"
            )
        proposer = str(axes.lifecycle.get("proposer") or "")
        if validator == proposer:
            self._deny(
                rule_id, action="validate", actor=validator,
                reason="SELF_VALIDATION", tick=tick,
            )
            raise SelfApprovalDenied(
                "the proposer may not validate its own rule"
            )

        candidate = self._candidate_rule(head)
        try:
            snapshot_id = self._validate_snapshot(candidate)
        except ProposalRejected as exc:
            self._deny(
                rule_id, action="validate", actor=validator,
                reason=exc.reason or "STRUCTURAL_VALIDATION", tick=tick,
            )
            raise
        contradiction = self._contradiction(
            candidate, self.active_rules(include_isolated=True),
        )
        if contradiction is not None:
            stored, evidence, _ = self._transition(
                rule_id, action="contradiction", actor=validator,
                state="blocked", tick=tick,
                expected_generation=expected_generation,
                status="blocked", reason=contradiction["reason"],
                payload_extra=contradiction,
            )
            raise ContradictionError(
                contradiction["reason"],
                record=self._record(stored, evidence),
                affected=tuple(contradiction["rule_ids"]),
            )

        proposal = self._proposal_of(head) or {}
        proof_candidate = proposal.get("proof_candidate")
        if proof_digest is None and isinstance(proof_candidate, Mapping):
            proof_digest = proof_candidate.get("proof_digest")
            checker = proof_candidate.get("checker")
        proof_digest = _require_digest(
            proof_digest, "proof_digest", allow_none=True,
        )
        if checker is not None:
            _require_text(checker, "checker", maximum=256)
        if (proof_digest is None) != (checker is None):
            raise ProposalRejected(
                "proof_digest and checker must be supplied together"
            )
        trusted = (
            proof_digest is not None
            and checker is not None
            and checker in self.trusted_checkers
            and validator != proposer
        )
        if proof_digest is not None and not trusted and validator == proposer:
            raise SelfApprovalDenied("the proposer may not verify its own proof")

        validation_digest = digest_object({
            "rule_id": rule_id,
            "version": head.version,
            "proposal_digest": axes.lifecycle.get("proposal_digest"),
            "validator": validator,
            "snapshot_id": snapshot_id,
            "proof_digest": proof_digest,
            "checker": checker,
            "trusted": trusted,
            "tick": tick,
        })

        def mutate_axes(values: dict[str, Any]) -> None:
            validity = values["validity"]
            validity["earned"] = "V3" if trusted else "V1"
            validity["basis"] = [
                "schema", "structural", "snapshot:" + snapshot_id,
            ]
            validity["stale"] = False
            if proof_digest is not None:
                values["proof"] = {
                    "status": "checked" if trusted else "candidate",
                    "proof_digest": proof_digest,
                    "checker_digest": sha256_text(checker or ""),
                    "trusted": trusted,
                }
            if trusted:
                truth_status = (
                    "definitional"
                    if proposal.get("claim_class") == "definition"
                    else "theorem"
                )
                values["truth"] = {
                    "status": truth_status,
                    "claim": values["truth"].get("claim", "open"),
                    "basis": ["proof:" + str(proof_digest)],
                }
            values["lifecycle"]["validator"] = validator
            values["lifecycle"]["validation_digest"] = validation_digest

        stored, evidence, _ = self._transition(
            rule_id, action="validate", actor=validator, state="validated",
            tick=tick, expected_generation=expected_generation,
            axes_mutator=mutate_axes,
            certificate_digest=(proof_digest if trusted else _UNSET),
            payload_extra={
                "validator": validator,
                "snapshot_id": snapshot_id,
                "validation_digest": validation_digest,
                "proof_digest": proof_digest,
                "checker": checker,
                "proof_trusted": trusted,
            },
        )
        return self._record(stored, evidence)

    def test(self, rule_id: str, *, tester: str,
             cases: Iterable[Mapping[str, Any]], harness: str,
             bounded: bool = True,
             expected_generation: int | None = None,
             tick: int = 0) -> LifecycleRecord:
        _require_text(tester, "tester", maximum=128)
        _require_text(harness, "harness", maximum=256)
        _require_bool(bounded, "bounded")
        _require_int(tick, "tick")
        head, _ = self._head(rule_id)
        axes = self._axes_of(head)
        self._authorize(
            TEST,
            {
                "rule_id": rule_id,
                "proposer_id": axes.lifecycle.get("proposer"),
                "validator_id": axes.lifecycle.get("validator"),
                "tester_id": tester,
            },
            actor=tester,
        )
        if axes.state != "validated":
            raise LifecycleStateError(
                f"rule {rule_id!r} is {axes.state}, not validated"
            )
        proposer = str(axes.lifecycle.get("proposer") or "")
        validator = axes.lifecycle.get("validator")
        if tester == proposer:
            self._deny(
                rule_id, action="test", actor=tester,
                reason="SELF_VALIDATION", tick=tick,
            )
            raise SelfApprovalDenied(
                "the proposer may not test its own rule"
            )
        if tester == validator:
            self._deny(
                rule_id, action="test", actor=tester,
                reason="SELF_VALIDATION", tick=tick,
            )
            raise SelfApprovalDenied(
                "the validator may not also count as the independent tester"
            )
        if not bounded:
            self._deny(
                rule_id, action="test", actor=tester,
                reason="UNBOUNDED_TEST", tick=tick,
            )
            raise InconclusiveEvidence("tests must be deterministic and bounded")
        normalised = self._normalise_cases(cases)
        if not normalised:
            self._deny(
                rule_id, action="test", actor=tester,
                reason="EMPTY_TEST_SET", tick=tick,
            )
            raise InconclusiveEvidence("at least one bounded test case is required")
        failures = [case for case in normalised if case["outcome"] == "fail"]
        inconclusive = [
            case for case in normalised if case["outcome"] == "inconclusive"
        ]
        cases_digest = digest_object(normalised)
        if failures:
            stored, evidence, _ = self._transition(
                rule_id, action="test_failed", actor=tester,
                state="rejected", tick=tick,
                expected_generation=expected_generation,
                status="blocked", reason="TEST_FAILURE",
                payload_extra={
                    "harness": harness,
                    "cases_digest": cases_digest,
                    "failed": len(failures),
                    "case_count": len(normalised),
                },
            )
            raise TestFailure(
                f"{len(failures)} bounded test case(s) failed",
                record=self._record(stored, evidence),
                reason="TEST_FAILURE",
            )
        if inconclusive:
            self._deny(
                rule_id, action="test", actor=tester,
                reason="INCONCLUSIVE_TEST", tick=tick,
            )
            raise InconclusiveEvidence(
                f"{len(inconclusive)} test case(s) were inconclusive"
            )

        test_digest = digest_object({
            "harness": harness,
            "cases_digest": cases_digest,
            "case_count": len(normalised),
            "tester": tester,
            "bounded": True,
        })

        def mutate_axes(values: dict[str, Any]) -> None:
            validity = values["validity"]
            if validity.get("earned") != "V3":
                validity["earned"] = "V2"
            validity["basis"] = list(validity.get("basis") or ()) + [
                "bounded-tests:" + test_digest,
            ]
            # Testing is not proof.  The proof axis is untouched.
            values["lifecycle"]["tester"] = tester
            values["lifecycle"]["test_digest"] = test_digest

        def mutate_contract(contract: dict[str, Any]) -> None:
            evidence = contract.get("learning_evidence")
            if not isinstance(evidence, dict):
                evidence = {}
            evidence["tests"] = {
                "harness": harness,
                "case_count": len(normalised),
                "cases_digest": cases_digest,
                "test_digest": test_digest,
                "failed": 0,
                "inconclusive": 0,
                "bounded": True,
                "tester": tester,
            }
            contract["learning_evidence"] = evidence

        stored, evidence, _ = self._transition(
            rule_id, action="test", actor=tester, state="tested", tick=tick,
            expected_generation=expected_generation,
            axes_mutator=mutate_axes,
            contract_mutator=mutate_contract,
            payload_extra={
                "harness": harness,
                "cases_digest": cases_digest,
                "case_count": len(normalised),
                "test_digest": test_digest,
            },
        )
        return self._record(stored, evidence)

    def _normalise_cases(self, cases: Iterable[Mapping[str, Any]]
                         ) -> list[dict[str, Any]]:
        if isinstance(cases, Mapping):
            raise ProposalRejected("cases must be a list, not an object")
        try:
            items = list(cases)
        except TypeError as exc:
            raise ProposalRejected("cases must be iterable") from exc
        if len(items) > self.max_test_cases:
            raise InconclusiveEvidence(
                f"test set exceeds max_test_cases={self.max_test_cases}"
            )
        normalised = []
        for index, case in enumerate(items):
            if not isinstance(case, Mapping):
                raise ProposalRejected("each test case must be an object")
            expected = case.get("expected", _UNSET)
            observed = case.get("observed", _UNSET)
            expected_digest = None if expected is _UNSET \
                else digest_object(_canonical_copy(expected, "expected"))
            observed_digest = None if observed is _UNSET \
                else digest_object(_canonical_copy(observed, "observed"))
            outcome = case.get("outcome")
            if outcome is None and "passed" in case:
                passed = case.get("passed")
                if passed is True:
                    outcome = "pass"
                elif passed is False:
                    outcome = "fail"
                else:
                    outcome = "inconclusive"
            if outcome is None:
                outcome = "inconclusive"
            if not isinstance(outcome, str) or outcome not in _TEST_OUTCOMES:
                raise ProposalRejected(f"unknown test outcome: {outcome!r}")
            if expected_digest is not None and observed_digest is not None \
                    and expected_digest != observed_digest:
                outcome = "fail"
            item = {
                "index": index,
                "outcome": outcome,
                "input_digest": (
                    digest_object(_canonical_copy(case.get("inputs", {}),
                                                  "case inputs"))
                ),
                "expected_digest": expected_digest,
                "observed_digest": observed_digest,
            }
            if isinstance(case.get("case_id"), str):
                item["case_id"] = case["case_id"]
            normalised.append(item)
        return normalised

    def approve(self, rule_id: str, *, approver: str,
                expected_generation: int | None = None,
                tick: int = 0) -> LifecycleRecord:
        _require_text(approver, "approver", maximum=128)
        _require_int(tick, "tick")
        head, _ = self._head(rule_id)
        axes = self._axes_of(head)
        self._authorize(
            APPROVE,
            {
                "rule_id": rule_id,
                "proposer_id": axes.lifecycle.get("proposer"),
            },
            actor=approver,
        )
        if axes.state != "tested":
            raise LifecycleStateError(
                f"rule {rule_id!r} is {axes.state}, not tested"
            )
        proposer = str(axes.lifecycle.get("proposer") or "")
        validator = axes.lifecycle.get("validator")
        tester = axes.lifecycle.get("tester")
        if approver in {proposer, validator, tester}:
            self._deny(
                rule_id, action="approve", actor=approver,
                reason="SELF_APPROVAL", tick=tick,
            )
            raise SelfApprovalDenied(
                "approval must be independent of proposal, validation, and test"
            )
        evidence_contract = head.contract.get("learning_evidence")
        tests = evidence_contract.get("tests") \
            if isinstance(evidence_contract, Mapping) else None
        if not isinstance(tests, Mapping) or int(tests.get("failed", 0)) != 0 \
                or int(tests.get("case_count", 0)) < 1:
            raise ProposalRejected("approval requires passing bounded tests")
        if axes.validity.get("earned") not in {"V2", "V3"}:
            raise ProposalRejected("approval requires V2 bounded validity or V3")
        contradiction = self._contradiction(
            head, self.active_rules(include_isolated=True),
        )
        if contradiction is not None:
            stored, evidence, _ = self._transition(
                rule_id, action="contradiction", actor=approver,
                state="blocked", tick=tick,
                expected_generation=expected_generation,
                status="blocked", reason=contradiction["reason"],
                payload_extra=contradiction,
            )
            raise ContradictionError(
                contradiction["reason"],
                record=self._record(stored, evidence),
                affected=tuple(contradiction["rule_ids"]),
            )
        approval_digest = digest_object({
            "rule_id": rule_id,
            "version": head.version,
            "proposal_digest": axes.lifecycle.get("proposal_digest"),
            "approver": approver,
            "test_digest": tests.get("test_digest"),
            "tick": tick,
        })

        def mutate_axes(values: dict[str, Any]) -> None:
            values["lifecycle"]["approver"] = approver
            values["lifecycle"]["approval_digest"] = approval_digest

        def mutate_contract(contract: dict[str, Any]) -> None:
            evidence = contract.get("learning_evidence")
            if not isinstance(evidence, dict):
                evidence = {}
            evidence["approval"] = {
                "approver": approver,
                "approval_digest": approval_digest,
                "test_digest": tests.get("test_digest"),
            }
            contract["learning_evidence"] = evidence

        stored, evidence, _ = self._transition(
            rule_id, action="approve", actor=approver, state="approved",
            tick=tick, expected_generation=expected_generation,
            axes_mutator=mutate_axes,
            contract_mutator=mutate_contract,
            payload_extra={"approval_digest": approval_digest},
        )
        return self._record(stored, evidence)

    def commit(self, rule_id: str, *, actor: str,
               expected_generation: int | None = None,
               tick: int = 0) -> LifecycleRecord:
        _require_text(actor, "actor", maximum=128)
        _require_int(tick, "tick")
        head, _ = self._head(rule_id)
        axes = self._axes_of(head)
        self._authorize(
            COMMIT,
            {
                "rule_id": rule_id,
                "proposer_id": axes.lifecycle.get("proposer"),
            },
            actor=actor,
        )
        if axes.state != "approved":
            raise LifecycleStateError(
                f"rule {rule_id!r} is {axes.state}, not approved"
            )
        proposer = str(axes.lifecycle.get("proposer") or "")
        if actor == proposer:
            self._deny(
                rule_id, action="commit", actor=actor,
                reason="SELF_PROMOTION", tick=tick,
            )
            raise SelfApprovalDenied(
                "the proposer may not commit its own rule"
            )
        if not axes.lifecycle.get("approval_digest"):
            raise ProposalRejected("commit requires an approval record")
        contradiction = self._contradiction(
            head, self.active_rules(include_isolated=True),
        )
        if contradiction is not None:
            stored, evidence, _ = self._transition(
                rule_id, action="contradiction", actor=actor,
                state="blocked", tick=tick,
                expected_generation=expected_generation,
                status="blocked", reason=contradiction["reason"],
                payload_extra=contradiction,
            )
            raise ContradictionError(
                contradiction["reason"],
                record=self._record(stored, evidence),
                affected=tuple(contradiction["rule_ids"]),
            )

        def mutate_axes(values: dict[str, Any]) -> None:
            values["lifecycle"]["committer"] = actor
            values["lifecycle"]["committed_version"] = head.version + 1

        stored, evidence, _ = self._transition(
            rule_id, action="commit", actor=actor, state="committed",
            tick=tick, expected_generation=expected_generation,
            event_type="commit", axes_mutator=mutate_axes,
        )
        return self._record(stored, evidence)

    def activate(self, rule_id: str, *, actor: str,
                 isolated: bool = False,
                 expected_generation: int | None = None,
                 tick: int = 0) -> LifecycleRecord:
        _require_text(actor, "actor", maximum=128)
        _require_bool(isolated, "isolated")
        _require_int(tick, "tick")
        head, _ = self._head(rule_id)
        axes = self._axes_of(head)
        self._authorize(
            ACTIVATE,
            {
                "rule_id": rule_id,
                "proposer_id": axes.lifecycle.get("proposer"),
                "isolated": bool(isolated),
            },
            actor=actor,
        )
        if axes.state != "committed":
            raise LifecycleStateError(
                f"rule {rule_id!r} is {axes.state}, not committed"
            )
        proposer = str(axes.lifecycle.get("proposer") or "")
        if actor == proposer:
            self._deny(
                rule_id, action="activate", actor=actor,
                reason="SELF_PROMOTION", tick=tick,
            )
            raise SelfApprovalDenied(
                "the proposer may not activate its own rule"
            )
        if head.level == 3 and not isolated:
            self._deny(
                rule_id, action="activate", actor=actor,
                reason="LEVEL3_ISOLATION_REQUIRED", tick=tick,
            )
            raise Level3IsolationError(
                "level-3 rules may only be activated in isolation"
            )
        if head.level != 3 and isolated:
            raise Level3IsolationError(
                "only level-3 rules may use isolated activation"
            )
        contradiction = self._contradiction(
            head, self.active_rules(include_isolated=True),
        )
        if contradiction is not None:
            stored, evidence, _ = self._transition(
                rule_id, action="contradiction", actor=actor,
                state="blocked", tick=tick,
                expected_generation=expected_generation,
                status="blocked", reason=contradiction["reason"],
                payload_extra=contradiction,
            )
            raise ContradictionError(
                contradiction["reason"],
                record=self._record(stored, evidence),
                affected=tuple(contradiction["rule_ids"]),
            )

        def mutate_axes(values: dict[str, Any]) -> None:
            values["lifecycle"]["activator"] = actor

        def mutate_lifecycle(axes_doc: dict[str, Any], lifecycle: dict[str, Any],
                             version: int, generation: int) -> None:
            lifecycle["active_version"] = version
            lifecycle["isolated"] = bool(head.level == 3 or isolated)

        stored, evidence, _ = self._transition(
            rule_id, action="activate", actor=actor, state="active",
            tick=tick, expected_generation=expected_generation,
            status="active", axes_mutator=mutate_axes,
            lifecycle_mutator=mutate_lifecycle,
            payload_extra={"isolated": bool(isolated)},
        )
        try:
            mapping = self._set_active_mapping(stored, tick=tick)
        except MathStoreError as exc:
            # The active pointer did not move.  Quarantine the unpointed head
            # so it cannot be mistaken for an active rule.
            try:
                self._transition(
                    rule_id, action="activate_failed", actor=actor,
                    state="blocked", tick=tick, status="blocked",
                    reason=str(exc),
                )
            finally:
                raise MathLearningError(
                    f"activation mapping CAS failed: {exc}"
                ) from exc
        return self._record(stored, evidence, mapping=mapping)

    # -- terminal transitions ----------------------------------------------

    def deprecate(self, rule_id: str, *, actor: str,
                  reason: str = "",
                  expected_generation: int | None = None,
                  tick: int = 0) -> LifecycleRecord:
        _require_text(actor, "actor", maximum=128)
        _require_int(tick, "tick")
        head, _ = self._head(rule_id)
        axes = self._axes_of(head)
        self._authorize(
            PRUNE,
            {
                "rule_id": rule_id,
                "proposer_id": axes.lifecycle.get("proposer"),
                "transition": "deprecate",
            },
            actor=actor,
        )
        if axes.state != "active":
            raise LifecycleStateError(
                f"rule {rule_id!r} is {axes.state}, not active"
            )

        def mutate_axes(values: dict[str, Any]) -> None:
            values["lifecycle"]["deprecator"] = actor
            values["lifecycle"]["deprecated_version"] = head.version + 1
            values["lifecycle"]["active_version"] = None

        stored, evidence, _ = self._transition(
            rule_id, action="deprecate", actor=actor, state="deprecated",
            tick=tick, expected_generation=expected_generation,
            status="deprecated", axes_mutator=mutate_axes, reason=reason,
        )
        mapping = self._try_sync_active_mapping(stored, tick=tick)
        return self._record(stored, evidence, mapping=mapping)

    def revoke(self, rule_id: str, *, actor: str, reason: str = "",
               expected_generation: int | None = None,
               tick: int = 0) -> LifecycleRecord:
        _require_text(actor, "actor", maximum=128)
        _require_int(tick, "tick")
        head, _ = self._head(rule_id)
        axes = self._axes_of(head)
        self._authorize(
            PRUNE,
            {
                "rule_id": rule_id,
                "proposer_id": axes.lifecycle.get("proposer"),
                "transition": "revoke",
            },
            actor=actor,
        )
        if axes.state not in {
            "active", "deprecated", "approved", "committed", "tested",
            "validated",
        }:
            raise LifecycleStateError(
                f"rule {rule_id!r} is {axes.state} and cannot be revoked"
            )

        def mutate_axes(values: dict[str, Any]) -> None:
            values["lifecycle"]["revoker"] = actor
            values["lifecycle"]["revoked_version"] = head.version + 1
            values["lifecycle"]["active_version"] = None

        stored, evidence, _ = self._transition(
            rule_id, action="revoke", actor=actor, state="revoked",
            tick=tick, expected_generation=expected_generation,
            status="revoked", axes_mutator=mutate_axes, reason=reason,
        )
        mapping = self._try_sync_active_mapping(stored, tick=tick)
        return self._record(stored, evidence, mapping=mapping)

    def archive(self, rule_id: str, *, actor: str, reason: str = "",
                expected_generation: int | None = None,
                tick: int = 0) -> LifecycleRecord:
        _require_text(actor, "actor", maximum=128)
        _require_int(tick, "tick")
        head, _ = self._head(rule_id)
        axes = self._axes_of(head)
        self._authorize(
            PRUNE,
            {
                "rule_id": rule_id,
                "proposer_id": axes.lifecycle.get("proposer"),
                "transition": "archive",
            },
            actor=actor,
        )
        if axes.state == "archived":
            return self._record(
                head, {}, duplicate=True,
                mapping=self._mapping_if_present(rule_id),
            )
        if axes.state not in {
            "deprecated", "revoked", "blocked", "rejected", "rolled_back",
        }:
            raise LifecycleStateError(
                f"rule {rule_id!r} is {axes.state} and cannot be archived"
            )

        def mutate_axes(values: dict[str, Any]) -> None:
            values["lifecycle"]["archiver"] = actor
            values["lifecycle"]["archived_version"] = head.version + 1
            values["lifecycle"]["active_version"] = None

        stored, evidence, _ = self._transition(
            rule_id, action="archive", actor=actor, state="archived",
            tick=tick, expected_generation=expected_generation,
            status="revoked", axes_mutator=mutate_axes, reason=reason,
        )
        mapping = self._try_sync_active_mapping(stored, tick=tick)
        return self._record(stored, evidence, mapping=mapping)

    def rollback(self, rule_id: str, *, actor: str,
                 target_version: int | None = None,
                 expected_generation: int | None = None,
                 tick: int = 0) -> LifecycleRecord:
        _require_text(actor, "actor", maximum=128)
        _require_int(tick, "tick")
        head, meta = self._head(rule_id)
        axes = self._axes_of(head)
        self._authorize(
            ACTIVATE,
            {
                "rule_id": rule_id,
                "proposer_id": axes.lifecycle.get("proposer"),
                "transition": "rollback",
                "target_version": target_version,
            },
            actor=actor,
        )
        history = self._history(rule_id)
        try:
            current_mapping = self.store.get_mapping(
                self.active_mapping_id(rule_id))
        except MathReferenceError:
            current_mapping = None

        if target_version is None:
            target = None
            for rule in reversed(history[:-1]):
                rule_axes = self._axes_of(rule)
                if rule.status == "active" and rule_axes.state == "active":
                    target = rule
                    break
            if target is None:
                raise LifecycleStateError(
                    f"rule {rule_id!r} has no earlier active version to roll back to"
                )
            target_version = target.version
        else:
            _require_int(target_version, "target_version", minimum=1)
            if target_version >= head.version:
                if target_version == head.version and axes.state == "active":
                    return self._record(
                        head, {}, duplicate=True, mapping=current_mapping,
                    )
                raise LifecycleStateError(
                    "rollback target must be an earlier rule version"
                )
            target = self.store.get_rule(rule_id, target_version)
        target_axes = self._axes_of(target)
        if target.status != "active" or target_axes.state != "active":
            raise LifecycleStateError(
                f"rollback target {rule_id}@{target_version} is not active"
            )
        if target.level != head.level:
            raise SelfApprovalDenied(
                "rollback cannot silently change rule level"
            )
        if current_mapping is not None and \
                target_version > int(current_mapping["current_version"]):
            raise LifecycleStateError(
                "rollback cannot move the active pointer forward"
            )
        if current_mapping is not None and \
                int(current_mapping["current_version"]) == target_version:
            # Idempotent: the pointer already names the target.
            if axes.state == "rolled_back":
                return self._record(
                    head, {}, duplicate=True, mapping=current_mapping,
                )

        if axes.state == "rolled_back":
            # A previous marker was written but the pointer move failed.
            # Retry the CAS without creating another marker.
            try:
                mapping = self.store.rollback_mapping(
                    self.active_mapping_id(rule_id), target_version,
                    expected_version=int(current_mapping["current_version"])
                    if current_mapping is not None else 0,
                    expected_generation=int(current_mapping["generation"])
                    if current_mapping is not None else 0,
                    tick=tick,
                )
            except MathStoreError as exc:
                raise MathLearningError(
                    f"rollback mapping CAS failed: {exc}"
                ) from exc
            evidence = self._append_learning_event(
                head, action="rollback", actor=actor,
                state="rolled_back", tick=tick,
                generation=int(meta["generation"]),
                event_type="rollback",
                reason="retry pointer move",
                payload_extra={"target_version": target_version},
            )
            return self._record(head, evidence, mapping=mapping)
        if axes.state not in {"active", "deprecated", "committed"}:
            raise LifecycleStateError(
                f"rule {rule_id!r} is {axes.state} and cannot be rolled back"
            )
        if expected_generation is not None:
            _require_int(expected_generation, "expected_generation")
            if expected_generation != int(meta["generation"]):
                raise StaleGenerationError(
                    f"rule {rule_id!r} is at generation {meta['generation']}, "
                    f"not {expected_generation}"
                )

        def mutate_axes(values: dict[str, Any]) -> None:
            values["lifecycle"]["roller_back"] = actor
            values["lifecycle"]["rollback_to"] = target_version
            values["lifecycle"]["active_version"] = target_version

        def mutate_lifecycle(axes_doc: dict[str, Any], lifecycle: dict[str, Any],
                             version: int, generation: int) -> None:
            lifecycle["rollback_to"] = target_version
            lifecycle["active_version"] = target_version

        stored, evidence, _ = self._transition(
            rule_id, action="rollback", actor=actor, state="rolled_back",
            tick=tick, expected_generation=expected_generation,
            status="proposed", axes_mutator=mutate_axes,
            lifecycle_mutator=mutate_lifecycle,
            payload_extra={"target_version": target_version},
        )
        current_mapping = self._mapping_if_present(rule_id)
        try:
            if current_mapping is None:
                mapping = self._set_active_mapping(
                    self.store.get_rule(rule_id, target_version), tick=tick,
                )
            else:
                mapping = self.store.rollback_mapping(
                    self.active_mapping_id(rule_id), target_version,
                    expected_version=int(current_mapping["current_version"]),
                    expected_generation=int(current_mapping["generation"]),
                    tick=tick,
                )
        except MathStoreError as exc:
            raise MathLearningError(
                f"rollback mapping CAS failed: {exc}"
            ) from exc
        return self._record(stored, evidence, mapping=mapping)

    # -- experiments: utility only -----------------------------------------

    def record_experiment(self, rule_id: str,
                          outcome: ExperimentOutcome | Mapping[str, Any], *,
                          actor: str,
                          expected_generation: int | None = None,
                          request_promotion: bool = False,
                          tick: int = 0) -> LifecycleRecord:
        _require_text(actor, "actor", maximum=128)
        _require_int(tick, "tick")
        _require_bool(request_promotion, "request_promotion")
        if request_promotion:
            raise ExperimentPromotionDenied(
                "experiment outcomes are utility evidence, never validity or "
                "proof; use the validate/test/approve/commit/activate lifecycle"
            )
        head, _ = self._head(rule_id)
        axes = self._axes_of(head)
        self._authorize(
            TEST,
            {
                "rule_id": rule_id,
                "proposer_id": axes.lifecycle.get("proposer"),
                "transition": "experiment",
            },
            actor=actor,
        )
        if axes.state == "archived":
            raise LifecycleStateError("archived rules cannot receive experiments")
        record = self._normalise_experiment(outcome)
        reasons: list[str] = []
        if record["outcome"] in {"supported", "ablation_passed"}:
            if record["synthetic"]:
                reasons.append("synthetic")
            if record["underpowered"]:
                reasons.append("underpowered")
            if int(record["sample_size"]) < 1:
                reasons.append("no-samples")
            if record["data_digest"] is None:
                reasons.append("missing-data-digest")
        if reasons:
            record["requested_outcome"] = record["outcome"]
            record["outcome"] = "inconclusive"
            record["inconclusive_reasons"] = reasons
        record["recorded_by"] = actor
        record["tick"] = tick
        record["outcome_digest"] = digest_object({
            key: value for key, value in record.items()
            if key != "outcome_digest"
        })

        def mutate_axes(values: dict[str, Any]) -> None:
            utility = values["utility"]
            outcomes = list(utility.get("outcomes") or ())
            outcomes.append(_canonical_copy(record, "experiment outcome"))
            utility["outcomes"] = outcomes
            if record["score"] is not None:
                utility["score"] = record["score"]
            if record["scope"]:
                utility["scope"] = _canonical_copy(
                    record["scope"], "experiment scope")
            if any(item.get("outcome") == "rejected" for item in outcomes):
                utility["status"] = "rejected"
            elif any(
                item.get("outcome") in {"supported", "ablation_passed"}
                for item in outcomes
            ):
                utility["status"] = "supported"
            elif outcomes:
                utility["status"] = "inconclusive"
            else:
                utility["status"] = "unknown"
            values["lifecycle"]["last_experiment_by"] = actor
            if axes.state == "active":
                values["lifecycle"]["active_version"] = head.version + 1

        def mutate_lifecycle(axes_doc: dict[str, Any], lifecycle: dict[str, Any],
                             version: int, generation: int) -> None:
            if axes.state == "active":
                lifecycle["active_version"] = version

        stored, evidence, _ = self._transition(
            rule_id, action="experiment_outcome", actor=actor,
            state=axes.state, tick=tick,
            expected_generation=expected_generation,
            axes_mutator=mutate_axes,
            lifecycle_mutator=mutate_lifecycle,
            payload_extra={
                "experiment_source": record["source"],
                "experiment_outcome": record["outcome"],
                "outcome_digest": record["outcome_digest"],
                "utility_only": True,
            },
        )
        mapping = None
        if axes.state == "active":
            mapping = self._try_sync_active_mapping(stored, tick=tick)
        return self._record(stored, evidence, mapping=mapping)

    def _normalise_experiment(self, outcome: ExperimentOutcome | Mapping[str, Any]
                              ) -> dict[str, Any]:
        if isinstance(outcome, ExperimentOutcome):
            raw = outcome.to_dict()
        elif isinstance(outcome, Mapping):
            raw = _canonical_copy(dict(outcome), "experiment outcome")
        else:
            raise MathLearningError("outcome must be ExperimentOutcome or object")
        source = raw.get("source")
        if not isinstance(source, str):
            raise MathLearningError("experiment source must be a string")
        aliases = {
            "r7_experiment": "r7",
            "lm": "lm_ablation",
            "lm_adapter": "lm_ablation",
            "lm_ablation_adapter": "lm_ablation",
        }
        source = aliases.get(source, source)
        if source not in EXPERIMENT_SOURCES:
            raise MathLearningError(
                f"experiment source must be one of: "
                f"{', '.join(sorted(EXPERIMENT_SOURCES))}"
            )
        value = raw.get("outcome")
        if not isinstance(value, str) or value not in EXPERIMENT_OUTCOMES:
            raise MathLearningError(
                f"experiment outcome must be one of: "
                f"{', '.join(sorted(EXPERIMENT_OUTCOMES))}"
            )
        scope = _mapping(raw.get("scope", {}), "experiment scope")
        sample_size = _require_int(
            raw.get("sample_size", 0), "sample_size",
        )
        seeds_raw = raw.get("seeds", ())
        if not isinstance(seeds_raw, (tuple, list)):
            raise MathLearningError("seeds must be a list")
        seeds = []
        for seed in seeds_raw:
            if isinstance(seed, bool) or not isinstance(seed, (str, int)):
                raise MathLearningError("seeds must be strings or integers")
            seeds.append(seed)
        data_digest = _require_digest(
            raw.get("data_digest"), "data_digest", allow_none=True,
        )
        evidence_digest = _require_digest(
            raw.get("evidence_digest"), "evidence_digest", allow_none=True,
        )
        synthetic = _require_bool(raw.get("synthetic", False), "synthetic")
        underpowered = _require_bool(
            raw.get("underpowered", False), "underpowered",
        )
        score = raw.get("score")
        if score is not None:
            _require_int(score, "score")
        return {
            "source": source,
            "outcome": value,
            "scope": scope,
            "sample_size": sample_size,
            "seeds": seeds,
            "data_digest": data_digest,
            "evidence_digest": evidence_digest,
            "synthetic": synthetic,
            "underpowered": underpowered,
            "score": score,
            "utility_only": True,
        }

    def promote_by_experiment(self, rule_id: str, *, actor: str) -> None:
        """A deliberately explicit denial for the forbidden shortcut."""
        raise ExperimentPromotionDenied(
            "an experiment outcome cannot promote a rule; validity and proof "
            "are separate axes"
        )

    # -- level promotion (separate authority) ------------------------------

    def promote(self, rule_id: str, target_level: int, *, actor: str,
                proof_digest: str | None = None,
                checker: str | None = None,
                expected_generation: int | None = None,
                tick: int = 0) -> LifecycleRecord:
        _require_text(actor, "actor", maximum=128)
        _require_int(tick, "tick")
        if isinstance(target_level, bool) or target_level not in (1, 2, 3):
            raise Level0ImmutableError(
                "promotion target must be level 1, 2, or 3; level 0 is never learned"
            )
        head, _ = self._head(rule_id)
        self._assert_not_level0(rule_id)
        axes = self._axes_of(head)
        self._authorize(
            PROMOTE,
            {
                "rule_id": rule_id,
                "proposer_id": axes.lifecycle.get("proposer"),
                "target_level": target_level,
            },
            actor=actor,
        )
        proposer = str(axes.lifecycle.get("proposer") or "")
        if actor == proposer:
            self._deny(
                rule_id, action="promote", actor=actor,
                reason="SELF_PROMOTION", tick=tick,
            )
            raise SelfApprovalDenied(
                "the proposer may not promote its own rule"
            )
        if target_level == head.level:
            raise LifecycleStateError("rule is already at the target level")
        proof = axes.proof
        trusted = (
            proof.get("status") == "checked"
            and proof.get("trusted") is True
            and proof.get("proof_digest") is not None
        )
        if target_level < head.level:
            if not trusted:
                raise ProposalRejected(
                    "PROOF_REQUIRED_FOR_PROMOTION: a lower level number "
                    "requires a checked, trusted proof"
                )
            if proof_digest is not None:
                _require_digest(proof_digest, "proof_digest")
                if proof_digest != proof.get("proof_digest"):
                    raise ProposalRejected(
                        "proof_digest does not name the checked proof"
                    )
            if checker is not None:
                _require_text(checker, "checker", maximum=256)
                if sha256_text(checker) != proof.get("checker_digest"):
                    raise ProposalRejected(
                        "checker does not match the recorded proof checker"
                    )

        def mutate_axes(values: dict[str, Any]) -> None:
            values["lifecycle"]["promoter"] = actor
            values["lifecycle"]["promoted_from_level"] = head.level
            values["lifecycle"]["promoted_to_level"] = target_level
            values["lifecycle"]["isolated"] = target_level == 3

        def mutate_contract(contract: dict[str, Any]) -> None:
            history = contract.get("promotion_history")
            if not isinstance(history, list):
                history = []
            history.append({
                "from_level": head.level,
                "to_level": target_level,
                "actor": actor,
                "tick": tick,
                "proof_digest": proof.get("proof_digest"),
            })
            contract["promotion_history"] = history

        def mutate_lifecycle(axes_doc: dict[str, Any], lifecycle: dict[str, Any],
                             version: int, generation: int) -> None:
            if axes.state == "active":
                lifecycle["active_version"] = version

        stored, evidence, _ = self._transition(
            rule_id, action="promote", actor=actor, state=axes.state,
            tick=tick, expected_generation=expected_generation,
            level=target_level, axes_mutator=mutate_axes,
            contract_mutator=mutate_contract,
            lifecycle_mutator=mutate_lifecycle,
            payload_extra={
                "from_level": head.level,
                "to_level": target_level,
            },
        )
        mapping = None
        if axes.state == "active":
            mapping = self._try_sync_active_mapping(stored, tick=tick)
        return self._record(stored, evidence, mapping=mapping)

    # -- lookup helpers -----------------------------------------------------

    def _mapping_if_present(self, rule_id: str) -> dict[str, Any] | None:
        try:
            return self.store.get_mapping(self.active_mapping_id(rule_id))
        except MathReferenceError:
            return None

    # -- negative memory ----------------------------------------------------

    def negative_memory(self) -> dict[str, list[dict[str, Any]]]:
        """Reconstruct negative memory from append-only rule versions."""
        mappings = self.store.list_mappings(object_type="rule", limit=65536)
        rule_ids = {str(mapping["object_id"]) for mapping in mappings}
        memory: dict[str, list[dict[str, Any]]] = {}
        for rule_id in sorted(rule_ids):
            for rule in self._history(rule_id):
                proposal = self._proposal_of(rule)
                if proposal is None:
                    continue
                axes = self._axes_of(rule)
                if axes.state not in NEGATIVE_STATES:
                    continue
                memory.setdefault(
                    str(proposal["content_digest"]), []
                ).append({
                    "rule_id": rule_id,
                    "version": rule.version,
                    "state": axes.state,
                    "reason": axes.lifecycle.get("reason"),
                })
        return memory

    # -- audit --------------------------------------------------------------

    def audit(self, rule_id: str) -> dict[str, Any]:
        head, meta = self._head(rule_id)
        events = self._learning_events(rule_id)
        chain = "0" * 64
        evidence: list[dict[str, Any]] = []
        for event in events:
            view = self._evidence_view(event)
            chain = sha256_text(canonical_json({
                "previous": chain,
                "evidence_id": view["evidence_id"],
                "action": view["action"],
                "state": view["state"],
            }))
            view["chain_digest"] = chain
            evidence.append(view)
        mapping_events = self.store.list_events(
            object_type="mapping",
            object_id=self.active_mapping_id(rule_id),
            limit=65536,
        )
        return {
            "schema": LEARNING_SCHEMA,
            "rule_id": rule_id,
            "version": head.version,
            "generation": int(meta["generation"]),
            "state": self._axes_of(head).state,
            "axes": self._axes_of(head).to_dict(),
            "events": evidence,
            "event_count": len(evidence),
            "mapping_event_count": len(mapping_events),
            "mapping": self._mapping_if_present(rule_id),
            "audit_digest": chain,
        }

    def verify_audit(self, rule_id: str,
                     expected_digest: str | None = None) -> bool:
        audit = self.audit(rule_id)
        if expected_digest is not None:
            expected_digest = _require_digest(expected_digest, "expected_digest")
            if expected_digest != audit["audit_digest"]:
                raise AuditError("audit digest does not match")
        if audit["event_count"] == 0:
            raise AuditError("no learning evidence is present")
        states = [event["state"] for event in audit["events"]
                  if event["action"] not in {"duplicate_proposal"}]
        if states and states[0] != "proposed":
            raise AuditError("evidence chain does not begin at proposed")
        return True


# Convenient alias for callers that prefer the narrower name.
RuleLifecycleService = MathLearningService


__all__ = [
    "ACTIVE_MAPPING_PREFIX",
    "AuditError",
    "CLAIM_CLASSES",
    "ContradictionError",
    "DuplicateProposalConflict",
    "EXPERIMENT_OUTCOMES",
    "EXPERIMENT_SOURCES",
    "ExperimentOutcome",
    "ExperimentPromotionDenied",
    "InconclusiveEvidence",
    "LEARNING_SCHEMA",
    "LIFECYCLE_STATES",
    "LearningAuthorizationDenied",
    "LearningAuthorizationError",
    "LearningConfigError",
    "Level0ImmutableError",
    "Level3IsolationError",
    "LifecycleRecord",
    "LifecycleStateError",
    "MathLearningAuthorizationError",
    "MathLearningError",
    "MathLearningService",
    "NEGATIVE_STATES",
    "NegativeMemoryError",
    "PROOF_AXIS_STATES",
    "ProposalRejected",
    "RuleAxes",
    "RuleLifecycleService",
    "RuleProposal",
    "SelfApprovalDenied",
    "StaleGenerationError",
    "TERMINAL_STATES",
    "TestFailure",
    "TRUTH_CLAIMS",
    "VALIDITY_LEVELS",
    "verify_audit",
]


def verify_audit(service: MathLearningService, rule_id: str,
                 expected_digest: str | None = None) -> bool:
    """Module-level convenience wrapper around ``service.verify_audit``."""
    if not isinstance(service, MathLearningService):
        raise MathLearningError("service must be a MathLearningService")
    return service.verify_audit(rule_id, expected_digest)
