#!/usr/bin/env python3
"""Host input-validation tests, no learning/model arithmetic."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from apply_native_trihead_journal_transport import parse_native_log

GOOD = (
    b"MTH_META_ACCEPTED_HEX "
    b"00000000 00000001 00000003 00000002 000413EC 3F500000\n"
    b"MTH TRIHEAD META FEEDBACK PASS\n"
)


class NativeJournalIntake(unittest.TestCase):
    def test_exact_guest_record(self):
        self.assertEqual(
            parse_native_log(GOOD),
            (0, 1, 3, 2, 267244, 0x3F500000),
        )

    def test_reject_unadmitted_or_malformed(self):
        bad = [
            GOOD.replace(b"000413EC", b"000413E8"),  # opposite mirror lane
            GOOD.replace(b"00000000", b"000000FF", 1),  # void proposer
            GOOD.replace(b"00000001", b"000000FF", 1),  # void first axis
            GOOD.replace(b"3F500000", b"7F800000"),  # Inf weight
            GOOD.replace(b"3F500000", b"7FC00000"),  # NaN weight
            GOOD.replace(b" PASS", b" FAIL"),
            GOOD + GOOD.splitlines()[0] + b"\n",  # duplicate journal
            b"MTH TRIHEAD META FEEDBACK PASS\n",  # absent journal
        ]
        for record in bad:
            with self.subTest(data=record[:90]):
                with self.assertRaises(ValueError):
                    parse_native_log(record)


if __name__ == "__main__":
    unittest.main()
