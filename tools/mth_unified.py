#!/usr/bin/env python3
"""Build or check the unified MTH catalog across local NaN repositories.

No network fetch, native execution, or credential access occurs here.  The
tool records local repository heads only when ``--scan-repositories`` is used.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runner_riddle.mth_unified import (
    MANIFEST_PATH,
    REPO_ROOT as PACKAGE_ROOT,
    SPEC_PATH,
    build_catalog,
    write_catalog,
)
from runner_riddle.universe_map import page_directory_document

DEFAULT_OUTPUT = PACKAGE_ROOT / "build" / "mth" / "unified-catalog.json"


def _check_universe_spec() -> list[str]:
    spec = PACKAGE_ROOT / "spec" / "universe-map.json"
    if not spec.is_file():
        return [f"missing {spec}"]
    expected = page_directory_document()
    actual = json.loads(spec.read_text(encoding="utf-8"))
    return [] if actual == expected else [f"stale {spec}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", type=Path, nargs="?", const=DEFAULT_OUTPUT, default=None,
        help="write the catalog (default: build/mth/unified-catalog.json)",
    )
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument(
        "--strict", action="store_true",
        help="fail when a required provider checkout is missing",
    )
    parser.add_argument(
        "--scan-repositories", action="store_true",
        help="include local NaN repository HEAD/dirty evidence",
    )
    parser.add_argument(
        "--repository-root", type=Path, default=None,
        help="root used by --scan-repositories (default: home)",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="verify the generated universe map and catalog status",
    )
    args = parser.parse_args(argv)

    errors = _check_universe_spec() if args.check else []
    document = build_catalog(
        repo_root=REPO_ROOT,
        spec_path=SPEC_PATH,
        manifest_path=MANIFEST_PATH,
        strict=args.strict,
        scan_repositories=args.scan_repositories,
        repository_root=args.repository_root,
    )
    errors.extend(document["errors"])
    if args.write is not None:
        write_catalog(
            args.write,
            repo_root=REPO_ROOT,
            spec_path=SPEC_PATH,
            manifest_path=MANIFEST_PATH,
            strict=args.strict,
            scan_repositories=args.scan_repositories,
            repository_root=args.repository_root,
        )
        print(f"wrote {args.write}")
    if args.json:
        print(json.dumps(document, sort_keys=True, indent=2))
    else:
        print(
            "status={status} kernels={count} sources={sources} "
            "fixtures={fixtures} points={points} providers={providers} "
            "warnings={warnings}".format(
                status=document["status"],
                count=document["kernel_catalog"]["count"],
                sources=document["kernel_catalog"]["unique_sources"],
                fixtures=document["kernel_catalog"]["unique_fixtures"],
                points=document["universe_map"]["relation_points"],
                providers=len(document["provider_audit"]),
                warnings=len(document["warnings"]),
            )
        )
        if errors:
            for error in errors:
                print(f"ERROR {error}")
    return 0 if not errors and document["status"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
