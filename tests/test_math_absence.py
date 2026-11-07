from __future__ import annotations

import unittest

from runner_riddle.math_absence import (
    CANCELLED, EMPTY, ERROR, INFINITY, NULL, UNDEFINED, UNKNOWN, VOID, ZERO,
    AbsenceAlgebra, AbsenceError, AbsenceResult,
)
from runner_riddle.math_objects import MathLeaf


def leaf(kind="vector", i=1):
    return MathLeaf(f"nml:U0:{kind}:{i}", kind=kind,
                    type={"element": "opaque", "shape": []},
                    content={"digest": "a" * 64, "word_count": 1})


class AbsenceAlgebraTests(unittest.TestCase):
    def setUp(self):
        self.algebra = AbsenceAlgebra()

    def test_zero_is_not_null(self):
        zero = MathLeaf("nml:U0:scalar:0", kind="scalar",
                        type={"element": "float32", "shape": []},
                        content={"digest": "b" * 64, "value": "0"})
        null = self.algebra.to_leaf(NULL, reason="no result")
        self.assertEqual(self.algebra.classify(zero), ZERO)
        self.assertEqual(self.algebra.classify(null), NULL)
        self.assertNotEqual(zero.kind, null.kind)
        self.assertEqual(self.algebra.conjoin(zero, null).state, NULL)

    def test_each_terminal_absence_is_typed(self):
        for state in (NULL, VOID, UNDEFINED, UNKNOWN, ERROR, CANCELLED):
            with self.subTest(state=state):
                record = self.algebra.to_leaf(state, reason=f"{state}_TEST")
                self.assertEqual(record.kind, state.lower())
                self.assertIsNone(record.content)
                self.assertIn("reason", record.metadata)

    def test_void_conjunction_semantics(self):
        object_leaf = leaf()
        void_record = self.algebra.to_leaf(VOID, reason="no object")
        self.assertEqual(self.algebra.conjoin(object_leaf, void_record).state, UNKNOWN)
        self.assertEqual(self.algebra.conjoin(void_record, void_record).state, VOID)
        self.assertNotEqual(self.algebra.conjoin(object_leaf, void_record).state, ZERO)

    def test_null_and_undefined_are_not_interchangeable(self):
        null = self.algebra.to_leaf(NULL, reason="no transform")
        undefined = self.algebra.to_leaf(UNDEFINED, reason="division by zero")
        self.assertEqual(self.algebra.conjoin(null, leaf()).state, NULL)
        self.assertEqual(self.algebra.conjoin(undefined, leaf()).state, UNDEFINED)
        self.assertNotEqual(self.algebra.conjoin(null, leaf()).state,
                            self.algebra.conjoin(undefined, leaf()).state)

    def test_missing_required_object_is_unknown_or_reference_error(self):
        void = self.algebra.to_leaf(VOID, reason="missing")
        self.assertEqual(self.algebra.conjoin(leaf(), void).state, UNKNOWN)
        self.assertEqual(self.algebra.conjoin(leaf(), void, missing_is_unknown=False).state, ERROR)
        with self.assertRaises(AbsenceError):
            self.algebra.require_present(void)

    def test_empty_structure_is_valid_and_distinct(self):
        self.assertEqual(self.algebra.classify([]), EMPTY)
        self.assertEqual(self.algebra.classify({}), EMPTY)
        empty = self.algebra.conjoin([], leaf())
        self.assertEqual(empty.state, EMPTY)
        self.assertNotEqual(empty.state, NULL)

    def test_raw_host_numbers_are_not_silently_classified(self):
        with self.assertRaises(AbsenceError):
            self.algebra.classify(0.0)
        self.assertEqual(self.algebra.classify(False), ZERO)

    def test_absence_leaf_id_is_deterministic(self):
        a = self.algebra.to_leaf(NULL, reason="same")
        b = self.algebra.to_leaf(NULL, reason="same")
        self.assertEqual(a.leaf_id, b.leaf_id)
        self.assertEqual(a.to_dict(), b.to_dict())


if __name__ == "__main__":
    unittest.main()
