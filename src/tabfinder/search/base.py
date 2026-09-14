"""Shared types for tab search.

The search sources look up *where* a tab lives and link to it. They do not
copy tab content out of the sites that host it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Sequence

USER_AGENT = (
    "guitar-tab-finder/0.1 (+https://github.com/aaronmatson1/guitar-tab-finder)"
)
DEFAULT_TIMEOUT = 8.0


@dataclass
class TabResult:
    """One tab someone has already published."""

    title: str
    artist: str
    url: str
    source: str
    kind: str = "tab"
    rating: Optional[float] = None
    votes: Optional[int] = None
    version: Optional[int] = None

    def relevance(self, query: str) -> float:
        """How well this result matches what was asked for, 0-1."""
        target = f"{self.artist} {self.title}".lower()
        query_text = query.lower()
        best = SequenceMatcher(None, query_text, target).ratio()
        # Also try matching against the title alone, for "artist - title" input.
        best = max(best, SequenceMatcher(None, query_text, self.title.lower()).ratio())
        for token in _tokens(query_text):
            if token in target:
                best += 0.05
        return min(1.0, best)

    def quality(self) -> float:
        """A rough ranking signal from the host site's own ratings."""
        if self.rating is None:
            return 0.0
        votes = self.votes or 0
        # A 5-star tab with three votes should not outrank a 4.8 with a thousand.
        return float(self.rating) * min(1.0, votes / 50.0)

    def describe(self) -> str:
        bits = [f"{self.artist} - {self.title}"]
        detail = [self.kind]
        if self.version:
            detail.append(f"v{self.version}")
        if self.rating is not None:
            stars = f"{self.rating:.1f}"
            detail.append(f"{stars}★" + (f" ({self.votes})" if self.votes else ""))
        bits.append("[" + ", ".join(detail) + "]")
        return " ".join(bits)


@dataclass
class SearchOutcome:
    """Everything a search turned up, plus whatever went wrong."""

    results: List[TabResult] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)

    @property
    def found(self) -> bool:
        return bool(self.results)

    def ranked(self, query: str, limit: int = 10) -> List[TabResult]:
        """Best matches first, blending name similarity with site ratings."""
        scored = sorted(
            self.results,
            key=lambda r: -(r.relevance(query) * 3.0 + r.quality() * 0.4),
        )
        seen = set()
        out = []
        for result in scored:
            if result.url in seen:
                continue
            seen.add(result.url)
            out.append(result)
            if len(out) >= limit:
                break
        return out


def _tokens(text: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) > 2]


def split_query(query: str) -> Sequence[str]:
    """Split ``"Artist - Title"`` into its parts, if it is written that way."""
    for separator in (" - ", " – ", " by ", " -- "):
        if separator in query:
            left, right = query.split(separator, 1)
            return (left.strip(), right.strip())
    return (query.strip(),)


class TabSource:
    """A place to look for tabs."""

    name = "source"

    def search(self, query: str, limit: int = 10, timeout: float = DEFAULT_TIMEOUT) -> List[TabResult]:
        raise NotImplementedError
