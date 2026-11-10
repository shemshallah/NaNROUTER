#!/usr/bin/env python3
"""HW5:0 Gutenberg offline reference: exact text + NaN16 C(256,2) projection.

This is intake/reference storage, NOT a native NaN16 guest, student model,
active BS0 ring, or a claim that 20 MiB text fits losslessly inside 8 MiB.
The fixed-head bank has 256 x 128 bytes; 32,640 canonical mirror pairs
have 256 bytes each. Directed byte transitions and distance-two edges
are projected to opposite lanes; exact ordered triples live in SQLite.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import shutil
import sqlite3
import struct
import tarfile
from urllib.request import Request, urlopen

ROUTE = "nan://GM0:SC0:MC0:BS0:0:HW5:0"
OWNER = "NaNROUTER/MC0:0"
SCHEMA = "nanrouter.hw5-gutenberg-c256.v1"
ROOT_BYTES = 8388608
HEADS = 256
COGNITIVE = 255
HEAD_BYTES = 128
PAIRS = 32640
PAIR_BYTES = 256
MIN_BYTES = 19 * 1024 * 1024
MAX_BYTES = 22 * 1024 * 1024
MAX_SOURCE_BYTES = 6 * 1024 * 1024
MIRROR = "https://gutenberg.pglaf.org/cache/epub"
# Order deliberately fixed.  All selected works are public-domain US editions.
BOOKS = (
 (2600, "War and Peace", "Leo Tolstoy"),
 (2000, "Don Quixote", "Miguel de Cervantes"),
 (2701, "Moby Dick", "Herman Melville"),
 (4300, "Ulysses", "James Joyce"),
 (2554, "Crime and Punishment", "Fyodor Dostoevsky"),
 (1400, "Great Expectations", "Charles Dickens"),
 (1260, "Jane Eyre", "Charlotte Bronte"),
 (1342, "Pride and Prejudice", "Jane Austen"),
 (345, "Dracula", "Bram Stoker"),
 (98, "A Tale of Two Cities", "Charles Dickens"),
 (1661, "The Adventures of Sherlock Holmes", "Arthur Conan Doyle"),
 (76, "Adventures of Huckleberry Finn", "Mark Twain"),
 (74, "The Adventures of Tom Sawyer", "Mark Twain"),
 (84, "Frankenstein", "Mary Shelley"),
 (174, "The Picture of Dorian Gray", "Oscar Wilde"),
 (36, "The War of the Worlds", "H. G. Wells"),
 (1322, "Leaves of Grass", "Walt Whitman"),
 (1497, "The Republic", "Plato"),
 (1232, "The Prince", "Niccolo Machiavelli"),
 (6130, "The Iliad", "Homer"),
 (1727, "The Odyssey", "Homer"),
 (203, "Gulliver's Travels", "Jonathan Swift"),
 (135, "The Count of Monte Cristo", "Alexandre Dumas"),
 (2814, "Dubliners", "James Joyce"),
 (11, "Alice's Adventures in Wonderland", "Lewis Carroll"),
 (5200, "Metamorphosis", "Franz Kafka"),
 (219, "Heart of Darkness", "Joseph Conrad"),
 (3825, "Pygmalion", "George Bernard Shaw"),
 (1952, "The Yellow Wallpaper", "Charlotte Perkins Gilman"),
 (1080, "A Modest Proposal", "Jonathan Swift"),
 (844, "The Importance of Being Earnest", "Oscar Wilde"),
 (829, "The Arabian Nights", "Anonymous"),
 (3207, "Leviathan", "Thomas Hobbes"),
)
START = re.compile(rb"(?im)^\\*\\*\\*\\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^\\n]*\\n")
END = re.compile(rb"(?im)^\\*\\*\\*\\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK")
def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def clean(raw: bytes) -> bytes:
    if len(raw) > MAX_SOURCE_BYTES: raise ValueError("Gutenberg source over limit")
    start=START.search(raw)
    end=END.search(raw)
    if not start or not end or end.start()<=start.end():
        raise ValueError("missing or reversed Gutenberg START/END boundaries")
    text=raw[start.end():end.start()].decode("utf-8-sig",errors="strict")
    text=text.replace("\\r\\n","\\n").replace("\\r","\\n").strip()
    encoded=(text+"\\n").encode("utf-8")
    if b"\\xff" in encoded or len(encoded)<2048:
        raise ValueError("text violates native ingress or minimum length")
    return encoded
def book_url(book_id: int) -> str:
    return f"{MIRROR}/{book_id}/pg{book_id}.txt"
def collect(source_dir: Path):
    """Fetch a bounded selected-public-domain slice from the approved mirror.

    No downloads are made against the human-facing Gutenberg website.
    All hashes are captured from actual bytes; a failed source is fatal.
    """
    if source_dir.exists() and any(source_dir.iterdir()):
        raise FileExistsError("source directory must be empty")
    source_dir.mkdir(parents=True,exist_ok=True)
    records=[]
    total=0
    for id_,title,author in BOOKS:
        if total>=MIN_BYTES: break
        url=book_url(id_)
        req=Request(url,headers={"User-Agent":"NaNLM-HW5-Research/1.0 (offline corpus; github.com/shemshallah/NaNROUTER)"})
        with urlopen(req,timeout=75) as stream:
            raw=stream.read(MAX_SOURCE_BYTES+1)
        text=clean(raw)
        if total+len(text)>MAX_BYTES:
            # Preserve whole-document splits, never silently truncate a book.
            continue
        path=source_dir/f"pg{id_}.txt"
        path.write_bytes(raw)
        records.append(dict(id=id_,title=title,author=author,url=url,
                            raw_sha256=digest(raw),text_sha256=digest(text),
                            bytes=len(text)))
        total+=len(text)
    if not MIN_BYTES<=total<=MAX_BYTES or len(records)<12:
        raise ValueError(f"Insufficient whole Gutenberg works: books={len(records)}, bytes={total}")
    (source_dir/"source_manifest.json").write_text(
        json.dumps({"schema":"nanrouter.hw5-source-ledger.v1","books":records,
                    "corpus_bytes":total},sort_keys=True,indent=2)+"\\n")
    print("HW5_SOURCE_COLLECTED",json.dumps({"books":len(records),"bytes":total}))
def pair_index(a:int,b:int)->int:
    if not (0<=a<b<256): raise ValueError("pair endpoints out of range")
    return 1+(a*(511-a)//2)+(b-a-1)
def project(docs,root:Path,dbpath:Path):
    adjacent=Counter()
    skip=Counter()
    triples=Counter()
    out_head=Counter()
    in_head=Counter()
    start_head=Counter()
    end_head=Counter()
    total=0
    for doc in docs:
        data=doc["text"]
        total+=len(data)
        start_head[data[0]]+=1
        end_head[data[-1]]+=1
        for a,b in zip(data,data[1:]):
            adjacent[a,b]+=1
            out_head[a]+=1
            in_head[b]+=1
        for a,b,c in zip(data,data[1:],data[2:]):
            skip[a,c]+=1
            triples[a,b,c]+=1
    with root.open("xb") as f: f.truncate(ROOT_BYTES)
    with root.open("r+b") as f:
        mm=mmap.mmap(f.fileno(),ROOT_BYTES)
        try:
            for h in range(COGNITIVE):
                offset=h*HEAD_BYTES
                struct.pack_into("<IIIIIIII",mm,offset,h,out_head[h],in_head[h],
                                 adjacent[h,h],skip[h,h],start_head[h],end_head[h],1)
            # Head 255 must remain completely zero: HW5 does not claim the gateway.
            for lane,counts in enumerate((adjacent,skip)):
                for (a,b),n in counts.items():
                    if a==b: continue
                    low,high=sorted((a,b))
                    idx=pair_index(low,high)
                    base=HEADS*HEAD_BYTES+(idx-1)*PAIR_BYTES
                    direction=0 if a<b else 1
                    slot=base+16+4*(direction*16+lane)
                    struct.pack_into("<I",mm,slot,n)
                    # pair header count is adjacent count, not adjacency+skip.
                    if lane==0: struct.pack_into("<I",mm,base+4*direction,n)
                    mask_off=base+8+4*direction
                    mask=struct.unpack_from("<I",mm,mask_off)[0]
                    struct.pack_into("<I",mm,mask_off,mask|(1<<lane))
            mm.flush()
        finally: mm.close()
    with sqlite3.connect(dbpath) as db:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA synchronous=FULL")
        db.executescript("""
           CREATE TABLE documents(id INTEGER PRIMARY KEY, title TEXT NOT NULL,
             author TEXT NOT NULL, split TEXT NOT NULL, url TEXT NOT NULL,
             source_sha256 TEXT NOT NULL, text_sha256 TEXT NOT NULL,
             text_bytes INTEGER NOT NULL);
           CREATE TABLE triples(a INTEGER NOT NULL,b INTEGER NOT NULL,c INTEGER NOT NULL,
             n INTEGER NOT NULL CHECK(n>0), PRIMARY KEY(a,b,c)) WITHOUT ROWID;
        """)
        db.executemany("INSERT INTO documents VALUES(?,?,?,?,?,?,?,?)",
                       ((d[k] for k in ("id","title","author","split","url",
                                          "raw_sha256","text_sha256","bytes")) for d in docs))
        db.executemany("INSERT INTO triples VALUES(?,?,?,?)",
                       ((a,b,c,n) for (a,b,c),n in sorted(triples.items())))
    return {"adjacent_transitions":sum(adjacent.values()),"skip_transitions":sum(skip.values()),
            "triple_count":sum(triples.values()),"unique_triples":len(triples),
            "nonzero_adjacent_pairs":len(adjacent),
            "nonzero_skip_pairs":len(skip),
            "occupied_mirror_pairs":len({pair_index(min(a,b),max(a,b))
                                          for (a,b) in set(adjacent)|set(skip) if a!=b}),
            "total_bytes":total}
def build(source_dir:Path,store:Path):
    if store.exists(): raise FileExistsError("HW5 reference must not overwrite an existing generation")
    source=json.loads((source_dir/"source_manifest.json").read_text())
    if source["schema"]!="nanrouter.hw5-source-ledger.v1": raise ValueError("wrong source schema")
    docs=[]
    for ordinal,entry in enumerate(source["books"]):
        id_=entry["id"]
        raw=(source_dir/f"pg{id_}.txt").read_bytes()
        if digest(raw)!=entry["raw_sha256"]: raise ValueError("source drift")
        text=clean(raw)
        if digest(text)!=entry["text_sha256"] or len(text)!=entry["bytes"]:
            raise ValueError("normalized source changed")
        if ordinal%10==8: split="dev"
        elif ordinal%10==9: split="test"
        else: split="train"
        docs.append({**entry,"split":split,"text":text})
    if not MIN_BYTES<=sum(len(d["text"]) for d in docs)<=MAX_BYTES:
        raise ValueError("bad corpus size")
    if not all(any(d["split"]==s for d in docs) for s in ("train","dev","test")):
        raise ValueError("no document-disjoint train/dev/test")
    tmp=store.with_name(store.name+".staging")
    if tmp.exists(): raise FileExistsError("HW5 staging already exists")
    generation=tmp/"generation-00000001"
    generation.mkdir(parents=True)
    try:
        for name in ("all","train","dev","test"):
            with (generation/f"{name}.txt").open("xb") as out:
                for doc in docs:
                    if name=="all" or name==doc["split"]:
                        out.write(doc["text"])
        stats=project(docs,generation/"gutenberg-c256.root",generation/"gutenberg-triples.sqlite3")
        manifest={
            "schema":SCHEMA,"route":ROUTE,"ring_owner":OWNER,
            "main_ring_writable":False,"reference_only":True,
            "generation_name":"generation-00000001",
            "root_bytes":ROOT_BYTES,"heads":HEADS,"gateway_head":255,
            "mirror_pairs":PAIRS,"canonical_cells":PAIRS+HEADS,
            "pair_formula":"1+a*(511-a)/2+(b-a-1) for a<b",
            "pair_record":"offset=32768+(pair_id-1)*256; u32 forward_adjacent, reverse_adjacent, forward_mask, reverse_mask; 16*u32 forward lanes, 16*u32 reverse lanes; reserved",
            "lanes":{"0":"directed adjacent bytes","1":"directed distance-two bytes"},
            "head_record":"u32 head_id,outgoing,incoming,self_adjacent,self_skip,document_starts,document_ends,projection_version",
            "hypermatrix":"ordered exact (a,b,c,count) SQLite; 3 mirror legs a->b,b->c,c->a; no extra dense cubic tensor",
            "corpus_policy":"whole books only; document-level split ordinal modulo 10, no split inside a title",
            "source_mirror":MIRROR,"books":[{k:v for k,v in d.items() if k!="text"} for d in docs],
            "corpus_bytes":stats["total_bytes"],"projection":stats,
            "artifacts":{name:{"bytes":(generation/name).stat().st_size,"sha256":sha(generation/name)}
               for name in ("all.txt","train.txt","dev.txt","test.txt",
                            "gutenberg-c256.root","gutenberg-triples.sqlite3")}
        }
        (generation/"manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\\n")
        pointer={"schema":SCHEMA,"generation_name":"generation-00000001",
                 "manifest_sha256":sha(generation/"manifest.json")}
        (tmp/"CURRENT.json").write_text(json.dumps(pointer,sort_keys=True)+"\\n")
        tmp.rename(store)
    except Exception:
        shutil.rmtree(tmp,ignore_errors=True)
        raise
    return verify(store)
def verify(store:Path):
    pointer=json.loads((store/"CURRENT.json").read_text())
    if pointer["schema"]!=SCHEMA or pointer["generation_name"]!="generation-00000001":
        raise ValueError("wrong HW5 current")
    generation=store/pointer["generation_name"]
    if sha(generation/"manifest.json")!=pointer["manifest_sha256"]:
        raise ValueError("HW5 current pointer digest mismatch")
    manifest=json.loads((generation/"manifest.json").read_text())
    if manifest["schema"]!=SCHEMA or manifest["route"]!=ROUTE or manifest["ring_owner"]!=OWNER:
        raise ValueError("wrong HW5 reference identity")
    if manifest["main_ring_writable"] is not False or not manifest["reference_only"]:
        raise ValueError("HW5 is not immutable reference")
    for name,meta in manifest["artifacts"].items():
        p=generation/name
        if p.is_symlink() or p.stat().st_size!=meta["bytes"] or sha(p)!=meta["sha256"]:
            raise ValueError("HW5 artifact mismatch "+name)
    if manifest["root_bytes"]!=ROOT_BYTES or manifest["mirror_pairs"]!=PAIRS:
        raise ValueError("wrong root geometry")
    with (generation/"gutenberg-c256.root").open("rb") as f:
        f.seek(255*HEAD_BYTES)
        if f.read(HEAD_BYTES)!=bytes(HEAD_BYTES): raise ValueError("gateway head occupied")
    with sqlite3.connect("file:"+str((generation/"gutenberg-triples.sqlite3").resolve())+"?mode=ro&immutable=1",uri=True) as db:
        n,c=db.execute("SELECT COUNT(*),COALESCE(SUM(n),0) FROM triples").fetchone()
        if n!=manifest["projection"]["unique_triples"] or c!=manifest["projection"]["triple_count"]:
            raise ValueError("trigram ledger corrupted")
        if db.execute("SELECT count(*) FROM documents").fetchone()[0]!=len(manifest["books"]):
            raise ValueError("document ledger corrupted")
    if manifest["projection"]["adjacent_transitions"]!=manifest["corpus_bytes"]-len(manifest["books"]):
        raise ValueError("adjacent boundary invariant")
    if manifest["projection"]["triple_count"]!=manifest["corpus_bytes"]-2*len(manifest["books"]):
        raise ValueError("triple boundary invariant")
    return manifest
def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="action",required=True)
    sub.add_parser("collect").add_argument("source_dir",type=Path)
    b=sub.add_parser("build")
    b.add_argument("source_dir",type=Path);b.add_argument("store",type=Path)
    sub.add_parser("verify").add_argument("store",type=Path)
    a=p.parse_args()
    if a.action=="collect":collect(a.source_dir)
    elif a.action=="build":
        m=build(a.source_dir,a.store)
        print("HW5_C256_BUILT",json.dumps({"bytes":m["corpus_bytes"],"books":len(m["books"]),"pairs":m["projection"]["occupied_mirror_pairs"],"triples":m["projection"]["unique_triples"]}))
    else:
        m=verify(a.store)
        print("HW5_C256_VERIFIED",json.dumps({"bytes":m["corpus_bytes"],"sha256":m["artifacts"]["all.txt"]["sha256"],"pairs":m["projection"]["occupied_mirror_pairs"]}))
if __name__=="__main__": main()
