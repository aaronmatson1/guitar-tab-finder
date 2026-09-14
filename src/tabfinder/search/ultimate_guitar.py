"""Search Ultimate Guitar.

Ultimate Guitar has no public API. Its search page embeds the result list as
JSON inside a ``div.js-store`` element, which is what this reads. Only the
result listing is read — titles, ratings and links — never the tab bodies,
which stay on their site. If the page layout changes, this source degrades to
returning nothing rather than breaking the whole search.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any, List, Optional

from .base import DEFAULT_TIMEOUT, TabResult, TabSource

SEARCH_URL = "https://www.ultimate-guitar.com/search.php"

# UG serves its result list to a JS front end via this data attribute.
_STORE_RE = re.compile(r'<div[^>]+class="js-store"[^>]+data-content="([^"]*)"', re.I)

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

#: UG labels each result with a type; these are the ones worth showing.
USEFUL_TYPES = {"Tab", "Chords", "Guitar Pro", "Bass Tabs", "Ukulele Chords", "Power"}


class UltimateGuitarSource(TabSource):
    """The biggest tab archive, and usually the first place to look."""

    name = "ultimate-guitar"

    def search(self, query: str, limit: int = 10, timeout: float = DEFAULT_TIMEOUT) -> List[TabResult]:
        import requests

        response = requests.get(
            SEARCH_URL,
            params={"search_type": "title", "value": query},
            headers={"User-Agent": BROWSER_UA, "Accept": "text/html"},
            timeout=timeout,
        )
        response.raise_for_status()
        return parse_ultimate_guitar(response.text, limit=limit)


def parse_ultimate_guitar(page: str, limit: int = 10) -> List[TabResult]:
    """Pull the result list out of a search page's embedded JSON."""
    match = _STORE_RE.search(page)
    if not match:
        return []
    try:
        store = json.loads(html.unescape(match.group(1)))
    except (ValueError, TypeError):
        return []

    entries = _find_results(store)
    out: List[TabResult] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        url = entry.get("tab_url") or entry.get("url")
        title = entry.get("song_name") or entry.get("name")
        if not url or not title:
            continue
        kind = str(entry.get("type") or "Tab")
        if USEFUL_TYPES and kind not in USEFUL_TYPES:
            continue
        out.append(
            TabResult(
                title=str(title),
                artist=str(entry.get("artist_name") or "unknown"),
                url=str(url),
                source="Ultimate Guitar",
                kind=kind.lower(),
                rating=_as_float(entry.get("rating")),
                votes=_as_int(entry.get("votes")),
                version=_as_int(entry.get("version")),
            )
        )
        if len(out) >= limit:
            break
    return out


def _find_results(store: Any) -> List[Any]:
    """Locate the results array, wherever UG has moved it to this month."""
    # The documented-by-observation path first, then a general search.
    try:
        data = store["store"]["page"]["data"]
        for key in ("results", "other_tabs", "tabs"):
            if isinstance(data.get(key), list):
                return data[key]
    except (KeyError, TypeError):
        pass

    found: List[Any] = []

    def walk(node: Any, depth: int = 0) -> None:
        if found or depth > 8:
            return
        if isinstance(node, list):
            if node and isinstance(node[0], dict) and "tab_url" in node[0]:
                found.extend(node)
                return
            for item in node:
                walk(item, depth + 1)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value, depth + 1)

    walk(store)
    return found


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
