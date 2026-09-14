"""Search Songsterr, which publishes a simple JSON search endpoint."""

from __future__ import annotations

from typing import Any, Dict, List

from .base import DEFAULT_TIMEOUT, USER_AGENT, TabResult, TabSource

API_URL = "https://www.songsterr.com/api/songs"
SONG_URL = "https://www.songsterr.com/a/wa/song?id={id}"


class SongsterrSource(TabSource):
    """Songsterr hosts interactive, playable tabs."""

    name = "songsterr"

    def search(self, query: str, limit: int = 10, timeout: float = DEFAULT_TIMEOUT) -> List[TabResult]:
        import requests

        response = requests.get(
            API_URL,
            params={"pattern": query, "size": max(1, min(limit, 25))},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=timeout,
        )
        response.raise_for_status()
        return parse_songsterr(response.json(), limit=limit)


def parse_songsterr(payload: Any, limit: int = 10) -> List[TabResult]:
    """Turn the Songsterr JSON payload into results.

    Written defensively: the endpoint is undocumented and its shape has
    changed before, so anything unexpected is skipped rather than fatal.
    """
    if isinstance(payload, dict):
        payload = payload.get("songs") or payload.get("results") or []
    if not isinstance(payload, list):
        return []

    out: List[TabResult] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        song_id = entry.get("id") or entry.get("songId")
        title = entry.get("title") or entry.get("name")
        artist = _artist_name(entry)
        if not song_id or not title:
            continue
        out.append(
            TabResult(
                title=str(title),
                artist=artist,
                url=SONG_URL.format(id=song_id),
                source="Songsterr",
                kind=_kind(entry),
            )
        )
        if len(out) >= limit:
            break
    return out


def _artist_name(entry: Dict[str, Any]) -> str:
    artist = entry.get("artist")
    if isinstance(artist, dict):
        return str(artist.get("name") or artist.get("nameWithoutThePrefix") or "unknown")
    if isinstance(artist, str):
        return artist
    return str(entry.get("artistName") or "unknown")


def _kind(entry: Dict[str, Any]) -> str:
    tracks = entry.get("tracks")
    if isinstance(tracks, list) and tracks:
        instruments = {
            str(t.get("instrument", "")).lower() for t in tracks if isinstance(t, dict)
        }
        if any("bass" in i for i in instruments):
            return "tab (incl. bass)"
    return "interactive tab"
