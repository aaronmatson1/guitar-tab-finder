"""Hand-built search links.

This source needs no network and never fails, so there is always something to
show when the live sources are unreachable or come up empty.
"""

from __future__ import annotations

from typing import List
from urllib.parse import quote_plus

from .base import DEFAULT_TIMEOUT, TabResult, TabSource

SITES = [
    ("Ultimate Guitar", "https://www.ultimate-guitar.com/search.php?search_type=title&value={q}"),
    ("Songsterr", "https://www.songsterr.com/?pattern={q}"),
    ("Chordify", "https://chordify.net/search/{q}"),
    ("GuitarTabs.cc", "https://www.guitartabs.cc/search.php?q={q}"),
    ("YouTube lessons", "https://www.youtube.com/results?search_query={q}+guitar+lesson"),
]


class SearchLinksSource(TabSource):
    """Offline fallback: links to run the search yourself."""

    name = "links"

    def search(self, query: str, limit: int = 10, timeout: float = DEFAULT_TIMEOUT) -> List[TabResult]:
        encoded = quote_plus(query)
        return [
            TabResult(
                title=query,
                artist="search",
                url=template.format(q=encoded),
                source=site,
                kind="search link",
            )
            for site, template in SITES[:limit]
        ]
