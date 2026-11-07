import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.gen_ring_csr import (
    DEFAULT_OUT,
    DIGEST_METHOD,
    NANNET_PORT_POSITION,
    PAGE_SIZE_BYTES,
    UNIVERSE_SIZE_BYTES,
    VERSION,
    build_document,
    canonical_json_bytes,
    compute_digest,
    render_document,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "spec" / "ring-255.json"
SCRIPT_PATH = REPO_ROOT / "tools" / "gen_ring_csr.py"


class RingCSRTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec_text = SPEC_PATH.read_text(encoding="utf-8")
        cls.document = json.loads(cls.spec_text)
        cls.row_offsets = cls.document["row_offsets"]
        cls.neighbors = cls.document["neighbors"]

    def rows(self):
        for head in range(255):
            start = self.row_offsets[head]
            stop = self.row_offsets[head + 1]
            yield head, self.neighbors[start:stop]

    def test_version_and_counts_are_stable(self):
        self.assertEqual(self.document["version"], VERSION)
        counts = self.document["counts"]
        self.assertEqual(counts["head_count"], 255)
        self.assertEqual(counts["head_index_min"], 0)
        self.assertEqual(counts["head_index_max"], 254)
        self.assertEqual(counts["ring_position_count"], 256)
        self.assertEqual(counts["nannet_port_count"], 1)
        self.assertEqual(counts["nannet_port_position"], 255)
        self.assertEqual(counts["csr_row_count"], 255)
        self.assertEqual(counts["row_offset_count"], 256)
        self.assertEqual(counts["directed_edge_count"], 510)
        self.assertEqual(counts["neighbor_count"], 510)
        self.assertEqual(counts["undirected_edge_count"], 255)
        self.assertEqual(counts["port_coupling_count"], 1)
        self.assertEqual(counts["page_count"], 256)
        self.assertEqual(counts["page_size_bytes"], 32768)
        self.assertEqual(counts["universe_size_bytes"], 8 * 1024 * 1024)

    def test_255_heads_and_256_ring_positions(self):
        positions = self.document["ring_positions"]
        self.assertEqual(len(positions), 256)
        self.assertEqual(
            [position["position"] for position in positions], list(range(256))
        )

        head_positions = [
            position for position in positions if position["kind"] == "head"
        ]
        self.assertEqual(len(head_positions), 255)
        for position in head_positions:
            self.assertEqual(position["head"], position["position"])
            self.assertLessEqual(position["head"], 254)

        port = positions[NANNET_PORT_POSITION]
        self.assertEqual(port["position"], 255)
        self.assertEqual(port["kind"], "nannet_port")
        self.assertIsNone(port["head"])
        self.assertNotIn(255, self.neighbors)
        self.assertLess(
            max(position["head"] for position in head_positions), 255
        )

    def test_510_directed_entries_and_degree_two_rows(self):
        self.assertEqual(len(self.neighbors), 510)
        self.assertEqual(len(self.row_offsets), 256)
        self.assertEqual(self.row_offsets[0], 0)
        self.assertEqual(self.row_offsets[-1], 510)
        self.assertEqual(
            self.row_offsets, [2 * head for head in range(256)]
        )
        self.assertEqual(
            self.row_offsets,
            sorted(self.row_offsets),
            "row offsets must be monotone nondecreasing",
        )

        for head, row in self.rows():
            with self.subTest(head=head):
                self.assertEqual(len(row), 2)
                self.assertEqual(
                    self.row_offsets[head + 1] - self.row_offsets[head], 2
                )
                self.assertEqual(row, sorted(row))
                self.assertEqual(len(set(row)), 2)
                self.assertTrue(all(0 <= neighbor < 255 for neighbor in row))
                expected = sorted({(head - 1) % 255, (head + 1) % 255})
                self.assertEqual(row, expected)

    def test_cycle_is_symmetric_and_has_no_self_loops(self):
        adjacency = [set(row) for _, row in self.rows()]
        for head, row in enumerate(adjacency):
            with self.subTest(head=head):
                self.assertNotIn(head, row)
                for neighbor in row:
                    self.assertIn(head, adjacency[neighbor])

        # The exact undirected edge set is C255: (i, (i + 1) mod 255).
        undirected = {
            tuple(sorted((head, neighbor)))
            for head, row in enumerate(adjacency)
            for neighbor in row
        }
        expected_edges = {
            tuple(sorted((head, (head + 1) % 255))) for head in range(255)
        }
        self.assertEqual(undirected, expected_edges)
        self.assertEqual(len(undirected), 255)

    def test_nannet_port_is_position_255_and_not_a_head(self):
        self.assertEqual(NANNET_PORT_POSITION, 255)
        self.assertEqual(len(self.document["port_couplings"]), 1)

        coupling = self.document["port_couplings"][0]
        self.assertEqual(coupling["port_position"], 255)
        self.assertEqual(coupling["head"], 0)
        self.assertEqual(coupling["weight"], 1.0)

        policy = self.document["port_policy"]
        self.assertEqual(
            policy["version"], "nanrouter.nannet-port-coupling.v1"
        )
        self.assertEqual(policy["attachment_head"], 0)
        self.assertEqual(policy["weight"], 1.0)

        self.assertEqual(self.document["counts"]["head_index_max"], 254)
        head_positions = [
            position
            for position in self.document["ring_positions"]
            if position["kind"] == "head"
        ]
        self.assertNotIn(255, [position["head"] for position in head_positions])

    def test_page_map_is_256_pages_of_32_kib(self):
        pages = self.document["page_map"]
        self.assertEqual(len(pages), 256)
        self.assertEqual(PAGE_SIZE_BYTES, 32768)
        self.assertEqual(UNIVERSE_SIZE_BYTES, 8 * 1024 * 1024)
        self.assertEqual(UNIVERSE_SIZE_BYTES, 256 * PAGE_SIZE_BYTES)

        for index, page in enumerate(pages):
            with self.subTest(page=index):
                self.assertEqual(page["page"], index)
                self.assertEqual(page["size_bytes"], 32768)
                self.assertEqual(page["offset_bytes"], index * 32768)
                if index < 255:
                    self.assertEqual(page["kind"], "head")
                    self.assertEqual(page["head"], index)
                else:
                    self.assertEqual(page["kind"], "nannet_port")
                    self.assertIsNone(page["head"])

        self.assertEqual(
            {page["page"] for page in pages}, set(range(256))
        )
        self.assertEqual(
            sum(page["size_bytes"] for page in pages), 8 * 1024 * 1024
        )
        self.assertEqual(
            pages[255]["offset_bytes"] + pages[255]["size_bytes"],
            8 * 1024 * 1024,
        )

    def test_digest_matches_documented_canonical_json(self):
        digest = self.document["digest"]
        self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", digest))
        self.assertEqual(digest, compute_digest(self.document))

        payload = dict(self.document)
        payload.pop("digest")
        expected = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(digest, expected)
        self.assertEqual(
            canonical_json_bytes(self.document),
            canonical_json_bytes(payload),
        )
        self.assertNotIn("digest", json.loads(canonical_json_bytes(payload)))
        self.assertEqual(
            self.document["digest_method"], dict(DIGEST_METHOD)
        )

    def test_deterministic_regeneration_equals_checked_in_file(self):
        regenerated = render_document()
        self.assertEqual(regenerated, self.spec_text)
        self.assertTrue(regenerated.endswith("\n"))
        self.assertEqual(build_document(), self.document)

    def test_cli_generates_identical_output_with_out_path(self):
        self.assertEqual(DEFAULT_OUT.resolve(), SPEC_PATH.resolve())
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "ring-a.json"
            second = Path(tmp) / "nested" / "ring-b.json"
            for path in (first, second):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT_PATH),
                        "--out",
                        str(path),
                    ],
                    cwd=REPO_ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self.assertIn("digest=", result.stdout)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(
                first.read_text(encoding="utf-8"), self.spec_text
            )


if __name__ == "__main__":
    unittest.main()
