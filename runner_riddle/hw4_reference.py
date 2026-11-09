"""Immutable, digest-verified HW4 WordNet C(256,2) reference generations.

OFFLINE PREPARATION ONLY. This is NOT a deployed NANNET HW4 service, not
another language-model instance, and not a writable upper universe.

One 8 MiB topology projection and one exact WordNet SQLite overlay form a
single logical reference generation. They must be pinned together; concept
hash collisions are resolved by exact synset IDs in the SQLite overlay.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import fcntl
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import sqlite3
import struct
import tempfile
import time

from .wordnet_mirror_adapter import head_for_key, pair_id

SCHEMA = "nanrouter.hw4-frozen-wordnet-reference.v1"
HW4_ROUTE = "nan://GM0:SC0:MC0:BS0:0:HW4:0"
ROOT_BYTES = 8388608
HEAD_BYTES = 128
PAIR_BYTES = 256
HEAD_COUNT = 256
PAIR_COUNT = 32640
GEN_RE = re.compile(r"^generation-[0-9]{8}$")
ID_RE = re.compile(r"^[0-9]{8}$")
CURRENT = "CURRENT.json"


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for piece in iter(lambda: f.read(1048576), b""):
            h.update(piece)
    return h.hexdigest()


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def _lock(store):
    store.mkdir(parents=True, exist_ok=True)
    fd = os.open(store/"WRITER.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _parse_data_noun(path):
    """Read full exact noun identities and retained WordNet source glosses."""
    with Path(path).open("r", encoding="utf-8") as f:
        for lineno,line in enumerate(f,1):
            if not line or not line[0].isdigit():
                continue
            left, delim, gloss = line.partition("|")
            if not delim:
                raise ValueError(f"bad WordNet gloss on {lineno}")
            tokens = left.split()
            if len(tokens) < 5 or not ID_RE.fullmatch(tokens[0]) or tokens[2] != "n":
                raise ValueError(f"bad WordNet noun header on {lineno}")
            count = int(tokens[3],16)
            if not 1 <= count <= 1024:
                raise ValueError(f"bad WordNet lexeme count on {lineno}")
            offset = 4 + count*2
            if len(tokens) <= offset:
                raise ValueError(f"bad WordNet lexeme fields on {lineno}")
            lemmas = tuple(tokens[4+2*j] for j in range(count))
            ptrs = int(tokens[offset],10)
            if not 0 <= ptrs <= 10000 or len(tokens)<offset+1+4*ptrs:
                raise ValueError(f"bad WordNet pointer table on {lineno}")
            relations = []
            for i in range(ptrs):
                kind,dst,pos,relation_src = tokens[offset+1+4*i:offset+1+4*i+4]
                if pos=="n" and ID_RE.fullmatch(dst):
                    relations.append((kind,dst+"-n",relation_src))
            yield (tokens[0]+"-n",lemmas,gloss.strip(),relations)


def _create_tables(connection):
    connection.executescript("""
        PRAGMA journal_mode=DELETE;
        PRAGMA synchronous=FULL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE synsets (
            synset TEXT PRIMARY KEY, head INTEGER NOT NULL,
            lemma TEXT NOT NULL, gloss TEXT NOT NULL
        );
        CREATE TABLE lemmas (
            lemma TEXT NOT NULL, synset TEXT NOT NULL,
            PRIMARY KEY(lemma,synset), FOREIGN KEY(synset)
              REFERENCES synsets(synset)
        );
        CREATE TABLE relations (
            src TEXT NOT NULL, dst TEXT NOT NULL, relation TEXT NOT NULL,
            source_target TEXT NOT NULL, src_head INTEGER NOT NULL,
            dst_head INTEGER NOT NULL, pair_id INTEGER NOT NULL,
            polarity INTEGER NOT NULL,
            FOREIGN KEY(src) REFERENCES synsets(synset),
            FOREIGN KEY(dst) REFERENCES synsets(synset)
        );
        CREATE INDEX rel_src ON relations(src,relation);
        CREATE INDEX rel_dst ON relations(dst,relation);
        CREATE INDEX rel_pair ON relations(pair_id,src_head,dst_head);
        CREATE INDEX lemma_lookup ON lemmas(lemma);
    """)


def _build(source, stage, source_hash, generation):
    root = stage/"wordnet-c256.root"
    database = stage/"wordnet-exact.sqlite3"
    manifest_file = stage/"manifest.json"
    with root.open("xb") as f:
        f.truncate(ROOT_BYTES)
    mm_file = root.open("r+b")
    mm = mmap.mmap(mm_file.fileno(), ROOT_BYTES)
    connection = sqlite3.connect(database)
    conn_open = True
    try:
        _create_tables(connection)
        rows = 0
        pending = []
        head_counts = Counter()
        connection.execute("BEGIN")
        for synset,lemmas,gloss,pointers in _parse_data_noun(source):
            h = head_for_key("synset:"+synset)
            connection.execute("INSERT INTO synsets VALUES(?,?,?,?)",
                               (synset,h,lemmas[0],gloss))
            connection.executemany("INSERT OR IGNORE INTO lemmas VALUES(?,?)",
                                   ((lemma,synset) for lemma in lemmas))
            for rel,dst,source_target in pointers:
                pending.append((synset,dst,rel,source_target,h))
            head_counts[h] += 1
            rows += 1
        if rows == 0:
            raise ValueError("empty WordNet noun source; no reference generation")
        connection.commit()
        known = {r[0]:r[1] for r in connection.execute("SELECT synset,head FROM synsets")}
        signed = Counter()
        collisions = 0
        unresolved = 0
        relations = 0
        connection.execute("BEGIN")
        for src,dst,rel,source_target,a in pending:
            b=known.get(dst)
            if b is None:
                unresolved += 1
                continue
            if a==b:
                collisions += 1
                pid=0  # no physical off-diagonal slot; exact overlay keeps it
            else:
                pid=pair_id(a,b)
                sign = 1 if a<b else -1
                signed[pid] += sign*(-1 if rel=="!" else 1)
            connection.execute(
                "INSERT INTO relations VALUES(?,?,?,?,?,?,?,?)",
                (src,dst,rel,source_target,a,b,pid,-1 if rel=="!" else 1))
            relations += 1
        connection.commit()
        # Reference-only readout: all 256 *data* coordinates exist in this
        # immutable snapshot. Do NOT mount it as a live guest root: runtime
        # ingress head roles and runtime register ownership are different.
        for h,count in head_counts.items():
            struct.pack_into("<I",mm,h*HEAD_BYTES+4,count)
            struct.pack_into("<f",mm,h*HEAD_BYTES+8,float(count))
            struct.pack_into("<I",mm,h*HEAD_BYTES+12,generation)
        for pid,value in signed.items():
            base = HEAD_COUNT*HEAD_BYTES+(pid-1)*PAIR_BYTES
            struct.pack_into("<f",mm,base,float(value))
            struct.pack_into("<f",mm,base+128,float(-value))
            struct.pack_into("<f",mm,base+108,1.0)
            struct.pack_into("<I",mm,base+120,generation)
        mm.flush()
        mm.close()
        mm_file.close()
        connection.close()
        conn_open=False
        manifest={
            "schema":SCHEMA,
            "route":HW4_ROUTE,
            "source_type":"Princeton WordNet data.noun",
            "source_sha256":source_hash,
            "generation":generation,
            "generation_name":f"generation-{generation:08d}",
            "head_hash":"nanrouter.wordnet.concept/1 SHA256(u32_be) & 255",
            "pair_formula":"1+a*(511-a)/2+(b-a-1)",
            "root_bytes":ROOT_BYTES,
            "root_profile":"offline wordnet reference projection, not live NaN16 guest",
            "mirror_rule":"pair lane1 == -pair lane0",
            "exact_overlay":"wordnet-exact.sqlite3",
            "synsets":rows,
            "relations":relations,
            "unresolved_noun_pointers":unresolved,
            "head_collision_relation_rows":collisions,
            "occupied_pairs":len(signed),
            "root_sha256":sha256(root),
            "sqlite_sha256":sha256(database),
        }
        manifest_file.write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n")
        for path in (root,database,manifest_file):
            with path.open("rb") as file: os.fsync(file.fileno())
        _fsync_dir(stage)
        return manifest
    finally:
        if not mm.closed: mm.close()
        mm_file.close()
        if conn_open: connection.close()


def _read_pointer(store):
    path=store/CURRENT
    if not path.exists():
        return None
    data=json.loads(path.read_text(encoding="utf-8"))
    if (set(data) != {"schema","generation_name","manifest_sha256"} or
        data["schema"]!=SCHEMA or
        not isinstance(data["generation_name"],str) or
        not GEN_RE.fullmatch(data["generation_name"]) or
        not isinstance(data["manifest_sha256"],str) or
        not re.fullmatch("[0-9a-f]{64}",data["manifest_sha256"])):
        raise ValueError("invalid frozen HW4 current pointer")
    return data


def verify(store, *, generation_name=None):
    """Load a frozen reference with digest checks and no writes."""
    store=Path(store)
    pointer=_read_pointer(store)
    if generation_name is None:
        if pointer is None:
            raise FileNotFoundError("HW4 reference has no committed generation")
        generation_name=pointer["generation_name"]
    if not isinstance(generation_name,str) or not GEN_RE.fullmatch(generation_name):
        raise ValueError("invalid reference generation name")
    folder=store/generation_name
    manifest_file=folder/"manifest.json"
    manifest=json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("schema")!=SCHEMA or manifest.get("generation_name")!=generation_name:
        raise ValueError("invalid HW4 reference manifest")
    if (pointer is not None and pointer["generation_name"]==generation_name and
        pointer["manifest_sha256"]!=sha256(manifest_file)):
        raise ValueError("HW4 current manifest tampering detected")
    for file,check in (("wordnet-c256.root","root_sha256"),
                       ("wordnet-exact.sqlite3","sqlite_sha256")):
        path=folder/file
        if sha256(path)!=manifest[check]:
            raise ValueError("HW4 reference artifact integrity failure: "+file)
    if (folder/"wordnet-c256.root").stat().st_size!=ROOT_BYTES:
        raise ValueError("HW4 root has wrong size")
    with sqlite3.connect("file:"+str((folder/"wordnet-exact.sqlite3").resolve())+"?mode=ro",
                         uri=True) as conn:
        n=conn.execute("SELECT COUNT(*) FROM synsets").fetchone()[0]
        e=conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
    if (n,e)!=(manifest["synsets"],manifest["relations"]):
        raise ValueError("HW4 reference SQLite count mismatch")
    return manifest


def install(source, store):
    """Atomically publish one immutable HW4 *reference*, never live guest state."""
    source,store=Path(source),Path(store)
    source_hash=sha256(source)
    with _lock(store):
        pointer=_read_pointer(store)
        if pointer is not None:
            current=verify(store)
            if current["source_sha256"]==source_hash:
                return {"reused":True, "manifest":current}
            generation=current["generation"]+1
        else:
            generation=1
        destination=store/f"generation-{generation:08d}"
        if destination.exists():
            raise FileExistsError("HW4 reference generation already exists")
        with tempfile.TemporaryDirectory(prefix=".hw4-staging-",dir=store) as temp:
            staging=Path(temp)
            manifest=_build(source,staging,source_hash,generation)
            staging.rename(destination)
        _fsync_dir(store)
        manifest_hash=sha256(destination/"manifest.json")
        pointer_content={
            "schema":SCHEMA, "generation_name":destination.name,
            "manifest_sha256":manifest_hash}
        next_pointer=store/(CURRENT+".tmp")
        with next_pointer.open("x",encoding="utf-8") as f:
            f.write(json.dumps(pointer_content,sort_keys=True)+"\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(next_pointer,store/CURRENT)
        _fsync_dir(store)
        verified=verify(store)
        return {"reused":False,"manifest":verified}


def inspect_pairs(store, a, b):
    """Exact reference evidence and canonical signed matrix value."""
    manifest=verify(store)
    if a==b:
        raise ValueError("same-head identities are indexed only in SQLite")
    folder=Path(store)/manifest["generation_name"]
    pid=pair_id(a,b)
    with (folder/"wordnet-c256.root").open("rb") as f:
        f.seek(HEAD_COUNT*HEAD_BYTES+(pid-1)*PAIR_BYTES)
        record=f.read(PAIR_BYTES)
    forward=struct.unpack_from("<f",record,0)[0]
    reverse=struct.unpack_from("<f",record,128)[0]
    if forward != -reverse:
        raise ValueError("mirror reference sign contract broken")
    with sqlite3.connect("file:"+str((folder/"wordnet-exact.sqlite3").resolve())+"?mode=ro",
                         uri=True) as conn:
        count=conn.execute("SELECT COUNT(*) FROM relations WHERE pair_id=?",
                           (pid,)).fetchone()[0]
    return {"pair_id":pid,"signed_reference":forward,
            "mirror_reference":reverse,"exact_relation_rows":count,
            "generation":manifest["generation"]}


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest="action",required=True)
    create=subs.add_parser("install")
    create.add_argument("data_noun",type=Path)
    create.add_argument("store",type=Path)
    check=subs.add_parser("verify")
    check.add_argument("store",type=Path)
    args=parser.parse_args()
    result=install(args.data_noun,args.store) if args.action=="install" else verify(args.store)
    print(json.dumps(result,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
