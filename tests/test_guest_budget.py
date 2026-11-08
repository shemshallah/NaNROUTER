from __future__ import annotations

import unittest

from runner_riddle.budget import (
    DEFAULT_BUDGET,
    DEFAULT_GUEST_BUDGET_BYTES,
    DEFAULT_GUEST_BUDGET_PAGES,
    DEFAULT_GUEST_BUDGET_WORDS,
    LEGACY_1MIB,
    LEGACY_GUEST_BUDGET_BYTES,
    PAGE_BYTES,
    WORD_BYTES,
    effective_words,
    from_bytes,
    from_words,
)
from runner_riddle.live_preflight import (
    MAX_GUEST_BUDGET_BYTES,
    MIN_GUEST_BUDGET_BYTES,
    preflight_report,
)
from runner_riddle.point0_bridge import MAX_FRAME_WORDS, MAX_PAYLOAD_BYTES


class GuestBudgetTests(unittest.TestCase):
    def test_standard_profile_is_two_mib(self):
        self.assertEqual(DEFAULT_GUEST_BUDGET_BYTES, 2 * 1024 * 1024)
        self.assertEqual(DEFAULT_GUEST_BUDGET_WORDS, 262_144)
        self.assertEqual(DEFAULT_GUEST_BUDGET_PAGES, 64)
        self.assertEqual(DEFAULT_BUDGET.words, 262_144)
        self.assertEqual(DEFAULT_BUDGET.pages, 64)
        self.assertEqual(DEFAULT_BUDGET.slack_words, 0)
        self.assertTrue(DEFAULT_BUDGET.adjustable)
        self.assertFalse(DEFAULT_BUDGET.page_limit_enforced)
        self.assertFalse(DEFAULT_BUDGET.glt_enforced)  # deprecated alias
        self.assertFalse(DEFAULT_BUDGET.to_dict()["page_limit_enforced"])
        self.assertNotIn("glt_enforced", DEFAULT_BUDGET.to_dict())

    def test_legacy_profile_is_one_mib(self):
        self.assertEqual(LEGACY_GUEST_BUDGET_BYTES, 1024 * 1024)
        self.assertEqual(LEGACY_1MIB.words, 131_072)
        self.assertEqual(LEGACY_1MIB.pages, 32)

    def test_custom_words_use_ceiling_and_report_slack(self):
        budget = from_words(200_000)
        self.assertEqual(budget.bytes, 200_000 * 8)
        self.assertEqual(budget.pages, 49)  # ceil(1,600,000 / 32,768)
        self.assertEqual(budget.slack_words, 49 * 4096 - 200_000)
        self.assertGreater(budget.slack_words, 0)

    def test_effective_words_is_bounded_by_profile_and_runner(self):
        self.assertEqual(
            effective_words(requested_words=262_144, profile=DEFAULT_BUDGET),
            262_144,
        )
        self.assertEqual(
            effective_words(requested_words=262_144, profile=LEGACY_1MIB),
            131_072,
        )
        self.assertEqual(
            effective_words(
                requested_words=262_144,
                profile=DEFAULT_BUDGET,
                runner_ceiling_bytes=1024 * 1024,
            ),
            131_072,
        )
        with self.assertRaises(ValueError):
            effective_words(requested_bytes=17)

    def test_point0_frame_matches_two_mib_budget(self):
        self.assertEqual(MAX_FRAME_WORDS, 262_144)
        self.assertEqual(MAX_PAYLOAD_BYTES, 262_144 * 8)
        self.assertEqual(PAGE_BYTES, 32 * 1024)

    def test_budget_source_round_trip(self):
        budget = from_bytes(2 * 1024 * 1024)
        self.assertEqual(budget.to_dict()["words"], 262_144)
        self.assertEqual(budget.to_dict()["pages"], 64)


def _check_by_id(report, check_id):
    matches = [check for check in report["checks"] if check["id"] == check_id]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {check_id!r} check")
    return matches[0]


class LivePreflightGuestBudgetTests(unittest.TestCase):
    def test_live_preflight_accepts_adjustable_guest_profiles(self):
        cases = (
            (1024 * 1024, 131_072, 32),
            (2 * 1024 * 1024, 262_144, 64),
            (4 * 1024 * 1024, 524_288, 128),
        )
        for size, words, pages in cases:
            with self.subTest(bytes=size):
                report = preflight_report({}, guest_budget_bytes=size)
                check = _check_by_id(report, "universe.guest_budget")
                self.assertEqual(check["status"], "pass")
                self.assertEqual(check["evidence"]["value"], size)
                self.assertEqual(check["evidence"]["guest_words"], words)
                self.assertEqual(check["evidence"]["guest_pages"], pages)
                self.assertEqual(check["evidence"]["word_bytes"], WORD_BYTES)
                runtime = report["evidence"]["runtime"]
                self.assertEqual(runtime["guest_budget_bytes"], size)
                self.assertEqual(runtime["guest_words"], words)
                self.assertEqual(runtime["guest_pages"], pages)

    def test_live_preflight_accepts_guest_words_and_reports_slack(self):
        report = preflight_report({}, guest_budget_words=131_073)
        check = _check_by_id(report, "universe.guest_budget")
        self.assertEqual(check["status"], "pass")
        self.assertEqual(check["evidence"]["value"], 131_073 * WORD_BYTES)
        self.assertEqual(check["evidence"]["guest_words"], 131_073)
        self.assertEqual(check["evidence"]["guest_pages"], 33)
        self.assertEqual(check["evidence"]["guest_slack_words"], 4_095)
        self.assertEqual(
            report["evidence"]["runtime"]["guest_budget_bytes"],
            131_073 * WORD_BYTES,
        )

    def test_live_preflight_rejects_explicit_guest_budget_errors(self):
        cases = (
            (
                {"guest_budget_bytes": 512 * 1024},
                "guest_budget_below_legacy_floor",
            ),
            (
                {"guest_budget_bytes": MIN_GUEST_BUDGET_BYTES + 1},
                "invalid_guest_budget",
            ),
            (
                {"guest_budget_bytes": MAX_GUEST_BUDGET_BYTES + WORD_BYTES},
                "guest_budget_exceeds_universe",
            ),
            (
                {
                    "guest_budget_words": 131_072,
                    "guest_budget_bytes": 2 * 1024 * 1024,
                },
                "guest_budget_mismatch",
            ),
            ({}, "guest_budget_required"),
        )
        for kwargs, expected_code in cases:
            with self.subTest(kwargs=kwargs):
                report = preflight_report({}, **kwargs)
                check = _check_by_id(report, "universe.guest_budget")
                self.assertEqual(check["status"], "fail")
                self.assertEqual(check["evidence"]["code"], expected_code)
                # Invalid input must not silently become the reported runtime
                # budget; the report keeps the default 2 MiB effective budget.
                self.assertEqual(
                    report["evidence"]["runtime"]["guest_budget_bytes"],
                    DEFAULT_GUEST_BUDGET_BYTES,
                )

    def test_live_preflight_guest_words_must_be_positive(self):
        report = preflight_report({}, guest_budget_words=0)
        check = _check_by_id(report, "universe.guest_budget")
        self.assertEqual(check["status"], "fail")
        self.assertEqual(check["evidence"]["code"], "invalid_guest_budget")


if __name__ == "__main__":
    unittest.main()
