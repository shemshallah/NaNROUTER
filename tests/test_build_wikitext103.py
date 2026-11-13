"""Offline tests for the WikiText-103 corpus builder."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_wikitext103.py"
SPEC = importlib.util.spec_from_file_location("build_wikitext103", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import machinery
    raise ImportError(f"cannot import {SCRIPT}")
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


class RegistryTests(unittest.TestCase):
    def test_registry_is_valid(self) -> None:
        builder.check_registry()

    def test_release_tags_are_unique(self) -> None:
        tags = [spec["release_tag"] for spec in builder.VARIANTS.values()]
        self.assertEqual(len(tags), len(set(tags)))
        self.assertIn("wikitext103", tags)
        self.assertIn("wikitext103-tokenized", tags)

    def test_split_names_match_extensions(self) -> None:
        for name, spec in builder.VARIANTS.items():
            for split in builder.SPLIT_ORDER:
                meta = spec["splits"][split]
                self.assertEqual(
                    meta["file"],
                    f"{builder.SPLIT_STEMS[split]}{spec['extension']}",
                    name,
                )

    def test_expected_totals(self) -> None:
        expected = {
            "raw": (543_005_627, 1_809_468, 101_880_768),
            "tokenized": (541_632_543, 1_809_468, 101_880_768),
        }
        for name, spec in builder.VARIANTS.items():
            totals = (
                sum(meta["bytes"] for meta in spec["splits"].values()),
                sum(meta["lines"] for meta in spec["splits"].values()),
                sum(meta["words"] for meta in spec["splits"].values()),
            )
            self.assertEqual(totals, expected[name], name)

    def test_archive_checksums_have_published_lengths(self) -> None:
        for name, spec in builder.VARIANTS.items():
            self.assertEqual(len(spec["archive_sha1"]), 40, name)
            self.assertEqual(len(spec["archive_sha256"]), 64, name)
            for url in spec["urls"]:
                self.assertTrue(url.endswith(spec["archive"]), name)


if __name__ == "__main__":
    unittest.main()
