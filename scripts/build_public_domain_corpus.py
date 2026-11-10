#!/usr/bin/env python3
"""Build public-domain sentence, paragraph, and short-story corpora.

Source: Project Gutenberg (public domain in the USA).
The script downloads the Gutenberg catalog, selects English Text entries,
downloads them politely in parallel, strips the Gutenberg header/footer,
and writes per-book files grouped into batch directories:

  corpora/sentences/batch-0001/<id>--<author>--<title>.txt
  corpora/paragraphs/batch-0001/<id>--<author>--<title>.txt
  corpora/short_stories/batch-0001/<id>--<author>--<title>.txt

Each batch directory becomes its own GitHub Release
(corpora-sentences-0001, corpora-paragraphs-0001,
corpora-short-stories-0001, ...), while the full category release contains
all batches. The payload is intentionally not committed to git.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import time
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
    "mr.", "mrs.", "ms.", "dr.", "st.", "jr.", "sr.", "vs.", "etc.",
    "e.g.", "i.e.", "no.", "vol.", "ch.", "p.", "pp.", "cf.", "al.",
    "prof.", "rev.", "hon.", "capt.", "col.", "gen.", "lt.", "sgt.",
    "maj.", "adm.", "gov.", "sen.", "rep.", "pres.",
}
CATEGORY_SHORT_STORIES = "Category: Short Stories"
PROTECTED_NAMES = {"README.md", "SOURCES.json", ".gitignore", "LICENSE.txt"}


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


def book_filename(row: dict[str, str]) -> str:
    book_id = row["Text#"]
    authors = slugify(row.get("Authors") or "unknown")
    title = slugify(row.get("Title") or "untitled")
    return f"{book_id}--{authors}--{title}.txt"


def batch_for(rows: list[dict[str, str]], batch_size: int) -> dict[str, int]:
    ordered = sorted(rows, key=lambda row: int(row["Text#"]))
    return {
        row["Text#"]: (index // batch_size) + 1
        for index, row in enumerate(ordered)
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build_batch_manifest(
    directory: Path, metadata_by_batch: dict[int, list[dict]], prefix: str
) -> list[dict]:
    batches = []
    for batch, rows in sorted(metadata_by_batch.items()):
        batch_dir = directory / f"batch-{batch:04d}"
        files = sorted(batch_dir.glob("*.txt")) if batch_dir.is_dir() else []
        if not files:
            continue
        batches.append(
            {
                "batch": batch,
                "tag": f"{prefix}-{batch:04d}",
                "books": len(rows),
                "files": len(files),
                "bytes": sum(path.stat().st_size for path in files),
            }
        )
    return batches


def cleanup_output(directory: Path, patterns: tuple[str, ...]) -> None:
    for pattern in patterns:
        for path in directory.glob(pattern):
            if path.name in PROTECTED_NAMES:
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-books", type=int, default=10000)
    parser.add_argument("--max-short-stories", type=int, default=4128)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--output-root", type=Path, default=Path("corpora"))
    parser.add_argument("--work-dir", type=Path, default=Path("/tmp/nanrouter-public-domain"))
    parser.add_argument("--max-workers", type=int, default=8)
    args = parser.parse_args()

    if args.max_books < 1:
        parser.error("--max-books must be >= 1")
    if args.batch_size < 1:
        parser.error("--batch-size must be >= 1")

    args.work_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = args.work_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    catalog = download_catalog(args.work_dir)
    with catalog.open(newline="", encoding="utf-8", errors="replace") as handle:
        rows = list(csv.DictReader(handle))
    selected, short_stories = select_books(rows, args.max_books, args.max_short_stories)
    selected_batch = batch_for(selected, args.batch_size)
    short_batch = batch_for(short_stories, args.batch_size)
    short_ids = {row["Text#"] for row in short_stories}
    print(
        f"Selected {len(selected):,} books ({len(short_stories):,} short-story books); "
        f"batch size {args.batch_size}"
    )

    output_sentences = args.output_root / "sentences"
    output_paragraphs = args.output_root / "paragraphs"
    output_stories = args.output_root / "short_stories"
    for directory in (output_sentences, output_paragraphs, output_stories):
        directory.mkdir(parents=True, exist_ok=True)

    cleanup_output(
        output_sentences,
        ("batch-*", "sentences-*.txt", "SOURCES.jsonl", "MANIFEST.json", "BATCHES.json"),
    )
    cleanup_output(
        output_paragraphs,
        ("batch-*", "paragraphs-*.txt", "SOURCES.jsonl", "MANIFEST.json", "BATCHES.json"),
    )
    cleanup_output(
        output_stories,
        ("batch-*", "*.txt", "SOURCES.jsonl", "MANIFEST.json", "BATCHES.json"),
    )

    metadata_by_batch: dict[int, list[dict]] = defaultdict(list)
    story_metadata_by_batch: dict[int, list[dict]] = defaultdict(list)
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
            path.unlink(missing_ok=True)
            return
        downloaded += 1
        book_id = row["Text#"]
        filename = book_filename(row)
        batch = selected_batch.get(book_id, 1)
        is_short_story = book_id in short_ids

        sentence_dir = output_sentences / f"batch-{batch:04d}"
        sentence_dir.mkdir(parents=True, exist_ok=True)
        sentence_path = sentence_dir / filename
        sentence_count = 0
        with sentence_path.open("w", encoding="utf-8") as handle:
            for sentence in iter_sentences(cleaned):
                handle.write(sentence + "\n")
                sentence_count += 1
        if sentence_count == 0:
            sentence_path.unlink(missing_ok=True)

        paragraph_dir = output_paragraphs / f"batch-{batch:04d}"
        paragraph_dir.mkdir(parents=True, exist_ok=True)
        paragraph_path = paragraph_dir / filename
        paragraph_count = 0
        with paragraph_path.open("w", encoding="utf-8") as handle:
            for paragraph in iter_paragraphs(cleaned):
                handle.write(paragraph + "\n")
                paragraph_count += 1
        if paragraph_count == 0:
            paragraph_path.unlink(missing_ok=True)

        meta = {
            "id": book_id,
            "title": row.get("Title") or "",
            "authors": row.get("Authors") or "",
            "bookshelves": row.get("Bookshelves") or "",
            "subjects": row.get("Subjects") or "",
            "source_url": source_url or "",
            "bytes": len(cleaned.encode("utf-8")),
            "short_story": is_short_story,
            "sentences": sentence_count,
            "paragraphs": paragraph_count,
            "batch": batch,
            "sentence_batch_tag": f"corpora-sentences-{batch:04d}",
            "paragraph_batch_tag": f"corpora-paragraphs-{batch:04d}",
        }
        metadata_by_batch[batch].append(meta)

        if is_short_story:
            story_batch = short_batch.get(book_id, 1)
            story_dir = output_stories / f"batch-{story_batch:04d}"
            story_dir.mkdir(parents=True, exist_ok=True)
            (story_dir / filename).write_text(cleaned + "\n", encoding="utf-8")
            story_meta = dict(meta)
            story_meta["batch"] = story_batch
            story_meta["short_story_batch_tag"] = f"corpora-short-stories-{story_batch:04d}"
            story_metadata_by_batch[story_batch].append(story_meta)

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

    all_metadata = sorted(
        (item for items in metadata_by_batch.values() for item in items),
        key=lambda item: int(item["id"]),
    )
    all_story_metadata = sorted(
        (item for items in story_metadata_by_batch.values() for item in items),
        key=lambda item: int(item["id"]),
    )

    write_jsonl(output_sentences / "SOURCES.jsonl", all_metadata)
    write_jsonl(output_paragraphs / "SOURCES.jsonl", all_metadata)
    write_jsonl(output_stories / "SOURCES.jsonl", all_story_metadata)
    for batch, items in metadata_by_batch.items():
        write_jsonl(
            output_sentences / f"batch-{batch:04d}" / "SOURCES.jsonl",
            sorted(items, key=lambda item: int(item["id"])),
        )
        write_jsonl(
            output_paragraphs / f"batch-{batch:04d}" / "SOURCES.jsonl",
            sorted(items, key=lambda item: int(item["id"])),
        )
    for batch, items in story_metadata_by_batch.items():
        write_jsonl(
            output_stories / f"batch-{batch:04d}" / "SOURCES.jsonl",
            sorted(items, key=lambda item: int(item["id"])),
        )

    sentence_batches = build_batch_manifest(
        output_sentences, metadata_by_batch, "corpora-sentences"
    )
    paragraph_batches = build_batch_manifest(
        output_paragraphs, metadata_by_batch, "corpora-paragraphs"
    )
    story_batches = build_batch_manifest(
        output_stories, story_metadata_by_batch, "corpora-short-stories"
    )

    generated_at = datetime.now(timezone.utc).isoformat()
    selection = {
        "max_books": args.max_books,
        "max_short_stories": args.max_short_stories,
        "batch_size": args.batch_size,
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

    sentence_stats = {
        "books": len(all_metadata),
        "sentences": sum(item["sentences"] for item in all_metadata),
        "files": sum(batch["files"] for batch in sentence_batches),
        "batches": len(sentence_batches),
        "bytes": sum(batch["bytes"] for batch in sentence_batches),
    }
    paragraph_stats = {
        "books": len(all_metadata),
        "paragraphs": sum(item["paragraphs"] for item in all_metadata),
        "files": sum(batch["files"] for batch in paragraph_batches),
        "batches": len(paragraph_batches),
        "bytes": sum(batch["bytes"] for batch in paragraph_batches),
    }
    story_stats = {
        "books": len(all_story_metadata),
        "stories": sum(batch["files"] for batch in story_batches),
        "files": sum(batch["files"] for batch in story_batches),
        "batches": len(story_batches),
        "bytes": sum(batch["bytes"] for batch in story_batches),
    }

    documents = {
        output_sentences: {
            "release_tag": "corpora-sentences",
            "batches": sentence_batches,
            "stats": sentence_stats,
        },
        output_paragraphs: {
            "release_tag": "corpora-paragraphs",
            "batches": paragraph_batches,
            "stats": paragraph_stats,
        },
        output_stories: {
            "release_tag": "corpora-short-stories",
            "batches": story_batches,
            "stats": story_stats,
        },
    }
    for directory, document in documents.items():
        manifest = {**common, **document}
        (directory / "MANIFEST.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        batches_document = {
            "generated_at": generated_at,
            "release_tag_prefix": document["release_tag"],
            "batch_size": args.batch_size,
            "batches": document["batches"],
        }
        (directory / "BATCHES.json").write_text(
            json.dumps(batches_document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "sentences": sentence_stats,
                "paragraphs": paragraph_stats,
                "short_stories": story_stats,
                "downloaded": downloaded,
                "failed": failed,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
