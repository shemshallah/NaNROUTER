"""Regression: only an exact native dev loss event may alter bank1."""
import pathlib
import sys
import unittest

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/"scripts"))
from apply_native_wholeword_journal_transport import parse_native_wholeword_log

VALID=b"""WHOLEWORD_DEV_NLL_MILLI 857234 857217 1
WHOLEWORD_TEST_NLL_MILLI 772133 772134 0
MTH_WHOLEWORD_ACCEPTED_HEX 00000001 00000013 00000007 00000004 004C23C4 BE000000
MTH ORIGINAL 48M WHOLEWORD NLL FEEDBACK PASS
"""

class NativeWholeWordJournalTests(unittest.TestCase):
    def test_exact_provenance_and_orientation(self):
        self.assertEqual(parse_native_wholeword_log(VALID),
                         (1,19,7,4,0x004C23C4,0xBE000000))
    def test_unsupported_and_untrusted_reject(self):
        tamper=[
            b"00000013 00000007 00000004",
            b"004C23C4",b"BE000000",
        ]
        replacements=[b"00000013 00000004 00000007",
                      b"004C23C0",b"7F800000"]
        for original,bad in zip(tamper,replacements):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                parse_native_wholeword_log(VALID.replace(original,bad))
    def test_failclosed_missing_duplicate_or_wrong_admission(self):
        fixtures=[
            VALID.replace(b" 857217 1",b" 857240 1"),
            VALID.replace(b" 857217 1",b" 857217 0"),
            VALID.replace(b"00000001 ",b"000000FF "),
            VALID.replace(b"PASS",b"FAIL"),
            VALID.replace(b"WHOLEWORD_TEST_NLL_MILLI",b"WHOLEWORD_DEV_NLL_MILLI"),
            VALID+VALID,
            VALID.replace(b"BE000000",b"BE000001"),
        ]
        for f in fixtures:
            with self.subTest(f=f[:65]),self.assertRaises(ValueError):
                parse_native_wholeword_log(f)

if __name__=="__main__":
    unittest.main()
