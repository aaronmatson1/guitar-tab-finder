"""Apple Music and iTunes.

The iTunes Search API is public and needs no key. It resolves a track's title
and artist, and hands back the same 30-second preview clip the Apple Music web
player uses. That clip is enough to find a song's key and its main chord loop,
which makes it the fallback for every provider that will not give us audio.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .fetch import DEFAULT_TIMEOUT, get_json
from .refs import TrackNotFound, TrackRef

LOOKUP_URL = "https://itunes.apple.com/lookup"
SEARCH_URL = "https://itunes.apple.com/search"

#: Apple's preview clips are 30 seconds (occasionally 90 for classical).
PREVIEW_SECONDS = 30.0


def parse_track(entry: Dict[str, Any], url: Optional[str] = None) -> Optional[TrackRef]:
    """Turn one iTunes API result into a track reference."""
    if not isinstance(entry, dict):
        return None
    if entry.get("kind") not in (None, "song", "music-video"):
        return None
    title = entry.get("trackName") or entry.get("collectionName")
    if not title:
        return None
    milliseconds = entry.get("trackTimeMillis")
    return TrackRef(
        provider="apple",
        url=url or entry.get("trackViewUrl") or "",
        track_id=str(entry.get("trackId")) if entry.get("trackId") else None,
        title=str(title),
        artist=str(entry["artistName"]) if entry.get("artistName") else None,
        duration=float(milliseconds) / 1000.0 if milliseconds else None,
        preview_url=entry.get("previewUrl"),
    )


def parse_results(payload: Any, url: Optional[str] = None) -> List[TrackRef]:
    """Read an iTunes lookup/search payload defensively."""
    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    out = []
    for entry in results:
        track = parse_track(entry, url=url)
        if track:
            out.append(track)
    return out


def resolve(track_id: str, url: str, timeout: float = DEFAULT_TIMEOUT) -> TrackRef:
    """Look up an Apple Music track id."""
    payload = get_json(LOOKUP_URL, {"id": track_id, "entity": "song"}, timeout=timeout)
    tracks = parse_results(payload, url=url)
    if not tracks:
        raise TrackNotFound(f"Apple Music has no track with id {track_id}")
    return tracks[0]


def find_preview(
    title: str, artist: Optional[str] = None, timeout: float = DEFAULT_TIMEOUT
) -> Optional[TrackRef]:
    """Search iTunes for a track, to borrow its preview clip.

    This is how a Spotify link — which will never give us audio — still ends up
    analysable: resolve the name there, find the same song here.
    """
    term = f"{artist} {title}" if artist else title
    payload = get_json(
        SEARCH_URL, {"term": term, "entity": "song", "limit": 5}, timeout=timeout
    )
    candidates = [t for t in parse_results(payload) if t.preview_url]
    if not candidates:
        return None
    return _best_match(candidates, title, artist)


def _best_match(candidates: List[TrackRef], title: str, artist: Optional[str]) -> TrackRef:
    """Pick the search result that best matches what we were looking for."""
    from difflib import SequenceMatcher

    def score(track: TrackRef) -> float:
        value = SequenceMatcher(None, title.lower(), (track.title or "").lower()).ratio()
        if artist and track.artist:
            value += SequenceMatcher(None, artist.lower(), track.artist.lower()).ratio()
        return value

    return max(candidates, key=score)
