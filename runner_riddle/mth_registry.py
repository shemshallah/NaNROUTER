"""Read-only MTH system registry and deterministic plan composer.

The registry is the control-plane view of the native MTH capability manifest
(``spec/wave-capabilities.json``).  It hashes source and fixture bytes,
validates the declared kernel contract, and exposes stable lookup/resolve
queries.  :meth:`MthRegistry.compose` turns a small JSON/dict specification
into an ordered, typed :class:`MthPlan`.

This module performs no kernel execution, host mathematics, database access,
or manifest mutation.  It is a system contract, not a second math owner.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "nanrouter.wave-capabilities.v1"
REGISTRY_SCHEMA = "nanrouter.mth-registry.v1"
PLAN_SCHEMA = "nanrouter.mth-plan.v1"
PLAN_SPEC_SCHEMA = "nanrouter.mth-plan-spec.v1"
REGISTRY_VERSION = 1

# Stable reason codes carried by MthPlanError.  They let callers distinguish a
# typed handoff failure from generic structural plan errors without parsing
# prose.  Existing raise sites keep the default ``invalid_plan`` reason.
PLAN_REASON_INVALID = "invalid_plan"
PLAN_REASON_VALUE_DESCRIPTOR = "invalid_value_descriptor"
PLAN_REASON_DESCRIPTOR_COUNT = "value_descriptor_count_mismatch"
PLAN_REASON_HANDOFF_SHAPE = "handoff_shape_mismatch"
PLAN_REASON_HANDOFF_PRECISION = "handoff_precision_mismatch"
PLAN_REASON_HANDOFF_LAYOUT = "handoff_layout_mismatch"
PLAN_REASON_HANDOFF_DOMAIN = "handoff_domain_mismatch"
PLAN_REASON_ALIAS_UNKNOWN = "alias_unknown"
PLAN_REASON_ALIAS_MISMATCH = "alias_mismatch"
PLAN_REASON_FUEL = "fuel_out_of_bounds"
PLAN_REASON_CANCEL = "cancel_out_of_bounds"

KERNEL_STATUSES = (
    "declared",
    "source_written",
    "native_verified",
    "degraded",
    "revoked",
)
PRECISIONS = (
    "float32", "u16->i32", "u32", "q16.16", "q32.32",
    "bool", "i32", "u32->u64",
)

_KERNEL_ID_RE = re.compile(r"^mth\.[a-z0-9][a-z0-9_.-]{0,120}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_.:>-]{0,63}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_TYPE_RE = re.compile(r"^[A-Za-z].{0,127}$")

_PLAN_SPEC_KEYS = frozenset({
    "schema", "version", "plan_id", "steps", "workspace_words",
    "fuel", "cancel_after",
})
_PLAN_STEP_KEYS = frozenset({
    "kernel_id", "name", "inputs", "outputs", "depends_on",
    "input_specs", "output_specs",
})
_VALUE_DESCRIPTOR_KEYS = frozenset({
    "precision", "shape", "layout", "domain", "alias_of",
})
_HANDOFF_FIELDS = ("precision", "shape", "layout", "domain")
_HANDOFF_REASONS = {
    "precision": PLAN_REASON_HANDOFF_PRECISION,
    "shape": PLAN_REASON_HANDOFF_SHAPE,
    "layout": PLAN_REASON_HANDOFF_LAYOUT,
    "domain": PLAN_REASON_HANDOFF_DOMAIN,
}


class MthRegistryError(ValueError):
    """Base class for MTH registry, manifest, and plan contract failures."""


class MthManifestError(MthRegistryError):
    """Raised when a capability manifest or one of its files is invalid."""


class MthPlanError(MthRegistryError):
    """Raised when a plan specification or plan document is invalid.

    ``reason`` is a stable code from ``PLAN_REASON_*``.  It defaults to
    ``invalid_plan`` so existing raise sites and callers stay compatible.
    """

    def __init__(self, message: str, *, reason: str = PLAN_REASON_INVALID) -> None:
        super().__init__(message)
        self.reason = reason


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_text(value: Any, name: str, *, maximum: int = 256,
                  error_cls: type[MthRegistryError] = MthRegistryError) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise error_cls(f"{name} must be a non-empty string of at most {maximum} characters")
    return value


def _require_int(value: Any, name: str, *, minimum: int = 0,
                 error_cls: type[MthRegistryError] = MthRegistryError) -> int:
    if not _is_int(value) or value < minimum:
        raise error_cls(f"{name} must be an integer >= {minimum}")
    return value


def _require_bool(value: Any, name: str, *,
                  error_cls: type[MthRegistryError] = MthRegistryError) -> bool:
    if not isinstance(value, bool):
        raise error_cls(f"{name} must be a boolean")
    return value


def _require_name(value: Any, name: str,
                  error_cls: type[MthRegistryError] = MthRegistryError) -> str:
    _require_text(value, name, maximum=128, error_cls=error_cls)
    if not _NAME_RE.fullmatch(value):
        raise error_cls(f"{name} is not a valid plan identifier: {value!r}")
    return value


def _require_kernel_id(value: Any, name: str = "kernel_id",
                       error_cls: type[MthRegistryError] = MthRegistryError) -> str:
    _require_text(value, name, maximum=128, error_cls=error_cls)
    if not _KERNEL_ID_RE.fullmatch(value):
        raise error_cls(f"{name} is not a valid MTH kernel identifier: {value!r}")
    return value


def _require_type_list(value: Any, name: str,
                       error_cls: type[MthRegistryError] = MthRegistryError) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise error_cls(f"{name} must be a list of typed strings")
    result: list[str] = []
    for item in value:
        _require_text(item, f"{name} entry", maximum=128, error_cls=error_cls)
        if not _TYPE_RE.fullmatch(item):
            raise error_cls(f"{name} entry is not a typed string: {item!r}")
        if item in result:
            raise error_cls(f"{name} contains a duplicate entry: {item!r}")
        result.append(item)
    return tuple(result)


def _require_name_list(value: Any, name: str,
                       error_cls: type[MthRegistryError] = MthRegistryError) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise error_cls(f"{name} must be a list of step names")
    result: list[str] = []
    for item in value:
        _require_name(item, f"{name} entry", error_cls=error_cls)
        if item in result:
            raise error_cls(f"{name} contains a duplicate entry: {item!r}")
        result.append(item)
    return tuple(result)


def sha256_file(path: str | Path) -> str:
    """Return the lowercase SHA-256 hex digest of a file's bytes."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_root(manifest_path: Path, root: str | Path | None) -> Path:
    if root is not None:
        root_path = Path(root).resolve()
    elif manifest_path.parent.name == "spec":
        root_path = manifest_path.parent.parent
    else:
        root_path = manifest_path.parent
    if not root_path.is_dir():
        raise MthManifestError(f"manifest root is not a directory: {root_path}")
    return root_path


def _resolve_member(root: Path, value: Any, kernel_id: str, field: str) -> tuple[str, Path]:
    _require_text(value, f"{kernel_id}: {field}", maximum=512,
                  error_cls=MthManifestError)
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise MthManifestError(
            f"{kernel_id}: {field} must be a relative path inside the manifest root"
        )
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise MthManifestError(
            f"{kernel_id}: {field} escapes the manifest root"
        ) from exc
    if not candidate.is_file():
        raise MthManifestError(f"{kernel_id}: missing {field} file: {value}")
    return relative.as_posix(), candidate


def _derived_tags(kernel_id: str, precision: str, workspace_words: int,
                  shape: tuple[int, ...], status: str, ci_verified: bool,
                  explicit: Iterable[str]) -> tuple[str, ...]:
    family = kernel_id.split(".", 2)[1]
    tags = set(explicit)
    tags.add(f"family:{family}")
    tags.add(f"precision:{precision.replace('->', '-to-')}")
    tags.add(f"shape:{'x'.join(str(dimension) for dimension in shape)}")
    tags.add(f"status:{status}")
    tags.add("ci:verified" if ci_verified else "ci:unverified")
    tags.add("workspace:zero" if workspace_words == 0 else "workspace:bounded")
    return tuple(sorted(tags))


def _plan_dataflow(steps: tuple["MthPlanStep", ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return external plan inputs and unique produced outputs.

    Typed values are opaque names.  Reusing an output name across steps is
    allowed so a plan can express an in-place state update; the aggregate
    output list contains each name once in first-definition order.
    """
    outputs: list[str] = []
    produced: set[str] = set()
    for step in steps:
        for output in step.outputs:
            if output not in produced:
                produced.add(output)
                outputs.append(output)

    external: list[str] = []
    seen: set[str] = set()
    for step in steps:
        for input_name in step.inputs:
            if input_name not in produced and input_name not in seen:
                seen.add(input_name)
                external.append(input_name)
    return tuple(external), tuple(outputs)


def _handoff_mismatch(left: "MthValueDescriptor",
                      right: "MthValueDescriptor") -> tuple[str, Any, Any] | None:
    """Return the first declared field that conflicts between two descriptors.

    Only fields declared on both sides participate.  Missing metadata is not
    treated as a match; it means the plan did not declare enough information
    for that check, which keeps old untyped plans valid.
    """
    for field in _HANDOFF_FIELDS:
        left_value = getattr(left, field)
        right_value = getattr(right, field)
        if field == "shape":
            if left_value is not None:
                left_value = tuple(left_value)
            if right_value is not None:
                right_value = tuple(right_value)
        if left_value is None or right_value is None:
            continue
        if left_value != right_value:
            return field, left_value, right_value
    return None


def _validate_plan_handoff(steps: tuple["MthPlanStep", ...]) -> None:
    """Validate declared value handoffs and aliases across ordered steps."""
    declared_values = {
        value
        for step in steps
        for value in (*step.inputs, *step.outputs)
    }
    produced: dict[str, MthValueDescriptor | None] = {}
    producer_steps: dict[str, str] = {}
    value_specs: dict[str, list[MthValueDescriptor]] = {}

    for step in steps:
        input_specs = tuple(step.input_specs)
        output_specs = tuple(step.output_specs)
        for index, value in enumerate(step.inputs):
            spec = input_specs[index] if input_specs else None
            if spec is None:
                continue
            value_specs.setdefault(value, []).append(spec)
            if value not in produced:
                continue
            producer = produced[value]
            if producer is None:
                continue
            mismatch = _handoff_mismatch(producer, spec)
            if mismatch is not None:
                field, producer_value, consumer_value = mismatch
                raise MthPlanError(
                    f"handoff for {value!r}: {field} mismatch from step "
                    f"{producer_steps[value]!r} to step {step.name!r}: "
                    f"{producer_value!r} != {consumer_value!r}",
                    reason=_HANDOFF_REASONS[field],
                )
        for index, value in enumerate(step.outputs):
            spec = output_specs[index] if output_specs else None
            if spec is not None:
                value_specs.setdefault(value, []).append(spec)
            if value in produced:
                previous = produced[value]
                if spec is not None and previous is not None:
                    mismatch = _handoff_mismatch(previous, spec)
                    if mismatch is not None:
                        field, previous_value, next_value = mismatch
                        raise MthPlanError(
                            f"redefined output {value!r}: {field} mismatch from "
                            f"step {producer_steps[value]!r} to step "
                            f"{step.name!r}: {previous_value!r} != {next_value!r}",
                            reason=_HANDOFF_REASONS[field],
                        )
                if spec is not None:
                    produced[value] = spec
                    producer_steps[value] = step.name
            else:
                produced[value] = spec
                producer_steps[value] = step.name

    for value in sorted(value_specs):
        for spec in value_specs[value]:
            alias = spec.alias_of
            if alias is None:
                continue
            if alias not in declared_values:
                raise MthPlanError(
                    f"alias for {value!r} names unknown plan value {alias!r}",
                    reason=PLAN_REASON_ALIAS_UNKNOWN,
                )
            for target in value_specs.get(alias, ()):
                mismatch = _handoff_mismatch(target, spec)
                if mismatch is not None:
                    field, target_value, alias_value = mismatch
                    raise MthPlanError(
                        f"alias {value!r} -> {alias!r}: {field} mismatch: "
                        f"{target_value!r} != {alias_value!r}",
                        reason=PLAN_REASON_ALIAS_MISMATCH,
                    )


@dataclass(frozen=True)
class MthValueDescriptor:
    """Optional declarative metadata for one plan input or output value.

    The descriptor carries no numeric payload.  It only names precision,
    shape, layout, and domain, plus an optional alias to another plan value.
    Every field is optional so plans that do not opt in keep the v1 contract.
    """

    precision: str | None = None
    shape: tuple[int, ...] | None = None
    layout: str | None = None
    domain: str | None = None
    alias_of: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.shape, list):
            object.__setattr__(self, "shape", tuple(self.shape))

    def validate(self) -> None:
        if self.precision is not None:
            if not isinstance(self.precision, str) or self.precision not in PRECISIONS:
                raise MthPlanError(
                    f"unsupported value precision: {self.precision!r}",
                    reason=PLAN_REASON_VALUE_DESCRIPTOR,
                )
        if self.shape is not None:
            if not isinstance(self.shape, (tuple, list)):
                raise MthPlanError(
                    "value shape must be a list of positive dimensions",
                    reason=PLAN_REASON_VALUE_DESCRIPTOR,
                )
            for dimension in self.shape:
                if not _is_int(dimension) or dimension < 1:
                    raise MthPlanError(
                        "value shape dimensions must be positive integers",
                        reason=PLAN_REASON_VALUE_DESCRIPTOR,
                    )
        for field in ("layout", "domain"):
            value = getattr(self, field)
            if value is None:
                continue
            if not isinstance(value, str) or not _TAG_RE.fullmatch(value):
                raise MthPlanError(
                    f"value {field} must be a lowercase token: {value!r}",
                    reason=PLAN_REASON_VALUE_DESCRIPTOR,
                )
        if self.alias_of is not None:
            if (
                not isinstance(self.alias_of, str)
                or not self.alias_of
                or len(self.alias_of) > 128
                or not _TYPE_RE.fullmatch(self.alias_of)
            ):
                raise MthPlanError(
                    f"value alias_of is not a typed plan value: {self.alias_of!r}",
                    reason=PLAN_REASON_VALUE_DESCRIPTOR,
                )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        document: dict[str, Any] = {}
        if self.precision is not None:
            document["precision"] = self.precision
        if self.shape is not None:
            document["shape"] = list(self.shape)
        if self.layout is not None:
            document["layout"] = self.layout
        if self.domain is not None:
            document["domain"] = self.domain
        if self.alias_of is not None:
            document["alias_of"] = self.alias_of
        return document


def _require_value_descriptor_list(
    value: Any, name: str, *, expected: int,
) -> tuple[MthValueDescriptor, ...]:
    if not isinstance(value, (tuple, list)):
        raise MthPlanError(
            f"{name} must be a list of value descriptors",
            reason=PLAN_REASON_VALUE_DESCRIPTOR,
        )
    descriptors: list[MthValueDescriptor] = []
    for index, item in enumerate(value):
        if not isinstance(item, MthValueDescriptor):
            raise MthPlanError(
                f"{name} entry {index} must be an MthValueDescriptor",
                reason=PLAN_REASON_VALUE_DESCRIPTOR,
            )
        item.validate()
        descriptors.append(item)
    result = tuple(descriptors)
    if result and len(result) != expected:
        raise MthPlanError(
            f"{name} declares {len(result)} descriptors for {expected} values",
            reason=PLAN_REASON_DESCRIPTOR_COUNT,
        )
    return result


def _parse_value_descriptors(
    value: Any, name: str,
) -> tuple[MthValueDescriptor, ...]:
    if value is None:
        return ()
    if not isinstance(value, (tuple, list)):
        raise MthPlanError(
            f"{name} must be a list of value descriptors",
            reason=PLAN_REASON_VALUE_DESCRIPTOR,
        )
    descriptors: list[MthValueDescriptor] = []
    for index, raw in enumerate(value):
        if isinstance(raw, MthValueDescriptor):
            descriptor = raw
        elif isinstance(raw, Mapping):
            unknown = set(raw) - _VALUE_DESCRIPTOR_KEYS
            if unknown:
                raise MthPlanError(
                    f"{name} entry {index} has unknown fields: "
                    f"{', '.join(sorted(unknown))}",
                    reason=PLAN_REASON_VALUE_DESCRIPTOR,
                )
            descriptor = MthValueDescriptor(
                precision=raw.get("precision"),
                shape=raw.get("shape"),
                layout=raw.get("layout"),
                domain=raw.get("domain"),
                alias_of=raw.get("alias_of"),
            )
        else:
            raise MthPlanError(
                f"{name} entry {index} must be a value descriptor object",
                reason=PLAN_REASON_VALUE_DESCRIPTOR,
            )
        descriptor.validate()
        descriptors.append(descriptor)
    return tuple(descriptors)


def _require_plan_bound(value: Any, name: str, reason: str) -> None:
    if value is None:
        return
    if not _is_int(value) or value < 1:
        raise MthPlanError(
            f"{name} must be a positive integer when declared",
            reason=reason,
        )


@dataclass(frozen=True)
class MthKernelDescriptor:
    """Validated description of one native MTH kernel."""

    kernel_id: str
    source: str
    fixture: str
    marker: str
    steps: int
    precision: str
    workspace_words: int
    shape: tuple[int, ...]
    status: str
    ci_verified: bool
    source_digest: str
    fixture_digest: str
    tags: tuple[str, ...] = ()
    version: int = 1

    def validate(self) -> None:
        _require_kernel_id(self.kernel_id)
        _require_int(self.version, "version", minimum=1)
        _require_text(self.source, "source", maximum=512)
        _require_text(self.fixture, "fixture", maximum=512)
        _require_text(self.marker, "marker", maximum=256)
        _require_int(self.steps, "steps", minimum=1)
        if self.precision not in PRECISIONS:
            raise MthRegistryError(f"unsupported precision: {self.precision!r}")
        _require_int(self.workspace_words, "workspace_words", minimum=0)
        if not isinstance(self.shape, (tuple, list)) or not self.shape:
            raise MthRegistryError("shape must be a non-empty list of positive dimensions")
        for dimension in self.shape:
            _require_int(dimension, "shape dimension", minimum=1)
        if self.status not in KERNEL_STATUSES:
            raise MthRegistryError(f"unknown kernel status: {self.status!r}")
        _require_bool(self.ci_verified, "ci_verified")
        for field, digest in (
            ("source_digest", self.source_digest),
            ("fixture_digest", self.fixture_digest),
        ):
            if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
                raise MthRegistryError(
                    f"{field} must be 64 lowercase hexadecimal characters"
                )
        if not isinstance(self.tags, (tuple, list)):
            raise MthRegistryError("tags must be a list of lowercase tag strings")
        seen_tags: set[str] = set()
        for tag in self.tags:
            if not isinstance(tag, str) or not _TAG_RE.fullmatch(tag):
                raise MthRegistryError(f"invalid tag: {tag!r}")
            if tag in seen_tags:
                raise MthRegistryError(f"duplicate tag: {tag!r}")
            seen_tags.add(tag)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "kernel_id": self.kernel_id,
            "version": self.version,
            "source": self.source,
            "fixture": self.fixture,
            "marker": self.marker,
            "steps": self.steps,
            "precision": self.precision,
            "workspace_words": self.workspace_words,
            "shape": list(self.shape),
            "status": self.status,
            "ci_verified": self.ci_verified,
            "source_digest": self.source_digest,
            "fixture_digest": self.fixture_digest,
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class MthPlanStep:
    """One ordered step in an MTH plan; it names inputs and outputs only.

    ``input_specs`` and ``output_specs`` are optional positional metadata for
    the corresponding names.  They are emitted only when declared, so a step
    that does not use them serializes exactly as MTH plan v1 did.
    """

    name: str
    kernel_id: str
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    input_specs: tuple[MthValueDescriptor, ...] = ()
    output_specs: tuple[MthValueDescriptor, ...] = ()

    def validate(self) -> None:
        _require_name(self.name, "step name", error_cls=MthPlanError)
        _require_kernel_id(self.kernel_id, error_cls=MthPlanError)
        _require_type_list(self.inputs, f"{self.name}: inputs", error_cls=MthPlanError)
        _require_type_list(self.outputs, f"{self.name}: outputs", error_cls=MthPlanError)
        _require_name_list(
            self.depends_on, f"{self.name}: depends_on", error_cls=MthPlanError
        )
        _require_value_descriptor_list(
            self.input_specs, f"{self.name}: input_specs",
            expected=len(self.inputs),
        )
        _require_value_descriptor_list(
            self.output_specs, f"{self.name}: output_specs",
            expected=len(self.outputs),
        )
        if self.name in self.depends_on:
            raise MthPlanError(f"step {self.name!r} must not depend on itself")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        document: dict[str, Any] = {
            "name": self.name,
            "kernel_id": self.kernel_id,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "depends_on": list(self.depends_on),
        }
        if self.input_specs:
            document["input_specs"] = [
                descriptor.to_dict() for descriptor in self.input_specs
            ]
        if self.output_specs:
            document["output_specs"] = [
                descriptor.to_dict() for descriptor in self.output_specs
            ]
        return document


@dataclass(frozen=True)
class MthPlan:
    """Deterministic, typed execution plan produced by :meth:`compose`.

    ``fuel`` and ``cancel_after`` are optional positive execution bounds.  They
    are serialized only when declared, preserving the v1 plan document for old
    plans.
    """

    plan_id: str
    steps: tuple[MthPlanStep, ...]
    workspace_words: int = 0
    deterministic: bool = True
    version: int = 1
    fuel: int | None = None
    cancel_after: int | None = None

    @property
    def kernel_ids(self) -> tuple[str, ...]:
        return tuple(step.kernel_id for step in self.steps)

    @property
    def inputs(self) -> tuple[str, ...]:
        return _plan_dataflow(self.steps)[0]

    @property
    def outputs(self) -> tuple[str, ...]:
        return _plan_dataflow(self.steps)[1]

    def to_dict(self) -> dict[str, Any]:
        document = {
            "schema": PLAN_SCHEMA,
            "version": self.version,
            "plan_id": self.plan_id,
            "steps": [step.to_dict() for step in self.steps],
            "kernel_ids": list(self.kernel_ids),
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "workspace_words": self.workspace_words,
            "deterministic": self.deterministic,
        }
        if self.fuel is not None:
            document["fuel"] = self.fuel
        if self.cancel_after is not None:
            document["cancel_after"] = self.cancel_after
        return document


class MthRegistry:
    """Immutable, read-only registry over validated MTH kernel descriptors."""

    def __init__(self, descriptors: Iterable[MthKernelDescriptor], *,
                 manifest_path: str | Path | None = None) -> None:
        ordered = tuple(descriptors)
        if not ordered:
            raise MthManifestError("registry requires at least one kernel")
        by_id: dict[str, MthKernelDescriptor] = {}
        for descriptor in ordered:
            if not isinstance(descriptor, MthKernelDescriptor):
                raise MthManifestError("descriptors must be MthKernelDescriptor instances")
            descriptor.validate()
            if descriptor.kernel_id in by_id:
                raise MthManifestError(f"duplicate kernel_id: {descriptor.kernel_id}")
            by_id[descriptor.kernel_id] = descriptor
        self._descriptors = ordered
        self._by_id = by_id
        self.manifest_path = None if manifest_path is None else Path(manifest_path)

    @classmethod
    def load(cls, path: str | Path, *, root: str | Path | None = None) -> "MthRegistry":
        """Load and validate a wave-capabilities manifest.

        ``root`` defaults to the manifest's parent directory, or to its
        grandparent when the manifest lives in a ``spec`` directory.  Manifest
        source/fixture paths must be relative to that root.
        """
        manifest_path = Path(path)
        if not manifest_path.is_file():
            raise MthManifestError(f"manifest not found: {manifest_path}")
        try:
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MthManifestError(f"cannot read manifest: {manifest_path}") from exc
        if not isinstance(document, Mapping):
            raise MthManifestError("manifest must be a JSON object")
        if document.get("schema") != MANIFEST_SCHEMA:
            raise MthManifestError(
                f"unsupported manifest schema: {document.get('schema')!r}"
            )
        raw_kernels = document.get("kernels")
        if not isinstance(raw_kernels, list) or not raw_kernels:
            raise MthManifestError("manifest has no kernels")

        resolved_root = _manifest_root(manifest_path.resolve(), root)
        descriptors: list[MthKernelDescriptor] = []
        seen_ids: set[str] = set()

        for index, raw in enumerate(raw_kernels):
            if not isinstance(raw, Mapping):
                raise MthManifestError(f"kernel entry {index} must be an object")
            required = (
                "kernel_id", "source", "fixture", "marker", "steps",
                "precision", "workspace_words", "shape", "status",
                "ci_verified",
            )
            missing = [field for field in required if field not in raw]
            if missing:
                raise MthManifestError(
                    f"kernel entry {index} is missing fields: {', '.join(missing)}"
                )

            kernel_id = _require_kernel_id(
                raw["kernel_id"], f"kernel entry {index}: kernel_id",
                error_cls=MthManifestError,
            )
            if kernel_id in seen_ids:
                raise MthManifestError(f"duplicate kernel_id: {kernel_id}")
            seen_ids.add(kernel_id)

            marker = _require_text(
                raw["marker"], f"{kernel_id}: marker", maximum=256,
                error_cls=MthManifestError,
            )
            steps = _require_int(
                raw["steps"], f"{kernel_id}: steps", minimum=1,
                error_cls=MthManifestError,
            )
            precision = _require_text(
                raw["precision"], f"{kernel_id}: precision", maximum=64,
                error_cls=MthManifestError,
            )
            if precision not in PRECISIONS:
                raise MthManifestError(
                    f"{kernel_id}: unsupported precision: {precision!r}"
                )
            workspace_words = _require_int(
                raw["workspace_words"], f"{kernel_id}: workspace_words",
                minimum=0, error_cls=MthManifestError,
            )
            shape = _require_shape(raw["shape"], kernel_id)
            status = _require_text(
                raw["status"], f"{kernel_id}: status", maximum=64,
                error_cls=MthManifestError,
            )
            if status not in KERNEL_STATUSES:
                raise MthManifestError(f"{kernel_id}: unknown status: {status!r}")
            ci_verified = _require_bool(
                raw["ci_verified"], f"{kernel_id}: ci_verified",
                error_cls=MthManifestError,
            )
            version = _require_int(
                raw.get("version", 1), f"{kernel_id}: version", minimum=1,
                error_cls=MthManifestError,
            )

            raw_tags = raw.get("tags", [])
            if not isinstance(raw_tags, (tuple, list)):
                raise MthManifestError(f"{kernel_id}: tags must be a list")
            explicit_tags: list[str] = []
            seen_tags: set[str] = set()
            for tag in raw_tags:
                if not isinstance(tag, str) or not _TAG_RE.fullmatch(tag):
                    raise MthManifestError(f"{kernel_id}: invalid tag: {tag!r}")
                if tag in seen_tags:
                    raise MthManifestError(f"{kernel_id}: duplicate tag: {tag!r}")
                seen_tags.add(tag)
                explicit_tags.append(tag)

            source, source_path = _resolve_member(
                resolved_root, raw["source"], kernel_id, "source"
            )
            fixture, fixture_path = _resolve_member(
                resolved_root, raw["fixture"], kernel_id, "fixture"
            )
            try:
                source_digest = sha256_file(source_path)
                fixture_digest = sha256_file(fixture_path)
            except OSError as exc:
                raise MthManifestError(
                    f"{kernel_id}: cannot hash source or fixture"
                ) from exc

            descriptor = MthKernelDescriptor(
                kernel_id=kernel_id,
                version=version,
                source=source,
                fixture=fixture,
                marker=marker,
                steps=steps,
                precision=precision,
                workspace_words=workspace_words,
                shape=shape,
                status=status,
                ci_verified=ci_verified,
                source_digest=source_digest,
                fixture_digest=fixture_digest,
                tags=_derived_tags(
                    kernel_id, precision, workspace_words, shape, status,
                    ci_verified, explicit_tags,
                ),
            )
            descriptor.validate()
            descriptors.append(descriptor)

        return cls(descriptors, manifest_path=manifest_path)

    def __len__(self) -> int:
        return len(self._descriptors)

    def __iter__(self):
        return iter(self._descriptors)

    def __contains__(self, kernel_id: object) -> bool:
        return isinstance(kernel_id, str) and kernel_id in self._by_id

    def __repr__(self) -> str:
        return f"MthRegistry(kernels={len(self._descriptors)})"

    @property
    def kernels(self) -> tuple[MthKernelDescriptor, ...]:
        return self._descriptors

    def lookup(self, kernel_id: str) -> MthKernelDescriptor | None:
        """Return a descriptor by ID, or ``None`` when it is not registered."""
        _require_text(kernel_id, "kernel_id", maximum=128)
        return self._by_id.get(kernel_id)

    def require(self, kernel_id: str) -> MthKernelDescriptor:
        """Return a descriptor by ID or raise :class:`MthRegistryError`."""
        descriptor = self.lookup(kernel_id)
        if descriptor is None:
            raise MthRegistryError(f"unknown kernel_id: {kernel_id}")
        return descriptor

    def resolve(self, *, tags: str | Iterable[str] | None = None,
                max_workspace: int | None = None,
                require_ci: bool = True) -> tuple[MthKernelDescriptor, ...]:
        """Select descriptors in manifest order.

        ``tags`` is an all-of filter.  ``max_workspace`` bounds
        ``workspace_words`` inclusive.  ``require_ci`` defaults to ``True`` so
        a dispatch candidate must carry the manifest's CI-verified claim.
        """
        if tags is None:
            requested: tuple[str, ...] = ()
        elif isinstance(tags, str):
            requested = (tags,)
        else:
            try:
                requested = tuple(tags)
            except TypeError as exc:
                raise MthRegistryError("tags must be a string or iterable of strings") from exc
        for tag in requested:
            if not isinstance(tag, str) or not _TAG_RE.fullmatch(tag):
                raise MthRegistryError(f"invalid tag filter: {tag!r}")
        if max_workspace is not None:
            _require_int(max_workspace, "max_workspace", minimum=0)
        _require_bool(require_ci, "require_ci")

        wanted = set(requested)
        selected: list[MthKernelDescriptor] = []
        for descriptor in self._descriptors:
            if require_ci and not descriptor.ci_verified:
                continue
            if max_workspace is not None and descriptor.workspace_words > max_workspace:
                continue
            if wanted and not wanted.issubset(descriptor.tags):
                continue
            selected.append(descriptor)
        return tuple(selected)

    def validate_plan(self, plan: MthPlan) -> MthPlan:
        """Validate an ordered plan against this registry and return it."""
        if not isinstance(plan, MthPlan):
            raise MthPlanError("plan must be an MthPlan")
        _require_name(plan.plan_id, "plan_id", error_cls=MthPlanError)
        _require_int(plan.version, "plan version", minimum=1, error_cls=MthPlanError)
        _require_plan_bound(plan.fuel, "fuel", PLAN_REASON_FUEL)
        _require_plan_bound(
            plan.cancel_after, "cancel_after", PLAN_REASON_CANCEL
        )
        if plan.deterministic is not True:
            raise MthPlanError("plan must be deterministic")
        if not isinstance(plan.steps, (tuple, list)) or not plan.steps:
            raise MthPlanError("plan must contain at least one step")

        seen_names: set[str] = set()
        required_workspace = 0
        for step in plan.steps:
            if not isinstance(step, MthPlanStep):
                raise MthPlanError("plan steps must be MthPlanStep instances")
            step.validate()
            if step.name in seen_names:
                raise MthPlanError(f"duplicate plan step name: {step.name!r}")
            for dependency in step.depends_on:
                if dependency not in seen_names:
                    raise MthPlanError(
                        f"step {step.name!r} dependency {dependency!r} "
                        "must be defined earlier"
                    )
            try:
                descriptor = self.require(step.kernel_id)
            except MthRegistryError as exc:
                raise MthPlanError(
                    f"step {step.name!r} names unknown kernel {step.kernel_id!r}"
                ) from exc
            if descriptor.status != "native_verified":
                raise MthPlanError(
                    f"step {step.name!r} kernel {step.kernel_id!r} is not native_verified"
                )
            if not descriptor.ci_verified:
                raise MthPlanError(
                    f"step {step.name!r} kernel {step.kernel_id!r} is not CI-verified"
                )
            required_workspace += descriptor.workspace_words
            seen_names.add(step.name)

        _require_int(
            plan.workspace_words, "workspace_words", minimum=0,
            error_cls=MthPlanError,
        )
        _plan_dataflow(tuple(plan.steps))
        _validate_plan_handoff(tuple(plan.steps))
        # A plan that declares dependencies also declares the liveness
        # boundary of each producer buffer.  Admit it by peak live workspace;
        # a plan with no dependency edges retains the conservative v1 sum.
        if any(step.depends_on for step in plan.steps):
            required_workspace = self.plan_workspace_peak(plan)
        if required_workspace > plan.workspace_words:
            raise MthPlanError(
                f"plan workspace bound {plan.workspace_words} is below the "
                f"required {required_workspace} words"
            )

        return plan

    def plan_workspace_peak(self, plan: MthPlan) -> int:
        """Return peak live workspace for an ordered plan.

        The v1 manifest has no liveness metadata, so this conservative model
        keeps a step's workspace live until its last consumer in the ordered
        plan.  It is an advisory control-plane bound; the declared
        ``plan.workspace_words`` and v1 sum remain backward-compatible.
        """
        if not isinstance(plan, MthPlan):
            raise MthPlanError("plan must be an MthPlan")
        steps = tuple(plan.steps)
        if not steps:
            raise MthPlanError("plan must contain at least one step")
        indices = {step.name: index for index, step in enumerate(steps)}
        workspaces = [self.require(step.kernel_id).workspace_words for step in steps]
        last_consumer = list(range(len(steps)))
        for index, step in enumerate(steps):
            for dependency in step.depends_on:
                dep_index = indices.get(dependency)
                if dep_index is None:
                    raise MthPlanError(
                        f"step {step.name!r} dependency {dependency!r} is not in the plan"
                    )
                last_consumer[dep_index] = max(last_consumer[dep_index], index)
        live: dict[int, int] = {}
        peak = 0
        for index in range(len(steps)):
            live[index] = workspaces[index]
            peak = max(peak, sum(live.values()))
            for dep_index in tuple(live):
                if last_consumer[dep_index] <= index:
                    del live[dep_index]
        return peak

    def compose(self, plan_spec: Mapping[str, Any]) -> MthPlan:
        """Build and validate a deterministic :class:`MthPlan` from a dict spec."""
        if not isinstance(plan_spec, Mapping):
            raise MthPlanError("plan spec must be a mapping")
        unknown = set(plan_spec) - _PLAN_SPEC_KEYS
        if unknown:
            raise MthPlanError(f"unknown plan spec fields: {', '.join(sorted(unknown))}")
        if "schema" in plan_spec and plan_spec["schema"] != PLAN_SPEC_SCHEMA:
            raise MthPlanError(
                f"unsupported plan spec schema: {plan_spec['schema']!r}"
            )
        plan_id = _require_name(
            plan_spec.get("plan_id", "plan"), "plan_id", error_cls=MthPlanError
        )
        version = _require_int(
            plan_spec.get("version", 1), "plan version", minimum=1,
            error_cls=MthPlanError,
        )
        raw_steps = plan_spec.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise MthPlanError("plan spec must contain a non-empty steps list")

        parsed: list[dict[str, Any]] = []
        names: dict[str, int] = {}
        for index, raw_step in enumerate(raw_steps):
            if not isinstance(raw_step, Mapping):
                raise MthPlanError(f"plan step {index} must be an object")
            unknown = set(raw_step) - _PLAN_STEP_KEYS
            if unknown:
                raise MthPlanError(
                    f"plan step {index} has unknown fields: {', '.join(sorted(unknown))}"
                )
            kernel_id = _require_kernel_id(
                raw_step.get("kernel_id"), f"plan step {index}: kernel_id",
                error_cls=MthPlanError,
            )
            try:
                self.require(kernel_id)
            except MthRegistryError as exc:
                raise MthPlanError(
                    f"plan step {index} names unknown kernel {kernel_id!r}"
                ) from exc
            name = _require_name(
                raw_step.get("name"), f"plan step {index}: name",
                error_cls=MthPlanError,
            )
            if name in names:
                raise MthPlanError(f"duplicate plan step name: {name!r}")
            names[name] = index
            parsed.append({
                "name": name,
                "kernel_id": kernel_id,
                "inputs": _require_type_list(
                    raw_step.get("inputs", []), f"plan step {name}: inputs",
                    error_cls=MthPlanError,
                ),
                "outputs": _require_type_list(
                    raw_step.get("outputs", []), f"plan step {name}: outputs",
                    error_cls=MthPlanError,
                ),
                "depends_on": _require_name_list(
                    raw_step.get("depends_on", []), f"plan step {name}: depends_on",
                    error_cls=MthPlanError,
                ),
                "input_specs": _parse_value_descriptors(
                    raw_step.get("input_specs"),
                    f"plan step {name}: input_specs",
                ),
                "output_specs": _parse_value_descriptors(
                    raw_step.get("output_specs"),
                    f"plan step {name}: output_specs",
                ),
            })

        ordered_indices = self._topological_order(parsed, names)
        ordered_steps = tuple(
            MthPlanStep(
                name=parsed[index]["name"],
                kernel_id=parsed[index]["kernel_id"],
                inputs=parsed[index]["inputs"],
                outputs=parsed[index]["outputs"],
                depends_on=parsed[index]["depends_on"],
                input_specs=parsed[index]["input_specs"],
                output_specs=parsed[index]["output_specs"],
            )
            for index in ordered_indices
        )
        required_workspace = sum(
            self.require(step.kernel_id).workspace_words for step in ordered_steps
        )
        declared_bound = plan_spec.get("workspace_words")
        if declared_bound is None:
            workspace_words = required_workspace
        else:
            workspace_words = _require_int(
                declared_bound, "workspace_words", minimum=0,
                error_cls=MthPlanError,
            )
            if workspace_words < required_workspace:
                raise MthPlanError(
                    f"plan workspace bound {workspace_words} is below the "
                    f"required {required_workspace} words"
                )

        plan = MthPlan(
            plan_id=plan_id,
            steps=ordered_steps,
            workspace_words=workspace_words,
            deterministic=True,
            version=version,
            fuel=plan_spec.get("fuel"),
            cancel_after=plan_spec.get("cancel_after"),
        )
        return self.validate_plan(plan)

    @staticmethod
    def _topological_order(parsed: list[dict[str, Any]],
                           names: dict[str, int]) -> list[int]:
        count = len(parsed)
        indegree = [0] * count
        edges: list[list[int]] = [[] for _ in range(count)]
        for index, step in enumerate(parsed):
            for dependency in step["depends_on"]:
                dependency_index = names.get(dependency)
                if dependency_index is None:
                    raise MthPlanError(
                        f"step {step['name']!r} depends on unknown step "
                        f"{dependency!r}"
                    )
                if dependency_index == index:
                    raise MthPlanError(
                        f"step {step['name']!r} must not depend on itself"
                    )
                edges[dependency_index].append(index)
                indegree[index] += 1

        ready = [index for index, degree in enumerate(indegree) if degree == 0]
        heapq.heapify(ready)
        ordered: list[int] = []
        while ready:
            index = heapq.heappop(ready)
            ordered.append(index)
            for dependent in edges[index]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    heapq.heappush(ready, dependent)
        if len(ordered) != count:
            raise MthPlanError("plan dependency graph contains a cycle")
        return ordered

    def health(self) -> dict[str, Any]:
        """Return deterministic counts by status, precision, and CI claim."""
        status_counts = Counter(descriptor.status for descriptor in self._descriptors)
        precision_counts = Counter(
            descriptor.precision for descriptor in self._descriptors
        )
        ci_counts = Counter(descriptor.ci_verified for descriptor in self._descriptors)
        return {
            "schema": "nanrouter.mth-registry-health.v1",
            "kernels": len(self._descriptors),
            "status": dict(sorted(status_counts.items())),
            "precision": dict(sorted(precision_counts.items())),
            "ci": {
                "verified": ci_counts.get(True, 0),
                "unverified": ci_counts.get(False, 0),
            },
            "ci_verified": ci_counts.get(True, 0),
            "ci_unverified": ci_counts.get(False, 0),
            "native_verified_ci": sum(
                1 for descriptor in self._descriptors
                if descriptor.status == "native_verified" and descriptor.ci_verified
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": REGISTRY_SCHEMA,
            "version": REGISTRY_VERSION,
            "manifest": (
                None if self.manifest_path is None
                else str(self.manifest_path)
            ),
            "kernels": [descriptor.to_dict() for descriptor in self._descriptors],
        }


def _require_shape(value: Any, kernel_id: str) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise MthManifestError(
            f"{kernel_id}: shape must be a non-empty list of positive integers"
        )
    shape: list[int] = []
    for dimension in value:
        shape.append(
            _require_int(
                dimension, f"{kernel_id}: shape dimension", minimum=1,
                error_cls=MthManifestError,
            )
        )
    return tuple(shape)


__all__ = [
    "KERNEL_STATUSES",
    "MANIFEST_SCHEMA",
    "MthKernelDescriptor",
    "MthManifestError",
    "MthPlan",
    "MthPlanError",
    "MthPlanStep",
    "MthRegistry",
    "MthRegistryError",
    "MthValueDescriptor",
    "PLAN_REASON_ALIAS_MISMATCH",
    "PLAN_REASON_ALIAS_UNKNOWN",
    "PLAN_REASON_CANCEL",
    "PLAN_REASON_DESCRIPTOR_COUNT",
    "PLAN_REASON_FUEL",
    "PLAN_REASON_HANDOFF_DOMAIN",
    "PLAN_REASON_HANDOFF_LAYOUT",
    "PLAN_REASON_HANDOFF_PRECISION",
    "PLAN_REASON_HANDOFF_SHAPE",
    "PLAN_REASON_INVALID",
    "PLAN_REASON_VALUE_DESCRIPTOR",
    "PLAN_SCHEMA",
    "PLAN_SPEC_SCHEMA",
    "PRECISIONS",
    "REGISTRY_SCHEMA",
    "REGISTRY_VERSION",
    "sha256_file",
]
