"""WordNet 3.1 full dictionary -> immutable HW4:0 C(256,2) reference.

This is OFFLINE intake/byte transport, not a new mathematical kernel.
It uses the established NaNROUTER SHA256 concept head mapping. The 8 MiB
image is a read-only reference, NOT a writable guest, BS0 model or ring slot.
Exact directed pointers, polysemous senses, and source provenance are stored
in SQLite; the matrix is deliberately a lossy, dense integer projection.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import sqlite3
import struct
import tempfile
import zipfile

from .hw4_reference import _lock, _fsync_dir, sha256
from .wordnet_mirror_adapter import head_for_key, pair_id

SCHEMA = "nanrouter.hw4-wordnet31-complete.v1"
ROUTE = "nan://GM0:SC0:MC0:BS0:0:HW4:0"
RING_OWNER = "NaNROUTER/MC0:0"
MAIN_RING_WRITABLE = False
HEADS = 256
PAIRS = 32640
HEAD_BYTES = 128
PAIR_BYTES = 256
ROOT_BYTES = HEADS * HEAD_BYTES + PAIRS * PAIR_BYTES
CURRENT = "CURRENT.json"
GEN_RE = re.compile(r"generation-[0-9]{8}\Z")
DATAFILES = ("data.noun", "data.verb", "data.adj", "data.adv")
SENSE_FILE = "index.sense"

# Aggregated lanes do not substitute for the exact WordNet pointer symbol.
POINTER_LANES = {
    "@": 0, "@i": 0, "~": 1, "~i": 1, "!": 2, "+": 3,
    "=": 4, "*": 5, ">": 6, "^": 7, "&": 8, "$": 9,
    "%m": 10, "%s": 10, "%p": 10,
    "#m": 11, "#s": 11, "#p": 11,
    ";c": 12, ";r": 12, ";u": 12,
    "-c": 13, "-r": 13, "-u": 13,
    "\\": 14,
}
POS_OF_SENSE = {"1": "n", "2": "v", "3": "a", "4": "r", "5": "s"}


def _files(archive: zipfile.ZipFile):
    """Require exactly one member per canonical dictionary basename."""
    names = {}
    for name in archive.namelist():
        basename = name.rsplit("/", 1)[-1]
        if basename in (*DATAFILES, SENSE_FILE):
            if basename in names:
                raise ValueError("ambiguous dictionary member: " + basename)
            names[basename] = name
    missing = set((*DATAFILES, SENSE_FILE)).difference(names)
    if missing:
        raise ValueError("missing WordNet 3.1 dictionary members: " + str(sorted(missing)))
    return names


def _source_rows(archive, member):
    with archive.open(member) as file:
        for line_no, raw in enumerate(file, 1):
            line = raw.decode("utf-8").rstrip("\r\n")
            if not line or not line[0].isdigit():
                continue
            left, separator, gloss = line.partition("|")
            if not separator:
                raise ValueError(f"{member}:{line_no}: missing gloss separator")
            tokens = left.split()
            if len(tokens) < 5 or not re.fullmatch(r"[0-9]{8}", tokens[0]):
                raise ValueError(f"{member}:{line_no}: invalid synset offset")
            offset = tokens[0]
            lexfile = int(tokens[1], 10)
            pos = tokens[2]
            if pos not in ("n", "v", "a", "s", "r"):
                raise ValueError(f"{member}:{line_no}: invalid synset part of speech")
            count = int(tokens[3], 16)
            if count < 1 or count > 1024:
                raise ValueError(f"{member}:{line_no}: invalid lemma count")
            k = 4 + 2 * count
            if len(tokens) <= k:
                raise ValueError(f"{member}:{line_no}: short lemma section")
            lemmas = [tokens[4 + 2 * i] for i in range(count)]
            n = int(tokens[k], 10)
            if n > 10000 or len(tokens) < k + 1 + 4 * n:
                raise ValueError(f"{member}:{line_no}: short pointer section")
            pointers = []
            for i in range(n):
                symbol, dest_offset, dest_pos, word_pair = tokens[k+1+4*i:k+5+4*i]
                if not re.fullmatch(r"[0-9]{8}", dest_offset):
                    raise ValueError(f"{member}:{line_no}: bad pointer target offset")
                if dest_pos not in ("n", "v", "a", "s", "r"):
                    raise ValueError(f"{member}:{line_no}: bad pointer target POS")
                if not re.fullmatch(r"[0-9a-fA-F]{4}", word_pair):
                    raise ValueError(f"{member}:{line_no}: bad lexical pointer indices")
                pointers.append((symbol, f"{dest_offset}-{dest_pos}",
                                 int(word_pair[:2], 16), int(word_pair[2:], 16)))
            yield f"{offset}-{pos}", offset, pos, lexfile, lemmas, gloss.strip(), pointers, line_no


def _create_db(conn):
    conn.executescript("""
    PRAGMA journal_mode=DELETE;
    PRAGMA synchronous=FULL;
    CREATE TABLE synsets (
        synset TEXT PRIMARY KEY, pos TEXT NOT NULL, offset TEXT NOT NULL,
        head INTEGER NOT NULL CHECK(head BETWEEN 0 AND 255),
        lexfile INTEGER NOT NULL, lemmas_json TEXT NOT NULL, gloss TEXT NOT NULL);
    CREATE TABLE senses (
        sense_key TEXT PRIMARY KEY, synset TEXT NOT NULL, lemma TEXT NOT NULL,
        sense_number INTEGER NOT NULL, tag_count INTEGER NOT NULL);
    CREATE TABLE pointers (
        id INTEGER PRIMARY KEY, src TEXT NOT NULL, dst TEXT NOT NULL,
        symbol TEXT NOT NULL, src_word INTEGER NOT NULL, dst_word INTEGER NOT NULL,
        src_head INTEGER NOT NULL, dst_head INTEGER NOT NULL,
        pair_id INTEGER NOT NULL CHECK(pair_id BETWEEN 0 AND 32640),
        resolved INTEGER NOT NULL, source_file TEXT NOT NULL, source_line INTEGER NOT NULL);
    CREATE INDEX ptr_pair ON pointers(pair_id,src_head,dst_head);
    CREATE INDEX ptr_src ON pointers(src,symbol);
    CREATE INDEX ptr_dst ON pointers(dst,symbol);
    CREATE INDEX senses_synset ON senses(synset);
    CREATE INDEX senses_lemma ON senses(lemma);
    """)


def _find_target(known, key):
    head = known.get(key)
    if head is not None:
        return key, head
    # WordNet adj and satellite references may use alternate a/s POS.
    if key.endswith("-a") or key.endswith("-s"):
        alternate = key[:-1] + ("s" if key.endswith("-a") else "a")
        head = known.get(alternate)
        if head is not None:
            return alternate, head
    return key, None


def _populate(source_zip, stage, generation):
    root = stage / "wordnet-c256.root"
    dbpath = stage / "wordnet-exact.sqlite3"
    manifest_path = stage / "manifest.json"
    data_digests = {}
    heads = Counter()
    senses_per_head = Counter()
    same_head = Counter()
    pending = []
    known = {}
    with zipfile.ZipFile(source_zip) as archive:
        names = _files(archive)
        if archive.testzip() is not None:
            raise ValueError("WordNet archive failed CRC integrity check")
        for basename, member in names.items():
            data_digests[basename] = hashlib.sha256(archive.read(member)).hexdigest()
        with sqlite3.connect(dbpath) as conn:
            _create_db(conn)
            conn.execute("BEGIN")
            for basename in DATAFILES:
                for key, offset, pos, lexfile, lemmas, gloss, pointers, lineno in _source_rows(archive, names[basename]):
                    h = head_for_key("synset:" + key)
                    if key in known:
                        raise ValueError("duplicate WordNet synset key " + key)
                    known[key] = h
                    heads[h] += 1
                    conn.execute(
                        "INSERT INTO synsets VALUES (?,?,?,?,?,?,?)",
                        (key, pos, offset, h, lexfile,
                         json.dumps(lemmas, ensure_ascii=True), gloss))
                    for symbol, dst, sw, dw in pointers:
                        pending.append((key, dst, symbol, sw, dw, h, basename, lineno))
            if not known:
                raise ValueError("empty WordNet archive")
            sense_count = 0
            with archive.open(names[SENSE_FILE]) as f:
                for lineno, raw in enumerate(f, 1):
                    tokens = raw.decode("utf-8").split()
                    if not tokens:
                        continue
                    if len(tokens) != 4 or "%" not in tokens[0]:
                        raise ValueError(f"{SENSE_FILE}:{lineno}: invalid sense row")
                    sense_key = tokens[0]
                    pos = POS_OF_SENSE.get(sense_key.split("%", 1)[1][:1])
                    if pos is None:
                        raise ValueError(f"{SENSE_FILE}:{lineno}: invalid sense POS")
                    original = f"{tokens[1]}-{pos}"
                    key, h = _find_target(known, original)
                    if h is None:
                        # Retain exact sense key even if the data archive has a bad link.
                        h = head_for_key("synset:" + original)
                        key = original
                    conn.execute("INSERT INTO senses VALUES (?,?,?,?,?)",
                                 (sense_key, key, sense_key.split("%", 1)[0],
                                  int(tokens[2]), int(tokens[3])))
                    senses_per_head[h] += 1
                    sense_count += 1
            conn.commit()
        del archive
    # 256 * 128-byte head records + 32640 * 256-byte pair records exactly.
    with root.open("xb") as f:
        f.truncate(ROOT_BYTES)
    with root.open("r+b") as f, sqlite3.connect(dbpath) as conn:
        matrix = mmap.mmap(f.fileno(), ROOT_BYTES)
        try:
            total_pointers = 0
            unresolved = 0
            self_pointers = 0
            pair_occupied = set()
            lane_hist = Counter()
            out_counts = Counter()
            in_counts = Counter()
            conn.execute("BEGIN")
            for src, dst_raw, sym, sw, dw, a, basename, lineno in pending:
                dst, b = _find_target(known, dst_raw)
                valid = b is not None
                if not valid:
                    unresolved += 1
                    b = head_for_key("synset:" + dst_raw)
                pid = pair_id(a, b) if valid and a != b else 0
                conn.execute(
                    "INSERT INTO pointers(src,dst,symbol,src_word,dst_word,"
                    "src_head,dst_head,pair_id,resolved,source_file,source_line) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (src, dst, sym, sw, dw, a, b, pid, int(valid), basename, lineno))
                total_pointers += 1
                if not valid:
                    continue
                out_counts[a] += 1
                in_counts[b] += 1
                lane = POINTER_LANES.get(sym, 15)
                lane_hist[lane] += 1
                if a == b:
                    same_head[a] += 1
                    self_pointers += 1
                    continue
                pair_occupied.add(pid)
                base = HEADS * HEAD_BYTES + (pid - 1) * PAIR_BYTES
                direction = 0 if a < b else 1
                count_offset = base + 4 * direction
                mask_offset = base + 8 + 4 * direction
                lane_offset = base + 16 + 4 * (direction * 16 + lane)
                for offset in (count_offset, lane_offset):
                    count = struct.unpack_from("<I", matrix, offset)[0]
                    if count == 0xffffffff:
                        raise OverflowError("HW4 pair counter exceeds uint32")
                    struct.pack_into("<I", matrix, offset, count + 1)
                mask = struct.unpack_from("<I", matrix, mask_offset)[0]
                struct.pack_into("<I", matrix, mask_offset, mask | (1 << lane))
            conn.commit()
            for h in range(HEADS):
                start = h * HEAD_BYTES
                struct.pack_into("<IIIIII", matrix, start, h, heads[h],
                                 senses_per_head[h], out_counts[h],
                                 in_counts[h], same_head[h])
                struct.pack_into("<I", matrix, start + 24, generation)
            matrix.flush()
        finally:
            matrix.close()
    manifest = {
        "schema": SCHEMA, "route": ROUTE, "ring_owner": RING_OWNER,
        "main_ring_writable": MAIN_RING_WRITABLE,
        "generation": generation,
        "generation_name": f"generation-{generation:08d}",
        "source_archive_sha256": sha256(source_zip),
        "dictionary_sha256": data_digests,
        "head_hash": "nanrouter.wordnet.concept/1 SHA256(u32_be)&255",
        "pair_formula": "1+a*(511-a)/2+(b-a-1)",
        "pair_record_schema": "u32 fwd_count,rev_count,fwd_mask,rev_mask; 16 u32 lanes per direction; reserved tail",
        "root_profile": "immutable HW4 reference only, NOT a NaN16 guest root",
        "root_bytes": ROOT_BYTES, "heads": HEADS, "pair_count": PAIRS,
        "synsets": len(known), "senses": sense_count, "pointers": total_pointers,
        "unresolved_pointers": unresolved,
        "same_head_pointers": self_pointers,
        "occupied_pairs": len(pair_occupied),
        "lane_histogram": dict(sorted(lane_hist.items())),
        "root_sha256": sha256(root), "sqlite_sha256": sha256(dbpath),
    }
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    for path in (root, dbpath, manifest_path):
        with path.open("rb") as f:
            os.fsync(f.fileno())
    _fsync_dir(stage)
    return manifest


def _current(store):
    file = Path(store) / CURRENT
    if not file.exists():
        return None
    doc = json.loads(file.read_text())
    if set(doc) != {"schema", "generation_name", "manifest_sha256"} or doc["schema"] != SCHEMA:
        raise ValueError("invalid full WordNet HW4 current pointer")
    if not GEN_RE.fullmatch(doc["generation_name"]):
        raise ValueError("invalid full WordNet HW4 generation name")
    if not re.fullmatch("[a-f0-9]{64}", doc["manifest_sha256"]):
        raise ValueError("invalid full WordNet HW4 manifest digest")
    return doc


def verify(store):
    store = Path(store)
    pointer = _current(store)
    if pointer is None:
        raise FileNotFoundError("no committed complete HW4 WordNet generation")
    folder = store / pointer["generation_name"]
    mf = folder / "manifest.json"
    if sha256(mf) != pointer["manifest_sha256"]:
        raise ValueError("HW4 full WordNet manifest checksum mismatch")
    manifest = json.loads(mf.read_text())
    if (manifest.get("schema") != SCHEMA or manifest.get("route") != ROUTE or
        manifest.get("ring_owner") != RING_OWNER or
        manifest.get("main_ring_writable") is not False or
        manifest.get("generation_name") != pointer["generation_name"]):
        raise ValueError("invalid full WordNet HW4 reference contract")
    root = folder / "wordnet-c256.root"
    db = folder / "wordnet-exact.sqlite3"
    if root.stat().st_size != ROOT_BYTES or sha256(root) != manifest["root_sha256"]:
        raise ValueError("HW4 full reference root integrity failure")
    if sha256(db) != manifest["sqlite_sha256"]:
        raise ValueError("HW4 full reference exact ledger integrity failure")
    with sqlite3.connect("file:" + str(db.resolve()) + "?mode=ro", uri=True) as conn:
        counts = [conn.execute("SELECT count(*) FROM " + name).fetchone()[0]
                  for name in ("synsets", "senses", "pointers")]
        if counts != [manifest["synsets"], manifest["senses"], manifest["pointers"]]:
            raise ValueError("HW4 full reference ledger count mismatch")
    return manifest


def install(source_zip, store):
    source_zip = Path(source_zip)
    store = Path(store)
    if not zipfile.is_zipfile(source_zip):
        raise ValueError("complete WordNet source must be wn3.1.dict.zip")
    digest = sha256(source_zip)
    with _lock(store):
        old = _current(store)
        if old is not None:
            previous = verify(store)
            if previous["source_archive_sha256"] == digest:
                return {"reused": True, "manifest": previous}
            generation = previous["generation"] + 1
        else:
            generation = 1
        target = store / f"generation-{generation:08d}"
        if target.exists():
            raise FileExistsError("HW4 full reference generation already exists")
        with tempfile.TemporaryDirectory(prefix=".hw4zip-staging-", dir=store) as td:
            stage = Path(td)
            manifest = _populate(source_zip, stage, generation)
            stage.rename(target)
        _fsync_dir(store)
        pointer = {"schema": SCHEMA, "generation_name": target.name,
                   "manifest_sha256": sha256(target / "manifest.json")}
        next_path = store / (CURRENT + ".tmp")
        with next_path.open("x") as f:
            f.write(json.dumps(pointer, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(next_path, store / CURRENT)
        _fsync_dir(store)
        return {"reused": False, "manifest": verify(store)}


class MountedHW4:
    """Pinned, read-only HW4 matrix+ledger held open by the NaNROUTER service.

    No independent ring, no main-ring state, no write API. The caller must
    expose this through the existing authenticated NaNROUTER service.
    """
    def __init__(self, store):
        self.store = Path(store)
        self.manifest = verify(self.store)
        folder = self.store / self.manifest["generation_name"]
        self._file = (folder / "wordnet-c256.root").open("rb")
        self._matrix = mmap.mmap(self._file.fileno(), ROOT_BYTES, access=mmap.ACCESS_READ)
        uri = "file:" + str((folder / "wordnet-exact.sqlite3").resolve()) + "?mode=ro&immutable=1"
        self._db = sqlite3.connect(uri, uri=True, check_same_thread=False)
    def close(self):
        self._db.close()
        self._matrix.close()
        self._file.close()
    def status(self):
        return {"route": ROUTE, "ring_owner": RING_OWNER, "main_ring_writable": False,
                "mounted": True, "read_only": True, "generation": self.manifest["generation"],
                "root_sha256": self.manifest["root_sha256"],
                "synsets": self.manifest["synsets"], "senses": self.manifest["senses"],
                "pointers": self.manifest["pointers"], "pair_count": PAIRS}
    def pair(self, a, b):
        if type(a) is not int or type(b) is not int or not 0 <= a < 256 or not 0 <= b < 256 or a == b:
            raise ValueError("pair must have two distinct heads in 0..255")
        pid = pair_id(a, b)
        off = HEADS * HEAD_BYTES + (pid - 1) * PAIR_BYTES
        fwd, rev, fmask, rmask = struct.unpack_from("<IIII", self._matrix, off)
        return {"pair_id": pid, "forward_count": fwd, "reverse_count": rev,
                "forward_mask": fmask, "reverse_mask": rmask,
                "orientation": "forward" if a < b else "mirror"}
    def exact(self, synset, limit=32):
        if type(synset) is not str or len(synset) > 40 or not re.fullmatch(r"[0-9]{8}-[nvasr]", synset):
            raise ValueError("invalid exact WordNet synset key")
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("limit must be 1..128")
        rows = self._db.execute(
            "SELECT dst,symbol,src_word,dst_word,pair_id,resolved FROM pointers "
            "WHERE src=? ORDER BY id LIMIT ?", (synset, limit)).fetchall()
        return [dict(zip(("target","relation","src_word","dst_word","pair_id","resolved"), row))
                for row in rows]


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("install")
    build.add_argument("zip", type=Path)
    build.add_argument("store", type=Path)
    audit = sub.add_parser("verify")
    audit.add_argument("store", type=Path)
    args = parser.parse_args()
    result = install(args.zip, args.store) if args.command == "install" else verify(args.store)
    print(json.dumps(result, sort_keys=True, indent=2))

if __name__ == "__main__":
    main()
