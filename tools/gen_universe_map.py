#!/usr/bin/env python3
"""Generate the machine-readable full 8 MiB universe map.

This is a control-plane generator.  It performs address arithmetic and hashing
only; it executes no native kernel and makes no mathematical claim.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runner_riddle.universe_map import page_directory_document

DEFAULT_OUTPUT = REPO_ROOT / "spec" / "universe-map.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help="output JSON path (default: spec/universe-map.json)",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="verify that the output is current instead of writing it",
    )
    args = parser.parse_args(argv)
    document = page_directory_document()
    encoded = json.dumps(
        document, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False
    ) + "\n"
    if args.check:
        if not args.output.is_file():
            print(f"missing {args.output}")
            return 1
        if args.output.read_text(encoding="utf-8") != encoded:
            print(f"stale {args.output}")
            return 1
        print(f"current {args.output}")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8")
    print(
        f"wrote {args.output} pages=256 points=32896 "
        f"digest={document['page_directory_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
