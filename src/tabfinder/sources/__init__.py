"""Turn a music link into a searchable name, and into audio where we can.

What each service can give us differs, and the difference is not a technical
detail — it decides what the tool can do:

===========  ==========================  ==================================
service      metadata                    audio
===========  ==========================  ==================================
YouTube      public oEmbed, no key       full track, via yt-dlp, opt-in
Apple Music  public iTunes API, no key   30-second preview clip
Spotify      public oEmbed + page tags   none — the streams are DRM-locked
===========  ==========================  ==================================

Anything without audio of its own falls back to searching iTunes for the same
song and borrowing its preview clip, so a Spotify link still ends in a real
analysis without going anywhere near the DRM.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from . import apple, spotify, youtube
from .fetch import DEFAULT_TIMEOUT, download, ensure_readable, have_ffmpeg
from .refs import (
    AudioNotAvailable,
    AudioSource,
    SourceError,
    TrackNotFound,
    TrackRef,
    UnsupportedURL,
    clean_title,
    identify,
    is_url,
    split_artist_title,
)

__all__ = [
    "AudioNotAvailable",
    "AudioPolicy",
    "AudioSource",
    "SourceError",
    "TrackNotFound",
    "TrackRef",
    "UnsupportedURL",
    "acquire_audio",
    "clean_title",
    "identify",
    "is_url",
    "resolve_track",
    "split_artist_title",
]

#: Services that can hand over full audio, and how.
FULL_AUDIO_PROVIDERS = {"youtube"}


@dataclass
class AudioPolicy:
    """What the user has allowed us to fetch.

    Preview clips are public, tiny and meant to be played, so they are on by
    default. Pulling a full track off a video site is a bigger step and stays
    off until asked for.
    """

    allow_preview: bool = True
    allow_download: bool = False
    timeout: float = 30.0


def resolve_track(url: str, timeout: float = DEFAULT_TIMEOUT) -> TrackRef:
    """Identify what a YouTube, Spotify or Apple Music link points at."""
    provider, track_id = identify(url)
    if not track_id:
        raise UnsupportedURL(f"could not find a track id in {url!r}")

    if provider == "youtube":
        return youtube.resolve(track_id, url, timeout=timeout)
    if provider == "spotify":
        return spotify.resolve(track_id, url, timeout=timeout)
    if provider == "apple":
        return apple.resolve(track_id, url, timeout=timeout)
    raise UnsupportedURL(f"no resolver for provider {provider!r}")


def acquire_audio(
    ref: TrackRef,
    directory: Path,
    policy: Optional[AudioPolicy] = None,
) -> AudioSource:
    """Get audio for a track, within what the policy allows.

    Tries the fullest source first and falls back, so the caller always gets
    the best audio available rather than the first thing that works.
    """
    policy = policy or AudioPolicy()
    directory = Path(directory)
    attempts: List[str] = []

    if policy.allow_download and ref.provider in FULL_AUDIO_PROVIDERS:
        try:
            path = youtube.download_audio(ref.url, directory, timeout=max(policy.timeout, 300.0))
            return AudioSource(
                path=ensure_readable(path),
                kind="full",
                origin="YouTube (yt-dlp)",
                seconds=ref.duration,
            )
        except SourceError as exc:
            attempts.append(f"full download: {exc}")

    if policy.allow_preview:
        preview = _preview_ref(ref, policy, attempts)
        if preview is not None and preview.preview_url:
            suffix = _suffix_of(preview.preview_url)
            target = directory / f"preview_{preview.track_id or 'track'}{suffix}"
            try:
                downloaded = download(preview.preview_url, target, timeout=policy.timeout)
                origin = "Apple Music" if preview is ref else f"Apple Music ({preview.display})"
                return AudioSource(
                    path=ensure_readable(downloaded),
                    kind="preview",
                    origin=origin,
                    seconds=apple.PREVIEW_SECONDS,
                )
            except SourceError:
                raise
            except Exception as exc:  # noqa: BLE001 - network/IO
                attempts.append(f"preview download: {exc}")

    raise AudioNotAvailable(_explain(ref, policy, attempts))


def _preview_ref(ref: TrackRef, policy: AudioPolicy, attempts: List[str]) -> Optional[TrackRef]:
    """The track whose preview clip we should download."""
    if ref.preview_url:
        return ref
    if not ref.title:
        return None
    try:
        found = apple.find_preview(ref.title, ref.artist, timeout=policy.timeout)
    except Exception as exc:  # noqa: BLE001 - network
        attempts.append(f"iTunes preview search: {exc}")
        return None
    if found is None:
        attempts.append(f"iTunes has no preview for {ref.query!r}")
    return found


def _suffix_of(url: str) -> str:
    """The file extension of a URL, defaulting to Apple's m4a previews."""
    tail = url.split("?")[0].rsplit("/", 1)[-1]
    if "." in tail:
        suffix = "." + tail.rsplit(".", 1)[-1].lower()
        if len(suffix) <= 5:
            return suffix
    return ".m4a"


def _explain(ref: TrackRef, policy: AudioPolicy, attempts: List[str]) -> str:
    """Say why there is no audio, and what the user can do about it."""
    lines = [f"could not get audio for {ref.display}."]
    if attempts:
        lines.append("Tried:")
        lines.extend(f"  - {attempt}" for attempt in attempts)

    if ref.provider == "spotify":
        lines.append(
            "Spotify streams are DRM-protected, so there is never audio to take from a "
            "Spotify link directly."
        )
    if ref.provider in FULL_AUDIO_PROVIDERS and not policy.allow_download:
        lines.append(
            "Pass --allow-download to fetch the full audio with yt-dlp (you are "
            "responsible for having the right to do so)."
        )
    elif ref.provider in FULL_AUDIO_PROVIDERS and not youtube.yt_dlp_available():
        lines.append("Install yt-dlp to fetch full audio:  pip install yt-dlp")
    if not have_ffmpeg():
        lines.append(
            "ffmpeg is not installed, which is needed to decode preview clips "
            "(they are AAC). Install it, or supply a wav/mp3 file yourself."
        )
    lines.append("You can also supply the audio yourself:  tabfinder analyze <file>")
    return "\n".join(lines)
