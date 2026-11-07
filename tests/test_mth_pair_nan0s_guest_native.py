from __future__ import annotations
import tempfile
import unittest
from pathlib import Path

from runner_riddle.mth_pair_file_pages import FilePairTilePageStore, PAGE_BYTES
from runner_riddle.mth_pair_nan0s_guest import NaN0SCLIPairTileGuest, _raw_word, _payload
from runner_riddle.mth_pair_tile_executor import _tile_strips
from runner_riddle.wave_tile_orchestrator import TileDescriptor

def _matrix_pages(matrix: bytearray) -> list[bytes]:
    pages=[]
    for tile_row in range(16):
        for tile_col in range(16):
            page=bytearray()
            for local_row in range(16):
                start=((tile_row*16+local_row)*256+tile_col*16)*8
                page.extend(matrix[start:start+16*8])
            assert len(page)==PAGE_BYTES
            pages.append(bytes(page))
    return pages

@unittest.skipUnless(
    Path("nan0s/tools/nmk.awk").is_file() and Path("nan0s/aarch64/android/nan_cli").is_file(),
    "canonical NaN0S assembler and CLI are not present",
)
class NativePairTileGuestTests(unittest.TestCase):
    def test_k16_driver_matches_full_u_for_nonzero_cross_slice_tile(self):
        with tempfile.TemporaryDirectory(prefix="mth-pair-native-test-") as temp:
            root=Path(temp)
            zero=_raw_word(0)
            l=bytearray(zero*(256*256))
            u=bytearray(zero*(256*256))
            def put(matrix,row,col,payload):
                start=(row*256+col)*8
                matrix[start:start+8]=_raw_word(payload)
            # LU contribution in K slice 0: L[1,3]*U[3,2] = 4.
            put(l,1,3,0x40000000)
            put(u,3,2,0x40000000)
            # UL^T contribution in K slice 15: U[1,245]*L[2,245] = 4.
            put(u,1,245,0x40000000)
            put(l,2,245,0x40000000)
            snapshot=FilePairTilePageStore.install_operator_snapshot(
                root,generation=0,l_pages=_matrix_pages(l),u_pages=_matrix_pages(u)
            )
            store=FilePairTilePageStore(root)
            descriptor=TileDescriptor(0)
            strips=_tile_strips(store,snapshot,descriptor)
            guest=NaN0SCLIPairTileGuest(source=store,repo_root=Path.cwd(),nan0s_root="nan0s")
            actual=guest.run_k16_driver(descriptor,strips,snapshot)
            reference=guest.run_full_u_reference(descriptor,snapshot)
            self.assertEqual(actual,reference)
            self.assertEqual(_payload(actual[18*8:19*8]),0x41000000)
            self.assertEqual(sum(_payload(actual[i:i+8])!=0 for i in range(0,len(actual),8)),1)

if __name__=="__main__":unittest.main()
