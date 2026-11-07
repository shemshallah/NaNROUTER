"""Control-plane runtime facade for the GAME_PLAN_:: vertical slice.

This module composes the semantic function registry, ``::`` linker, validity
engine, math store, and (optionally) ``MthSystem``.  It does not execute a
native kernel, perform host mathematics, or write canonical pages.  The host
compiles a selected candidate into an ``MthPlan`` and submits it through the
existing single-active runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Iterable, Mapping

from .math_objects import MathAdmission, MathCandidate, MathFunction, MathLeaf
from .math_registry import MathFunctionRegistry, MathRegistryError
from .math_store import MathStore, MathStoreError
from . import nmp
from .math_validity import (
    VALID,
    AdmissionRejected,
    MathSnapshot,
    MathValidityEngine,
)
from .mth_registry import MthPlan, MthPlanStep, MthRegistry
from .mth_system import MthSystem, MthSystemError


class MathRuntimeError(ValueError):
    """Control-plane composition or submission failure."""


class MathRuntimeConfigError(MathRuntimeError):
    pass


class MathRuntimePlanError(MathRuntimeError):
    pass


@dataclass(frozen=True)
class CompiledMathPlan:
    candidate: MathCandidate
    function: MathFunction
    admission: MathAdmission
    plan: MthPlan
    workspace_words: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate.candidate_id,
            "function_id": self.function.function_id,
            "admission_id": self.admission.admission_id,
            "verdict": self.admission.verdict,
            "plan": self.plan.to_dict(),
            "workspace_words": self.workspace_words,
        }


class MathRuntime:
    """Compose math records/authority with the existing MTH runtime facade."""

    def __init__(
        self,
        functions: MathFunctionRegistry,
        *,
        store: MathStore | None = None,
        system: MthSystem | None = None,
        linker: Any = None,
        validity: MathValidityEngine | None = None,
        leaves: Mapping[str, MathLeaf] | None = None,
    ) -> None:
        if not isinstance(functions, MathFunctionRegistry):
            raise MathRuntimeConfigError("functions must be a MathFunctionRegistry")
        if store is not None and not isinstance(store, MathStore):
            raise MathRuntimeConfigError("store must be a MathStore")
        if system is not None and not isinstance(system, MthSystem):
            raise MathRuntimeConfigError("system must be an MthSystem")
        self.functions = functions
        self.store = store
        self.system = system
        self.linker = linker
        self.validity = validity or MathValidityEngine()
        self._leaves = dict(leaves or {})

    # -- leaves --------------------------------------------------------------

    def leaf(self, leaf_id: str, version: int | None = None) -> MathLeaf:
        if self.store is not None:
            try:
                return self.store.get_leaf(leaf_id, version=version)
            except (MathStoreError, KeyError) as exc:
                raise MathRuntimeError(f"cannot resolve leaf {leaf_id!r}") from exc
        leaf = self._leaves.get(leaf_id)
        if leaf is None:
            raise MathRuntimeError(f"cannot resolve leaf {leaf_id!r}")
        if version is not None and leaf.version != version:
            raise MathRuntimeError(
                f"leaf {leaf_id!r} version {version} is not available"
            )
        return leaf

    def add_leaf(self, leaf: MathLeaf) -> MathLeaf:
        if self.store is not None:
            return self.store.put_leaf(leaf)
        existing = self._leaves.get(leaf.leaf_id)
        if existing is not None and existing.digest() != leaf.digest():
            raise MathRuntimeError(f"leaf {leaf.leaf_id!r} already exists")
        self._leaves[leaf.leaf_id] = leaf
        return leaf

    def _leaf_pins(self, candidate: MathCandidate) -> tuple[dict[str, Any], ...]:
        pins = []
        for item in candidate.inputs:
            leaf_id = item.get("leaf_id")
            version = item.get("version")
            if not isinstance(leaf_id, str) or not isinstance(version, int):
                raise MathRuntimeError("candidate input is missing leaf_id/version")
            leaf = self.leaf(leaf_id, version)
            pin = {
                "leaf_id": leaf_id,
                "version": leaf.version,
                "content_digest": leaf.content_digest,
                "kind": leaf.kind,
                "type": dict(leaf.type),
                "status": leaf.status,
                "metadata": dict(leaf.metadata),
            }
            if leaf.content_digest is not None:
                pin["content_digest"] = leaf.content_digest
            pins.append(pin)
        return tuple(pins)

    def snapshot_for(self, candidate: MathCandidate,
                     *, snapshot_id: str | None = None) -> MathSnapshot:
        function = self.functions.require(candidate.function_id)
        sid = snapshot_id or candidate.snapshot_id
        if not sid:
            sid = "snp:" + hashlib.sha256(
                (candidate.candidate_id + function.digest()).encode("utf-8")
            ).hexdigest()
        return MathSnapshot(
            snapshot_id=sid,
            functions=(function,),
            leaf_pins=self._leaf_pins(candidate),
            capabilities=(),
        )

    # -- linker / validity ---------------------------------------------------

    def propose(self, refs: Iterable[Any], **kwargs: Any) -> Any:
        if self.linker is None:
            from .math_linker import propose
            linker = propose
        else:
            linker = getattr(self.linker, "propose", self.linker)
        raw_refs = list(refs)
        leaves = None
        if all(isinstance(ref, str) for ref in raw_refs):
            leaf_map = {}
            for ref in raw_refs:
                leaf_id = ref.split("@v", 1)[0]
                leaf = self.leaf(leaf_id)
                leaf_map[leaf.leaf_id] = leaf
            leaves = leaf_map
        return linker(
            raw_refs,
            registry=self.functions.functions,
            leaves=leaves,
            **kwargs,
        )

    def preflight(self, candidate: MathCandidate,
                  *, snapshot: MathSnapshot | None = None) -> MathAdmission:
        function = self.functions.require(candidate.function_id)
        snap = snapshot or self.snapshot_for(candidate)
        admission = self.validity.preflight(candidate, snap, function)
        if not isinstance(admission, MathAdmission):
            raise MathRuntimeError("validity engine returned no typed admission")
        return admission

    def compile(self, candidate: MathCandidate, admission: MathAdmission) -> CompiledMathPlan:
        if admission.verdict != VALID:
            raise MathRuntimePlanError(
                f"candidate admission is {admission.verdict}, not VALID"
            )
        function = self.functions.require(candidate.function_id)
        implementations = [
            item for item in function.implementations
            if item.get("kernel_id")
        ]
        if not implementations:
            raise MathRuntimePlanError(
                f"function {function.function_id!r} has no native implementation"
            )
        implementation = implementations[0]
        kernel_id = implementation["kernel_id"]
        try:
            descriptor = self.functions.implementation_registry.require(kernel_id)
        except MthRegistryError as exc:
            raise MathRuntimePlanError(
                f"implementation kernel {kernel_id!r} is unavailable"
            ) from exc
        steps = (
            MthPlanStep(
                name="n0",
                kernel_id=kernel_id,
                inputs=tuple(
                    f"math[{item.get('kind', 'value')}].{item.get('leaf_id', index)}"
                    for index, item in enumerate(candidate.inputs)
                ),
                outputs=tuple(
                    f"math[{item.get('kind', 'value')}].{item.get('name', index)}"
                    for index, item in enumerate(candidate.outputs)
                ),
            ),
        )
        plan = MthPlan(
            plan_id="math_" + candidate.candidate_id.split(":", 1)[-1][:64],
            steps=steps,
            workspace_words=descriptor.workspace_words,
            deterministic=True,
        )
        try:
            self.functions.implementation_registry.validate_plan(plan)
        except MthRegistryError as exc:
            raise MathRuntimePlanError("compiled math plan is invalid") from exc
        return CompiledMathPlan(
            candidate=candidate,
            function=function,
            admission=admission,
            plan=plan,
            workspace_words=descriptor.workspace_words,
        )

    def prepare_packet(
        self,
        compiled: CompiledMathPlan,
        *,
        lane_id: int = 0,
        capability_set: Any = (),
        capability_epoch: int = 1,
        ring_incarnation: str | None = None,
        ring_epoch: int | None = None,
        guest_words: int | None = None,
        ruleset_id: str = "",
        ruleset_version: int = 1,
        request_id: str | None = None,
    ) -> nmp.NmpPacket:
        """Create an NMP packet bound to the compiled admission.

        The packet is evidence/authorization, not an execution.  A caller must
        pass it through ``nmp.execution_gate`` and then the MthSystem lease.
        """
        return nmp.prepare(
            compiled.candidate,
            compiled.admission,
            snapshot_id=compiled.admission.snapshot_id,
            admission=compiled.admission,
            lane_id=lane_id,
            capability_set=capability_set,
            capability_epoch=capability_epoch,
            ring_incarnation=ring_incarnation,
            ring_epoch=ring_epoch,
            guest_words=guest_words,
            ruleset_id=ruleset_id,
            ruleset_version=ruleset_version,
            request_id=request_id,
            plan_digest=None,
        )

    def submit(
        self,
        compiled: CompiledMathPlan,
        submit_token: str,
        job_id: str,
        universe_id: str,
        generation: int,
        *,
        payload: Any = None,
        now_tick: int = 0,
    ) -> dict[str, Any]:
        if self.system is None:
            raise MathRuntimeConfigError("submit requires an MthSystem")
        # The MthPlan v1 record is intentionally frozen and has no admission
        # field; the NMP/runtime bridge binds the admission in its job payload.
        # Validate the typed admission here and pass its digest into the job.
        self.validity.require_admission(compiled.admission)
        operator_digest = compiled.plan.steps[0].kernel_id
        try:
            descriptor = self.functions.implementation_registry.require(operator_digest)
        except MthRegistryError as exc:
            raise MathRuntimePlanError("compiled kernel is unavailable") from exc
        bound_payload = {} if payload is None else dict(payload)
        bound_payload.setdefault("math_admission", compiled.admission.to_dict())
        bound_payload.setdefault("math_snapshot_id", compiled.admission.snapshot_id)
        return self.system.submit_plan(
            compiled.plan,
            submit_token,
            job_id,
            universe_id,
            descriptor.source_digest,
            generation,
            payload=bound_payload,
            now_tick=now_tick,
            operator_id=descriptor.kernel_id,
            precision=descriptor.precision,
            workspace=compiled.workspace_words,
        )


__all__ = [
    "CompiledMathPlan",
    "MathRuntime",
    "MathRuntimeConfigError",
    "MathRuntimeError",
    "MathRuntimePlanError",
]
