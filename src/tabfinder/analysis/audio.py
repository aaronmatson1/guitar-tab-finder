"""Loading audio, and a clear error when the audio extra is not installed."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover
    import numpy as np

INSTALL_HINT = (
    "Audio analysis needs the optional audio extra. Install it with:\n"
    "    pip install 'guitar-tab-finder[audio]'\n"
    "(or: pip install librosa soundfile)"
)

DEFAULT_SR = 22050


class AudioUnavailable(RuntimeError):
    """Raised when audio analysis is requested without its dependencies."""


def require_audio() -> Tuple[Any, Any]:
    """Import librosa and numpy, or explain how to install them."""
    try:
        import librosa  # noqa: F401  (imported for the caller)
        import numpy as np
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise AudioUnavailable(f"{exc}\n\n{INSTALL_HINT}") from exc
    return librosa, np


@dataclass
class AudioClip:
    """Decoded audio, plus where it came from."""

    samples: "np.ndarray"
    sample_rate: int
    path: Optional[Path] = None
    offset: float = 0.0

    @property
    def duration(self) -> float:
        return len(self.samples) / float(self.sample_rate)

    def describe(self) -> str:
        minutes, seconds = divmod(self.duration, 60)
        return f"{int(minutes)}:{seconds:04.1f} at {self.sample_rate} Hz"


def load_audio(
    path: str,
    sample_rate: int = DEFAULT_SR,
    offset: float = 0.0,
    duration: Optional[float] = None,
) -> AudioClip:
    """Load an audio file as mono samples.

    Any format your libsndfile/audioread install can open works — wav, flac,
    ogg, mp3, m4a.
    """
    librosa, _np = require_audio()
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"no such audio file: {path}")
    samples, sr = librosa.load(
        str(source), sr=sample_rate, mono=True, offset=offset, duration=duration
    )
    if samples.size == 0:
        raise ValueError(f"{path} decoded to no audio (is the offset past the end?)")
    return AudioClip(samples=samples, sample_rate=int(sr), path=source, offset=offset)


def format_time(seconds: float) -> str:
    """Format a timestamp as ``m:ss``."""
    minutes, secs = divmod(max(0.0, seconds), 60)
    return f"{int(minutes)}:{secs:04.1f}"
