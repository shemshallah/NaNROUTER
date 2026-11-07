#!/usr/bin/env python3
"""Control-plane math demo: leaf -> :: -> preflight -> execute -> commit.

This tool deliberately does not perform host arithmetic.  The executor callback
returns a deterministic digest for a stand-in native result so the demo can
exercise every control-plane boundary without pretending that Python computed
a dot product.  A production caller supplies the same callback from the native
MTH runner.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from runner_riddle.math_execution import MathExecutionBridge
from runner_riddle.math_objects import MathLeaf, digest_object
from runner_riddle.math_relation import (
    Hypergraph,
    RelationMember,
    RelationRecord,
    RelationSchema,
    RoleSpec,
)
from runner_riddle.math_registry import MathFunctionRegistry
from runner_riddle.math_runtime import MathRuntime
from runner_riddle.math_store import MathStore
from runner_riddle.mth_registry import MthRegistry
from runner_riddle.mth_system import MthSystem
from runner_riddle.wave_ring_scheduler import WaveRingScheduler
from runner_riddle.wave_service import WaveService
from runner_riddle.wave_store import WaveStore

SUBMIT_TOKEN = "submit-token-0000000000000000"
WORKER_TOKEN = "worker-token-1111111111111111"
ADMIN_TOKEN = "admin-token-22222222222222222"


def vector_leaf(index: int, digest_char: str) -> MathLeaf:
    return MathLeaf(
        leaf_id=f"nml:U0:vector:demo-{index}",
        kind="vector",
        type={
            "element": "float32",
            "shape": [256],
            "layout": "row_major",
            "domain": "real",
        },
        content={"digest": digest_char * 64, "word_count": 256},
    )


def run_demo(root: Path | None = None, *, keep: bool = False) -> dict[str, Any]:
    """Run the vertical slice and return a JSON-safe report."""
    if root is None:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
    else:
        temp = None
    try:
        native = MthRegistry.load(REPO / "spec" / "wave-capabilities.json")
        functions = MathFunctionRegistry.load(
            REPO / "spec" / "math-functions.v1.json",
            implementations=native,
        )
        math_store = MathStore(root / "bs0.sqlite3", root / "mc0.sqlite3")
        a = math_store.put_leaf(vector_leaf(1, "a"))
        b = math_store.put_leaf(vector_leaf(2, "b"))

        wave_store = WaveStore(
            root / "wave-bs.sqlite3", root / "wave-mc.sqlite3",
        )
        service = WaveService(
            wave_store, SUBMIT_TOKEN, WORKER_TOKEN, ADMIN_TOKEN,
        )
        scheduler = WaveRingScheduler(cycle_ticks=64, now_tick=0)
        scheduler.start(0)
        system = MthSystem(native, wave_store, service, scheduler)
        runtime = MathRuntime(functions, store=math_store, system=system)
        bridge = MathExecutionBridge(
            runtime,
            system,
            submit_token=SUBMIT_TOKEN,
            worker_token=WORKER_TOKEN,
        )

        proposed = runtime.propose(
            [f"{a.leaf_id}@v1", f"{b.leaf_id}@v1"],
            snapshot_id="snp:" + "d" * 64,
            max_candidates=16,
        )
        candidate = next(
            item for item in proposed.items
            if item.function_id == "math.vector.dot"
        )
        admission = runtime.preflight(candidate)
        if admission.verdict != "VALID":
            raise RuntimeError(f"dot admission is {admission.verdict}")
        compiled = runtime.compile(candidate, admission)

        binding = bridge.ring_binding(now_tick=0)
        descriptor = native.require(compiled.plan.kernel_ids[0])
        wave_store.register_capability(
            kernel_id=descriptor.kernel_id,
            runner_id=binding.active_slot_id or "NANROUTER-0",
            verified_digest=descriptor.source_digest,
            workspace=1,
            precision=descriptor.precision,
            status="native_verified",
        )

        packet = bridge.prepare_packet(compiled)
        submission = bridge.submit(packet, compiled, now_tick=0)
        lease = bridge.lease(submission, now_tick=0)
        if lease is None:
            raise RuntimeError("the queued demo job was not leased")

        # This is an evidence digest, not a computed vector result.  The native
        # executor owns the numeric bytes; this demo owns the state machine.
        result_digest = digest_object({
            "schema": "nanrouter.math-demo-result.v1",
            "candidate_id": candidate.candidate_id,
            "admission_id": admission.admission_id,
            "plan_digest": digest_object(compiled.plan.to_dict()),
            "inputs": [
                {"leaf_id": a.leaf_id, "digest": a.content_digest},
                {"leaf_id": b.leaf_id, "digest": b.content_digest},
            ],
            "note": "control-plane digest; native numeric executor is external",
        })
        output = MathLeaf(
            leaf_id="nml:U0:scalar:demo-dot",
            kind="scalar",
            type={"element": "float32", "shape": [], "domain": "real"},
            content={"digest": result_digest, "word_count": 1},
            parents=(
                {
                    "leaf_id": a.leaf_id,
                    "version": a.version,
                    "content_digest": a.content_digest,
                },
                {
                    "leaf_id": b.leaf_id,
                    "version": b.version,
                    "content_digest": b.content_digest,
                },
            ),
            operation={
                "function_id": candidate.function_id,
                "function_version": candidate.function_version,
                "ruleset_snapshot_id": admission.rule_snapshot_id,
                "candidate_id": candidate.candidate_id,
                "plan_digest": digest_object(compiled.plan.to_dict()),
            },
            provenance={
                "producer": "nanrouter.math-demo.v1",
                "candidate_id": candidate.candidate_id,
                "function_id": candidate.function_id,
                "function_version": candidate.function_version,
                "admission_id": admission.admission_id,
                "preflight_digest": admission.preflight_digest,
                "ruleset_snapshot_id": admission.rule_snapshot_id,
                "packet_id": packet.packet_id,
                "job_id": submission.job_id,
                "kernel_id": descriptor.kernel_id,
                "runner_id": binding.active_slot_id,
                "ring_incarnation": packet.ring_incarnation,
                "ring_epoch": packet.ring_epoch,
                "jahs": packet.jahs,
                "plan_digest": digest_object(compiled.plan.to_dict()),
            },
            metadata={
                "demo": True,
                "numeric_execution": "external",
                "evidence_digest_only": True,
            },
        )
        math_store.put_leaf(output)

        completed = bridge.execute(
            lease,
            lambda: result_digest,
            now_tick=1,
            output_leaf_id=output.leaf_id,
            commit=True,
            provenance={"demo": True},
        )
        feedback_leaf = runtime.leaf(output.leaf_id)
        feedback_mapping = math_store.get_mapping("leaf:" + output.leaf_id)
        relation_schema = RelationSchema(
            schema_id="nanrouter.demo.dot-relation",
            roles=(
                RoleSpec("input", min_count=2, max_count=2, required=True),
                RoleSpec("output", min_count=1, max_count=1, required=True),
            ),
            min_arity=3,
            max_arity=3,
        )
        relation = RelationRecord(
            relation_id="rel:demo:dot",
            schema=relation_schema,
            members=(
                RelationMember(a.leaf_id, a.version, "input"),
                RelationMember(b.leaf_id, b.version, "input"),
                RelationMember(output.leaf_id, output.version, "output"),
            ),
        )
        hypergraph = Hypergraph(
            "hg:demo:dot", relations=(relation,),
        )
        report = {
            "schema": "nanrouter.math-demo-report.v1",
            "ok": completed.state == "COMMITTED",
            "candidate_id": candidate.candidate_id,
            "function_id": candidate.function_id,
            "admission_verdict": admission.verdict,
            "preflight_digest": admission.preflight_digest,
            "kernel_ids": list(compiled.plan.kernel_ids),
            "workspace_words": compiled.workspace_words,
            "packet_id": packet.packet_id,
            "job_id": submission.job_id,
            "job_state": completed.job_state,
            "execution_state": completed.state,
            "committed": completed.committed,
            "result_digest": completed.result_digest,
            "output_leaf_id": output.leaf_id,
            "output_leaf": feedback_leaf.to_dict(),
            "feedback_relation": {
                "relation_id": relation.relation_id,
                "digest": relation.digest(),
                "member_count": len(relation.members),
                "hypergraph_id": hypergraph.hypergraph_id,
                "members": [
                    {"leaf_id": member.leaf_id, "version": member.version,
                     "role": member.role}
                    for member in relation.members
                ],
            },
            "feedback": {
                "leaf_id": feedback_leaf.leaf_id,
                "version": feedback_leaf.version,
                "content_digest": feedback_leaf.content_digest,
                "mapping_id": feedback_mapping["mapping_id"],
                "mapping_version": feedback_mapping["current_version"],
            },
            "note": (
                "control-plane execution only; result_digest is an evidence "
                "digest, not a claimed numeric dot product"
            ),
        }
        return report
    finally:
        if temp is not None:
            if keep:
                # The temporary directory is intentionally retained only when
                # the caller passed an explicit directory; this branch is
                # defensive for future callers.
                pass
            temp.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=None,
        help="directory for SQLite stores (default: a temporary directory)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    args = parser.parse_args(argv)
    report = run_demo(args.root, keep=args.root is not None)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"ok: {report['ok']}")
        print(f"candidate: {report['candidate_id']}")
        print(f"admission: {report['admission_verdict']}")
        print(f"kernel: {', '.join(report['kernel_ids'])}")
        print(f"packet: {report['packet_id']}")
        print(f"job: {report['job_id']} ({report['job_state']})")
        print(f"execution: {report['execution_state']}")
        print(f"output leaf: {report['output_leaf_id']}")
        print(f"feedback digest: {report['feedback']['content_digest']}")
        print(report["note"])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
