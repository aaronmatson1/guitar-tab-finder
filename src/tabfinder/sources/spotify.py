"""Spotify.

Spotify streams are DRM-protected: there is no legitimate way to get audio out
of them, and this module does not try. What it does is resolve a track link to
a title and artist from Spotify's public oEmbed endpoint and page metadata,
which is enough to search for a tab — and enough to find the same song's
preview clip elsewhere if the audio is needed.
"""

from __future__ import annotations

import html
import re
from typing import Any, Dict, Optional

from .fetch import DEFAULT_TIMEOUT, get_json, get_text
from .refs import TrackNotFound, TrackRef, clean_title

OEMBED_URL = "https://open.spotify.com/oembed"
TRACK_URL = "https://open.spotify.com/track/{id}"

_OG_TAG = re.compile(
    r'<meta[^>]+(?:property|name)=["\']og:(title|description)["\'][^>]+content=["\']([^"\']*)["\']',
    re.IGNORECASE,
)
# Spotify's og:description reads like "Oasis · Song · 1995".
_DESCRIPTION = re.compile(r"^(?P<artist>.+?)\s*·\s*(?:Song|Single|Album|Track)\b", re.IGNORECASE)


def parse_oembed(payload: Dict[str, Any], track_id: str, url: str) -> Optional[TrackRef]:
    """Read an oEmbed response. Spotify's title is usually just the song."""
    if not isinstance(payload, dict):
        return None
    title = str(payload.get("title") or "").strip()
    if not title:
        return None
    artist = None
    # Some responses pack both into the title as "Song - Artist".
    for separator in (" · ", " - "):
        if separator in title:
            left, right = (part.strip() for part in title.split(separator, 1))
            title, artist = left, right
            break
    return TrackRef(
        provider="spotify",
        url=url,
        track_id=track_id,
        title=clean_title(title),
        artist=artist,
    )


def parse_page(page: str, track_id: str, url: str) -> Optional[TrackRef]:
    """Read title and artist from a track page's OpenGraph tags."""
    tags = {key.lower(): html.unescape(value) for key, value in _OG_TAG.findall(page)}
    title = tags.get("title", "").strip()
    if not title:
        return None
    artist = None
    match = _DESCRIPTION.match(tags.get("description", "").strip())
    if match:
        artist = match.group("artist").strip()
    return TrackRef(
        provider="spotify",
        url=url,
        track_id=track_id,
        title=clean_title(title),
        artist=artist,
    )


def resolve(track_id: str, url: str, timeout: float = DEFAULT_TIMEOUT) -> TrackRef:
    """Resolve a Spotify track to a title and artist.

    Tries oEmbed first, then the page's own metadata, and merges the two: the
    page usually carries the artist that oEmbed leaves out.
    """
    canonical = TRACK_URL.format(id=track_id)
    from_oembed: Optional[TrackRef] = None
    try:
        payload = get_json(OEMBED_URL, {"url": canonical}, timeout=timeout)
        from_oembed = parse_oembed(payload, track_id, url)
    except Exception:  # noqa: BLE001 - fall through to the page metadata
        from_oembed = None

    from_page: Optional[TrackRef] = None
    try:
        from_page = parse_page(get_text(canonical, timeout=timeout), track_id, url)
    except Exception:  # noqa: BLE001
        from_page = None

    return _merge(from_oembed, from_page, track_id)


def _merge(a: Optional[TrackRef], b: Optional[TrackRef], track_id: str) -> TrackRef:
    """Combine two partial lookups, preferring whichever field is filled in."""
    if a is None and b is None:
        raise TrackNotFound(
            f"could not read Spotify track {track_id}. The link may be private, "
            "region-locked, or no longer available."
        )
    if a is None:
        return b  # type: ignore[return-value]
    if b is None:
        return a
    return TrackRef(
        provider="spotify",
        url=a.url,
        track_id=track_id,
        title=a.title or b.title,
        artist=a.artist or b.artist,
        duration=a.duration or b.duration,
    )
