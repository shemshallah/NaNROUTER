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
    effective_words,
    from_bytes,
    from_words,
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
        self.assertFalse(DEFAULT_BUDGET.glt_enforced)

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


if __name__ == "__main__":
    unittest.main()
