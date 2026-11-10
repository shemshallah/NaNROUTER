"""Bootstrap pinned HW4 WordNet release into NaNROUTER persistent MC0 storage.

Only when explicitly enabled at startup. Never writes BS0 or a native guest
memory image; the service later mounts the verified generation read-only.
No release tag discovery, mutable/latest URLs, or arbitrary tar extraction.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
from urllib.request import urlopen

from .hw4_full_dict import verify

RELEASE_URL = (
    "https://github.com/shemshallah/NaNROUTER/releases/download/"
    "hw4-wordnet31-full-g1/hw4-wordnet31-full-reference.tar.gz"
)
ARCHIVE_SHA256 = "87dbcdd2d209db95e8d15be68109ef3642e78ef540ea12ad71f3b04982876695"
ROOT_DIR = "hw4-full-reference"
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_EXTRACT_BYTES = 192 * 1024 * 1024


class HW4BootstrapError(RuntimeError):
    pass


def _allowed_root(store: Path):
    # Never permit cross-owner installation on the main BS0 volume.
    parts = store.resolve(strict=False).parts
    if "bs0db" in parts:
        raise HW4BootstrapError("HW4 may not be installed on BS0DB")
    if store.exists() and store.is_symlink():
        raise HW4BootstrapError("HW4 root must not be a symlink")


def _download(path: Path):
    digest = hashlib.sha256()
    total = 0
    with urlopen(RELEASE_URL, timeout=30) as response, path.open("xb") as f:
        while True:
            part = response.read(1024 * 1024)
            if not part:
                break
            total += len(part)
            if total > MAX_ARCHIVE_BYTES:
                raise HW4BootstrapError("HW4 release archive exceeds limit")
            digest.update(part)
            f.write(part)
        f.flush()
        os.fsync(f.fileno())
    if digest.hexdigest() != ARCHIVE_SHA256:
        raise HW4BootstrapError("pinned HW4 release SHA256 mismatch")


def _extract(archive: Path, target: Path):
    total = 0
    with tarfile.open(archive, "r:gz") as tar:
        for entry in tar:
            p = PurePosixPath(entry.name)
            if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] != ROOT_DIR:
                raise HW4BootstrapError("HW4 release contains invalid path")
            if not (entry.isfile() or entry.isdir()):
                raise HW4BootstrapError("HW4 release contains unsupported link or special member")
            if entry.isfile():
                total += entry.size
                if total > MAX_EXTRACT_BYTES:
                    raise HW4BootstrapError("HW4 extracted data exceeds size limit")
                rel = Path(*p.parts[1:])
                dest = target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                f = tar.extractfile(entry)
                if f is None:
                    raise HW4BootstrapError("HW4 release file missing bytes")
                with f, dest.open("xb") as out:
                    shutil.copyfileobj(f, out, length=1024 * 1024)
                    out.flush()
                    os.fsync(out.fileno())
            else:
                (target / Path(*p.parts[1:])).mkdir(parents=True, exist_ok=True)


def bootstrap(store: str | Path, *, archive_path: str | Path | None = None):
    """Verify an existing store or install the pinned immutable generation.

    archive_path is an offline/testing override: the exact same pinned SHA256
    must match; it never allows an untrusted alternative archive digest.
    """
    store = Path(store)
    _allowed_root(store)
    if store.exists():
        return {"reused": True, "manifest": verify(store)}
    store.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".hw4-release-", dir=store.parent) as td:
        temp = Path(td)
        incoming = temp / "release.tar.gz"
        if archive_path is None:
            _download(incoming)
        else:
            shutil.copyfile(archive_path, incoming)
            if hashlib.sha256(incoming.read_bytes()).hexdigest() != ARCHIVE_SHA256:
                raise HW4BootstrapError("local HW4 release digest mismatch")
        staging = temp / "staging"
        staging.mkdir()
        _extract(incoming, staging)
        manifest = verify(staging)
        if store.exists():
            return {"reused": True, "manifest": verify(store)}
        staging.rename(store)
        descriptor = os.open(store.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return {"reused": False, "manifest": manifest}


def main():
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store", type=Path)
    args = parser.parse_args()
    print(json.dumps(bootstrap(args.store), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
