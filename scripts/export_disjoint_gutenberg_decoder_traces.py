#!/usr/bin/env python3
"""Export causal frozen HW0 decoder traces from six DEV and six TEST books.

The exact six-document groups are selected by the existing SHA-sorted
native-inverse corpus split. The decoder ROOT is frozen and read-only for
this step. No training, candidate selection, prediction mathematics or
cross-entropy is implemented by this script: it only calls the real decoder
trace reader on distinct document files and combines its raw bitstrings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from build_native_inverse_trigram26_corpus_fixture import split_documents
from build_native_decoder_ce_fixture import parse


def sha(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            d.update(chunk)
    return d.hexdigest()


def export(root: Path, exporter: Path, corpus: Path, output: Path,
           manifest: Path, h: int, a: int, per_book: int) -> dict:
    if not 1 <= per_book <= 5:
        raise ValueError("per-book trace bound must be 1..5")
    if not 0 <= h <= 254 or not 0 <= a <= 254:
        raise ValueError("cannot use void head as context")
    splits = split_documents(corpus)
    for name in ("dev","test"):
        if len(splits[name]) != 6:
            raise ValueError("exactly six independent books required per split")
    output.mkdir(parents=True, exist_ok=True)
    initial = sha(root)
    record = {"schema":"nanrouter-frozen-real-decoder-disjoint-books/1",
              "decoder_root_sha256":initial, "context":[h,a],
              "book_split":"native-inverse deterministic SHA document split",
              "books_per_split":6,"rows_per_book":per_book,
              "training_documents_used_for_decoder":False,
              "groups":{}}
    all_digests = set()
    for group in ("dev","test"):
        lines=[]
        book_records=[]
        for i,(path,data,digest) in enumerate(splits[group]):
            if digest in all_digests:
                raise ValueError("document overlap across splits")
            all_digests.add(digest)
            result = subprocess.run(
                [str(exporter.resolve()),str(root.resolve()),str(path.resolve()),
                 str(h),str(a),str(per_book)],
                check=True, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=180)
            temp = output / f"{group}-{i:02d}.trace"
            temp.write_text(result.stdout,encoding="ascii")
            rows = parse(temp,h,a)
            if len(rows) != per_book:
                raise ValueError(f"insufficient causal contexts: {path}")
            parts = result.stdout.splitlines()
            lines.extend(parts[1:])
            book_records.append({
                "path":str(path.relative_to(corpus)),
                "sha256":digest,"source_bytes":len(data),
                "examples":len(rows),
                "raw_trace_sha256":sha(temp)})
        target=output/f"{group}.trace"
        target.write_text(
            f"FROZEN_DECODER_TRACE_V1 {h} {a} {len(lines)}\n"
            +"\n".join(lines)+"\n",encoding="ascii")
        parse(target,h,a)
        record["groups"][group]={"books":book_records,
                                  "trace_sha256":sha(target),
                                  "rows":len(lines)}
    if sha(root) != initial:
        raise ValueError("frozen decoder model root changed during export")
    manifest.write_text(json.dumps(record,sort_keys=True,indent=2)+"\n")
    print("DISJOINT_GUTENBERG_DECODER_TRACES "+json.dumps({
        "dev_books":len(record["groups"]["dev"]["books"]),
        "test_books":len(record["groups"]["test"]["books"]),
        "dev_rows":record["groups"]["dev"]["rows"],
        "test_rows":record["groups"]["test"]["rows"],
        "root_sha256":initial},sort_keys=True))
    return record


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--exporter",type=Path,required=True)
    p.add_argument("--corpus",type=Path,required=True)
    p.add_argument("--output-dir",type=Path,required=True)
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--h",type=int,default=116)
    p.add_argument("--a",type=int,default=104)
    p.add_argument("--rows-per-book",type=int,default=4)
    q=p.parse_args()
    export(q.root,q.exporter,q.corpus,q.output_dir,q.manifest,
           q.h,q.a,q.rows_per_book)
