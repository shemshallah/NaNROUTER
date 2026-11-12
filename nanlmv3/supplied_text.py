#!/usr/bin/env python3
"""Extract embedded text from the supplied Python files (no NaN* imports)."""

from __future__ import annotations

import re
from pathlib import Path

DEFAULT_SUPPLIED = [
    Path.home() / "meta" / "transformer_baseline_lm.py",
    Path("/storage/emulated/0/download/Meta Ai/c256_x5f_2_x5f_gutenberg_x5f_specialization_x5f_6gram_x5f_final.py.txt"),
    Path("/storage/emulated/0/download/Meta Ai/mirror.py.txt"),
]

EMBEDDED_RE = re.compile(
    r"(?:EMBEDDED_BIG|EMBEDDED_GUTENBERG|REAL_TEXT)\s*=\s*(?:'''|\"\"\")(.*?)(?:'''|\"\"\")",
    re.DOTALL,
)


def extract_supplied_text(paths: list[Path]) -> str:
    parts: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8", errors="ignore")
        for match in EMBEDDED_RE.finditer(raw):
            text = match.group(1).strip()
            if len(text) > 1000:
                parts.append(text)
    if not parts:
        raise SystemExit(
            "No embedded text found in the supplied Python files. Pass --corpus."
        )
    return "\n\n".join(parts)


__all__ = ["DEFAULT_SUPPLIED", "EMBEDDED_RE", "extract_supplied_text"]
