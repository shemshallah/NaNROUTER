"""Pinned HW4 release restoration: offline digest and path security checks."""
from __future__ import annotations
import hashlib
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from runner_riddle.hw4_full_dict import install, verify
from runner_riddle.hw4_release_bootstrap import HW4BootstrapError, bootstrap
from tests.test_hw4_full_dict import DATA


class HW4ReleaseBootstrapTests(unittest.TestCase):
    def test_offline_pinned_release_roundtrip_and_restart(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "wn3.1.dict.zip"
            with ZipFile(source, "w") as z:
                for name, body in DATA.items():
                    z.writestr("wn3.1.dict/dict/" + name, body)
            reference = base / "hw4-full-reference"
            install(source, reference)
            bundle = base / "release.tar.gz"
            with tarfile.open(bundle, "w:gz") as tar:
                tar.add(reference, arcname="hw4-full-reference")
            digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
            output = base / "mc0db" / "hw4-wordnet31"
            with patch("runner_riddle.hw4_release_bootstrap.ARCHIVE_SHA256", digest):
                result = bootstrap(output, archive_path=bundle)
                self.assertFalse(result["reused"])
                self.assertEqual(verify(output)["pointers"], 6)
                self.assertTrue(bootstrap(output, archive_path=bundle)["reused"])
                self.assertEqual(verify(output)["root_bytes"], 8388608)

    def test_wrong_archive_digest_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            bundle = base / "wrong.tar.gz"
            bundle.write_bytes(b"untrusted")
            with self.assertRaisesRegex(HW4BootstrapError, "digest mismatch"):
                bootstrap(base / "mc0db" / "hw4", archive_path=bundle)

    def test_traversal_member_rejected_after_matching_pinned_digest(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            bundle = base / "evil.tar.gz"
            with tarfile.open(bundle, "w:gz") as tar:
                member = tarfile.TarInfo("hw4-full-reference/../../escape")
                member.size = 0
                tar.addfile(member)
            digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
            with patch("runner_riddle.hw4_release_bootstrap.ARCHIVE_SHA256", digest):
                with self.assertRaisesRegex(HW4BootstrapError, "invalid path"):
                    bootstrap(base / "mc0db" / "hw4", archive_path=bundle)
            self.assertFalse((base / "escape").exists())

    def test_disallow_bs0db_owner(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(HW4BootstrapError, "BS0DB"):
                bootstrap(Path(td) / "bs0db" / "hw4")


if __name__ == "__main__":
    unittest.main()
