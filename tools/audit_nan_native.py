#!/usr/bin/env python3
"""Audit the NaN16-native boundary and its declared host exceptions.

This is a static coverage audit. It proves that every registered kernel has a
NaN16 source and fixture, that every native source is registered, that every
fixture is wired into the canonical runner and CI workflow, and that production
control modules do not import host numerical libraries. It does not prove
numerical equivalence; that remains the job of the native fixtures and CI.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "spec/nan-native-boundary.json"
MANIFEST_PATH = REPO_ROOT / "spec/wave-capabilities.json"
RUNNER_PATH = REPO_ROOT / "tools/run_mth_fixtures.py"
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/mth-native-contract.yml"

_FIXTURE_RE = re.compile(
    r'Fixture\(\s*"(?P<name>[^"]+)"\s*,\s*"(?P<path>[^"]+)"'
)
def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _layer_for(kernel_id: str, layers: list[dict[str, Any]]) -> str | None:
    """Choose the longest matching prefix; ties use manifest layer order."""
    best: tuple[int, int, str] | None = None
    for index, layer in enumerate(layers):
        for prefix in layer.get("prefixes", []):
            if kernel_id.startswith(prefix):
                candidate = (len(prefix), -index, layer["id"])
                if best is None or candidate > best:
                    best = candidate
    return best[2] if best else None


def _top_level_imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {"<unreadable>"}
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".", 1)[0])
    return roots


def _runner_fixtures() -> dict[str, str]:
    text = RUNNER_PATH.read_text(encoding="utf-8")
    return {match.group("name"): match.group("path") for match in _FIXTURE_RE.finditer(text)}


def _workflow_fixture_mentions() -> tuple[set[str], set[str], str]:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    paths = set(re.findall(r"mth/tests/([A-Za-z0-9_.-]+\.nas)", text))
    stems = {Path(path).stem for path in paths}
    # The compact arithmetic loop refers to fixtures by their basename stem.
    stems.update(re.findall(r"\b(mth_[A-Za-z0-9_.-]+_test)\b", text))
    names = set(re.findall(r"--only\s+([A-Za-z0-9_]+)", text))
    return stems, names, text


def audit(
    *,
    repo_root: Path = REPO_ROOT,
    spec_path: Path = SPEC_PATH,
    manifest_path: Path = MANIFEST_PATH,
    runner_path: Path = RUNNER_PATH,
    workflow_path: Path = WORKFLOW_PATH,
) -> dict[str, Any]:
    spec = _read_json(spec_path)
    manifest = _read_json(manifest_path)
    kernels = manifest["kernels"]
    layers = spec["layers"]
    errors: list[str] = []
    layer_counts = {layer["id"]: 0 for layer in layers}

    registered_sources: set[str] = set()
    unique_fixtures: set[str] = set()
    for index, kernel in enumerate(kernels):
        kernel_id = kernel.get("kernel_id")
        label = f"kernel[{index}] {kernel_id}"
        if not isinstance(kernel_id, str) or not kernel_id.startswith("mth."):
            errors.append(f"{label}: invalid kernel_id")
            continue
        source = kernel.get("source")
        fixture = kernel.get("fixture")
        if not source or not (repo_root / source).is_file():
            errors.append(f"{label}: missing native source {source!r}")
        else:
            registered_sources.add(source)
        if not fixture or not (repo_root / fixture).is_file():
            errors.append(f"{label}: missing native fixture {fixture!r}")
        else:
            unique_fixtures.add(fixture)
        if kernel.get("status") not in {"source_written", "native_verified", "ci_verified"}:
            errors.append(f"{label}: invalid status {kernel.get('status')!r}")
        if not isinstance(kernel.get("ci_verified"), bool):
            errors.append(f"{label}: ci_verified must be boolean")
        if not kernel.get("marker"):
            errors.append(f"{label}: empty fixture marker")
        layer = _layer_for(kernel_id, layers)
        if layer is None:
            errors.append(f"{label}: no L0-L7 layer assignment")
        else:
            layer_counts[layer] += 1

    native_sources = {
        _relative(path)
        for path in (repo_root / spec["native_source_dir"]).glob("*.nas")
    }
    for source in sorted(native_sources - registered_sources):
        errors.append(f"native source is not registered in the manifest: {source}")
    for source in sorted(registered_sources - native_sources):
        errors.append(f"manifest source is not under {spec['native_source_dir']}: {source}")

    fixtures = _runner_fixtures()
    runner_fixture_paths = set(fixtures.values())
    for fixture in sorted(unique_fixtures - runner_fixture_paths):
        errors.append(f"manifest fixture is missing from the canonical runner: {fixture}")
    for fixture in sorted(runner_fixture_paths - unique_fixtures):
        errors.append(f"runner fixture is not registered in the manifest: {fixture}")

    workflow_stems, workflow_names, workflow_text = _workflow_fixture_mentions()
    for name, fixture in sorted(fixtures.items()):
        path = Path(fixture)
        if (
            fixture in workflow_text
            or path.stem in workflow_stems
            or name in workflow_names
        ):
            continue
        errors.append(f"runner fixture is not referenced by the CI workflow: {fixture}")

    boundary = spec["host_boundary"]
    all_runner_modules = sorted((repo_root / "runner_riddle").glob("*.py"))
    for path in all_runner_modules:
        imports = _top_level_imports(path)
        forbidden = imports & set(boundary["forbidden_numeric_imports_global"])
        for name in sorted(forbidden):
            errors.append(f"{_relative(path)} imports forbidden numeric module {name}")

    for module in boundary["control_modules"]:
        path = repo_root / module
        if not path.is_file():
            errors.append(f"declared control module is missing: {module}")
            continue
        imports = _top_level_imports(path)
        forbidden = imports & set(boundary["forbidden_in_control_modules"])
        for name in sorted(forbidden):
            errors.append(f"control module {module} imports host numeric module {name}")

    for row in boundary["metadata_math_modules"]:
        module = row["module"]
        path = repo_root / module
        if not path.is_file():
            errors.append(f"declared metadata-math module is missing: {module}")
            continue
        imports = _top_level_imports(path)
        forbidden = imports & set(boundary["forbidden_in_metadata_modules"])
        for name in sorted(forbidden):
            errors.append(f"metadata module {module} imports forbidden numeric module {name}")

    for row in boundary["experiment_analysis_modules"]:
        module = row["module"]
        if not (repo_root / module).is_file():
            errors.append(f"declared experiment-analysis module is missing: {module}")

    return {
        "schema": "nanrouter.nan-native-audit.v1",
        "status": "green" if not errors else "blocked",
        "kernel_count": len(kernels),
        "native_source_count": len(native_sources),
        "unique_fixture_count": len(unique_fixtures),
        "runner_fixture_count": len(runner_fixture_paths),
        "layer_counts": layer_counts,
        "control_modules": len(boundary["control_modules"]),
        "metadata_math_modules": len(boundary["metadata_math_modules"]),
        "experiment_analysis_modules": len(boundary["experiment_analysis_modules"]),
        "errors": errors,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the full JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = audit()
    if args.json:
        print(json.dumps(report, sort_keys=True, indent=2))
    else:
        print(
            f"status={report['status']} kernels={report['kernel_count']} "
            f"sources={report['native_source_count']} fixtures={report['unique_fixture_count']} "
            f"runner={report['runner_fixture_count']}"
        )
        for layer, count in report["layer_counts"].items():
            print(f"{layer} kernels={count}")
        for error in report["errors"]:
            print(f"ERROR {error}")
    return 0 if report["status"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
