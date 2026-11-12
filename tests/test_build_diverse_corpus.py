"""Unit tests for the domain-diverse corpus builder.

These tests are offline: they exercise the streaming sink, field selection,
and local record readers without touching Kaggle, Hugging Face, or the network.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_diverse_corpus.py"
SPEC = importlib.util.spec_from_file_location("build_diverse_corpus", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import machinery
    raise ImportError(f"cannot import {SCRIPT}")
corpus = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = corpus
SPEC.loader.exec_module(corpus)


class RegistryTests(unittest.TestCase):
    def test_registry_has_domains_and_licenses(self) -> None:
        self.assertGreaterEqual(len(corpus.COLLECTIONS), 12)
        for name, collection in corpus.COLLECTIONS.items():
            self.assertEqual(name, collection.name)
            self.assertGreater(collection.max_mb, 0)
            self.assertTrue(collection.sources)
            for source in collection.sources:
                self.assertTrue(source.license, f"{name}: missing license")
                self.assertIn(source.kind, {"kaggle", "http", "hf", "rfc"})

    def test_check_registry_is_clean(self) -> None:
        corpus.check_registry()


class TextTests(unittest.TestCase):
    def test_normalize_text(self) -> None:
        raw = "a\r\n\r\n\r\nb\x00  \n"
        self.assertEqual(corpus.normalize_text(raw), "a\n\nb")

    def test_useful_text_rejects_short_or_numeric(self) -> None:
        self.assertFalse(corpus.useful_text("1234567890" * 20))
        self.assertTrue(corpus.useful_text("This is a sufficiently long sentence with words in it. " * 3))

    def test_sink_respects_budget_and_counts_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.txt"
            sink = corpus.TextSink(path, max_bytes=500, min_chars=40, max_doc_chars=400)
            self.assertTrue(sink.add("First document. " * 12))
            self.assertTrue(sink.add("Second document. " * 12))
            sink.add("Third document. " * 12)
            sink.close()
            self.assertLessEqual(path.stat().st_size, 501)
            self.assertGreaterEqual(sink.documents, 1)
            body = path.read_text(encoding="utf-8")
            self.assertIn("First document.", body)
            self.assertTrue(body.endswith("\n"))


class RecordTests(unittest.TestCase):
    def _source(self, fields=(), labels=True):
        return corpus.Source(
            kind="http",
            url="https://example.invalid/source",
            fields=fields,
            labels=labels,
            license="test",
        )

    def test_configured_fields(self) -> None:
        collection = corpus.COLLECTIONS["arxiv"]
        source = self._source(("title", "abstract"))
        text = corpus.record_to_text(
            {
                "title": "A sufficiently long paper title",
                "abstract": "This abstract contains enough words to be useful. " * 4,
                "id": "1234.5678",
            },
            source,
            collection,
        )
        self.assertIn("Title: A sufficiently long paper title", text)
        self.assertIn("Abstract: This abstract", text)
        self.assertNotIn("1234.5678", text)

    def test_auto_fields_find_sec_style_sections(self) -> None:
        collection = corpus.COLLECTIONS["finance"]
        source = self._source(("business", "risk_factors"))
        text = corpus.record_to_text(
            {
                "item_1_business": "The company sells widgets and services. " * 20,
                "item_1a_risk_factors": "Risks include competition and regulation. " * 20,
                "cik": "0000000001",
            },
            source,
            collection,
        )
        self.assertIn("Business:", text)
        self.assertIn("Risk Factors:", text)

    def test_r_vector_parsing(self) -> None:
        value = 'c("blueberries", "sugar", NA, "lemon juice")'
        self.assertEqual(
            corpus.stringify(value, "RecipeIngredientParts"),
            "blueberries\nsugar\nlemon juice",
        )

    def test_jsonl_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.jsonl"
            path.write_text(
                '{"text": "first record with enough text"}\n'
                '{"text": "second record with enough text"}\n',
                encoding="utf-8",
            )
            with path.open("rb") as handle:
                rows = list(corpus.iter_jsonl_records(handle))
            self.assertEqual([row["text"] for row in rows], [
                "first record with enough text",
                "second record with enough text",
            ])

    def test_xnli_parses_translation_variable_languages(self) -> None:
        value = (
            '{"language": ["en", "fr"], '
            '"translation": ["A hypothesis", "Une hypothese"]}'
        )
        self.assertEqual(
            corpus.parse_language_map(value),
            {"en": "A hypothesis", "fr": "Une hypothese"},
        )

    def test_xnli_parses_pandas_array_repr(self) -> None:
        value = (
            "{'language': array(['en', 'fr'], dtype=object), "
            "'translation': array(['A hypothesis', \"L' hypothese\"], dtype=object)}"
        )
        self.assertEqual(
            corpus.parse_language_map(value),
            {"en": "A hypothesis", "fr": "L' hypothese"},
        )

    def test_parse_dict_string_handles_escaped_quotes(self) -> None:
        value = '{\\"en\\": \\"A premise\\", \\"fr\\": \\"Une premisse\\"}'
        self.assertEqual(
            corpus.parse_dict_string(value),
            {"en": "A premise", "fr": "Une premisse"},
        )

    def test_xnli_expands_language_dicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "xnli.csv"
            path.write_text(
                "premise,hypothesis,label\n"
                "\"{'en': 'A premise', 'fr': 'Une premisse'}\","
                "\"{'en': 'A hypothesis', 'fr': 'Une hypothese'}\",0\n",
                encoding="utf-8",
            )
            with path.open("rb") as handle:
                rows = list(corpus.iter_xnli_records(handle, self._source()))
            self.assertEqual(len(rows), 2)
            self.assertEqual({row["language"] for row in rows}, {"en", "fr"})
            self.assertEqual(rows[0]["premise"], "A premise")

    def test_csv_records_strip_bom_and_preserve_commas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.csv"
            path.write_text(
                "\ufeffquestion,answer\n"
                '"What is 2+2?","It is 4, obviously."\n',
                encoding="utf-8",
            )
            with path.open("rb") as handle:
                rows = list(corpus.iter_csv_records(handle, self._source()))
            self.assertEqual(rows[0]["question"], "What is 2+2?")
            self.assertEqual(rows[0]["answer"], "It is 4, obviously.")


if __name__ == "__main__":
    unittest.main()
