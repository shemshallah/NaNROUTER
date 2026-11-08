"""Host-only output/sampling plan controller over the MTH registry.

The controller maps the output and sampling operations required by
``docs/GAME_PLAN_MTH.md`` §4 onto explicit registered NaN16 kernels and
composes a validated :class:`~runner_riddle.mth_registry.MthPlan`:

sampling mode:
``logit_scale -> temperature -> [penalty] -> top_k -> top_p -> normalize ->
sample``

greedy mode:
``logit_scale -> temperature -> [penalty] -> greedy_tiebreak``

It is a control-plane selector, not a math implementation: it performs no
numerical operation, executes no kernel, generates no random value, and
offers no alternate execution path.  A route result is either ``PLANNED``
with a validated plan and deterministic plan digest, or ``UNAVAILABLE`` with
a stable reason code.

The sampling kernels are not registered in the current capability manifest.
The registered top-k and argmax kernels are used when they satisfy the
declared native/CI contract; a missing or non-dispatchable stage kernel
always produces a typed ``UNAVAILABLE`` result.  The controller never
substitutes host arithmetic, a Python PRNG, or an unregistered fallback.
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

SAMPLING_CONTROLLER_SCHEMA = "nanrouter.sampling-controller.v1"
SAMPLING_ROUTE_SCHEMA = "nanrouter.sampling-route.v1"

SAMPLING_ROUTE = "GENERATE"

SAMPLING_STAGES = (
    "logit_scale",
    "temperature",
    "penalty",
    "top_k",
    "top_p",
    "normalize",
    "sample",
    "greedy_tiebreak",
)

SAMPLING_MODES = ("sample", "greedy")
DEFAULT_SAMPLING_MODE = "sample"

SAMPLING_PENALTY_POLICIES = ("none", "repetition", "frequency")
DEFAULT_PENALTY_POLICY = "none"

# Declared penalty kernels.  A penalty stage is only planned when the caller
# explicitly selects a non-``none`` policy, as required by the game plan.
PENALTY_KERNELS = {
    "repetition": "mth.sampling.penalty.repetition.f32",
    "frequency": "mth.sampling.penalty.frequency.f32",
}

# Declared stage kernels.  The top-k and greedy tie-break entries name real
# manifest kernels; the remaining entries are explicit capability gaps that
# make the route UNAVAILABLE until a dispatchable native kernel exists.
DEFAULT_STAGE_KERNELS = {
    "logit_scale": "mth.sampling.logit.scale.f32",
    "temperature": "mth.sampling.temperature.f32",
    "penalty": PENALTY_KERNELS["repetition"],
    "top_k": "mth.topk.256.f32",
    "top_p": "mth.sampling.top.p.f32",
    "normalize": "mth.sampling.softmax.stable.f32",
    "sample": "mth.sampling.categorical.seeded.f32",
    "greedy_tiebreak": "mth.vector.argmax256.f32",
}

STAGE_KERNEL_FAMILIES = {
    "logit_scale": (DEFAULT_STAGE_KERNELS["logit_scale"],),
    "temperature": (DEFAULT_STAGE_KERNELS["temperature"],),
    "penalty": tuple(PENALTY_KERNELS.values()),
    "top_k": (DEFAULT_STAGE_KERNELS["top_k"],),
    "top_p": (DEFAULT_STAGE_KERNELS["top_p"],),
    "normalize": (DEFAULT_STAGE_KERNELS["normalize"],),
    "sample": (DEFAULT_STAGE_KERNELS["sample"],),
    "greedy_tiebreak": (DEFAULT_STAGE_KERNELS["greedy_tiebreak"],),
}

SAMPLING_STATUS_PLANNED = "PLANNED"
SAMPLING_STATUS_UNAVAILABLE = "UNAVAILABLE"

SAMPLING_REASON_INVALID_CONFIG = "invalid_config"
SAMPLING_REASON_INVALID_REQUEST = "invalid_request"
SAMPLING_REASON_INVALID_MODE = "invalid_mode"
SAMPLING_REASON_INVALID_PENALTY_POLICY = "invalid_penalty_policy"
SAMPLING_REASON_UNKNOWN_KERNEL = "unknown_kernel"
SAMPLING_REASON_KERNEL_NOT_NATIVE_VERIFIED = "kernel_not_native_verified"
SAMPLING_REASON_KERNEL_NOT_CI_VERIFIED = "kernel_not_ci_verified"
SAMPLING_REASON_LOGIT_SCALE_UNAVAILABLE = "logit_scale_kernel_unavailable"
SAMPLING_REASON_TEMPERATURE_UNAVAILABLE = "temperature_kernel_unavailable"
SAMPLING_REASON_PENALTY_UNAVAILABLE = "penalty_kernel_unavailable"
SAMPLING_REASON_TOP_K_UNAVAILABLE = "top_k_kernel_unavailable"
SAMPLING_REASON_TOP_P_UNAVAILABLE = "top_p_kernel_unavailable"
SAMPLING_REASON_NORMALIZE_UNAVAILABLE = "normalize_kernel_unavailable"
SAMPLING_REASON_SAMPLE_UNAVAILABLE = "sample_kernel_unavailable"
SAMPLING_REASON_GREEDY_TIEBREAK_UNAVAILABLE = (
    "greedy_tiebreak_kernel_unavailable"
)
SAMPLING_REASON_STEP_LIMIT = "step_limit_exceeded"
SAMPLING_REASON_WORKSPACE = "unsupported_workspace"
SAMPLING_REASON_PLAN_REJECTED = "plan_rejected"
SAMPLING_REASON_ROUTE_UNAVAILABLE = "route_unavailable"

SAMPLING_MAX_SEED = 18446744073709551615

_STAGE_UNAVAILABLE_REASONS = {
    "logit_scale": SAMPLING_REASON_LOGIT_SCALE_UNAVAILABLE,
    "temperature": SAMPLING_REASON_TEMPERATURE_UNAVAILABLE,
    "penalty": SAMPLING_REASON_PENALTY_UNAVAILABLE,
    "top_k": SAMPLING_REASON_TOP_K_UNAVAILABLE,
    "top_p": SAMPLING_REASON_TOP_P_UNAVAILABLE,
    "normalize": SAMPLING_REASON_NORMALIZE_UNAVAILABLE,
    "sample": SAMPLING_REASON_SAMPLE_UNAVAILABLE,
    "greedy_tiebreak": SAMPLING_REASON_GREEDY_TIEBREAK_UNAVAILABLE,
}

_STAGE_SPEC_FIELDS = frozenset({
    "kernel_id", "name", "inputs", "outputs", "depends_on",
})

_STAGE_STEP_NAMES = {
    "logit_scale": "sampling.logit-scale",
    "temperature": "sampling.temperature",
    "penalty": "sampling.penalty",
    "top_k": "sampling.top-k",
    "top_p": "sampling.top-p",
    "normalize": "sampling.normalize",
    "sample": "sampling.sample",
    "greedy_tiebreak": "sampling.greedy-tiebreak",
}


class SamplingControllerError(ValueError):
    """Base class for sampling controller configuration and routing failures."""

    reason = "sampling_controller_error"

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason or type(self).reason


class SamplingConfigError(SamplingControllerError):
    """The controller was configured with an invalid stage or bound."""

    reason = SAMPLING_REASON_INVALID_CONFIG


class SamplingRequestError(SamplingControllerError):
    """A route request is malformed or rejected by the plan contract."""

    reason = SAMPLING_REASON_INVALID_REQUEST


class SamplingModeError(SamplingRequestError):
    """The requested sampling mode is not declared."""

    reason = SAMPLING_REASON_INVALID_MODE


class SamplingPenaltyError(SamplingRequestError):
    """The requested penalty policy is not declared."""

    reason = SAMPLING_REASON_INVALID_PENALTY_POLICY


class SamplingKernelError(SamplingControllerError):
    """A route names an unknown or non-dispatchable override kernel."""

    reason = SAMPLING_REASON_UNKNOWN_KERNEL


class SamplingStepLimitError(SamplingControllerError):
    """A route exceeds the controller's bounded step count."""

    reason = SAMPLING_REASON_STEP_LIMIT


class SamplingWorkspaceError(SamplingControllerError):
    """A route exceeds its workspace budget or requests too little space."""

    reason = SAMPLING_REASON_WORKSPACE


class SamplingUnavailableError(SamplingControllerError):
    """A caller required a plan from a typed UNAVAILABLE route."""

    reason = SAMPLING_REASON_ROUTE_UNAVAILABLE


@dataclass(frozen=True)
class SamplingStageSpec:
    """One sampling stage override; empty fields are filled deterministically.

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
        raise SamplingRequestError("plan must be an MthPlan")
    document = plan.to_dict()
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def _require_bound(value: Any, name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SamplingConfigError(f"{name} must be an integer >= {minimum}")
    return value


def _require_request_bound(value: Any, name: str, *,
                           minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SamplingRequestError(f"{name} must be an integer >= {minimum}")
    return value


def _normalise_mode(value: Any) -> str:
    if not isinstance(value, str):
        raise SamplingModeError("sampling mode must be a string")
    mode = value.lower()
    if mode not in SAMPLING_MODES:
        raise SamplingModeError(
            f"unknown sampling mode: {value!r}; expected one of "
            f"{', '.join(SAMPLING_MODES)}"
        )
    return mode


def _normalise_penalty_policy(value: Any) -> str:
    if not isinstance(value, str):
        raise SamplingPenaltyError("penalty policy must be a string")
    policy = value.lower()
    if policy not in SAMPLING_PENALTY_POLICIES:
        raise SamplingPenaltyError(
            f"unknown penalty policy: {value!r}; expected one of "
            f"{', '.join(SAMPLING_PENALTY_POLICIES)}"
        )
    return policy


def _normalise_seed(value: Any) -> int:
    seed = _require_request_bound(value, "seed", minimum=0)
    if seed > SAMPLING_MAX_SEED:
        raise SamplingRequestError(
            f"seed must fit an unsigned 64-bit word (<= {SAMPLING_MAX_SEED})"
        )
    return seed


def _text_tuple(value: Any, name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raise SamplingConfigError(f"{name} must be a sequence of typed names")
    if not isinstance(value, (tuple, list)):
        raise SamplingConfigError(f"{name} must be a sequence of typed names")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise SamplingConfigError(
                f"{name} entry {index} must be a non-empty string"
            )
        result.append(item)
    return tuple(result)


def _normalise_stage(stage: str, value: Any) -> SamplingStageSpec:
    if isinstance(value, SamplingStageSpec):
        if not isinstance(value.kernel_id, str) or not value.kernel_id:
            raise SamplingConfigError(f"stage {stage!r} has no kernel_id")
        return value
    if isinstance(value, str):
        if not value:
            raise SamplingConfigError(f"stage {stage!r} has no kernel_id")
        return SamplingStageSpec(kernel_id=value)
    if isinstance(value, Mapping):
        unknown = sorted(key for key in value if key not in _STAGE_SPEC_FIELDS)
        if unknown:
            raise SamplingConfigError(
                f"stage {stage!r} has unknown fields: {', '.join(unknown)}"
            )
        kernel_id = value.get("kernel_id", "")
        if not isinstance(kernel_id, str) or not kernel_id:
            raise SamplingConfigError(f"stage {stage!r} has no kernel_id")
        name = value.get("name")
        if name is not None and (not isinstance(name, str) or not name):
            raise SamplingConfigError(
                f"stage {stage!r} name must be a non-empty string or None"
            )
        return SamplingStageSpec(
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
    raise SamplingConfigError(
        f"stage {stage!r} must be a kernel id, mapping, or SamplingStageSpec"
    )


def _stage_kernels(penalty_policy: str) -> dict[str, str]:
    """Return the declared default kernel id per stage for one policy."""
    kernels = dict(DEFAULT_STAGE_KERNELS)
    if penalty_policy != "none":
        kernels["penalty"] = PENALTY_KERNELS[penalty_policy]
    return kernels


def _active_stages(mode: str, penalty_policy: str) -> tuple[str, ...]:
    stages = ["logit_scale", "temperature"]
    if penalty_policy != "none":
        stages.append("penalty")
    if mode == "greedy":
        stages.append("greedy_tiebreak")
    else:
        stages.extend(("top_k", "top_p", "normalize", "sample"))
    return tuple(stages)


def _seed_input(seed: int | None) -> str:
    if seed is None:
        return "u64.sampling.seed"
    return f"u64.sampling.seed.{seed}"


def _default_stage_step(
    stage: str,
    kernel_id: str,
    penalty_policy: str,
    previous_name: str | None,
    previous_output: str | None,
    seed: int | None,
) -> SamplingStageSpec:
    step_name = _STAGE_STEP_NAMES[stage]

    if stage == "logit_scale":
        inputs = ("f32[256].sampling.logits",)
        outputs = ("f32[256].sampling.logits.scaled",)
    elif stage == "temperature":
        inputs = (previous_output,)
        outputs = ("f32[256].sampling.logits.tempered",)
    elif stage == "penalty":
        policy_token = penalty_policy.replace("_", ".")
        inputs = (
            previous_output,
            "u32[256].sampling.context.tokens",
        )
        outputs = (
            f"f32[256].sampling.logits.penalized.{policy_token}",
        )
    elif stage == "top_k":
        inputs = (previous_output,)
        outputs = ("f32[256].sampling.logits.top-k",)
    elif stage == "top_p":
        inputs = (previous_output,)
        outputs = ("f32[256].sampling.logits.top-p",)
    elif stage == "normalize":
        inputs = (previous_output,)
        outputs = ("f32[256].sampling.probabilities",)
    elif stage == "sample":
        inputs = (previous_output, _seed_input(seed))
        outputs = ("u32.sampling.token",)
    else:
        inputs = (previous_output,)
        outputs = ("u32.sampling.token.greedy",)

    depends_on: tuple[str, ...] = ()
    if previous_name is not None:
        depends_on = (previous_name,)
    return SamplingStageSpec(
        kernel_id=kernel_id,
        name=step_name,
        inputs=tuple(inputs),
        outputs=tuple(outputs),
        depends_on=depends_on,
    )


def _merge_stage(
    override: SamplingStageSpec, default: SamplingStageSpec,
) -> SamplingStageSpec:
    return SamplingStageSpec(
        kernel_id=override.kernel_id,
        name=override.name or default.name,
        inputs=override.inputs or default.inputs,
        outputs=override.outputs or default.outputs,
        depends_on=override.depends_on or default.depends_on,
    )


@dataclass(frozen=True)
class SamplingRouteResult:
    """Typed outcome of composing one output/sampling route.

    A ``PLANNED`` result carries a registry-validated plan and its digest.  An
    ``UNAVAILABLE`` result carries no plan and a stable reason code.  Neither
    form is execution evidence.
    """

    status: str
    mode: str
    penalty_policy: str
    stages: tuple[str, ...]
    kernel_ids: tuple[str, ...]
    plan: MthPlan | None = None
    plan_digest: str | None = None
    reason: str | None = None
    detail: str | None = None
    workspace_words: int | None = None
    step_count: int = 0
    deterministic: bool = True
    seed: int | None = None

    @property
    def available(self) -> bool:
        return self.status == SAMPLING_STATUS_PLANNED

    def require_plan(self) -> MthPlan:
        """Return the route plan or raise :class:`SamplingUnavailableError`."""
        if self.plan is None:
            raise SamplingUnavailableError(
                f"{SAMPLING_ROUTE} route is {self.status}: "
                f"{self.detail or self.reason}",
                reason=self.reason or SAMPLING_REASON_ROUTE_UNAVAILABLE,
            )
        return self.plan

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SAMPLING_ROUTE_SCHEMA,
            "route": SAMPLING_ROUTE,
            "status": self.status,
            "mode": self.mode,
            "penalty_policy": self.penalty_policy,
            "seed": self.seed,
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


class SamplingController:
    """Compose an output/sampling route into a validated MTH plan.

    ``stages`` optionally overrides the kernel id, step name, typed inputs,
    outputs, or dependencies of one stage.  Overrides are normalized before
    use; a route with more than ``max_steps`` active stages is rejected at
    request time.

    ``max_workspace_words`` is an optional hard controller budget.  Request
    workspace below the plan's required workspace is always rejected.

    ``sampling_mode`` selects ``sample`` or ``greedy``.  ``penalty_policy``
    defaults to ``none``; repetition or frequency penalties are only planned
    when explicitly requested.  ``seed`` is control-plane metadata for the
    seeded categorical sampling stage; it is never used to generate values.
    """

    def __init__(
        self,
        registry: MthRegistry,
        stages: Mapping[str, Any] | None = None,
        *,
        max_steps: int = 8,
        max_workspace_words: int | None = None,
        sampling_mode: str = DEFAULT_SAMPLING_MODE,
        penalty_policy: str = DEFAULT_PENALTY_POLICY,
    ) -> None:
        if not isinstance(registry, MthRegistry):
            raise SamplingConfigError("registry must be an MthRegistry")
        self.registry = registry
        self.max_steps = _require_bound(max_steps, "max_steps", minimum=1)
        if max_workspace_words is None:
            self.max_workspace_words = None
        else:
            self.max_workspace_words = _require_bound(
                max_workspace_words, "max_workspace_words", minimum=0
            )
        self.default_mode = _normalise_mode(sampling_mode)
        self.default_penalty_policy = _normalise_penalty_policy(
            penalty_policy
        )

        overrides: dict[str, SamplingStageSpec] = {}
        if stages is not None:
            if not isinstance(stages, Mapping):
                raise SamplingConfigError("stages must be a mapping")
            for raw_stage, raw_value in stages.items():
                if not isinstance(raw_stage, str):
                    raise SamplingConfigError("stage names must be strings")
                stage = raw_stage.lower()
                if stage not in SAMPLING_STAGES:
                    raise SamplingConfigError(
                        f"unknown sampling stage: {raw_stage!r}"
                    )
                overrides[stage] = _normalise_stage(stage, raw_value)
        self._overrides = {
            stage: overrides[stage]
            for stage in SAMPLING_STAGES
            if stage in overrides
        }

    @property
    def stages(self) -> tuple[str, ...]:
        return SAMPLING_STAGES

    @property
    def modes(self) -> tuple[str, ...]:
        return SAMPLING_MODES

    @property
    def penalty_policies(self) -> tuple[str, ...]:
        return SAMPLING_PENALTY_POLICIES

    def kernel_ids(
        self, *, mode: str | None = None,
        penalty_policy: str | None = None,
    ) -> tuple[str, ...]:
        """Return the configured kernel id per active stage."""
        selected_mode = (
            self.default_mode if mode is None else _normalise_mode(mode)
        )
        selected_policy = (
            self.default_penalty_policy
            if penalty_policy is None
            else _normalise_penalty_policy(penalty_policy)
        )
        defaults = _stage_kernels(selected_policy)
        return tuple(
            self._overrides[stage].kernel_id
            if stage in self._overrides
            else defaults[stage]
            for stage in _active_stages(selected_mode, selected_policy)
        )

    def _resolve_steps(
        self,
        mode: str,
        penalty_policy: str,
        seed: int | None,
    ) -> tuple[tuple[str, SamplingStageSpec], ...]:
        defaults = _stage_kernels(penalty_policy)
        resolved: list[tuple[str, SamplingStageSpec]] = []
        previous_name: str | None = None
        previous_output: str | None = None
        for stage in _active_stages(mode, penalty_policy):
            default = _default_stage_step(
                stage,
                defaults[stage],
                penalty_policy,
                previous_name,
                previous_output,
                seed,
            )
            override = self._overrides.get(stage)
            step = default if override is None else _merge_stage(override, default)
            resolved.append((stage, step))
            previous_name = step.name
            previous_output = step.outputs[0]
        return tuple(resolved)

    def _unavailable(
        self,
        resolved: tuple[tuple[str, SamplingStageSpec], ...],
        mode: str,
        penalty_policy: str,
        seed: int | None,
        reason: str,
        detail: str,
    ) -> SamplingRouteResult:
        return SamplingRouteResult(
            status=SAMPLING_STATUS_UNAVAILABLE,
            mode=mode,
            penalty_policy=penalty_policy,
            seed=seed,
            stages=tuple(stage for stage, _ in resolved),
            kernel_ids=tuple(step.kernel_id for _, step in resolved),
            reason=reason,
            detail=detail,
            step_count=len(resolved),
        )

    def _check_dispatchable(
        self,
        resolved: tuple[tuple[str, SamplingStageSpec], ...],
        mode: str,
        penalty_policy: str,
        seed: int | None,
    ) -> SamplingRouteResult | None:
        for stage, step in resolved:
            descriptor = self.registry.lookup(step.kernel_id)
            declared = step.kernel_id in STAGE_KERNEL_FAMILIES[stage]
            if descriptor is None:
                if declared:
                    return self._unavailable(
                        resolved,
                        mode,
                        penalty_policy,
                        seed,
                        _STAGE_UNAVAILABLE_REASONS[stage],
                        f"{stage} kernel {step.kernel_id!r} is not registered",
                    )
                raise SamplingKernelError(
                    f"{stage} stage names unknown kernel {step.kernel_id!r}",
                    reason=SAMPLING_REASON_UNKNOWN_KERNEL,
                )
            if descriptor.status != "native_verified":
                if declared:
                    return self._unavailable(
                        resolved,
                        mode,
                        penalty_policy,
                        seed,
                        _STAGE_UNAVAILABLE_REASONS[stage],
                        f"{stage} kernel {step.kernel_id!r} has status "
                        f"{descriptor.status!r}, not 'native_verified'",
                    )
                raise SamplingKernelError(
                    f"{stage} stage kernel {step.kernel_id!r} has status "
                    f"{descriptor.status!r}, not 'native_verified'",
                    reason=SAMPLING_REASON_KERNEL_NOT_NATIVE_VERIFIED,
                )
            if not descriptor.ci_verified:
                if declared:
                    return self._unavailable(
                        resolved,
                        mode,
                        penalty_policy,
                        seed,
                        _STAGE_UNAVAILABLE_REASONS[stage],
                        f"{stage} kernel {step.kernel_id!r} is not CI-verified",
                    )
                raise SamplingKernelError(
                    f"{stage} stage kernel {step.kernel_id!r} is not CI-verified",
                    reason=SAMPLING_REASON_KERNEL_NOT_CI_VERIFIED,
                )
        return None

    def _step_document(self, step: SamplingStageSpec) -> dict[str, Any]:
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
        mode: str | None = None,
        penalty_policy: str | None = None,
        seed: int | None = None,
        workspace_words: int | None = None,
        fuel: int | None = None,
        cancel_after: int | None = None,
    ) -> SamplingRouteResult:
        """Compose one sampling plan or return a typed UNAVAILABLE result."""
        selected_mode = (
            self.default_mode if mode is None else _normalise_mode(mode)
        )
        selected_policy = (
            self.default_penalty_policy
            if penalty_policy is None
            else _normalise_penalty_policy(penalty_policy)
        )
        if seed is None:
            normalised_seed: int | None = None
        else:
            normalised_seed = _normalise_seed(seed)
            if selected_mode == "greedy":
                raise SamplingRequestError(
                    "seed is only applicable to sampling mode, not greedy mode"
                )

        active = _active_stages(selected_mode, selected_policy)
        if len(active) > self.max_steps:
            raise SamplingStepLimitError(
                f"{SAMPLING_ROUTE} route has {len(active)} active steps, "
                f"above the bounded maximum of {self.max_steps}",
                reason=SAMPLING_REASON_STEP_LIMIT,
            )

        resolved = self._resolve_steps(
            selected_mode, selected_policy, normalised_seed
        )
        unavailable = self._check_dispatchable(
            resolved, selected_mode, selected_policy, normalised_seed
        )
        if unavailable is not None:
            return unavailable

        if plan_id is None:
            plan_id = "sampling.generate"
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
            raise SamplingRequestError(
                f"{SAMPLING_ROUTE} route plan was rejected: {exc}",
                reason=SAMPLING_REASON_PLAN_REJECTED,
            ) from exc

        required_workspace = plan.workspace_words
        if (
            self.max_workspace_words is not None
            and required_workspace > self.max_workspace_words
        ):
            raise SamplingWorkspaceError(
                f"{SAMPLING_ROUTE} route needs {required_workspace} workspace "
                f"words, above the controller budget of "
                f"{self.max_workspace_words}",
                reason=SAMPLING_REASON_WORKSPACE,
            )
        if workspace_words is not None:
            if workspace_words < required_workspace:
                raise SamplingWorkspaceError(
                    f"{SAMPLING_ROUTE} route needs at least "
                    f"{required_workspace} workspace words, got "
                    f"{workspace_words}",
                    reason=SAMPLING_REASON_WORKSPACE,
                )
            if workspace_words != required_workspace:
                spec["workspace_words"] = workspace_words
                try:
                    plan = self.registry.compose(spec)
                except MthPlanError as exc:
                    raise SamplingRequestError(
                        f"{SAMPLING_ROUTE} route plan was rejected: {exc}",
                        reason=SAMPLING_REASON_PLAN_REJECTED,
                    ) from exc

        digest = plan_digest(plan)
        return SamplingRouteResult(
            status=SAMPLING_STATUS_PLANNED,
            mode=selected_mode,
            penalty_policy=selected_policy,
            seed=normalised_seed,
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
        mode: str | None = None,
        penalty_policy: str | None = None,
        seed: int | None = None,
        workspace_words: int | None = None,
        fuel: int | None = None,
        cancel_after: int | None = None,
    ) -> SamplingRouteResult:
        """Alias of :meth:`route`; composition never executes the plan."""
        return self.route(
            plan_id=plan_id,
            mode=mode,
            penalty_policy=penalty_policy,
            seed=seed,
            workspace_words=workspace_words,
            fuel=fuel,
            cancel_after=cancel_after,
        )

    def availability(
        self,
        *,
        mode: str | None = None,
        penalty_policy: str | None = None,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Return the typed route status without executing anything."""
        try:
            result = self.route(
                mode=mode, penalty_policy=penalty_policy, seed=seed
            )
        except SamplingControllerError as exc:
            selected_mode = (
                self.default_mode if mode is None else str(mode)
            )
            selected_policy = (
                self.default_penalty_policy
                if penalty_policy is None
                else str(penalty_policy)
            )
            try:
                kernel_ids = list(
                    self.kernel_ids(
                        mode=mode,
                        penalty_policy=penalty_policy,
                    )
                )
            except SamplingControllerError:
                kernel_ids = list(self.kernel_ids())
            return {
                "route": SAMPLING_ROUTE,
                "status": "REJECTED",
                "reason": exc.reason,
                "detail": str(exc),
                "mode": selected_mode,
                "penalty_policy": selected_policy,
                "seed": seed,
                "kernel_ids": kernel_ids,
            }
        return {
            "route": SAMPLING_ROUTE,
            "status": result.status,
            "reason": result.reason,
            "detail": result.detail,
            "mode": result.mode,
            "penalty_policy": result.penalty_policy,
            "seed": result.seed,
            "kernel_ids": list(result.kernel_ids),
            "plan_digest": result.plan_digest,
        }

    def to_dict(self) -> dict[str, Any]:
        defaults = _stage_kernels(self.default_penalty_policy)
        stage_kernels = {
            stage: (
                self._overrides[stage].kernel_id
                if stage in self._overrides
                else defaults[stage]
            )
            for stage in SAMPLING_STAGES
        }
        return {
            "schema": SAMPLING_CONTROLLER_SCHEMA,
            "route": SAMPLING_ROUTE,
            "stages": list(SAMPLING_STAGES),
            "modes": list(SAMPLING_MODES),
            "penalty_policies": list(SAMPLING_PENALTY_POLICIES),
            "default_mode": self.default_mode,
            "default_penalty_policy": self.default_penalty_policy,
            "max_steps": self.max_steps,
            "max_workspace_words": self.max_workspace_words,
            "max_seed": SAMPLING_MAX_SEED,
            "stage_kernels": stage_kernels,
            "stage_kernel_families": {
                stage: list(STAGE_KERNEL_FAMILIES[stage])
                for stage in SAMPLING_STAGES
            },
            "penalty_kernels": dict(PENALTY_KERNELS),
        }


__all__ = [
    "DEFAULT_PENALTY_POLICY",
    "DEFAULT_SAMPLING_MODE",
    "DEFAULT_STAGE_KERNELS",
    "PENALTY_KERNELS",
    "SAMPLING_CONTROLLER_SCHEMA",
    "SAMPLING_MAX_SEED",
    "SAMPLING_MODES",
    "SAMPLING_PENALTY_POLICIES",
    "SAMPLING_REASON_GREEDY_TIEBREAK_UNAVAILABLE",
    "SAMPLING_REASON_INVALID_CONFIG",
    "SAMPLING_REASON_INVALID_MODE",
    "SAMPLING_REASON_INVALID_PENALTY_POLICY",
    "SAMPLING_REASON_INVALID_REQUEST",
    "SAMPLING_REASON_KERNEL_NOT_CI_VERIFIED",
    "SAMPLING_REASON_KERNEL_NOT_NATIVE_VERIFIED",
    "SAMPLING_REASON_LOGIT_SCALE_UNAVAILABLE",
    "SAMPLING_REASON_NORMALIZE_UNAVAILABLE",
    "SAMPLING_REASON_PENALTY_UNAVAILABLE",
    "SAMPLING_REASON_PLAN_REJECTED",
    "SAMPLING_REASON_ROUTE_UNAVAILABLE",
    "SAMPLING_REASON_SAMPLE_UNAVAILABLE",
    "SAMPLING_REASON_STEP_LIMIT",
    "SAMPLING_REASON_TEMPERATURE_UNAVAILABLE",
    "SAMPLING_REASON_TOP_K_UNAVAILABLE",
    "SAMPLING_REASON_TOP_P_UNAVAILABLE",
    "SAMPLING_REASON_UNKNOWN_KERNEL",
    "SAMPLING_REASON_WORKSPACE",
    "SAMPLING_ROUTE",
    "SAMPLING_ROUTE_SCHEMA",
    "SAMPLING_STAGES",
    "SAMPLING_STATUS_PLANNED",
    "SAMPLING_STATUS_UNAVAILABLE",
    "STAGE_KERNEL_FAMILIES",
    "SamplingConfigError",
    "SamplingController",
    "SamplingControllerError",
    "SamplingKernelError",
    "SamplingModeError",
    "SamplingPenaltyError",
    "SamplingRequestError",
    "SamplingRouteResult",
    "SamplingStageSpec",
    "SamplingStepLimitError",
    "SamplingUnavailableError",
    "SamplingWorkspaceError",
    "plan_digest",
]
