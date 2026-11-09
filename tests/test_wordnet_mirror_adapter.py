"""Host-only WordNet HW4 -> mirror-memory adapter tests."""
import hashlib
import unittest

from runner_riddle.wordnet_mirror_adapter import (
    CANONICAL_ROUTE, HEAD_COUNT, PAIR_COUNT, PAIR_ID_MAX, PAIR_ID_MIN,
    ROUTE, SCHEMA, WORDNET_ROUTE, WordNetMirrorAdapter,
    WordNetMirrorError, adapt_row, adapt_rows, concept_id, cycle_metadata,
    decode_pair_id, head_for_key, pair_heads, pair_id, relation_type,
    relation_type_id, stable_key,
)


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


class CanonicalRouteTests(unittest.TestCase):
    def test_route_is_the_reserved_wordnet_hw4_route(self):
        expected = "nan://GM0:SC0:MC0:BS0:0:HW4:0"
        self.assertEqual(CANONICAL_ROUTE, expected)
        self.assertEqual(ROUTE, expected)
        self.assertEqual(WORDNET_ROUTE, expected)
        self.assertEqual(SCHEMA, "nanrouter.wordnet-mirror-adapter/1")

    def test_every_emitted_record_carries_the_one_canonical_route(self):
        adapter = WordNetMirrorAdapter()
        leaf = adapter.map_synset("02084071-n", lemma="dog%1:05:00::")
        relation = adapter.map_relation(
            "synset:02084071-n", "synset:02084072-n", "hypernym")
        for record in (leaf, relation,
                       *adapter.concepts(), *adapter.records()):
            self.assertEqual(record["route"], CANONICAL_ROUTE)

    def test_host_only_non_promotion_flags(self):
        status = WordNetMirrorAdapter().status()
        self.assertTrue(status["host_only"])
        self.assertFalse(status["writes_database"])
        self.assertFalse(status["executes_math"])
        self.assertFalse(status["canonical_promotion"])
        self.assertFalse(status["llm_fallback"])


class StableMappingTests(unittest.TestCase):
    def test_stable_key_and_concept_head_are_deterministic(self):
        for key, kind in (("02084071-n", "synset"),
                          ("dog%1:05:00::", "lemma")):
            first = stable_key(key, kind)
            second = stable_key(key, kind)
            self.assertEqual(first, second)
            self.assertEqual(concept_id(key, kind), concept_id(key, kind))
            head = head_for_key(key, kind)
            self.assertGreaterEqual(head, 0)
            self.assertLessEqual(head, HEAD_COUNT - 1)
            self.assertEqual(head, concept_id(key, kind) % HEAD_COUNT)

    def test_namespaced_spelling_and_bare_synset_default(self):
        self.assertEqual(stable_key("synset:02084071-n"), "synset:02084071-n")
        self.assertEqual(stable_key("lemma:dog"), "lemma:dog")
        self.assertEqual(stable_key("02084071-n"), "synset:02084071-n")
        self.assertEqual(stable_key("dog", "lemma"), "lemma:dog")
        self.assertNotEqual(concept_id("same", "synset"),
                            concept_id("same", "lemma"))

    def test_same_key_maps_to_same_concept_across_adapter_instances(self):
        one = WordNetMirrorAdapter()
        two = WordNetMirrorAdapter()
        a = one.register_synset("02084071-n")
        b = two.register_synset("02084071-n")
        self.assertEqual(a, b)
        self.assertEqual(a["concept_id"], concept_id("02084071-n", "synset"))
        self.assertEqual(a["head"], head_for_key("02084071-n", "synset"))


class PairIdBoundaryTests(unittest.TestCase):
    def test_formula_boundaries_are_one_based(self):
        self.assertEqual(pair_id(0, 1), PAIR_ID_MIN)
        self.assertEqual(pair_id(0, 1), 1 + 0 * 511 // 2 + (1 - 0 - 1))
        self.assertEqual(pair_id(254, 255), PAIR_ID_MAX)
        self.assertEqual(pair_id(254, 255),
                         1 + 254 * (511 - 254) // 2 + (255 - 254 - 1))
        self.assertEqual(pair_id(254, 255), PAIR_COUNT)

    def test_unordered_endpoints_are_canonicalized(self):
        for a, b in ((0, 1), (0, 255), (7, 200), (254, 255)):
            self.assertEqual(pair_id(a, b), pair_id(b, a))
            self.assertEqual(pair_heads(pair_id(a, b)),
                             (min(a, b), max(a, b)))

    def test_decode_roundtrips_and_all_ids_stay_in_range(self):
        for a in range(HEAD_COUNT):
            for b in range(a + 1, HEAD_COUNT):
                value = pair_id(a, b)
                self.assertGreaterEqual(value, PAIR_ID_MIN)
                self.assertLessEqual(value, PAIR_ID_MAX)
                self.assertEqual(decode_pair_id(value), (a, b))

    def test_self_pairs_and_invalid_heads_fail_closed(self):
        for a, b in ((0, 0), (255, 255)):
            with self.assertRaises(WordNetMirrorError):
                pair_id(a, b)
        for bad in (-1, 256, True, 1.0, "1", None):
            with self.subTest(bad=bad), self.assertRaises(WordNetMirrorError):
                pair_id(bad, 1)
        for bad in (0, PAIR_ID_MAX + 1, -1, True, 1.0, None):
            with self.subTest(bad=bad), self.assertRaises(WordNetMirrorError):
                decode_pair_id(bad)


class PolysemyTests(unittest.TestCase):
    def test_one_lemma_keeps_multiple_synset_leaves(self):
        adapter = WordNetMirrorAdapter()
        leaves = adapter.map_lemma(
            "bank%1:17:00::", synsets=["bank-river", "bank-money"])
        self.assertEqual(len(leaves), 2)
        self.assertNotEqual(leaves[0]["leaf_id"], leaves[1]["leaf_id"])
        self.assertEqual({leaf["synset_key"] for leaf in leaves},
                         {"bank-river", "bank-money"})
        self.assertEqual(len({leaf["lemma_concept_id"] for leaf in leaves}), 1)
        self.assertEqual(len({leaf["lemma_head"] for leaf in leaves}), 1)
        self.assertEqual(len({leaf["synset_concept_id"] for leaf in leaves}), 2)

    def test_repeating_a_polysemous_row_does_not_collapse_or_duplicate(self):
        adapter = WordNetMirrorAdapter()
        row = {"kind": "lemma", "lemma": "bank",
               "synsets": ["bank-river", "bank-money"]}
        first = adapter.map_rows([row, row])
        second = adapter.map_rows([row])
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)

    def test_one_synset_can_keep_multiple_lemma_leaves(self):
        leaf = WordNetMirrorAdapter().map_synset(
            "dog-synset", lemma=None)
        self.assertEqual(leaf["synset_key"], "dog-synset")
        adapter = WordNetMirrorAdapter()
        records = adapter.adapt_row({
            "kind": "synset", "synset": "dog-synset",
            "lemmas": ["dog", "domestic_dog"],
        })
        self.assertEqual(len(records), 2)
        self.assertEqual(len({record["leaf_id"] for record in records}), 2)


class TypedRelationTests(unittest.TestCase):
    def test_relation_record_has_all_typed_fields_and_pair_id(self):
        adapter = WordNetMirrorAdapter()
        record = adapter.map_relation(
            "synset:02084071-n", "synset:02084072-n", "hypernym",
            polarity=1, confidence=0.75,
            source_digest=sha("wordnet row"),
            evidence={"file": "data.noun", "line": 42},
        )
        a = head_for_key("synset:02084071-n")
        b = head_for_key("synset:02084072-n")
        self.assertEqual(record["pair_id"], pair_id(a, b))
        self.assertEqual(record["relation_type"], "hypernym")
        self.assertEqual(record["relation_type_id"],
                         relation_type_id("hypernym"))
        self.assertEqual(record["polarity"], 1)
        self.assertEqual(record["confidence"], 0.75)
        self.assertEqual(record["source_digest"], sha("wordnet row"))
        self.assertEqual(record["evidence"],
                         {"file": "data.noun", "line": 42})
        self.assertEqual(record["evidence_sha256"], sha(
            '{"file":"data.noun","line":42}'))
        self.assertTrue(record["candidate_only"])
        self.assertFalse(record["canonical_promotion"])
        self.assertFalse(record["math_execution"])

    def test_relation_aliases_and_direction_are_preserved(self):
        adapter = WordNetMirrorAdapter()
        record = adapter.map_relation(
            "synset:a", "synset:b", "is-a", polarity="positive",
            confidence_q16=32768)
        self.assertEqual(record["relation_type"], "hypernym")
        self.assertEqual(record["polarity"], 1)
        self.assertEqual(record["confidence"], 0.5)
        self.assertEqual(record["source_head"], head_for_key("synset:a"))
        self.assertEqual(record["target_head"], head_for_key("synset:b"))
        self.assertEqual(record["orientation"],
                         "forward" if record["source_head"] <
                         record["target_head"] else "mirror")

    def test_sparse_relation_row_is_adapted(self):
        record = adapt_row({
            "kind": "relation",
            "source": {"synset": "s-a"},
            "target": {"synset": "s-b"},
            "relation_type": "antonym",
            "polarity": -1,
            "confidence": 0.25,
            "source_digest": sha("row"),
            "evidence": ["sparse.noun", 7],
        })[0]
        self.assertEqual(record["record_type"], "relation")
        self.assertEqual(record["relation_type"], "antonym")
        self.assertEqual(record["polarity"], -1)
        self.assertEqual(record["confidence"], 0.25)
        self.assertEqual(record["source_stable_key"], "synset:s-a")
        self.assertEqual(record["target_stable_key"], "synset:s-b")

    def test_optional_cycle_metadata_for_zero_origin(self):
        cycle = cycle_metadata(0, 3, 7)
        self.assertEqual(cycle["cycle"], [0, 3, 7])
        self.assertEqual(cycle["pair_ids"], [
            pair_id(0, 3), pair_id(3, 7), pair_id(0, 7)])
        self.assertEqual(len(cycle["cycle_id"]), 64)
        self.assertFalse(cycle["executed"])

        record = adapt_row({
            "kind": "relation", "source": "synset:a", "target": "synset:b",
            "relation": "related", "cycle": [0, 3, 7],
        })[0]
        self.assertEqual(record["cycle"]["cycle"], [0, 3, 7])
        self.assertEqual(record["cycle_id"], cycle["cycle_id"])

    def test_cycle_requires_root_zero_and_distinct_heads(self):
        for args in ((1, 3, 7), (0, 3, 3), (0, 0, 7), (0, 7, 0)):
            with self.subTest(args=args), self.assertRaises(WordNetMirrorError):
                cycle_metadata(*args)
        with self.assertRaises(WordNetMirrorError):
            cycle_metadata([0, 1])


class MalformedInputTests(unittest.TestCase):
    def test_incomplete_rows_are_rejected_without_inventing_keys(self):
        adapter = WordNetMirrorAdapter()
        rows = (
            {},
            {"kind": "synset"},
            {"kind": "lemma"},
            {"kind": "relation"},
            {"kind": "relation", "source": "synset:a"},
            {"kind": "relation", "source": "synset:a",
             "target": "synset:b"},
            {"kind": "synset", "synset": "s", "synsets": ["s"]},
            {"kind": "lemma", "lemma": "l", "synsets": []},
            {"kind": "lemma", "lemma": "l", "synsets": ["s", "s"]},
            {"kind": "unknown", "synset": "s"},
        )
        for row in rows:
            with self.subTest(row=row), self.assertRaises(WordNetMirrorError):
                adapter.adapt_row(row)
        self.assertEqual(adapter.records(), ())

    def test_ambiguous_endpoint_and_self_relation_are_rejected(self):
        adapter = WordNetMirrorAdapter()
        rows = (
            {"kind": "relation", "source": {"synset": "a", "lemma": "b"},
             "target": "synset:c", "relation": "hypernym"},
            {"kind": "relation", "source": "synset:a",
             "source_key": "synset:b", "target": "synset:c",
             "relation": "hypernym"},
            {"kind": "relation", "source": "synset:a",
             "target": "synset:a", "relation": "hypernym"},
        )
        for row in rows:
            with self.subTest(row=row), self.assertRaises(WordNetMirrorError):
                adapter.adapt_row(row)

    def test_unknown_relation_polarity_confidence_and_digest_fail(self):
        adapter = WordNetMirrorAdapter()
        base = {"kind": "relation", "source": "synset:a",
                "target": "synset:b", "relation": "hypernym"}
        for override in (
            {"relation": "not_a_wordnet_pointer"},
            {"polarity": 2},
            {"polarity": True},
            {"confidence": 1.5},
            {"confidence": float("nan")},
            {"confidence_q16": 65_537},
            {"source_digest": "bad"},
            {"source_digest": "A" * 64},
            {"evidence": {"value": object()}},
        ):
            row = {**base, **override}
            with self.subTest(override=override), self.assertRaises(
                    WordNetMirrorError):
                adapter.adapt_row(row)

    def test_unknown_concept_id_endpoint_is_rejected(self):
        with self.assertRaises(WordNetMirrorError):
            adapt_row({
                "kind": "relation",
                "source": {"concept_id": 123},
                "target": "synset:b",
                "relation": "hypernym",
            })

    def test_invalid_cycle_shape_is_rejected(self):
        with self.assertRaises(WordNetMirrorError):
            adapt_row({
                "kind": "relation", "source": "synset:a",
                "target": "synset:b", "relation": "related",
                "cycle": True,
            })
        with self.assertRaises(WordNetMirrorError):
            adapt_row({
                "kind": "relation", "source": "synset:a",
                "target": "synset:b", "relation": "related",
                "cycle": [0, 1, 1],
            })


class NoDenseMatrixTests(unittest.TestCase):
    def test_adapter_has_no_head_per_word_or_dense_matrix(self):
        adapter = WordNetMirrorAdapter()
        for index in range(512):
            adapter.map_synset(f"synset-{index}")
        status = adapter.status()
        self.assertFalse(status["allocates_head_per_word"])
        self.assertFalse(status["dense_matrix_allocated"])
        self.assertIsNone(status["dense_matrix_shape"])
        self.assertEqual(status["head_space"], HEAD_COUNT)
        for attribute in ("matrix", "_matrix", "dense", "_dense",
                          "head_matrix", "pair_matrix"):
            self.assertFalse(hasattr(adapter, attribute))
        # State grows by sparse mapping entries, not 256x256 cells per word.
        self.assertEqual(len(adapter.concepts()), 512)
        self.assertEqual(len(adapter.records()), 512)

    def test_module_exposes_no_math_or_database_path(self):
        import runner_riddle.wordnet_mirror_adapter as module
        with open(module.__file__, encoding="utf-8") as stream:
            source = stream.read()
        for forbidden in ("import sqlite3", "import numpy", "torch",
                          "subprocess", "requests", "openai"):
            self.assertNotIn(forbidden, source)


class IdempotenceTests(unittest.TestCase):
    def test_repeated_rows_produce_the_same_records(self):
        adapter = WordNetMirrorAdapter()
        rows = [
            {"kind": "synset", "synset": "s-a", "lemma": "word"},
            {"kind": "synset", "synset": "s-b"},
            {"kind": "relation", "source": "synset:s-a",
             "target": "synset:s-b", "relation": "hypernym",
             "polarity": 1, "confidence": 0.5,
             "source_digest": sha("row")},
        ]
        first = adapter.map_rows(rows)
        second = adapter.map_rows(rows + rows)
        third = WordNetMirrorAdapter().map_rows(rows)
        self.assertEqual(first, second)
        self.assertEqual(first, third)
        self.assertEqual(len(adapter.records()), 3)
        self.assertEqual(len(adapter.relations()), 1)
        self.assertEqual(adapter.as_dict(), adapter.as_dict())

    def test_relation_id_and_pair_id_are_deterministic(self):
        adapter = WordNetMirrorAdapter()
        row = {"kind": "relation", "source": "synset:s-a",
               "target": "synset:s-b", "relation": "related"}
        first = adapter.map_row(row)[0]
        second = adapter.map_row(row)[0]
        self.assertEqual(first["relation_id"], second["relation_id"])
        self.assertEqual(first["pair_id"], second["pair_id"])

    def test_caller_mutation_does_not_change_internal_state(self):
        adapter = WordNetMirrorAdapter()
        record = adapter.map_relation("synset:a", "synset:b", "related")
        record["pair_id"] = 99
        self.assertNotEqual(adapter.relations()[0]["pair_id"], 99)

    def test_batch_order_does_not_create_duplicate_leaf_ids(self):
        rows = [{"kind": "synset", "synset": "s", "lemma": "w"},
                {"kind": "synset", "synset": "s", "lemma": "w"}]
        records = adapt_rows(rows)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["route"], CANONICAL_ROUTE)
        self.assertTrue(records[0]["candidate_only"])


if __name__ == "__main__":
    unittest.main()
