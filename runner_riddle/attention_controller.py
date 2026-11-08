"""Host-only attention plan controller over the MTH plan registry.

The controller maps the attention vertical slice required by
``docs/GAME_PLAN_MTH.md`` §4 onto explicit registered NaN16 kernels and
composes a validated :class:`~runner_riddle.mth_registry.MthPlan`:

``qk_dot -> scale -> [mask] -> softmax -> weighted_sum -> head_concat ->
projection``

It is a control-plane selector, not a math implementation: it performs no
numerical operation, executes no kernel, and offers no alternate execution
path.  A route result is either ``PLANNED`` with a validated plan and
deterministic plan digest, or ``UNAVAILABLE`` with a stable reason code.

The mask, stable-softmax, weighted-sum, and head-concat stage kernels are not
registered in the current capability manifest.  A missing (or not
dispatchable) mask/softmax/weighted-sum kernel therefore produces a typed
``UNAVAILABLE`` result.  The controller never substitutes host arithmetic or
an unregistered fallback.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .math_objects import canonical_json
from .mth_registry import (
    PLAN_SPEC_SCHEMA,
    MthPlan,
    MthPlanError,
    MthRegistry,
)

ATTENTION_CONTROLLER_SCHEMA = "nanrouter.attention-controller.v1"
ATTENTION_ROUTE_SCHEMA = "nanrouter.attention-route.v1"

ATTENTION_ROUTE = "ATTEND"

ATTENTION_STAGES = (
    "qk_dot",
    "scale",
    "mask",
    "softmax",
    "weighted_sum",
    "head_concat",
    "projection",
)

# These stages are mandatory for a numerically meaningful attention plan.  A
# missing or non-dispatchable critical kernel is a typed availability result,
# never a silent fallback.
ATTENTION_CRITICAL_STAGES = ("mask", "softmax", "weighted_sum")

ATTENTION_MASK_POLICIES = ("none", "causal", "padding", "causal_padding")
DEFAULT_MASK_POLICY = "causal"

# Declared control-plane defaults.  Kernel IDs that are not currently in
# ``spec/wave-capabilities.json`` stay explicit here and make the route
# UNAVAILABLE until a real dispatchable kernel is registered.
DEFAULT_STAGE_KERNELS = {
    "qk_dot": "mth.vector.dot256.f32",
    "scale": "mth.vector.axpy256.f32",
    "mask": "mth.attention.mask.f32",
    "softmax": "mth.attention.softmax.stable.f32",
    "weighted_sum": "mth.attention.weighted.sum.f32",
    "head_concat": "mth.attention.head.concat.f32",
    "projection": "mth.matvec256.full.f32",
}

ATTENTION_STATUS_PLANNED = "PLANNED"
ATTENTION_STATUS_UNAVAILABLE = "UNAVAILABLE"

ATTENTION_REASON_INVALID_CONFIG = "invalid_config"
ATTENTION_REASON_INVALID_REQUEST = "invalid_request"
ATTENTION_REASON_INVALID_MASK_POLICY = "invalid_mask_policy"
ATTENTION_REASON_UNKNOWN_KERNEL = "unknown_kernel"
ATTENTION_REASON_KERNEL_NOT_NATIVE_VERIFIED = "kernel_not_native_verified"
ATTENTION_REASON_KERNEL_NOT_CI_VERIFIED = "kernel_not_ci_verified"
ATTENTION_REASON_MASK_UNAVAILABLE = "mask_kernel_unavailable"
ATTENTION_REASON_SOFTMAX_UNAVAILABLE = "softmax_kernel_unavailable"
ATTENTION_REASON_WEIGHTED_SUM_UNAVAILABLE = "weighted_sum_kernel_unavailable"
ATTENTION_REASON_STEP_LIMIT = "step_limit_exceeded"
ATTENTION_REASON_WORKSPACE = "unsupported_workspace"
ATTENTION_REASON_PLAN_REJECTED = "plan_rejected"
ATTENTION_REASON_ROUTE_UNAVAILABLE = "route_unavailable"

_CRITICAL_UNAVAILABLE_REASONS = {
    "mask": ATTENTION_REASON_MASK_UNAVAILABLE,
    "softmax": ATTENTION_REASON_SOFTMAX_UNAVAILABLE,
    "weighted_sum": ATTENTION_REASON_WEIGHTED_SUM_UNAVAILABLE,
}

_STAGE_SPEC_FIELDS = frozenset({
    "kernel_id", "name", "inputs", "outputs", "depends_on",
})


class AttentionControllerError(ValueError):
    """Base class for attention controller configuration and routing failures."""

    reason = "attention_controller_error"

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason or type(self).reason


class AttentionConfigError(AttentionControllerError):
    """The controller was configured with an invalid stage or bound."""

    reason = ATTENTION_REASON_INVALID_CONFIG


class AttentionRequestError(AttentionControllerError):
    """A route request is malformed or rejected by the plan contract."""

    reason = ATTENTION_REASON_INVALID_REQUEST


class AttentionMaskError(AttentionRequestError):
    """The requested attention mask policy is not declared."""

    reason = ATTENTION_REASON_INVALID_MASK_POLICY


class AttentionKernelError(AttentionControllerError):
    """A non-critical route stage names an absent or non-dispatchable kernel."""

    reason = ATTENTION_REASON_UNKNOWN_KERNEL


class AttentionStepLimitError(AttentionControllerError):
    """A route exceeds the controller's bounded step count."""

    reason = ATTENTION_REASON_STEP_LIMIT


class AttentionWorkspaceError(AttentionControllerError):
    """A route exceeds its workspace budget or requests too little space."""

    reason = ATTENTION_REASON_WORKSPACE


class AttentionUnavailableError(AttentionControllerError):
    """A caller required a plan from a typed UNAVAILABLE route."""

    reason = ATTENTION_REASON_ROUTE_UNAVAILABLE


@dataclass(frozen=True)
class AttentionStageSpec:
    """One attention stage override; empty fields are filled deterministically.

    ``kernel_id`` is mandatory.  When ``name`` is omitted the controller uses
    ``attention.<stage>``.  When ``inputs``/``outputs`` are omitted the
    controller uses the declared typed dataflow for that stage.  When
    ``depends_on`` is omitted the stage depends on the previous stage.
    """

    kernel_id: str
    name: str | None = None
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kernel_id": self.kernel_id,
            "name": self.name,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "depends_on": list(self.depends_on),
        }


def plan_digest(plan: MthPlan) -> str:
    """Return the deterministic SHA-256 digest of a plan document."""
    if not isinstance(plan, MthPlan):
        raise AttentionRequestError("plan must be an MthPlan")
    document = plan.to_dict()
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def _require_bound(value: Any, name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AttentionConfigError(f"{name} must be an integer >= {minimum}")
    return value


def _require_request_bound(value: Any, name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AttentionRequestError(f"{name} must be an integer >= {minimum}")
    return value


def _normalise_mask_policy(value: Any) -> str:
    if not isinstance(value, str):
        raise AttentionMaskError("mask_policy must be a string")
    policy = value.lower()
    if policy not in ATTENTION_MASK_POLICIES:
        raise AttentionMaskError(
            f"unknown attention mask policy: {value!r}; expected one of "
            f"{', '.join(ATTENTION_MASK_POLICIES)}"
        )
    return policy


def _active_stages(mask_policy: str) -> tuple[str, ...]:
    return tuple(
        stage
        for stage in ATTENTION_STAGES
        if stage != "mask" or mask_policy != "none"
    )


def _text_tuple(value: Any, name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raise AttentionConfigError(f"{name} must be a sequence of typed names")
    if not isinstance(value, (tuple, list)):
        raise AttentionConfigError(f"{name} must be a sequence of typed names")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise AttentionConfigError(
                f"{name} entry {index} must be a non-empty string"
            )
        result.append(item)
    return tuple(result)


def _normalise_stage(stage: str, value: Any) -> AttentionStageSpec:
    if isinstance(value, AttentionStageSpec):
        if not isinstance(value.kernel_id, str) or not value.kernel_id:
            raise AttentionConfigError(
                f"stage {stage!r} has no kernel_id"
            )
        return value
    if isinstance(value, str):
        if not value:
            raise AttentionConfigError(f"stage {stage!r} has no kernel_id")
        return AttentionStageSpec(kernel_id=value)
    if isinstance(value, Mapping):
        unknown = sorted(key for key in value if key not in _STAGE_SPEC_FIELDS)
        if unknown:
            raise AttentionConfigError(
                f"stage {stage!r} has unknown fields: {', '.join(unknown)}"
            )
        kernel_id = value.get("kernel_id", "")
        if not isinstance(kernel_id, str) or not kernel_id:
            raise AttentionConfigError(f"stage {stage!r} has no kernel_id")
        name = value.get("name")
        if name is not None and (not isinstance(name, str) or not name):
            raise AttentionConfigError(
                f"stage {stage!r} name must be a non-empty string or None"
            )
        return AttentionStageSpec(
            kernel_id=kernel_id,
            name=name,
            inputs=_text_tuple(value.get("inputs", ()), f"stage {stage!r} inputs"),
            outputs=_text_tuple(
                value.get("outputs", ()), f"stage {stage!r} outputs"
            ),
            depends_on=_text_tuple(
                value.get("depends_on", ()), f"stage {stage!r} depends_on"
            ),
        )
    raise AttentionConfigError(
        f"stage {stage!r} must be a kernel id, mapping, or AttentionStageSpec"
    )


def _default_stage_step(
    stage: str,
    kernel_id: str,
    mask_policy: str,
    previous_name: str | None,
    previous_output: str | None,
) -> AttentionStageSpec:
    step_name = f"attention.{stage.replace('_', '-')}"
    if stage == "qk_dot":
        inputs = (
            "f32[256].attention.query",
            "f32[256].attention.key",
        )
    elif stage == "weighted_sum":
        inputs = (previous_output, "f32[256].attention.value")
    else:
        inputs = (previous_output,)

    if stage == "qk_dot":
        outputs = ("f32[256].attention.qk.scores",)
    elif stage == "scale":
        outputs = ("f32[256].attention.qk.scaled",)
    elif stage == "mask":
        policy_token = mask_policy.replace("_", ".")
        outputs = (f"f32[256].attention.qk.masked.{policy_token}",)
    elif stage == "softmax":
        outputs = ("f32[256].attention.weights",)
    elif stage == "weighted_sum":
        outputs = ("f32[256].attention.head.context",)
    elif stage == "head_concat":
        outputs = ("f32[256].attention.concat.context",)
    else:
        outputs = ("f32[256].attention.projected",)

    depends_on: tuple[str, ...] = ()
    if previous_name is not None:
        depends_on = (previous_name,)
    return AttentionStageSpec(
        kernel_id=kernel_id,
        name=step_name,
        inputs=tuple(inputs),
        outputs=outputs,
        depends_on=depends_on,
    )


def _merge_stage(
    override: AttentionStageSpec, default: AttentionStageSpec,
) -> AttentionStageSpec:
    return AttentionStageSpec(
        kernel_id=override.kernel_id,
        name=override.name or default.name,
        inputs=override.inputs or default.inputs,
        outputs=override.outputs or default.outputs,
        depends_on=override.depends_on or default.depends_on,
    )


@dataclass(frozen=True)
class AttentionRouteResult:
    """Typed outcome of composing the attention route.

    A ``PLANNED`` result carries a registry-validated plan and its digest.  An
    ``UNAVAILABLE`` result carries no plan and a stable reason code.  Neither
    form is execution evidence.
    """

    status: str
    mask_policy: str
    stages: tuple[str, ...]
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
        return self.status == ATTENTION_STATUS_PLANNED

    def require_plan(self) -> MthPlan:
        """Return the route plan or raise :class:`AttentionUnavailableError`."""
        if self.plan is None:
            raise AttentionUnavailableError(
                f"{ATTENTION_ROUTE} route is {self.status}: "
                f"{self.detail or self.reason}",
                reason=self.reason or ATTENTION_REASON_ROUTE_UNAVAILABLE,
            )
        return self.plan

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ATTENTION_ROUTE_SCHEMA,
            "route": ATTENTION_ROUTE,
            "status": self.status,
            "mask_policy": self.mask_policy,
            "stages": list(self.stages),
            "kernel_ids": list(self.kernel_ids),
            "step_count": self.step_count,
            "workspace_words": self.workspace_words,
            "deterministic": self.deterministic,
            "plan_digest": self.plan_digest,
            "reason": self.reason,
            "detail": self.detail,
            "plan": None if self.plan is None else self.plan.to_dict(),
        }


class AttentionController:
    """Compose the attention vertical slice into a validated MTH plan.

    ``stages`` optionally overrides the kernel id, step name, typed inputs,
    outputs, or dependencies of one stage.  Overrides are normalized before
    use; a route with more than ``max_steps`` active steps is rejected at
    request time.

    ``max_workspace_words`` is an optional hard controller budget.  Request
    workspace below the plan's required workspace is always rejected.
    """

    def __init__(
        self,
        registry: MthRegistry,
        stages: Mapping[str, Any] | None = None,
        *,
        max_steps: int = 8,
        max_workspace_words: int | None = None,
        mask_policy: str = DEFAULT_MASK_POLICY,
    ) -> None:
        if not isinstance(registry, MthRegistry):
            raise AttentionConfigError("registry must be an MthRegistry")
        self.registry = registry
        self.max_steps = _require_bound(max_steps, "max_steps", minimum=1)
        if max_workspace_words is None:
            self.max_workspace_words = None
        else:
            self.max_workspace_words = _require_bound(
                max_workspace_words, "max_workspace_words", minimum=0
            )
        self.default_mask_policy = _normalise_mask_policy(mask_policy)

        table = {
            stage: AttentionStageSpec(kernel_id=kernel_id)
            for stage, kernel_id in DEFAULT_STAGE_KERNELS.items()
        }
        if stages is not None:
            if not isinstance(stages, Mapping):
                raise AttentionConfigError("stages must be a mapping")
            for raw_stage, raw_value in stages.items():
                if not isinstance(raw_stage, str):
                    raise AttentionConfigError("stage names must be strings")
                stage = raw_stage.lower()
                if stage not in ATTENTION_STAGES:
                    raise AttentionConfigError(
                        f"unknown attention stage: {raw_stage!r}"
                    )
                table[stage] = _normalise_stage(stage, raw_value)
        self._stages = {
            stage: table[stage] for stage in ATTENTION_STAGES
        }

    @property
    def stages(self) -> tuple[str, ...]:
        return ATTENTION_STAGES

    @property
    def critical_stages(self) -> tuple[str, ...]:
        return ATTENTION_CRITICAL_STAGES

    @property
    def kernel_ids(self) -> tuple[str, ...]:
        return tuple(self._stages[stage].kernel_id for stage in ATTENTION_STAGES)

    def _unavailable(
        self,
        resolved: tuple[tuple[str, AttentionStageSpec], ...],
        mask_policy: str,
        reason: str,
        detail: str,
    ) -> AttentionRouteResult:
        return AttentionRouteResult(
            status=ATTENTION_STATUS_UNAVAILABLE,
            mask_policy=mask_policy,
            stages=tuple(stage for stage, _ in resolved),
            kernel_ids=tuple(step.kernel_id for _, step in resolved),
            reason=reason,
            detail=detail,
            step_count=len(resolved),
        )

    def _check_dispatchable(
        self,
        resolved: tuple[tuple[str, AttentionStageSpec], ...],
        mask_policy: str,
    ) -> AttentionRouteResult | None:
        for stage, step in resolved:
            descriptor = self.registry.lookup(step.kernel_id)
            critical = stage in ATTENTION_CRITICAL_STAGES
            if descriptor is None:
                if critical:
                    return self._unavailable(
                        resolved,
                        mask_policy,
                        _CRITICAL_UNAVAILABLE_REASONS[stage],
                        f"{stage} kernel {step.kernel_id!r} is not registered",
                    )
                raise AttentionKernelError(
                    f"{stage} stage names unknown kernel {step.kernel_id!r}",
                    reason=ATTENTION_REASON_UNKNOWN_KERNEL,
                )
            if critical:
                if descriptor.status != "native_verified":
                    return self._unavailable(
                        resolved,
                        mask_policy,
                        _CRITICAL_UNAVAILABLE_REASONS[stage],
                        f"{stage} kernel {step.kernel_id!r} has status "
                        f"{descriptor.status!r}, not 'native_verified'",
                    )
                if not descriptor.ci_verified:
                    return self._unavailable(
                        resolved,
                        mask_policy,
                        _CRITICAL_UNAVAILABLE_REASONS[stage],
                        f"{stage} kernel {step.kernel_id!r} is not CI-verified",
                    )
                continue
            if descriptor.status != "native_verified":
                raise AttentionKernelError(
                    f"{stage} stage kernel {step.kernel_id!r} has status "
                    f"{descriptor.status!r}, not 'native_verified'",
                    reason=ATTENTION_REASON_KERNEL_NOT_NATIVE_VERIFIED,
                )
            if not descriptor.ci_verified:
                raise AttentionKernelError(
                    f"{stage} stage kernel {step.kernel_id!r} is not CI-verified",
                    reason=ATTENTION_REASON_KERNEL_NOT_CI_VERIFIED,
                )
        return None

    def _step_document(self, step: AttentionStageSpec) -> dict[str, Any]:
        return {
            "name": step.name,
            "kernel_id": step.kernel_id,
            "inputs": list(step.inputs),
            "outputs": list(step.outputs),
            "depends_on": list(step.depends_on),
        }

    def route(
        self,
        *,
        plan_id: str | None = None,
        mask_policy: str | None = None,
        workspace_words: int | None = None,
        fuel: int | None = None,
        cancel_after: int | None = None,
    ) -> AttentionRouteResult:
        """Compose the attention plan or return a typed UNAVAILABLE result."""
        policy = (
            self.default_mask_policy
            if mask_policy is None
            else _normalise_mask_policy(mask_policy)
        )
        active = _active_stages(policy)
        if len(active) > self.max_steps:
            raise AttentionStepLimitError(
                f"{ATTENTION_ROUTE} route has {len(active)} active steps, "
                f"above the bounded maximum of {self.max_steps}",
                reason=ATTENTION_REASON_STEP_LIMIT,
            )

        resolved_steps: list[tuple[str, AttentionStageSpec]] = []
        previous_name: str | None = None
        previous_output: str | None = None
        for stage in active:
            override = self._stages[stage]
            default = _default_stage_step(
                stage,
                override.kernel_id,
                policy,
                previous_name,
                previous_output,
            )
            step = _merge_stage(override, default)
            resolved_steps.append((stage, step))
            previous_name = step.name
            previous_output = step.outputs[0]
        resolved = tuple(resolved_steps)

        unavailable = self._check_dispatchable(resolved, policy)
        if unavailable is not None:
            return unavailable

        if plan_id is None:
            plan_id = "attention.attend"
        if workspace_words is not None:
            workspace_words = _require_request_bound(
                workspace_words, "workspace_words", minimum=0
            )

        spec: dict[str, Any] = {
            "schema": PLAN_SPEC_SCHEMA,
            "plan_id": plan_id,
            "steps": [self._step_document(step) for _, step in resolved],
        }
        if fuel is not None:
            spec["fuel"] = fuel
        if cancel_after is not None:
            spec["cancel_after"] = cancel_after

        try:
            plan = self.registry.compose(spec)
        except MthPlanError as exc:
            raise AttentionRequestError(
                f"{ATTENTION_ROUTE} route plan was rejected: {exc}",
                reason=ATTENTION_REASON_PLAN_REJECTED,
            ) from exc

        required_workspace = plan.workspace_words
        if (
            self.max_workspace_words is not None
            and required_workspace > self.max_workspace_words
        ):
            raise AttentionWorkspaceError(
                f"{ATTENTION_ROUTE} route needs {required_workspace} workspace "
                f"words, above the controller budget of "
                f"{self.max_workspace_words}",
                reason=ATTENTION_REASON_WORKSPACE,
            )
        if workspace_words is not None:
            if workspace_words < required_workspace:
                raise AttentionWorkspaceError(
                    f"{ATTENTION_ROUTE} route needs at least "
                    f"{required_workspace} workspace words, got "
                    f"{workspace_words}",
                    reason=ATTENTION_REASON_WORKSPACE,
                )
            if workspace_words != required_workspace:
                spec["workspace_words"] = workspace_words
                try:
                    plan = self.registry.compose(spec)
                except MthPlanError as exc:
                    raise AttentionRequestError(
                        f"{ATTENTION_ROUTE} route plan was rejected: {exc}",
                        reason=ATTENTION_REASON_PLAN_REJECTED,
                    ) from exc

        digest = plan_digest(plan)
        return AttentionRouteResult(
            status=ATTENTION_STATUS_PLANNED,
            mask_policy=policy,
            stages=tuple(stage for stage, _ in resolved),
            kernel_ids=plan.kernel_ids,
            plan=plan,
            plan_digest=digest,
            workspace_words=plan.workspace_words,
            step_count=len(plan.steps),
            deterministic=plan.deterministic,
        )

    def compose(
        self,
        *,
        plan_id: str | None = None,
        mask_policy: str | None = None,
        workspace_words: int | None = None,
        fuel: int | None = None,
        cancel_after: int | None = None,
    ) -> AttentionRouteResult:
        """Alias of :meth:`route`; composition never executes the plan."""
        return self.route(
            plan_id=plan_id,
            mask_policy=mask_policy,
            workspace_words=workspace_words,
            fuel=fuel,
            cancel_after=cancel_after,
        )

    def availability(
        self, *, mask_policy: str | None = None,
    ) -> dict[str, Any]:
        """Return the typed attention route status without executing anything."""
        try:
            result = self.route(mask_policy=mask_policy)
        except AttentionControllerError as exc:
            policy = (
                self.default_mask_policy
                if mask_policy is None
                else str(mask_policy)
            )
            return {
                "route": ATTENTION_ROUTE,
                "status": "REJECTED",
                "reason": exc.reason,
                "detail": str(exc),
                "mask_policy": policy,
                "kernel_ids": list(self.kernel_ids),
            }
        return {
            "route": ATTENTION_ROUTE,
            "status": result.status,
            "reason": result.reason,
            "detail": result.detail,
            "mask_policy": result.mask_policy,
            "kernel_ids": list(result.kernel_ids),
            "plan_digest": result.plan_digest,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ATTENTION_CONTROLLER_SCHEMA,
            "route": ATTENTION_ROUTE,
            "stages": list(ATTENTION_STAGES),
            "critical_stages": list(ATTENTION_CRITICAL_STAGES),
            "mask_policies": list(ATTENTION_MASK_POLICIES),
            "default_mask_policy": self.default_mask_policy,
            "max_steps": self.max_steps,
            "max_workspace_words": self.max_workspace_words,
            "stage_kernels": {
                stage: self._stages[stage].kernel_id
                for stage in ATTENTION_STAGES
            },
        }


__all__ = [
    "ATTENTION_CONTROLLER_SCHEMA",
    "ATTENTION_CRITICAL_STAGES",
    "ATTENTION_MASK_POLICIES",
    "ATTENTION_REASON_INVALID_CONFIG",
    "ATTENTION_REASON_INVALID_MASK_POLICY",
    "ATTENTION_REASON_INVALID_REQUEST",
    "ATTENTION_REASON_KERNEL_NOT_CI_VERIFIED",
    "ATTENTION_REASON_KERNEL_NOT_NATIVE_VERIFIED",
    "ATTENTION_REASON_MASK_UNAVAILABLE",
    "ATTENTION_REASON_PLAN_REJECTED",
    "ATTENTION_REASON_ROUTE_UNAVAILABLE",
    "ATTENTION_REASON_SOFTMAX_UNAVAILABLE",
    "ATTENTION_REASON_STEP_LIMIT",
    "ATTENTION_REASON_UNKNOWN_KERNEL",
    "ATTENTION_REASON_WEIGHTED_SUM_UNAVAILABLE",
    "ATTENTION_REASON_WORKSPACE",
    "ATTENTION_ROUTE",
    "ATTENTION_ROUTE_SCHEMA",
    "ATTENTION_STAGES",
    "ATTENTION_STATUS_PLANNED",
    "ATTENTION_STATUS_UNAVAILABLE",
    "AttentionConfigError",
    "AttentionController",
    "AttentionControllerError",
    "AttentionKernelError",
    "AttentionMaskError",
    "AttentionRequestError",
    "AttentionRouteResult",
    "AttentionStageSpec",
    "AttentionStepLimitError",
    "AttentionUnavailableError",
    "AttentionWorkspaceError",
    "DEFAULT_MASK_POLICY",
    "DEFAULT_STAGE_KERNELS",
    "plan_digest",
]
