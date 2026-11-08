from __future__ import annotations

import json
import math
import unittest

from runner_riddle.capacity_snr import (
    CAPACITY_SNR_SCHEMA,
    CONDITION_COUPLED,
    CONDITION_MATCHED_BASELINE,
    CONDITION_MATCHED_VARIANCE_NOISE,
    CONDITION_RANDOM_COUPLING,
    CONDITION_SHUFFLED_MEMORY,
    CONDITION_ZERO_COUPLING,
    CONDITIONS,
    CONTROL_CONDITIONS,
    SNR_DEFINITION,
    CapacitySNRError,
    CapacitySNRHarness,
    CapacitySNRSpec,
    SNRPoint,
    SNRSweep,
    SeedSet,
    SyntheticFrozenModelStub,
    SyntheticStubConfig,
    run_capacity_snr,
)


def gate_check(report: dict, name: str) -> dict:
    for check in report["gate"]["checks"]:
        if check["name"] == name:
            return check
    raise AssertionError(f"missing gate check {name!r}")


class CapacitySNRConfigTests(unittest.TestCase):
    def test_snr_sweep_has_explicit_power_definition(self):
        point = SNRPoint(-10.0)
        self.assertEqual(point.definition, SNR_DEFINITION)
        self.assertAlmostEqual(point.noise_power(1.0), 10.0)
        self.assertAlmostEqual(point.noise_sigma(1.0), math.sqrt(10.0))
        self.assertAlmostEqual(SNRPoint(0.0).noise_power(2.0), 2.0)

        sweep = SNRSweep(
            points=(SNRPoint(-12.0), SNRPoint(-4.0)),
            signal_power=2.0,
            declared_range_db=(-20.0, 0.0),
        )
        self.assertAlmostEqual(sweep.noise_power(-10.0), 20.0)
        self.assertTrue(sweep.contains(-8.0))
        self.assertFalse(sweep.contains(1.0))
        evidence = sweep.to_dict()
        self.assertEqual(evidence["definition"], SNR_DEFINITION)
        self.assertEqual(evidence["snr_db_values"], [-12.0, -4.0])
        self.assertEqual(evidence["declared_range_db"], [-20.0, 0.0])

    def test_snr_sweep_rejects_duplicate_and_bad_range(self):
        with self.assertRaises(CapacitySNRError):
            SNRSweep(points=(SNRPoint(-8.0), SNRPoint(-8.0)))
        with self.assertRaises(CapacitySNRError):
            SNRSweep(
                points=(SNRPoint(-8.0),),
                declared_range_db=(0.0, -10.0),
            )
        with self.assertRaises(CapacitySNRError):
            SNRSweep(points=())

    def test_seed_and_spec_validation(self):
        with self.assertRaises(CapacitySNRError):
            SeedSet(seeds=())
        with self.assertRaises(CapacitySNRError):
            SeedSet(seeds=(0, 0))
        with self.assertRaises(CapacitySNRError):
            SeedSet(seeds=(0, 1), min_seeds=1)
        with self.assertRaises(CapacitySNRError):
            CapacitySNRSpec(item_counts=(8, 8))
        with self.assertRaises(CapacitySNRError):
            CapacitySNRSpec(dimension=1)
        with self.assertRaises(CapacitySNRError):
            CapacitySNRSpec(confidence=1.0)
        with self.assertRaises(CapacitySNRError):
            CapacitySNRSpec(min_snr_points=1)

        spec = CapacitySNRSpec()
        protocol = spec.to_dict()
        self.assertEqual(protocol["definitions"]["snr"], SNR_DEFINITION)
        self.assertEqual(protocol["seeds"]["min_seeds"], 2)
        self.assertIn("heldout_accuracy", protocol["definitions"])
        self.assertIn("steps", protocol["definitions"])
        self.assertIn("memory", protocol["definitions"])

    def test_stub_is_deterministic_and_marked_synthetic(self):
        stub = SyntheticFrozenModelStub()
        point = SNRPoint(-10.0)
        first = stub.run_trial(
            condition=CONDITION_COUPLED,
            snr_point=point,
            signal_power=1.0,
            item_count=12,
            dimension=24,
            seed=3,
            repeat=0,
            null_query_count=4,
            match_similarity_threshold=0.9,
        )
        second = stub.run_trial(
            condition=CONDITION_COUPLED,
            snr_point=point,
            signal_power=1.0,
            item_count=12,
            dimension=24,
            seed=3,
            repeat=0,
            null_query_count=4,
            match_similarity_threshold=0.9,
        )
        self.assertEqual(first, second)
        self.assertTrue(stub.synthetic_only)
        self.assertFalse(stub.real_model)
        self.assertFalse(stub.real_data)
        self.assertTrue(stub.describe()["synthetic_only"])
        self.assertFalse(stub.describe()["real_model"])

        baseline = stub.run_trial(
            condition=CONDITION_MATCHED_BASELINE,
            snr_point=point,
            signal_power=1.0,
            item_count=12,
            dimension=24,
            seed=3,
            repeat=0,
            null_query_count=4,
            match_similarity_threshold=0.9,
        )
        noise_control = stub.run_trial(
            condition=CONDITION_MATCHED_VARIANCE_NOISE,
            snr_point=point,
            signal_power=1.0,
            item_count=12,
            dimension=24,
            seed=3,
            repeat=0,
            null_query_count=4,
            match_similarity_threshold=0.9,
        )
        self.assertEqual(
            baseline.effective_noise_sigma,
            noise_control.effective_noise_sigma,
        )
        self.assertEqual(noise_control.noise_model, "synthetic-ar1-colored-component-variance.v1")


class CapacitySNRRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = CapacitySNRHarness().run()

    def test_deterministic_rerun_is_identical(self):
        first = self.report
        second = run_capacity_snr()
        self.assertEqual(
            json.dumps(first, sort_keys=True),
            json.dumps(second, sort_keys=True),
        )
        self.assertEqual(first["report_digest"], second["report_digest"])
        self.assertEqual(first["report_digest"], CapacitySNRHarness().run()["report_digest"])

        other = CapacitySNRHarness(
            CapacitySNRSpec(seeds=SeedSet(seeds=(0, 7)))
        ).run()
        self.assertNotEqual(first["report_digest"], other["report_digest"])

    def test_synthetic_gate_pass_records_all_six_r5_checks(self):
        report = self.report
        self.assertEqual(report["schema"], CAPACITY_SNR_SCHEMA)
        self.assertEqual(report["status"], "synthetic_supported")
        self.assertEqual(report["gate_status"], "supported")
        self.assertTrue(report["passed"])
        self.assertTrue(report["synthetic_supported"])
        checks = report["gate"]["checks"]
        self.assertEqual(len(checks), 6)
        expected_names = [
            "r5_gate_1_candidate_beats_matched_baseline",
            "r5_gate_2_controls_do_not_reproduce_gain",
            "r5_gate_3_gain_persists_across_seeds_and_snr",
            "r5_gate_4_uncertainty_interval_excludes_zero",
            "r5_gate_5_active_memory_and_steps_reported",
            "r5_gate_6_no_extrapolation_beyond_noise_model",
        ]
        self.assertEqual([check["name"] for check in checks], expected_names)
        for check in checks:
            self.assertEqual(check["status"], "pass", check)
        self.assertEqual(report["gate"]["reasons"], [])
        self.assertEqual(
            set(report["metrics"]["conditions"]), set(CONDITIONS)
        )
        self.assertEqual(len(report["metrics"]["conditions"]), 6)

    def test_metrics_report_accuracy_ci_false_match_steps_and_memory(self):
        report = self.report
        metrics = report["metrics"]
        conditions = metrics["conditions"]
        primary = metrics["deltas"][CONDITION_MATCHED_BASELINE]
        self.assertEqual(primary["status"], "pass")
        self.assertGreater(primary["mean_delta"], 0.0)
        self.assertGreater(primary["ci_low"], 0.0)
        self.assertLessEqual(primary["ci_low"], primary["ci_high"])
        self.assertEqual(primary["n_blocks"], 9)
        self.assertEqual(primary["n_seeds"], 2)
        self.assertEqual(len(primary["per_seed"]), 2)
        self.assertEqual(len(primary["per_snr"]), 3)
        for item in primary["per_seed"]:
            self.assertGreater(item["mean_delta"], 0.0)
        for item in primary["per_snr"]:
            self.assertGreater(item["mean_delta"], 0.0)

        for condition in CONDITIONS:
            condition_metrics = conditions[condition]
            self.assertGreaterEqual(condition_metrics["accuracy"], 0.0)
            self.assertLessEqual(condition_metrics["accuracy"], 1.0)
            self.assertGreaterEqual(
                condition_metrics["false_match_rate"], 0.0
            )
            self.assertLessEqual(condition_metrics["false_match_rate"], 1.0)
            self.assertGreater(condition_metrics["steps"], 0)
            self.assertGreater(condition_metrics["memory_bytes"], 0)
            self.assertEqual(condition_metrics["null_total"], 288)
            self.assertEqual(
                condition_metrics["memory_words"],
                condition_metrics["memory_bytes"] // 4,
            )
        self.assertEqual(
            conditions[CONDITION_COUPLED]["steps"],
            conditions[CONDITION_MATCHED_BASELINE]["steps"],
        )
        self.assertEqual(
            conditions[CONDITION_COUPLED]["memory_bytes"],
            conditions[CONDITION_MATCHED_BASELINE]["memory_bytes"],
        )
        self.assertLessEqual(
            conditions[CONDITION_COUPLED]["false_match_rate"], 0.1
        )
        self.assertEqual(
            metrics["capacity_at_snr"]["threshold"],
            CapacitySNRSpec().capacity_threshold,
        )
        candidate_capacity = metrics["capacity_at_snr"]["candidate"]
        baseline_capacity = metrics["capacity_at_snr"]["matched_baseline"]
        for snr_key in baseline_capacity:
            self.assertGreaterEqual(
                candidate_capacity[snr_key], baseline_capacity[snr_key]
            )
        self.assertGreater(
            sum(candidate_capacity.values()),
            sum(baseline_capacity.values()),
        )
        self.assertIn("steps", metrics["definitions"])
        self.assertIn("memory", metrics["definitions"])
        json.dumps(report)

    def test_controls_do_not_reproduce_candidate_gain(self):
        report = self.report
        candidate_accuracy = report["metrics"]["conditions"][
            CONDITION_COUPLED
        ]["accuracy"]
        for control in CONTROL_CONDITIONS:
            control_accuracy = report["metrics"]["conditions"][control][
                "accuracy"
            ]
            self.assertGreater(candidate_accuracy, control_accuracy)
            delta = report["metrics"]["deltas"][control]
            self.assertEqual(delta["status"], "pass", delta)
            self.assertGreater(delta["mean_delta"], 0.0)
            self.assertGreater(delta["ci_low"], 0.0)
        shuffled = report["metrics"]["deltas"][CONDITION_SHUFFLED_MEMORY]
        self.assertGreater(shuffled["mean_delta"], 0.5)

    def test_zero_coupling_reproducing_gain_fails_gate_two(self):
        report = CapacitySNRHarness(
            stub_config=SyntheticStubConfig(zero_coupling_gain_db=6.0)
        ).run()
        self.assertEqual(report["status"], "rejected")
        self.assertEqual(report["gate_status"], "rejected")
        self.assertFalse(report["passed"])
        self.assertEqual(
            report["metrics"]["deltas"][CONDITION_ZERO_COUPLING][
                "mean_delta"
            ],
            0.0,
        )
        check = gate_check(
            report, "r5_gate_2_controls_do_not_reproduce_gain"
        )
        self.assertEqual(check["status"], "fail")
        self.assertIn(
            "zero_coupling", " ".join(report["gate"]["reasons"])
        )

    def test_shuffled_memory_identical_to_candidate_fails_gate_two(self):
        report = CapacitySNRHarness(
            stub_config=SyntheticStubConfig(shuffled_shift=0)
        ).run()
        self.assertEqual(report["status"], "rejected")
        self.assertFalse(report["passed"])
        shuffled = report["metrics"]["deltas"][CONDITION_SHUFFLED_MEMORY]
        self.assertEqual(shuffled["mean_delta"], 0.0)
        self.assertEqual(shuffled["status"], "fail")
        check = gate_check(
            report, "r5_gate_2_controls_do_not_reproduce_gain"
        )
        self.assertEqual(check["status"], "fail")

    def test_insufficient_seeds_is_inconclusive(self):
        report = CapacitySNRHarness(
            CapacitySNRSpec(seeds=SeedSet(seeds=(0,), min_seeds=2))
        ).run()
        self.assertEqual(report["status"], "inconclusive")
        self.assertEqual(report["gate_status"], "inconclusive")
        self.assertFalse(report["passed"])
        check = gate_check(
            report, "r5_gate_3_gain_persists_across_seeds_and_snr"
        )
        self.assertEqual(check["status"], "inconclusive")
        self.assertIn("min_seeds", check["detail"])
        self.assertEqual(len(report["protocol"]["seeds"]["seeds"]), 1)

    def test_underpowered_item_sweep_and_single_snr_are_inconclusive(self):
        underpowered = CapacitySNRHarness(
            CapacitySNRSpec(item_counts=(2,), min_items=8)
        ).run()
        self.assertEqual(underpowered["status"], "inconclusive")
        self.assertFalse(underpowered["passed"])
        check = gate_check(
            underpowered, "r5_gate_1_candidate_beats_matched_baseline"
        )
        self.assertEqual(check["status"], "inconclusive")
        self.assertIn("underpowered", check["detail"])

        single_snr = CapacitySNRHarness(
            CapacitySNRSpec(
                sweep=SNRSweep(points=(SNRPoint(-8.0),)),
                min_snr_points=2,
            )
        ).run()
        self.assertEqual(single_snr["status"], "inconclusive")
        check = gate_check(
            single_snr, "r5_gate_3_gain_persists_across_seeds_and_snr"
        )
        self.assertEqual(check["status"], "inconclusive")
        self.assertIn("min_snr_points", check["detail"])

    def test_snr_outside_declared_noise_model_fails_gate_six(self):
        report = CapacitySNRHarness(
            CapacitySNRSpec(
                sweep=SNRSweep(
                    points=(SNRPoint(-12.0), SNRPoint(0.0)),
                    declared_range_db=(-12.0, -8.0),
                )
            )
        ).run()
        self.assertEqual(report["status"], "rejected")
        self.assertFalse(report["passed"])
        check = gate_check(
            report, "r5_gate_6_no_extrapolation_beyond_noise_model"
        )
        self.assertEqual(check["status"], "fail")
        self.assertEqual(
            report["noise_model"]["outside_declared_range_db"], [0.0]
        )
        self.assertFalse(report["noise_model"]["extrapolation"])
        self.assertFalse(report["noise_model"]["extrapolation_allowed"])

    def test_no_real_capacity_claim_or_promotion_field(self):
        report = self.report
        self.assertTrue(report["synthetic_only"])
        self.assertFalse(report["real_model"])
        self.assertFalse(report["real_data"])
        self.assertFalse(report["real_capacity_supported"])
        self.assertFalse(report["capacity_claim"])
        self.assertFalse(report["promotable_as_real_capacity_result"])
        self.assertFalse(report["claim"]["real_capacity_claim"])
        self.assertFalse(
            report["claim"]["promotable_as_real_capacity_result"]
        )
        self.assertFalse(report["promotion"]["allowed"])
        self.assertEqual(
            report["promotion"]["status"], "blocked_synthetic_only"
        )
        self.assertIn(
            "cannot be promoted", report["promotion"]["reason"]
        )
        self.assertTrue(report["gate"]["synthetic_only"])
        self.assertFalse(report["gate"]["real_capacity_claim"])
        self.assertFalse(report["model"]["real_model"])
        self.assertFalse(report["model"]["real_data"])
        self.assertFalse(report["dataset"]["real_data"])


if __name__ == "__main__":
    unittest.main()
