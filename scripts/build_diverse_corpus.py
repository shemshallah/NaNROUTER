#!/usr/bin/env python3
"""Build domain-diverse plain-text corpora for NaNROUTER.

Each *collection* is one UTF-8 ``.txt`` file made of documents separated by a
blank line.  The default source list mixes encyclopedic, scientific, legal,
medical, technical, code, mathematical, news, dialogue, and reference data so
the resulting training material is not dominated by a single genre.

The script is intentionally a streaming builder: it never loads a whole large
JSON/CSV source into memory and it stops writing as soon as the collection cap
is reached.  The GitHub Actions workflow in
``.github/workflows/fetch-diverse-corpus.yml`` runs one collection per runner
and publishes each ``.txt`` as its own public GitHub Release.

Examples
--------
    python scripts/build_diverse_corpus.py --list
    python scripts/build_diverse_corpus.py --check
    python scripts/build_diverse_corpus.py --collection arxiv --max-mb 200
    python scripts/build_diverse_corpus.py --collection standards --max-mb 5

Kaggle access uses ``KAGGLE_API_TOKEN`` (a ``KGAT_...`` token or the contents
of ``kaggle.json``).  Hugging Face and direct HTTP sources need no token.
"""

from __future__ import annotations

import argparse
import base64
import bz2
import csv
import fnmatch
import gzip
import hashlib
import html
import io
import json
import os
import re
import shutil
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Iterator, Sequence

try:  # Optional but required for large JSON arrays (e.g. the arXiv snapshot).
    import ijson  # type: ignore
except ImportError:  # pragma: no cover - exercised only when the extra is absent
    ijson = None

try:
    import pyarrow.parquet as pq  # type: ignore
except ImportError:  # pragma: no cover - parquet sources fail with a clear message
    pq = None


USER_AGENT = "NaNROUTER-diverse-corpus/1.0 (+https://github.com/shemshallah/NaNROUTER)"
INDEX_URL = "https://www.rfc-editor.org/rfc-index.xml"
RFC_TEXT_URL = "https://www.rfc-editor.org/rfc/rfc{number}.txt"

# Keep the CSV parser from rejecting long abstracts, articles, or code blobs.
try:
    csv.field_size_limit(min(sys.maxsize, 1 << 30))
except OverflowError:  # pragma: no cover - defensive for unusual platforms
    csv.field_size_limit(1 << 30)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Source:
    """One downloadable source inside a collection."""

    kind: str  # kaggle | http | hf | rfc
    ref: str = ""
    url: str = ""
    files: tuple[str, ...] = ()
    fmt: str = ""
    fields: tuple[str, ...] = ()
    labels: bool = True
    auto_fallback: bool = True
    required: bool = True
    max_bytes: int = 0
    max_files: int = 0
    revision: str = "main"
    license: str = ""
    license_url: str = ""
    homepage: str = ""
    notes: str = ""

    def validate(self, collection: str) -> None:
        if self.kind not in {"kaggle", "http", "hf", "rfc"}:
            raise ValueError(f"{collection}: unknown source kind {self.kind!r}")
        if self.kind in {"kaggle", "hf"} and "/" not in self.ref:
            raise ValueError(f"{collection}: {self.kind} ref must be owner/name: {self.ref!r}")
        if self.kind in {"http", "rfc"} and not self.url:
            raise ValueError(f"{collection}: {self.kind} source needs a URL")
        if not self.license:
            raise ValueError(f"{collection}: source {self.ref or self.url} needs a license")


@dataclass(frozen=True)
class Collection:
    """A single released .txt corpus and its ordered sources."""

    name: str
    title: str
    domain: str
    description: str
    max_mb: int
    sources: tuple[Source, ...]
    min_chars: int = 120
    max_doc_chars: int = 240_000
    labels: bool = True


def _mb(value: int) -> int:
    return value * 1_000_000


COLLECTIONS: dict[str, Collection] = {
    "wikipedia-en": Collection(
        name="wikipedia-en",
        title="English Wikipedia",
        domain="encyclopedia",
        description=(
            "Plain-text English Wikipedia articles from the 2023-11-01 "
            "Wikimedia dump, sampled from the start of the corpus."
        ),
        max_mb=1500,
        sources=(
            Source(
                kind="hf",
                ref="wikimedia/wikipedia",
                revision="main",
                files=("20231101.en/train-*.parquet",),
                fmt="parquet",
                fields=("title", "text"),
                max_files=3,
                max_bytes=_mb(1500),
                license="CC BY-SA 4.0",
                license_url="https://creativecommons.org/licenses/by-sa/4.0/",
                homepage="https://huggingface.co/datasets/wikimedia/wikipedia",
                notes="Wikimedia dump 20231101.en; attribution required.",
            ),
        ),
    ),
    "arxiv": Collection(
        name="arxiv",
        title="arXiv metadata and abstracts",
        domain="science, technology, engineering, mathematics",
        description=(
            "Title, authors, categories, and abstract for arXiv papers across "
            "physics, mathematics, computer science, statistics, and biology."
        ),
        max_mb=1200,
        sources=(
            Source(
                kind="kaggle",
                ref="Cornell-University/arxiv",
                files=("arxiv-metadata-oai-snapshot.json",),
                fmt="jsonl",
                fields=("title", "authors", "categories", "abstract"),
                max_bytes=_mb(1200),
                license="CC0 1.0",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                homepage="https://www.kaggle.com/datasets/Cornell-University/arxiv",
                notes="arXiv metadata snapshot maintained by Cornell University.",
            ),
        ),
    ),
    "pubmed": Collection(
        name="pubmed",
        title="PubMed article and abstract corpus",
        domain="biomedicine and life sciences",
        description=(
            "Biomedical full-text articles paired with their author abstracts "
            "from the PubMed summarization dataset."
        ),
        max_mb=1000,
        sources=(
            Source(
                kind="kaggle",
                ref="thedevastator/pubmed-article-summarization-dataset",
                files=("train.csv",),
                fmt="csv",
                fields=("article", "abstract"),
                max_bytes=_mb(1000),
                license="CC0 1.0",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                homepage="https://www.kaggle.com/datasets/thedevastator/pubmed-article-summarization-dataset",
                notes="Derived from PubMed/PMC open-access material.",
            ),
        ),
    ),
    "law": Collection(
        name="law",
        title="Supreme Court opinions and statutes",
        domain="law and government",
        description=(
            "Full text of U.S. Supreme Court opinions, plus Kentucky Revised "
            "Statutes sections as a second, statute-oriented legal register."
        ),
        max_mb=850,
        sources=(
            Source(
                kind="kaggle",
                ref="jboysen/scotus-corpus",
                files=("scotus_file.gz",),
                fmt="csv",
                fields=("plain_text|html_with_citations|html|html_columbia|html_lawbox",),
                auto_fallback=False,
                max_bytes=_mb(760),
                license="CC0 1.0",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                homepage="https://www.kaggle.com/datasets/jboysen/scotus-corpus",
                notes="CourtListener/Free Law Project Supreme Court opinions.",
            ),
            Source(
                kind="kaggle",
                ref="jscotthorn/kentucky-revised-statutes-parsed-csv",
                files=("*.statutes.csv",),
                fmt="csv",
                fields=(),
                max_bytes=_mb(80),
                required=False,
                license="Apache 2.0",
                license_url="https://www.apache.org/licenses/LICENSE-2.0",
                homepage="https://www.kaggle.com/datasets/jscotthorn/kentucky-revised-statutes-parsed-csv",
                notes="Kentucky Revised Statutes, parsed edition.",
            ),
        ),
    ),
    "patents": Collection(
        name="patents",
        title="US patent abstracts",
        domain="patents and invention",
        description=(
            "US patent publication numbers and abstracts covering mechanical, "
            "chemical, electrical, medical, and software inventions."
        ),
        max_mb=900,
        sources=(
            Source(
                kind="kaggle",
                ref="dheerajmpai/us-patent-abstracts-vector-indexed",
                files=("train_mini.csv",),
                fmt="csv",
                fields=("publication_number", "abstract"),
                max_bytes=_mb(900),
                license="Apache 2.0",
                license_url="https://www.apache.org/licenses/LICENSE-2.0",
                homepage="https://www.kaggle.com/datasets/dheerajmpai/us-patent-abstracts-vector-indexed",
                notes="US patent abstracts with publication and application numbers.",
            ),
        ),
    ),
    "code": Collection(
        name="code",
        title="Competitive programming and code instructions",
        domain="computer programming and software",
        description=(
            "Accepted Codeforces submissions plus general code-instruction "
            "examples, giving both raw source code and natural-language coding "
            "tasks."
        ),
        max_mb=900,
        sources=(
            Source(
                kind="hf",
                ref="open-r1/codeforces-submissions",
                revision="main",
                files=("data/train-*.parquet",),
                fmt="parquet",
                fields=("problem_id", "source"),
                max_files=6,
                max_bytes=_mb(760),
                license="CC BY 4.0",
                license_url="https://creativecommons.org/licenses/by/4.0/",
                homepage="https://huggingface.co/datasets/open-r1/codeforces-submissions",
                notes="Human Codeforces submissions, filtered to accepted solutions upstream.",
            ),
            Source(
                kind="kaggle",
                ref="thedevastator/evol-instruct-code-80k-v1-dataset",
                files=("train.csv",),
                fmt="csv",
                fields=("instruction", "input", "output"),
                max_bytes=_mb(120),
                required=False,
                license="CC0 1.0",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                homepage="https://www.kaggle.com/datasets/thedevastator/evol-instruct-code-80k-v1-dataset",
                notes="Evol-Instruct code tasks.",
            ),
        ),
    ),
    "math": Collection(
        name="math",
        title="Mathematics Stack Exchange",
        domain="mathematics",
        description=(
            "Questions, answers, proofs, and worked reasoning from Mathematics "
            "Stack Exchange."
        ),
        max_mb=900,
        sources=(
            Source(
                kind="kaggle",
                ref="botcanlearn/math-stackexchange-llama-factory-jsonl",
                files=("data.jsonl",),
                fmt="jsonl",
                fields=("text",),
                max_bytes=_mb(900),
                license="CC BY-SA 4.0",
                license_url="https://creativecommons.org/licenses/by-sa/4.0/",
                homepage="https://www.kaggle.com/datasets/botcanlearn/math-stackexchange-llama-factory-jsonl",
                notes="Mathematics Stack Exchange pretraining text; attribution/share-alike.",
            ),
        ),
    ),
    "news": Collection(
        name="news",
        title="News articles and headlines",
        domain="journalism, politics, business, and current events",
        description=(
            "CNN/Daily Mail news articles with highlights, plus a broad set of "
            "HuffPost news headlines and short descriptions."
        ),
        max_mb=800,
        sources=(
            Source(
                kind="kaggle",
                ref="gowrishankarp/newspaper-text-summarization-cnn-dailymail",
                files=("cnn_dailymail/train.csv",),
                fmt="csv",
                fields=("article", "highlights"),
                max_bytes=_mb(700),
                license="CC0 1.0",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                homepage="https://www.kaggle.com/datasets/gowrishankarp/newspaper-text-summarization-cnn-dailymail",
                notes="CNN and Daily Mail news articles.",
            ),
            Source(
                kind="kaggle",
                ref="rmisra/news-category-dataset",
                files=("News_Category_Dataset_v3.json",),
                fmt="jsonl",
                fields=("headline", "short_description", "category"),
                max_bytes=_mb(100),
                required=False,
                license="CC BY 4.0",
                license_url="https://creativecommons.org/licenses/by/4.0/",
                homepage="https://www.kaggle.com/datasets/rmisra/news-category-dataset",
                notes="HuffPost news headlines and short descriptions.",
            ),
        ),
    ),
    "recipes": Collection(
        name="recipes",
        title="Food.com recipes",
        domain="cooking, food, and everyday procedures",
        description=(
            "Recipe names, descriptions, ingredient lists, and step-by-step "
            "directions from Food.com."
        ),
        max_mb=650,
        sources=(
            Source(
                kind="kaggle",
                ref="irkaal/foodcom-recipes-and-reviews",
                files=("recipes.parquet",),
                fmt="parquet",
                fields=("Name", "Description", "RecipeIngredientParts", "RecipeInstructions"),
                max_bytes=_mb(650),
                license="CC0 1.0",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                homepage="https://www.kaggle.com/datasets/irkaal/foodcom-recipes-and-reviews",
                notes="Food.com recipe corpus.",
            ),
        ),
    ),
    "security": Collection(
        name="security",
        title="CVE vulnerability records",
        domain="cybersecurity",
        description=(
            "NVD CVE records joined with CVSS, CWE, CISA KEV, and EPSS data: "
            "vulnerability descriptions, affected products, and exploit status."
        ),
        max_mb=450,
        sources=(
            Source(
                kind="kaggle",
                ref="afr1ste/nvd-cve-cvss-kev-vulnerabilities-2020-2026",
                files=("nvd_cve_records.csv", "cisa_kev_catalog.csv"),
                fmt="csv",
                fields=("cve_id", "description", "cvss_vector", "cwe", "vendor_project", "product"),
                max_bytes=_mb(450),
                license="CC0 1.0",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                homepage="https://www.kaggle.com/datasets/afr1ste/nvd-cve-cvss-kev-vulnerabilities-2020-2026",
                notes="NVD, CISA KEV, and FIRST EPSS derived records.",
            ),
        ),
    ),
    "qa": Collection(
        name="qa",
        title="Stack Exchange question-answer pairs",
        domain="question answering, explanation, and technical discussion",
        description=(
            "Question and answer pairs from Stack Exchange sites, including "
            "general, expert, and biomedical collections."
        ),
        max_mb=850,
        sources=(
            Source(
                kind="kaggle",
                ref="xhlulu/stackexchange-qa-pairs",
                files=("pre_covid/expert.csv", "pre_covid/general.csv", "pre_covid/biomedical.csv"),
                fmt="csv",
                fields=("question", "answer"),
                max_bytes=_mb(850),
                license="CC BY-SA 4.0",
                license_url="https://creativecommons.org/licenses/by-sa/4.0/",
                homepage="https://www.kaggle.com/datasets/xhlulu/stackexchange-qa-pairs",
                notes="Stack Exchange Q&A pairs; attribution/share-alike.",
            ),
        ),
    ),
    "multilingual": Collection(
        name="multilingual",
        title="Multilingual natural-language inference",
        domain="multilingual language and reasoning",
        description=(
            "Parallel premise/hypothesis pairs across many languages from XNLI, "
            "providing non-English grammar, vocabulary, and reasoning material."
        ),
        max_mb=700,
        sources=(
            Source(
                kind="kaggle",
                ref="thedevastator/xnli-multilingual-nli-dataset",
                files=("all_languages_train.csv",),
                fmt="csv",
                fields=("premise", "hypothesis", "language"),
                max_bytes=_mb(700),
                license="CC0 1.0",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                homepage="https://www.kaggle.com/datasets/thedevastator/xnli-multilingual-nli-dataset",
                notes="XNLI multilingual NLI corpus.",
            ),
        ),
    ),
    "finance": Collection(
        name="finance",
        title="SEC 10-K annual filings",
        domain="finance, accounting, and corporate governance",
        description=(
            "Business descriptions, risk factors, management discussion, and "
            "other narrative sections from SEC Form 10-K annual filings."
        ),
        max_mb=700,
        sources=(
            Source(
                kind="kaggle",
                ref="pranjalverma08/sec-edgar-annual-financial-filings-2021",
                files=("extracted/*.json",),
                fmt="json",
                fields=(
                    "business",
                    "risk_factors",
                    "mdna",
                    "legal_proceedings",
                    "properties",
                    "item_1_business",
                    "item_1a_risk_factors",
                    "item_7_mdna",
                ),
                max_bytes=_mb(700),
                license="CC0 1.0",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                homepage="https://www.kaggle.com/datasets/pranjalverma08/sec-edgar-annual-financial-filings-2021",
                notes="SEC EDGAR 10-K filings; U.S. government works.",
            ),
        ),
    ),
    "standards": Collection(
        name="standards",
        title="IETF Request for Comments",
        domain="networking, protocols, and technical standards",
        description=(
            "The IETF RFC series: protocol specifications, architecture, "
            "security guidance, and operational standards."
        ),
        max_mb=350,
        sources=(
            Source(
                kind="rfc",
                ref="ietf-rfc",
                url=INDEX_URL,
                fmt="rfc",
                fields=("title", "abstract", "text"),
                max_bytes=_mb(350),
                license="IETF Trust Legal Provisions",
                license_url="https://trustee.ietf.org/license-info/",
                homepage="https://www.rfc-editor.org/",
                notes="RFC text is reproduced under the IETF Trust legal provisions.",
            ),
        ),
    ),
    "humanities": Collection(
        name="humanities",
        title="Religious, spiritual, and poetic texts",
        domain="religion, philosophy, and poetry",
        description=(
            "Public-domain religious and spiritual texts paired with a "
            "Project Gutenberg-derived poetry corpus."
        ),
        max_mb=500,
        sources=(
            Source(
                kind="kaggle",
                ref="metron/public-files-of-religious-and-spiritual-texts",
                files=("*.txt",),
                fmt="text",
                fields=(),
                max_bytes=_mb(180),
                license="CC0 1.0",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                homepage="https://www.kaggle.com/datasets/metron/public-files-of-religious-and-spiritual-texts",
                notes="Public-domain religious and spiritual texts.",
            ),
            Source(
                kind="hf",
                ref="biglam/gutenberg-poetry-corpus",
                revision="main",
                files=("data/train-*.parquet",),
                fmt="poetry",
                fields=("text",),
                max_bytes=_mb(300),
                required=False,
                license="CC0 1.0",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                homepage="https://huggingface.co/datasets/biglam/gutenberg-poetry-corpus",
                notes="Poetry lines from Project Gutenberg, grouped by book.",
            ),
        ),
    ),
    "chemistry": Collection(
        name="chemistry",
        title="Chemistry problems and solutions",
        domain="chemistry",
        description=(
            "Chemistry problems with worked solutions, supplementing the "
            "physics/mathematics coverage in the arXiv and math collections."
        ),
        max_mb=120,
        sources=(
            Source(
                kind="kaggle",
                ref="thedevastator/chemistry-problem-solution-dataset",
                files=("train.csv",),
                fmt="csv",
                fields=("topic", "sub_topic", "message_1", "message_2"),
                max_bytes=_mb(120),
                license="CC0 1.0",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                homepage="https://www.kaggle.com/datasets/thedevastator/chemistry-problem-solution-dataset",
                notes="Chemistry problem/solution pairs.",
            ),
        ),
    ),
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slug(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "untitled"


def human_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(value)
    for unit in units:
        if size < 1000 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1000


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value: str, limit: int = 100) -> str:
    name = Path(value).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return (name[:limit] or "file")


def selected(name: str, patterns: Sequence[str]) -> bool:
    if not patterns:
        return True
    candidates = (name, Path(name).name)
    return any(
        fnmatch.fnmatch(candidate, pattern)
        for pattern in patterns
        for candidate in candidates
    )


def normalize_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\x00", "").replace("\ufeff", "")
    value = value.replace("\u00a0", " ")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = "".join(
        char
        for char in value
        if char in "\n\t" or ord(char) >= 32
    )
    return value.strip()


def useful_text(text: str) -> bool:
    if len(text) < 80:
        return False
    letters = sum(char.isalpha() for char in text)
    if letters < 20:
        return False
    # Reject binary/base64-like blobs and tables that are almost entirely digits.
    return letters >= int(len(text) * 0.10)


def truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def strip_html(value: str) -> str:
    value = re.sub(r"<script\b.*?</script>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<style\b.*?</style>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"[ \t]{2,}", " ", value)


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------


FIELD_LABELS = {
    "plain_text": "",
    "text": "",
    "html": "",
    "html_with_citations": "",
    "html_columbia": "",
    "html_lawbox": "",
    "article": "Article",
    "abstract": "Abstract",
    "summary": "Summary",
    "title": "Title",
    "headline": "Headline",
    "authors": "Authors",
    "author": "Author",
    "author_str": "Author",
    "categories": "Categories",
    "category": "Category",
    "source": "Code",
    "problem_id": "Problem",
    "publication_number": "Patent",
    "application_number": "Application",
    "question": "Question",
    "answer": "Answer",
    "instruction": "Instruction",
    "input": "Input",
    "output": "Output",
    "premise": "Premise",
    "hypothesis": "Hypothesis",
    "language": "Language",
    "Name": "Recipe",
    "Description": "Description",
    "RecipeIngredientParts": "Ingredients",
    "RecipeInstructions": "Directions",
    "business": "Business",
    "risk_factors": "Risk Factors",
    "mdna": "Management Discussion",
    "legal_proceedings": "Legal Proceedings",
    "properties": "Properties",
    "cve_id": "CVE",
    "description": "Description",
    "cvss_vector": "CVSS",
    "cwe": "CWE",
    "vendor_project": "Vendor",
    "product": "Product",
    "poem": "",
    "date_created": "Date",
    "journal-ref": "Journal Reference",
    "comments": "Comments",
    "message_1": "Question",
    "message_2": "Answer",
    "topic": "Topic",
    "sub_topic": "Subtopic",
}

HIGH_VALUE_KEYS = {
    "text": 100,
    "content": 98,
    "article": 96,
    "body": 94,
    "plain_text": 92,
    "full_text": 90,
    "abstract": 88,
    "summary": 86,
    "description": 84,
    "question": 82,
    "answer": 80,
    "solution": 78,
    "prompt": 76,
    "instruction": 74,
    "output": 72,
    "review": 70,
    "comment": 68,
    "opinion": 66,
    "document": 64,
    "passage": 62,
    "story": 60,
    "poem": 58,
    "recipe": 56,
    "directions": 54,
    "ingredients": 52,
    "code": 50,
    "source_code": 48,
    "title": 50,
    "headline": 48,
    "name": 46,
    "caption": 44,
    "business": 42,
    "risk_factors": 40,
    "mdna": 38,
    "legal_proceedings": 36,
    "properties": 34,
    "premise": 32,
    "hypothesis": 30,
    "authors": 28,
    "author": 26,
    "categories": 24,
}

LOW_VALUE_KEYS = {
    "id",
    "url",
    "uri",
    "link",
    "sha",
    "sha1",
    "sha256",
    "hash",
    "date",
    "date_created",
    "date_modified",
    "timestamp",
    "count",
    "score",
    "label",
    "labels",
    "index",
    "row",
    "file",
    "path",
    "code",
    "status",
    "type",
    "version",
    "year",
    "month",
    "day",
    "number",
}

FIELD_BLACKLIST_RE = re.compile(
    r"(^|_)(id|url|uri|link|sha|hash|uuid|key|token|path|file|index|row|score|label|status|type|version|year|month|day|count)(_|$)",
    re.IGNORECASE,
)


def label_for(field: str) -> str:
    if field in FIELD_LABELS:
        return FIELD_LABELS[field]
    short = field.rsplit(".", 1)[-1]
    if short in FIELD_LABELS:
        return FIELD_LABELS[short]
    return short.replace("_", " ").replace("-", " ").title()


def get_path(record: dict[str, Any], path: str) -> Any:
    current: Any = record
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def stringify(value: Any, field_name: str = "", depth: int = 0) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
        key = field_name.lower()
        if "html" in key and "<" in text:
            text = strip_html(text)
        return text.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, bool):
        return ""
    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            part = stringify(item, field_name, depth + 1)
            if part:
                parts.append(part)
        if not parts:
            return ""
        if any(key in field_name.lower() for key in ("ingredient", "instruction", "direction")):
            return "\n".join(parts)
        return ", ".join(parts)
    if isinstance(value, dict) and depth < 3:
        parts = []
        for key, item in value.items():
            part = stringify(item, f"{field_name}.{key}" if field_name else key, depth + 1)
            if part:
                parts.append(f"{label_for(key)}: {part}" if label_for(key) else part)
        return "\n\n".join(parts)
    return ""


def flatten_strings(record: Any, prefix: str = "", depth: int = 0) -> Iterator[tuple[str, str]]:
    if depth > 3:
        return
    if isinstance(record, dict):
        for key, value in record.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield from flatten_strings(value, path, depth + 1)
    elif isinstance(record, (list, tuple)):
        for item in record:
            yield from flatten_strings(item, prefix, depth + 1)
    elif isinstance(record, str):
        yield prefix, record


def auto_fields(record: dict[str, Any], min_chars: int = 40) -> list[tuple[str, str]]:
    candidates: list[tuple[int, int, str, str]] = []
    for path, value in flatten_strings(record):
        key = path.rsplit(".", 1)[-1]
        lowered = key.lower()
        if FIELD_BLACKLIST_RE.search(lowered):
            continue
        text = stringify(value, path)
        if len(text) < min_chars:
            continue
        score = HIGH_VALUE_KEYS.get(lowered, 0)
        if not score:
            # SEC filings often use names such as item_1_business or
            # item_1a_risk_factors rather than the bare section name.
            for token, token_score in HIGH_VALUE_KEYS.items():
                if token in lowered:
                    score = max(score, token_score - 5)
        if not score and lowered in LOW_VALUE_KEYS:
            continue
        # Prefer leaf text fields over containers with the same content.
        candidates.append((score, len(text), path, text))
    candidates.sort(key=lambda row: (-row[0], -row[1], row[2]))
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for score, _length, path, text in candidates:
        if text in seen:
            continue
        if score == 0 and len(text) < 160:
            continue
        seen.add(text)
        result.append((path, text))
        if len(result) >= 8:
            break
    return result


def record_to_text(
    record: Any,
    source: Source,
    collection: Collection,
) -> str:
    if isinstance(record, str):
        return normalize_text(record)
    if not isinstance(record, dict):
        return ""

    pairs: list[tuple[str, str]] = []
    for field_name in source.fields:
        # A field can list fallbacks, e.g. plain_text|html_with_citations.
        # Use the first non-empty variant for that document.
        for alternative in field_name.split("|"):
            value = get_path(record, alternative)
            if value is None:
                continue
            text = stringify(value, field_name)
            if text:
                pairs.append((alternative, text))
                break

    if not pairs:
        pairs = auto_fields(record)

    blocks: list[str] = []
    seen: set[str] = set()
    use_labels = source.labels and collection.labels
    for field_name, raw_text in pairs:
        text = normalize_text(raw_text)
        if len(text) < 20 or text in seen:
            continue
        seen.add(text)
        label = label_for(field_name)
        if use_labels and label:
            blocks.append(f"{label}: {text}")
        else:
            blocks.append(text)
        if len(blocks) >= 10:
            break

    if source.auto_fallback and len(blocks) < 2 and not any(len(block) > 4000 for block in blocks):
        # Configured names can be missing, too short, or only capture part of
        # a heterogeneous record (for example a question without its answer).
        # Add generic text fields until the document has useful structure.
        # A single long full-text block is already a complete document; do not
        # append duplicate HTML/plaint-text variants to it.
        for field_name, raw_text in auto_fields(record):
            text = normalize_text(raw_text)
            if len(text) < 20 or text in seen:
                continue
            seen.add(text)
            label = label_for(field_name)
            blocks.append(f"{label}: {text}" if use_labels and label else text)
            if len(blocks) >= 6:
                break
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Sink
# ---------------------------------------------------------------------------


class TextSink:
    """Streaming UTF-8 text writer with a hard byte budget and document counter."""

    def __init__(
        self,
        path: Path,
        max_bytes: int,
        min_chars: int,
        max_doc_chars: int,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.handle = path.open("w", encoding="utf-8", newline="\n")
        self.max_bytes = max_bytes
        self.min_chars = min_chars
        self.max_doc_chars = max_doc_chars
        self.bytes = 0
        self.documents = 0
        self._first = True
        self.closed = False

    def add(self, value: str) -> bool:
        if self.closed or self.bytes >= self.max_bytes:
            return False
        text = normalize_text(value)[: self.max_doc_chars].strip()
        if len(text) < self.min_chars or not useful_text(text):
            return False

        separator = "" if self._first else "\n\n"
        separator_bytes = len(separator.encode("utf-8"))
        remaining = self.max_bytes - self.bytes - separator_bytes
        if remaining <= 0:
            return False
        encoded = text.encode("utf-8")
        if len(encoded) > remaining:
            text = truncate_utf8(text, remaining)
            encoded = text.encode("utf-8")
            if len(text) < self.min_chars:
                return False

        self.handle.write(separator)
        self.handle.write(text)
        self.bytes += separator_bytes + len(encoded)
        self.documents += 1
        self._first = False
        return True

    def close(self) -> None:
        if self.closed:
            return
        if not self._first:
            self.handle.write("\n")
        self.handle.close()
        self.closed = True


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------


def kaggle_token() -> str:
    token = os.environ.get("KAGGLE_API_TOKEN") or os.environ.get("KAGGLE_KEY")
    if token:
        return token.strip()
    for path in (Path.home() / ".kaggle" / "access_token", Path.home() / ".kaggle" / "kaggle.json"):
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    raise RuntimeError(
        "KAGGLE_API_TOKEN is not set and ~/.kaggle/access_token is missing. "
        "Set the repository secret KAGGLE_API_TOKEN before running Kaggle sources."
    )


def kaggle_auth_header(token: str) -> str:
    token = token.strip()
    if token.startswith("{"):
        data = json.loads(token)
        raw = f"{data['username']}:{data['key']}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")
    return "Bearer " + token


def download_url(
    url: str,
    destination: Path,
    headers: dict[str, str] | None = None,
    timeout: int = 300,
    retries: int = 5,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        partial = destination.with_suffix(destination.suffix + ".part")
        partial.unlink(missing_ok=True)
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT, **(headers or {})},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                total = int(response.headers.get("Content-Length") or 0)
                done = 0
                last_mark = 0
                with partial.open("wb") as handle:
                    while True:
                        chunk = response.read(4 * 1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        done += len(chunk)
                        if done - last_mark >= 256 * 1024 * 1024:
                            last_mark = done
                            suffix = f" / {human_bytes(total)}" if total else ""
                            print(f"  download {done / 1e6:.0f} MB{suffix}", flush=True)
            if partial.stat().st_size == 0:
                raise RuntimeError("empty download")
            partial.replace(destination)
            return destination
        except Exception as exc:  # noqa: BLE001 - retry all network errors
            last_error = exc
            partial.unlink(missing_ok=True)
            if attempt < retries:
                delay = min(30, 2 ** attempt)
                print(f"  retry {attempt}/{retries} for {url}: {exc}; waiting {delay}s", flush=True)
                time.sleep(delay)
    raise RuntimeError(f"failed to download {url}: {last_error}")


def materialize_source(
    source: Source,
    collection: Collection,
    work_dir: Path,
) -> tuple[list[Path], list[dict[str, Any]]]:
    downloads = work_dir / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)

    if source.kind == "kaggle":
        tag = source.ref.replace("/", "--")
        destination = downloads / f"{tag}.zip"
        if not (destination.exists() and zipfile.is_zipfile(destination)):
            print(f"  kaggle download {source.ref}", flush=True)
            token = kaggle_token()
            download_url(
                f"https://www.kaggle.com/api/v1/datasets/download/{urllib.parse.quote(source.ref, safe='/')}",
                destination,
                headers={"Authorization": kaggle_auth_header(token)},
            )
        return [destination], [{"kind": "kaggle", "ref": source.ref, "bytes": destination.stat().st_size}]

    if source.kind == "http":
        destination = downloads / safe_name(urllib.parse.urlparse(source.url).path or "download.bin")
        if not destination.exists() or destination.stat().st_size == 0:
            print(f"  http download {source.url}", flush=True)
            download_url(source.url, destination)
        return [destination], [{"kind": "http", "url": source.url, "bytes": destination.stat().st_size}]

    if source.kind == "hf":
        tree_url = (
            f"https://huggingface.co/api/datasets/{source.ref}/tree/"
            f"{urllib.parse.quote(source.revision, safe='')}"
        )
        if source.files and any("/" in pattern for pattern in source.files):
            # Wikimedia-style configs live in a subdirectory; use its tree.
            first_pattern = source.files[0]
            prefix = first_pattern.rsplit("/", 1)[0]
            tree_url += "/" + urllib.parse.quote(prefix, safe="/")
        with urllib.request.urlopen(
            urllib.request.Request(tree_url, headers={"User-Agent": USER_AGENT}),
            timeout=60,
        ) as response:
            entries = json.load(response)
        files = [
            entry for entry in entries
            if entry.get("type") == "file" and selected(entry.get("path", ""), source.files)
        ]
        files.sort(key=lambda entry: entry.get("path", ""))
        if source.max_files:
            files = files[: source.max_files]
        if not files:
            raise RuntimeError(f"no Hugging Face files matched {source.files} in {source.ref}")
        paths: list[Path] = []
        for entry in files:
            path = entry["path"]
            destination = downloads / source.ref.replace("/", "--") / safe_name(path)
            if not destination.exists() or destination.stat().st_size == 0:
                url = (
                    f"https://huggingface.co/datasets/{source.ref}/resolve/"
                    f"{urllib.parse.quote(source.revision, safe='')}/"
                    f"{urllib.parse.quote(path, safe='/')}?download=true"
                )
                print(f"  huggingface download {source.ref}/{path}", flush=True)
                download_url(url, destination)
            paths.append(destination)
        return paths, [
            {"kind": "hf", "ref": source.ref, "path": entry["path"], "bytes": path.stat().st_size}
            for entry, path in zip(files, paths)
        ]

    if source.kind == "rfc":
        destination = downloads / "rfc-index.xml"
        if not destination.exists() or destination.stat().st_size == 0:
            print(f"  http download {source.url}", flush=True)
            download_url(source.url, destination)
        return [destination], [{"kind": "rfc-index", "url": source.url, "bytes": destination.stat().st_size}]

    raise RuntimeError(f"unsupported source kind {source.kind}")


# ---------------------------------------------------------------------------
# Archive / record iteration
# ---------------------------------------------------------------------------


def extract_zip_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, work_dir: Path) -> Path:
    extracted = work_dir / "extracted"
    extracted.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(info.filename.encode("utf-8")).hexdigest()[:12]
    destination = extracted / f"{digest}-{safe_name(info.filename)}"
    if destination.exists() and destination.stat().st_size == info.file_size:
        return destination
    with zf.open(info) as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target, length=4 * 1024 * 1024)
    return destination


def should_extract(name: str, size: int) -> bool:
    lowered = name.lower()
    if lowered.endswith((".parquet", ".tar", ".tar.gz", ".tgz", ".tar_1", ".zip", ".zst")):
        return True
    # JSONL/CSV/plain-text readers stream directly; extracting a multi-GB
    # member only wastes disk and time.
    if lowered.endswith((".json", ".jsonl", ".ndjson", ".csv", ".tsv", ".txt", ".md")):
        return False
    # A very large unknown member is easier to inspect from disk.
    return size > 2_000_000_000 and not lowered.endswith((".gz", ".bz2"))


def iter_zip_records(path: Path, source: Source, work_dir: Path) -> Iterator[Any]:
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir() or not selected(info.filename, source.files):
                continue
            if should_extract(info.filename, info.file_size):
                extracted = extract_zip_member(zf, info, work_dir)
                yield from iter_path_records(extracted, source, work_dir)
            else:
                with zf.open(info) as stream:
                    yield from iter_stream_records(stream, info.filename, source, work_dir)


def iter_tar_records(stream: BinaryIO, source: Source, work_dir: Path) -> Iterator[Any]:
    mode = "r|*"
    with tarfile.open(fileobj=stream, mode=mode) as tf:
        for member in tf:
            if not member.isfile() or not selected(member.name, source.files):
                continue
            extracted_file = tf.extractfile(member)
            if extracted_file is None:
                continue
            yield from iter_stream_records(extracted_file, member.name, source, work_dir)


def iter_parquet_records(path: Path, source: Source) -> Iterator[dict[str, Any]]:
    if pq is None:
        raise RuntimeError("pyarrow is required for parquet sources; pip install pyarrow")
    parquet_file = pq.ParquetFile(path)
    available = set(parquet_file.schema.names)
    columns = [field for field in source.fields if field in available] or None
    for batch in parquet_file.iter_batches(batch_size=2000, columns=columns):
        for row in batch.to_pylist():
            yield row


def iter_poetry_records(path: Path, source: Source) -> Iterator[dict[str, str]]:
    """Group line-oriented poetry parquet rows into one document per book.

    The Gutenberg poetry corpus stores one row per line with a ``gutenberg_id``
    and ``line`` column.  Grouping by book is important: treating each line as
    a document would destroy metre, stanza structure, and cross-line context.
    """
    if pq is None:
        raise RuntimeError("pyarrow is required for poetry sources; pip install pyarrow")
    parquet_file = pq.ParquetFile(path)
    books: dict[str, list[str]] = {}
    for batch in parquet_file.iter_batches(batch_size=4000, columns=["line", "gutenberg_id"]):
        for row in batch.to_pylist():
            line = (row.get("line") or "").rstrip()
            if not line:
                continue
            books.setdefault(str(row.get("gutenberg_id")), []).append(line)

    for book_id, lines in books.items():
        poem = normalize_text("\n".join(lines))
        if poem:
            yield {"text": poem, "gutenberg_id": book_id}


def iter_jsonl_records(stream: BinaryIO) -> Iterator[Any]:
    text = io.TextIOWrapper(stream, encoding="utf-8", errors="replace")
    try:
        for line in text:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
    finally:
        try:
            text.detach()
        except Exception:
            pass


def iter_json_records(stream: BinaryIO) -> Iterator[Any]:
    if ijson is not None:
        try:
            yielded = False
            for item in ijson.items(stream, "item"):
                yielded = True
                yield item
            if yielded:
                return
        except Exception:
            pass
        try:
            stream.seek(0)
        except Exception:
            pass

    # Small JSON objects (for example one SEC filing per file) are safe to load.
    try:
        size = stream.seek(0, os.SEEK_END)
        stream.seek(0)
    except Exception:
        size = 0
    if size > 512 * 1024 * 1024:
        raise RuntimeError("large JSON file needs ijson; install ijson")
    data = json.load(io.TextIOWrapper(stream, encoding="utf-8", errors="replace"))
    if isinstance(data, list):
        yield from data
    else:
        yield data


def iter_csv_records(stream: BinaryIO, source: Source) -> Iterator[dict[str, str]]:
    text = io.TextIOWrapper(stream, encoding="utf-8", errors="replace", newline="")
    try:
        sample = text.read(64 * 1024)
        if not sample:
            return
        text.seek(0)
        delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
        reader = csv.DictReader(text, delimiter=delimiter)
        if reader.fieldnames:
            reader.fieldnames = [name.lstrip("\ufeff") for name in reader.fieldnames]
        for row in reader:
            yield {key.lstrip("\ufeff"): value for key, value in row.items()}
    finally:
        try:
            text.detach()
        except Exception:
            pass


def iter_text_records(stream: BinaryIO) -> Iterator[str]:
    text = io.TextIOWrapper(stream, encoding="utf-8", errors="replace")
    try:
        yield text.read(8_000_000)
    finally:
        try:
            text.detach()
        except Exception:
            pass


def iter_stream_records(
    stream: BinaryIO,
    name: str,
    source: Source,
    work_dir: Path,
) -> Iterator[Any]:
    lowered = name.lower()

    if source.fmt == "rfc":
        yield from iter_rfc_records(stream, source)
        return

    if lowered.endswith((".tar", ".tar_1", ".tgz", ".tar.gz")):
        yield from iter_tar_records(stream, source, work_dir)
        return

    if lowered.endswith(".gz"):
        with gzip.GzipFile(fileobj=stream) as gz:
            yield from iter_stream_records(gz, name[:-3], source, work_dir)
        return

    if lowered.endswith(".bz2"):
        with bz2.BZ2File(stream) as bz:
            yield from iter_stream_records(bz, name[:-4], source, work_dir)
        return

    if lowered.endswith(".zip"):
        with zipfile.ZipFile(stream) as nested:
            for info in nested.infolist():
                if info.is_dir() or not selected(info.filename, source.files):
                    continue
                with nested.open(info) as nested_stream:
                    yield from iter_stream_records(nested_stream, info.filename, source, work_dir)
        return

    fmt = source.fmt
    if not fmt:
        if lowered.endswith((".jsonl", ".ndjson")):
            fmt = "jsonl"
        elif lowered.endswith(".json"):
            fmt = "json"
        elif lowered.endswith((".csv", ".tsv")):
            fmt = "csv"
        elif lowered.endswith((".txt", ".md", ".text", ".rst")):
            fmt = "text"

    if fmt == "jsonl":
        yield from iter_jsonl_records(stream)
    elif fmt == "json":
        yield from iter_json_records(stream)
    elif fmt == "csv":
        yield from iter_csv_records(stream, source)
    elif fmt == "text":
        yield from iter_text_records(stream)
    else:
        # Last resort: treat unknown text-like members as prose.
        yield from iter_text_records(stream)


def iter_path_records(path: Path, source: Source, work_dir: Path) -> Iterator[Any]:
    if zipfile.is_zipfile(path):
        yield from iter_zip_records(path, source, work_dir)
        return
    if tarfile.is_tarfile(path):
        with tarfile.open(path, mode="r:*") as tf:
            for member in tf:
                if not member.isfile() or not selected(member.name, source.files):
                    continue
                extracted_file = tf.extractfile(member)
                if extracted_file is not None:
                    yield from iter_stream_records(extracted_file, member.name, source, work_dir)
        return
    if path.suffix.lower() == ".parquet":
        if source.fmt == "poetry":
            yield from iter_poetry_records(path, source)
        else:
            yield from iter_parquet_records(path, source)
        return
    with path.open("rb") as stream:
        yield from iter_stream_records(stream, path.name, source, work_dir)


# ---------------------------------------------------------------------------
# RFCs
# ---------------------------------------------------------------------------


def iter_rfc_records(stream: BinaryIO, source: Source) -> Iterator[dict[str, str]]:
    import xml.etree.ElementTree as ET

    root = ET.parse(stream).getroot()
    entries: list[dict[str, str]] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag != "rfc-entry":
            continue
        values: dict[str, str] = {}
        for child in element.iter():
            child_tag = child.tag.rsplit("}", 1)[-1]
            if child_tag in {"doc-id", "title", "abstract", "date", "status", "stream"} and child.text:
                values[child_tag] = normalize_text(child.text)
        doc_id = values.get("doc-id", "")
        match = re.search(r"(\d+)", doc_id)
        if not match:
            continue
        values["number"] = match.group(1)
        entries.append(values)

    # Fetch RFC text with a bounded number of concurrent requests.  The sink
    # stops consumption when the collection budget is reached; the executor is
    # cancelled by the generator's context manager on the way out.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def fetch(entry: dict[str, str]) -> dict[str, str] | None:
        number = entry["number"]
        url = RFC_TEXT_URL.format(number=number)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read(4_000_000).decode("utf-8", errors="replace")
        except Exception:
            return None
        entry = dict(entry)
        entry["text"] = body
        return entry

    # Submit in bounded batches instead of queueing all ~10k RFCs at once.
    # If the consumer stops at the byte cap, only the current small batch has
    # been requested.
    for start in range(0, len(entries), 48):
        batch = entries[start : start + 48]
        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = [executor.submit(fetch, entry) for entry in batch]
            for future in as_completed(futures):
                record = future.result()
                if record:
                    yield record


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build_collection(
    collection: Collection,
    max_bytes: int,
    output_dir: Path,
    work_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    text_path = output_dir / f"{collection.name}.txt"
    sink = TextSink(
        text_path,
        max_bytes=max_bytes,
        min_chars=collection.min_chars,
        max_doc_chars=collection.max_doc_chars,
    )
    source_records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    print(f"building {collection.name}: cap {human_bytes(max_bytes)}", flush=True)
    try:
        for source in collection.sources:
            if sink.bytes >= sink.max_bytes:
                break
            source_docs = 0
            source_bytes = 0
            started = time.monotonic()
            source_entry: dict[str, Any] = {
                "kind": source.kind,
                "ref": source.ref or source.url,
                "files": list(source.files),
                "format": source.fmt,
                "fields": list(source.fields),
                "license": source.license,
                "license_url": source.license_url,
                "homepage": source.homepage,
                "notes": source.notes,
                "required": source.required,
            }
            try:
                paths, downloads = materialize_source(source, collection, work_dir)
                source_entry["downloads"] = downloads
                source_limit = source.max_bytes or (sink.max_bytes - sink.bytes)
                source_start = sink.bytes
                for path in paths:
                    for record in iter_path_records(path, source, work_dir):
                        text = record_to_text(record, source, collection)
                        if not text:
                            continue
                        before = sink.bytes
                        if sink.add(text):
                            source_docs += 1
                            source_bytes += sink.bytes - before
                        if sink.bytes >= sink.max_bytes:
                            break
                        if source_limit and sink.bytes - source_start >= source_limit:
                            break
                    if sink.bytes >= sink.max_bytes:
                        break
                    if source_limit and sink.bytes - source_start >= source_limit:
                        break
                source_entry.update(
                    {
                        "documents": source_docs,
                        "bytes": source_bytes,
                        "elapsed_seconds": round(time.monotonic() - started, 1),
                    }
                )
                if source.required and source_docs == 0:
                    raise RuntimeError(f"required source produced no documents: {source.ref}")
                print(
                    f"  source {source.ref or source.url}: {source_docs:,} docs, "
                    f"{human_bytes(source_bytes)}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001 - optional sources may fail independently
                source_entry["error"] = str(exc)
                errors.append({"source": source.ref or source.url, "error": str(exc)})
                if source.required:
                    raise
                print(f"  optional source failed: {source.ref or source.url}: {exc}", flush=True)
            source_records.append(source_entry)
    finally:
        sink.close()

    if sink.documents == 0:
        raise RuntimeError(f"{collection.name}: no documents were produced")

    digest = sha256_file(text_path)
    size = text_path.stat().st_size
    generated_at = utc_now()
    release_tag = f"corpora-{collection.name}"
    manifest = {
        "collection": collection.name,
        "title": collection.title,
        "domain": collection.domain,
        "description": collection.description,
        "release_tag": release_tag,
        "file": text_path.name,
        "bytes": size,
        "sha256": digest,
        "documents": sink.documents,
        "max_bytes": max_bytes,
        "generated_at": generated_at,
        "builder": "scripts/build_diverse_corpus.py",
        "repo": "shemshallah/NaNROUTER",
        "license_summary": sorted({source.license for source in collection.sources}),
        "sources": source_records,
        "errors": errors,
    }
    sources_payload = {
        "collection": collection.name,
        "generated_at": generated_at,
        "release_tag": release_tag,
        "layout": "UTF-8 text; documents separated by one blank line",
        "sources": source_records,
        "errors": errors,
    }
    (output_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "SOURCES.json").write_text(
        json.dumps(sources_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "SHA256SUMS").write_text(
        f"{digest}  {text_path.name}\n",
        encoding="utf-8",
    )
    notes = (
        f"{collection.title}.\n\n"
        f"Domain: {collection.domain}.\n"
        f"One UTF-8 text file; documents are separated by a blank line. "
        f"This release is a deterministic-ish sample capped at {human_bytes(max_bytes)}.\n"
        f"Sources and licenses: see {collection.name}.SOURCES.json and the "
        f"repository's corpora/domains/README.md.\n"
        f"Built by .github/workflows/fetch-diverse-corpus.yml. "
        f"NaNROUTER does not claim ownership of the source text."
    )
    (output_dir / "RELEASE.json").write_text(
        json.dumps(
            {"tag": release_tag, "title": f"Corpus: {collection.title}", "notes": notes},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"finished {collection.name}: {sink.documents:,} docs, "
        f"{human_bytes(size)}, sha256 {digest}",
        flush=True,
    )
    return manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def check_registry() -> None:
    seen: set[str] = set()
    for name, collection in COLLECTIONS.items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
            raise ValueError(f"invalid collection name: {name!r}")
        if name in seen:
            raise ValueError(f"duplicate collection: {name}")
        seen.add(name)
        if collection.name != name:
            raise ValueError(f"{name}: collection.name mismatch: {collection.name}")
        if collection.max_mb <= 0:
            raise ValueError(f"{name}: max_mb must be positive")
        if not collection.sources:
            raise ValueError(f"{name}: no sources")
        for source in collection.sources:
            source.validate(name)
    print(f"OK: {len(COLLECTIONS)} collections")
    for name, collection in COLLECTIONS.items():
        print(
            f"  {name:16s} {collection.max_mb:5d} MB  "
            f"{collection.domain[:52]:52s} {len(collection.sources)} source(s)"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", help="collection name")
    parser.add_argument("--max-mb", type=int, default=0, help="override collection cap in MB")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--keep-work", action="store_true", help="keep downloaded/extracted work files")
    parser.add_argument("--list", action="store_true", help="list collections as JSON")
    parser.add_argument("--check", action="store_true", help="validate the registry and exit")
    args = parser.parse_args(argv)

    if args.list:
        print(
            json.dumps(
                {
                    name: {
                        "title": collection.title,
                        "domain": collection.domain,
                        "description": collection.description,
                        "max_mb": collection.max_mb,
                        "sources": [
                            {
                                "kind": source.kind,
                                "ref": source.ref or source.url,
                                "license": source.license,
                                "required": source.required,
                            }
                            for source in collection.sources
                        ],
                    }
                    for name, collection in COLLECTIONS.items()
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.check:
        check_registry()
        return 0

    if not args.collection:
        parser.error("--collection is required unless --list or --check is used")
    if args.collection not in COLLECTIONS:
        parser.error(f"unknown collection {args.collection!r}; use --list")

    collection = COLLECTIONS[args.collection]
    max_mb = args.max_mb or collection.max_mb
    if max_mb <= 0:
        parser.error("--max-mb must be positive")
    max_bytes = max_mb * 1_000_000
    output_dir = args.output_dir or Path("build") / "corpora" / collection.name
    work_dir = args.work_dir or Path("/tmp") / "nanrouter-corpus" / collection.name

    try:
        build_collection(collection, max_bytes, output_dir, work_dir)
    finally:
        if not args.keep_work:
            shutil.rmtree(work_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
