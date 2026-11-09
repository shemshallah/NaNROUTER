"""All-manifest Hermes MTH catalog and plan integration tests.

The catalog is required to cover every native manifest kernel, rather than
silently truncating the later spectral/math additions.
"""
import json
import unittest
from pathlib import Path

from runner_riddle.hermes_mth_tools import HermesMthTools, HermesMthToolError
from runner_riddle.mth_registry import MthPlanError, MthRegistryError

ROOT = Path(__file__).resolve().parents[1]


class HermesMthToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tools = HermesMthTools.from_checkout(ROOT)
        cls.manifest = json.loads(
            (ROOT / "spec" / "wave-capabilities.json").read_text()
        )

    def test_all_manifest_functions_discoverable_no_loss(self):
        expected = {k["kernel_id"] for k in self.manifest["kernels"]}
        found = set()
        offset = 0
        while True:
            page = self.tools.invoke("mth.catalog", {"offset": offset, "limit": 13})
            self.assertEqual(page["total"], len(expected))
            found.update(k["kernel_id"] for k in page["kernels"])
            if page["next_offset"] is None:
                break
            self.assertGreater(page["next_offset"], offset)
            offset = page["next_offset"]
        self.assertEqual(found, expected)

    def test_every_native_kernel_can_be_inspected_and_prepared(self):
        for kernel in self.tools.registry.kernels:
            with self.subTest(kernel=kernel.kernel_id):
                desc = self.tools.invoke("mth.inspect", {"kernel_id": kernel.kernel_id})
                self.assertEqual(desc["kernel"]["source_digest"], kernel.source_digest)
                self.assertEqual(desc["kernel"]["fixture_digest"], kernel.fixture_digest)
                args = {"kernel_id": kernel.kernel_id,
                        "inputs": [], "outputs": []}
                if kernel.ci_verified and kernel.status == "native_verified":
                    result = self.tools.invoke("mth.prepare", args)
                    self.assertEqual(result["plan"]["steps"][0]["kernel_id"],
                                     kernel.kernel_id)
                    self.assertFalse(result["execution_available_here"])
                else:
                    with self.assertRaises(HermesMthToolError):
                        self.tools.invoke("mth.prepare", args)

    def test_catalogue_ci_claims_match_local_promotion_state(self):
        kernels = self.tools.registry.kernels
        self.assertEqual(len(kernels), 133)
        self.assertTrue(all(kernel.status == "native_verified" for kernel in kernels))
        self.assertEqual(sum(kernel.ci_verified for kernel in kernels), 131)
        local_only = {
            "mth.definition.slot_io.u32",
            "mth.gauge.triangle_recover.f32",
        }
        self.assertEqual(
            {kernel.kernel_id for kernel in kernels if not kernel.ci_verified},
            local_only,
        )

    def test_all_families_accounted_for(self):
        result = self.tools.invoke("mth.categories")
        self.assertEqual(sum(result["families"].values()), len(self.tools.registry))
        self.assertEqual(sum(result["execution_modes"].values()), len(self.tools.registry))
        self.assertEqual(result["execution_modes"].get("admission_gated_native_abi"), 4)

    def test_head_directed_kernel_and_family_resolution(self):
        family = self.tools.invoke("mth.route", {
            "address": "HW0:23::vector", "head_index": 23})
        self.assertTrue(family["result"]["kernels"])
        self.assertTrue(all(
            k["kernel_id"].startswith("mth.vector.")
            for k in family["result"]["kernels"]))
        kernel = self.tools.invoke("mth.route", {
            "address": "HW0:23::mth.vector.dot256.f32", "head_index": 23})
        self.assertEqual(kernel["result"]["kernel"]["kernel_id"],
                         "mth.vector.dot256.f32")
        with self.assertRaises(HermesMthToolError):
            self.tools.invoke("mth.route", {
                "address": "HW0:24::vector", "head_index": 23})
        with self.assertRaises(HermesMthToolError):
            self.tools.invoke("mth.route", {
                "address": "HW0:255::vector", "head_index": 255})

    def test_bounded_composition_and_native_dispatch_is_not_faked(self):
        result = self.tools.invoke("mth.compose", {"plan": {
            "plan_id": "probe",
            "steps": [{"name": "dot", "kernel_id": "mth.vector.dot256.f32",
                       "inputs": ["f32.a", "f32.b"], "outputs": ["f32.dot"],
                       "depends_on": []}],
        }})
        self.assertFalse(result["execution_available_here"])
        self.assertEqual(result["execution_modes"], ["admission_gated_native_abi"])

    def test_invalid_requests_fail_closed(self):
        invalid = [
            ("mth.catalog", {"offset": -1}),
            ("mth.catalog", {"limit": 1000}),
            ("mth.catalog", {"tags": ["x"] * 9}),
            ("mth.inspect", {"kernel_id": "mth.not.real"}),
            ("mth.prepare", {"kernel_id": "mth.not.real"}),
            ("mth.compose", {"plan": {"steps": []}}),
            ("mth.run", {"kernel_id": "mth.vector.dot256.f32"}),
        ]
        for tool, args in invalid:
            with self.subTest(tool=tool, args=args):
                with self.assertRaises((HermesMthToolError, MthRegistryError, MthPlanError)):
                    self.tools.invoke(tool, args)


if __name__ == "__main__":
    unittest.main()
