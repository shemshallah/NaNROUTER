"""Bounded corpus-to-mirror mapping: stable ids, provenance, no math claims."""
import hashlib
import io
import json
import math
from pathlib import Path
import tempfile
import unittest

from runner_riddle.mirror_corpus_mapper import (
    CONCEPT_DOMAIN, MAX_LINE_BYTES, MAX_ROWS, MAX_TEXT_CHARS, PAIR_ID_FORMULA,
    PAIR_ID_MAX, PAIR_ID_MIN, SCHEMA, CorpusBoundError, CorpusMapperError,
    CorpusMirrorMapper, CorpusRowError, concept_alias, concept_digest,
    concept_head, concept_id, concept_mirror, decode_pair_id, fnv_head,
    map_concept,
    normalize_text, pair_heads, pair_id, prepare_batch, prepare_jsonl,
    prepare_records, read_jsonl, reverse8, status,
)


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def all_lists(value):
    """Yield every list nested inside JSON-safe output."""
    if isinstance(value, list):
        yield value
        for item in value:
            yield from all_lists(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from all_lists(item)


def all_numbers(value):
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from all_numbers(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from all_numbers(item)


class NormalizeAndIdentityTests(unittest.TestCase):
    def test_normalize_is_nfkc_whitespace_and_case_preserving(self):
        self.assertEqual(normalize_text("  A \t  Ｃａｔ\n"), "A Cat")
        self.assertEqual(normalize_text("\u212b  tree"), "\u00c5 tree")
        self.assertEqual(normalize_text(None), "")
        with self.assertRaises(CorpusMapperError):
            normalize_text(7)

    def test_concept_id_is_domain_separated_sha256_and_case_folded(self):
        digest = hashlib.sha256(CONCEPT_DOMAIN + b"cat").hexdigest()
        self.assertEqual(concept_id(" CAT "), digest)
        self.assertEqual(concept_id("Ｃａｔ"), digest)
        self.assertEqual(concept_id("cat"), digest)
        self.assertEqual(concept_alias("cat"), "concept:" + digest[:32])
        self.assertNotEqual(concept_id("cat"), concept_id("cats"))
        self.assertEqual(len(concept_digest("cat")), 64)
        self.assertRegex(concept_digest("cat"), r"^[0-9a-f]{64}$")
        with self.assertRaises(CorpusMapperError):
            concept_id("   ")

    def test_no_python_hash_and_map_concept_shape(self):
        first = map_concept("Bird")
        second = map_concept("  bird ")
        self.assertEqual(first["concept_id"], second["concept_id"])
        self.assertEqual(first["identity"], second["identity"])
        self.assertEqual(first["head"], second["head"])
        self.assertEqual(first["head"], fnv_head("bird"))
        self.assertEqual(first["mirror_head"], reverse8(first["head"]))
        self.assertEqual(first["concept_id"], concept_id("bird"))
        self.assertEqual(first["concept_alias"], concept_alias("bird"))
        self.assertEqual(first["head_pair_id"], pair_id(0, first["head"]))
        self.assertTrue(first["host_only"])
        self.assertFalse(first["native_execution"])
        self.assertFalse(first["training_performed"])


class HeadAndPairTests(unittest.TestCase):
    def test_fnv_head_reverse_and_bounds(self):
        self.assertEqual(fnv_head("cat"), 7)
        self.assertEqual(concept_head("cat"), 7)
        self.assertEqual(concept_mirror("cat"), reverse8(7))
        self.assertEqual(reverse8(0), 0)
        self.assertEqual(reverse8(1), 128)
        self.assertEqual(reverse8(255), 255)
        for term in ("", " "):
            with self.subTest(term=term):
                with self.assertRaises(CorpusMapperError):
                    fnv_head(term)
        for bad in (-1, 256, True, 1.0, "1"):
            with self.subTest(bad=bad):
                with self.assertRaises(CorpusMapperError):
                    reverse8(bad)

    def test_pair_formula_endpoints_and_exhaustive_roundtrip(self):
        self.assertEqual(PAIR_ID_FORMULA,
                         "1 + a*(511-a)/2 + (b-a-1) for 0 <= a < b <= 255")
        self.assertEqual(pair_id(0, 1), 1)
        self.assertEqual(pair_id(1, 0), 1)
        self.assertEqual(pair_id(0, 255), 255)
        self.assertEqual(pair_id(1, 2), 256)
        self.assertEqual(pair_id(254, 255), PAIR_ID_MAX)
        self.assertEqual(PAIR_ID_MIN, 1)
        self.assertEqual(PAIR_ID_MAX, 32640)
        seen = set()
        for a in range(256):
            for b in range(a + 1, 256):
                value = pair_id(a, b)
                self.assertEqual(value, 1 + a * (511 - a) // 2 + (b - a - 1))
                self.assertEqual(pair_id(b, a), value)
                self.assertNotIn(value, seen)
                seen.add(value)
                self.assertEqual(decode_pair_id(value), (a, b))
                self.assertEqual(pair_heads(value), (a, b))
        self.assertEqual(len(seen), PAIR_ID_MAX)
        self.assertIsNone(decode_pair_id(0, allow_void=True))
        for bad in (0, -1, 32641, True, 1.0, "1"):
            with self.subTest(bad=bad):
                with self.assertRaises(CorpusMapperError):
                    decode_pair_id(bad)
        with self.assertRaises(CorpusMapperError):
            pair_id(7, 7)


class JsonlReadTests(unittest.TestCase):
    def test_reads_path_and_iterable_with_blank_lines(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "corpus.jsonl"
        path.write_text(
            '{"text":"first row"}\n\n{"text":"second row"}\n', encoding="utf-8")
        rows = read_jsonl(path)
        self.assertEqual([row["text"] for row in rows],
                         ["first row", "second row"])
        self.assertEqual(read_jsonl(io.StringIO('{"text":"stream row"}\n')),
                         [{"text": "stream row"}])
        self.assertEqual(read_jsonl(['{"text":"line row"}']),
                         [{"text": "line row"}])

    def test_malformed_json_non_object_and_duplicate_keys_rejected(self):
        cases = [
            ('{bad json}\n', CorpusRowError),
            ('[1, 2, 3]\n', CorpusRowError),
            ('"text"\n', CorpusRowError),
            ('{"text":"aa","text":"bb"}\n', CorpusRowError),
        ]
        for payload, error in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(error):
                    read_jsonl(io.StringIO(payload))

    def test_bounded_rows_lines_and_invalid_bounds_rejected(self):
        two = '{"text":"aa"}\n{"text":"bb"}\n'
        with self.assertRaises(CorpusBoundError):
            read_jsonl(io.StringIO(two), max_rows=1)
        with self.assertRaises(CorpusBoundError):
            read_jsonl(io.StringIO('{"text":"aa"}\n'), max_line_bytes=4)
        for value in (0, -1, MAX_ROWS + 1, True, 1.0):
            with self.subTest(value=value):
                with self.assertRaises(CorpusBoundError):
                    read_jsonl([], max_rows=value)
        with self.assertRaises(CorpusBoundError):
            read_jsonl([], max_line_bytes=MAX_LINE_BYTES + 1)


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {
                "text": "The quick brown fox.",
                "split": "train",
                "source_digest": "A" * 64,
                "synset": "fox.n.01",
                "lexfile": "noun.animal",
                "confidence": 0.9,
                "polarity": 0,
            },
            {
                "text": "cats are animals",
                "subject": "cats",
                "predicate": "are",
                "object": "animals",
                "split": "validation",
                "source": "unit-fixture",
                "provenance": {"fixture": "synthetic"},
                "confidence": 0.8,
                "polarity": "supports",
            },
            {
                "text": "birds can fly",
                "subject": "birds",
                "predicate": "can",
                "object": "fly",
                "polarity": "refutes",
                "confidence": 0.4,
                "synset": "bird.n.01",
            },
            {
                "text": "an incomplete relation",
                "subject": "dogs",
                "predicate": "like",
            },
            {
                "text": "cats are animals",
                "subject": "cats",
                "predicate": "are",
                "object": "animals",
                "split": "validation",
                "source": "unit-fixture",
                "provenance": {"fixture": "synthetic"},
                "confidence": 0.8,
                "polarity": "supports",
            },
        ]

    def test_emits_leaves_relations_and_observations(self):
        batch = prepare_batch(self.rows)
        self.assertEqual(batch["schema"], SCHEMA)
        self.assertEqual(batch["counts"]["rows"], len(self.rows))
        self.assertEqual(batch["counts"]["relations"], 2)
        self.assertEqual(len(batch["relations"]), 2)
        self.assertGreaterEqual(len(batch["leaves"]), 8)
        self.assertEqual(len(batch["observations"]), 2)
        self.assertEqual(batch["cycle_candidates"], [])

        relation = next(item for item in batch["relations"]
                        if item["subject"] == "cats")
        self.assertEqual(relation["subject_head"], fnv_head("cats"))
        self.assertEqual(relation["object_head"], fnv_head("animals"))
        self.assertEqual(relation["pair_id"], pair_id(fnv_head("cats"),
                                                       fnv_head("animals")))
        self.assertEqual(relation["polarity"], "supports")
        self.assertEqual(relation["polarity_value"], 1)
        self.assertEqual(relation["confidence"], 0.8)
        self.assertEqual(relation["split"], "validation")
        self.assertEqual(relation["provenance"]["source"], "unit-fixture")
        self.assertEqual(relation["provenance"]["input"],
                         {"fixture": "synthetic"})

        neutral = next(item for item in batch["observations"]
                       if item["text"] == "The quick brown fox.")
        self.assertEqual(neutral["relation_status"], "absent")
        self.assertEqual(neutral["polarity"], "neutral")
        self.assertEqual(neutral["split"], "train")
        self.assertEqual(neutral["synset"], "fox.n.01")
        self.assertEqual(neutral["lexfile"], "noun.animal")

    def test_incomplete_relation_is_observation_without_invention(self):
        batch = prepare_batch([self.rows[3]])
        self.assertEqual(batch["relations"], [])
        self.assertEqual(len(batch["observations"]), 1)
        observation = batch["observations"][0]
        self.assertEqual(observation["relation_status"], "incomplete")
        self.assertEqual(sorted(observation["parts"]), ["predicate", "subject"])
        self.assertEqual(observation["parts"]["subject"]["text"], "dogs")
        self.assertEqual(observation["part_texts"]["subject"], "dogs")
        self.assertEqual(observation["missing_relation_fields"], ["object"])
        self.assertNotIn("object", observation["parts"])
        self.assertNotIn("object", observation["part_texts"])
        self.assertNotIn("object", observation)
        self.assertEqual(observation["subject"], "dogs")
        self.assertEqual(observation["predicate"], "like")
        self.assertTrue(observation["observation"])

    def test_complete_neutral_relation_is_retained(self):
        batch = prepare_batch([{
            "text": "cats maybe animals",
            "subject": "cats",
            "predicate": "maybe",
            "object": "animals",
            "polarity": 0,
        }])
        self.assertEqual(len(batch["relations"]), 1)
        relation = batch["relations"][0]
        self.assertEqual(relation["polarity"], "neutral")
        self.assertEqual(relation["polarity_value"], 0)
        self.assertEqual(batch["counts"]["neutral_relations"], 1)

    def test_ids_are_stable_across_case_and_whitespace(self):
        first = prepare_records([{"text": "  Red   Apple "}])
        second = prepare_records([{"text": "red apple"}])
        self.assertEqual(first[0]["concept_id"], second[0]["concept_id"])
        self.assertEqual(first[0]["leaf_id"], second[0]["leaf_id"])
        self.assertEqual(first[0]["head"], second[0]["head"])
        self.assertEqual(first[0]["source_digest"], second[0]["source_digest"])
        self.assertEqual(first[0]["concept_id"], concept_id("red apple"))
        self.assertEqual(first[0]["leaf_id"], concept_alias("red apple"))
        self.assertEqual(first[0]["head"], fnv_head("red apple"))

    def test_explicit_and_derived_source_digests_and_provenance(self):
        batch = prepare_batch(self.rows[:1])
        leaf = batch["leaves"][0]
        self.assertEqual(leaf["source_digest"], "a" * 64)
        self.assertEqual(leaf["provenance"]["source_digest"], "a" * 64)
        self.assertEqual(leaf["provenance"]["jsonl_lines"], [1])
        self.assertFalse(leaf["provenance"].get("source_digest_derived", False))

        derived_one = prepare_batch([{"text": "derived source"}])["leaves"][0]
        derived_two = prepare_batch([{"text": "  derived   source "}])["leaves"][0]
        self.assertEqual(derived_one["source_digest"],
                         derived_two["source_digest"])
        self.assertRegex(derived_one["source_digest"], r"^[0-9a-f]{64}$")
        self.assertTrue(
            derived_one["provenance"]["source_digest_derived"])

        batch = prepare_batch(self.rows[1:2])
        for record in batch["records"]:
            self.assertEqual(record["source_digest"],
                             record["provenance"]["source_digest"])
            self.assertRegex(record["source_digest"], r"^[0-9a-f]{64}$")
            self.assertEqual(record["provenance"]["jsonl_lines"], [1])

    def test_duplicate_rows_deduplicate_idempotently(self):
        first = prepare_records(self.rows)
        second = prepare_records(self.rows)
        self.assertEqual(first, second)
        self.assertEqual(
            prepare_batch(self.rows)["records_sha256"],
            prepare_batch(self.rows)["records_sha256"])

        duplicate = [
            self.rows[1],
            {"text": "unrelated observation"},
            self.rows[1],
        ]
        batch = prepare_batch(duplicate)
        relations = [item for item in batch["relations"]
                     if item["subject"] == "cats"]
        self.assertEqual(len(relations), 1)
        relation = relations[0]
        self.assertEqual(relation["occurrences"], 2)
        self.assertEqual(relation["provenance"]["jsonl_lines"], [1, 3])
        self.assertEqual(batch["counts"]["duplicate_occurrences"], 5)

    def test_relation_identity_changes_with_polarity_or_confidence(self):
        base = {
            "text": "cats are animals", "subject": "cats",
            "predicate": "are", "object": "animals",
        }
        ids = {
            prepare_batch([dict(base)])["relations"][0]["relation_id"],
            prepare_batch([dict(base, polarity=1)])["relations"][0]["relation_id"],
            prepare_batch([dict(base, polarity=-1)])["relations"][0]["relation_id"],
            prepare_batch([dict(base, confidence=0.25)])["relations"][0]["relation_id"],
        }
        self.assertEqual(len(ids), 4)
        self.assertTrue(all(value.startswith("rel:")
                            for value in ids))


class CycleCandidateTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            "text": "cats chase dogs",
            "subject": "cats",
            "predicate": "chase",
            "object": "dogs",
            "source_digest": "b" * 64,
            "polarity": "supports",
            "confidence": 0.75,
        }

    def test_optional_cycle_has_formula_metadata_and_pair_ids(self):
        without = prepare_batch([self.row])
        self.assertEqual(without["cycle_candidates"], [])

        alias_batch = prepare_batch([self.row], include_cycles=True)
        self.assertEqual(len(alias_batch["cycle_candidates"]), 1)

        batch = prepare_batch([self.row], cycle_candidates=True)
        self.assertEqual(len(batch["cycle_candidates"]), 1)
        cycle = batch["cycle_candidates"][0]
        i = fnv_head("cats")
        j = fnv_head("dogs")
        self.assertEqual(i, 156)
        self.assertEqual(j, 14)
        self.assertEqual(cycle["reference_head"], 0)
        self.assertEqual(cycle["heads"], [i, j])
        self.assertEqual(cycle["pair_ids"], [
            pair_id(0, i), pair_id(i, j), pair_id(0, j),
        ])
        self.assertEqual([entry["pair_id"] for entry in cycle["pairs"]],
                         cycle["pair_ids"])
        self.assertEqual(cycle["F_ij"]["formula"],
                         "anti(0,i) + anti(i,j) - anti(0,j)")
        self.assertEqual(cycle["F_ij"]["anti_formula"],
                         "0.5 * (w(i,j) - w(j,i))")
        self.assertFalse(cycle["F_ij"]["evaluated"])
        self.assertIsNone(cycle["F_ij"]["value"])
        self.assertTrue(cycle["formula_metadata_only"])
        self.assertFalse(cycle["host_math_performed"])
        self.assertFalse(cycle["native_execution"])
        self.assertFalse(cycle["training_performed"])
        self.assertFalse(cycle["learned"])
        self.assertEqual(cycle["source_digest"], "b" * 64)

    def test_same_head_or_reference_endpoint_cycle_is_not_invented(self):
        same = dict(self.row, subject="cats", object="cats",
                    text="cats chase cats")
        batch = prepare_batch([same], cycle_candidates=True)
        self.assertEqual(len(batch["relations"]), 1)
        self.assertEqual(batch["cycle_candidates"], [])
        self.assertEqual(batch["relations"][0]["pair_status"], "same_head")
        self.assertIsNone(batch["relations"][0]["pair_id"])

    def test_duplicate_cycles_deduplicate(self):
        batch = prepare_batch([self.row, self.row], cycle_candidates=True)
        self.assertEqual(len(batch["cycle_candidates"]), 1)
        cycle = batch["cycle_candidates"][0]
        self.assertEqual(cycle["occurrences"], 2)
        self.assertEqual(cycle["provenance"]["jsonl_lines"], [1, 2])


class RejectionTests(unittest.TestCase):
    def assert_bad_row(self, row, error=CorpusRowError):
        with self.assertRaises(error):
            prepare_records([row])

    def test_missing_or_bad_text_rejected(self):
        for row in ({}, {"text": None}, {"text": 7}, {"text": ""},
                    {"text": "a"}):
            with self.subTest(row=row):
                self.assert_bad_row(row)
        self.assert_bad_row({"text": "a" * (MAX_TEXT_CHARS + 1)})
        with self.assertRaises(CorpusRowError):
            prepare_records([{"text": "abcdef"}], max_text_chars=5)

    def test_bad_optional_fields_rejected(self):
        base = {"text": "valid text"}
        cases = [
            dict(base, source_digest="short"),
            dict(base, source_digest=7),
            dict(base, confidence=1.5),
            dict(base, confidence=True),
            dict(base, confidence="0.5"),
            dict(base, confidence=float("nan")),
            dict(base, polarity="maybe"),
            dict(base, polarity=True),
            dict(base, polarity=2),
            dict(base, split="bogus"),
            dict(base, split=3),
            dict(base, synset=7),
            dict(base, lexfile=["noun"]),
            dict(base, provenance="not an object"),
            {"text": "valid text", "subject": 7},
        ]
        for row in cases:
            with self.subTest(row=row):
                self.assert_bad_row(row)

    def test_non_object_and_batch_bound_rejected(self):
        with self.assertRaises(CorpusRowError):
            prepare_records([["not", "an", "object"]])
        with self.assertRaises(CorpusMapperError):
            prepare_records("a string is not a row iterable")
        with self.assertRaises(CorpusBoundError):
            prepare_records([{"text": "one"}, {"text": "two"}], max_rows=1)
        for value in (0, -1, MAX_ROWS + 1, True):
            with self.subTest(value=value):
                with self.assertRaises(CorpusBoundError):
                    prepare_records([], max_rows=value)

    def test_invalid_rows_are_rejected_not_silently_invented(self):
        with self.assertRaises(CorpusRowError):
            prepare_jsonl(io.StringIO(
                '{"text":"first"}\n{"text":""}\n'))
        with self.assertRaises(CorpusRowError):
            prepare_jsonl(io.StringIO('{"text":"first"}\nnot json\n'))

    def test_mapper_class_applies_its_bounds(self):
        mapper = CorpusMirrorMapper(max_rows=1)
        with self.assertRaises(CorpusBoundError):
            mapper.prepare([{"text": "one"}, {"text": "two"}])
        self.assertEqual(len(mapper.prepare([{"text": "one"}])["records"]), 1)
        with self.assertRaises(CorpusBoundError):
            CorpusMirrorMapper(max_rows=0)
        with self.assertRaises(CorpusBoundError):
            CorpusMirrorMapper(max_text_chars=MAX_TEXT_CHARS + 1)


class JsonSafetyAndBoundaryTests(unittest.TestCase):
    def rows(self):
        return [
            {"text": "alpha observation", "provenance": {
                "nan": float("nan"), "inf": float("inf"),
                "blob": b"\x00\xff", "nested": [1, 2.5, None],
            }},
            {"text": "alpha relates beta", "subject": "alpha",
             "predicate": "relates", "object": "beta",
             "polarity": 1, "confidence": 0.5},
        ]

    def test_output_is_json_safe_and_contains_no_dense_matrix(self):
        batch = prepare_batch(self.rows(), cycle_candidates=True)
        encoded = json.dumps(batch, allow_nan=False, sort_keys=True)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["counts"], batch["counts"])
        for number in all_numbers(batch):
            self.assertTrue(math.isfinite(number))
        self.assertLessEqual(max(len(item) for item in all_lists(batch)), 8)
        self.assertTrue(batch["matrix_free"])
        self.assertEqual(batch["dense_matrices_allocated"], 0)
        self.assertFalse(batch["db_writes"])
        self.assertFalse(batch["native_execution"])
        self.assertFalse(batch["training_performed"])
        self.assertFalse(batch["learning_claimed"])
        self.assertEqual(len(batch["records_sha256"]), 64)
        self.assertRegex(batch["records_sha256"], r"^[0-9a-f]{64}$")

    def test_status_reports_host_only_and_no_learning(self):
        info = status()
        self.assertTrue(info["matrix_free"])
        self.assertEqual(info["dense_matrices_allocated"], 0)
        self.assertTrue(info["host_only"])
        self.assertFalse(info["db_writes"])
        self.assertFalse(info["native_execution"])
        self.assertFalse(info["training_performed"])
        self.assertFalse(info["learning_claimed"])
        self.assertEqual(info["heads"], 256)
        self.assertEqual(info["pair_count"], 32640)
        self.assertEqual(info["reference_head"], 0)
        self.assertIn("anti(0,i)", info["cycle_formula"])

    def test_every_record_has_provenance_and_digest(self):
        batch = prepare_batch(self.rows(), cycle_candidates=True)
        self.assertGreater(len(batch["records"]), 0)
        for record in batch["records"]:
            self.assertIn("source_digest", record)
            self.assertRegex(record["source_digest"], r"^[0-9a-f]{64}$")
            self.assertEqual(record["source_digest"],
                             record["provenance"]["source_digest"])
            self.assertTrue(record["provenance"]["jsonl_lines"])
            self.assertFalse(record["db_write"])
            self.assertFalse(record["native_execution"])
        relation = batch["relations"][0]
        for key in ("subject", "predicate", "object"):
            self.assertEqual(relation[key],
                             relation[key + "_identity"] or relation[key])
        self.assertNotIn(None, relation["pair_ids"])


if __name__ == "__main__":
    unittest.main()
