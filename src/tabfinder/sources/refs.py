"""What a music link points at, and what audio we can get for it."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse


class SourceError(RuntimeError):
    """Something went wrong resolving or fetching a track."""


class UnsupportedURL(SourceError):
    """The link is not one we know how to read."""


class TrackNotFound(SourceError):
    """The link looked right but the provider had nothing for it."""


class AudioNotAvailable(SourceError):
    """We could identify the track but cannot legally get audio for it."""


@dataclass
class TrackRef:
    """A track identified from a link: who it is, and where audio might come from."""

    provider: str
    url: str
    track_id: Optional[str] = None
    title: Optional[str] = None
    artist: Optional[str] = None
    duration: Optional[float] = None
    preview_url: Optional[str] = None

    @property
    def query(self) -> str:
        """The best search string for finding a tab for this track."""
        if self.artist and self.title:
            return f"{self.artist} - {self.title}"
        return self.title or self.url

    @property
    def display(self) -> str:
        if self.artist and self.title:
            return f"{self.title} — {self.artist}"
        return self.title or self.url

    @property
    def resolved(self) -> bool:
        return bool(self.title)


@dataclass
class AudioSource:
    """Audio on disk, and how much of the song it actually is."""

    path: Path
    kind: str           # "full" or "preview"
    origin: str         # where it came from, for the report
    seconds: Optional[float] = None
    temporary: bool = True

    @property
    def is_preview(self) -> bool:
        return self.kind == "preview"

    def describe(self) -> str:
        if self.is_preview:
            length = f"{self.seconds:.0f}s " if self.seconds else ""
            return f"{length}preview clip from {self.origin}"
        return f"full audio from {self.origin}"


# --- link parsing --------------------------------------------------------

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
_SPOTIFY_HOSTS = {"open.spotify.com", "play.spotify.com"}
_APPLE_HOSTS = {"music.apple.com", "itunes.apple.com", "geo.music.apple.com"}

_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def is_url(text: str) -> bool:
    """True when a string looks like a link rather than a song title."""
    candidate = text.strip()
    if candidate.startswith("spotify:"):
        return True
    parsed = urlparse(candidate)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def identify(url: str) -> Tuple[str, Optional[str]]:
    """Work out which service a link belongs to, and the id inside it.

    Returns ``(provider, track_id)``. Raises :class:`UnsupportedURL` for links
    we cannot read, and for links that point at a playlist or album rather
    than a single track.
    """
    text = url.strip()

    # Spotify's own URI scheme, e.g. spotify:track:7ygpwy2qP3NbrxVkHvUhXY
    if text.startswith("spotify:"):
        parts = text.split(":")
        if len(parts) >= 3 and parts[1] == "track":
            return "spotify", parts[2]
        raise UnsupportedURL(
            f"only Spotify track links work, not {parts[1] if len(parts) > 1 else 'that'} links"
        )

    parsed = urlparse(text)
    host = parsed.netloc.lower()
    path = parsed.path
    query = parse_qs(parsed.query)

    if host in _YOUTUBE_HOSTS:
        return "youtube", _youtube_id(host, path, query)

    if host in _SPOTIFY_HOSTS:
        # Locale-prefixed links look like /intl-de/track/<id>.
        match = re.search(r"/track/([A-Za-z0-9]+)", path)
        if match:
            return "spotify", match.group(1)
        if "/album/" in path or "/playlist/" in path:
            raise UnsupportedURL("that is a Spotify album or playlist link; link a single track")
        raise UnsupportedURL(f"cannot find a track id in {url!r}")

    if host in _APPLE_HOSTS:
        # Apple Music puts the track id in ?i= on an album URL.
        track_id = query.get("i", [None])[0]
        if track_id:
            return "apple", track_id
        match = re.search(r"/song/(?:[^/]+/)?(\d+)", path)
        if match:
            return "apple", match.group(1)
        if "/album/" in path or "/playlist/" in path:
            raise UnsupportedURL(
                "that Apple Music link points at a whole album; open one song and copy that link "
                "(it ends with ?i=<number>)"
            )
        raise UnsupportedURL(f"cannot find a track id in {url!r}")

    raise UnsupportedURL(
        f"unsupported link: {url!r}. YouTube, Spotify and Apple Music links work, "
        "or just pass the song title."
    )


def _youtube_id(host: str, path: str, query: dict) -> Optional[str]:
    """Pull the video id out of any of YouTube's link shapes."""
    if host == "youtu.be":
        candidate = path.lstrip("/").split("/")[0]
        return candidate or None
    if path.startswith("/watch"):
        return query.get("v", [None])[0]
    for prefix in ("/shorts/", "/embed/", "/v/", "/live/"):
        if path.startswith(prefix):
            return path[len(prefix) :].split("/")[0] or None
    if "list" in query and "v" not in query:
        raise UnsupportedURL("that is a YouTube playlist link; link a single video")
    return query.get("v", [None])[0]


# --- title tidying -------------------------------------------------------

#: Words that carry no information for a tab search. A bracketed group made
#: only of these is clutter; one with a real word in it ("Live at Wembley",
#: "feat. Someone") is kept, because it distinguishes one version from another.
_NOISE_WORDS = {
    "official", "video", "audio", "music", "lyric", "lyrics", "lyrical",
    "visualizer", "visualiser", "hd", "hq", "uhd", "4k", "8k", "1080p", "720p",
    "remaster", "remastered", "remasterd", "mv", "m/v", "explicit", "clean",
    "version", "full", "album", "single", "edit", "stereo", "mono", "in",
    "the", "a", "and", "with", "from", "new", "original", "sound", "track",
}

_BRACKETS = re.compile(r"\s*[\(\[]([^()\[\]]*)[\)\]]")
_TRAILING_NOISE = re.compile(
    r"\s*[-\u2013|]\s*(?:official\s+)?(?:music\s+)?(?:video|audio|lyrics?)\s*$",
    re.IGNORECASE,
)


def _is_noise_group(text: str) -> bool:
    """True when a bracketed group says nothing about which song this is."""
    words = re.findall(r"[a-z0-9/]+", text.lower())
    if not words:
        return True
    for word in words:
        if word in _NOISE_WORDS:
            continue
        if word.isdigit() and len(word) == 4:  # a year, e.g. "Remastered 2014"
            continue
        return False
    return True


def clean_title(title: str) -> str:
    """Strip the ``(Official Video) [Remastered in 4K]`` clutter off a title."""
    text = title.strip()
    previous = None
    while previous != text:
        previous = text
        text = _BRACKETS.sub(lambda m: "" if _is_noise_group(m.group(1)) else m.group(0), text)
        text = _TRAILING_NOISE.sub("", text)
    return " ".join(text.split()).strip(" -\u2013|")


def split_artist_title(text: str, fallback_artist: Optional[str] = None) -> Tuple[Optional[str], str]:
    """Split ``"Oasis - Wonderwall"`` into artist and title.

    Video titles usually carry the artist in front of a dash. When there is no
    dash, fall back to the channel name, which is often the artist itself.
    """
    cleaned = clean_title(text)
    channel = _tidy_channel(fallback_artist)
    for separator in (" - ", " \u2013 ", " \u2014 ", " | "):
        if separator not in cleaned:
            continue
        left, right = (part.strip() for part in cleaned.split(separator, 1))
        if not (left and right):
            continue
        # Plenty of uploads are titled "Song - Artist"; the channel name says
        # which half is which.
        if channel and _same_name(right, channel) and not _same_name(left, channel):
            return right, left
        return left, right
    return channel, cleaned


def _same_name(a: str, b: str) -> bool:
    """Compare names ignoring case, spacing and punctuation."""
    normalise = lambda text: re.sub(r"[^a-z0-9]", "", text.lower())  # noqa: E731
    return normalise(a) == normalise(b)


def _tidy_channel(name: Optional[str]) -> Optional[str]:
    """Turn a channel name into an artist name, where that makes sense."""
    if not name:
        return None
    text = name.strip()
    # "OasisVEVO" / "Oasis - Topic" are really just the artist.
    text = re.sub(r"\s*VEVO$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*-\s*Topic$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*Official$", "", text, flags=re.IGNORECASE)
    return text.strip() or None
