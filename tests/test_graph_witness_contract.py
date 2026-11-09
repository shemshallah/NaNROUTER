"""Contract regression tests for the graph claim-probe / path-witness split.

The catalogued numerical kernel ``mth.graph.claim_probe.u32`` and the
standalone excluded guest ``mth/nan16/mth_graph_path_witness.nas`` must remain
distinct: only the claim probe belongs to the numerical MTH manifest, and
neither primitive carries proof, authorization, or promotion authority.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "spec" / "graph-witness-contract.v1.json"
MANIFEST_PATH = ROOT / "spec" / "wave-capabilities.json"
BOUNDARY_PATH = ROOT / "spec" / "nan-native-boundary.json"

CLAIM_PROBE_ID = "mth.graph.claim_probe.u32"
CLAIM_PROBE_SOURCE = "mth/nan16/mth_graph_claim_probe.nas"
CLAIM_PROBE_FIXTURE = "mth/tests/mth_graph_claim_probe_test.nas"
CLAIM_PROBE_WORKFLOW = ".github/workflows/native-graph-claim-probe.yml"
PATH_WITNESS_SOURCE = "mth/nan16/mth_graph_path_witness.nas"
PATH_WITNESS_FIXTURE = "mth/tests/mth_graph_path_witness_test.nas"
PATH_WITNESS_WORKFLOW = ".github/workflows/native-graph-path-witness.yml"


class GraphWitnessContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.boundary = json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))
        cls.claim_probe = cls.contract["participants"]["claim_probe"]
        cls.path_witness = cls.contract["participants"]["path_witness"]

    def test_contract_loads_and_declares_the_distinction(self):
        contract = self.contract
        self.assertEqual(contract["schema"], "nanrouter.graph-witness-contract.v1")
        self.assertEqual(contract["version"], 1)
        self.assertEqual(contract["status"], "active")
        self.assertEqual(contract["canonical_language"], "NaN16")
        self.assertEqual(
            contract["numerical_mth_manifest"], "spec/wave-capabilities.json"
        )
        self.assertEqual(contract["native_boundary"], "spec/nan-native-boundary.json")
        self.assertIn("claim_probe", contract["distinction"])
        self.assertIn("path_witness", contract["distinction"])
        self.assertIn("operational_difference", contract["distinction"])

        claim_probe = self.claim_probe
        self.assertEqual(claim_probe["kernel_id"], CLAIM_PROBE_ID)
        self.assertEqual(
            claim_probe["classification"], "catalogued_numerical_mth_kernel"
        )
        self.assertIs(claim_probe["numerical_mth_kernel"], True)
        self.assertIs(claim_probe["catalogued_in_numerical_manifest"], True)
        self.assertIs(claim_probe["excluded_from_numerical_manifest"], False)

        path_witness = self.path_witness
        self.assertIsNone(path_witness["kernel_id"])
        self.assertEqual(
            path_witness["classification"],
            "standalone_excluded_multihop_path_witness",
        )
        self.assertIs(path_witness["numerical_mth_kernel"], False)
        self.assertIs(path_witness["catalogued_in_numerical_manifest"], False)
        self.assertIs(path_witness["excluded_from_numerical_manifest"], True)

    def test_declared_sources_fixtures_workflows_and_docs_exist(self):
        declared = {
            self.contract["numerical_mth_manifest"],
            self.contract["native_boundary"],
            *self.contract["reference_documents"],
            self.claim_probe["source"],
            self.claim_probe["fixture"],
            self.claim_probe["ci_workflow"],
            self.path_witness["source"],
            self.path_witness["fixture"],
            self.path_witness["ci_workflow"],
            self.contract["ci_separation"]["canonical_numerical_ci_workflow"],
        }
        for relative in sorted(declared):
            with self.subTest(path=relative):
                self.assertTrue(
                    (ROOT / relative).is_file(), f"declared artifact is missing: {relative}"
                )

        claim_workflow = (ROOT / CLAIM_PROBE_WORKFLOW).read_text(encoding="utf-8")
        path_workflow = (ROOT / PATH_WITNESS_WORKFLOW).read_text(encoding="utf-8")
        self.assertIn("name: native-graph-claim-probe", claim_workflow)
        self.assertIn(CLAIM_PROBE_FIXTURE, claim_workflow)
        self.assertIn("name: native-graph-path-witness", path_workflow)
        self.assertIn(PATH_WITNESS_FIXTURE, path_workflow)
        self.assertNotEqual(CLAIM_PROBE_WORKFLOW, PATH_WITNESS_WORKFLOW)

    def test_claim_probe_is_included_in_the_numerical_mth_manifest(self):
        matches = [
            kernel
            for kernel in self.manifest["kernels"]
            if kernel.get("kernel_id") == CLAIM_PROBE_ID
        ]
        self.assertEqual(len(matches), 1)
        entry = matches[0]
        self.assertEqual(entry["source"], CLAIM_PROBE_SOURCE)
        self.assertEqual(entry["fixture"], CLAIM_PROBE_FIXTURE)
        self.assertEqual(entry["marker"], self.claim_probe["test_marker"])
        self.assertNotIn(CLAIM_PROBE_SOURCE, self.boundary["excluded_native_sources"])
        runner = (ROOT / "tools" / "run_mth_fixtures.py").read_text(encoding="utf-8")
        self.assertIn(CLAIM_PROBE_FIXTURE, runner)

    def test_path_witness_is_excluded_from_the_numerical_mth_manifest(self):
        kernels = self.manifest["kernels"]
        self.assertFalse(
            any(kernel.get("kernel_id") == self.path_witness["kernel_id"] for kernel in kernels)
        )
        self.assertFalse(
            any(kernel.get("source") == PATH_WITNESS_SOURCE for kernel in kernels)
        )
        self.assertFalse(
            any(kernel.get("fixture") == PATH_WITNESS_FIXTURE for kernel in kernels)
        )
        self.assertFalse(
            any("path_witness" in str(kernel.get("kernel_id", "")) for kernel in kernels)
        )

        excluded = self.boundary["excluded_native_sources"]
        self.assertIn(PATH_WITNESS_SOURCE, excluded)
        self.assertIn("not an authorized numerical MTH kernel", excluded[PATH_WITNESS_SOURCE])
        self.assertEqual(self.path_witness["exclusion_reason"], excluded[PATH_WITNESS_SOURCE])

        runner = (ROOT / "tools" / "run_mth_fixtures.py").read_text(encoding="utf-8")
        self.assertNotIn(PATH_WITNESS_FIXTURE, runner)

    def test_no_proof_authorization_or_merge_promotion_authority_leaks(self):
        authority = self.contract["authority_boundary"]
        self.assertIs(authority["candidate_observation_only"], True)
        denied = {
            "mathematical_proof",
            "logical_entailment",
            "authorization",
            "learning_admission",
            "merge_promotion",
            "native_promotion",
            "nannet_route_commit",
            "mathstore_write",
            "graph_state_write",
            "model_update",
            "wire_format_trust",
        }
        for key in sorted(denied):
            self.assertIn(key, authority)
            self.assertIs(authority[key], False, f"{key} must stay false")
        for key, value in authority.items():
            if key in {"candidate_observation_only", "statement"}:
                continue
            self.assertIs(value, False, f"unexpected authority grant: {key}")

        for name, participant in (
            ("claim_probe", self.claim_probe),
            ("path_witness", self.path_witness),
        ):
            with self.subTest(participant=name):
                self.assertEqual(participant["authority_granted"], [])
                self.assertEqual(participant["observation_promotion"], "none")

    def test_shared_ranges_relations_and_masks_are_bounded(self):
        shared = self.contract["shared_constants"]
        cell_range = shared["canonical_cell_range"]
        self.assertEqual(cell_range["min"], 0)
        self.assertEqual(cell_range["max"], 32895)
        self.assertEqual(cell_range["head_range"], {"min": 0, "max": 255})
        self.assertEqual(cell_range["mirror_pair_range"], {"min": 256, "max": 32895})
        self.assertEqual(cell_range["out_of_range"], "reject")
        self.assertEqual(shared["layer_range"], {
            "min": 0,
            "max": 9,
            "out_of_range": "reject",
        })

        codes = shared["relation_codes"]
        self.assertEqual(codes["1"], "supports")
        self.assertEqual(codes["2"], "refutes")
        self.assertEqual(codes["accepted"], [1, 2])
        self.assertEqual(codes["other"], "reject")

        self.assertEqual(set(shared["relation_masks"]), {"0", "1", "2", "3"})
        self.assertEqual(self.claim_probe["output_semantics"]["mask_domain"], [0, 1, 2, 3])
        self.assertEqual(self.path_witness["output_semantics"]["mask_domain"], [1, 2, 3])
        self.assertIn("rejected", self.path_witness["output_semantics"]["zero_mask"])

        claim_inputs = self.claim_probe["allowed_inputs"]
        claim_records = claim_inputs["records"]
        self.assertEqual(claim_records["layout"], ["src", "dst", "layer", "relation"])
        self.assertEqual(claim_records["words_per_record"], 4)
        self.assertEqual(claim_records["count_min"], 0)
        self.assertEqual(claim_records["count_max"], 1024)
        claim_query = claim_inputs["query"]
        self.assertEqual(claim_query["src_range"], {"min": 0, "max": 32895})
        self.assertEqual(claim_query["dst_range"], {"min": 0, "max": 32895})
        self.assertEqual(claim_query["layer_range"], {"min": 0, "max": 9})
        self.assertEqual(claim_query["match"], "exact directed (src,dst,layer)")

        path_inputs = self.path_witness["allowed_inputs"]
        path_records = path_inputs["records"]
        self.assertEqual(path_records["layout"], ["src", "dst", "layer", "relation"])
        self.assertEqual(path_records["words_per_record"], 4)
        self.assertEqual(path_records["count_min"], 0)
        self.assertEqual(path_records["count_max"], 1024)
        witness = path_inputs["witness"]
        self.assertEqual(witness["layout"], ["src", "dst", "layer"])
        self.assertEqual(witness["words_per_hop"], 3)
        self.assertEqual(witness["hop_count_min"], 1)
        self.assertEqual(witness["hop_count_max"], 8)
        self.assertEqual(witness["src_range"], {"min": 0, "max": 32895})
        self.assertEqual(witness["dst_range"], {"min": 0, "max": 32895})
        self.assertEqual(witness["layer_range"], {"min": 0, "max": 9})
        self.assertIs(witness["directed"], True)
        self.assertIs(witness["must_chain"], True)
        self.assertIs(witness["each_hop_must_have_active_candidate"], True)
        self.assertIs(witness["caller_proposed"], True)

    def test_reject_atomicity_is_declared_for_both_primitives(self):
        atomicity = self.contract["reject_atomicity"]
        for key in (
            "validate_entire_record_batch_before_any_output",
            "validate_unrelated_records",
            "validate_complete_witness_before_any_output",
            "all_hops_must_be_found_before_output_commit",
            "output_untouched_on_reject",
            "path_witness_words_beyond_hop_count_untouched_on_success",
        ):
            with self.subTest(invariant=key):
                self.assertIs(atomicity[key], True)
        self.assertIs(atomicity["partial_output_on_reject"], False)
        self.assertIs(atomicity["input_buffers_mutated"], False)
        self.assertIs(atomicity["graph_or_model_state_mutated"], False)
        self.assertEqual(
            atomicity["claim_probe_output_words"],
            self.claim_probe["allowed_inputs"]["output"]["words"],
        )
        self.assertEqual(
            atomicity["path_witness_output_words"],
            self.path_witness["allowed_inputs"]["output"]["words"],
        )

    def test_authenticated_graph_snapshot_is_required_before_use(self):
        preconditions = self.contract["snapshot_preconditions"]
        for key in (
            "authenticated_graph_snapshot_required_before_use",
            "snapshot_must_be_complete_and_immutable",
            "snapshot_must_come_from_independently_verified_nanrouter_graph_pages",
            "hermes_binding_required",
            "bind_to_resident_chart_and_revision_history_commitment",
            "caller_must_bind_input_digest",
            "caller_must_bind_chart_generation",
            "caller_must_bind_rule_epoch",
            "mixed_chart_generations_must_be_rejected",
            "incomplete_history_must_be_rejected",
            "records_must_be_active_candidates_only",
        ):
            with self.subTest(precondition=key):
                self.assertIs(preconditions[key], True)
        self.assertIs(preconditions["wire_format_has_cryptographic_binding"], False)
        checks = " ".join(preconditions["external_checks_required"]).lower()
        for expected in (
            "sha-256",
            "mathleaf",
            "ed25519",
            "acl",
            "nonce",
            "native admission receipt",
        ):
            self.assertIn(expected, checks)

    def test_path_witness_ci_is_separate_from_the_numerical_manifest_ci(self):
        separation = self.contract["ci_separation"]
        self.assertIs(separation["separate_ci_workflows"], True)
        self.assertEqual(separation["claim_probe_workflow"], CLAIM_PROBE_WORKFLOW)
        self.assertEqual(separation["path_witness_workflow"], PATH_WITNESS_WORKFLOW)
        self.assertNotEqual(
            separation["claim_probe_workflow"], separation["path_witness_workflow"]
        )
        self.assertIs(separation["path_witness_workflow_is_independent"], True)
        self.assertIs(separation["path_witness_source_in_numerical_manifest"], False)
        self.assertIs(separation["path_witness_fixture_in_numerical_manifest"], False)
        self.assertIs(separation["path_witness_fixture_in_canonical_runner"], False)

        declared_workflows = set(self.boundary["ci_workflows"])
        self.assertIn(CLAIM_PROBE_WORKFLOW, declared_workflows)
        self.assertIn(PATH_WITNESS_WORKFLOW, declared_workflows)

        path_workflow = (ROOT / PATH_WITNESS_WORKFLOW).read_text(encoding="utf-8")
        self.assertNotIn("run_mth_fixtures", path_workflow)


if __name__ == "__main__":
    unittest.main()
