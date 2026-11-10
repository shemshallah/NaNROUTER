#!/usr/bin/env python3
"""Build public-domain sentence, paragraph, and short-story corpora.

Source: Project Gutenberg (public domain in the USA).
The script downloads the Gutenberg catalog, selects English Text entries,
downloads them politely in parallel, strips the Gutenberg header/footer,
and writes:

  corpora/sentences/sentences-NNNN.txt      one sentence per line
  corpora/paragraphs/paragraphs-NNNN.txt    one paragraph per line
  corpora/short_stories/<id>--<author>--<title>.txt

It also writes MANIFEST.json and SOURCES.jsonl in each category. The payload
is intentionally not committed to git; the GitHub workflow publishes it as
release assets.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

CATALOG_URL = "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv"
USER_AGENT = "NaNROUTER-corpus/1.0 (+https://github.com/shemshallah/NaNROUTER)"
START_RE = re.compile(
    r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*",
    re.IGNORECASE | re.DOTALL,
)
END_RE = re.compile(
    r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*",
    re.IGNORECASE | re.DOTALL,
)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
ABBREVIATIONS = {
    "mr.",
    "mrs.",
    "ms.",
    "dr.",
    "st.",
    "jr.",
    "sr.",
    "vs.",
    "etc.",
    "e.g.",
    "i.e.",
    "no.",
    "vol.",
    "ch.",
    "p.",
    "pp.",
    "cf.",
    "al.",
    "prof.",
    "rev.",
    "hon.",
    "capt.",
    "col.",
    "gen.",
    "lt.",
    "sgt.",
    "maj.",
    "adm.",
    "gov.",
    "sen.",
    "rep.",
    "pres.",
}
CATEGORY_SHORT_STORIES = "Category: Short Stories"


def fetch_url(url: str, destination: Path, retries: int = 4, timeout: int = 90) -> bool:
    """Download url to destination. Returns True on success."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                with destination.open("wb") as handle:
                    shutil.copyfileobj(response, handle)
            if destination.stat().st_size > 0:
                return True
        except Exception as exc:  # noqa: BLE001 - network failures vary
            if attempt == retries:
                print(f"WARN: failed {url}: {exc}", file=sys.stderr)
            else:
                time.sleep(1.5 ** attempt)
    destination.unlink(missing_ok=True)
    return False


def download_catalog(work_dir: Path) -> Path:
    catalog = work_dir / "pg_catalog.csv"
    if catalog.exists() and catalog.stat().st_size > 1_000_000:
        return catalog
    print(f"Downloading catalog: {CATALOG_URL}")
    if not fetch_url(CATALOG_URL, catalog, retries=5, timeout=180):
        raise SystemExit("Could not download the Project Gutenberg catalog")
    print(f"Catalog: {catalog.stat().st_size:,} bytes")
    return catalog


def languages(row: dict[str, str]) -> set[str]:
    return {part.strip() for part in (row.get("Language") or "").split(";") if part.strip()}


def categories(row: dict[str, str]) -> list[str]:
    return [part.strip() for part in (row.get("Bookshelves") or "").split(";") if part.strip()]


def select_books(
    rows: list[dict[str, str]], max_books: int, max_short_stories: int
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    english = [
        row
        for row in rows
        if (row.get("Type") or "") == "Text" and "en" in languages(row)
    ]
    english.sort(key=lambda row: int(row["Text#"]))

    short_stories = [row for row in english if CATEGORY_SHORT_STORIES in categories(row)]
    short_stories = short_stories[: min(max_short_stories, max_books)]
    short_ids = {row["Text#"] for row in short_stories}

    other = [row for row in english if row["Text#"] not in short_ids]

    # Round-robin across the first bookshelf category for breadth.
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in other:
        row_categories = categories(row)
        key = row_categories[0] if row_categories else "Uncategorized"
        groups[key].append(row)

    queues = [
        deque(group)
        for _, group in sorted(groups.items(), key=lambda item: len(item[1]), reverse=True)
    ]
    selected = list(short_stories)
    while len(selected) < max_books and queues:
        for queue in list(queues):
            if queue and len(selected) < max_books:
                selected.append(queue.popleft())
            if not queue:
                queues.remove(queue)
    return selected, short_stories


def book_urls(book_id: str) -> list[str]:
    return [
        f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt",
        f"https://www.gutenberg.org/files/{book_id}/{book_id}-0.txt",
        f"https://www.gutenberg.org/ebooks/{book_id}.txt.utf-8",
    ]


def download_book(
    row: dict[str, str], raw_dir: Path
) -> tuple[dict[str, str], Path | None, str | None]:
    book_id = row["Text#"]
    destination = raw_dir / f"{book_id}.txt"
    if destination.exists() and destination.stat().st_size > 0:
        return row, destination, "cached"
    for url in book_urls(book_id):
        if fetch_url(url, destination, retries=2):
            return row, destination, url
    return row, None, None


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    match = START_RE.search(text)
    if match:
        text = text[match.end() :]
    match = END_RE.search(text)
    if match:
        text = text[: match.start()]
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def iter_paragraphs(text: str):
    for block in re.split(r"\n\s*\n", text):
        paragraph = " ".join(block.split())
        if not (120 <= len(paragraph) <= 4000):
            continue
        if "project gutenberg" in paragraph.lower():
            continue
        letters = sum(char.isalpha() for char in paragraph)
        if letters < len(paragraph) * 0.45:
            continue
        yield paragraph


def split_sentences(paragraph: str) -> list[str]:
    parts = SENTENCE_SPLIT_RE.split(paragraph)
    sentences: list[str] = []
    current = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not current:
            current = part
            continue
        words = current.split()
        last = words[-1].lower().strip("\"'“”‘’()[]") if words else ""
        if last in ABBREVIATIONS:
            current = f"{current} {part}"
        else:
            sentences.append(current)
            current = part
    if current:
        sentences.append(current)
    return sentences


def iter_sentences(text: str):
    for paragraph in iter_paragraphs(text):
        for sentence in split_sentences(paragraph):
            sentence = " ".join(sentence.split())
            if not (30 <= len(sentence) <= 500):
                continue
            if "project gutenberg" in sentence.lower():
                continue
            letters = sum(char.isalpha() for char in sentence)
            if letters < len(sentence) * 0.45:
                continue
            yield sentence


def slugify(value: str, max_length: int = 80) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return (value[:max_length].strip("-") or "untitled")


class ShardWriter:
    def __init__(self, directory: Path, prefix: str, max_lines: int):
        self.directory = directory
        self.prefix = prefix
        self.max_lines = max_lines
        self.index = 0
        self.count = 0
        self.total = 0
        self.handle = None
        self.path = None
        self._open()

    def _open(self) -> None:
        self.index += 1
        self.count = 0
        self.path = self.directory / f"{self.prefix}-{self.index:04d}.txt"
        self.handle = self.path.open("w", encoding="utf-8")

    def write(self, line: str) -> None:
        if self.count >= self.max_lines:
            self.handle.close()
            self._open()
        self.handle.write(line + "\n")
        self.count += 1
        self.total += 1

    def close(self) -> None:
        if self.handle:
            self.handle.close()
            self.handle = None

    @property
    def shards(self) -> int:
        return self.index


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def directory_bytes(directory: Path, patterns: tuple[str, ...]) -> int:
    total = 0
    for pattern in patterns:
        for path in directory.glob(pattern):
            if path.is_file():
                total += path.stat().st_size
    return total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-books", type=int, default=10000)
    parser.add_argument("--max-short-stories", type=int, default=4128)
    parser.add_argument("--output-root", type=Path, default=Path("corpora"))
    parser.add_argument("--work-dir", type=Path, default=Path("/tmp/nanrouter-public-domain"))
    parser.add_argument("--max-workers", type=int, default=8)
    args = parser.parse_args()

    if args.max_books < 1:
        parser.error("--max-books must be >= 1")

    args.work_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = args.work_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    catalog = download_catalog(args.work_dir)
    with catalog.open(newline="", encoding="utf-8", errors="replace") as handle:
        rows = list(csv.DictReader(handle))
    selected, short_stories = select_books(rows, args.max_books, args.max_short_stories)
    short_ids = {row["Text#"] for row in short_stories}
    print(f"Selected {len(selected):,} books ({len(short_stories):,} short-story books)")

    output_sentences = args.output_root / "sentences"
    output_paragraphs = args.output_root / "paragraphs"
    output_stories = args.output_root / "short_stories"
    for directory in (output_sentences, output_paragraphs, output_stories):
        directory.mkdir(parents=True, exist_ok=True)

    # Remove previous generated payload but keep tracked README/SOURCES/LICENSE/.gitignore.
    for directory, patterns in (
        (output_sentences, ("sentences-*.txt", "SOURCES.jsonl", "MANIFEST.json")),
        (output_paragraphs, ("paragraphs-*.txt", "SOURCES.jsonl", "MANIFEST.json")),
        (output_stories, ("*.txt", "SOURCES.jsonl", "MANIFEST.json")),
    ):
        for pattern in patterns:
            for path in directory.glob(pattern):
                if path.name in {"README.md", "SOURCES.json", ".gitignore", "LICENSE.txt"}:
                    continue
                path.unlink()

    sentence_writer = ShardWriter(output_sentences, "sentences", 1_000_000)
    paragraph_writer = ShardWriter(output_paragraphs, "paragraphs", 500_000)

    metadata: list[dict] = []
    story_metadata: list[dict] = []
    downloaded = 0
    failed = 0

    def process_book(row: dict[str, str], path: Path, source_url: str | None) -> None:
        nonlocal downloaded
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"WARN: could not read {path}: {exc}", file=sys.stderr)
            return
        cleaned = clean_text(text)
        if not cleaned:
            return
        downloaded += 1
        book_id = row["Text#"]
        title = row.get("Title") or ""
        authors = row.get("Authors") or ""
        is_short_story = book_id in short_ids

        sentence_count = 0
        for sentence in iter_sentences(cleaned):
            sentence_writer.write(sentence)
            sentence_count += 1
        paragraph_count = 0
        for paragraph in iter_paragraphs(cleaned):
            paragraph_writer.write(paragraph)
            paragraph_count += 1

        meta = {
            "id": book_id,
            "title": title,
            "authors": authors,
            "bookshelves": row.get("Bookshelves") or "",
            "subjects": row.get("Subjects") or "",
            "source_url": source_url or "",
            "bytes": len(cleaned.encode("utf-8")),
            "short_story": is_short_story,
            "sentences": sentence_count,
            "paragraphs": paragraph_count,
        }
        metadata.append(meta)
        if is_short_story:
            story_metadata.append(meta)
            filename = (
                f"{book_id}--{slugify(authors)}--{slugify(title)}.txt"
            )
            (output_stories / filename).write_text(cleaned + "\n", encoding="utf-8")
        path.unlink(missing_ok=True)

    with ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as executor:
        futures = {
            executor.submit(download_book, row, raw_dir): row for row in selected
        }
        completed = 0
        for future in as_completed(futures):
            row = futures[future]
            completed += 1
            try:
                result_row, path, source_url = future.result()
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"WARN: download failed for {row['Text#']}: {exc}", file=sys.stderr)
                continue
            if path is None:
                failed += 1
                continue
            process_book(result_row, path, source_url)
            if completed % 250 == 0:
                print(f"  processed {completed:,}/{len(selected):,} books")

    sentence_writer.close()
    paragraph_writer.close()

    metadata.sort(key=lambda item: int(item["id"]))
    story_metadata.sort(key=lambda item: int(item["id"]))
    write_jsonl(output_sentences / "SOURCES.jsonl", metadata)
    write_jsonl(output_paragraphs / "SOURCES.jsonl", metadata)
    write_jsonl(output_stories / "SOURCES.jsonl", story_metadata)

    generated_at = datetime.now(timezone.utc).isoformat()
    selection = {
        "max_books": args.max_books,
        "max_short_stories": args.max_short_stories,
        "selected": len(selected),
        "short_story_books_selected": len(short_stories),
        "downloaded": downloaded,
        "failed": failed,
    }
    common = {
        "generated_at": generated_at,
        "source": "Project Gutenberg",
        "catalog_url": CATALOG_URL,
        "license": "Public domain in the USA; Project Gutenberg License",
        "license_url": "https://www.gutenberg.org/policy/license.html",
        "selection": selection,
    }

    sentence_manifest = {
        **common,
        "release_tag": "corpora-sentences",
        "stats": {
            "books": downloaded,
            "sentences": sentence_writer.total,
            "shards": sentence_writer.shards,
            "bytes": directory_bytes(output_sentences, ("sentences-*.txt",)),
        },
    }
    paragraph_manifest = {
        **common,
        "release_tag": "corpora-paragraphs",
        "stats": {
            "books": downloaded,
            "paragraphs": paragraph_writer.total,
            "shards": paragraph_writer.shards,
            "bytes": directory_bytes(output_paragraphs, ("paragraphs-*.txt",)),
        },
    }
    story_manifest = {
        **common,
        "release_tag": "corpora-short-stories",
        "stats": {
            "books": len(story_metadata),
            "stories": len(story_metadata),
            "bytes": directory_bytes(output_stories, ("*.txt",)),
        },
    }

    (output_sentences / "MANIFEST.json").write_text(
        json.dumps(sentence_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_paragraphs / "MANIFEST.json").write_text(
        json.dumps(paragraph_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_stories / "MANIFEST.json").write_text(
        json.dumps(story_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(json.dumps(
        {
            "sentences": sentence_manifest["stats"],
            "paragraphs": paragraph_manifest["stats"],
            "short_stories": story_manifest["stats"],
            "downloaded": downloaded,
            "failed": failed,
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
