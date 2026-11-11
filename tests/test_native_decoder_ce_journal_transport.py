#!/usr/bin/env python3
"""Strict input-validation tests for real decoder CE guest-journal transport."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from apply_native_decoder_ce_journal_transport import parse_decoder_native_log

VALID=(
  b"DCE_DEV_NAT_MILLI 2175 2105 1\n"
  b"DCE_TEST_NAT_MILLI 2090 2020 1\n"
  b"DCE_DEV_ACCEPTED_MOVES 3\n"
  b"MTH_DECODER_CE_ACCEPTED_HEX "
  b"00000001 00000074 00000068 00000065 01D28B1C 3F000000\n"
  b"MTH REAL DECODER CE FEEDBACK PASS\n"
)

class DecoderFeedbackReplayValidation(unittest.TestCase):
    def test_exact_guest_ce_record(self):
        got=parse_decoder_native_log(VALID)
        self.assertEqual(got,(1,116,104,101,30575388,0x3f000000))

    def test_no_forged_or_ambiguous_journal(self):
        variants=[
          VALID.replace(b"01D28B1C",b"01D28B18"),   # mirror reversed lane
          VALID.replace(b"00000001",b"000000FF",1), # reserved proposer
          VALID.replace(b"00000074",b"000000FF",1), # reserved tensor h
          VALID.replace(b"3F000000",b"7F800000"),   # +infinity
          VALID.replace(b"3F000000",b"7FC00000"),   # NaN
          VALID.replace(b" PASS",b" FAIL"),
          VALID.replace(b"DCE_DEV_ACCEPTED_MOVES 3\n",b""),
          VALID.replace(b"DCE_DEV_ACCEPTED_MOVES 3",b"DCE_DEV_ACCEPTED_MOVES 0"),
          VALID.replace(b"DCE_DEV_NAT_MILLI 2175 2105 1",
                        b"DCE_DEV_NAT_MILLI 2175 2105 0"),
          VALID+VALID.splitlines()[-2]+b"\n",       # duplicate proof
          b"MTH REAL DECODER CE FEEDBACK PASS\n",
        ]
        for raw in variants:
            with self.subTest(raw=raw[:100]):
                with self.assertRaises(ValueError):
                    parse_decoder_native_log(raw)

if __name__=="__main__":
    unittest.main()
