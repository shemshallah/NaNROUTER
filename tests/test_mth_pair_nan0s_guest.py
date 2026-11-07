import unittest
from runner_riddle.mth_pair_nan0s_guest import _payload,_raw_word,_render_words,_parse_peek
from runner_riddle.mth_pair_tile_executor import PairTileExecutionError

class NaN0SGuestCodecTests(unittest.TestCase):
    def test_canonical_word_round_trip(self):
        for x in (0,1,0x3f800000,0x40000000,0x40400000,0x7fc00000,0xffffffff):
            self.assertEqual(_payload(_raw_word(x)),x)
    def test_word_render(self):
        raw=b"".join(_raw_word(x) for x in (0,0x3f800000,0x40000000))
        self.assertEqual(_render_words(raw),".word 0x00000000\n.word 0x3F800000\n.word 0x40000000\n")
    def test_peek_requires_clean_halt_and_exact_count(self):
        out="00000001\n3F800000\n40000000\n"
        err="[nan_cli] nan-text: 123 steps, rc=3, pc=0, trap=''\n"
        raw=_parse_peek(out,err,3)
        self.assertEqual(_payload(raw[:8]),1)
        with self.assertRaises(PairTileExecutionError):_parse_peek(out,err,4)
        with self.assertRaises(PairTileExecutionError):_parse_peek(out,"rc=3, pc=0, trap='!O0001'",3)

if __name__=="__main__":unittest.main()
