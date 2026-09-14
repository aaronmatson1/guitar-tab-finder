"""YouTube.

Titles and channel names come from YouTube's public oEmbed endpoint, which
needs no API key. Audio needs yt-dlp, which is not a dependency of this
project and is only ever run when the user explicitly opts in.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from .fetch import DEFAULT_TIMEOUT, get_json
from .refs import AudioNotAvailable, SourceError, TrackNotFound, TrackRef, split_artist_title

OEMBED_URL = "https://www.youtube.com/oembed"
WATCH_URL = "https://www.youtube.com/watch?v={id}"

#: Formats worth asking yt-dlp for, best first. m4a and webm both need ffmpeg
#: to decode, which :func:`tabfinder.sources.fetch.ensure_readable` handles.
FORMAT_PREFERENCE = "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best"


def parse_oembed(payload: Dict[str, Any], video_id: str, url: str) -> TrackRef:
    """Turn an oEmbed response into a track reference."""
    raw_title = str(payload.get("title") or "").strip()
    if not raw_title:
        raise TrackNotFound(f"YouTube returned no title for {video_id}")
    artist, title = split_artist_title(raw_title, payload.get("author_name"))
    return TrackRef(
        provider="youtube",
        url=url,
        track_id=video_id,
        title=title,
        artist=artist,
    )


def resolve(video_id: str, url: str, timeout: float = DEFAULT_TIMEOUT) -> TrackRef:
    """Look up a video's title and channel."""
    payload = get_json(
        OEMBED_URL, {"url": WATCH_URL.format(id=video_id), "format": "json"}, timeout=timeout
    )
    if not isinstance(payload, dict):
        raise TrackNotFound(f"unexpected oEmbed response for {video_id}")
    return parse_oembed(payload, video_id, url)


def yt_dlp_available() -> bool:
    """Whether yt-dlp is installed and on PATH."""
    return shutil.which("yt-dlp") is not None


def download_audio(url: str, directory: Path, timeout: float = 300.0) -> Path:
    """Pull the audio track out of a video with yt-dlp.

    Only ever called when the caller has explicitly allowed downloading.
    """
    if not yt_dlp_available():
        raise AudioNotAvailable(
            "downloading YouTube audio needs yt-dlp, which is not installed.\n"
            "    pip install yt-dlp        (or: brew install yt-dlp)"
        )
    directory.mkdir(parents=True, exist_ok=True)
    template = str(directory / "%(id)s.%(ext)s")
    command = [
        "yt-dlp",
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        "-f", FORMAT_PREFERENCE,
        "-o", template,
        "--print", "after_move:filepath",
        url,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise SourceError(f"yt-dlp timed out after {timeout:.0f}s") from exc

    if result.returncode != 0:
        raise SourceError(f"yt-dlp failed: {_first_error(result.stderr)}")

    path = _downloaded_path(result.stdout, directory)
    if path is None:
        raise SourceError("yt-dlp reported success but produced no file")
    return path


def _downloaded_path(stdout: str, directory: Path) -> Optional[Path]:
    """Find the file yt-dlp wrote, from its output or from the directory."""
    for line in reversed([line.strip() for line in stdout.splitlines() if line.strip()]):
        candidate = Path(line)
        if candidate.exists():
            return candidate
    files = sorted(directory.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _first_error(stderr: str) -> str:
    """The most useful line out of a yt-dlp failure."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    for line in lines:
        if "ERROR" in line:
            return line[:300]
    return (lines[-1] if lines else "unknown error")[:300]
