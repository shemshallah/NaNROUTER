"""Static cross-repo contract verifier tests; no sibling repo is modified."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from runner_riddle.n16pack_contract import (
    BANK_BYTES,
    BANK_END,
    BANK_OFFSET,
    BANK_WORDS,
    CHART_BYTES,
    ContractStatus,
    HEAD0_RESERVED_FOR,
    N16PACK1_MAGIC,
    N16ROOT1_MAGIC,
    N16SNAP1_MAGIC,
    NH_WORDS,
    verify_contract,
)


HERMES_TRANSPORT = '''"""Frozen native bank transport fixture."""
BANK_OFFSET = 0x640000
BANK_WORDS = 67838
BANK_BYTES = BANK_WORDS * 8
BANK_END = BANK_OFFSET + BANK_BYTES
BANK_GUEST_WORD_OFFSET = BANK_OFFSET // 8
BANK_HEADS = 255
BANK_FEATURES = 128


def _region(chart):
    """The caller must supply an 8 MiB chart."""
    return chart
'''

HERMES_ROOT = '''"""Frozen N16ROOT1 fixture for one 8 MiB chart."""
ROOT_MAGIC = b"N16ROOT1"
ROOT_VERSION = 1
ROOT_BYTES = 4096
'''

HERMES_CHART = '''"""Frozen chart geometry fixture."""
PAGE_BYTES = 8 * 1024 * 1024
'''

HERMES_PACK = '''"""Frozen N16PACK1 magic fixture."""
MAGIC = b"N16PACK1"
'''

HERMES_SNAP = '''"""Frozen N16SNAP1 snapshot geometry fixture."""
MAGIC = b"N16SNAP1"
PAGE_BYTES = 8 * 1024 * 1024
'''

NAN0S_NAS = '''; NaN16 head scratch bank: 255 logical heads, double-buffered snapshots.
; head n = base + 8 + (n-1)*266
;   nh_put:    r1=base,r2=head(1..255),r3=source of 128 NaN16 words
.equ NH_MAGIC 0x4E485331
.equ NH_SLOT_MAGIC 0x4E484431
.equ NH_COMMIT 0x434D5431
.equ NH_STRIDE 266
.equ NH_SLOT 133
.equ NH_DATA 128
.equ NH_WORDS 67838
'''

NAN0S_DOC = '''# Native head runtime fixture

This is a guest-native scratch bank. Head 0 is reserved for NANNET0.
NH_WORDS=67838 and the bank is exactly 67,838 NaN16 words / 542,704 bytes.
The 8 MiB HERMES chart may carry the bank as raw bytes.
'''

HERMES_FILES = {
    "nanlmind_hermes/head_bank_transport.py": HERMES_TRANSPORT,
    "nanlmind_hermes/universe_root.py": HERMES_ROOT,
    "nanlmind_hermes/universe_chart.py": HERMES_CHART,
    "nanlmind_hermes/universe_pack.py": HERMES_PACK,
    "nanlmind_hermes/chart_storage.py": HERMES_SNAP,
}

NAN0S_FILES = {
    "src/nannet/n16_head_store.nas": NAN0S_NAS,
    "docs/N16_HEAD_RUNTIME.md": NAN0S_DOC,
}


def _git(repository: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
        check=True,
        env=environment,
    )
    return completed.stdout


def _write_files(repository: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        target = repository / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _make_repository(base: Path, name: str, files: dict[str, str]) -> Path:
    repository = base / name
    repository.mkdir()
    _git(repository, "init", "-q")
    _write_files(repository, files)
    _git(repository, "add", "-A")
    _git(
        repository,
        "-c", "user.name=Contract Test",
        "-c", "user.email=contract@example.invalid",
        "commit", "-q", "-m", "frozen contract",
    )
    _git(repository, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repository


def _commit_origin(repository: Path, files: dict[str, str]) -> None:
    _write_files(repository, files)
    _git(repository, "add", "-A")
    _git(
        repository,
        "-c", "user.name=Contract Test",
        "-c", "user.email=contract@example.invalid",
        "commit", "-q", "-m", "origin/main drift",
    )
    _git(repository, "update-ref", "refs/remotes/origin/main", "HEAD")


class TempRepositoryContractTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.hermes = _make_repository(self.base, "hermes", HERMES_FILES)
        self.nan0s = _make_repository(self.base, "nan0s", NAN0S_FILES)

    def verify(self, *, hermes: Path | None = None,
               nan0s: Path | None = None):
        return verify_contract(
            hermes_repo=self.hermes if hermes is None else hermes,
            nan0s_repo=self.nan0s if nan0s is None else nan0s,
        )

    def test_valid_contract_is_available_and_pins_constants(self) -> None:
        report = self.verify()
        self.assertIs(report.status, ContractStatus.AVAILABLE)
        data = report.as_dict()
        self.assertEqual(data["status"], "available")
        self.assertEqual(data["contract"]["n16root1_magic"], "N16ROOT1")
        self.assertEqual(data["contract"]["bank_offset"], BANK_OFFSET)
        self.assertEqual(data["contract"]["bank_words"], BANK_WORDS)
        self.assertEqual(data["contract"]["bank_heads"], 255)
        self.assertEqual(data["contract"]["nh_words"], NH_WORDS)
        self.assertEqual(data["contract"]["head0_reserved_for"],
                         HEAD0_RESERVED_FOR)
        self.assertEqual(data["contract"]["chart_bytes"], CHART_BYTES)
        self.assertEqual(data["contract"]["bank_bytes"], BANK_BYTES)
        self.assertEqual(data["contract"]["bank_end_exclusive"], BANK_END)
        self.assertEqual(data["contract"]["n16pack1_magic"], "N16PACK1")
        self.assertEqual(data["contract"]["n16snap1_magic"], "N16SNAP1")
        self.assertTrue(data["host_only"])
        self.assertFalse(data["network_fetch_performed"])
        self.assertFalse(data["live_deployment_claimed"])
        self.assertFalse(data["repository_mutated"])
        self.assertEqual(data["deployment_status"], "not-observed")
        self.assertTrue(data["origin_main_verified"])
        for provider in ("hermes", "nan0s"):
            self.assertEqual(data["providers"][provider]["status"],
                             "available")
            self.assertIsNotNone(
                data["providers"][provider]["origin_main_commit"]
            )

    def test_dirty_worktree_falls_back_to_git_show_origin_main(self) -> None:
        target = self.hermes / "nanlmind_hermes/head_bank_transport.py"
        target.write_text(
            HERMES_TRANSPORT.replace("BANK_OFFSET = 0x640000",
                                     "BANK_OFFSET = 0x650000"),
            encoding="utf-8",
        )
        report = self.verify()
        self.assertIs(report.status, ContractStatus.AVAILABLE)
        document = report.providers["hermes"]["documents"][
            "head_bank_transport"
        ]
        self.assertEqual(document["source"], "git-show:origin/main")
        self.assertEqual(document["worktree_state"], "dirty")
        self.assertEqual(
            report.providers["hermes"]["constants"]["head_bank_transport"][
                "BANK_OFFSET"
            ],
            BANK_OFFSET,
        )

    def test_missing_worktree_file_falls_back_to_git_show_origin_main(self) -> None:
        (self.nan0s / "src/nannet/n16_head_store.nas").unlink()
        (self.nan0s / "docs/N16_HEAD_RUNTIME.md").unlink()
        report = self.verify()
        self.assertIs(report.status, ContractStatus.AVAILABLE)
        documents = report.providers["nan0s"]["documents"]
        self.assertEqual(documents["n16_head_store"]["source"],
                         "git-show:origin/main")
        self.assertEqual(documents["n16_head_store"]["worktree_state"],
                         "missing")
        self.assertEqual(documents["runtime_doc"]["source"],
                         "git-show:origin/main")
        self.assertEqual(
            report.providers["nan0s"]["constants"]["n16_head_store"][
                "NH_WORDS"
            ],
            NH_WORDS,
        )

    def test_origin_main_contract_drift_is_typed(self) -> None:
        _commit_origin(self.hermes, {
            "nanlmind_hermes/head_bank_transport.py":
                HERMES_TRANSPORT.replace("BANK_OFFSET = 0x640000",
                                         "BANK_OFFSET = 0x650000"),
        })
        # Leave the old worktree behind so drift is also read via git show.
        (self.hermes / "nanlmind_hermes/head_bank_transport.py").write_text(
            HERMES_TRANSPORT, encoding="utf-8"
        )
        report = self.verify()
        self.assertIs(report.status, ContractStatus.DRIFT)
        self.assertEqual(report.providers["hermes"]["status"], "drift")
        document = report.providers["hermes"]["documents"][
            "head_bank_transport"
        ]
        self.assertEqual(document["source"], "git-show:origin/main")
        issues = report.providers["hermes"]["issues"]
        mismatch = [
            issue for issue in issues
            if issue["code"] == "constant-mismatch"
            and issue.get("actual") == 0x650000
        ]
        self.assertTrue(mismatch)
        self.assertEqual(report.as_dict()["status"], "drift")

    def test_documented_head0_or_magic_drift_is_typed(self) -> None:
        _commit_origin(self.nan0s, {
            "docs/N16_HEAD_RUNTIME.md":
                NAN0S_DOC.replace("Head 0 is reserved for NANNET0",
                                  "Head 255 is a normal head"),
        })
        report = self.verify()
        self.assertIs(report.status, ContractStatus.DRIFT)
        codes = {
            issue["code"]
            for issue in report.providers["nan0s"]["issues"]
        }
        self.assertIn("head0-reservation-mismatch", codes)

    def test_missing_provider_returns_unavailable_with_warning(self) -> None:
        missing = self.base / "missing-nan0s"
        report = self.verify(nan0s=missing)
        self.assertIs(report.status, ContractStatus.UNAVAILABLE)
        self.assertEqual(report.providers["nan0s"]["status"], "unavailable")
        self.assertEqual(report.providers["hermes"]["status"], "available")
        self.assertIn(
            "missing-provider",
            [warning["code"] for warning in report.warnings],
        )
        self.assertFalse(report.as_dict()["live_deployment_claimed"])
        self.assertFalse(report.as_dict()["network_fetch_performed"])

    def test_report_json_is_deterministic_and_path_independent(self) -> None:
        first = self.verify()
        second = self.verify()
        self.assertEqual(first.to_json(), second.to_json())
        decoded = json.loads(first.to_json())
        self.assertEqual(decoded["status"], "available")
        self.assertNotIn(str(self.base), first.to_json())
        self.assertNotIn("timestamp", first.to_json().lower())
        self.assertEqual(
            first.to_json(),
            json.dumps(decoded, sort_keys=True, separators=(",", ":")),
        )


class FetchedOriginMainTests(unittest.TestCase):
    """Integration check when the real sibling checkouts are present."""

    def test_fetched_origin_main_contract_is_available(self) -> None:
        home = Path(__file__).resolve().parents[1].parent
        hermes = Path(os.environ.get("NANLMIND_HERMES_ROOT",
                                     home / "NaNLMind_HERMES"))
        nan0s = Path(os.environ.get("NAN0S_ROOT", home / "nan0s"))
        if not hermes.is_dir() or not nan0s.is_dir():
            self.skipTest("sibling repositories are not available")
        for repository in (hermes, nan0s):
            probe = subprocess.run(
                ["git", "-C", str(repository), "rev-parse", "--verify",
                 "origin/main^{commit}"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ.copy(),
                check=False,
            )
            if probe.returncode != 0:
                self.skipTest("sibling origin/main is not fetched")
        report = verify_contract(hermes_repo=hermes, nan0s_repo=nan0s)
        self.assertIs(report.status, ContractStatus.AVAILABLE, report.to_json())
        self.assertEqual(
            report.providers["hermes"]["constants"]["universe_root"][
                "ROOT_MAGIC"
            ],
            N16ROOT1_MAGIC,
        )
        self.assertEqual(
            report.providers["nan0s"]["constants"]["n16_head_store"][
                "NH_WORDS"
            ],
            NH_WORDS,
        )
        self.assertTrue(report.origin_main_verified)
        self.assertFalse(report.as_dict()["live_deployment_claimed"])


if __name__ == "__main__":
    unittest.main()
