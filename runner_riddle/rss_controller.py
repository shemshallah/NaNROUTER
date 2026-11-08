"""Host-only RSS verb controller over the MTH plan registry.

The controller maps the eight public RSS verbs (ENCODE, QUERY, MATCH, FILTER,
DRIVE, PROPAGATE, FOLD, DECODE) onto registered NaN16 kernels and composes an
:class:`~runner_riddle.mth_registry.MthPlan` for each route.  It is a
control-plane selector, not a math implementation: it performs no numerical
operation, executes no kernel, and offers no alternate execution path.

A route result is either ``PLANNED`` with a validated plan and deterministic
plan digest, or ``UNAVAILABLE`` with a stable reason code.  In particular, a
FILTER route whose kernel is absent or not dispatchable is reported as
``UNAVAILABLE``; the controller never substitutes host arithmetic.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .math_objects import canonical_json
from .mth_registry import (
    PLAN_SPEC_SCHEMA,
    MthPlan,
    MthPlanError,
    MthRegistry,
)

RSS_CONTROLLER_SCHEMA = "nanrouter.rss-controller.v1"
RSS_ROUTE_SCHEMA = "nanrouter.rss-route.v1"

RSS_VERBS = (
    "ENCODE",
    "QUERY",
    "MATCH",
    "FILTER",
    "DRIVE",
    "PROPAGATE",
    "FOLD",
    "DECODE",
)

RSS_STATUS_PLANNED = "PLANNED"
RSS_STATUS_UNAVAILABLE = "UNAVAILABLE"

RSS_REASON_INVALID_CONFIG = "invalid_config"
RSS_REASON_INVALID_REQUEST = "invalid_request"
RSS_REASON_UNKNOWN_VERB = "unknown_verb"
RSS_REASON_UNKNOWN_KERNEL = "unknown_kernel"
RSS_REASON_KERNEL_NOT_NATIVE_VERIFIED = "kernel_not_native_verified"
RSS_REASON_KERNEL_NOT_CI_VERIFIED = "kernel_not_ci_verified"
RSS_REASON_FILTER_UNAVAILABLE = "filter_kernel_unavailable"
RSS_REASON_FILTER_NOT_CI_VERIFIED = "filter_kernel_not_ci_verified"
RSS_REASON_STEP_LIMIT = "step_limit_exceeded"
RSS_REASON_WORKSPACE = "unsupported_workspace"
RSS_REASON_PLAN_REJECTED = "plan_rejected"
RSS_REASON_ROUTE_UNAVAILABLE = "route_unavailable"


class RssControllerError(ValueError):
    """Base class for RSS controller configuration and routing failures."""

    reason = "rss_controller_error"

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason or type(self).reason


class RssConfigError(RssControllerError):
    """The controller was configured with an invalid route or bound."""

    reason = RSS_REASON_INVALID_CONFIG


class RssRequestError(RssControllerError):
    """A route request is malformed or rejected by the plan contract."""

    reason = RSS_REASON_INVALID_REQUEST


class RssVerbError(RssRequestError):
    """The requested verb is not one of the eight public RSS verbs."""

    reason = RSS_REASON_UNKNOWN_VERB


class RssKernelError(RssControllerError):
    """A route names an absent or non-dispatchable kernel."""

    reason = RSS_REASON_UNKNOWN_KERNEL


class RssStepLimitError(RssControllerError):
    """A route exceeds the controller's bounded step count."""

    reason = RSS_REASON_STEP_LIMIT


class RssWorkspaceError(RssControllerError):
    """A route exceeds its workspace budget or requests too little space."""

    reason = RSS_REASON_WORKSPACE


class RssUnavailableError(RssControllerError):
    """A caller required a plan from a typed UNAVAILABLE route."""

    reason = RSS_REASON_ROUTE_UNAVAILABLE


@dataclass(frozen=True)
class RssPlanStepSpec:
    """One route step template; empty fields are filled deterministically.

    ``kernel_id`` is mandatory.  When ``name`` is omitted, the controller uses
    ``<verb>.<index>``.  When ``inputs``/``outputs`` are omitted, the controller
    chains typed names sequentially so a multi-kernel route is still a valid
    ordered plan.
    """

    kernel_id: str
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kernel_id": self.kernel_id,
            "name": self.name,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "depends_on": list(self.depends_on),
        }


def _default_routes() -> dict[str, tuple[RssPlanStepSpec, ...]]:
    """Return the declared one-kernel route for each public RSS verb."""
    return {
        "ENCODE": (
            RssPlanStepSpec(
                name="encode",
                kernel_id="mth.encode.256.full.f32",
                inputs=("f32[256].rss.encode.relation",),
                outputs=("f32[256].rss.encode.state",),
            ),
        ),
        "QUERY": (
            RssPlanStepSpec(
                name="query",
                kernel_id="mth.sparse.laplacian.q16.16",
                inputs=("q16.16[256].rss.query.state",),
                outputs=("q16.16[256].rss.query.result",),
            ),
        ),
        "MATCH": (
            RssPlanStepSpec(
                name="match",
                kernel_id="mth.vector.cosine256.f32",
                inputs=(
                    "f32[256].rss.match.left",
                    "f32[256].rss.match.right",
                ),
                outputs=("f32.rss.match.score",),
            ),
        ),
        "FILTER": (
            RssPlanStepSpec(
                name="filter",
                kernel_id="mth.graph.filter.poly2.q16.16",
                inputs=("q16.16[256].rss.filter.state",),
                outputs=("q16.16[256].rss.filter.state",),
            ),
        ),
        "DRIVE": (
            RssPlanStepSpec(
                name="drive",
                kernel_id="mth.drive.source.256.f32",
                inputs=(
                    "f32[256].rss.drive.state",
                    "f32[256].rss.drive.source",
                ),
                outputs=("f32[256].rss.drive.state",),
            ),
        ),
        "PROPAGATE": (
            RssPlanStepSpec(
                name="propagate",
                kernel_id="mth.graph.wave_step.f32",
                inputs=(
                    "f32[256].rss.propagate.position",
                    "f32[256].rss.propagate.velocity",
                    "f32[256].rss.propagate.acceleration",
                ),
                outputs=(
                    "f32[256].rss.propagate.position",
                    "f32[256].rss.propagate.velocity",
                ),
            ),
        ),
        "FOLD": (
            RssPlanStepSpec(
                name="fold",
                kernel_id="mth.graph.fold.f32",
                inputs=("f32[256].rss.fold.state",),
                outputs=("f32[128].rss.fold.folded",),
            ),
        ),
        "DECODE": (
            RssPlanStepSpec(
                name="decode",
                kernel_id="mth.decode.256.full.f32",
                inputs=("f32[256].rss.decode.state",),
                outputs=("f32[256].rss.decode.output",),
            ),
        ),
    }


DEFAULT_ROUTES = _default_routes()


def plan_digest(plan: MthPlan) -> str:
    """Return the deterministic SHA-256 digest of a plan document."""
    if not isinstance(plan, MthPlan):
        raise RssRequestError("plan must be an MthPlan")
    document = plan.to_dict()
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def _require_bound(value: Any, name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RssConfigError(f"{name} must be an integer >= {minimum}")
    return value


def _require_request_bound(value: Any, name: str, *,
                           minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RssRequestError(f"{name} must be an integer >= {minimum}")
    return value


def _normalise_steps(value: Any, verb: str) -> tuple[RssPlanStepSpec, ...]:
    if isinstance(value, str):
        raw_steps: Sequence[Any] = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        raw_steps = value
    else:
        raise RssConfigError(
            f"route {verb!r} must be a kernel id or a sequence of route steps"
        )
    if not raw_steps:
        raise RssConfigError(f"route {verb!r} must contain at least one step")
    steps: list[RssPlanStepSpec] = []
    for index, raw in enumerate(raw_steps):
        if isinstance(raw, RssPlanStepSpec):
            if not raw.kernel_id:
                raise RssConfigError(
                    f"route {verb!r} step {index} has no kernel_id"
                )
            steps.append(raw)
        elif isinstance(raw, str):
            if not raw:
                raise RssConfigError(
                    f"route {verb!r} step {index} has no kernel_id"
                )
            steps.append(RssPlanStepSpec(kernel_id=raw))
        elif isinstance(raw, Mapping):
            unknown = sorted(
                key for key in raw
                if key not in {
                    "kernel_id", "name", "inputs", "outputs", "depends_on",
                }
            )
            if unknown:
                raise RssConfigError(
                    f"route {verb!r} step {index} has unknown fields: "
                    f"{', '.join(sorted(unknown))}"
                )
            steps.append(RssPlanStepSpec(
                kernel_id=raw.get("kernel_id", ""),
                name=raw.get("name"),
                inputs=tuple(raw.get("inputs", ())),
                outputs=tuple(raw.get("outputs", ())),
                depends_on=tuple(raw.get("depends_on", ())),
            ))
            if not steps[-1].kernel_id:
                raise RssConfigError(
                    f"route {verb!r} step {index} has no kernel_id"
                )
        else:
            raise RssConfigError(
                f"route {verb!r} step {index} must be a kernel id, mapping, "
                "or RssPlanStepSpec"
            )
    return tuple(steps)


@dataclass(frozen=True)
class RssRouteResult:
    """Typed outcome of routing one RSS verb.

    A ``PLANNED`` result carries a registry-validated plan and its digest.  An
    ``UNAVAILABLE`` result carries no plan and a stable reason code.  Neither
    form is execution evidence.
    """

    verb: str
    status: str
    kernel_ids: tuple[str, ...]
    plan: MthPlan | None = None
    plan_digest: str | None = None
    reason: str | None = None
    detail: str | None = None
    workspace_words: int | None = None
    step_count: int = 0
    deterministic: bool = True

    @property
    def available(self) -> bool:
        return self.status == RSS_STATUS_PLANNED

    def require_plan(self) -> MthPlan:
        """Return the route plan or raise :class:`RssUnavailableError`."""
        if self.plan is None:
            raise RssUnavailableError(
                f"{self.verb} route is {self.status}: {self.detail or self.reason}",
                reason=self.reason or RSS_REASON_ROUTE_UNAVAILABLE,
            )
        return self.plan

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RSS_ROUTE_SCHEMA,
            "verb": self.verb,
            "status": self.status,
            "kernel_ids": list(self.kernel_ids),
            "step_count": self.step_count,
            "workspace_words": self.workspace_words,
            "deterministic": self.deterministic,
            "plan_digest": self.plan_digest,
            "reason": self.reason,
            "detail": self.detail,
            "plan": None if self.plan is None else self.plan.to_dict(),
        }


class RssController:
    """Compose RSS verb routes into validated MTH plans.

    ``routes`` optionally overrides or extends :data:`DEFAULT_ROUTES`.  Each
    value is a kernel id, a sequence of kernel ids, mappings, or
    :class:`RssPlanStepSpec` objects.  Overrides are normalized before use; a
    route with more than ``max_steps`` steps is rejected at request time.

    ``max_workspace_words`` is an optional hard controller budget.  Request
    workspace below the route's required workspace is always rejected.
    """

    def __init__(
        self,
        registry: MthRegistry,
        routes: Mapping[str, Any] | None = None,
        *,
        max_steps: int = 16,
        max_workspace_words: int | None = None,
    ) -> None:
        if not isinstance(registry, MthRegistry):
            raise RssConfigError("registry must be an MthRegistry")
        self.registry = registry
        self.max_steps = _require_bound(max_steps, "max_steps", minimum=1)
        if max_workspace_words is None:
            self.max_workspace_words = None
        else:
            self.max_workspace_words = _require_bound(
                max_workspace_words, "max_workspace_words", minimum=0
            )

        table = dict(DEFAULT_ROUTES)
        if routes is not None:
            if not isinstance(routes, Mapping):
                raise RssConfigError("routes must be a mapping")
            for raw_verb, raw_route in routes.items():
                verb = self._normalise_verb(raw_verb)
                table[verb] = _normalise_steps(raw_route, verb)
        self._routes = {
            verb: tuple(table[verb])
            for verb in RSS_VERBS
        }

    @property
    def verbs(self) -> tuple[str, ...]:
        return RSS_VERBS

    @property
    def routes(self) -> dict[str, tuple[str, ...]]:
        return {
            verb: tuple(step.kernel_id for step in steps)
            for verb, steps in self._routes.items()
        }

    @staticmethod
    def _normalise_verb(verb: Any) -> str:
        if not isinstance(verb, str):
            raise RssRequestError("verb must be a string")
        normalised = verb.upper()
        if normalised not in RSS_VERBS:
            raise RssVerbError(f"unknown RSS verb: {verb!r}")
        return normalised

    def _resolve_steps(
        self, verb: str, templates: tuple[RssPlanStepSpec, ...],
    ) -> tuple[RssPlanStepSpec, ...]:
        resolved: list[RssPlanStepSpec] = []
        previous_name: str | None = None
        previous_output: str | None = None
        for index, template in enumerate(templates):
            name = template.name or f"{verb.lower()}.step{index}"
            depends_on = template.depends_on
            if not depends_on and previous_name is not None:
                depends_on = (previous_name,)
            inputs = template.inputs
            if not inputs:
                if previous_output is None:
                    inputs = (f"rss.{verb.lower()}.input",)
                else:
                    inputs = (previous_output,)
            outputs = template.outputs
            if not outputs:
                outputs = (f"rss.{verb.lower()}.step{index}.output",)
            resolved.append(RssPlanStepSpec(
                kernel_id=template.kernel_id,
                name=name,
                inputs=tuple(inputs),
                outputs=tuple(outputs),
                depends_on=tuple(depends_on),
            ))
            previous_name = name
            previous_output = outputs[0]
        return tuple(resolved)

    def _unavailable(
        self,
        verb: str,
        steps: tuple[RssPlanStepSpec, ...],
        reason: str,
        detail: str,
    ) -> RssRouteResult:
        kernel_ids = tuple(step.kernel_id for step in steps)
        return RssRouteResult(
            verb=verb,
            status=RSS_STATUS_UNAVAILABLE,
            kernel_ids=kernel_ids,
            reason=reason,
            detail=detail,
            step_count=len(kernel_ids),
        )

    def _check_dispatchable(
        self, verb: str, steps: tuple[RssPlanStepSpec, ...],
    ) -> RssRouteResult | None:
        for step in steps:
            descriptor = self.registry.lookup(step.kernel_id)
            if descriptor is None:
                if verb == "FILTER":
                    return self._unavailable(
                        verb,
                        steps,
                        RSS_REASON_FILTER_UNAVAILABLE,
                        f"FILTER kernel {step.kernel_id!r} is not registered",
                    )
                raise RssKernelError(
                    f"{verb} route names unknown kernel {step.kernel_id!r}",
                    reason=RSS_REASON_UNKNOWN_KERNEL,
                )
            if descriptor.status != "native_verified":
                raise RssKernelError(
                    f"{verb} route kernel {step.kernel_id!r} has status "
                    f"{descriptor.status!r}, not 'native_verified'",
                    reason=RSS_REASON_KERNEL_NOT_NATIVE_VERIFIED,
                )
            if not descriptor.ci_verified:
                if verb == "FILTER":
                    return self._unavailable(
                        verb,
                        steps,
                        RSS_REASON_FILTER_NOT_CI_VERIFIED,
                        f"FILTER kernel {step.kernel_id!r} is not CI-verified",
                    )
                raise RssKernelError(
                    f"{verb} route kernel {step.kernel_id!r} is not CI-verified",
                    reason=RSS_REASON_KERNEL_NOT_CI_VERIFIED,
                )
        return None

    def _step_document(self, step: RssPlanStepSpec) -> dict[str, Any]:
        return {
            "name": step.name,
            "kernel_id": step.kernel_id,
            "inputs": list(step.inputs),
            "outputs": list(step.outputs),
            "depends_on": list(step.depends_on),
        }

    def route(
        self,
        verb: str,
        *,
        plan_id: str | None = None,
        workspace_words: int | None = None,
        fuel: int | None = None,
        cancel_after: int | None = None,
    ) -> RssRouteResult:
        """Compose one RSS verb into a validated plan or typed UNAVAILABLE."""
        normalised = self._normalise_verb(verb)
        templates = self._routes[normalised]
        if len(templates) > self.max_steps:
            raise RssStepLimitError(
                f"{normalised} route has {len(templates)} steps, above the "
                f"bounded maximum of {self.max_steps}",
                reason=RSS_REASON_STEP_LIMIT,
            )
        steps = self._resolve_steps(normalised, templates)
        unavailable = self._check_dispatchable(normalised, steps)
        if unavailable is not None:
            return unavailable

        if plan_id is None:
            plan_id = f"rss.{normalised.lower()}"
        if workspace_words is not None:
            workspace_words = _require_request_bound(
                workspace_words, "workspace_words", minimum=0
            )

        spec: dict[str, Any] = {
            "schema": PLAN_SPEC_SCHEMA,
            "plan_id": plan_id,
            "steps": [self._step_document(step) for step in steps],
        }
        if fuel is not None:
            spec["fuel"] = fuel
        if cancel_after is not None:
            spec["cancel_after"] = cancel_after

        try:
            plan = self.registry.compose(spec)
        except MthPlanError as exc:
            raise RssRequestError(
                f"{normalised} route plan was rejected: {exc}",
                reason=RSS_REASON_PLAN_REJECTED,
            ) from exc

        required_workspace = plan.workspace_words
        if (
            self.max_workspace_words is not None
            and required_workspace > self.max_workspace_words
        ):
            raise RssWorkspaceError(
                f"{normalised} route needs {required_workspace} workspace "
                f"words, above the controller budget of "
                f"{self.max_workspace_words}",
                reason=RSS_REASON_WORKSPACE,
            )
        if workspace_words is not None:
            if workspace_words < required_workspace:
                raise RssWorkspaceError(
                    f"{normalised} route needs at least {required_workspace} "
                    f"workspace words, got {workspace_words}",
                    reason=RSS_REASON_WORKSPACE,
                )
            if workspace_words != required_workspace:
                spec["workspace_words"] = workspace_words
                try:
                    plan = self.registry.compose(spec)
                except MthPlanError as exc:
                    raise RssRequestError(
                        f"{normalised} route plan was rejected: {exc}",
                        reason=RSS_REASON_PLAN_REJECTED,
                    ) from exc

        digest = plan_digest(plan)
        return RssRouteResult(
            verb=normalised,
            status=RSS_STATUS_PLANNED,
            kernel_ids=plan.kernel_ids,
            plan=plan,
            plan_digest=digest,
            workspace_words=plan.workspace_words,
            step_count=len(plan.steps),
            deterministic=plan.deterministic,
        )

    def compose(
        self,
        verb: str,
        *,
        plan_id: str | None = None,
        workspace_words: int | None = None,
        fuel: int | None = None,
        cancel_after: int | None = None,
    ) -> RssRouteResult:
        """Alias of :meth:`route`; composition never executes the plan."""
        return self.route(
            verb,
            plan_id=plan_id,
            workspace_words=workspace_words,
            fuel=fuel,
            cancel_after=cancel_after,
        )

    def availability(self) -> dict[str, dict[str, Any]]:
        """Return the typed status of every verb without executing anything."""
        report: dict[str, dict[str, Any]] = {}
        for verb in RSS_VERBS:
            try:
                result = self.route(verb)
            except RssControllerError as exc:
                report[verb] = {
                    "verb": verb,
                    "status": "REJECTED",
                    "reason": exc.reason,
                    "detail": str(exc),
                    "kernel_ids": list(self.routes[verb]),
                }
            else:
                report[verb] = {
                    "verb": verb,
                    "status": result.status,
                    "reason": result.reason,
                    "detail": result.detail,
                    "kernel_ids": list(result.kernel_ids),
                    "plan_digest": result.plan_digest,
                }
        return report

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RSS_CONTROLLER_SCHEMA,
            "verbs": list(RSS_VERBS),
            "max_steps": self.max_steps,
            "max_workspace_words": self.max_workspace_words,
            "routes": {
                verb: [step.to_dict() for step in self._routes[verb]]
                for verb in RSS_VERBS
            },
        }


__all__ = [
    "DEFAULT_ROUTES",
    "RSS_CONTROLLER_SCHEMA",
    "RSS_ROUTE_SCHEMA",
    "RSS_REASON_FILTER_NOT_CI_VERIFIED",
    "RSS_REASON_FILTER_UNAVAILABLE",
    "RSS_REASON_INVALID_CONFIG",
    "RSS_REASON_INVALID_REQUEST",
    "RSS_REASON_KERNEL_NOT_CI_VERIFIED",
    "RSS_REASON_KERNEL_NOT_NATIVE_VERIFIED",
    "RSS_REASON_PLAN_REJECTED",
    "RSS_REASON_ROUTE_UNAVAILABLE",
    "RSS_REASON_STEP_LIMIT",
    "RSS_REASON_UNKNOWN_KERNEL",
    "RSS_REASON_UNKNOWN_VERB",
    "RSS_REASON_WORKSPACE",
    "RSS_STATUS_PLANNED",
    "RSS_STATUS_UNAVAILABLE",
    "RSS_VERBS",
    "RssConfigError",
    "RssController",
    "RssControllerError",
    "RssKernelError",
    "RssPlanStepSpec",
    "RssRequestError",
    "RssRouteResult",
    "RssStepLimitError",
    "RssUnavailableError",
    "RssVerbError",
    "RssWorkspaceError",
    "plan_digest",
]
