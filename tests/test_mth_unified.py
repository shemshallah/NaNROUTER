from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from runner_riddle.mth_unified import (
    MANIFEST_PATH,
    REPO_ROOT,
    SPEC_PATH,
    MthUnifiedError,
    build_catalog,
    repository_state,
    scan_nan_repositories,
)


def _write_spec(path: Path, providers: list[dict]) -> Path:
    document = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    document["providers"] = providers
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _provider(root: Path, name: str = "test.provider", **extra) -> dict:
    value = {
        "id": name,
        "repo": "TEST",
        "role": "test provider",
        "local_path": str(root),
        "required": True,
        "required_artifacts": ["artifact.txt"],
        "contracts": [{"file": "artifact.txt", "contains": "CONTRACT"}],
    }
    value.update(extra)
    return value


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, text=True, capture_output=True,
    )


class MthUnifiedTests(unittest.TestCase):
    def test_real_catalog_covers_every_kernel_and_relation_point(self):
        catalog = build_catalog()
        self.assertEqual(catalog["schema"], "nanrouter.mth-unified-catalog.v1")
        self.assertEqual(catalog["status"], "green", catalog["errors"])
        self.assertEqual(catalog["kernel_catalog"]["count"], 135)
        self.assertEqual(catalog["kernel_catalog"]["ci_verified"], 133)
        self.assertEqual(catalog["kernel_catalog"]["local_only"], 2)
        self.assertEqual(catalog["kernel_catalog"]["unique_sources"], 133)
        self.assertEqual(catalog["kernel_catalog"]["unique_fixtures"], 132)
        self.assertEqual(catalog["kernel_catalog"]["native_dispatch_abi"], 5)
        self.assertEqual(catalog["universe_map"]["relation_points"], 32_896)
        self.assertEqual(catalog["universe_map"]["pages"], 256)
        self.assertEqual(catalog["universe_map"]["universe_bytes"], 8 * 1024 * 1024)
        self.assertEqual(len(catalog["kernels"]), 135)
        self.assertEqual(
            len({item["kernel_id"] for item in catalog["kernels"]}), 135
        )
        for kernel in catalog["kernels"]:
            self.assertTrue(kernel["route"].startswith("math://"))
            self.assertEqual(
                kernel["route"].split("/")[-1], kernel["kernel_id"] + "@v1"
            )
            self.assertIn(kernel["execution_mode"], {
                "native_dispatch_abi", "native_fixture_only"
            })
            self.assertEqual(len(kernel["source_sha256"]), 64)
            self.assertEqual(len(kernel["fixture_sha256"]), 64)
        self.assertFalse(catalog["claims_ci_verified"])
        self.assertFalse(catalog["claims_live_deployment"])
        self.assertEqual(len(catalog["catalog_sha256"]), 64)

    def test_catalog_digest_is_deterministic(self):
        first = build_catalog()
        second = build_catalog()
        self.assertEqual(first["catalog_sha256"], second["catalog_sha256"])
        self.assertEqual(first["kernel_catalog"], second["kernel_catalog"])
        self.assertEqual(first["universe_map"], second["universe_map"])

    def test_missing_required_provider_is_warning_then_strict_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = _write_spec(
                Path(tmp) / "spec.json",
                [_provider(Path(tmp) / "missing")],
            )
            relaxed = build_catalog(spec_path=spec)
            self.assertEqual(relaxed["status"], "green")
            self.assertEqual(relaxed["provider_audit"][0]["status"], "unavailable")
            self.assertTrue(relaxed["warnings"])
            strict = build_catalog(spec_path=spec, strict=True)
            self.assertEqual(strict["status"], "blocked")
            self.assertTrue(strict["errors"])

    def test_provider_contract_drift_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "provider"
            root.mkdir()
            (root / "artifact.txt").write_text("wrong contract", encoding="utf-8")
            spec = _write_spec(Path(tmp) / "spec.json", [_provider(root)])
            catalog = build_catalog(spec_path=spec)
            self.assertEqual(catalog["status"], "blocked")
            audit = catalog["provider_audit"][0]
            self.assertEqual(audit["status"], "drift")
            self.assertTrue(audit["mismatched"])
            self.assertEqual(catalog["errors"], ["test.provider: provider artifact or contract drift"])

    def test_origin_main_is_used_without_touching_a_dirty_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _git(repo, "init", "-q")
            _git(repo, "config", "user.email", "test@example.invalid")
            _git(repo, "config", "user.name", "Test")
            (repo / "artifact.txt").write_text(
                "CONTRACT\nlocal user work\n", encoding="utf-8"
            )
            _git(repo, "add", "artifact.txt")
            _git(repo, "commit", "-q", "-m", "contract")
            _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
            # The local worktree is deliberately behind and dirty.
            (repo / "artifact.txt").write_text("dirty local edit\n", encoding="utf-8")
            spec = _write_spec(Path(tmp) / "spec.json", [_provider(repo)])
            catalog = build_catalog(spec_path=spec)
            self.assertEqual(catalog["status"], "green", catalog["errors"])
            audit = catalog["provider_audit"][0]
            self.assertEqual(audit["status"], "available")
            self.assertEqual(audit["contract_source"], "origin/main")
            self.assertEqual(
                audit["contracts"][0]["source"], "origin/main"
            )
            state = repository_state(repo)
            self.assertTrue(state["dirty"])
            self.assertIsNotNone(state["head"])
            self.assertEqual(state["origin_main"], state["head"])

    def test_duplicate_manifest_kernel_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            manifest["kernels"].append(dict(manifest["kernels"][0]))
            path = Path(tmp) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(MthUnifiedError):
                build_catalog(manifest_path=path)

    def test_scan_repositories_is_local_and_does_not_modify(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "NaNExample"
            repo.mkdir()
            _git(repo, "init", "-q")
            _git(repo, "config", "user.email", "test@example.invalid")
            _git(repo, "config", "user.name", "Test")
            (repo / "README.md").write_text("NaN\n", encoding="utf-8")
            _git(repo, "add", "README.md")
            _git(repo, "commit", "-q", "-m", "initial")
            before = repository_state(repo)
            found = scan_nan_repositories(root)
            after = repository_state(repo)
            self.assertEqual(before, after)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["name"], "NaNExample")
            self.assertFalse(found[0]["dirty"])


if __name__ == "__main__":
    unittest.main()
