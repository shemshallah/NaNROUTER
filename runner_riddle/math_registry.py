"""Semantic mathematical function registry over the native MTH manifest.

``MthRegistry`` is the implementation registry: it validates the frozen
61-kernel ``spec/wave-capabilities.json`` manifest and its source/fixture
digests.  This module adds the layer above it:

    MathFunction  -- semantic contract, one or more native implementations
    MthRegistry   -- validated implementation facts (``kernel_id``, digest,
                     precision, shape, workspace, status, CI evidence)

The registry is read-only and host-control-plane only.  It performs no kernel
execution, no host mathematics, no database access, and no manifest mutation.
Composition is contract satisfaction, not execution: ``g . f`` is accepted
only when the output contract of ``f`` satisfies the input contract of ``g``.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from .math_objects import (
    FUNCTION_SCHEMA,
    PROOF_STATUSES,
    MathFunction,
    MathObjectError,
    MathTypeDescriptor,
    canonical_json,
    digest_object,
    sha256_text,
)
from .mth_registry import (
    MthKernelDescriptor,
    MthRegistry,
    MthRegistryError,
    PRECISIONS,
)

CATALOG_SCHEMA = "nanrouter.math-functions.v1"
CATALOG_VERSION = 1
HEALTH_SCHEMA = "nanrouter.math-functions-health.v1"
COMPATIBILITY_SCHEMA = "nanrouter.math-compatibility-index.v1"

# Separate from ``mth_registry.PRECISIONS`` so future semantic contracts do not
# change the frozen implementation enum.  Nothing here widens the MTH manifest.
MATH_PRECISIONS = tuple(dict.fromkeys(
    (*PRECISIONS, "float16", "float64", "i64", "exact", "boolean", "any")
))

FUNCTION_STATUSES = frozenset({"proposed", "active", "deprecated", "revoked"})
NUMERIC_PROOF_STATUSES = frozenset({"verified", "proven", "axiom"})

_FUNCTION_ID_RE = re.compile(r"^math\.[a-z0-9][a-z0-9_.-]{0,120}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

_CATALOG_KEYS = frozenset({
    "schema", "version", "generated_by", "notes", "description", "functions",
})
_FUNCTION_KEYS = frozenset({
    "schema", "function_id", "version", "family", "signature", "semantics",
    "preconditions", "postconditions", "undefined_conditions",
    "numerical_policy", "implementations", "proof_status", "status",
    "contract_digest",
})
_IMPLEMENTATION_KEYS = frozenset({
    "kernel_id", "version", "source_digest", "fixture_digest", "precision",
    "shape", "workspace_words", "capability_class", "implementation_digest",
    "source", "fixture", "marker", "steps", "tags", "notes",
})
_SIGNATURE_KEYS = frozenset({"inputs", "output", "name", "description"})
_ENDPOINT_KEYS = frozenset({
    "name", "type", "domain", "shape", "precision", "invariants", "requires",
    "guarantees", "role", "unit", "units", "layout", "dtype", "element",
    "element_type", "stride", "strides", "rank", "context", "description",
})
_POLICY_KEYS = frozenset({
    "precision", "rounding", "reduction_order", "fma", "nan_propagation",
    "overflow", "subnormals", "accumulation", "deterministic", "exact",
    "components", "notes",
})
_PROOF_RANK = {
    "none": 0,
    "stated": 1,
    "experimental": 2,
    "empirical": 3,
    "tested": 4,
    "verified": 5,
    "proven": 6,
    "axiom": 6,
    "rejected": -1,
}


class MathRegistryError(ValueError):
    """Base class for semantic registry, catalogue, and composition failures."""


class MathCatalogError(MathRegistryError):
    """Raised when ``spec/math-functions.v1.json`` is structurally invalid."""


class MathFunctionError(MathRegistryError):
    """Raised for an unknown or invalid semantic function contract."""


class MathImplementationError(MathRegistryError):
    """Raised when a function implementation does not match MthRegistry facts."""


class MathCompositionError(MathRegistryError):
    """Raised when two function contracts cannot be composed."""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_text(value: Any, name: str, *, maximum: int = 256,
                  error_cls: type[MathRegistryError] = MathRegistryError) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise error_cls(f"{name} must be a non-empty string <= {maximum} characters")
    return value


def _require_int(value: Any, name: str, *, minimum: int = 0,
                 error_cls: type[MathRegistryError] = MathRegistryError) -> int:
    if not _is_int(value) or value < minimum:
        raise error_cls(f"{name} must be an integer >= {minimum}")
    return value


def _require_bool(value: Any, name: str, *,
                  error_cls: type[MathRegistryError] = MathRegistryError) -> bool:
    if not isinstance(value, bool):
        raise error_cls(f"{name} must be a boolean")
    return value


def _require_mapping(value: Any, name: str,
                     error_cls: type[MathRegistryError] = MathRegistryError) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise error_cls(f"{name} must be an object")
    return dict(value)


def _require_string_list(value: Any, name: str,
                         error_cls: type[MathRegistryError] = MathRegistryError) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise error_cls(f"{name} must be a list of strings")
    result: list[str] = []
    for entry in value:
        result.append(_require_text(entry, f"{name} entry", error_cls=error_cls))
    return result


def _normalize_shape(value: Any, name: str,
                     error_cls: type[MathRegistryError] = MathRegistryError) -> Any:
    if isinstance(value, str):
        if value not in {"any", "*"}:
            raise error_cls(f"{name} must be a list of dimensions or 'any'")
        return "any"
    if not isinstance(value, (list, tuple)) or not value:
        raise error_cls(f"{name} must be a non-empty list of positive dimensions")
    dimensions: list[int] = []
    for dimension in value:
        dimensions.append(_require_int(
            dimension, f"{name} dimension", minimum=1, error_cls=error_cls,
        ))
    return dimensions


def _normalize_conditions(value: Any, name: str,
                          error_cls: type[MathRegistryError] = MathRegistryError
                          ) -> tuple[dict[str, Any], ...]:
    """Accept object conditions and the shorthand string form from the plan."""
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise error_cls(f"{name} must be a list of condition objects or strings")
    conditions: list[dict[str, Any]] = []
    for index, entry in enumerate(value):
        if isinstance(entry, str):
            text = entry.strip()
            if not text:
                raise error_cls(f"{name} entry {index} must not be empty")
            conditions.append({"expr": text})
        elif isinstance(entry, Mapping):
            conditions.append(dict(entry))
        else:
            raise error_cls(f"{name} entry {index} must be an object or string")
    return tuple(conditions)


def _validate_endpoint(value: Any, name: str, *, require_name: bool,
                       error_cls: type[MathRegistryError] = MathRegistryError
                       ) -> dict[str, Any]:
    endpoint = _require_mapping(value, name, error_cls=error_cls)
    unknown = set(endpoint) - _ENDPOINT_KEYS
    if unknown:
        raise error_cls(f"{name} has unknown fields: {', '.join(sorted(unknown))}")
    if require_name:
        _require_text(endpoint.get("name"), f"{name}.name", maximum=128,
                      error_cls=error_cls)
    endpoint_type = _require_text(
        endpoint.get("type"), f"{name}.type", maximum=64, error_cls=error_cls,
    )
    if not re.fullmatch(r"[a-z][a-z0-9_.:*+-]{0,63}", endpoint_type):
        raise error_cls(f"{name}.type is not a lowercase typed name: {endpoint_type!r}")
    domain = endpoint.get("domain", "any")
    _require_text(domain, f"{name}.domain", maximum=64, error_cls=error_cls)
    endpoint["domain"] = domain

    if "shape" in endpoint:
        endpoint["shape"] = _normalize_shape(
            endpoint["shape"], f"{name}.shape", error_cls=error_cls,
        )
    if "precision" in endpoint:
        precision = endpoint["precision"]
        if not isinstance(precision, str) or precision not in MATH_PRECISIONS:
            raise error_cls(f"{name}.precision is not a supported precision")
    for field in ("invariants", "requires", "guarantees"):
        if field in endpoint:
            endpoint[field] = _require_string_list(
                endpoint[field], f"{name}.{field}", error_cls=error_cls,
            )
    MathTypeDescriptor.from_mapping(
        endpoint, name, error_cls=error_cls, include_nested_type=True,
    )
    return endpoint


def _validate_signature(value: Any,
                        error_cls: type[MathRegistryError] = MathRegistryError
                        ) -> dict[str, Any]:
    signature = _require_mapping(value, "signature", error_cls=error_cls)
    unknown = set(signature) - _SIGNATURE_KEYS
    if unknown:
        raise error_cls(f"signature has unknown fields: {', '.join(sorted(unknown))}")
    raw_inputs = signature.get("inputs")
    if not isinstance(raw_inputs, (list, tuple)) or not raw_inputs:
        raise error_cls("signature.inputs must be a non-empty list")
    inputs: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, raw_input in enumerate(raw_inputs):
        endpoint = _validate_endpoint(
            raw_input, f"signature.inputs[{index}]", require_name=True,
            error_cls=error_cls,
        )
        if endpoint["name"] in names:
            raise error_cls(f"duplicate signature input name: {endpoint['name']!r}")
        names.add(endpoint["name"])
        inputs.append(endpoint)
    if "output" not in signature:
        raise error_cls("signature.output is required")
    output = _validate_endpoint(
        signature["output"], "signature.output", require_name=False,
        error_cls=error_cls,
    )
    normalized = dict(signature)
    normalized["inputs"] = inputs
    normalized["output"] = output
    return normalized


def _validate_numerical_policy(value: Any, signature: Mapping[str, Any],
                               error_cls: type[MathRegistryError] = MathRegistryError
                               ) -> dict[str, Any]:
    policy = _require_mapping(value, "numerical_policy", error_cls=error_cls)
    if not policy:
        raise error_cls("numerical_policy must not be empty")
    unknown = set(policy) - _POLICY_KEYS
    if unknown:
        raise error_cls(
            f"numerical_policy has unknown fields: {', '.join(sorted(unknown))}"
        )
    precision = policy.get("precision")
    if not isinstance(precision, str) or precision not in MATH_PRECISIONS:
        raise error_cls("numerical_policy.precision is required and must be supported")
    output_precision = signature["output"].get("precision")
    if (output_precision and output_precision != "any"
            and precision != "any" and output_precision != precision):
        raise error_cls(
            "numerical_policy.precision does not match the output precision"
        )
    for field in ("rounding", "reduction_order", "nan_propagation", "overflow",
                  "subnormals", "accumulation", "notes"):
        if field in policy and not isinstance(policy[field], str):
            raise error_cls(f"numerical_policy.{field} must be a string")
    for field in ("fma", "deterministic", "exact"):
        if field in policy:
            _require_bool(policy[field], f"numerical_policy.{field}",
                          error_cls=error_cls)
    if "components" in policy:
        components = policy["components"]
        if not isinstance(components, (list, tuple)):
            raise error_cls("numerical_policy.components must be a list")
        for index, component in enumerate(components):
            _require_mapping(component, f"numerical_policy.components[{index}]",
                             error_cls=error_cls)
    return policy


def _validate_proof_discipline(function: MathFunction) -> None:
    """Reject proof claims that are internally inconsistent or overclaimed."""
    if function.status not in FUNCTION_STATUSES:
        raise MathFunctionError(f"unknown function status: {function.status!r}")
    if function.proof_status not in PROOF_STATUSES:
        raise MathFunctionError(f"unknown proof_status: {function.proof_status!r}")
    if function.status == "active" and function.proof_status in {"none", "rejected"}:
        raise MathFunctionError(
            f"{function.function_id}: active functions must declare proof/test status"
        )
    if function.proof_status == "rejected" and function.status not in {
        "deprecated", "revoked",
    }:
        raise MathFunctionError(
            f"{function.function_id}: rejected proof status requires revoked/deprecated"
        )
    if function.proof_status == "verified" and not function.implementations:
        raise MathFunctionError(
            f"{function.function_id}: verified proof status requires a native "
            "implementation"
        )


def function_family(function_or_id: MathFunction | str) -> str:
    """Return the family segment of ``math.<family>.<name>``."""
    function_id = (
        function_or_id.function_id
        if isinstance(function_or_id, MathFunction)
        else function_or_id
    )
    parts = _require_text(function_id, "function_id").split(".")
    if len(parts) < 3 or parts[0] != "math" or not parts[1]:
        raise MathFunctionError(
            "function_id must have the form math.<family>.<name>"
        )
    return parts[1]


def implementation_digest(descriptor: MthKernelDescriptor) -> str:
    """Stable digest of the validated implementation facts for one kernel."""
    if not isinstance(descriptor, MthKernelDescriptor):
        raise MathImplementationError(
            "implementation_digest requires an MthKernelDescriptor"
        )
    return digest_object({
        "kernel_id": descriptor.kernel_id,
        "version": descriptor.version,
        "source_digest": descriptor.source_digest,
        "fixture_digest": descriptor.fixture_digest,
        "precision": descriptor.precision,
        "shape": list(descriptor.shape),
        "workspace_words": descriptor.workspace_words,
    })


def _validate_implementations(function: MathFunction, registry: MthRegistry) -> None:
    if not isinstance(registry, MthRegistry):
        raise MathImplementationError("implementations must be an MthRegistry")
    seen: set[str] = set()
    for index, raw in enumerate(function.implementations):
        if not isinstance(raw, Mapping):
            raise MathImplementationError(
                f"{function.function_id}: implementation {index} must be an object"
            )
        implementation = dict(raw)
        unknown = set(implementation) - _IMPLEMENTATION_KEYS
        if unknown:
            raise MathImplementationError(
                f"{function.function_id}: implementation {index} has unknown "
                f"fields: {', '.join(sorted(unknown))}"
            )
        kernel_id = _require_text(
            implementation.get("kernel_id"),
            f"{function.function_id}: implementation {index}.kernel_id",
            maximum=128, error_cls=MathImplementationError,
        )
        if kernel_id in seen:
            raise MathImplementationError(
                f"{function.function_id}: duplicate implementation {kernel_id}"
            )
        seen.add(kernel_id)
        descriptor = registry.lookup(kernel_id)
        if descriptor is None:
            raise MathImplementationError(
                f"{function.function_id}: missing implementation kernel "
                f"{kernel_id!r} in MthRegistry"
            )
        if descriptor.status == "revoked":
            raise MathImplementationError(
                f"{function.function_id}: implementation {kernel_id!r} is revoked"
            )
        if descriptor.status != "native_verified":
            raise MathImplementationError(
                f"{function.function_id}: implementation {kernel_id!r} is not "
                f"native_verified (status={descriptor.status!r})"
            )
        if not descriptor.ci_verified:
            raise MathImplementationError(
                f"{function.function_id}: implementation {kernel_id!r} is not "
                "CI-verified"
            )

        if "version" in implementation:
            version = _require_int(
                implementation["version"],
                f"{function.function_id}: implementation {index}.version",
                minimum=1, error_cls=MathImplementationError,
            )
            if version != descriptor.version:
                raise MathImplementationError(
                    f"{function.function_id}: implementation {kernel_id!r} "
                    f"version {version} != MthRegistry version {descriptor.version}"
                )
        for field in ("source_digest", "fixture_digest"):
            if field in implementation:
                declared = implementation[field]
                actual = getattr(descriptor, field)
                if declared != actual:
                    raise MathImplementationError(
                        f"{function.function_id}: implementation {kernel_id!r} "
                        f"{field} does not match MthRegistry"
                    )
        if "precision" in implementation:
            if implementation["precision"] != descriptor.precision:
                raise MathImplementationError(
                    f"{function.function_id}: implementation {kernel_id!r} "
                    f"precision {implementation['precision']!r} != "
                    f"{descriptor.precision!r}"
                )
        policy_precision = function.numerical_policy.get("precision")
        if (policy_precision in PRECISIONS
                and descriptor.precision != policy_precision):
            raise MathImplementationError(
                f"{function.function_id}: implementation {kernel_id!r} precision "
                f"{descriptor.precision!r} does not satisfy contract precision "
                f"{policy_precision!r}"
            )
        endpoints = [*function.signature["inputs"], function.signature["output"]]
        declared_precisions = {
            endpoint.get("precision")
            for endpoint in endpoints
            if endpoint.get("precision") in PRECISIONS
        }
        if declared_precisions and descriptor.precision not in declared_precisions:
            raise MathImplementationError(
                f"{function.function_id}: implementation {kernel_id!r} precision "
                f"{descriptor.precision!r} is not declared by the function "
                "signature"
            )
        declared_shapes = {
            tuple(endpoint["shape"])
            for endpoint in endpoints
            if isinstance(endpoint.get("shape"), (list, tuple))
        }
        if declared_shapes and descriptor.shape not in declared_shapes:
            raise MathImplementationError(
                f"{function.function_id}: implementation {kernel_id!r} shape "
                f"{list(descriptor.shape)!r} is not declared by the function "
                "signature"
            )
        if "shape" in implementation:
            declared_shape = _normalize_shape(
                implementation["shape"],
                f"{function.function_id}: implementation {index}.shape",
                error_cls=MathImplementationError,
            )
            if tuple(declared_shape) != descriptor.shape:
                raise MathImplementationError(
                    f"{function.function_id}: implementation {kernel_id!r} shape "
                    f"{declared_shape!r} != {list(descriptor.shape)!r}"
                )
        if "workspace_words" in implementation:
            workspace = _require_int(
                implementation["workspace_words"],
                f"{function.function_id}: implementation {index}.workspace_words",
                minimum=0, error_cls=MathImplementationError,
            )
            if workspace != descriptor.workspace_words:
                raise MathImplementationError(
                    f"{function.function_id}: implementation {kernel_id!r} "
                    f"workspace_words {workspace} != "
                    f"{descriptor.workspace_words}"
                )
        actual_implementation_digest = implementation_digest(descriptor)
        if "implementation_digest" in implementation:
            if implementation["implementation_digest"] != actual_implementation_digest:
                raise MathImplementationError(
                    f"{function.function_id}: implementation {kernel_id!r} "
                    "implementation_digest does not match MthRegistry facts"
                )

    if function.proof_status == "verified" and not function.implementations:
        raise MathFunctionError(
            f"{function.function_id}: verified proof status requires a native "
            "implementation"
        )


def _normalize_function(function: MathFunction) -> MathFunction:
    if not isinstance(function, MathFunction):
        raise MathFunctionError("function must be a MathFunction")
    if not _FUNCTION_ID_RE.fullmatch(function.function_id):
        raise MathFunctionError(
            "function_id must be a math.<family>.<name> identifier"
        )
    function_family(function.function_id)
    _require_int(function.version, "version", minimum=1,
                 error_cls=MathFunctionError)
    signature = _validate_signature(function.signature,
                                    error_cls=MathFunctionError)
    policy = _validate_numerical_policy(
        function.numerical_policy, signature, error_cls=MathFunctionError,
    )
    preconditions = _normalize_conditions(
        function.preconditions, "preconditions", error_cls=MathFunctionError,
    )
    postconditions = _normalize_conditions(
        function.postconditions, "postconditions", error_cls=MathFunctionError,
    )
    undefined_conditions = _normalize_conditions(
        function.undefined_conditions, "undefined_conditions",
        error_cls=MathFunctionError,
    )
    semantics = _require_mapping(function.semantics, "semantics",
                                 error_cls=MathFunctionError)
    normalized = replace(
        function,
        signature=signature,
        semantics=semantics,
        numerical_policy=policy,
        preconditions=preconditions,
        postconditions=postconditions,
        undefined_conditions=undefined_conditions,
    )
    _validate_proof_discipline(normalized)
    return normalized


def _parse_function(raw: Any, index: int) -> MathFunction:
    if not isinstance(raw, Mapping):
        raise MathCatalogError(f"function entry {index} must be an object")
    unknown = set(raw) - _FUNCTION_KEYS
    if unknown:
        raise MathCatalogError(
            f"function entry {index} has unknown fields: "
            f"{', '.join(sorted(unknown))}"
        )
    schema = raw.get("schema")
    if schema is not None and schema != FUNCTION_SCHEMA:
        raise MathCatalogError(
            f"function entry {index} has unsupported schema: {schema!r}"
        )
    function_id = _require_text(
        raw.get("function_id"), f"function entry {index}: function_id",
        maximum=128, error_cls=MathCatalogError,
    )
    family = raw.get("family")
    if family is not None:
        declared_family = _require_text(
            family, f"{function_id}: family", maximum=64,
            error_cls=MathCatalogError,
        )
        id_parts = function_id.split(".")
        if len(id_parts) < 3 or declared_family != id_parts[1]:
            raise MathCatalogError(
                f"{function_id}: family does not match function_id"
            )
    contract_digest = raw.get("contract_digest")
    if isinstance(contract_digest, str) and contract_digest.startswith("sha256:"):
        contract_digest = contract_digest[len("sha256:"):]
    try:
        function = MathFunction(
            function_id=function_id,
            version=raw.get("version", 1),
            signature=raw.get("signature", {}),
            semantics=raw.get("semantics", {}),
            preconditions=_normalize_conditions(
                raw.get("preconditions"), f"{function_id}: preconditions",
                error_cls=MathCatalogError,
            ),
            postconditions=_normalize_conditions(
                raw.get("postconditions"), f"{function_id}: postconditions",
                error_cls=MathCatalogError,
            ),
            undefined_conditions=_normalize_conditions(
                raw.get("undefined_conditions"),
                f"{function_id}: undefined_conditions",
                error_cls=MathCatalogError,
            ),
            numerical_policy=raw.get("numerical_policy", {}),
            implementations=raw.get("implementations", ()),
            proof_status=raw.get("proof_status", "none"),
            status=raw.get("status", "proposed"),
            contract_digest=contract_digest,
        )
    except (MathObjectError, TypeError, ValueError) as exc:
        raise MathCatalogError(f"function entry {index}: {exc}") from exc
    return function


def _contract_key(contract: Mapping[str, Any]) -> dict[str, Any]:
    key = {
        "type": contract.get("type"),
        "domain": contract.get("domain", "any"),
    }
    if "shape" in contract:
        key["shape"] = contract["shape"]
    if "precision" in contract:
        key["precision"] = contract["precision"]
    invariant_fields = {"type", "domain", "shape", "precision"}
    descriptor = MathTypeDescriptor.from_mapping(contract)
    for name, value in descriptor.to_dict().items():
        if name not in invariant_fields:
            key[name] = value
    invariants = contract.get("invariants") or contract.get("guarantees")
    if invariants:
        key["invariants"] = sorted(invariants)
    return key


def _contract_satisfies(output: Mapping[str, Any],
                        required: Mapping[str, Any]) -> tuple[bool, str]:
    """Return whether an output contract satisfies a consumer input contract."""
    output_type = output.get("type")
    required_type = required.get("type", "any")
    if required_type not in {"any", "*"} and output_type != required_type:
        return False, f"type {output_type!r} does not satisfy {required_type!r}"

    required_domain = required.get("domain", "any")
    output_domain = output.get("domain", "any")
    if required_domain not in {"any", "*"} and output_domain != required_domain:
        return (
            False,
            f"domain {output_domain!r} does not satisfy {required_domain!r}",
        )

    required_shape = required.get("shape")
    if required_shape not in (None, "any", "*"):
        output_shape = output.get("shape")
        if output_shape in (None, "any", "*"):
            return False, "output shape is not declared"
        if list(output_shape) != list(required_shape):
            return (
                False,
                f"shape {list(output_shape)!r} does not satisfy "
                f"{list(required_shape)!r}",
            )

    required_precision = required.get("precision")
    if required_precision not in (None, "any", "*"):
        output_precision = output.get("precision")
        if output_precision != required_precision:
            return (
                False,
                f"precision {output_precision!r} does not satisfy "
                f"{required_precision!r}",
            )

    output_descriptor = MathTypeDescriptor.from_mapping(output)
    required_descriptor = MathTypeDescriptor.from_mapping(required)
    issues = output_descriptor.compatibility_issues(required_descriptor)
    if issues:
        return False, issues[0]

    required_invariants = required.get("invariants") or required.get("requires") or []
    output_invariants = set(
        output.get("invariants") or output.get("guarantees") or []
    )
    missing = [item for item in required_invariants if item not in output_invariants]
    if missing:
        return False, f"missing output invariants: {', '.join(missing)}"
    return True, ""


def _merge_conditions(*groups: Iterable[Mapping[str, Any]]
                      ) -> tuple[dict[str, Any], ...]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for condition in group:
            item = dict(condition)
            key = canonical_json(item)
            if key not in seen:
                seen.add(key)
                merged.append(item)
    return tuple(merged)


def _proof_for_composition(functions: Sequence[MathFunction]) -> str:
    if all(item.proof_status in NUMERIC_PROOF_STATUSES for item in functions):
        # ``verified`` is reserved for a native implementation; a composition
        # is structurally checked but not itself native-verified.
        return "proven" if all(
            item.proof_status in {"proven", "axiom"} for item in functions
        ) else "stated"
    weakest = min(
        (item.proof_status for item in functions),
        key=lambda status: _PROOF_RANK.get(status, 0),
    )
    return "stated" if weakest in {"none", "rejected"} else weakest


class MathFunctionRegistry:
    """Immutable semantic function registry over a validated ``MthRegistry``."""

    def __init__(self, functions: Iterable[MathFunction],
                 implementations: MthRegistry, *,
                 catalog_path: str | Path | None = None,
                 version: int = CATALOG_VERSION) -> None:
        if not isinstance(implementations, MthRegistry):
            raise MathFunctionError("implementations must be an MthRegistry")
        self._implementations = implementations
        self._catalog_path = (
            None if catalog_path is None else Path(catalog_path)
        )
        self._version = _require_int(version, "catalog version", minimum=1)

        ordered: list[MathFunction] = []
        latest: dict[str, MathFunction] = {}
        by_id: dict[str, dict[int, MathFunction]] = {}
        for raw_function in functions:
            function = self._finalize_function(raw_function)
            versions = by_id.setdefault(function.function_id, {})
            if function.version in versions:
                raise MathCatalogError(
                    f"duplicate function contract: {function.function_id} "
                    f"version {function.version}"
                )
            versions[function.version] = function
            if (function.function_id not in latest
                    or function.version > latest[function.function_id].version):
                latest[function.function_id] = function
            ordered.append(function)
        if not ordered:
            raise MathCatalogError("catalog has no functions")

        self._functions = tuple(ordered)
        self._by_id = by_id
        self._latest = latest

    @classmethod
    def load(cls, path: str | Path, *,
             implementations: MthRegistry | str | Path | None = None,
             implementation_path: str | Path | None = None,
             root: str | Path | None = None) -> "MathFunctionRegistry":
        """Load a ``math-functions.v1`` catalog and its implementation registry.

        When ``implementations`` is omitted the sibling
        ``spec/wave-capabilities.json`` is loaded.  A missing sibling falls back
        to this repository's frozen spec so temporary catalogues can be tested
        without copying the 61-kernel manifest.
        """
        catalog_path = Path(path)
        if not catalog_path.is_file():
            raise MathCatalogError(f"catalog not found: {catalog_path}")
        try:
            document = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MathCatalogError(f"cannot read catalog: {catalog_path}") from exc

        if implementations is None:
            if implementation_path is not None:
                manifest_path = Path(implementation_path)
            else:
                manifest_path = catalog_path.parent / "wave-capabilities.json"
                if not manifest_path.is_file():
                    manifest_path = (
                        Path(__file__).resolve().parent.parent
                        / "spec" / "wave-capabilities.json"
                    )
            implementations = MthRegistry.load(manifest_path, root=root)
        elif isinstance(implementations, (str, Path)):
            implementations = MthRegistry.load(implementations, root=root)
        elif not isinstance(implementations, MthRegistry):
            raise MathFunctionError(
                "implementations must be an MthRegistry, path, or None"
            )
        return cls.from_dict(
            document, implementations, catalog_path=catalog_path,
        )

    @classmethod
    def from_dict(cls, document: Mapping[str, Any], implementations: MthRegistry, *,
                  catalog_path: str | Path | None = None) -> "MathFunctionRegistry":
        """Validate a catalogue document and build a registry."""
        if not isinstance(document, Mapping):
            raise MathCatalogError("catalog must be a JSON object")
        unknown = set(document) - _CATALOG_KEYS
        if unknown:
            raise MathCatalogError(
                f"catalog has unknown fields: {', '.join(sorted(unknown))}"
            )
        if document.get("schema") != CATALOG_SCHEMA:
            raise MathCatalogError(
                f"unsupported catalog schema: {document.get('schema')!r}"
            )
        version = _require_int(
            document.get("version", CATALOG_VERSION), "catalog version",
            minimum=1, error_cls=MathCatalogError,
        )
        raw_functions = document.get("functions")
        if not isinstance(raw_functions, (list, tuple)) or not raw_functions:
            raise MathCatalogError("catalog.functions must be a non-empty list")
        functions = [
            _parse_function(raw, index)
            for index, raw in enumerate(raw_functions)
        ]
        return cls(
            functions, implementations, catalog_path=catalog_path,
            version=version,
        )

    def _finalize_function(self, function: MathFunction) -> MathFunction:
        normalized = _normalize_function(function)
        _validate_implementations(normalized, self._implementations)
        computed_digest = normalized.digest()
        if (normalized.contract_digest is not None
                and normalized.contract_digest != computed_digest):
            raise MathCatalogError(
                f"{normalized.function_id}: contract_digest does not match "
                "the canonical contract"
            )
        return replace(normalized, contract_digest=computed_digest)

    def __len__(self) -> int:
        return len(self._latest)

    def __iter__(self):
        return iter(self._functions)

    def __contains__(self, function_id: object) -> bool:
        return isinstance(function_id, str) and function_id in self._by_id

    def __repr__(self) -> str:
        return (
            f"MathFunctionRegistry(functions={len(self._latest)}, "
            f"versions={len(self._functions)})"
        )

    @property
    def functions(self) -> tuple[MathFunction, ...]:
        return self._functions

    @property
    def implementation_registry(self) -> MthRegistry:
        return self._implementations

    @property
    def catalog_path(self) -> Path | None:
        return self._catalog_path

    @property
    def version(self) -> int:
        return self._version

    def lookup(self, function_id: str,
               version: int | None = None) -> MathFunction | None:
        """Return a function contract, or ``None`` when it is unknown."""
        if not isinstance(function_id, str) or not function_id:
            return None
        versions = self._by_id.get(function_id)
        if not versions:
            return None
        if version is None:
            return versions[max(versions)]
        if not _is_int(version) or version < 1:
            return None
        return versions.get(version)

    def require(self, function_id: str,
                version: int | None = None) -> MathFunction:
        """Return a function contract or raise :class:`MathFunctionError`."""
        if not isinstance(function_id, str) or not function_id:
            raise MathFunctionError("function_id must be a non-empty string")
        function = self.lookup(function_id, version)
        if function is None:
            suffix = "" if version is None else f" version {version}"
            raise MathFunctionError(f"unknown function_id: {function_id}{suffix}")
        return function

    def resolve(self, *, family: str | None = None,
                tags: str | Iterable[str] | None = None,
                status: str | None = None,
                proof_status: str | None = None,
                require_implementations: bool = False,
                max_workspace: int | None = None,
                require_ci: bool = True) -> tuple[MathFunction, ...]:
        """Select the latest contract version of each function in catalog order.

        ``status`` defaults to ``None`` (all statuses).  ``max_workspace``
        requires at least one implementation within the bound, so functions
        without a native implementation are excluded when a bound is supplied.
        """
        if family is not None:
            _require_text(family, "family")
        if status is not None:
            _require_text(status, "status")
            if status not in FUNCTION_STATUSES:
                raise MathFunctionError(f"unknown function status: {status!r}")
        if proof_status is not None:
            _require_text(proof_status, "proof_status")
            if proof_status not in PROOF_STATUSES:
                raise MathFunctionError(f"unknown proof_status: {proof_status!r}")
        if tags is None:
            requested: tuple[str, ...] = ()
        elif isinstance(tags, str):
            requested = (tags,)
        else:
            try:
                requested = tuple(tags)
            except TypeError as exc:
                raise MathFunctionError(
                    "tags must be a string or iterable of strings"
                ) from exc
        for tag in requested:
            _require_text(tag, "tag", maximum=128)
        if max_workspace is not None:
            _require_int(max_workspace, "max_workspace", minimum=0)
        _require_bool(require_implementations, "require_implementations")
        _require_bool(require_ci, "require_ci")

        wanted = set(requested)
        selected: list[MathFunction] = []
        for function in self._functions:
            if self._latest[function.function_id] is not function:
                continue
            if family is not None and function_family(function.function_id) != family:
                continue
            if status is not None and function.status != status:
                continue
            if proof_status is not None and function.proof_status != proof_status:
                continue
            if require_implementations and not function.implementations:
                continue
            if wanted and not wanted.issubset(self._function_tags(function)):
                continue
            if max_workspace is not None:
                qualifying = [
                    implementation
                    for implementation in function.implementations
                    if self._implementation_within_workspace(
                        implementation, max_workspace, require_ci,
                    )
                ]
                if not qualifying:
                    continue
            elif require_ci and function.implementations:
                if not any(
                    self._implementation_ci_verified(implementation)
                    for implementation in function.implementations
                ):
                    continue
            selected.append(function)
        return tuple(selected)

    def _implementation_ci_verified(self, implementation: Mapping[str, Any]) -> bool:
        descriptor = self._implementations.lookup(
            str(implementation.get("kernel_id", ""))
        )
        return descriptor is not None and descriptor.ci_verified

    def _implementation_within_workspace(self, implementation: Mapping[str, Any],
                                         maximum: int, require_ci: bool) -> bool:
        descriptor = self._implementations.lookup(
            str(implementation.get("kernel_id", ""))
        )
        if descriptor is None:
            return False
        if require_ci and not descriptor.ci_verified:
            return False
        return descriptor.workspace_words <= maximum

    def _function_tags(self, function: MathFunction) -> frozenset[str]:
        tags = {
            f"family:{function_family(function.function_id)}",
            f"status:{function.status}",
            f"proof:{function.proof_status}",
            f"version:{function.version}",
        }
        signature = function.signature
        output = signature["output"]
        tags.add(f"output:{output['type']}")
        if output.get("domain"):
            tags.add(f"domain:{output['domain']}")
        if output.get("precision"):
            tags.add(f"precision:{output['precision']}")
        for endpoint in signature["inputs"]:
            tags.add(f"input:{endpoint['type']}")
        if function.implementations:
            tags.add("implementation:native")
        else:
            tags.add("implementation:none")
        return frozenset(tags)

    def validate_contract(self, function: MathFunction) -> MathFunction:
        """Validate one contract against the same rules used at load time."""
        return self._finalize_function(function)

    def compose(self, functions: Iterable[MathFunction | str] | MathFunction | str,
                *more: MathFunction | str) -> MathFunction:
        """Compose contracts left-to-right when output satisfies input.

        Accepts either ``compose([a, b, c])`` or ``compose(a, b, c)``.  Each
        consumer except the first must have exactly one input, because chained
        output is bound to that input.  Composition never selects or invokes a
        kernel; it creates a new contract leaf with no native implementation.
        """
        if isinstance(functions, (str, MathFunction)):
            chain: tuple[MathFunction | str, ...] = (functions,) + tuple(more)
        else:
            if more:
                raise MathCompositionError(
                    "pass either one iterable or multiple function arguments"
                )
            try:
                chain = tuple(functions)
            except TypeError as exc:
                raise MathCompositionError(
                    "compose requires an iterable of functions"
                ) from exc
        resolved: list[MathFunction] = []
        for item in chain:
            if isinstance(item, str):
                resolved.append(self.require(item))
            elif isinstance(item, MathFunction):
                resolved.append(self.validate_contract(item))
            else:
                raise MathCompositionError(
                    "composition members must be function IDs or MathFunction"
                )
        if not resolved:
            raise MathCompositionError("composition requires at least one function")
        if any(item.status == "revoked" for item in resolved):
            raise MathCompositionError("revoked functions cannot be composed")
        if len(resolved) == 1:
            return resolved[0]

        for left, right in zip(resolved, resolved[1:]):
            right_inputs = right.signature["inputs"]
            if len(right_inputs) != 1:
                raise MathCompositionError(
                    f"{right.function_id}: composition requires exactly one input, "
                    f"found {len(right_inputs)}"
                )
            satisfied, reason = _contract_satisfies(
                left.signature["output"], right_inputs[0],
            )
            if not satisfied:
                raise MathCompositionError(
                    f"cannot compose {left.function_id} -> {right.function_id}: "
                    f"{reason}"
                )

        component_payload = [
            {
                "function_id": item.function_id,
                "version": item.version,
                "contract_digest": item.contract_digest or item.digest(),
            }
            for item in resolved
        ]
        composition_id = (
            "math.composition."
            + digest_object({"components": component_payload})[:16]
        )
        signature = {
            "inputs": [dict(item) for item in resolved[0].signature["inputs"]],
            "output": dict(resolved[-1].signature["output"]),
        }
        output_precision = signature["output"].get("precision")
        policy_precision = output_precision
        if policy_precision is None:
            policy_precision = resolved[-1].numerical_policy.get("precision", "any")
        numerical_policy = {
            "precision": policy_precision,
            "rounding": "per-component",
            "reduction_order": "per-component",
            "fma": False,
            "nan_propagation": "per-component",
            "deterministic": all(
                item.numerical_policy.get("deterministic", True)
                for item in resolved
            ),
            "components": [
                dict(item.numerical_policy) for item in resolved
            ],
        }
        function = MathFunction(
            function_id=composition_id,
            version=1,
            signature=signature,
            semantics={
                "definition": "left-to-right contract composition",
                "composition": [item.function_id for item in resolved],
                "component_versions": [item.version for item in resolved],
            },
            preconditions=_merge_conditions(
                *(item.preconditions for item in resolved)
            ),
            postconditions=_merge_conditions(
                *(item.postconditions for item in resolved)
            ),
            undefined_conditions=_merge_conditions(
                *(item.undefined_conditions for item in resolved)
            ),
            numerical_policy=numerical_policy,
            implementations=(),
            proof_status=_proof_for_composition(resolved),
            status=(
                "active" if all(item.status == "active" for item in resolved)
                else "proposed"
            ),
        )
        computed_digest = function.digest()
        return replace(function, contract_digest=computed_digest)

    def compatibility_index(self, *, status: str | None = None,
                            require_implementations: bool = False
                            ) -> dict[str, Any]:
        """Deterministic compatibility cache keyed by full input/output contract."""
        entries: list[dict[str, Any]] = []
        for function in self.resolve(
                status=status,
                require_implementations=require_implementations,
        ):
            signature = function.signature
            payload = {
                "inputs": [_contract_key(item) for item in signature["inputs"]],
                "output": _contract_key(signature["output"]),
            }
            entries.append({
                "signature_key": sha256_text(canonical_json(payload)),
                "function_id": function.function_id,
                "version": function.version,
                "contract_digest": function.contract_digest,
            })
        entries.sort(key=lambda entry: (
            entry["signature_key"], entry["function_id"], entry["version"],
        ))
        return {
            "schema": COMPATIBILITY_SCHEMA,
            "entries": entries,
            "functions": len(entries),
        }

    def health(self) -> dict[str, Any]:
        """Return deterministic registry/implementation health counts."""
        status_counts = Counter(
            function.status for function in self._latest.values()
        )
        proof_counts = Counter(
            function.proof_status for function in self._latest.values()
        )
        family_counts = Counter(
            function_family(function.function_id)
            for function in self._latest.values()
        )
        implementations = [
            implementation
            for function in self._latest.values()
            for implementation in function.implementations
        ]
        kernels = {
            str(implementation.get("kernel_id")) for implementation in implementations
        }
        implemented_functions = sum(
            1 for function in self._latest.values() if function.implementations
        )
        return {
            "schema": HEALTH_SCHEMA,
            "catalog_version": self._version,
            "catalog": None if self._catalog_path is None else str(self._catalog_path),
            "functions": len(self._latest),
            "contracts": len(self._functions),
            "status": dict(sorted(status_counts.items())),
            "proof_status": dict(sorted(proof_counts.items())),
            "families": dict(sorted(family_counts.items())),
            "implemented_functions": implemented_functions,
            "unimplemented_functions": len(self._latest) - implemented_functions,
            "implementations": len(implementations),
            "implementation_kernels": len(kernels),
            "native_verified_ci": sum(
                1 for implementation in implementations
                if self._implementation_ci_verified(implementation)
            ),
            "mth_kernels": len(self._implementations),
            "healthy": True,
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize the loaded catalogue without changing the MTH manifest."""
        return {
            "schema": CATALOG_SCHEMA,
            "version": self._version,
            "functions": [function.to_dict() for function in self._functions],
        }


__all__ = [
    "CATALOG_SCHEMA",
    "CATALOG_VERSION",
    "COMPATIBILITY_SCHEMA",
    "FUNCTION_STATUSES",
    "HEALTH_SCHEMA",
    "MATH_PRECISIONS",
    "MathCatalogError",
    "MathCompositionError",
    "MathFunctionError",
    "MathFunctionRegistry",
    "MathImplementationError",
    "MathRegistryError",
    "NUMERIC_PROOF_STATUSES",
    "function_family",
    "implementation_digest",
]
