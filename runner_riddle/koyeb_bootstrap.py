"""Fail-safe startup bootstrap for the Koyeb BS0:0 control-plane service.

The bootstrap intentionally separates three concerns:

* creating the four tier database files when their mount roots are writable;
* signing a volume registry only when every provider binding is present;
* refusing to start only when the operator opts into strict registry health.

A service without Koyeb volume bindings is still a useful control-plane
listener; it must report ``unknown`` rather than pretend a volume is green.
This module contains no mathematical execution and never invents provider IDs,
mount observations, or health.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Callable, Mapping

from .volume_registry import (
    CANONICAL,
    DEFAULT_MOUNT_ROOTS,
    VolumeRegistry,
    VolumeRegistryError,
    build_koyeb_registry,
    write_koyeb_registry,
)

SCHEMA = "nanrouter.koyeb-bootstrap.v1"
REQUIRE_ENV = "RIDDLE_REQUIRE_VOLUME_REGISTRY"
DEFAULT_REGISTRY_PATH = "/data/volume-registry.json"

MountProbe = Callable[[str], bool]


class KoyebBootstrapError(RuntimeError):
    """A configured-but-invalid deployment must fail closed."""


def _as_bool(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})


def _has_any_volume_config(environ: Mapping[str, str]) -> bool:
    if environ.get("RIDDLE_VOLUME_HMAC_KEY") or environ.get("KOYEB_REGION"):
        return True
    return any(environ.get(f"KOYEB_VOLUME_ID_{tier}") for tier in CANONICAL)


def _missing_volume_config(environ: Mapping[str, str]) -> list[str]:
    missing: list[str] = []
    key = environ.get("RIDDLE_VOLUME_HMAC_KEY", "").encode()
    if len(key) < 32:
        missing.append("RIDDLE_VOLUME_HMAC_KEY")
    if not environ.get("KOYEB_REGION", "").strip():
        missing.append("KOYEB_REGION")
    for tier in CANONICAL:
        value = environ.get(f"KOYEB_VOLUME_ID_{tier}", "").strip()
        if not value or value.startswith("<") or "placeholder" in value.lower():
            missing.append(f"KOYEB_VOLUME_ID_{tier}")
    return missing


def mount_root(environ: Mapping[str, str], tier: str) -> Path:
    """Return the configured physical mount for a canonical tier."""
    if tier not in CANONICAL:
        raise KoyebBootstrapError("unknown volume tier")
    return Path(
        environ.get(f"KOYEB_MOUNT_ROOT_{tier}", DEFAULT_MOUNT_ROOTS[tier]).strip()
    )


def ensure_tier_database(root: Path, tier: str) -> Path:
    """Create the canonical tier database file if the mount is writable.

    This is bootstrap bookkeeping, not a claim that the volume is mounted.  A
    physically absent mount remains ``mount_verified=false`` in the signed
    registry because the volume registry probes ``os.path.ismount`` separately.
    """
    root.mkdir(parents=True, exist_ok=True)
    database = root / CANONICAL[tier][1]
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS router_volume_bootstrap "
            "(tier TEXT PRIMARY KEY, created_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT OR REPLACE INTO router_volume_bootstrap(tier, created_at) "
            "VALUES (?, datetime('now'))",
            (tier,),
        )
    return database


def default_registry_path(environ: Mapping[str, str]) -> Path:
    return Path(
        environ.get(
            "RIDDLE_VOLUME_REGISTRY_PATH",
            str(Path(environ.get("RIDDLE_DATA_DIR", "/data")) / "volume-registry.json"),
        )
    )


def bootstrap_koyeb(
    environ: Mapping[str, str] | None = None,
    *,
    registry_path: str | Path | None = None,
    mount_probe: MountProbe | None = None,
    now_tick: int | None = None,
    write_registry: bool = True,
    initialize_databases: bool = True,
) -> dict[str, Any]:
    """Bootstrap tier databases and, when configured, the signed registry.

    Returns a JSON-safe report.  ``ok`` is false only for a partial/invalid
    volume configuration or when strict registry health was requested and not
    achieved.  Missing volume configuration is deliberately not an error.
    """
    env = dict(os.environ if environ is None else environ)
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "ok": True,
        "databases": {},
        "registry": {
            "configured": False,
            "status": "not_configured",
            "written": False,
        },
    }

    if initialize_databases:
        for tier in CANONICAL:
            root = mount_root(env, tier)
            try:
                database = ensure_tier_database(root, tier)
            except OSError as exc:
                result["databases"][tier] = {
                    "root": str(root),
                    "status": "unwritable",
                    "error": exc.__class__.__name__,
                }
            else:
                result["databases"][tier] = {
                    "root": str(root),
                    "status": "ready",
                    "database": str(database),
                }

    if not _has_any_volume_config(env):
        if _as_bool(env.get(REQUIRE_ENV)):
            result["ok"] = False
            result["registry"] = {
                "configured": False,
                "status": "missing",
                "written": False,
                "required": True,
            }
            raise KoyebBootstrapError(
                "RIDDLE_REQUIRE_VOLUME_REGISTRY is set but no Koyeb volume bindings exist"
            )
        return result

    missing = _missing_volume_config(env)
    if missing:
        result["ok"] = False
        result["registry"] = {
            "configured": True,
            "status": "invalid",
            "written": False,
            "missing": missing,
        }
        if _as_bool(env.get(REQUIRE_ENV)):
            raise KoyebBootstrapError(
                "Koyeb volume configuration is incomplete: " + ", ".join(missing)
            )
        return result

    target = Path(registry_path) if registry_path is not None else default_registry_path(env)
    previous_digest = None
    generation = 1
    try:
        if target.exists():
            previous = VolumeRegistry.load(target, env["RIDDLE_VOLUME_HMAC_KEY"].encode())
            generation = previous.document["generation"] + 1
            previous_digest = previous.document["registry_digest"]
        registry = build_koyeb_registry(
            env,
            mount_probe=mount_probe,
            now_tick=now_tick,
            generation=generation,
            previous_digest=previous_digest,
        )
        if write_registry:
            write_koyeb_registry(target, registry)
    except (VolumeRegistryError, OSError) as exc:
        result["ok"] = False
        result["registry"] = {
            "configured": True,
            "status": "invalid",
            "written": False,
            "error": str(exc),
        }
        if _as_bool(env.get(REQUIRE_ENV)):
            raise KoyebBootstrapError(f"volume registry bootstrap failed: {exc}") from exc
        return result

    result["registry"] = {
        "configured": True,
        "status": registry.health,
        "written": bool(write_registry),
        "path": str(target),
        "generation": registry.document["generation"],
        "registry_digest": registry.document["registry_digest"],
    }
    if _as_bool(env.get(REQUIRE_ENV)) and registry.health != "green":
        result["ok"] = False
        raise KoyebBootstrapError(
            f"strict volume registry health is not green: {registry.health}"
        )
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the signed registry when configured")
    parser.add_argument("--path", default=None, help="override RIDDLE_VOLUME_REGISTRY_PATH")
    parser.add_argument("--no-databases", action="store_true", help="do not create tier database files")
    parser.add_argument("--quiet", action="store_true", help="suppress the JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = bootstrap_koyeb(
            registry_path=args.path,
            write_registry=args.write,
            initialize_databases=not args.no_databases,
        )
    except KoyebBootstrapError as exc:
        report = {
            "schema": SCHEMA,
            "ok": False,
            "error": str(exc),
            "registry": {"status": "blocked"},
        }
        if not args.quiet:
            print(json.dumps(report, sort_keys=True, indent=2))
        return 2
    if not args.quiet:
        print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
