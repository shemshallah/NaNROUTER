"""Guest-budget profiles for the NaN16 runtime.

Guest accounting is in 8-byte NaN16 words.  The default is the 2 MiB profile;
the legacy 1 MiB profile remains selectable for compatibility.  This module is
control-plane arithmetic only: it does not allocate memory or execute code.
"""
from __future__ import annotations

from dataclasses import dataclass

WORD_BYTES = 8
PAGE_BYTES = 32 * 1024
LEGACY_GUEST_BUDGET_BYTES = 1024 * 1024
DEFAULT_GUEST_BUDGET_BYTES = 2 * 1024 * 1024
DEFAULT_GUEST_BUDGET_WORDS = DEFAULT_GUEST_BUDGET_BYTES // WORD_BYTES
DEFAULT_GUEST_BUDGET_PAGES = DEFAULT_GUEST_BUDGET_BYTES // PAGE_BYTES
LEGACY_GUEST_BUDGET_WORDS = LEGACY_GUEST_BUDGET_BYTES // WORD_BYTES
LEGACY_GUEST_BUDGET_PAGES = LEGACY_GUEST_BUDGET_BYTES // PAGE_BYTES


@dataclass(frozen=True)
class GuestBudget:
    """One declarative guest budget, in words and derived pages."""

    name: str
    bytes: int
    words: int
    pages: int
    word_bytes: int = WORD_BYTES
    page_bytes: int = PAGE_BYTES
    glt_enforced: bool = False
    adjustable: bool = True

    def validate(self) -> None:
        if not self.name:
            raise ValueError("budget name must be non-empty")
        if self.word_bytes != WORD_BYTES or self.page_bytes != PAGE_BYTES:
            raise ValueError("only 8-byte words and 32 KiB pages are supported")
        if self.words < 1 or self.bytes != self.words * self.word_bytes:
            raise ValueError("budget words/bytes are inconsistent")
        expected_pages = (self.bytes + self.page_bytes - 1) // self.page_bytes
        if self.pages != expected_pages:
            raise ValueError("budget page count must use ceil(bytes/page_bytes)")

    @property
    def slack_words(self) -> int:
        return self.pages * (self.page_bytes // self.word_bytes) - self.words

    def to_dict(self) -> dict:
        self.validate()
        return {
            "schema": "nanrouter.guest-budget.v1",
            "name": self.name,
            "bytes": self.bytes,
            "words": self.words,
            "pages": self.pages,
            "word_bytes": self.word_bytes,
            "page_bytes": self.page_bytes,
            "slack_words": self.slack_words,
            "glt_enforced": self.glt_enforced,
            "adjustable": self.adjustable,
        }


STANDARD_2MIB = GuestBudget(
    name="standard-2mib",
    bytes=DEFAULT_GUEST_BUDGET_BYTES,
    words=DEFAULT_GUEST_BUDGET_WORDS,
    pages=DEFAULT_GUEST_BUDGET_PAGES,
)
LEGACY_1MIB = GuestBudget(
    name="legacy-1mib",
    bytes=LEGACY_GUEST_BUDGET_BYTES,
    words=LEGACY_GUEST_BUDGET_WORDS,
    pages=LEGACY_GUEST_BUDGET_PAGES,
)
DEFAULT_BUDGET = STANDARD_2MIB
PROFILES = {profile.name: profile for profile in (STANDARD_2MIB, LEGACY_1MIB)}


def from_words(words: int, *, name: str = "custom", glt_enforced: bool = False) -> GuestBudget:
    """Build a validated custom budget from guest words."""
    if isinstance(words, bool) or not isinstance(words, int) or words < 1:
        raise ValueError("guest words must be a positive integer")
    size = words * WORD_BYTES
    return GuestBudget(
        name=name,
        bytes=size,
        words=words,
        pages=(size + PAGE_BYTES - 1) // PAGE_BYTES,
        glt_enforced=glt_enforced,
    )


def from_bytes(size: int, *, name: str = "custom", glt_enforced: bool = False) -> GuestBudget:
    if isinstance(size, bool) or not isinstance(size, int) or size < WORD_BYTES:
        raise ValueError("guest bytes must be at least one word")
    if size % WORD_BYTES:
        raise ValueError("guest bytes must be a multiple of 8")
    return from_words(size // WORD_BYTES, name=name, glt_enforced=glt_enforced)


def effective_words(
    *,
    requested_words: int | None = None,
    requested_bytes: int | None = None,
    profile: GuestBudget = DEFAULT_BUDGET,
    runner_ceiling_bytes: int | None = None,
) -> int:
    """Resolve the effective guest words; bytes and words must not disagree."""
    if requested_words is not None and requested_bytes is not None:
        if requested_words * WORD_BYTES != requested_bytes:
            raise ValueError("requested words and bytes disagree")
    if requested_words is None and requested_bytes is not None:
        if requested_bytes % WORD_BYTES:
            raise ValueError("requested bytes must be a multiple of 8")
        requested_words = requested_bytes // WORD_BYTES
    if requested_words is None:
        requested_words = profile.words
    if requested_words < 1:
        raise ValueError("effective guest words must be positive")
    ceiling = profile.words
    if runner_ceiling_bytes is not None:
        ceiling = min(ceiling, runner_ceiling_bytes // WORD_BYTES)
    return min(requested_words, ceiling)


__all__ = [
    "DEFAULT_BUDGET",
    "DEFAULT_GUEST_BUDGET_BYTES",
    "DEFAULT_GUEST_BUDGET_PAGES",
    "DEFAULT_GUEST_BUDGET_WORDS",
    "GuestBudget",
    "LEGACY_1MIB",
    "LEGACY_GUEST_BUDGET_BYTES",
    "LEGACY_GUEST_BUDGET_PAGES",
    "LEGACY_GUEST_BUDGET_WORDS",
    "PAGE_BYTES",
    "PROFILES",
    "STANDARD_2MIB",
    "WORD_BYTES",
    "effective_words",
    "from_bytes",
    "from_words",
]
