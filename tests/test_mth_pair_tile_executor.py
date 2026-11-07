from __future__ import annotations

import hashlib
import unittest
from dataclasses import dataclass

from runner_riddle.wave_tile_orchestrator import TileDescriptor, TileGrid
from runner_riddle.mth_pair_tile_executor import (
    DenseReferenceMismatchError,
    OperatorSnapshot,
    PageStrip,
    PairTileExecutionError,
    PairTileGenerationExecutor,
    SnapshotMismatchError,
    STRIP_BYTES,
)

D = lambda text: hashlib.sha256(text.encode()).hexdigest()
SNAPSHOT = OperatorSnapshot(
    generation=4, operator_digest=D("operator"), l_digest=D("L"),
    u_digest=D("U"), page_set_digest=D("input-pages"), snapshot_id="snapshot-4",
)


class FakeSource:
    def __init__(self, *, mismatch_at=None):
        self.mismatch_at = mismatch_at
        self.reads = []

    def pin_snapshot(self, *, expected_operator_digest=None):
        if expected_operator_digest is not None and expected_operator_digest != SNAPSHOT.operator_digest:
            raise SnapshotMismatchError("operator digest mismatch")
        return SNAPSHOT

    def read_strip(self, snapshot, *, matrix, row_base, col_base, rows, cols):
        key = (matrix, row_base, col_base, rows, cols)
        self.reads.append(key)
        wrong = self.mismatch_at == key
        return PageStrip(
            matrix=matrix, row_base=row_base, col_base=col_base,
            rows=rows, cols=cols, data=bytes([len(self.reads) % 251]) * STRIP_BYTES,
            generation=snapshot.generation,
            operator_digest=("0" * 64) if wrong else snapshot.operator_digest,
            matrix_digest=snapshot.l_digest if matrix == "L" else snapshot.u_digest,
            page_set_digest=snapshot.page_set_digest,
        )


class FakeGuest:
    def __init__(self, *, mismatch_tile=None):
        self.k16_calls = []
        self.reference_calls = []
        self.mismatch_tile = mismatch_tile

    def run_k16_driver(self, descriptor, strips, snapshot):
        self.k16_calls.append(descriptor.tile_index)
        assert tuple(strips) == ("L_IK", "U_KJ", "U_IK", "L_JK")
        return bytes([descriptor.tile_index % 251]) * 2048

    def run_full_u_reference(self, descriptor, snapshot):
        self.reference_calls.append(descriptor.tile_index)
        value = descriptor.tile_index % 251
        if descriptor.tile_index == self.mismatch_tile:
            value = (value + 1) % 251
        return bytes([value]) * 2048


class FakePageStore:
    def __init__(self):
        self.candidate = None
        self.tiles = {}
        self.published = None
        self.discarded = False

    def begin_candidate(self, **kwargs):
        self.candidate = kwargs
        return object()

    def write_tile(self, candidate, descriptor, output, tile_digest):
        if descriptor.tile_index in self.tiles:
            raise AssertionError("duplicate tile")
        self.tiles[descriptor.tile_index] = (output, tile_digest)

    def candidate_page_set_digest(self, candidate):
        return hashlib.sha256(b"".join(
            self.tiles[i][1].encode() for i in sorted(self.tiles)
        )).hexdigest()

    def publish_candidate(self, candidate, **kwargs):
        self.published = kwargs

    def discard_candidate(self, candidate):
        self.discarded = True


class PairTileGenerationExecutorTests(unittest.TestCase):
    def make_executor(self, *, guest=None, source=None, store=None, workers=3,
                      guest_budget_words=None):
        kwargs = {
            "source": source or FakeSource(),
            "guest": guest or FakeGuest(),
            "page_store": store or FakePageStore(),
            "max_workers": workers,
        }
        if guest_budget_words is not None:
            kwargs["guest_budget_words"] = guest_budget_words
        return PairTileGenerationExecutor(**kwargs)

    def test_all_256_tiles_stage_compare_and_publish_one_generation(self):
        source, guest, store = FakeSource(), FakeGuest(), FakePageStore()
        executor = self.make_executor(source=source, guest=guest, store=store)
        manifest = executor.execute(expected_operator_digest=SNAPSHOT.operator_digest)
        self.assertEqual(manifest.tile_count, 256)
        self.assertEqual(manifest.generation, SNAPSHOT.generation + 1)
        self.assertEqual(len(guest.k16_calls), 256)
        self.assertEqual(len(guest.reference_calls), 256)
        self.assertEqual(len(source.reads), 256 * 4)
        self.assertEqual(len(store.tiles), 256)
        self.assertIsNotNone(store.published)
        self.assertFalse(store.discarded)
        self.assertEqual(store.candidate["expected_current_generation"], 4)
        self.assertEqual(store.candidate["target_generation"], 5)

    def test_every_tile_is_bound_to_the_same_operator_and_page_set(self):
        source, guest, store = FakeSource(), FakeGuest(), FakePageStore()
        manifest = self.make_executor(source=source, guest=guest, store=store).execute()
        self.assertTrue(all(t.plan_digest == manifest.plan_digest for t in manifest.tiles))
        self.assertTrue(all(t.generation == 5 for t in manifest.tiles))

    def test_changed_operator_digest_rejects_staging(self):
        source, guest, store = FakeSource(mismatch_at=("L", 0, 0, 16, 256)), FakeGuest(), FakePageStore()
        with self.assertRaises(SnapshotMismatchError):
            self.make_executor(source=source, guest=guest, store=store).execute()
        self.assertTrue(store.discarded)
        self.assertIsNone(store.published)

    def test_dense_reference_mismatch_discards_candidate(self):
        store = FakePageStore()
        with self.assertRaises(DenseReferenceMismatchError):
            self.make_executor(guest=FakeGuest(mismatch_tile=17), store=store).execute()
        self.assertTrue(store.discarded)
        self.assertIsNone(store.published)

    def test_workspace_budget_limits_parallel_guest_workers(self):
        with self.assertRaises(PairTileExecutionError):
            self.make_executor(workers=4, guest_budget_words=131_072)
        # The default 2 MiB profile permits 10 K16 workers + the dense reference.
        self.make_executor(workers=10)
        with self.assertRaises(PairTileExecutionError):
            self.make_executor(workers=11)

    def test_wrong_expected_operator_digest_fails_before_candidate_creation(self):
        store = FakePageStore()
        with self.assertRaises(SnapshotMismatchError):
            self.make_executor(store=store).execute(expected_operator_digest="0" * 64)
        self.assertIsNone(store.candidate)

    def test_row_strip_is_packed_as_sixteen_contiguous_k_blocks(self):
        from runner_riddle.mth_pair_tile_executor import _pack_row_strip_k16

        source = bytearray(16 * 256 * 8)
        for row in range(16):
            for k in range(256):
                word = (row * 256 + k).to_bytes(8, "little")
                start = (row * 256 + k) * 8
                source[start:start + 8] = word

        packed = _pack_row_strip_k16(bytes(source))
        self.assertEqual(len(packed), len(source))
        for k_block in range(16):
            for row in range(16):
                for local_k in range(16):
                    global_k = k_block * 16 + local_k
                    target_word = k_block * 256 + row * 16 + local_k
                    actual = int.from_bytes(packed[target_word * 8:(target_word + 1) * 8], "little")
                    self.assertEqual(actual, row * 256 + global_k)

    def test_invalid_row_strip_length_is_rejected(self):
        from runner_riddle.mth_pair_tile_executor import _pack_row_strip_k16

        with self.assertRaises(PairTileExecutionError):
            _pack_row_strip_k16(b"short")

    def test_strip_shape_is_enforced(self):
        page = PageStrip(
            matrix="L", row_base=0, col_base=0, rows=16, cols=256,
            data=b"x", generation=4, operator_digest=SNAPSHOT.operator_digest,
            matrix_digest=SNAPSHOT.l_digest, page_set_digest=SNAPSHOT.page_set_digest,
        )
        with self.assertRaises(SnapshotMismatchError):
            page.validate_for(SNAPSHOT, matrix="L", row_base=0, col_base=0, rows=16, cols=256)


if __name__ == "__main__":
    unittest.main()
