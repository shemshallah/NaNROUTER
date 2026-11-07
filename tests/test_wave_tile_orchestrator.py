from __future__ import annotations

import hashlib
import unittest

from runner_riddle.wave_tile_orchestrator import (
    BLOCK16_KERNEL_ID,
    DEFAULT_KERNEL_ID,
    FULL_U_TILE_KERNEL_ID,
    GUEST_BUDGET_BYTES,
    GUEST_BUDGET_WORDS,
    K16_KERNEL_ID,
    MATVEC_BLOCK16_KERNEL,
    TILE_COUNT,
    TILE_WORDS,
    AtomicTilePublication,
    DuplicateTileError,
    GenerationMismatchError,
    KernelMismatchError,
    MissingTileError,
    OutOfOrderTileError,
    PlanMismatchError,
    PublicationClosedError,
    TileDescriptor,
    TileEvidence,
    TileExecutionError,
    TileGrid,
    TileGridError,
    TileManifest,
    TileOrchestrator,
    TilePageWindow,
    TilePublicationError,
    TileWindowBudgetError,
    canonical_json,
    sha256_canonical_json,
)


GENERATION = 11
PLAN_DIGEST = "a" * 64


def tile_digest(index: int, salt: str = "tile") -> str:
    return hashlib.sha256(f"{salt}:{index}".encode("utf-8")).hexdigest()


class RecordingExecutor:
    def __init__(self, transform=None):
        self.calls: list[int] = []
        self.transform = transform

    def __call__(self, descriptor: TileDescriptor):
        self.calls.append(descriptor.tile_index)
        if self.transform is not None:
            return self.transform(descriptor)
        return tile_digest(descriptor.tile_index)


class TileGridTests(unittest.TestCase):
    def test_grid_is_exactly_256_row_major_16x16_tiles(self):
        grid = TileGrid()
        self.assertEqual(TILE_COUNT, 256)
        self.assertEqual(len(grid), 256)
        self.assertEqual(grid.tile_count, 256)
        self.assertEqual(grid.rows, 256)
        self.assertEqual(grid.cols, 256)
        self.assertEqual(
            [tile.tile_index for tile in grid], list(range(256))
        )

        for tile in grid:
            row, col = divmod(tile.tile_index, 16)
            self.assertEqual(tile.tile_row, row)
            self.assertEqual(tile.tile_col, col)
            self.assertEqual(tile.i_base, row * 16)
            self.assertEqual(tile.j_base, col * 16)
            self.assertEqual((tile.rows, tile.cols), (16, 16))
            self.assertEqual(tile.shape, (16, 16))
            self.assertEqual(tile.word_count, TILE_WORDS)
            self.assertEqual(tile.kernel_id, K16_KERNEL_ID)
            self.assertEqual(tile.k_slices, 16)

    def test_grid_digest_is_deterministic_and_canonical(self):
        first = TileGrid()
        second = TileGrid.build()
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(first.digest, sha256_canonical_json(first.payload()))
        self.assertEqual(len(first.digest), 64)
        self.assertEqual(first.to_dict()["grid_digest"], first.digest)
        self.assertNotIn("grid_digest", first.payload())
        self.assertEqual(
            canonical_json({"b": 1, "a": 2}),
            '{"a":2,"b":1}',
        )

    def test_alternate_block16_and_full_u_descriptors_are_available(self):
        block16 = TileGrid(kernel_id=BLOCK16_KERNEL_ID)
        self.assertEqual(block16.kernel_id, BLOCK16_KERNEL_ID)
        self.assertEqual(block16[0].kernel_id, BLOCK16_KERNEL_ID)
        self.assertEqual(
            block16[0].k_slices, MATVEC_BLOCK16_KERNEL.k_slices
        )
        self.assertEqual(len(block16), 256)

        full_u = TileGrid(kernel_id=FULL_U_TILE_KERNEL_ID)
        self.assertEqual(full_u.kernel_id, FULL_U_TILE_KERNEL_ID)
        self.assertEqual(full_u[0].k_slices, 1)
        self.assertEqual(len(full_u), 256)

    def test_invalid_descriptor_index_and_kernel_are_rejected(self):
        for index in (-1, 256, True, 1.5, "0"):
            with self.subTest(index=index):
                with self.assertRaises(TileGridError):
                    TileDescriptor(tile_index=index)
        with self.assertRaises(TileGridError):
            TileDescriptor(tile_index=0, kernel_id="not.a.kernel")

    def test_default_kernel_is_the_bounded_k16_pair_tile(self):
        self.assertEqual(DEFAULT_KERNEL_ID, K16_KERNEL_ID)
        self.assertEqual(TileGrid().kernel_id, K16_KERNEL_ID)


class TilePageWindowTests(unittest.TestCase):
    def test_window_has_one_input_one_accumulator_output_and_one_descriptor(self):
        window = TilePageWindow()
        self.assertEqual(window.input_windows, 1)
        self.assertEqual(window.input_words, TILE_WORDS)
        self.assertEqual(window.accumulator_output_windows, 1)
        self.assertEqual(window.accumulator_output_words, TILE_WORDS)
        self.assertEqual(window.tile_descriptors, 1)
        self.assertEqual(window.descriptor_words, 1)
        self.assertEqual(window.window_words, 2 * TILE_WORDS + 1)
        self.assertEqual(window.window_bytes, window.window_words * 8)

    def test_window_stays_inside_the_one_mib_guest_budget(self):
        window = TilePageWindow()
        self.assertEqual(window.guest_budget_bytes, GUEST_BUDGET_BYTES)
        self.assertEqual(window.guest_budget_words, GUEST_BUDGET_WORDS)
        self.assertEqual(window.guest_budget_bytes, 1024 * 1024)
        self.assertEqual(window.guest_budget_words, 131072)
        self.assertTrue(window.within_guest_budget)
        self.assertLessEqual(window.window_bytes, GUEST_BUDGET_BYTES)

        orchestrator = TileOrchestrator()
        publication = orchestrator.new_publication()
        for bounded in (window, orchestrator, publication):
            self.assertEqual(bounded.window_words, window.window_words)
            self.assertLessEqual(bounded.window_words, GUEST_BUDGET_WORDS)
            self.assertTrue(bounded.within_guest_budget)

    def test_window_cannot_be_widened_past_one_tile(self):
        with self.assertRaises(TileWindowBudgetError):
            TilePageWindow(input_words=TILE_WORDS + 1)
        with self.assertRaises(TileWindowBudgetError):
            TilePageWindow(accumulator_output_words=TILE_WORDS + 1)
        with self.assertRaises(TileWindowBudgetError):
            TilePageWindow(descriptor_words=2)

    def test_window_budget_violation_is_rejected(self):
        with self.assertRaises(TileWindowBudgetError):
            TilePageWindow(guest_budget_bytes=TilePageWindow().window_bytes - 1)
        with self.assertRaises(TileWindowBudgetError):
            TileOrchestrator(guest_budget_bytes=1)


class AtomicTilePublicationTests(unittest.TestCase):
    def setUp(self):
        self.grid = TileGrid()
        self.publication = AtomicTilePublication(
            grid=self.grid,
            generation=GENERATION,
            plan_digest=PLAN_DIGEST,
        )

    def fill(self, count=256, *, generation=None, plan_digest=None):
        for index in range(count):
            kwargs = {}
            if generation is not None:
                kwargs["generation"] = generation
            if plan_digest is not None:
                kwargs["plan_digest"] = plan_digest
            self.publication.add_tile(index, tile_digest(index), **kwargs)

    def test_all_256_tiles_publish_one_canonical_manifest(self):
        self.fill()
        self.assertTrue(self.publication.is_complete)
        self.assertEqual(self.publication.received_count, 256)
        self.assertEqual(self.publication.missing_indices, ())
        self.assertFalse(self.publication.published)
        self.assertIsNone(self.publication.manifest)
        self.assertIsNone(self.publication.digest)

        manifest = self.publication.publish()
        self.assertIsInstance(manifest, TileManifest)
        self.assertTrue(self.publication.published)
        self.assertIs(self.publication.manifest, manifest)
        self.assertIs(self.publication.publish(), manifest)
        self.assertEqual(self.publication.digest, manifest.digest)
        self.assertEqual(self.publication.manifest_digest, manifest.digest)
        self.assertEqual(manifest.tile_count, 256)
        self.assertEqual(manifest.generation, GENERATION)
        self.assertEqual(manifest.plan_digest, PLAN_DIGEST)
        self.assertEqual(manifest.grid_digest, self.grid.digest)
        self.assertEqual(len(manifest.tiles), 256)
        self.assertEqual(
            [tile.tile_index for tile in manifest.tiles], list(range(256))
        )
        self.assertTrue(
            all(tile.digest == tile_digest(i) for i, tile in enumerate(manifest.tiles))
        )

        document = manifest.to_dict()
        self.assertEqual(document["manifest_digest"], manifest.digest)
        self.assertEqual(document["tile_count"], 256)
        self.assertEqual(document["window_words"], self.publication.window_words)
        recomputed = dict(document)
        claimed = recomputed.pop("manifest_digest")
        self.assertEqual(claimed, sha256_canonical_json(recomputed))
        self.assertEqual(manifest["manifest_digest"], manifest.digest)
        self.assertEqual(manifest["digest"], manifest.digest)
        self.assertEqual(manifest.get("generation"), GENERATION)

    def test_missing_tile_blocks_publication(self):
        self.fill(255)
        self.assertFalse(self.publication.is_complete)
        self.assertEqual(self.publication.missing_indices, (255,))
        with self.assertRaises(MissingTileError):
            self.publication.publish()
        self.assertFalse(self.publication.published)
        self.assertIsNone(self.publication.manifest)

    def test_publish_failure_is_recoverable_by_adding_the_missing_tile(self):
        self.fill(255)
        with self.assertRaises(MissingTileError):
            self.publication.publish()
        self.publication.add_tile(255, tile_digest(255))
        manifest = self.publication.publish()
        self.assertEqual(manifest.tile_count, 256)
        self.assertTrue(self.publication.published)

    def test_manifest_digest_is_deterministic_across_publications(self):
        self.fill()
        second = AtomicTilePublication(
            grid=self.grid, generation=GENERATION, plan_digest=PLAN_DIGEST
        )
        for index in range(256):
            second.add_tile(index, tile_digest(index))
        self.assertEqual(
            self.publication.publish().digest, second.publish().digest
        )

    def test_duplicate_tile_blocks_publication(self):
        evidence = TileEvidence(0, tile_digest(0))
        self.publication.add_tile(evidence)
        with self.assertRaises(DuplicateTileError):
            self.publication.add_tile(evidence)
        self.assertEqual(self.publication.received_count, 1)
        self.assertFalse(self.publication.published)

    def test_out_of_order_tile_blocks_publication(self):
        with self.assertRaises(OutOfOrderTileError):
            self.publication.add_tile(1, tile_digest(1))
        self.assertEqual(self.publication.received_count, 0)
        self.assertFalse(self.publication.published)
        with self.assertRaises(MissingTileError):
            self.publication.publish()

    def test_wrong_generation_blocks_publication(self):
        evidence = TileEvidence(
            tile_index=0,
            digest=tile_digest(0),
            generation=GENERATION + 1,
            plan_digest=PLAN_DIGEST,
        )
        with self.assertRaises(GenerationMismatchError):
            self.publication.add_tile(evidence)
        self.assertEqual(self.publication.received_count, 0)
        with self.assertRaises(MissingTileError):
            self.publication.publish()

    def test_wrong_plan_digest_blocks_publication(self):
        evidence = TileEvidence(
            tile_index=0,
            digest=tile_digest(0),
            generation=GENERATION,
            plan_digest="b" * 64,
        )
        with self.assertRaises(PlanMismatchError):
            self.publication.add_tile(evidence)
        self.assertEqual(self.publication.received_count, 0)

    def test_wrong_kernel_or_slice_count_blocks_publication(self):
        with self.assertRaises(KernelMismatchError):
            self.publication.add_tile(
                0, tile_digest(0), kernel_id=BLOCK16_KERNEL_ID
            )
        with self.assertRaises(KernelMismatchError):
            self.publication.add_tile(0, tile_digest(0), k_slices=15)
        self.assertEqual(self.publication.received_count, 0)

    def test_published_publication_is_closed(self):
        self.fill()
        self.publication.publish()
        with self.assertRaises(PublicationClosedError):
            self.publication.add_tile(256, tile_digest(256))

    def test_constructor_aliases_and_defaults(self):
        defaulted = AtomicTilePublication(grid=self.grid, expected_generation=3)
        self.assertEqual(defaulted.generation, 3)
        self.assertEqual(defaulted.expected_generation, 3)
        self.assertEqual(defaulted.plan_digest, self.grid.digest)
        self.assertEqual(defaulted.expected_plan_digest, self.grid.digest)

        with self.assertRaises(TilePublicationError):
            AtomicTilePublication(
                grid=self.grid, generation=1, expected_generation=2
            )
        with self.assertRaises(PlanMismatchError):
            AtomicTilePublication(
                grid=self.grid, plan_digest="a" * 64,
                expected_plan_digest="b" * 64,
            )
        with self.assertRaises(KernelMismatchError):
            AtomicTilePublication(
                grid=self.grid, expected_kernel_id=BLOCK16_KERNEL_ID
            )

    def test_keyword_tile_index_and_mapping_forms(self):
        self.publication.add_tile(
            tile_index=0, digest=tile_digest(0), generation=GENERATION,
            plan_digest=PLAN_DIGEST,
        )
        self.publication.add_tile(
            {
                "tile_index": 1,
                "digest": tile_digest(1),
                "generation": GENERATION,
                "plan_digest": PLAN_DIGEST,
            }
        )
        self.assertEqual(self.publication.received_count, 2)
        self.assertEqual(self.publication.missing_indices[0], 2)


class TileOrchestratorTests(unittest.TestCase):
    def test_executor_runs_all_tiles_row_major_and_publishes(self):
        orchestrator = TileOrchestrator()
        executor = RecordingExecutor()
        manifest = orchestrator.execute(
            executor, generation=GENERATION, plan_digest=PLAN_DIGEST
        )

        self.assertEqual(executor.calls, list(range(256)))
        self.assertEqual(manifest.tile_count, 256)
        self.assertEqual(manifest.generation, GENERATION)
        self.assertEqual(manifest.plan_digest, PLAN_DIGEST)
        self.assertEqual(manifest.kernel_id, K16_KERNEL_ID)
        self.assertEqual(manifest.grid_digest, orchestrator.grid.digest)
        self.assertEqual(manifest.tiles[0].digest, tile_digest(0))
        self.assertEqual(manifest.digest, sha256_canonical_json(manifest.payload()))

    def test_executor_can_return_raw_output_window_bytes(self):
        orchestrator = TileOrchestrator()
        manifest = orchestrator.execute(
            lambda descriptor: f"tile-{descriptor.tile_index}".encode(),
            generation=1,
        )
        self.assertEqual(
            manifest.tiles[0].digest,
            hashlib.sha256(b"tile-0").hexdigest(),
        )
        self.assertEqual(manifest.tiles[255].digest, hashlib.sha256(b"tile-255").hexdigest())

    def test_executor_can_return_evidence_or_mapping(self):
        orchestrator = TileOrchestrator()

        def executor(descriptor):
            if descriptor.tile_index % 2:
                return {
                    "digest": tile_digest(descriptor.tile_index),
                    "generation": 7,
                    "plan_digest": orchestrator.digest,
                }
            return TileEvidence(
                tile_index=descriptor.tile_index,
                digest=tile_digest(descriptor.tile_index),
                generation=7,
                plan_digest=orchestrator.digest,
                kernel_id=descriptor.kernel_id,
                k_slices=descriptor.k_slices,
            )

        manifest = orchestrator.execute(executor, generation=7)
        self.assertEqual(manifest.tile_count, 256)
        self.assertEqual(manifest.tiles[1].digest, tile_digest(1))

    def test_executor_failure_leaves_publication_incomplete(self):
        orchestrator = TileOrchestrator()
        publication = orchestrator.new_publication(generation=5)

        def executor(descriptor):
            if descriptor.tile_index == 137:
                raise RuntimeError("native execution failed")
            return tile_digest(descriptor.tile_index)

        with self.assertRaises(RuntimeError):
            orchestrator.execute(executor, publication=publication)

        self.assertEqual(publication.received_count, 137)
        self.assertFalse(publication.is_complete)
        self.assertFalse(publication.published)
        self.assertIsNone(publication.manifest)
        with self.assertRaises(MissingTileError):
            publication.publish()

    def test_retry_resumes_at_the_first_missing_tile(self):
        orchestrator = TileOrchestrator()
        publication = orchestrator.new_publication(generation=5)

        def failing_executor(descriptor):
            if descriptor.tile_index == 137:
                raise RuntimeError("native execution failed")
            return tile_digest(descriptor.tile_index)

        with self.assertRaises(RuntimeError):
            orchestrator.execute(failing_executor, publication=publication)

        resumed = RecordingExecutor()
        manifest = orchestrator.execute(
            resumed, publication=publication, generation=5
        )
        self.assertEqual(resumed.calls, list(range(137, 256)))
        self.assertEqual(manifest.tile_count, 256)
        self.assertEqual(manifest.tiles[0].digest, tile_digest(0))
        self.assertEqual(manifest.tiles[137].digest, tile_digest(137))

    def test_executor_result_must_belong_to_the_current_tile(self):
        orchestrator = TileOrchestrator()
        with self.assertRaises(TileExecutionError):
            orchestrator.execute(
                lambda descriptor: TileEvidence(
                    tile_index=(descriptor.tile_index + 1) % 256,
                    digest=tile_digest(descriptor.tile_index),
                )
            )
        with self.assertRaises(TileExecutionError):
            orchestrator.execute(lambda descriptor: {"notes": "no digest"})
        with self.assertRaises(TileExecutionError):
            orchestrator.execute(lambda descriptor: object())

    def test_executor_must_be_callable(self):
        with self.assertRaises(TileExecutionError):
            TileOrchestrator().execute(None)

    def test_publication_can_be_bound_before_execution(self):
        orchestrator = TileOrchestrator()
        publication = orchestrator.new_publication(
            expected_generation=8, expected_plan_digest=orchestrator.digest
        )
        manifest = orchestrator.execute(
            RecordingExecutor(), publication=publication, generation=8
        )
        self.assertIs(manifest, publication.manifest)

    def test_orchestrator_rejects_a_mismatched_publication(self):
        first = TileOrchestrator()
        second = TileOrchestrator(kernel_id=BLOCK16_KERNEL_ID)
        publication = first.new_publication()
        with self.assertRaises(TilePublicationError):
            second.execute(RecordingExecutor(), publication=publication)
        with self.assertRaises(GenerationMismatchError):
            first.execute(
                RecordingExecutor(),
                publication=publication,
                generation=publication.generation + 1,
            )

    def test_iter_tiles_yields_one_descriptor_at_a_time(self):
        orchestrator = TileOrchestrator()
        seen = []
        for descriptor in orchestrator.iter_tiles():
            seen.append(descriptor.tile_index)
        self.assertEqual(seen, list(range(256)))
        self.assertEqual(orchestrator.tile_count, 256)
        self.assertEqual(orchestrator.window_words, TilePageWindow().window_words)


if __name__ == "__main__":
    unittest.main()
