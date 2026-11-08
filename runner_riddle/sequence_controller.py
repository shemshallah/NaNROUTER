"""Host-only token/sequence plan controller over the MTH registry.

The controller maps the token and sequence operations required by
``docs/GAME_PLAN_MTH.md`` §4 onto explicit registered NaN16 kernels and
composes a validated :class:`~runner_riddle.mth_registry.MthPlan`:

``embedding_gather -> position_add -> slice_window -> mask_apply ->
ngram_build -> [head_concat]``

It is a control-plane selector, not a math or token implementation: it performs
no numerical operation, no token indexing, no position arithmetic, no slicing,
no n-gram construction, executes no kernel, and offers no alternate execution
path.  A route result is either ``PLANNED`` with a validated plan and
deterministic plan digest, or ``UNAVAILABLE`` with a stable reason code.

The embedding-gather, position-add, slice-window, mask-apply, n-gram-build, and
head-concat kernels are not registered in the current capability manifest.  A
missing (or not dispatchable) declared stage kernel therefore produces a typed
``UNAVAILABLE`` result.  The controller never substitutes host arithmetic, host
token manipulation, or an unregistered fallback.
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

SEQUENCE_CONTROLLER_SCHEMA = "nanrouter.sequence-controller.v1"
SEQUENCE_ROUTE_SCHEMA = "nanrouter.sequence-route.v1"

SEQUENCE_ROUTE = "SEQUENCE"

SEQUENCE_STAGES = (
    "embedding_gather",
    "position_add",
    "slice_window",
    "mask_apply",
    "ngram_build",
    "head_concat",
)

# The head-concat stage is optional: it is only planned for multi-head
# sequence compositions.  All other stages are mandatory.
SEQUENCE_BASE_STAGES = (
    "embedding_gather",
    "position_add",
    "slice_window",
    "mask_apply",
    "ngram_build",
)

SEQUENCE_OPTIONAL_STAGES = ("head_concat",)

SEQUENCE_MASK_POLICIES = ("none", "causal", "padding", "causal_padding")
DEFAULT_MASK_POLICY = "causal"

DEFAULT_NGRAM_ORDER = 2
SEQUENCE_MAX_NGRAM_ORDER = 64
SEQUENCE_MAX_WINDOW = 1048576

# Declared stage kernels.  Every entry is currently an explicit capability gap:
# the real manifest registers none of these sequence kernels.  A missing
# declared family kernel makes the route typed UNAVAILABLE.
DEFAULT_STAGE_KERNELS = {
    "embedding_gather": "mth.sequence.embedding.gather.f32",
    "position_add": "mth.sequence.position.add.f32",
    "slice_window": "mth.sequence.slice.window.f32",
    "mask_apply": "mth.sequence.mask.apply.f32",
    "ngram_build": "mth.sequence.ngram.build.u32",
    "head_concat": "mth.sequence.head.concat.f32",
}

STAGE_KERNEL_FAMILIES = {
    "embedding_gather": (DEFAULT_STAGE_KERNELS["embedding_gather"],),
    "position_add": (DEFAULT_STAGE_KERNELS["position_add"],),
    "slice_window": (DEFAULT_STAGE_KERNELS["slice_window"],),
    "mask_apply": (DEFAULT_STAGE_KERNELS["mask_apply"],),
    "ngram_build": (DEFAULT_STAGE_KERNELS["ngram_build"],),
    "head_concat": (DEFAULT_STAGE_KERNELS["head_concat"],),
}

SEQUENCE_STATUS_PLANNED = "PLANNED"
SEQUENCE_STATUS_UNAVAILABLE = "UNAVAILABLE"

SEQUENCE_REASON_INVALID_CONFIG = "invalid_config"
SEQUENCE_REASON_INVALID_REQUEST = "invalid_request"
SEQUENCE_REASON_INVALID_MASK_POLICY = "invalid_mask_policy"
SEQUENCE_REASON_UNKNOWN_KERNEL = "unknown_kernel"
SEQUENCE_REASON_KERNEL_NOT_NATIVE_VERIFIED = "kernel_not_native_verified"
SEQUENCE_REASON_KERNEL_NOT_CI_VERIFIED = "kernel_not_ci_verified"
SEQUENCE_REASON_EMBEDDING_GATHER_UNAVAILABLE = (
    "embedding_gather_kernel_unavailable"
)
SEQUENCE_REASON_POSITION_ADD_UNAVAILABLE = "position_add_kernel_unavailable"
SEQUENCE_REASON_SLICE_WINDOW_UNAVAILABLE = "slice_window_kernel_unavailable"
SEQUENCE_REASON_MASK_APPLY_UNAVAILABLE = "mask_apply_kernel_unavailable"
SEQUENCE_REASON_NGRAM_BUILD_UNAVAILABLE = "ngram_build_kernel_unavailable"
SEQUENCE_REASON_HEAD_CONCAT_UNAVAILABLE = "head_concat_kernel_unavailable"
SEQUENCE_REASON_STEP_LIMIT = "step_limit_exceeded"
SEQUENCE_REASON_WORKSPACE = "unsupported_workspace"
SEQUENCE_REASON_PLAN_REJECTED = "plan_rejected"
SEQUENCE_REASON_ROUTE_UNAVAILABLE = "route_unavailable"

_STAGE_UNAVAILABLE_REASONS = {
    "embedding_gather": SEQUENCE_REASON_EMBEDDING_GATHER_UNAVAILABLE,
    "position_add": SEQUENCE_REASON_POSITION_ADD_UNAVAILABLE,
    "slice_window": SEQUENCE_REASON_SLICE_WINDOW_UNAVAILABLE,
    "mask_apply": SEQUENCE_REASON_MASK_APPLY_UNAVAILABLE,
    "ngram_build": SEQUENCE_REASON_NGRAM_BUILD_UNAVAILABLE,
    "head_concat": SEQUENCE_REASON_HEAD_CONCAT_UNAVAILABLE,
}

_STAGE_SPEC_FIELDS = frozenset({
    "kernel_id", "name", "inputs", "outputs", "depends_on",
})

_STAGE_STEP_NAMES = {
    "embedding_gather": "sequence.embedding-gather",
    "position_add": "sequence.position-add",
    "slice_window": "sequence.slice-window",
    "mask_apply": "sequence.mask-apply",
    "ngram_build": "sequence.ngram-build",
    "head_concat": "sequence.head-concat",
}

_UNSET = object()


class SequenceControllerError(ValueError):
    """Base class for sequence controller configuration/routing failures."""

    reason = "sequence_controller_error"

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason or type(self).reason


class SequenceConfigError(SequenceControllerError):
    """The controller was configured with an invalid stage or bound."""

    reason = SEQUENCE_REASON_INVALID_CONFIG


class SequenceRequestError(SequenceControllerError):
    """A route request is malformed or rejected by the plan contract."""

    reason = SEQUENCE_REASON_INVALID_REQUEST


class SequenceMaskError(SequenceControllerError):
    """The requested sequence mask policy is not declared."""

    reason = SEQUENCE_REASON_INVALID_MASK_POLICY


class SequenceKernelError(SequenceControllerError):
    """A route names an unknown or non-dispatchable override kernel."""

    reason = SEQUENCE_REASON_UNKNOWN_KERNEL


class SequenceStepLimitError(SequenceControllerError):
    """A route exceeds the controller's bounded step count."""

    reason = SEQUENCE_REASON_STEP_LIMIT


class SequenceWorkspaceError(SequenceControllerError):
    """A route exceeds its workspace budget or requests too little space."""

    reason = SEQUENCE_REASON_WORKSPACE


class SequenceUnavailableError(SequenceControllerError):
    """A caller required a plan from a typed UNAVAILABLE route."""

    reason = SEQUENCE_REASON_ROUTE_UNAVAILABLE


@dataclass(frozen=True)
class SequenceStageSpec:
    """One sequence stage override; empty fields are filled deterministically.

    ``kernel_id`` is mandatory.  When ``name`` is omitted the controller uses
    the declared stage name.  When ``inputs``/``outputs`` are omitted the
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
        raise SequenceRequestError("plan must be an MthPlan")
    document = plan.to_dict()
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def _require_bound(
    value: Any,
    name: str,
    *,
    minimum: int,
    maximum: int | None = None,
    error_cls: type[SequenceControllerError] = SequenceConfigError,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise error_cls(f"{name} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise error_cls(f"{name} must be an integer <= {maximum}")
    return value


def _normalise_mask_policy(value: Any) -> str:
    if not isinstance(value, str):
        raise SequenceMaskError("mask_policy must be a string")
    policy = value.lower()
    if policy not in SEQUENCE_MASK_POLICIES:
        raise SequenceMaskError(
            f"unknown sequence mask policy: {value!r}; expected one of "
            f"{', '.join(SEQUENCE_MASK_POLICIES)}"
        )
    return policy


def _normalise_window(value: Any, *, request: bool) -> int | None:
    if value is None:
        return None
    error_cls = SequenceRequestError if request else SequenceConfigError
    return _require_bound(
        value,
        "window",
        minimum=1,
        maximum=SEQUENCE_MAX_WINDOW,
        error_cls=error_cls,
    )


def _normalise_ngram_order(value: Any, *, request: bool) -> int:
    error_cls = SequenceRequestError if request else SequenceConfigError
    return _require_bound(
        value,
        "ngram_order",
        minimum=1,
        maximum=SEQUENCE_MAX_NGRAM_ORDER,
        error_cls=error_cls,
    )


def _normalise_head_concat(value: Any, *, request: bool) -> bool:
    if not isinstance(value, bool):
        error_cls = SequenceRequestError if request else SequenceConfigError
        raise error_cls("include_head_concat must be a boolean")
    return value


def _text_tuple(value: Any, name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raise SequenceConfigError(f"{name} must be a sequence of typed names")
    if not isinstance(value, (tuple, list)):
        raise SequenceConfigError(f"{name} must be a sequence of typed names")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise SequenceConfigError(
                f"{name} entry {index} must be a non-empty string"
            )
        result.append(item)
    return tuple(result)


def _normalise_stage(stage: str, value: Any) -> SequenceStageSpec:
    if isinstance(value, SequenceStageSpec):
        if not isinstance(value.kernel_id, str) or not value.kernel_id:
            raise SequenceConfigError(f"stage {stage!r} has no kernel_id")
        return value
    if isinstance(value, str):
        if not value:
            raise SequenceConfigError(f"stage {stage!r} has no kernel_id")
        return SequenceStageSpec(kernel_id=value)
    if isinstance(value, Mapping):
        unknown = sorted(key for key in value if key not in _STAGE_SPEC_FIELDS)
        if unknown:
            raise SequenceConfigError(
                f"stage {stage!r} has unknown fields: {', '.join(unknown)}"
            )
        kernel_id = value.get("kernel_id", "")
        if not isinstance(kernel_id, str) or not kernel_id:
            raise SequenceConfigError(f"stage {stage!r} has no kernel_id")
        name = value.get("name")
        if name is not None and (not isinstance(name, str) or not name):
            raise SequenceConfigError(
                f"stage {stage!r} name must be a non-empty string or None"
            )
        return SequenceStageSpec(
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
    raise SequenceConfigError(
        f"stage {stage!r} must be a kernel id, mapping, or SequenceStageSpec"
    )


def _active_stages(include_head_concat: bool) -> tuple[str, ...]:
    if include_head_concat:
        return SEQUENCE_STAGES
    return SEQUENCE_BASE_STAGES


def _window_token(window: int | None) -> str:
    if window is None:
        return "unbounded"
    return str(window)


def _default_stage_step(
    stage: str,
    kernel_id: str,
    mask_policy: str,
    window: int | None,
    ngram_order: int,
    previous_name: str | None,
    previous_output: str | None,
) -> SequenceStageSpec:
    step_name = _STAGE_STEP_NAMES[stage]

    if stage == "embedding_gather":
        inputs = (
            "u32[256].sequence.tokens",
            "f32[256].sequence.embedding.table",
        )
        outputs = ("f32[256].sequence.embedded",)
    elif stage == "position_add":
        inputs = (
            previous_output,
            "u32[256].sequence.positions",
        )
        outputs = ("f32[256].sequence.positioned",)
    elif stage == "slice_window":
        inputs = (previous_output,)
        outputs = (
            f"f32[256].sequence.window.{_window_token(window)}",
        )
    elif stage == "mask_apply":
        policy_token = mask_policy.replace("_", ".")
        inputs = (
            previous_output,
            "u32[256].sequence.mask",
        )
        outputs = (
            f"f32[256].sequence.masked.{policy_token}",
        )
    elif stage == "ngram_build":
        inputs = (previous_output,)
        outputs = (f"u32[256].sequence.ngram.{ngram_order}",)
    else:
        inputs = (
            previous_output,
            "f32[256].sequence.heads.context",
        )
        outputs = ("f32[256].sequence.heads.concat",)

    depends_on: tuple[str, ...] = ()
    if previous_name is not None:
        depends_on = (previous_name,)
    return SequenceStageSpec(
        kernel_id=kernel_id,
        name=step_name,
        inputs=tuple(inputs),
        outputs=outputs,
        depends_on=depends_on,
    )


def _merge_stage(
    override: SequenceStageSpec, default: SequenceStageSpec,
) -> SequenceStageSpec:
    return SequenceStageSpec(
        kernel_id=override.kernel_id,
        name=override.name or default.name,
        inputs=override.inputs or default.inputs,
        outputs=override.outputs or default.outputs,
        depends_on=override.depends_on or default.depends_on,
    )


@dataclass(frozen=True)
class SequenceRouteResult:
    """Typed outcome of composing one token/sequence route.

    A ``PLANNED`` result carries a registry-validated plan and its digest.  An
    ``UNAVAILABLE`` result carries no plan and a stable reason code.  Neither
    form is execution evidence.
    """

    status: str
    mask_policy: str
    include_head_concat: bool
    window: int | None
    ngram_order: int
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
        return self.status == SEQUENCE_STATUS_PLANNED

    def require_plan(self) -> MthPlan:
        """Return the route plan or raise :class:`SequenceUnavailableError`."""
        if self.plan is None:
            raise SequenceUnavailableError(
                f"{SEQUENCE_ROUTE} route is {self.status}: "
                f"{self.detail or self.reason}",
                reason=self.reason or SEQUENCE_REASON_ROUTE_UNAVAILABLE,
            )
        return self.plan

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SEQUENCE_ROUTE_SCHEMA,
            "route": SEQUENCE_ROUTE,
            "status": self.status,
            "mask_policy": self.mask_policy,
            "include_head_concat": self.include_head_concat,
            "window": self.window,
            "ngram_order": self.ngram_order,
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


class SequenceController:
    """Compose a token/sequence route into a validated MTH plan.

    ``stages`` optionally overrides the kernel id, step name, typed inputs,
    outputs, or dependencies of one stage.  Overrides are normalized before
    use; a route with more than ``max_steps`` active stages is rejected at
    request time.

    ``max_workspace_words`` is an optional hard controller budget.  Request
    workspace below the plan's required workspace is always rejected.

    ``mask_policy``, ``window``, ``ngram_order``, and ``include_head_concat``
    are control-plane declarations.  They are encoded into typed plan value
    names for deterministic plans; the controller never applies a mask, slices
    a sequence, computes positions, or builds n-grams.
    """

    def __init__(
        self,
        registry: MthRegistry,
        stages: Mapping[str, Any] | None = None,
        *,
        max_steps: int = 8,
        max_workspace_words: int | None = None,
        mask_policy: str = DEFAULT_MASK_POLICY,
        window: int | None = None,
        ngram_order: int = DEFAULT_NGRAM_ORDER,
        include_head_concat: bool = False,
    ) -> None:
        if not isinstance(registry, MthRegistry):
            raise SequenceConfigError("registry must be an MthRegistry")
        self.registry = registry
        self.max_steps = _require_bound(max_steps, "max_steps", minimum=1)
        if max_workspace_words is None:
            self.max_workspace_words = None
        else:
            self.max_workspace_words = _require_bound(
                max_workspace_words, "max_workspace_words", minimum=0
            )
        self.default_mask_policy = _normalise_mask_policy(mask_policy)
        self.default_window = _normalise_window(window, request=False)
        self.default_ngram_order = _normalise_ngram_order(
            ngram_order, request=False
        )
        self.default_include_head_concat = _normalise_head_concat(
            include_head_concat, request=False
        )

        overrides: dict[str, SequenceStageSpec] = {}
        if stages is not None:
            if not isinstance(stages, Mapping):
                raise SequenceConfigError("stages must be a mapping")
            for raw_stage, raw_value in stages.items():
                if not isinstance(raw_stage, str):
                    raise SequenceConfigError("stage names must be strings")
                stage = raw_stage.lower()
                if stage not in SEQUENCE_STAGES:
                    raise SequenceConfigError(
                        f"unknown sequence stage: {raw_stage!r}"
                    )
                overrides[stage] = _normalise_stage(stage, raw_value)
        self._overrides = {
            stage: overrides[stage]
            for stage in SEQUENCE_STAGES
            if stage in overrides
        }

    @property
    def stages(self) -> tuple[str, ...]:
        return SEQUENCE_STAGES

    @property
    def base_stages(self) -> tuple[str, ...]:
        return SEQUENCE_BASE_STAGES

    @property
    def optional_stages(self) -> tuple[str, ...]:
        return SEQUENCE_OPTIONAL_STAGES

    @property
    def mask_policies(self) -> tuple[str, ...]:
        return SEQUENCE_MASK_POLICIES

    def kernel_ids(
        self, *, include_head_concat: bool | None = None,
    ) -> tuple[str, ...]:
        """Return the configured kernel id per active stage."""
        selected = (
            self.default_include_head_concat
            if include_head_concat is None
            else _normalise_head_concat(include_head_concat, request=True)
        )
        return tuple(
            self._overrides[stage].kernel_id
            if stage in self._overrides
            else DEFAULT_STAGE_KERNELS[stage]
            for stage in _active_stages(selected)
        )

    def _resolve_steps(
        self,
        mask_policy: str,
        window: int | None,
        ngram_order: int,
        include_head_concat: bool,
    ) -> tuple[tuple[str, SequenceStageSpec], ...]:
        resolved: list[tuple[str, SequenceStageSpec]] = []
        previous_name: str | None = None
        previous_output: str | None = None
        for stage in _active_stages(include_head_concat):
            default = _default_stage_step(
                stage,
                DEFAULT_STAGE_KERNELS[stage],
                mask_policy,
                window,
                ngram_order,
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
        resolved: tuple[tuple[str, SequenceStageSpec], ...],
        mask_policy: str,
        include_head_concat: bool,
        window: int | None,
        ngram_order: int,
        reason: str,
        detail: str,
    ) -> SequenceRouteResult:
        return SequenceRouteResult(
            status=SEQUENCE_STATUS_UNAVAILABLE,
            mask_policy=mask_policy,
            include_head_concat=include_head_concat,
            window=window,
            ngram_order=ngram_order,
            stages=tuple(stage for stage, _ in resolved),
            kernel_ids=tuple(step.kernel_id for _, step in resolved),
            reason=reason,
            detail=detail,
            step_count=len(resolved),
        )

    def _check_dispatchable(
        self,
        resolved: tuple[tuple[str, SequenceStageSpec], ...],
        mask_policy: str,
        include_head_concat: bool,
        window: int | None,
        ngram_order: int,
    ) -> SequenceRouteResult | None:
        for stage, step in resolved:
            descriptor = self.registry.lookup(step.kernel_id)
            declared = step.kernel_id in STAGE_KERNEL_FAMILIES[stage]
            if descriptor is None:
                if declared:
                    return self._unavailable(
                        resolved,
                        mask_policy,
                        include_head_concat,
                        window,
                        ngram_order,
                        _STAGE_UNAVAILABLE_REASONS[stage],
                        f"{stage} kernel {step.kernel_id!r} is not registered",
                    )
                raise SequenceKernelError(
                    f"{stage} stage names unknown kernel {step.kernel_id!r}",
                    reason=SEQUENCE_REASON_UNKNOWN_KERNEL,
                )
            if descriptor.status != "native_verified":
                if declared:
                    return self._unavailable(
                        resolved,
                        mask_policy,
                        include_head_concat,
                        window,
                        ngram_order,
                        _STAGE_UNAVAILABLE_REASONS[stage],
                        f"{stage} kernel {step.kernel_id!r} has status "
                        f"{descriptor.status!r}, not 'native_verified'",
                    )
                raise SequenceKernelError(
                    f"{stage} stage kernel {step.kernel_id!r} has status "
                    f"{descriptor.status!r}, not 'native_verified'",
                    reason=SEQUENCE_REASON_KERNEL_NOT_NATIVE_VERIFIED,
                )
            if not descriptor.ci_verified:
                if declared:
                    return self._unavailable(
                        resolved,
                        mask_policy,
                        include_head_concat,
                        window,
                        ngram_order,
                        _STAGE_UNAVAILABLE_REASONS[stage],
                        f"{stage} kernel {step.kernel_id!r} is not CI-verified",
                    )
                raise SequenceKernelError(
                    f"{stage} stage kernel {step.kernel_id!r} is not CI-verified",
                    reason=SEQUENCE_REASON_KERNEL_NOT_CI_VERIFIED,
                )
        return None

    def _step_document(self, step: SequenceStageSpec) -> dict[str, Any]:
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
        mask_policy: Any = _UNSET,
        window: Any = _UNSET,
        ngram_order: Any = _UNSET,
        include_head_concat: Any = _UNSET,
        workspace_words: int | None = None,
        fuel: int | None = None,
        cancel_after: int | None = None,
    ) -> SequenceRouteResult:
        """Compose one token/sequence plan or return typed UNAVAILABLE."""
        policy = (
            self.default_mask_policy
            if mask_policy is _UNSET
            else _normalise_mask_policy(mask_policy)
        )
        selected_window = (
            self.default_window
            if window is _UNSET
            else _normalise_window(window, request=True)
        )
        selected_ngram_order = (
            self.default_ngram_order
            if ngram_order is _UNSET
            else _normalise_ngram_order(ngram_order, request=True)
        )
        selected_head_concat = (
            self.default_include_head_concat
            if include_head_concat is _UNSET
            else _normalise_head_concat(include_head_concat, request=True)
        )

        active = _active_stages(selected_head_concat)
        if len(active) > self.max_steps:
            raise SequenceStepLimitError(
                f"{SEQUENCE_ROUTE} route has {len(active)} active steps, "
                f"above the bounded maximum of {self.max_steps}",
                reason=SEQUENCE_REASON_STEP_LIMIT,
            )

        resolved = self._resolve_steps(
            policy,
            selected_window,
            selected_ngram_order,
            selected_head_concat,
        )
        unavailable = self._check_dispatchable(
            resolved,
            policy,
            selected_head_concat,
            selected_window,
            selected_ngram_order,
        )
        if unavailable is not None:
            return unavailable

        if plan_id is None:
            plan_id = "sequence.compose"
        if workspace_words is not None:
            workspace_words = _require_bound(
                workspace_words,
                "workspace_words",
                minimum=0,
                error_cls=SequenceRequestError,
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
            raise SequenceRequestError(
                f"{SEQUENCE_ROUTE} route plan was rejected: {exc}",
                reason=SEQUENCE_REASON_PLAN_REJECTED,
            ) from exc

        required_workspace = plan.workspace_words
        if (
            self.max_workspace_words is not None
            and required_workspace > self.max_workspace_words
        ):
            raise SequenceWorkspaceError(
                f"{SEQUENCE_ROUTE} route needs {required_workspace} workspace "
                f"words, above the controller budget of "
                f"{self.max_workspace_words}",
                reason=SEQUENCE_REASON_WORKSPACE,
            )
        if workspace_words is not None:
            if workspace_words < required_workspace:
                raise SequenceWorkspaceError(
                    f"{SEQUENCE_ROUTE} route needs at least "
                    f"{required_workspace} workspace words, got "
                    f"{workspace_words}",
                    reason=SEQUENCE_REASON_WORKSPACE,
                )
            if workspace_words != required_workspace:
                spec["workspace_words"] = workspace_words
                try:
                    plan = self.registry.compose(spec)
                except MthPlanError as exc:
                    raise SequenceRequestError(
                        f"{SEQUENCE_ROUTE} route plan was rejected: {exc}",
                        reason=SEQUENCE_REASON_PLAN_REJECTED,
                    ) from exc

        digest = plan_digest(plan)
        return SequenceRouteResult(
            status=SEQUENCE_STATUS_PLANNED,
            mask_policy=policy,
            include_head_concat=selected_head_concat,
            window=selected_window,
            ngram_order=selected_ngram_order,
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
        mask_policy: Any = _UNSET,
        window: Any = _UNSET,
        ngram_order: Any = _UNSET,
        include_head_concat: Any = _UNSET,
        workspace_words: int | None = None,
        fuel: int | None = None,
        cancel_after: int | None = None,
    ) -> SequenceRouteResult:
        """Alias of :meth:`route`; composition never executes the plan."""
        return self.route(
            plan_id=plan_id,
            mask_policy=mask_policy,
            window=window,
            ngram_order=ngram_order,
            include_head_concat=include_head_concat,
            workspace_words=workspace_words,
            fuel=fuel,
            cancel_after=cancel_after,
        )

    def availability(
        self,
        *,
        mask_policy: Any = _UNSET,
        window: Any = _UNSET,
        ngram_order: Any = _UNSET,
        include_head_concat: Any = _UNSET,
    ) -> dict[str, Any]:
        """Return the typed route status without executing anything."""
        try:
            result = self.route(
                mask_policy=mask_policy,
                window=window,
                ngram_order=ngram_order,
                include_head_concat=include_head_concat,
            )
        except SequenceControllerError as exc:
            try:
                kernels = list(
                    self.kernel_ids(
                        include_head_concat=(
                            None
                            if include_head_concat is _UNSET
                            else include_head_concat
                        )
                    )
                )
            except SequenceControllerError:
                kernels = list(self.kernel_ids())
            return {
                "route": SEQUENCE_ROUTE,
                "status": "REJECTED",
                "reason": exc.reason,
                "detail": str(exc),
                "kernel_ids": kernels,
            }
        return {
            "route": SEQUENCE_ROUTE,
            "status": result.status,
            "reason": result.reason,
            "detail": result.detail,
            "mask_policy": result.mask_policy,
            "include_head_concat": result.include_head_concat,
            "window": result.window,
            "ngram_order": result.ngram_order,
            "kernel_ids": list(result.kernel_ids),
            "plan_digest": result.plan_digest,
        }

    def to_dict(self) -> dict[str, Any]:
        stage_kernels = {
            stage: (
                self._overrides[stage].kernel_id
                if stage in self._overrides
                else DEFAULT_STAGE_KERNELS[stage]
            )
            for stage in SEQUENCE_STAGES
        }
        return {
            "schema": SEQUENCE_CONTROLLER_SCHEMA,
            "route": SEQUENCE_ROUTE,
            "stages": list(SEQUENCE_STAGES),
            "base_stages": list(SEQUENCE_BASE_STAGES),
            "optional_stages": list(SEQUENCE_OPTIONAL_STAGES),
            "mask_policies": list(SEQUENCE_MASK_POLICIES),
            "default_mask_policy": self.default_mask_policy,
            "default_window": self.default_window,
            "default_ngram_order": self.default_ngram_order,
            "default_include_head_concat": self.default_include_head_concat,
            "max_steps": self.max_steps,
            "max_workspace_words": self.max_workspace_words,
            "max_ngram_order": SEQUENCE_MAX_NGRAM_ORDER,
            "max_window": SEQUENCE_MAX_WINDOW,
            "stage_kernels": stage_kernels,
            "stage_kernel_families": {
                stage: list(STAGE_KERNEL_FAMILIES[stage])
                for stage in SEQUENCE_STAGES
            },
        }


__all__ = [
    "DEFAULT_MASK_POLICY",
    "DEFAULT_NGRAM_ORDER",
    "DEFAULT_STAGE_KERNELS",
    "SEQUENCE_BASE_STAGES",
    "SEQUENCE_CONTROLLER_SCHEMA",
    "SEQUENCE_MAX_NGRAM_ORDER",
    "SEQUENCE_MAX_WINDOW",
    "SEQUENCE_MASK_POLICIES",
    "SEQUENCE_OPTIONAL_STAGES",
    "SEQUENCE_REASON_EMBEDDING_GATHER_UNAVAILABLE",
    "SEQUENCE_REASON_HEAD_CONCAT_UNAVAILABLE",
    "SEQUENCE_REASON_INVALID_CONFIG",
    "SEQUENCE_REASON_INVALID_MASK_POLICY",
    "SEQUENCE_REASON_INVALID_REQUEST",
    "SEQUENCE_REASON_KERNEL_NOT_CI_VERIFIED",
    "SEQUENCE_REASON_KERNEL_NOT_NATIVE_VERIFIED",
    "SEQUENCE_REASON_MASK_APPLY_UNAVAILABLE",
    "SEQUENCE_REASON_NGRAM_BUILD_UNAVAILABLE",
    "SEQUENCE_REASON_PLAN_REJECTED",
    "SEQUENCE_REASON_POSITION_ADD_UNAVAILABLE",
    "SEQUENCE_REASON_ROUTE_UNAVAILABLE",
    "SEQUENCE_REASON_SLICE_WINDOW_UNAVAILABLE",
    "SEQUENCE_REASON_STEP_LIMIT",
    "SEQUENCE_REASON_UNKNOWN_KERNEL",
    "SEQUENCE_REASON_WORKSPACE",
    "SEQUENCE_ROUTE",
    "SEQUENCE_ROUTE_SCHEMA",
    "SEQUENCE_STAGES",
    "SEQUENCE_STATUS_PLANNED",
    "SEQUENCE_STATUS_UNAVAILABLE",
    "STAGE_KERNEL_FAMILIES",
    "SequenceConfigError",
    "SequenceController",
    "SequenceControllerError",
    "SequenceKernelError",
    "SequenceMaskError",
    "SequenceRequestError",
    "SequenceRouteResult",
    "SequenceStageSpec",
    "SequenceStepLimitError",
    "SequenceUnavailableError",
    "SequenceWorkspaceError",
    "plan_digest",
]
