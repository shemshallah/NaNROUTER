#!/usr/bin/env python3
"""Fetch and stage WikiText-103 for GitHub Releases.

WikiText-103 is a 103M-token English language-modeling corpus built from
verified Good and Featured Wikipedia articles.  This script downloads the two
official v1 archives, verifies them against their published SHA-1/SHA-256
checksums, extracts the train/validation/test splits, verifies every split,
and writes the manifests and checksums used by the release workflow:

  build/corpora/wikitext103/
    raw/
      wiki.train.raw
      wiki.valid.raw
      wiki.test.raw
      MANIFEST.json
      SOURCES.json
      SHA256SUMS
    tokenized/
      wiki.train.tokens
      wiki.valid.tokens
      wiki.test.tokens
      MANIFEST.json
      SOURCES.json
      SHA256SUMS
    MANIFEST.json
    SOURCES.json
    SHA256SUMS

The payload is intentionally not committed to git.  The workflow publishes
``raw/`` as release ``wikitext103``, ``tokenized/`` as
``wikitext103-tokenized``, and the root metadata as ``wikitext103-latest``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

USER_AGENT = "NaNROUTER-corpus/1.0 (+https://github.com/shemshallah/NaNROUTER)"
REPO = "shemshallah/NaNROUTER"
DATASET = "WikiText-103"
HOMEPAGE = (
    "https://blog.einstein.ai/"
    "the-wikitext-long-term-dependency-language-modeling-dataset/"
)
PAPER = "https://arxiv.org/abs/1609.07843"
LICENSE = "CC-BY-SA-3.0 AND GFDL"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/3.0/"
CITATION = (
    "@misc{merity2016pointer,\n"
    "  title={Pointer Sentinel Mixture Models},\n"
    "  author={Stephen Merity and Caiming Xiong and James Bradbury and Richard Socher},\n"
    "  year={2016},\n"
    "  eprint={1609.07843},\n"
    "  archivePrefix={arXiv},\n"
    "  primaryClass={cs.CL}\n"
    "}"
)

SPLIT_ORDER = ("train", "validation", "test")
SPLIT_STEMS = {
    "train": "wiki.train",
    "validation": "wiki.valid",
    "test": "wiki.test",
}

# Both archives are still served by the original WikiText host.  The
# Hugging Face mirror is used as a fallback for the raw archive because the
# Salesforce S3 bucket that used to host it now returns 403.
VARIANTS = {
    "raw": {
        "dataset_variant": "wikitext-103-raw-v1",
        "archive": "wikitext-103-raw-v1.zip",
        "urls": (
            "https://wikitext.smerity.com/wikitext-103-raw-v1.zip",
            "https://huggingface.co/datasets/segyges/wikitext-103/resolve/main/"
            "wikitext-103-raw-v1.zip",
        ),
        "archive_sha1": "86f2375181b9247049d9c9205fad2b71b274b568",
        "archive_sha256": (
            "91c00ae287f0d699e18605c84afc9e45c192bc6b7797ff8837e5474655a33794"
        ),
        "archive_bytes": 191_984_949,
        "release_tag": "wikitext103",
        "release_title": "WikiText-103 (raw)",
        "extension": ".raw",
        "splits": {
            "train": {
                "file": "wiki.train.raw",
                "sha1": "3d06627c15e834408cfee91293f862c11c1cc9ef",
                "bytes": 540_568_191,
                "lines": 1_801_350,
                "words": 101_425_671,
            },
            "validation": {
                "file": "wiki.valid.raw",
                "sha1": "db78d4db83700cba1b1bf4a9381087043db2876d",
                "bytes": 1_146_846,
                "lines": 3_760,
                "words": 213_886,
            },
            "test": {
                "file": "wiki.test.raw",
                "sha1": "6f1fe2054a940eebfc76b284b09680763b37f5ea",
                "bytes": 1_290_590,
                "lines": 4_358,
                "words": 241_211,
            },
        },
    },
    "tokenized": {
        "dataset_variant": "wikitext-103-v1",
        "archive": "wikitext-103-v1.zip",
        "urls": (
            "https://wikitext.smerity.com/wikitext-103-v1.zip",
        ),
        "archive_sha1": "0aec09a7537b58d4bb65362fee27650eeaba625a",
        "archive_sha256": (
            "242ba0f20b329cfdf1ccc61e9e9e5b59becf189db7f7a81cd2a0e2fc31539590"
        ),
        "archive_bytes": 190_229_076,
        "release_tag": "wikitext103-tokenized",
        "release_title": "WikiText-103 (tokenized)",
        "extension": ".tokens",
        "splits": {
            "train": {
                "file": "wiki.train.tokens",
                "sha1": "b7497e2dfe77e72cfef5e3dbc61b7b53712ac211",
                "bytes": 539_209_157,
                "lines": 1_801_350,
                "words": 101_425_671,
            },
            "validation": {
                "file": "wiki.valid.tokens",
                "sha1": "c326ac59dc587676d58c422eb8a03e119582f92b",
                "bytes": 1_142_309,
                "lines": 3_760,
                "words": 213_886,
            },
            "test": {
                "file": "wiki.test.tokens",
                "sha1": "8a5befc548865cec54ed4273cf87dbbad60d1e47",
                "bytes": 1_281_077,
                "lines": 4_358,
                "words": 241_211,
            },
        },
    },
}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def hash_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha1_file(path: Path) -> str:
    return hash_file(path, "sha1")


def sha256_file(path: Path) -> str:
    return hash_file(path, "sha256")


def write_json(path: Path, data: object) -> None:
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def check_registry() -> None:
    """Validate the offline registry without touching the network."""
    if set(VARIANTS) != {"raw", "tokenized"}:
        raise SystemExit("expected raw and tokenized variants")
    tags = set()
    for name, spec in VARIANTS.items():
        if len(spec["archive_sha1"]) != 40 or len(spec["archive_sha256"]) != 64:
            raise SystemExit(f"{name}: malformed archive checksum")
        if spec["archive_bytes"] <= 0:
            raise SystemExit(f"{name}: archive size must be positive")
        if spec["release_tag"] in tags:
            raise SystemExit(f"duplicate release tag: {spec['release_tag']}")
        tags.add(spec["release_tag"])
        if set(spec["splits"]) != set(SPLIT_ORDER):
            raise SystemExit(f"{name}: split set mismatch")
        for split, meta in spec["splits"].items():
            expected = f"{SPLIT_STEMS[split]}{spec['extension']}"
            if meta["file"] != expected:
                raise SystemExit(f"{name}/{split}: expected {expected}")
            if len(meta["sha1"]) != 40:
                raise SystemExit(f"{name}/{split}: malformed sha1")
            for key in ("bytes", "lines", "words"):
                if meta[key] <= 0:
                    raise SystemExit(f"{name}/{split}: {key} must be positive")


def download_archive(spec: dict, work_dir: Path) -> Path:
    """Download and verify an archive, reusing a verified cached copy."""
    archive = work_dir / spec["archive"]
    if archive.exists() and archive.stat().st_size == spec["archive_bytes"]:
        if (
            sha1_file(archive) == spec["archive_sha1"]
            and sha256_file(archive) == spec["archive_sha256"]
        ):
            print(f"Using verified cached archive: {archive}")
            return archive
        archive.unlink()

    part = archive.with_name(archive.name + ".part")
    errors: list[str] = []
    for url in spec["urls"]:
        for attempt in range(1, 4):
            try:
                print(f"Downloading {url} (attempt {attempt})")
                request = urllib.request.Request(
                    url, headers={"User-Agent": USER_AGENT}
                )
                with urllib.request.urlopen(request, timeout=600) as response:
                    with part.open("wb") as handle:
                        shutil.copyfileobj(response, handle, length=1024 * 1024)
                size = part.stat().st_size
                if size != spec["archive_bytes"]:
                    raise ValueError(
                        f"size {size:,} != expected {spec['archive_bytes']:,}"
                    )
                actual_sha1 = sha1_file(part)
                if actual_sha1 != spec["archive_sha1"]:
                    raise ValueError(f"sha1 {actual_sha1} != {spec['archive_sha1']}")
                actual_sha256 = sha256_file(part)
                if actual_sha256 != spec["archive_sha256"]:
                    raise ValueError(
                        f"sha256 {actual_sha256} != {spec['archive_sha256']}"
                    )
                part.replace(archive)
                print(f"Verified archive: {archive.name} ({size:,} bytes)")
                return archive
            except Exception as exc:  # noqa: BLE001 - network failures vary
                part.unlink(missing_ok=True)
                message = f"{url}: {exc}"
                errors.append(message)
                print(f"WARN: {message}", file=sys.stderr)
                if attempt < 3:
                    time.sleep(2**attempt)
    raise SystemExit(
        "could not download a verified archive:\n  " + "\n  ".join(errors)
    )


def extract_split(archive: Path, spec: dict, split: str, destination: Path) -> None:
    """Extract one split without unpacking unrelated zip members."""
    filename = spec["splits"][split]["file"]
    expected = f"{spec['dataset_variant']}/{filename}"
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        member = expected if expected in names else ""
        if not member:
            matches = [name for name in names if name.rsplit("/", 1)[-1] == filename]
            if len(matches) != 1:
                raise SystemExit(
                    f"{archive.name}: cannot locate {filename} "
                    f"(matches: {len(matches)})"
                )
            member = matches[0]
        with bundle.open(member) as source, destination.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)


def verify_split(path: Path, meta: dict) -> dict:
    size = path.stat().st_size
    if size != meta["bytes"]:
        raise SystemExit(f"{path}: size {size:,} != expected {meta['bytes']:,}")
    actual_sha1 = sha1_file(path)
    if actual_sha1 != meta["sha1"]:
        raise SystemExit(f"{path}: sha1 {actual_sha1} != {meta['sha1']}")
    lines = 0
    words = 0
    with path.open("rb") as handle:
        for line in handle:
            lines += 1
            words += len(line.split())
    if lines != meta["lines"]:
        raise SystemExit(f"{path}: lines {lines:,} != expected {meta['lines']:,}")
    if words != meta["words"]:
        raise SystemExit(f"{path}: words {words:,} != expected {meta['words']:,}")
    return {
        "bytes": size,
        "file": path.name,
        "lines": lines,
        "sha1": actual_sha1,
        "sha256": sha256_file(path),
        "words": words,
    }


def build_variant(
    name: str, spec: dict, output_dir: Path, work_dir: Path
) -> dict:
    variant_dir = output_dir / name
    if variant_dir.exists():
        shutil.rmtree(variant_dir)
    variant_dir.mkdir(parents=True)

    archive = download_archive(spec, work_dir)
    entries = []
    for split in SPLIT_ORDER:
        meta = spec["splits"][split]
        path = variant_dir / meta["file"]
        print(f"Extracting {name}/{meta['file']}")
        extract_split(archive, spec, split, path)
        entry = verify_split(path, meta)
        entry["split"] = split
        entries.append(entry)

    manifest = {
        "archive": {
            "bytes": spec["archive_bytes"],
            "name": spec["archive"],
            "sha1": spec["archive_sha1"],
            "sha256": spec["archive_sha256"],
            "urls": list(spec["urls"]),
        },
        "dataset": DATASET,
        "dataset_variant": spec["dataset_variant"],
        "release_tag": spec["release_tag"],
        "splits": entries,
        "total_bytes": sum(entry["bytes"] for entry in entries),
        "total_lines": sum(entry["lines"] for entry in entries),
        "total_words": sum(entry["words"] for entry in entries),
        "variant": name,
    }
    write_json(variant_dir / "MANIFEST.json", manifest)
    write_json(
        variant_dir / "SOURCES.json",
        {
            "citation": CITATION,
            "dataset": DATASET,
            "dataset_variant": spec["dataset_variant"],
            "homepage": HOMEPAGE,
            "license": LICENSE,
            "license_url": LICENSE_URL,
            "paper": PAPER,
            "release_tag": spec["release_tag"],
            "repo": REPO,
            "sources": [
                {
                    "archive": spec["archive"],
                    "archive_bytes": spec["archive_bytes"],
                    "archive_sha1": spec["archive_sha1"],
                    "archive_sha256": spec["archive_sha256"],
                    "urls": list(spec["urls"]),
                }
            ],
        },
    )
    checksums = "".join(
        f"{entry['sha256']}  {entry['file']}\n" for entry in entries
    )
    (variant_dir / "SHA256SUMS").write_text(checksums, encoding="utf-8")
    print(
        f"{name}: {manifest['total_bytes']:,} bytes, "
        f"{manifest['total_lines']:,} lines, "
        f"{manifest['total_words']:,} words"
    )
    return manifest


def write_combined(output_dir: Path, variants: list[dict]) -> dict:
    generated_at = now_utc()
    manifests_by_name = {entry["variant"]: entry for entry in variants}
    combined = {
        "dataset": DATASET,
        "generated_at": generated_at,
        "homepage": HOMEPAGE,
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "paper": PAPER,
        "path": "corpora/wikitext103",
        "release_tags": [spec["release_tag"] for spec in VARIANTS.values()]
        + ["wikitext103-latest"],
        "repo": REPO,
        "total_bytes": sum(
            entry["total_bytes"] for entry in manifests_by_name.values()
        ),
        "total_lines": sum(
            entry["total_lines"] for entry in manifests_by_name.values()
        ),
        "total_words": sum(
            entry["total_words"] for entry in manifests_by_name.values()
        ),
        "variants": [manifests_by_name[name] for name in VARIANTS],
    }
    write_json(output_dir / "MANIFEST.json", combined)

    sources = []
    for name, spec in VARIANTS.items():
        sources.append(
            {
                "archive": spec["archive"],
                "archive_bytes": spec["archive_bytes"],
                "archive_sha1": spec["archive_sha1"],
                "archive_sha256": spec["archive_sha256"],
                "dataset_variant": spec["dataset_variant"],
                "release_tag": spec["release_tag"],
                "urls": list(spec["urls"]),
                "variant": name,
            }
        )
    write_json(
        output_dir / "SOURCES.json",
        {
            "citation": CITATION,
            "dataset": DATASET,
            "generated_at": generated_at,
            "homepage": HOMEPAGE,
            "license": LICENSE,
            "license_url": LICENSE_URL,
            "paper": PAPER,
            "path": "corpora/wikitext103",
            "repo": REPO,
            "runner": ".github/workflows/fetch-wikitext103.yml",
            "sources": sources,
        },
    )

    lines = []
    for name in VARIANTS:
        for entry in manifests_by_name[name]["splits"]:
            lines.append(
                f"{entry['sha256']}  {name}/{entry['file']}\n"
            )
    (output_dir / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")

    print(
        f"combined: {combined['total_bytes']:,} bytes, "
        f"{combined['total_lines']:,} lines, "
        f"{combined['total_words']:,} words"
    )
    return combined


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build/corpora/wikitext103"),
        help="directory for extracted splits and metadata",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "nanrouter-wikitext103",
        help="directory for verified archive downloads",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the offline registry and exit",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    check_registry()
    if args.check:
        print("WikiText-103 registry OK")
        return 0

    output_dir = args.output_dir.resolve()
    work_dir = args.work_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    manifests = [
        build_variant(name, spec, output_dir, work_dir)
        for name, spec in VARIANTS.items()
    ]
    write_combined(output_dir, manifests)
    print(f"metadata written to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
