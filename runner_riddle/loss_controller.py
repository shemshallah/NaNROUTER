"""Host-only loss/gradient/optimizer plan controller over the MTH registry.

The controller maps the Tier 5 learning primitives required by
``docs/GAME_PLAN_MTH.md`` §3 onto explicit registered NaN16 kernels and
composes a validated :class:`~runner_riddle.mth_registry.MthPlan`:

``loss -> gradient_accumulate -> clip -> moving_average -> update``

It is a control-plane selector, not a math implementation: it performs no
numerical operation, executes no kernel, and offers no alternate execution
path.  A route result is either ``PLANNED`` with a validated plan and
deterministic plan digest, or ``UNAVAILABLE`` with a stable reason code.

The loss, gradient, clipping, moving-average, and optimizer kernels are not
registered in the current capability manifest.  A missing declared stage
kernel therefore produces a typed ``UNAVAILABLE`` result.  The controller never
substitutes host arithmetic, a Python optimizer, or an unregistered fallback.
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

LOSS_CONTROLLER_SCHEMA = "nanrouter.loss-controller.v1"
LOSS_ROUTE_SCHEMA = "nanrouter.loss-route.v1"

LOSS_ROUTE = "OPTIMIZE"

LOSS_STAGES = (
    "loss",
    "gradient_accumulate",
    "clip",
    "moving_average",
    "update",
)

LOSS_KINDS = ("cross_entropy", "nll")
DEFAULT_LOSS_KIND = "cross_entropy"

LOSS_OPTIMIZERS = ("adam", "momentum")
DEFAULT_OPTIMIZER = "adam"

# Declared kernel families per stage.  A stage whose declared family kernel is
# absent from the registry is a typed capability gap, not a host-math fallback.
LOSS_KIND_KERNELS = {
    "cross_entropy": "mth.loss.cross_entropy.f32",
    "nll": "mth.loss.nll.f32",
}
OPTIMIZER_KERNELS = {
    "adam": "mth.optimizer.adam.f32",
    "momentum": "mth.optimizer.momentum.f32",
}
DEFAULT_STAGE_KERNELS = {
    "loss": LOSS_KIND_KERNELS[DEFAULT_LOSS_KIND],
    "gradient_accumulate": "mth.gradient.accumulate.f32",
    "clip": "mth.gradient.clip.global_norm.f32",
    "moving_average": "mth.optimizer.moving_average.f32",
    "update": OPTIMIZER_KERNELS[DEFAULT_OPTIMIZER],
}
STAGE_KERNEL_FAMILIES = {
    "loss": tuple(LOSS_KIND_KERNELS.values()),
    "gradient_accumulate": (DEFAULT_STAGE_KERNELS["gradient_accumulate"],),
    "clip": (DEFAULT_STAGE_KERNELS["clip"],),
    "moving_average": (DEFAULT_STAGE_KERNELS["moving_average"],),
    "update": tuple(OPTIMIZER_KERNELS.values()),
}

LOSS_STATUS_PLANNED = "PLANNED"
LOSS_STATUS_UNAVAILABLE = "UNAVAILABLE"

LOSS_REASON_INVALID_CONFIG = "invalid_config"
LOSS_REASON_INVALID_REQUEST = "invalid_request"
LOSS_REASON_INVALID_LOSS_KIND = "invalid_loss_kind"
LOSS_REASON_INVALID_OPTIMIZER = "invalid_optimizer"
LOSS_REASON_UNKNOWN_KERNEL = "unknown_kernel"
LOSS_REASON_KERNEL_NOT_NATIVE_VERIFIED = "kernel_not_native_verified"
LOSS_REASON_KERNEL_NOT_CI_VERIFIED = "kernel_not_ci_verified"
LOSS_REASON_LOSS_UNAVAILABLE = "loss_kernel_unavailable"
LOSS_REASON_GRADIENT_ACCUMULATE_UNAVAILABLE = (
    "gradient_accumulate_kernel_unavailable"
)
LOSS_REASON_CLIP_UNAVAILABLE = "clip_kernel_unavailable"
LOSS_REASON_MOVING_AVERAGE_UNAVAILABLE = "moving_average_kernel_unavailable"
LOSS_REASON_UPDATE_UNAVAILABLE = "update_kernel_unavailable"
LOSS_REASON_STEP_LIMIT = "step_limit_exceeded"
LOSS_REASON_WORKSPACE = "unsupported_workspace"
LOSS_REASON_PLAN_REJECTED = "plan_rejected"
LOSS_REASON_ROUTE_UNAVAILABLE = "route_unavailable"

_STAGE_UNAVAILABLE_REASONS = {
    "loss": LOSS_REASON_LOSS_UNAVAILABLE,
    "gradient_accumulate": LOSS_REASON_GRADIENT_ACCUMULATE_UNAVAILABLE,
    "clip": LOSS_REASON_CLIP_UNAVAILABLE,
    "moving_average": LOSS_REASON_MOVING_AVERAGE_UNAVAILABLE,
    "update": LOSS_REASON_UPDATE_UNAVAILABLE,
}

_STAGE_SPEC_FIELDS = frozenset({
    "kernel_id", "name", "inputs", "outputs", "depends_on",
})

_STAGE_STEP_NAMES = {
    "loss": "loss.compute",
    "gradient_accumulate": "loss.gradient-accumulate",
    "clip": "loss.clip",
    "moving_average": "loss.moving-average",
    "update": "loss.update",
}


class LossControllerError(ValueError):
    """Base class for loss controller configuration and routing failures."""

    reason = "loss_controller_error"

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason or type(self).reason


class LossConfigError(LossControllerError):
    """The controller was configured with an invalid stage or bound."""

    reason = LOSS_REASON_INVALID_CONFIG


class LossRequestError(LossControllerError):
    """A route request is malformed or rejected by the plan contract."""

    reason = LOSS_REASON_INVALID_REQUEST


class LossKindError(LossRequestError):
    """The requested loss kind is not declared."""

    reason = LOSS_REASON_INVALID_LOSS_KIND


class LossOptimizerError(LossRequestError):
    """The requested optimizer is not declared."""

    reason = LOSS_REASON_INVALID_OPTIMIZER


class LossKernelError(LossControllerError):
    """A route names an unknown or non-dispatchable kernel."""

    reason = LOSS_REASON_UNKNOWN_KERNEL


class LossStepLimitError(LossControllerError):
    """A route exceeds the controller's bounded step count."""

    reason = LOSS_REASON_STEP_LIMIT


class LossWorkspaceError(LossControllerError):
    """A route exceeds its workspace budget or requests too little space."""

    reason = LOSS_REASON_WORKSPACE


class LossUnavailableError(LossControllerError):
    """A caller required a plan from a typed UNAVAILABLE route."""

    reason = LOSS_REASON_ROUTE_UNAVAILABLE


@dataclass(frozen=True)
class LossStageSpec:
    """One loss/optimizer stage override; empty fields are filled in order.

    ``kernel_id`` is mandatory.  When ``name`` is omitted the controller uses
    ``loss.<stage>``.  When ``inputs``/``outputs`` are omitted the controller
    uses the declared typed dataflow for that stage.  When ``depends_on`` is
    omitted the stage depends on the previous stage.
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
        raise LossRequestError("plan must be an MthPlan")
    document = plan.to_dict()
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def _require_bound(value: Any, name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise LossConfigError(f"{name} must be an integer >= {minimum}")
    return value


def _require_request_bound(value: Any, name: str, *,
                           minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise LossRequestError(f"{name} must be an integer >= {minimum}")
    return value


def _normalise_loss_kind(value: Any) -> str:
    if not isinstance(value, str):
        raise LossKindError("loss_kind must be a string")
    kind = value.lower()
    if kind not in LOSS_KINDS:
        raise LossKindError(
            f"unknown loss kind: {value!r}; expected one of "
            f"{', '.join(LOSS_KINDS)}"
        )
    return kind


def _normalise_optimizer(value: Any) -> str:
    if not isinstance(value, str):
        raise LossOptimizerError("optimizer must be a string")
    optimizer = value.lower()
    if optimizer not in LOSS_OPTIMIZERS:
        raise LossOptimizerError(
            f"unknown optimizer: {value!r}; expected one of "
            f"{', '.join(LOSS_OPTIMIZERS)}"
        )
    return optimizer


def _text_tuple(value: Any, name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raise LossConfigError(f"{name} must be a sequence of typed names")
    if not isinstance(value, (tuple, list)):
        raise LossConfigError(f"{name} must be a sequence of typed names")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise LossConfigError(
                f"{name} entry {index} must be a non-empty string"
            )
        result.append(item)
    return tuple(result)


def _normalise_stage(stage: str, value: Any) -> LossStageSpec:
    if isinstance(value, LossStageSpec):
        if not isinstance(value.kernel_id, str) or not value.kernel_id:
            raise LossConfigError(f"stage {stage!r} has no kernel_id")
        return value
    if isinstance(value, str):
        if not value:
            raise LossConfigError(f"stage {stage!r} has no kernel_id")
        return LossStageSpec(kernel_id=value)
    if isinstance(value, Mapping):
        unknown = sorted(key for key in value if key not in _STAGE_SPEC_FIELDS)
        if unknown:
            raise LossConfigError(
                f"stage {stage!r} has unknown fields: {', '.join(unknown)}"
            )
        kernel_id = value.get("kernel_id", "")
        if not isinstance(kernel_id, str) or not kernel_id:
            raise LossConfigError(f"stage {stage!r} has no kernel_id")
        name = value.get("name")
        if name is not None and (not isinstance(name, str) or not name):
            raise LossConfigError(
                f"stage {stage!r} name must be a non-empty string or None"
            )
        return LossStageSpec(
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
    raise LossConfigError(
        f"stage {stage!r} must be a kernel id, mapping, or LossStageSpec"
    )


def _stage_kernels(loss_kind: str, optimizer: str) -> dict[str, str]:
    """Return the declared default kernel id per stage for one variant."""
    return {
        "loss": LOSS_KIND_KERNELS[loss_kind],
        "gradient_accumulate": DEFAULT_STAGE_KERNELS["gradient_accumulate"],
        "clip": DEFAULT_STAGE_KERNELS["clip"],
        "moving_average": DEFAULT_STAGE_KERNELS["moving_average"],
        "update": OPTIMIZER_KERNELS[optimizer],
    }


def _default_stage_step(
    stage: str,
    kernel_id: str,
    loss_kind: str,
    optimizer: str,
    previous_name: str | None,
    previous_output: str | None,
) -> LossStageSpec:
    step_name = _STAGE_STEP_NAMES[stage]
    loss_token = loss_kind

    if stage == "loss":
        inputs = (
            "f32[256].loss.logits",
            "u32[256].loss.targets",
        )
        outputs = (
            f"f32[256].loss.{loss_token}.gradient",
            f"f32.loss.{loss_token}.value",
        )
    elif stage == "gradient_accumulate":
        inputs = (
            previous_output,
            "f32[256].optimizer.gradient.accumulator",
        )
        outputs = ("f32[256].optimizer.gradient.accumulated",)
    elif stage == "clip":
        inputs = (previous_output,)
        outputs = ("f32[256].optimizer.gradient.clipped",)
    elif stage == "moving_average":
        inputs = (
            previous_output,
            "f32[256].optimizer.moving_average.state",
        )
        outputs = ("f32[256].optimizer.moving_average.updated",)
    else:
        inputs = (
            previous_output,
            f"f32[256].optimizer.{optimizer}.state",
            "f32[256].model.parameters",
        )
        outputs = (
            f"f32[256].model.parameters.{optimizer}.updated",
        )

    depends_on: tuple[str, ...] = ()
    if previous_name is not None:
        depends_on = (previous_name,)
    return LossStageSpec(
        kernel_id=kernel_id,
        name=step_name,
        inputs=tuple(inputs),
        outputs=tuple(outputs),
        depends_on=depends_on,
    )


def _merge_stage(
    override: LossStageSpec, default: LossStageSpec,
) -> LossStageSpec:
    return LossStageSpec(
        kernel_id=override.kernel_id,
        name=override.name or default.name,
        inputs=override.inputs or default.inputs,
        outputs=override.outputs or default.outputs,
        depends_on=override.depends_on or default.depends_on,
    )


@dataclass(frozen=True)
class LossRouteResult:
    """Typed outcome of composing one loss/optimizer route.

    A ``PLANNED`` result carries a registry-validated plan and its digest.  An
    ``UNAVAILABLE`` result carries no plan and a stable reason code.  Neither
    form is execution evidence.
    """

    status: str
    loss_kind: str
    optimizer: str
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
        return self.status == LOSS_STATUS_PLANNED

    def require_plan(self) -> MthPlan:
        """Return the route plan or raise :class:`LossUnavailableError`."""
        if self.plan is None:
            raise LossUnavailableError(
                f"{LOSS_ROUTE} route is {self.status}: "
                f"{self.detail or self.reason}",
                reason=self.reason or LOSS_REASON_ROUTE_UNAVAILABLE,
            )
        return self.plan

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": LOSS_ROUTE_SCHEMA,
            "route": LOSS_ROUTE,
            "status": self.status,
            "loss_kind": self.loss_kind,
            "optimizer": self.optimizer,
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


class LossOptimizerController:
    """Compose a loss/gradient/optimizer route into a validated MTH plan.

    ``stages`` optionally overrides the kernel id, step name, typed inputs,
    outputs, or dependencies of one stage.  Overrides are normalized before
    use; a route with more than ``max_steps`` stages is rejected at request
    time.

    ``max_workspace_words`` is an optional hard controller budget.  Request
    workspace below the plan's required workspace is always rejected.
    ``loss_kind`` and ``optimizer`` select the declared default kernels for the
    loss and update stages; a stage override replaces that selection.
    """

    def __init__(
        self,
        registry: MthRegistry,
        stages: Mapping[str, Any] | None = None,
        *,
        max_steps: int = 8,
        max_workspace_words: int | None = None,
        loss_kind: str = DEFAULT_LOSS_KIND,
        optimizer: str = DEFAULT_OPTIMIZER,
    ) -> None:
        if not isinstance(registry, MthRegistry):
            raise LossConfigError("registry must be an MthRegistry")
        self.registry = registry
        self.max_steps = _require_bound(max_steps, "max_steps", minimum=1)
        if max_workspace_words is None:
            self.max_workspace_words = None
        else:
            self.max_workspace_words = _require_bound(
                max_workspace_words, "max_workspace_words", minimum=0
            )
        self.default_loss_kind = _normalise_loss_kind(loss_kind)
        self.default_optimizer = _normalise_optimizer(optimizer)

        overrides: dict[str, LossStageSpec] = {}
        if stages is not None:
            if not isinstance(stages, Mapping):
                raise LossConfigError("stages must be a mapping")
            for raw_stage, raw_value in stages.items():
                if not isinstance(raw_stage, str):
                    raise LossConfigError("stage names must be strings")
                stage = raw_stage.lower()
                if stage not in LOSS_STAGES:
                    raise LossConfigError(
                        f"unknown loss stage: {raw_stage!r}"
                    )
                overrides[stage] = _normalise_stage(stage, raw_value)
        self._overrides = {
            stage: overrides[stage]
            for stage in LOSS_STAGES
            if stage in overrides
        }

    @property
    def stages(self) -> tuple[str, ...]:
        return LOSS_STAGES

    @property
    def loss_kinds(self) -> tuple[str, ...]:
        return LOSS_KINDS

    @property
    def optimizers(self) -> tuple[str, ...]:
        return LOSS_OPTIMIZERS

    def kernel_ids(
        self, *, loss_kind: str | None = None,
        optimizer: str | None = None,
    ) -> tuple[str, ...]:
        """Return the configured kernel id per stage for one variant."""
        kind = (
            self.default_loss_kind
            if loss_kind is None
            else _normalise_loss_kind(loss_kind)
        )
        selected_optimizer = (
            self.default_optimizer
            if optimizer is None
            else _normalise_optimizer(optimizer)
        )
        defaults = _stage_kernels(kind, selected_optimizer)
        return tuple(
            self._overrides[stage].kernel_id
            if stage in self._overrides
            else defaults[stage]
            for stage in LOSS_STAGES
        )

    def _resolve_steps(
        self, loss_kind: str, optimizer: str,
    ) -> tuple[tuple[str, LossStageSpec], ...]:
        defaults = _stage_kernels(loss_kind, optimizer)
        resolved: list[tuple[str, LossStageSpec]] = []
        previous_name: str | None = None
        previous_output: str | None = None
        for stage in LOSS_STAGES:
            default = _default_stage_step(
                stage,
                defaults[stage],
                loss_kind,
                optimizer,
                previous_name,
                previous_output,
            )
            override = self._overrides.get(stage)
            step = default if override is None else _merge_stage(override, default)
            resolved.append((stage, step))
            previous_name = step.name
            previous_output = step.outputs[0]
        return tuple(resolved)

    def _unavailable(
        self,
        resolved: tuple[tuple[str, LossStageSpec], ...],
        loss_kind: str,
        optimizer: str,
        reason: str,
        detail: str,
    ) -> LossRouteResult:
        return LossRouteResult(
            status=LOSS_STATUS_UNAVAILABLE,
            loss_kind=loss_kind,
            optimizer=optimizer,
            stages=tuple(stage for stage, _ in resolved),
            kernel_ids=tuple(step.kernel_id for _, step in resolved),
            reason=reason,
            detail=detail,
            step_count=len(resolved),
        )

    def _check_dispatchable(
        self,
        resolved: tuple[tuple[str, LossStageSpec], ...],
        loss_kind: str,
        optimizer: str,
    ) -> LossRouteResult | None:
        for stage, step in resolved:
            descriptor = self.registry.lookup(step.kernel_id)
            if descriptor is None:
                if step.kernel_id in STAGE_KERNEL_FAMILIES[stage]:
                    return self._unavailable(
                        resolved,
                        loss_kind,
                        optimizer,
                        _STAGE_UNAVAILABLE_REASONS[stage],
                        f"{stage} kernel {step.kernel_id!r} is not registered",
                    )
                raise LossKernelError(
                    f"{stage} stage names unknown kernel {step.kernel_id!r}",
                    reason=LOSS_REASON_UNKNOWN_KERNEL,
                )
            if descriptor.status != "native_verified":
                raise LossKernelError(
                    f"{stage} stage kernel {step.kernel_id!r} has status "
                    f"{descriptor.status!r}, not 'native_verified'",
                    reason=LOSS_REASON_KERNEL_NOT_NATIVE_VERIFIED,
                )
            if not descriptor.ci_verified:
                raise LossKernelError(
                    f"{stage} stage kernel {step.kernel_id!r} is not CI-verified",
                    reason=LOSS_REASON_KERNEL_NOT_CI_VERIFIED,
                )
        return None

    def _step_document(self, step: LossStageSpec) -> dict[str, Any]:
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
        loss_kind: str | None = None,
        optimizer: str | None = None,
        workspace_words: int | None = None,
        fuel: int | None = None,
        cancel_after: int | None = None,
    ) -> LossRouteResult:
        """Compose one loss/optimizer plan or return typed UNAVAILABLE."""
        kind = (
            self.default_loss_kind
            if loss_kind is None
            else _normalise_loss_kind(loss_kind)
        )
        selected_optimizer = (
            self.default_optimizer
            if optimizer is None
            else _normalise_optimizer(optimizer)
        )

        if len(LOSS_STAGES) > self.max_steps:
            raise LossStepLimitError(
                f"{LOSS_ROUTE} route has {len(LOSS_STAGES)} steps, above the "
                f"bounded maximum of {self.max_steps}",
                reason=LOSS_REASON_STEP_LIMIT,
            )

        resolved = self._resolve_steps(kind, selected_optimizer)
        unavailable = self._check_dispatchable(
            resolved, kind, selected_optimizer
        )
        if unavailable is not None:
            return unavailable

        if plan_id is None:
            plan_id = "loss.optimize"
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
            raise LossRequestError(
                f"{LOSS_ROUTE} route plan was rejected: {exc}",
                reason=LOSS_REASON_PLAN_REJECTED,
            ) from exc

        required_workspace = plan.workspace_words
        if (
            self.max_workspace_words is not None
            and required_workspace > self.max_workspace_words
        ):
            raise LossWorkspaceError(
                f"{LOSS_ROUTE} route needs {required_workspace} workspace "
                f"words, above the controller budget of "
                f"{self.max_workspace_words}",
                reason=LOSS_REASON_WORKSPACE,
            )
        if workspace_words is not None:
            if workspace_words < required_workspace:
                raise LossWorkspaceError(
                    f"{LOSS_ROUTE} route needs at least {required_workspace} "
                    f"workspace words, got {workspace_words}",
                    reason=LOSS_REASON_WORKSPACE,
                )
            if workspace_words != required_workspace:
                spec["workspace_words"] = workspace_words
                try:
                    plan = self.registry.compose(spec)
                except MthPlanError as exc:
                    raise LossRequestError(
                        f"{LOSS_ROUTE} route plan was rejected: {exc}",
                        reason=LOSS_REASON_PLAN_REJECTED,
                    ) from exc

        digest = plan_digest(plan)
        return LossRouteResult(
            status=LOSS_STATUS_PLANNED,
            loss_kind=kind,
            optimizer=selected_optimizer,
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
        loss_kind: str | None = None,
        optimizer: str | None = None,
        workspace_words: int | None = None,
        fuel: int | None = None,
        cancel_after: int | None = None,
    ) -> LossRouteResult:
        """Alias of :meth:`route`; composition never executes the plan."""
        return self.route(
            plan_id=plan_id,
            loss_kind=loss_kind,
            optimizer=optimizer,
            workspace_words=workspace_words,
            fuel=fuel,
            cancel_after=cancel_after,
        )

    def availability(
        self, *, loss_kind: str | None = None,
        optimizer: str | None = None,
    ) -> dict[str, Any]:
        """Return the typed route status without executing anything."""
        try:
            result = self.route(loss_kind=loss_kind, optimizer=optimizer)
        except LossControllerError as exc:
            kind = (
                self.default_loss_kind
                if loss_kind is None
                else str(loss_kind)
            )
            selected_optimizer = (
                self.default_optimizer
                if optimizer is None
                else str(optimizer)
            )
            return {
                "route": LOSS_ROUTE,
                "status": "REJECTED",
                "reason": exc.reason,
                "detail": str(exc),
                "loss_kind": kind,
                "optimizer": selected_optimizer,
                "kernel_ids": list(self.kernel_ids()),
            }
        return {
            "route": LOSS_ROUTE,
            "status": result.status,
            "reason": result.reason,
            "detail": result.detail,
            "loss_kind": result.loss_kind,
            "optimizer": result.optimizer,
            "kernel_ids": list(result.kernel_ids),
            "plan_digest": result.plan_digest,
        }

    def to_dict(self) -> dict[str, Any]:
        defaults = _stage_kernels(
            self.default_loss_kind, self.default_optimizer
        )
        stage_kernels = {
            stage: (
                self._overrides[stage].kernel_id
                if stage in self._overrides
                else defaults[stage]
            )
            for stage in LOSS_STAGES
        }
        return {
            "schema": LOSS_CONTROLLER_SCHEMA,
            "route": LOSS_ROUTE,
            "stages": list(LOSS_STAGES),
            "loss_kinds": list(LOSS_KINDS),
            "optimizers": list(LOSS_OPTIMIZERS),
            "default_loss_kind": self.default_loss_kind,
            "default_optimizer": self.default_optimizer,
            "max_steps": self.max_steps,
            "max_workspace_words": self.max_workspace_words,
            "stage_kernels": stage_kernels,
            "stage_kernel_families": {
                stage: list(STAGE_KERNEL_FAMILIES[stage])
                for stage in LOSS_STAGES
            },
            "loss_kind_kernels": dict(LOSS_KIND_KERNELS),
            "optimizer_kernels": dict(OPTIMIZER_KERNELS),
        }


__all__ = [
    "DEFAULT_LOSS_KIND",
    "DEFAULT_OPTIMIZER",
    "DEFAULT_STAGE_KERNELS",
    "LOSS_CONTROLLER_SCHEMA",
    "LOSS_KINDS",
    "LOSS_KIND_KERNELS",
    "LOSS_OPTIMIZERS",
    "LOSS_REASON_CLIP_UNAVAILABLE",
    "LOSS_REASON_GRADIENT_ACCUMULATE_UNAVAILABLE",
    "LOSS_REASON_INVALID_CONFIG",
    "LOSS_REASON_INVALID_LOSS_KIND",
    "LOSS_REASON_INVALID_OPTIMIZER",
    "LOSS_REASON_INVALID_REQUEST",
    "LOSS_REASON_KERNEL_NOT_CI_VERIFIED",
    "LOSS_REASON_KERNEL_NOT_NATIVE_VERIFIED",
    "LOSS_REASON_LOSS_UNAVAILABLE",
    "LOSS_REASON_MOVING_AVERAGE_UNAVAILABLE",
    "LOSS_REASON_PLAN_REJECTED",
    "LOSS_REASON_ROUTE_UNAVAILABLE",
    "LOSS_REASON_STEP_LIMIT",
    "LOSS_REASON_UNKNOWN_KERNEL",
    "LOSS_REASON_UPDATE_UNAVAILABLE",
    "LOSS_REASON_WORKSPACE",
    "LOSS_ROUTE",
    "LOSS_ROUTE_SCHEMA",
    "LOSS_STAGES",
    "LOSS_STATUS_PLANNED",
    "LOSS_STATUS_UNAVAILABLE",
    "LossConfigError",
    "LossControllerError",
    "LossKindError",
    "LossKernelError",
    "LossOptimizerError",
    "LossOptimizerController",
    "LossRequestError",
    "LossRouteResult",
    "LossStageSpec",
    "LossStepLimitError",
    "LossUnavailableError",
    "LossWorkspaceError",
    "OPTIMIZER_KERNELS",
    "STAGE_KERNEL_FAMILIES",
    "plan_digest",
]
