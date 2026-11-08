"""Unified MTH catalog across the NaN repositories.

This module is a control-plane index and drift audit.  It does not execute a
kernel, perform host mathematics, fetch the network, or claim that a local
checkout is a live deployment.  Native execution remains owned by NaN0S; NMP
admission and routing remain owned by NaNROUTER.

The stable catalog binds:

* every native kernel in ``spec/wave-capabilities.json`` to one function route
  and one execution mode;
* the full 8 MiB universe map and all 32,896 relation points;
* the provider contracts from NaN0S, HERMES, Android, NaNLMind, NaNLM and
  CLOCKED when their local checkouts are present;
* local repository HEAD/dirty state as evidence, not as a CI or live claim.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .universe_map import status as universe_map_status

SCHEMA = "nanrouter.mth-unified-catalog.v1"
SPEC_SCHEMA = "nanrouter.mth-unified-system.v1"
MANIFEST_SCHEMA = "nanrouter.wave-capabilities.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "spec" / "mth-unified-system.v1.json"
MANIFEST_PATH = REPO_ROOT / "spec" / "wave-capabilities.json"

NATIVE_DISPATCH = frozenset({
    "mth.vector.dot256.f32",
    "mth.vector.cosine256.f32",
    "mth.vector.add256.f32",
    "mth.vector.sub256.f32",
    "mth.universe.map.u32",
})
EXECUTION_MODES = frozenset({"native_dispatch_abi", "native_fixture_only"})
PROVIDER_STATUSES = frozenset({"available", "unavailable", "drift"})


class MthUnifiedError(ValueError):
    """The unified catalog or one of its provider contracts is invalid."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    )


def _load(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MthUnifiedError(f"cannot read {path}") from exc
    if not isinstance(document, dict):
        raise MthUnifiedError(f"{path} must contain a JSON object")
    return document


def _git(path: Path, *args: str, text: bool = True) -> str | bytes | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            check=False, text=text, capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip() if text else result.stdout
    return value or None


def _git_show(path: Path, relative: str, ref: str = "origin/main") -> str | None:
    """Read a tracked file from the fetched remote ref without checking it out."""
    value = _git(path, "show", f"{ref}:{relative}", text=True)
    return value if isinstance(value, str) else None


def _provider_artifact(path: Path, relative: str) -> tuple[bool, str | None, str | None]:
    """Return (present, sha256, source) using the worktree or origin/main."""
    target = path / relative
    if target.is_file():
        return True, _sha256_file(target), "worktree"
    remote = _git_show(path, relative)
    if remote is None:
        return False, None, None
    return True, _sha256_bytes(remote.encode("utf-8")), "origin/main"


def repository_state(path: Path) -> dict | None:
    """Read local git identity only; never fetch, push, or modify the repo."""
    if not (path / ".git").exists():
        return None
    head = _git(path, "rev-parse", "HEAD")
    if head is None:
        return None
    branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    origin_main = _git(path, "rev-parse", "refs/remotes/origin/main")
    status = _git(path, "status", "--porcelain")
    return {
        "path": str(path),
        "branch": branch,
        "head": head,
        "origin_main": origin_main,
        "dirty": bool(status),
        "behind_origin_main": bool(
            origin_main and head and origin_main != head
        ),
    }


def scan_nan_repositories(root: Path | None = None) -> list[dict]:
    """Record local NaN repository heads; no network and no working-tree write."""
    root = (root or Path.home()).expanduser()
    if not root.is_dir():
        return []
    found = []
    for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_dir():
            continue
        if not path.name.lower().startswith("nan"):
            continue
        state = repository_state(path)
        if state is not None:
            found.append({"name": path.name, **state})
    return found


def _provider_path(value: str) -> Path:
    return Path(value).expanduser()


def _audit_provider(spec: dict, *, strict: bool) -> dict:
    path = _provider_path(spec["local_path"])
    result = {
        "id": spec["id"],
        "repo": spec["repo"],
        "role": spec["role"],
        "required": bool(spec.get("required")),
        "path": str(path),
        "exists": path.is_dir(),
        "artifacts": [],
        "contracts": [],
        "status": "unavailable",
    }
    if not path.is_dir():
        if strict and result["required"]:
            result["error"] = "required provider checkout is missing"
        return result
    missing = []
    for relative in spec.get("required_artifacts", []):
        present, digest, source = _provider_artifact(path, relative)
        result["artifacts"].append({
            "path": relative,
            "present": present,
            "sha256": digest,
            "source": source,
        })
        if not present:
            missing.append(relative)
    mismatched = []
    remote_used = False
    for contract in spec.get("contracts", []):
        relative = contract["file"]
        expected = contract["contains"]
        local = path / relative
        text = (
            local.read_text(encoding="utf-8", errors="replace")
            if local.is_file() else None
        )
        present = text is not None and expected in text
        source = "worktree" if present else None
        if not present:
            remote = _git_show(path, relative)
            if remote is not None and expected in remote:
                present = True
                source = "origin/main"
                remote_used = True
        result["contracts"].append({
            "file": relative,
            "contains": expected,
            "present": present,
            "source": source,
        })
        if not present:
            mismatched.append({
                "file": relative, "reason": "contract text absent",
            })
    if missing or mismatched:
        result["status"] = "drift"
        result["error"] = "provider artifact or contract drift"
        result["missing"] = missing
        result["mismatched"] = mismatched
    else:
        result["status"] = "available"
        result["contract_source"] = "origin/main" if remote_used else "worktree"
    return result


def _kernel_entries(repo_root: Path, manifest: dict) -> tuple[list[dict], dict]:
    entries = []
    seen: set[str] = set()
    source_digests: dict[str, str] = {}
    fixture_digests: dict[str, str] = {}
    for index, kernel in enumerate(manifest["kernels"]):
        if not isinstance(kernel, dict):
            raise MthUnifiedError(f"kernel[{index}] is not an object")
        kernel_id = kernel.get("kernel_id")
        if not isinstance(kernel_id, str) or not kernel_id.startswith("mth."):
            raise MthUnifiedError(f"kernel[{index}] has an invalid id")
        if kernel_id in seen:
            raise MthUnifiedError(f"duplicate kernel id: {kernel_id}")
        seen.add(kernel_id)
        source = repo_root / str(kernel.get("source", ""))
        fixture = repo_root / str(kernel.get("fixture", ""))
        if not source.is_file():
            raise MthUnifiedError(f"{kernel_id}: missing source")
        if not fixture.is_file():
            raise MthUnifiedError(f"{kernel_id}: missing fixture")
        source_digest = _sha256_file(source)
        fixture_digest = _sha256_file(fixture)
        source_digests[str(kernel["source"])] = source_digest
        fixture_digests[str(kernel["fixture"])] = fixture_digest
        mode = (
            "native_dispatch_abi"
            if kernel_id in NATIVE_DISPATCH
            else "native_fixture_only"
        )
        if mode not in EXECUTION_MODES:
            raise MthUnifiedError(f"{kernel_id}: invalid execution mode")
        entries.append({
            "kernel_id": kernel_id,
            "version": 1,
            "family": kernel_id.split(".")[1],
            "status": kernel.get("status"),
            "ci_verified": kernel.get("ci_verified") is True,
            "execution_mode": mode,
            "native_dispatch_abi": mode == "native_dispatch_abi",
            "control_provider": "nanrouter.control",
            "executor_provider": "nan0s.vm",
            "route": (
                "math://GM0:SC0:MC0:BS0:0/function/"
                f"{kernel_id}@v1"
            ),
            "precision": kernel.get("precision"),
            "shape": kernel.get("shape"),
            "workspace_words": kernel.get("workspace_words"),
            "source": kernel.get("source"),
            "fixture": kernel.get("fixture"),
            "source_sha256": source_digest,
            "fixture_sha256": fixture_digest,
        })
    catalog = {
        "source": "spec/wave-capabilities.json",
        "schema": manifest.get("schema"),
        "count": len(entries),
        "ci_verified": sum(1 for item in entries if item["ci_verified"]),
        "local_only": sum(1 for item in entries if not item["ci_verified"]),
        "native_dispatch_abi": sum(
            1 for item in entries if item["native_dispatch_abi"]
        ),
        "unique_sources": len(source_digests),
        "unique_fixtures": len(fixture_digests),
        "kernel_ids_sha256": _sha256_bytes(
            _canonical(sorted(seen)).encode("utf-8")
        ),
        "source_set_sha256": _sha256_bytes(
            _canonical(source_digests).encode("utf-8")
        ),
        "fixture_set_sha256": _sha256_bytes(
            _canonical(fixture_digests).encode("utf-8")
        ),
    }
    return entries, catalog


def build_catalog(
    *,
    repo_root: Path = REPO_ROOT,
    spec_path: Path = SPEC_PATH,
    manifest_path: Path = MANIFEST_PATH,
    strict: bool = False,
    scan_repositories: bool = False,
    repository_root: Path | None = None,
) -> dict:
    """Build one deterministic unified catalog and provider audit."""
    spec = _load(spec_path)
    if spec.get("schema") != SPEC_SCHEMA:
        raise MthUnifiedError("unsupported unified-system schema")
    manifest = _load(manifest_path)
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise MthUnifiedError("unsupported manifest schema")
    if not isinstance(manifest.get("kernels"), list) or not manifest["kernels"]:
        raise MthUnifiedError("manifest has no kernels")

    kernels, kernel_catalog = _kernel_entries(repo_root, manifest)
    universe = universe_map_status()
    if universe.get("status") != "green":
        raise MthUnifiedError("universe map is not green")

    providers = [
        _audit_provider(provider, strict=strict)
        for provider in spec.get("providers", [])
    ]
    provider_ids = [item["id"] for item in providers]
    if len(provider_ids) != len(set(provider_ids)):
        raise MthUnifiedError("provider ids are not unique")

    errors = [
        f"{item['id']}: {item.get('error', item['status'])}"
        for item in providers
        if item["status"] == "drift"
        or (strict and item["required"] and item["status"] == "unavailable")
    ]
    warnings = [
        f"{item['id']}: unavailable"
        for item in providers
        if item["status"] == "unavailable"
    ]
    if kernel_catalog["count"] != len(kernels):
        errors.append("kernel catalog count mismatch")
    if universe["relation_points"] != (
        universe["fixed_heads"] + universe["mirror_pairs"]
    ):
        errors.append("relation-point count mismatch")

    stable = {
        "schema": SCHEMA,
        "spec_schema": SPEC_SCHEMA,
        "version": spec.get("version"),
        "canonical_language": spec.get("canonical_language"),
        "canonical_word": spec.get("canonical_word"),
        "universe": spec.get("universe"),
        "universe_map": universe,
        "control_plane": spec.get("control_plane"),
        "routes": spec.get("routes"),
        "authority": spec.get("authority"),
        "kernel_catalog": kernel_catalog,
        "kernels": kernels,
        "providers": [
            {
                "id": provider["id"],
                "repo": provider["repo"],
                "role": provider["role"],
                "required": bool(provider.get("required")),
                "required_artifacts": list(provider.get("required_artifacts", [])),
                "contracts": [
                    {"file": contract["file"], "contains": contract["contains"]}
                    for contract in provider.get("contracts", [])
                ],
            }
            for provider in spec.get("providers", [])
        ],
    }
    stable["catalog_sha256"] = _sha256_bytes(_canonical(stable).encode("utf-8"))
    document = {
        **stable,
        "status": "green" if not errors else "blocked",
        "errors": errors,
        "warnings": warnings,
        "provider_audit": providers,
        "evidence_policy": spec.get("evidence_policy"),
        "repositories": (
            scan_nan_repositories(repository_root) if scan_repositories else []
        ),
        "claims_ci_verified": False,
        "claims_live_deployment": False,
    }
    return document


def audit(**kwargs) -> dict:
    return build_catalog(**kwargs)


def write_catalog(path: Path, **kwargs) -> dict:
    document = build_catalog(**kwargs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, sort_keys=True, indent=2, ensure_ascii=True)
        + "\n",
        encoding="utf-8",
    )
    return document


__all__ = [
    "EXECUTION_MODES",
    "MANIFEST_SCHEMA",
    "MthUnifiedError",
    "NATIVE_DISPATCH",
    "PROVIDER_STATUSES",
    "REPO_ROOT",
    "SCHEMA",
    "SPEC_SCHEMA",
    "audit",
    "build_catalog",
    "repository_state",
    "scan_nan_repositories",
    "write_catalog",
]
