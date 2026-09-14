"""HTTP helpers and audio format wrangling for the link sources."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from .refs import SourceError

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 10.0

#: A preview clip is tiny; a full track is not. Cap downloads so a bad link
#: cannot fill the disk.
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024

#: Formats libsndfile reads without any external help.
NATIVE_AUDIO_SUFFIXES = {".wav", ".flac", ".ogg", ".oga", ".mp3", ".aiff", ".aif", ".au", ".w64"}


def get_json(url: str, params: Optional[Dict[str, Any]] = None, timeout: float = DEFAULT_TIMEOUT) -> Any:
    """GET a URL and parse the response as JSON."""
    import requests

    response = requests.get(
        url, params=params, headers={"User-Agent": BROWSER_UA, "Accept": "application/json"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def get_text(url: str, params: Optional[Dict[str, Any]] = None, timeout: float = DEFAULT_TIMEOUT) -> str:
    """GET a URL and return the body as text."""
    import requests

    response = requests.get(
        url, params=params, headers={"User-Agent": BROWSER_UA, "Accept": "text/html"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.text


def download(url: str, destination: Path, timeout: float = 30.0,
             max_bytes: int = MAX_DOWNLOAD_BYTES) -> Path:
    """Stream a URL to a file, refusing anything implausibly large."""
    import requests

    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=timeout, stream=True) as response:
        response.raise_for_status()
        with open(destination, "wb") as handle:
            for chunk in response.iter_content(chunk_size=65536):
                written += len(chunk)
                if written > max_bytes:
                    handle.close()
                    destination.unlink(missing_ok=True)
                    raise SourceError(
                        f"download exceeded {max_bytes // (1024 * 1024)} MB and was stopped"
                    )
                handle.write(chunk)
    if written == 0:
        destination.unlink(missing_ok=True)
        raise SourceError(f"downloaded nothing from {url}")
    return destination


def have_ffmpeg() -> bool:
    """Whether ffmpeg is on PATH to decode formats libsndfile cannot."""
    return shutil.which("ffmpeg") is not None


def ensure_readable(path: Path) -> Path:
    """Make sure the analyser can actually decode this file.

    libsndfile handles wav, flac, ogg and mp3 on its own. Anything else — an
    AAC preview clip, a webm stream from a video site — goes through ffmpeg.
    """
    if path.suffix.lower() in NATIVE_AUDIO_SUFFIXES:
        return path
    if not have_ffmpeg():
        raise SourceError(
            f"cannot decode {path.suffix or 'this'} audio without ffmpeg.\n"
            "Install ffmpeg (brew install ffmpeg / apt install ffmpeg), or pass a "
            "wav, mp3, flac or ogg file instead."
        )
    target = path.with_suffix(".wav")
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(path), "-ac", "1", "-ar", "22050", str(target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not target.exists():
        raise SourceError(f"ffmpeg could not decode {path.name}: {result.stderr.strip()[:200]}")
    return target
