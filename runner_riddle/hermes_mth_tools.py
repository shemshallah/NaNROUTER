"""HERMES tool facade for every registered native MTH kernel.

This adapter exposes the *existing* validated manifest, never a second
arithmetic implementation. A plan is not an execution receipt. Executing it
requires the separate admission/NMP/lease/native guest path; an LLM cannot
turn a catalog claim into an executable capability.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .budget import DEFAULT_GUEST_BUDGET_BYTES
from .mth_registry import MthRegistry, MthRegistryError, MthPlanError

SCHEMA = "nanrouter.hermes-mth-tools.v1"
# mth_execute.nas has exactly these two admitted program/operator paths today.
# Other manifest entries are native fixture-verified, NOT general callable ABIs.
NATIVE_DISPATCH = frozenset({
    "mth.vector.dot256.f32",
    "mth.vector.cosine256.f32",
})
MAX_CATALOG_PAGE = 100
MAX_PLAN_STEPS = 64
WORD_BYTES = 8


class HermesMthToolError(ValueError):
    """Invalid tool or bounded argument. No side effects occurred."""


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise HermesMthToolError(
            f"{label} must be an integer between {minimum} and {maximum}"
        )
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HermesMthToolError("arguments must be an object")
    return value


def _dispatch_mode(kernel_id: str) -> str:
    return ("admission_gated_native_abi"
            if kernel_id in NATIVE_DISPATCH else "native_fixture_only")


def _descriptor(kernel) -> dict[str, Any]:
    return {
        "kernel_id": kernel.kernel_id,
        "precision": kernel.precision,
        "shape": list(kernel.shape),
        "workspace_words": kernel.workspace_words,
        "steps": kernel.steps,
        "status": kernel.status,
        "ci_verified": kernel.ci_verified,
        "tags": list(kernel.tags),
        "execution_mode": _dispatch_mode(kernel.kernel_id),
    }


class HermesMthTools:
    """Lease-scoped read/compose tools for the NaNROUTER HERMES portal.

    Authentication and receipt-to-HW head binding are applied by the caller,
    before calling invoke. All methods here are read-only. In particular this
    does not run fixture images or perform host-side numerical computation.
    """

    def __init__(self, registry: MthRegistry) -> None:
        if not isinstance(registry, MthRegistry):
            raise HermesMthToolError("validated MTH registry required")
        self.registry = registry

    @classmethod
    def from_checkout(cls, root: str | Path | None = None) -> "HermesMthTools":
        base = Path(root) if root is not None else Path(__file__).resolve().parents[1]
        return cls(MthRegistry.load(base / "spec" / "wave-capabilities.json", root=base))

    @staticmethod
    def tool_definitions() -> tuple[dict[str, str], ...]:
        return (
            {"name": "mth.catalog", "description": "Page through native MTH kernels by category/tags."},
            {"name": "mth.inspect", "description": "Inspect a kernel's native source, fixture and provenance."},
            {"name": "mth.categories", "description": "Find available families and native ABI coverage."},
            {"name": "mth.compose", "description": "Validate and compose a bounded multi-kernel MTH plan."},
            {"name": "mth.prepare", "description": "Prepare a single native MTH kernel as a typed plan."},
        )

    def invoke(self, tool: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        args = _mapping({} if arguments is None else arguments)
        if not isinstance(tool, str) or len(tool) > 128:
            raise HermesMthToolError("invalid MTH tool name")
        if tool == "mth.catalog":
            return self.catalog(args)
        if tool == "mth.inspect":
            kernel_id = args.get("kernel_id")
            if not isinstance(kernel_id, str):
                raise HermesMthToolError("kernel_id must be a string")
            kernel = self.registry.require(kernel_id)
            return {"schema": SCHEMA, "tool": tool, "kernel": {
                **kernel.to_dict(),
                "execution_mode": _dispatch_mode(kernel_id),
                "execution_available_here": False,
            }}
        if tool == "mth.categories":
            families = Counter(k.kernel_id.split(".")[1] for k in self.registry.kernels)
            modes = Counter(_dispatch_mode(k.kernel_id) for k in self.registry.kernels)
            return {"schema": SCHEMA, "tool": tool,
                    "total": len(self.registry.kernels),
                    "families": dict(sorted(families.items())),
                    "execution_modes": dict(sorted(modes.items())),
                    "tools": list(self.tool_definitions())}
        if tool == "mth.compose":
            return self.compose(args.get("plan"))
        if tool == "mth.prepare":
            return self.prepare(args)
        raise HermesMthToolError("unknown MTH tool")

    def catalog(self, args: Mapping[str, Any]) -> dict[str, Any]:
        offset = _integer(args.get("offset", 0), "offset", 0, 1_000_000)
        limit = _integer(args.get("limit", 32), "limit", 1, MAX_CATALOG_PAGE)
        tags = args.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        if (not isinstance(tags, list) or len(tags) > 8
                or any(not isinstance(t, str) for t in tags)):
            raise HermesMthToolError("tags must be a list of at most eight strings")
        matches = self.registry.resolve(tags=tags, require_ci=True)
        family = args.get("family")
        if family is not None:
            if not isinstance(family, str) or not family.isascii() or not family.isalnum():
                raise HermesMthToolError("invalid family")
            matches = tuple(k for k in matches if k.kernel_id.split(".")[1] == family)
        selected = matches[offset: offset + limit]
        return {"schema": SCHEMA, "tool": "mth.catalog",
                "total": len(matches), "offset": offset,
                "next_offset": offset + len(selected) if offset + len(selected) < len(matches) else None,
                "kernels": [_descriptor(k) for k in selected]}

    def prepare(self, args: Mapping[str, Any]) -> dict[str, Any]:
        kernel_id = args.get("kernel_id")
        if not isinstance(kernel_id, str):
            raise HermesMthToolError("kernel_id must be a string")
        self.registry.require(kernel_id)
        step = {"name": "kernel", "kernel_id": kernel_id,
                "inputs": args.get("inputs", []),
                "outputs": args.get("outputs", []),
                "depends_on": []}
        for key in ("input_specs", "output_specs"):
            if key in args:
                step[key] = args[key]
        return self.compose({"plan_id": args.get("plan_id", "hermes.mth"),
                             "steps": [step], "fuel": args.get("fuel", 1_000_000)})

    def compose(self, plan_spec: Any) -> dict[str, Any]:
        if not isinstance(plan_spec, Mapping):
            raise HermesMthToolError("plan must be an object")
        steps = plan_spec.get("steps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_PLAN_STEPS:
            raise HermesMthToolError("plan must contain 1..64 steps")
        plan = self.registry.compose(plan_spec)
        footprint = plan.workspace_words * WORD_BYTES
        if footprint > DEFAULT_GUEST_BUDGET_BYTES:
            raise HermesMthToolError("plan exceeds the existing MTH guest workspace")
        return {"schema": SCHEMA, "tool": "mth.compose",
                "plan": plan.to_dict(),
                "workspace_bytes": footprint,
                "execution_modes": sorted({_dispatch_mode(k) for k in plan.kernel_ids}),
                "execution_available_here": False,
                "next_stage": "admission -> native NMP lease -> guest execution -> evidence"}

__all__ = ("HermesMthTools", "HermesMthToolError", "SCHEMA")
