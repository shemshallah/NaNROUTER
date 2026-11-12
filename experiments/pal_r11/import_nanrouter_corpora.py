#!/usr/bin/env python3
"""Strict, document-disjoint NaNROUTER Release corpus importer for PAL R11.

Consumes ONLY verified archives from shemshallah/NaNROUTER/corpora/*.
Outputs independent exact-text UTF-8 documents, NEVER a merged fake stream.
Checkpoint/weights are not modified by this utility.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import tarfile
from collections import Counter

REPO = "shemshallah/NaNROUTER"
SALT = b"PAL-R11-book-split-v1:"
# Existing NaNROUTER HW5 overlap exclusion, conservative, not a proof of
# independence from every past PAL training source.
HW5_IDS = {
    2600,2000,2701,4300,2554,1400,1260,1342,345,98,1661,76,74,84,
    174,36,1322,1497,1232,6130,1727
}
BOOK_RE = re.compile(r"(?:^|/)([0-9]+)--[^/]*\.txt$", re.I)
MAX_BOOK_BYTES = 2_000_000
SPLITS = ("train","dev","test")

def digest_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def split_of(gid):
    n = int.from_bytes(hashlib.sha256(SALT + str(gid).encode()).digest()[:8], "big") % 100
    return "train" if n < 90 else ("dev" if n < 95 else "test")

def import_one(archive, out, existing_ids, existing_hashes, counters, totals, sources, max_bytes):
    archive = pathlib.Path(archive)
    actual_archive_sha = digest_file(archive)
    p = subprocess.Popen(["zstd", "-dc", str(archive)], stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=p.stdout, mode="r|") as tf:
            for member in tf:
                if not member.isfile():
                    continue
                m = BOOK_RE.search(member.name)
                if not m or member.size > MAX_BOOK_BYTES or member.size < 6000:
                    counters["excluded_filename_or_size"] += 1
                    continue
                gid = int(m.group(1))
                if gid in HW5_IDS:
                    counters["excluded_known_HW5_id"] += 1
                    continue
                if gid in existing_ids:
                    counters["duplicate_gutenberg_id"] += 1
                    continue
                split = split_of(gid)
                if max_bytes and totals[split] + member.size > max_bytes:
                    counters["sample_limit_" + split] += 1
                    continue
                fh = tf.extractfile(member)
                if fh is None:
                    continue
                raw = fh.read()
                try:
                    decoded = raw.decode("utf-8", errors="strict")
                except UnicodeDecodeError:
                    counters["invalid_utf8"] += 1
                    continue
                if sum(c.isalpha() for c in decoded) < len(decoded) * 0.45:
                    counters["low_alpha"] += 1
                    continue
                source_sha = hashlib.sha256(raw).hexdigest()
                if source_sha in existing_hashes:
                    counters["duplicate_exact_text"] += 1
                    continue
                existing_ids.add(gid)
                existing_hashes.add(source_sha)
                target = out / split / (str(gid) + ".txt")
                target.write_bytes(raw)
                totals[split] += len(raw)
                sources.append({
                    "gutenberg_id": gid, "split": split, "bytes": len(raw),
                    "sha256": source_sha, "release_archive": archive.name,
                    "archive_member": member.name,
                })
                counters["accepted_" + split] += 1
    finally:
        if p.stdout:
            p.stdout.close()
        status = p.wait()
        if status != 0:
            raise RuntimeError(f"zstd decompression failed ({status}): {archive}")
    return {"path":archive.name,"sha256":actual_archive_sha}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", action="append", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--max-bytes-per-split", type=int, default=0,
                        help="0=unlimited (full training); positive=sized smoke sample")
    args = parser.parse_args()
    if args.max_bytes_per_split < 0:
        parser.error("negative limit")
    args.out.mkdir(parents=True, exist_ok=True)
    if any((args.out / s).exists() for s in SPLITS):
        parser.error("output split folders already exist (refuse accidental mix)")
    for split in SPLITS:
        (args.out / split).mkdir()
    seen_ids, seen_hashes, counters, totals, sources = set(), set(), Counter(), Counter(), [], 
    archives = []
    for archive in sorted(args.archive, key=str):
        archives.append(import_one(archive,args.out,seen_ids,seen_hashes,
                                   counters,totals,sources,args.max_bytes_per_split))
    if not all(counters["accepted_"+s] for s in SPLITS):
        raise RuntimeError("each split must have at least one document; choose larger archives/limits")
    manifest = {
        "source_repository":REPO, "source_policy":"published corpora/* only",
        "split_policy":"sha256(PAL-R11-book-split-v1:gutenberg_id) % 100; 90/5/5",
        "known_HW5_excluded":sorted(HW5_IDS),
        "cross_source_leakage_note":"Other historical PAL book IDs must be verified separately",
        "archives":archives,"counts":dict(counters),"bytes_by_split":dict(totals),
        "documents":sorted(sources,key=lambda r:(r["split"],r["gutenberg_id"])),
    }
    (args.out / "MANIFEST.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf8")
    (args.out / "SHA256SUMS").write_text("\n".join(
        r["sha256"]+"  "+r["split"]+"/"+str(r["gutenberg_id"])+".txt"
        for r in manifest["documents"])+"\n",encoding="ascii")
    print(json.dumps({k:manifest[k] for k in ("source_repository","counts","bytes_by_split","archives")},indent=2))

if __name__ == "__main__":
    main()
