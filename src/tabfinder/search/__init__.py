"""Finding tabs other people have already written."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Sequence

from .base import DEFAULT_TIMEOUT, SearchOutcome, TabResult, TabSource, split_query
from .links import SearchLinksSource
from .songsterr import SongsterrSource
from .ultimate_guitar import UltimateGuitarSource

#: Live sources, tried in parallel.
SOURCES: Dict[str, TabSource] = {
    "ultimate-guitar": UltimateGuitarSource(),
    "songsterr": SongsterrSource(),
}

__all__ = [
    "SearchOutcome",
    "TabResult",
    "TabSource",
    "SOURCES",
    "search_tabs",
    "search_links",
    "split_query",
]


def search_tabs(
    query: str,
    sources: Optional[Sequence[str]] = None,
    limit: int = 10,
    timeout: float = DEFAULT_TIMEOUT,
) -> SearchOutcome:
    """Look for published tabs across every source at once.

    A source that is unreachable or has changed its page layout is recorded in
    ``outcome.errors`` and the rest of the search carries on.
    """
    # An explicit empty list means 'no sources'; only None means 'all of them'.
    names = list(SOURCES) if sources is None else list(sources)
    unknown = [n for n in names if n not in SOURCES]
    if unknown:
        raise ValueError(f"unknown source(s): {', '.join(unknown)}")

    outcome = SearchOutcome()
    if not names:
        return outcome

    def run(name: str):
        return name, SOURCES[name].search(query, limit=limit, timeout=timeout)

    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        futures = [pool.submit(run, name) for name in names]
        for future in futures:
            try:
                name, results = future.result()
                outcome.results.extend(results)
            except Exception as exc:  # noqa: BLE001 - one source must not sink the rest
                outcome.errors[_blame(exc, names)] = f"{type(exc).__name__}: {exc}"
    return outcome


def _blame(exc: Exception, names: Sequence[str]) -> str:
    """Best-effort attribution of a failure to a source name."""
    text = str(exc).lower()
    for name in names:
        host = name.replace("-", "")
        if host in text.replace("-", "").replace(".", ""):
            return name
    return names[0] if len(names) == 1 else "search"


def search_links(query: str) -> List[TabResult]:
    """Links to run the search by hand — always available, never fails."""
    return SearchLinksSource().search(query)
