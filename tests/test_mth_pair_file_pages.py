from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from runner_riddle.mth_pair_file_pages import (
    FilePageStoreError,
    FilePairTilePageStore,
    PAGE_BYTES,
    StaleOutputGenerationError,
)
from runner_riddle.wave_tile_orchestrator import AtomicTilePublication, TileDescriptor, TileGrid

D = lambda b: hashlib.sha256(b).hexdigest()


def pages(seed: int):
    return [bytes([(seed + i) % 251]) * PAGE_BYTES for i in range(256)]


class FilePairTilePageStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.l_pages = pages(1)
        self.u_pages = pages(41)
        self.snapshot = FilePairTilePageStore.install_operator_snapshot(
            self.root, generation=4, l_pages=self.l_pages, u_pages=self.u_pages,
        )
        self.store = FilePairTilePageStore(self.root)
        self.store.initialize_output_head(generation=4, page_set_digest=self.snapshot.page_set_digest)

    def tearDown(self):
        self.temp.cleanup()

    def test_pin_snapshot_and_read_both_strip_orientations(self):
        snapshot = self.store.pin_snapshot(expected_operator_digest=self.snapshot.operator_digest)
        self.assertEqual(snapshot, self.snapshot)
        row_strip = self.store.read_strip(
            snapshot, matrix="L", row_base=0, col_base=0, rows=16, cols=256,
        )
        col_strip = self.store.read_strip(
            snapshot, matrix="U", row_base=0, col_base=0, rows=256, cols=16,
        )
        self.assertEqual(len(row_strip.data), 32768)
        self.assertEqual(len(col_strip.data), 32768)
        self.assertEqual(row_strip.data[:128], self.l_pages[0][:128])
        self.assertEqual(col_strip.data[:PAGE_BYTES], self.u_pages[0])

    def test_page_mutation_after_pin_is_detected_on_read(self):
        snapshot = self.store.pin_snapshot()
        page = self.root / "operators" / snapshot.operator_digest / "L" / "r000_c000.n16"
        page.write_bytes(b"x" * PAGE_BYTES)
        with self.assertRaises(FilePageStoreError):
            self.store.read_strip(snapshot, matrix="L", row_base=0, col_base=0, rows=16, cols=256)

    def test_operator_digest_is_immutable(self):
        with self.assertRaises(FilePageStoreError):
            FilePairTilePageStore.install_operator_snapshot(
                self.root, generation=4, l_pages=self.l_pages, u_pages=self.u_pages,
            )

    def test_all_256_tiles_publish_atomically_and_are_readable(self):
        snapshot = self.store.pin_snapshot()
        plan_digest = D(b"plan")
        candidate = self.store.begin_candidate(
            expected_current_generation=4, target_generation=5,
            plan_digest=plan_digest, snapshot=snapshot,
        )
        grid = TileGrid()
        publication = AtomicTilePublication(
            grid=grid, generation=5, plan_digest=plan_digest,
            expected_kernel_id=grid.kernel_id,
        )
        outputs = {}
        for index in range(256):
            output = bytes([index % 251]) * PAGE_BYTES
            digest = D(output)
            descriptor = TileDescriptor(index)
            self.store.write_tile(candidate, descriptor, output, digest)
            publication.add_tile(index, digest)
            outputs[index] = output
        manifest = publication.publish()
        page_digest = self.store.candidate_page_set_digest(candidate)
        pointer = self.store.publish_candidate(
            candidate, expected_current_generation=4,
            expected_page_set_digest=page_digest, manifest=manifest,
        )
        self.assertEqual(pointer["generation"], 5)
        self.assertEqual(self.store.read_output_tile(generation=5, tile_index=137), outputs[137])
        self.assertEqual(self.store.current_output_path.exists(), True)

    def test_incomplete_candidate_cannot_be_published(self):
        snapshot = self.store.pin_snapshot()
        candidate = self.store.begin_candidate(
            expected_current_generation=4, target_generation=5,
            plan_digest=D(b"plan"), snapshot=snapshot,
        )
        with self.assertRaises(FilePageStoreError):
            self.store.candidate_page_set_digest(candidate)
        self.store.discard_candidate(candidate)
        self.assertFalse(candidate.staging_path.exists())

    def test_stale_generation_cannot_publish(self):
        snapshot = self.store.pin_snapshot()
        candidate = self.store.begin_candidate(
            expected_current_generation=4, target_generation=5,
            plan_digest=D(b"plan"), snapshot=snapshot,
        )
        # Simulate another publisher winning the compare-and-swap.
        self.store.current_output_path.write_text(
            '{"schema":"nanrouter.mth-pair-output-head.v1","generation":5,"page_set_digest":"' + D(b"other") + '"}',
            encoding="utf-8",
        )
        for index in range(256):
            output = bytes([index % 251]) * PAGE_BYTES
            digest = D(output)
            self.store.write_tile(candidate, TileDescriptor(index), output, digest)
        publication = AtomicTilePublication(
            grid=TileGrid(), generation=5, plan_digest=candidate.plan_digest,
        )
        for index in range(256):
            publication.add_tile(index, candidate.tile_digests[index])
        manifest = publication.publish()
        with self.assertRaises(StaleOutputGenerationError):
            self.store.publish_candidate(
                candidate, expected_current_generation=4,
                expected_page_set_digest=self.store.candidate_page_set_digest(candidate),
                manifest=manifest,
            )
        self.store.discard_candidate(candidate)


if __name__ == "__main__":
    unittest.main()
