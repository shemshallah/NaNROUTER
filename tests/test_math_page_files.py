"""Tests for immutable file-backed 32 KiB universe page files.

The file layer is additive to the durable page records in ``MathStore``.  Page
files are bound to a page id, the record's immutable leaf digest, and the
SHA-256 of their exact 32 KiB content.  Page 255 remains the NANNET0 node page,
not a lane or head index.
"""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runner_riddle.math_objects import MathLeaf
from runner_riddle.math_page_files import (
    MathPageFileBoundsError,
    MathPageFileConflictError,
    MathPageFileDigestError,
    MathPageFileError,
    MathPageFileMapDigestError,
    MathPageFileMissingError,
    MathPageFileProvider,
    MathPageFileSizeError,
    PAGE_FILE_BYTES,
    PAGE_FILE_SCHEMA,
    PAGE_FILE_SET_SCHEMA,
)
from runner_riddle.math_store import (
    NANNET0_PAGE_ID, PAGE_COUNT, MathPageBoundsError, MathReferenceError,
    MathStore,
)


class MathPageFileProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "page-root"
        self.provider = MathPageFileProvider(self.root)
        self.store = MathStore(
            self.tmp.name + "/bs0db.sqlite3",
            self.tmp.name + "/mc0db.sqlite3",
        )
        self.leaf = self.make_leaf("nml:test:page-file:1", 1)
        self.data = bytes(range(256)) * 128

    def make_leaf(self, leaf_id, value):
        return self.store.put_leaf(MathLeaf(
            leaf_id=leaf_id,
            kind="scalar",
            content={"value": value},
            type={"kind": "scalar"},
            provenance={"producer": "page-file-test"},
        ))

    def payload(self, seed=0):
        return bytes((index + seed) % 256
                     for index in range(PAGE_FILE_BYTES))

    def pin(self, page_id, *, data=None, leaf=None):
        record = self.store.pin_page(
            page_id, "runner-0", leaf or self.leaf, tick=page_id + 1,
        )
        published = self.provider.pin_page_record(
            record, self.data if data is None else data,
        )
        return record, published

    # -- roundtrip and atomic publication -----------------------------------

    def test_pin_read_roundtrip_and_idempotent_reuse(self):
        record, published = self.pin(0)
        content_digest = hashlib.sha256(self.data).hexdigest()

        self.assertEqual(published["schema"], PAGE_FILE_SCHEMA)
        self.assertEqual(published["page_id"], 0)
        self.assertEqual(published["page_key"], "page:000")
        self.assertEqual(published["kind"], "head")
        self.assertEqual(published["leaf_digest"], self.leaf.digest())
        self.assertEqual(published["content_digest"], content_digest)
        self.assertEqual(published["size_bytes"], PAGE_FILE_BYTES)
        self.assertEqual(
            published["filename"],
            f"page-000-{self.leaf.digest()}-{content_digest}.page",
        )
        self.assertFalse(published["reused"])
        self.assertEqual(Path(published["path"]).parent, self.root)
        self.assertEqual(
            Path(published["path"]).stat().st_size, PAGE_FILE_BYTES,
        )

        self.assertEqual(self.provider.read_page_record(record), self.data)
        loaded = self.provider.load_page_record(record)
        self.assertEqual(loaded["data"], self.data)
        self.assertEqual(loaded["content_digest"], content_digest)
        self.assertEqual(
            self.provider.read_page(
                0, content_digest, leaf_digest=record["leaf_digest"],
            ),
            self.data,
        )

        replay = self.provider.pin_page_record(record, self.data)
        self.assertTrue(replay["reused"])
        self.assertEqual(len(self.provider.list_page_files()), 1)

    def test_atomic_publication_failure_leaves_no_partial_page(self):
        record = self.store.pin_page(
            0, "runner-0", self.leaf, tick=1,
        )
        expected = self.data

        def failing_replace(source, destination):
            source = Path(source)
            destination = Path(destination)
            self.assertEqual(source.parent, self.root)
            self.assertEqual(destination.parent, self.root)
            self.assertEqual(source.read_bytes(), expected)
            raise OSError("injected publication failure")

        with mock.patch(
            "runner_riddle.math_page_files.os.replace",
            side_effect=failing_replace,
        ) as replace:
            with self.assertRaises(OSError):
                self.provider.write_page(
                    0, self.data, leaf_digest=record["leaf_digest"],
                )
            self.assertEqual(replace.call_count, 1)

        self.assertEqual(self.provider.list_page_files(), [])
        self.assertEqual(
            [item.name for item in self.root.iterdir()
             if item.name.endswith(".tmp")],
            [],
        )
        self.assertEqual(
            [item.name for item in self.root.iterdir()
             if item.name.endswith(".page")],
            [],
        )

        published = self.provider.pin_page_record(record, self.data)
        self.assertTrue(Path(published["path"]).is_file())
        self.assertEqual(self.provider.read_page_record(record), self.data)

    # -- corruption / missing / wrong binding -------------------------------

    def test_corrupt_truncated_oversized_and_misnamed_files_are_rejected(self):
        record, published = self.pin(0)
        path = Path(published["path"])

        corrupt = bytearray(self.data)
        corrupt[17] ^= 0x80
        path.write_bytes(corrupt)
        with self.assertRaises(MathPageFileDigestError):
            self.provider.read_page_record(record)

        path.write_bytes(self.data[:-1])
        with self.assertRaises(MathPageFileSizeError):
            self.provider.read_page_record(record)

        path.write_bytes(self.data + b"\x00")
        with self.assertRaises(MathPageFileSizeError):
            self.provider.read_page_record(record)

        path.write_bytes(self.data)
        wrong_name = path.with_name(
            path.name.replace(published["content_digest"], "f" * 64)
        )
        path.rename(wrong_name)
        with self.assertRaises(MathPageFileDigestError):
            self.provider.read_page_record(record)

    def test_missing_file_is_a_reference_error(self):
        record = self.store.pin_page(
            0, "runner-0", self.leaf, tick=1,
        )
        with self.assertRaises(MathPageFileMissingError):
            self.provider.read_page_record(record)
        with self.assertRaises(MathReferenceError):
            self.provider.read_page_record(record)
        with self.assertRaises(MathPageFileMissingError):
            self.provider.read_page(
                0, hashlib.sha256(self.data).hexdigest(),
            )
        # Read-only loads never create or repair the caller's root.
        self.assertFalse(self.root.exists())

        record, published = self.pin(1)
        Path(published["path"]).unlink()
        with self.assertRaises(MathPageFileMissingError):
            self.provider.read_page_record(record)

    def test_wrong_page_digest_and_immutable_binding_are_rejected(self):
        record0 = self.store.pin_page(
            0, "runner-0", self.leaf, tick=1,
        )
        published = self.provider.pin_page_record(record0, self.data)
        record1 = self.store.pin_page(
            1, "runner-0", self.leaf, tick=2,
        )

        with self.assertRaises(MathPageFileMissingError):
            self.provider.read_page_record(record1)
        with self.assertRaises(MathPageFileMissingError):
            self.provider.read_page(0, "f" * 64)
        with self.assertRaises(MathPageFileDigestError):
            self.provider.write_page(
                0, self.data, leaf_digest=self.leaf.digest(),
                digest="0" * 64,
            )
        self.assertEqual(len(self.provider.list_page_files()), 1)

        other = self.payload(1)
        with self.assertRaises(MathPageFileConflictError):
            self.provider.write_page(
                0, other, leaf_digest=self.leaf.digest(),
            )
        self.assertEqual(self.provider.read_page_record(record0), self.data)

        path = Path(published["path"])
        path.rename(path.with_name(
            path.name.replace("page-000", "page-001")
        ))
        with self.assertRaises(MathPageFileMissingError):
            self.provider.read_page_record(record0)
        with self.assertRaises(MathPageFileMissingError):
            self.provider.read_page(0, published["content_digest"])

    # -- traversal / malformed names ---------------------------------------

    def test_traversal_and_invalid_page_ids_or_digests_are_rejected(self):
        leaf_digest = self.leaf.digest()
        content_digest = hashlib.sha256(self.data).hexdigest()

        for bad in (-1, PAGE_COUNT, 1000, True, "0", "../0", None, 1.5):
            with self.assertRaises(MathPageBoundsError):
                self.provider.page_path(bad, leaf_digest, content_digest)
            with self.assertRaises(MathPageBoundsError):
                self.provider.write_page(
                    bad, self.data, leaf_digest=leaf_digest,
                )

        for bad in ("", "a" * 63, "a" * 65, "A" * 64,
                    "../" + "a" * 61, None, 123):
            with self.assertRaises(MathPageFileError):
                self.provider.write_page(
                    0, self.data, leaf_digest=bad,
                )
            with self.assertRaises(MathPageFileError):
                self.provider.page_path(0, leaf_digest, bad)

        self.root.mkdir(parents=True)
        malformed = self.root / (
            f"page-999-{'a' * 64}-{'b' * 64}.page"
        )
        malformed.write_bytes(b"not-a-page")
        with self.assertRaises(MathPageFileBoundsError):
            self.provider.list_page_files()
        malformed.unlink()
        self.assertEqual(self.provider.list_page_files(), [])

    def test_symlinked_page_file_cannot_escape_the_root(self):
        record, published = self.pin(0)
        path = Path(published["path"])
        outside = Path(self.tmp.name) / "outside.page"
        path.rename(outside)
        try:
            path.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {exc}")

        with self.assertRaises(MathPageFileError):
            self.provider.read_page_record(record)
        with self.assertRaises(MathPageFileError):
            self.provider.verify_page_map(self.store)

    # -- NANNET0 and page-map digest ----------------------------------------

    def test_nannet0_page_file_roundtrip_and_kind_binding(self):
        record = self.store.pin_page(
            NANNET0_PAGE_ID, "node-0", self.leaf, tick=1,
        )
        self.assertEqual(record["kind"], "nannet0")
        published = self.provider.pin_page_record(record, self.data)
        self.assertEqual(published["page_id"], 255)
        self.assertEqual(published["kind"], "nannet0")
        self.assertIn("page-255-", published["filename"])
        loaded = self.provider.load_page_record(record)
        self.assertEqual(loaded["data"], self.data)
        self.assertEqual(loaded["kind"], "nannet0")

        with self.assertRaises(MathPageFileError):
            self.provider.pin_page_record(
                {**record, "kind": "head"}, self.data,
            )
        with self.assertRaises(MathPageFileError):
            self.provider.pin_page_record(
                {**record, "page_key": "page:254"}, self.data,
            )

    def test_page_map_digest_verification_and_operational_churn(self):
        self.pin(0)
        self.pin(NANNET0_PAGE_ID)
        expected = self.store.page_map_digest()

        report = self.provider.verify_page_map(
            self.store, expected_digest=expected,
        )
        self.assertEqual(report["schema"], PAGE_FILE_SET_SCHEMA)
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["page_map_digest"], expected)
        self.assertEqual(report["verified_pages"], 2)
        self.assertEqual(report["page_ids"], [0, NANNET0_PAGE_ID])
        self.assertEqual(report["page_bytes"], PAGE_FILE_BYTES)
        self.assertEqual(len(report["files"]), 2)

        # Pin/release churn does not change content binding or file identity.
        self.store.release_page(0, 1, tick=10)
        self.store.pin_page(
            0, "runner-1", self.leaf, expected_generation=2, tick=11,
        )
        replay = self.provider.verify_page_map(
            self.store, expected_digest=expected,
        )
        self.assertEqual(replay["page_map_digest"], expected)

        with self.assertRaises(MathPageFileMapDigestError):
            self.provider.verify_page_map(
                self.store, expected_digest="f" * 64,
            )

    def test_page_map_verification_detects_missing_and_unbound_files(self):
        record0, _ = self.pin(0)
        record1, published1 = self.pin(1)
        report = self.provider.verify_page_map(self.store)
        self.assertEqual(report["verified_pages"], 2)

        Path(published1["path"]).unlink()
        with self.assertRaises(MathPageFileMissingError):
            self.provider.verify_page_map(self.store)

        self.provider.pin_page_record(record1, self.data)
        self.assertEqual(
            self.provider.verify_page_map(self.store)["page_ids"], [0, 1],
        )

        other_leaf = self.make_leaf("nml:test:page-file:other", 99)
        self.provider.write_page(
            2, self.payload(2), leaf_digest=other_leaf.digest(),
        )
        with self.assertRaises(MathPageFileConflictError):
            self.provider.verify_page_map(self.store)
        self.assertEqual(
            self.provider.read_page_record(record0), self.data,
        )

    def test_page_data_must_be_exactly_one_32_kib_page(self):
        leaf_digest = self.leaf.digest()
        for length in (0, 1, PAGE_FILE_BYTES - 1, PAGE_FILE_BYTES + 1):
            with self.assertRaises(MathPageFileSizeError):
                self.provider.write_page(
                    0, b"\x00" * length, leaf_digest=leaf_digest,
                )
        for bad in ("x" * PAGE_FILE_BYTES, 123, None):
            with self.assertRaises(MathPageFileError):
                self.provider.write_page(
                    0, bad, leaf_digest=leaf_digest,
                )
        self.assertEqual(self.provider.list_page_files(), [])

        published = self.provider.write_page(
            0, memoryview(self.data), leaf_digest=leaf_digest,
        )
        self.assertEqual(
            self.provider.read_page(
                0, published["content_digest"], leaf_digest=leaf_digest,
            ),
            self.data,
        )


if __name__ == "__main__":
    unittest.main()
