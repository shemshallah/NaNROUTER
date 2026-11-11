#!/usr/bin/env python3
"""Build-time R25 28-way masked trace contract, without synthetic ML training."""
from pathlib import Path
import json
import struct
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from build_native_decoder_ce_fixture import parse,build

NEG_INF=0xFF800000

def f32bits(x:float)->int:
    return struct.unpack("<I",struct.pack("<f",x))[0]

def trace(path:Path,h:int=19,a:int=7,label:int=4,badpad:bool=False)->None:
    logits=[f32bits(-1.0)]*28+[NEG_INF]*228
    logits[4]=f32bits(0.0)
    if badpad: logits[200]=f32bits(-0.1)
    line=str(label)+" "+" ".join(f"{w:08X}" for w in logits)
    path.write_text(f"FROZEN_DECODER_TRACE_V1 {h} {a} 1\n"+line+"\n")


class MaskedHybridFixture(unittest.TestCase):
    def test_native_source_compatible_28_symbol_hybrid(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);dev=root/"dev.trace";test=root/"test.trace"
            trace(dev);trace(test)
            nas=root/"guest.nas";manifest=root/"manifest.json"
            build(dev,test,nas,manifest,19,7,4,"r25-48m-char")
            info=json.loads(manifest.read_text())
            self.assertTrue(info["hybrid_spelling_48m_connected"])
            self.assertFalse(info["hybrid_full_word_perplexity_connected"])
            self.assertEqual(info["sample_count"],{"dev":1,"test":1})
            self.assertEqual(info["tensor_coordinate"],[19,7,4])
            self.assertIn("masked 28-way",info["loss"])
            self.assertIn("0xFF800000",nas.read_text())
            self.assertNotIn("Frozen real HW0",nas.read_text())

    def test_masked_targets_and_outside_classes_reject(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);dev=root/"dev.trace";test=root/"test.trace"
            trace(dev);trace(test)
            cases=[
              lambda: trace(dev,badpad=True),
              lambda: trace(dev,label=28),
              lambda: trace(dev,h=116),
            ]
            for transform in cases:
                trace(dev)
                transform()
                with self.assertRaises(ValueError):
                    build(dev,test,root/"guest.nas",root/"manifest.json",
                          19,7,4,"r25-48m-char")

    def test_hybrid_requires_symbol_indices_not_ascii(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);dev=root/"dev.trace";test=root/"test.trace"
            trace(dev,h=116,a=104);trace(test,h=116,a=104)
            with self.assertRaises(ValueError):
                build(dev,test,root/"x.nas",root/"x.json",
                      116,104,101,"r25-48m-char")

if __name__=="__main__":
    unittest.main()
