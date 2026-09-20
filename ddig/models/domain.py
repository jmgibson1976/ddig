"""
Core Domain dataclass — canonical representation of a domain record
across all sources.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import time
import zoneinfo


@dataclass
class Domain:
    """Represents a single expired or expiring domain."""

    # Core identity
    name: str                           # e.g. "example"
    tld: str                            # e.g. "com"
    fqdn: str                           # e.g. "example.com"

    # Dates
    expiry_date:      Optional[datetime] = None
    drop_date:        Optional[datetime] = None
    fetched_at:       datetime           = field(default_factory=lambda: datetime.now(timezone.utc))

    # Metadata
    source:           str                = ""
    registrar:        Optional[str]      = None
    backlinks:        int | None         = None
    rank:             int | None         = None   # GlobalRank (lower = better, 1 = most linked)

    # NLP scoring (populated later)
    nlp_score:         float | None = None
    composite_score:   float | None = None   # 50% nlp + 30% backlinks + 20% rank
    is_real_word:     Optional[bool]     = None
    word_frequency:   Optional[float]    = None
    is_pronounceable: Optional[bool]     = None

    # Tags e.g. ["english-word", "short", "no-hyphens"]
    tags: list[str] = field(default_factory=list)

    # Raw source row — kept for debugging / re-parsing
    raw: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Derived helpers                                                      #
    # ------------------------------------------------------------------ #

    @property
    def length(self) -> int:
        return len(self.name)

    @property
    def has_hyphen(self) -> bool:
        return "-" in self.name

    @property
    def has_numbers(self) -> bool:
        return any(c.isdigit() for c in self.name)

    @property
    def days_until_drop(self) -> Optional[int]:
        if self.drop_date is None:
            return None
        delta = self.drop_date - datetime.now(timezone.utc)
        return delta.days

    def __str__(self) -> str:
        return self.fqdn

    def __repr__(self) -> str:
        return (
            f"Domain(fqdn={self.fqdn!r}, "
            f"drop={self.drop_date}, "
            f"nlp_score={self.nlp_score})"
        )