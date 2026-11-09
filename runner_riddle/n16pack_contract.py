"""Host-only static verifier for the N16PACK/N16SNAP cross-repo contract.

This module reads a small, fixed set of contract files from neighbouring
NaNLMind_HERMES and nan0s checkouts.  It performs *static* parsing only:

* it never imports or executes sibling-repo code;
* it never runs a native guest, opens a chart, or inspects a live service;
* it never fetches, pulls, updates a ref, or writes to another repository;
* it never claims that a deployment, bank, pack, or snapshot is live.

The authoritative source is the already-fetched local ``origin/main`` ref.
A clean worktree file is used when its bytes are identical to that ref; if
the worktree file is dirty or missing, ``git show`` supplies the contract
bytes instead.  This keeps verification reproducible without mutating either
sibling checkout.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "nanrouter.n16pack-contract-verifier/1"
CONTRACT_REF = "origin/main"

N16ROOT1_MAGIC = b"N16ROOT1"
N16PACK1_MAGIC = b"N16PACK1"
N16SNAP1_MAGIC = b"N16SNAP1"

NAN16_WORD_BYTES = 8
BANK_OFFSET = 0x640000
BANK_WORDS = 67838
BANK_HEADS = 255
BANK_FEATURES = 128
NH_WORDS = 67838
BANK_BYTES = BANK_WORDS * NAN16_WORD_BYTES
BANK_END = BANK_OFFSET + BANK_BYTES
BANK_GUEST_WORD_OFFSET = BANK_OFFSET // NAN16_WORD_BYTES
CHART_BYTES = 8 * 1024 * 1024
CHART_MIB = CHART_BYTES // (1024 * 1024)
HEAD0_RESERVED_FOR = "NANNET0"

NAS_HEAD_STRIDE_WORDS = 266
NAS_SLOT_WORDS = 133
NAS_DATA_WORDS = 128

assert BANK_BYTES == 542_704
assert BANK_END == 0x6C47F0
assert BANK_GUEST_WORD_OFFSET == 0xC8000
assert BANK_END <= CHART_BYTES
assert NAS_HEAD_STRIDE_WORDS == 2 * NAS_SLOT_WORDS
assert NAS_SLOT_WORDS == 1 + 4 + NAS_DATA_WORDS
assert NH_WORDS == BANK_WORDS


class ContractStatus(str, Enum):
    """Typed outcome for one provider or for the aggregate report."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DRIFT = "drift"


EXPECTED_CONTRACT: dict[str, Any] = {
    "schema": SCHEMA,
    "contract_ref": CONTRACT_REF,
    "n16root1_magic": N16ROOT1_MAGIC.decode("ascii"),
    "n16pack1_magic": N16PACK1_MAGIC.decode("ascii"),
    "n16snap1_magic": N16SNAP1_MAGIC.decode("ascii"),
    "nan16_word_bytes": NAN16_WORD_BYTES,
    "bank_offset": BANK_OFFSET,
    "bank_offset_hex": hex(BANK_OFFSET),
    "bank_words": BANK_WORDS,
    "bank_heads": BANK_HEADS,
    "bank_features": BANK_FEATURES,
    "nh_words": NH_WORDS,
    "bank_bytes": BANK_BYTES,
    "bank_end_exclusive": BANK_END,
    "bank_end_exclusive_hex": hex(BANK_END),
    "bank_guest_word_offset": BANK_GUEST_WORD_OFFSET,
    "bank_guest_word_offset_hex": hex(BANK_GUEST_WORD_OFFSET),
    "head0_reserved_for": HEAD0_RESERVED_FOR,
    "chart_bytes": CHART_BYTES,
    "chart_mib": CHART_MIB,
    "nas_head_stride_words": NAS_HEAD_STRIDE_WORDS,
    "nas_slot_words": NAS_SLOT_WORDS,
    "nas_data_words": NAS_DATA_WORDS,
    "live_deployment_claimed": False,
}


@dataclass(frozen=True)
class ContractReport:
    """Deterministic, JSON-ready result of a static contract verification."""

    status: ContractStatus
    providers: Mapping[str, Any]
    contract: Mapping[str, Any]
    checks: Sequence[Mapping[str, Any]]
    cross_checks: Sequence[Mapping[str, Any]]
    warnings: Sequence[Mapping[str, Any]]
    origin_main_verified: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "status": self.status.value,
            "contract": _plain(self.contract),
            "providers": _plain(self.providers),
            "checks": _plain(self.checks),
            "cross_checks": _plain(self.cross_checks),
            "warnings": _plain(self.warnings),
            "origin_main_verified": self.origin_main_verified,
            "host_only": True,
            "network_fetch_performed": False,
            "live_deployment_claimed": False,
            "repository_mutated": False,
            "deployment_status": "not-observed",
        }

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]

    def __iter__(self):
        return iter(self.as_dict())

    def __len__(self) -> int:
        return len(self.as_dict())

    def get(self, key: str, default: Any = None) -> Any:
        return self.as_dict().get(key, default)

    def to_json(self) -> str:
        """Canonical JSON: sorted keys, compact separators, no timestamps."""
        return json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":"),
            ensure_ascii=True,
        )


class ContractError(ValueError):
    """A malformed local contract source that cannot be parsed statically."""


@dataclass(frozen=True)
class _FileSpec:
    role: str
    path: str
    kind: str
    required: bool
    expected: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class _ProviderSpec:
    name: str
    repository_label: str
    environment: tuple[str, ...]
    default_directory: str
    files: tuple[_FileSpec, ...]


@dataclass(frozen=True)
class _GitBlob:
    content: bytes | None
    reason: str | None


@dataclass(frozen=True)
class _Source:
    status: ContractStatus
    content: bytes | None
    source: str
    sha256: str | None
    origin_main_verified: bool
    worktree_state: str
    reason: str | None = None


@dataclass(frozen=True)
class _ProviderFacts:
    status: ContractStatus
    report: Mapping[str, Any]
    issues: Sequence[Mapping[str, Any]]
    checks: Sequence[Mapping[str, Any]]
    constants: Mapping[str, Mapping[str, Any]]
    metrics: Mapping[str, Any]
    warnings: Sequence[Mapping[str, Any]]


_PROVIDERS: tuple[_ProviderSpec, ...] = (
    _ProviderSpec(
        name="hermes",
        repository_label="NaNLMind_HERMES",
        environment=("NANLMIND_HERMES_ROOT",),
        default_directory="NaNLMind_HERMES",
        files=(
            _FileSpec(
                "head_bank_transport",
                "nanlmind_hermes/head_bank_transport.py",
                "python",
                True,
                (
                    ("BANK_OFFSET", BANK_OFFSET),
                    ("BANK_WORDS", BANK_WORDS),
                    ("BANK_HEADS", BANK_HEADS),
                    ("BANK_FEATURES", BANK_FEATURES),
                    ("BANK_BYTES", BANK_BYTES),
                    ("BANK_END", BANK_END),
                    ("BANK_GUEST_WORD_OFFSET", BANK_GUEST_WORD_OFFSET),
                ),
            ),
            _FileSpec(
                "universe_root",
                "nanlmind_hermes/universe_root.py",
                "python",
                True,
                (
                    ("ROOT_MAGIC", N16ROOT1_MAGIC),
                    ("ROOT_VERSION", 1),
                ),
            ),
            _FileSpec(
                "universe_chart",
                "nanlmind_hermes/universe_chart.py",
                "python",
                False,
                (("PAGE_BYTES", CHART_BYTES),),
            ),
            _FileSpec(
                "universe_pack",
                "nanlmind_hermes/universe_pack.py",
                "python",
                False,
                (("MAGIC", N16PACK1_MAGIC),),
            ),
            _FileSpec(
                "chart_storage",
                "nanlmind_hermes/chart_storage.py",
                "python",
                False,
                (
                    ("MAGIC", N16SNAP1_MAGIC),
                    ("PAGE_BYTES", CHART_BYTES),
                ),
            ),
        ),
    ),
    _ProviderSpec(
        name="nan0s",
        repository_label="nan0s",
        environment=("NAN0S_ROOT",),
        default_directory="nan0s",
        files=(
            _FileSpec(
                "n16_head_store",
                "src/nannet/n16_head_store.nas",
                "nas",
                True,
                (
                    ("NH_WORDS", NH_WORDS),
                    ("NH_STRIDE", NAS_HEAD_STRIDE_WORDS),
                    ("NH_SLOT", NAS_SLOT_WORDS),
                    ("NH_DATA", NAS_DATA_WORDS),
                ),
            ),
            _FileSpec(
                "runtime_doc",
                "docs/N16_HEAD_RUNTIME.md",
                "text",
                True,
            ),
        ),
    ),
)

_MISSING = object()
_MAX_SOURCE_BYTES = 4 * 1024 * 1024
_REPO_ROOT = Path(__file__).resolve().parents[1]
_GIT_TIMEOUT_SECONDS = 8


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        try:
            return value.decode("ascii")
        except UnicodeDecodeError:
            return value.hex()
    if isinstance(value, Path):
        return value.name
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(item) for item in value]
    return value


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    # Read-only, non-interactive commands only.  GIT_NO_LAZY_FETCH keeps a
    # partial clone from contacting its promisor remote while reading a blob.
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GIT_NO_LAZY_FETCH"] = "1"
    environment.pop("GIT_DIR", None)
    environment.pop("GIT_WORK_TREE", None)
    environment.pop("GIT_INDEX_FILE", None)
    return environment


def _git_output(repository: Path, *arguments: str) -> tuple[int, bytes, str]:
    command = ["git", "-C", os.fspath(repository), *arguments]
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
            env=_git_environment(),
        )
    except (FileNotFoundError, OSError) as exc:
        return 127, b"", type(exc).__name__
    except subprocess.TimeoutExpired:
        return 124, b"", "timeout"
    return completed.returncode, completed.stdout, completed.stderr.decode(
        "utf-8", "replace"
    )


def _git_blob(repository: Path, ref: str, path: str) -> _GitBlob:
    """Read ``ref:path`` from the local object database; never fetch."""
    code, stdout, _stderr = _git_output(repository, "show", f"{ref}:{path}")
    if code != 0:
        return _GitBlob(None, "origin-main-source-unavailable")
    if len(stdout) > _MAX_SOURCE_BYTES:
        return _GitBlob(None, "origin-main-source-too-large")
    return _GitBlob(stdout, None)


def _origin_main_commit(repository: Path, ref: str) -> str | None:
    code, stdout, _stderr = _git_output(
        repository, "rev-parse", "--verify", f"{ref}^{{commit}}"
    )
    if code != 0:
        return None
    commit = stdout.decode("ascii", "strict").strip()
    if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit) is None:
        return None
    return commit


def _worktree_bytes(repository: Path, path: str) -> tuple[bytes | None, str]:
    target = repository / path
    try:
        if target.is_symlink():
            return None, "symlink"
        if not target.is_file():
            return None, "missing"
        if target.stat().st_size > _MAX_SOURCE_BYTES:
            return None, "too-large"
        return target.read_bytes(), "clean"
    except OSError:
        return None, "unreadable"


def _read_source(repository: Path, path: str, ref: str) -> _Source:
    """Prefer a clean worktree; fall back to the pinned ``ref`` blob."""
    origin = _git_blob(repository, ref, path)
    if origin.content is None:
        return _Source(
            ContractStatus.UNAVAILABLE, None, "unavailable", None, False,
            "unknown", origin.reason,
        )
    origin_sha = _sha256(origin.content)
    worktree, state = _worktree_bytes(repository, path)
    if worktree is not None and worktree == origin.content:
        return _Source(
            ContractStatus.AVAILABLE, origin.content, "worktree", origin_sha,
            True, "clean",
        )
    if worktree is not None:
        state = "dirty"
    return _Source(
        ContractStatus.AVAILABLE, origin.content, f"git-show:{ref}", origin_sha,
        True, state,
    )


def _decode_source(source: _Source) -> str:
    if source.content is None:
        raise ContractError("missing contract source")
    try:
        return source.content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("contract source is not UTF-8") from exc


def _eval_ast(node: ast.AST, environment: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return environment.get(node.id, _MISSING)
    if isinstance(node, ast.UnaryOp):
        value = _eval_ast(node.operand, environment)
        if value is _MISSING:
            return _MISSING
        if isinstance(node.op, ast.UAdd):
            return +value
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.Invert):
            return ~value
        if isinstance(node.op, ast.Not):
            return not value
        return _MISSING
    if isinstance(node, ast.BinOp):
        left = _eval_ast(node.left, environment)
        right = _eval_ast(node.right, environment)
        if left is _MISSING or right is _MISSING:
            return _MISSING
        try:
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.LShift):
                return left << right
            if isinstance(node.op, ast.RShift):
                return left >> right
            if isinstance(node.op, ast.BitOr):
                return left | right
            if isinstance(node.op, ast.BitAnd):
                return left & right
        except (ArithmeticError, TypeError, ValueError):
            return _MISSING
    return _MISSING


def parse_python_constants(text: str) -> dict[str, Any]:
    """Parse module-level literal/scalar assignments without executing code."""
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise ContractError("Python contract is not syntactically valid") from exc
    pending: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    pending[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                pending[node.target.id] = node.value
    values: dict[str, Any] = {}
    for _ in range(len(pending) + 1):
        progress = False
        for name, expression in tuple(pending.items()):
            value = _eval_ast(expression, values)
            if value is not _MISSING:
                values[name] = value
                del pending[name]
                progress = True
        if not progress:
            break
    scalar = (str, bytes, bool, int, float, type(None))
    return {name: value for name, value in values.items()
            if isinstance(value, scalar)}


def parse_nas_constants(text: str) -> dict[str, int]:
    """Parse literal ``.equ NAME value`` declarations from NaN16 assembly."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        statement = line.split(";", 1)[0].strip()
        match = re.fullmatch(r"\.equ\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.+)", statement)
        if match is None:
            continue
        name, expression = match.groups()
        try:
            parsed = ast.parse(expression.strip(), mode="eval")
        except SyntaxError as exc:
            raise ContractError(f"invalid .equ expression for {name}") from exc
        value = _eval_ast(parsed.body, values)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ContractError(f"non-integer .equ value for {name}")
        values[name] = value
    return values


def _match(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE | re.MULTILINE) is not None


def _check_record(
    check_id: str,
    provider: str | None,
    path: str | None,
    expected: Any,
    actual: Any,
    passed: bool,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "provider": provider,
        "path": path,
        "status": (
            ContractStatus.AVAILABLE.value if passed
            else ContractStatus.DRIFT.value
        ),
        "expected": _plain(expected),
        "actual": _plain(actual),
    }


def _issue_record(
    code: str,
    provider: str,
    path: str | None,
    message: str,
    expected: Any = None,
    actual: Any = None,
) -> dict[str, Any]:
    issue = {
        "code": code,
        "provider": provider,
        "path": path,
        "message": message,
    }
    if expected is not None:
        issue["expected"] = _plain(expected)
    if actual is not None:
        issue["actual"] = _plain(actual)
    return issue


def _compare_constants(
    provider: str,
    role: str,
    constants: Mapping[str, Any],
    expected: Iterable[tuple[str, Any]],
    checks: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    for name, wanted in expected:
        check_id = f"{provider}.{role}.{name}"
        if name not in constants:
            checks.append(_check_record(
                check_id, provider, role, wanted, "<missing>", False,
            ))
            issues.append(_issue_record(
                "constant-missing", provider, role,
                f"{name} is absent from the contract source", wanted,
                "<missing>",
            ))
            continue
        actual = constants[name]
        passed = type(actual) is type(wanted) and actual == wanted
        checks.append(_check_record(
            check_id, provider, role, wanted, actual, passed,
        ))
        if not passed:
            issues.append(_issue_record(
                "constant-mismatch", provider, role,
                f"{name} does not match the frozen cross-repo contract",
                wanted, actual,
            ))


def _missing_document(path: str, required: bool) -> dict[str, Any]:
    return {
        "path": path,
        "required": required,
        "status": ContractStatus.UNAVAILABLE.value,
        "source": "unavailable",
        "sha256": None,
        "worktree_state": "unknown",
    }


def _provider_facts(
    spec: _ProviderSpec,
    repository: Path | None,
    ref: str,
) -> _ProviderFacts:
    warnings: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    constants: dict[str, dict[str, Any]] = {}
    metrics: dict[str, Any] = {}
    documents: dict[str, dict[str, Any]] = {}
    provider_unavailable = False
    provider_drift = False

    if repository is None or not repository.is_dir():
        provider_unavailable = True
        warnings.append({
            "code": "missing-provider",
            "provider": spec.name,
            "message": "provider repository is unavailable; contract cannot be verified",
        })
        for file_spec in spec.files:
            documents[file_spec.role] = _missing_document(
                file_spec.path, file_spec.required
            )
        return _ProviderFacts(
            ContractStatus.UNAVAILABLE,
            {
                "status": ContractStatus.UNAVAILABLE.value,
                "repository": spec.repository_label,
                "origin_main_commit": None,
                "origin_main_verified": False,
                "documents": documents,
                "constants": {},
                "issues": [],
                "checks": [],
            },
            (), (), {}, {}, tuple(warnings),
        )

    origin_main_commit = _origin_main_commit(repository, ref)
    texts: dict[str, str] = {}

    for file_spec in spec.files:
        source = _read_source(repository, file_spec.path, ref)
        document = {
            "path": file_spec.path,
            "required": file_spec.required,
            "status": source.status.value,
            "source": source.source,
            "sha256": source.sha256,
            "worktree_state": source.worktree_state,
        }
        if source.content is None:
            document["reason"] = source.reason or "source-unavailable"
            documents[file_spec.role] = document
            warning_code = (
                "missing-contract-source" if file_spec.required
                else "optional-source-unavailable"
            )
            warnings.append({
                "code": warning_code,
                "provider": spec.name,
                "path": file_spec.path,
                "message": (
                    "required contract source is unavailable"
                    if file_spec.required
                    else "optional contract source is unavailable"
                ),
            })
            if file_spec.required:
                provider_unavailable = True
            continue

        try:
            text = _decode_source(source)
        except ContractError:
            document["status"] = ContractStatus.UNAVAILABLE.value
            document["reason"] = "source-not-utf8"
            documents[file_spec.role] = document
            warnings.append({
                "code": "unparsable-contract-source",
                "provider": spec.name,
                "path": file_spec.path,
                "message": "contract source is not valid UTF-8",
            })
            provider_unavailable = True
            continue

        try:
            if file_spec.kind == "python":
                parsed = parse_python_constants(text)
            elif file_spec.kind == "nas":
                parsed = parse_nas_constants(text)
            elif file_spec.kind == "text":
                parsed = {}
            else:  # pragma: no cover - fixed internal specification
                raise ContractError("unknown contract parser")
        except ContractError as exc:
            document["status"] = ContractStatus.UNAVAILABLE.value
            document["reason"] = "unparsable-source"
            documents[file_spec.role] = document
            warnings.append({
                "code": "unparsable-contract-source",
                "provider": spec.name,
                "path": file_spec.path,
                "message": str(exc),
            })
            provider_unavailable = True
            continue

        documents[file_spec.role] = document
        constants[file_spec.role] = parsed
        texts[file_spec.role] = text
        if file_spec.expected:
            before = len(issues)
            _compare_constants(
                spec.name, file_spec.role, parsed, file_spec.expected,
                checks, issues,
            )
            if len(issues) != before:
                provider_drift = True

    if spec.name == "hermes":
        transport = constants.get("head_bank_transport", {})
        offset = transport.get("BANK_OFFSET", _MISSING)
        words = transport.get("BANK_WORDS", _MISSING)
        byte_count = transport.get("BANK_BYTES", _MISSING)
        bank_end = transport.get("BANK_END", _MISSING)
        guest_word_offset = transport.get("BANK_GUEST_WORD_OFFSET", _MISSING)
        geometry_ok = (
            isinstance(offset, int) and isinstance(words, int)
            and isinstance(byte_count, int) and isinstance(bank_end, int)
            and isinstance(guest_word_offset, int)
            and offset == BANK_OFFSET
            and words == BANK_WORDS
            and byte_count == words * NAN16_WORD_BYTES
            and bank_end == offset + byte_count
            and bank_end <= CHART_BYTES
            and offset % NAN16_WORD_BYTES == 0
            and guest_word_offset == offset // NAN16_WORD_BYTES
        )
        chart_page = constants.get("universe_chart", {}).get("PAGE_BYTES", _MISSING)
        page_known = chart_page is not _MISSING
        page_ok = (not page_known) or chart_page == CHART_BYTES
        text_8mib = any(
            _match(r"\b8\s*MiB\b", texts.get(role, ""))
            for role in ("head_bank_transport", "universe_root")
        )
        chart_evidence = geometry_ok and page_ok and (page_known or text_8mib)
        checks.append(_check_record(
            "hermes.chart-geometry", "hermes", "head_bank_transport",
            {
                "chart_bytes": CHART_BYTES,
                "bank_offset": BANK_OFFSET,
                "bank_words": BANK_WORDS,
                "bank_end_exclusive": BANK_END,
                "bank_guest_word_offset": BANK_GUEST_WORD_OFFSET,
            },
            {
                "chart_page_bytes": None if chart_page is _MISSING else chart_page,
                "bank_offset": None if offset is _MISSING else offset,
                "bank_words": None if words is _MISSING else words,
                "bank_bytes": None if byte_count is _MISSING else byte_count,
                "bank_end_exclusive": None if bank_end is _MISSING else bank_end,
                "bank_guest_word_offset": (
                    None if guest_word_offset is _MISSING else guest_word_offset
                ),
                "source_text_mentions_8_mib": text_8mib,
            },
            chart_evidence,
        ))
        if not chart_evidence:
            provider_drift = True
            issues.append(_issue_record(
                "chart-geometry-mismatch", "hermes", "head_bank_transport",
                "native bank does not fit the documented 8 MiB chart geometry",
            ))
        metrics["chart_page_bytes"] = (
            None if chart_page is _MISSING else chart_page
        )

    if spec.name == "nan0s":
        nas_text = texts.get("n16_head_store", "")
        doc_text = texts.get("runtime_doc", "")
        declared_match = re.search(
            r"\b(\d+)\s+logical\s+heads\b", nas_text, re.IGNORECASE
        )
        declared_heads = int(declared_match.group(1)) if declared_match else None
        heads_ok = declared_heads == BANK_HEADS
        checks.append(_check_record(
            "nan0s.head-count", "nan0s", "n16_head_store",
            BANK_HEADS, declared_heads, heads_ok,
        ))
        if not heads_ok:
            provider_drift = True
            issues.append(_issue_record(
                "head-count-mismatch", "nan0s", "n16_head_store",
                "head-store declaration does not match 255 logical heads",
                BANK_HEADS, declared_heads,
            ))
        metrics["declared_heads"] = declared_heads

        head_range_ok = _match(r"head\(1\.\.255\)", nas_text)
        doc_reserved = _match(
            r"head\s+0\s+is\s+reserved\s+for\s+NANNET0", doc_text
        )
        reservation_ok = head_range_ok and doc_reserved
        checks.append(_check_record(
            "nan0s.head0-reservation", "nan0s", "runtime_doc",
            {
                "head0_reserved_for": HEAD0_RESERVED_FOR,
                "native_head_range": "1..255",
            },
            {
                "runtime_doc_states_head0_reserved": doc_reserved,
                "head_store_abi_1_to_255": head_range_ok,
            },
            reservation_ok,
        ))
        if not reservation_ok:
            provider_drift = True
            issues.append(_issue_record(
                "head0-reservation-mismatch", "nan0s", "runtime_doc",
                "head 0 must remain reserved for NANNET0 and native heads are 1..255",
            ))

        doc_8mib = _match(r"\b8\s*MiB\b", doc_text)
        doc_nh_words = _match(r"\bNH_WORDS\s*=\s*67838\b", doc_text)
        doc_bank_bytes = _match(r"\b542,?704\b", doc_text)
        doc_words = _match(r"\b67,?838\b", doc_text)
        documented_geometry = (
            doc_8mib and doc_nh_words and doc_bank_bytes and doc_words
        )
        checks.append(_check_record(
            "nan0s.documented-geometry", "nan0s", "runtime_doc",
            {
                "chart_mib": CHART_MIB,
                "bank_words": BANK_WORDS,
                "bank_bytes": BANK_BYTES,
            },
            {
                "mentions_8_mib": doc_8mib,
                "mentions_nh_words": doc_nh_words,
                "mentions_bank_bytes": doc_bank_bytes,
                "mentions_bank_words": doc_words,
            },
            documented_geometry,
        ))
        if not documented_geometry:
            provider_drift = True
            issues.append(_issue_record(
                "documented-geometry-mismatch", "nan0s", "runtime_doc",
                "runtime document does not state the frozen 8 MiB / 67,838-word geometry",
            ))
        metrics["documented_geometry"] = documented_geometry

    if provider_drift:
        status = ContractStatus.DRIFT
    elif provider_unavailable:
        status = ContractStatus.UNAVAILABLE
    else:
        status = ContractStatus.AVAILABLE

    required_documents = [
        document for document in documents.values()
        if document["required"]
    ]
    origin_main_verified = (
        origin_main_commit is not None
        and bool(required_documents)
        and all(
            document.get("status") == ContractStatus.AVAILABLE.value
            and document.get("source", "").startswith(
                ("worktree", "git-show:")
            )
            for document in required_documents
        )
    )

    report = {
        "status": status.value,
        "repository": spec.repository_label,
        "origin_main_commit": origin_main_commit,
        "origin_main_verified": origin_main_verified,
        "documents": documents,
        "constants": constants,
        "issues": issues,
        "checks": checks,
    }
    return _ProviderFacts(
        status, report, tuple(issues), tuple(checks), constants, metrics,
        tuple(warnings),
    )


def _cross_check(
    check_id: str,
    expected: Any,
    actual: Any,
    available: bool,
    passed: bool,
    message: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    record = _check_record(check_id, None, None, expected, actual, passed)
    if not available:
        record["status"] = ContractStatus.UNAVAILABLE.value
        return record, None
    issue = None
    if not passed:
        issue = _issue_record(
            "cross-repo-contract-mismatch", "cross-repo", None, message,
            expected, actual,
        )
    return record, issue


def _resolve_repository(
    spec: _ProviderSpec,
    explicit: str | Path | None,
    repositories: Mapping[str, str | Path] | None,
    repo_root: Path,
) -> Path | None:
    if explicit is not None:
        return Path(explicit).expanduser()
    if repositories is not None:
        candidate = repositories.get(spec.name)
        if candidate is not None:
            return Path(candidate).expanduser()
    for variable in spec.environment:
        value = os.environ.get(variable)
        if value:
            return Path(value).expanduser()
    nested = repo_root / spec.default_directory
    if nested.is_dir():
        return nested
    return repo_root.parent / spec.default_directory


def _sorted_warnings(
    warnings: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        (dict(warning) for warning in warnings),
        key=lambda warning: (
            warning.get("code", ""),
            warning.get("provider", ""),
            warning.get("path", ""),
            json.dumps(_plain(warning), sort_keys=True),
        ),
    )


def verify_contract(
    *,
    hermes_repo: str | Path | None = None,
    nan0s_repo: str | Path | None = None,
    repositories: Mapping[str, str | Path] | None = None,
    repo_root: str | Path | None = None,
    ref: str = CONTRACT_REF,
) -> ContractReport:
    """Verify the fixed cross-repo contract without network or live access.

    Resolution order for each provider is an explicit path, a repositories
    mapping, its environment variable (``NANLMIND_HERMES_ROOT`` or
    ``NAN0S_ROOT``), then the sibling directory next to this checkout.
    """
    if type(ref) is not str or not ref or ref.startswith("-"):
        raise ContractError("invalid contract ref")
    root = Path(repo_root).expanduser() if repo_root is not None else _REPO_ROOT
    facts: dict[str, _ProviderFacts] = {}
    facts["hermes"] = _provider_facts(
        _PROVIDERS[0],
        _resolve_repository(_PROVIDERS[0], hermes_repo, repositories, root),
        ref,
    )
    facts["nan0s"] = _provider_facts(
        _PROVIDERS[1],
        _resolve_repository(_PROVIDERS[1], nan0s_repo, repositories, root),
        ref,
    )

    checks: list[dict[str, Any]] = []
    cross_checks: list[dict[str, Any]] = []
    cross_issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for facts_item in facts.values():
        checks.extend(facts_item.checks)
        warnings.extend(facts_item.warnings)

    hermes_constants = facts["hermes"].constants
    nan0s_constants = facts["nan0s"].constants
    transport = hermes_constants.get("head_bank_transport", {})
    nas = nan0s_constants.get("n16_head_store", {})

    hermes_words = transport.get("BANK_WORDS", _MISSING)
    hermes_bytes = transport.get("BANK_BYTES", _MISSING)
    hermes_heads = transport.get("BANK_HEADS", _MISSING)
    nas_words = nas.get("NH_WORDS", _MISSING)
    nas_declared_heads = facts["nan0s"].metrics.get("declared_heads", _MISSING)

    words_available = (
        hermes_words is not _MISSING and nas_words is not _MISSING
    )
    words_record, words_issue = _cross_check(
        "cross-repo.bank-words",
        None if hermes_words is _MISSING else hermes_words,
        None if nas_words is _MISSING else nas_words,
        words_available,
        words_available and hermes_words == nas_words,
        "HERMES BANK_WORDS and NaN0S NH_WORDS differ",
    )
    cross_checks.append(words_record)
    if words_issue is not None:
        cross_issues.append(words_issue)

    bytes_available = (
        isinstance(hermes_bytes, int) and isinstance(nas_words, int)
    )
    expected_bytes = (
        nas_words * NAN16_WORD_BYTES if isinstance(nas_words, int) else None
    )
    bytes_record, bytes_issue = _cross_check(
        "cross-repo.bank-bytes",
        expected_bytes,
        None if hermes_bytes is _MISSING else hermes_bytes,
        bytes_available,
        bytes_available and hermes_bytes == expected_bytes,
        "HERMES BANK_BYTES disagrees with NaN0S NH_WORDS * 8",
    )
    cross_checks.append(bytes_record)
    if bytes_issue is not None:
        cross_issues.append(bytes_issue)

    heads_available = (
        isinstance(hermes_heads, int) and isinstance(nas_declared_heads, int)
    )
    heads_record, heads_issue = _cross_check(
        "cross-repo.bank-heads",
        None if hermes_heads is _MISSING else hermes_heads,
        None if nas_declared_heads is _MISSING else nas_declared_heads,
        heads_available,
        heads_available and hermes_heads == nas_declared_heads,
        "HERMES BANK_HEADS and NaN0S logical-head declaration differ",
    )
    cross_checks.append(heads_record)
    if heads_issue is not None:
        cross_issues.append(heads_issue)

    provider_statuses = [facts_item.status for facts_item in facts.values()]
    if any(status is ContractStatus.DRIFT for status in provider_statuses):
        status = ContractStatus.DRIFT
    elif any(status is ContractStatus.UNAVAILABLE for status in provider_statuses):
        status = ContractStatus.UNAVAILABLE
    elif cross_issues:
        status = ContractStatus.DRIFT
    else:
        status = ContractStatus.AVAILABLE

    # Provider-local issues are already nested in each provider report.
    # Cross-repo issues are summarised by the failing cross-check itself.

    contract = dict(EXPECTED_CONTRACT)
    contract["cross_repo_bank_words"] = (
        None if hermes_words is _MISSING else hermes_words
    )
    contract["cross_repo_nh_words"] = (
        None if nas_words is _MISSING else nas_words
    )

    origin_main_verified = all(
        facts_item.report.get("origin_main_verified") is True
        for facts_item in facts.values()
    )

    return ContractReport(
        status=status,
        providers={name: item.report for name, item in facts.items()},
        contract=contract,
        checks=tuple(checks),
        cross_checks=tuple(cross_checks),
        warnings=tuple(_sorted_warnings(warnings)),
        origin_main_verified=origin_main_verified,
    )


def report_json(report: ContractReport | Mapping[str, Any]) -> str:
    """Return canonical JSON for a report object or mapping."""
    if isinstance(report, ContractReport):
        return report.to_json()
    return json.dumps(
        _plain(report), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True,
    )


# Convenient explicit alias for callers that name the artifact.
verify_n16pack_contract = verify_contract


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Statically verify the N16PACK/N16SNAP origin/main contract",
    )
    parser.add_argument("--hermes-repo", default=None)
    parser.add_argument("--nan0s-repo", default=None)
    parser.add_argument("--ref", default=CONTRACT_REF)
    arguments = parser.parse_args(argv)
    try:
        report = verify_contract(
            hermes_repo=arguments.hermes_repo,
            nan0s_repo=arguments.nan0s_repo,
            ref=arguments.ref,
        )
    except ContractError as exc:
        sys.stderr.write(f"n16pack contract error: {exc}\n")
        return 1
    sys.stdout.write(report.to_json() + "\n")
    if report.status is ContractStatus.AVAILABLE:
        return 0
    if report.status is ContractStatus.UNAVAILABLE:
        return 1
    return 2


__all__ = [
    "BANK_BYTES",
    "BANK_END",
    "BANK_FEATURES",
    "BANK_GUEST_WORD_OFFSET",
    "BANK_HEADS",
    "BANK_OFFSET",
    "BANK_WORDS",
    "CHART_BYTES",
    "CHART_MIB",
    "CONTRACT_REF",
    "ContractError",
    "ContractReport",
    "ContractStatus",
    "EXPECTED_CONTRACT",
    "HEAD0_RESERVED_FOR",
    "N16PACK1_MAGIC",
    "N16ROOT1_MAGIC",
    "N16SNAP1_MAGIC",
    "NAN16_WORD_BYTES",
    "NAS_DATA_WORDS",
    "NAS_HEAD_STRIDE_WORDS",
    "NAS_SLOT_WORDS",
    "NH_WORDS",
    "SCHEMA",
    "parse_nas_constants",
    "parse_python_constants",
    "report_json",
    "verify_contract",
    "verify_n16pack_contract",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
