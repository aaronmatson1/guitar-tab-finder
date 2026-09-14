"""Transcribe a single-note line — a riff, a lick, a vocal melody — from audio.

This only works on monophonic material: one note at a time. Run it on an
isolated riff or an intro, not on a full mix, or you will get the loudest
partial of whatever is playing rather than a melody.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from ..theory.notes import midi_to_name
from .audio import AudioClip, require_audio

#: Sensible pitch bounds for guitar: low E to a high note up the neck.
DEFAULT_FMIN_MIDI = 40  # E2
DEFAULT_FMAX_MIDI = 88  # E6


@dataclass
class Note:
    """One transcribed note."""

    midi: int
    start: float
    end: float
    confidence: float = 1.0

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def name(self) -> str:
        return midi_to_name(self.midi)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name}@{self.start:.2f}s"


def transcribe_melody(
    clip: AudioClip,
    fmin_midi: int = DEFAULT_FMIN_MIDI,
    fmax_midi: int = DEFAULT_FMAX_MIDI,
    min_duration: float = 0.06,
    min_confidence: float = 0.5,
) -> List[Note]:
    """Extract a monophonic note sequence using probabilistic YIN."""
    librosa, np = require_audio()
    f0, voiced, voiced_prob = librosa.pyin(
        clip.samples,
        fmin=float(librosa.midi_to_hz(fmin_midi)),
        fmax=float(librosa.midi_to_hz(fmax_midi)),
        sr=clip.sample_rate,
    )
    times = librosa.times_like(f0, sr=clip.sample_rate)

    midi = librosa.hz_to_midi(f0)
    notes: List[Note] = []
    current: Optional[List] = None  # [rounded_midi, start, end, [confidences]]

    for index, value in enumerate(midi):
        is_voiced = bool(voiced[index]) and np.isfinite(value)
        confidence = float(voiced_prob[index]) if np.isfinite(voiced_prob[index]) else 0.0
        rounded = int(round(float(value))) if is_voiced else None
        if is_voiced and confidence >= min_confidence:
            if current is not None and current[0] == rounded:
                current[2] = float(times[index])
                current[3].append(confidence)
                continue
            if current is not None:
                notes.append(_finish(current))
            current = [rounded, float(times[index]), float(times[index]), [confidence]]
        elif current is not None:
            notes.append(_finish(current))
            current = None
    if current is not None:
        notes.append(_finish(current))

    kept = [n for n in notes if n.duration >= min_duration]
    return _join_repeats(kept)


def _finish(state: List) -> Note:
    midi, start, end, confidences = state
    return Note(
        midi=midi,
        start=start,
        end=end,
        confidence=sum(confidences) / len(confidences) if confidences else 0.0,
    )


def _join_repeats(notes: Sequence[Note], gap: float = 0.03) -> List[Note]:
    """Stitch a note back together when vibrato briefly split it in two."""
    out: List[Note] = []
    for note in notes:
        if out and out[-1].midi == note.midi and note.start - out[-1].end <= gap:
            out[-1].end = note.end
            continue
        out.append(note)
    return out


def quantize_to_beats(
    notes: Sequence[Note], beat_times: Sequence[float], subdivisions: int = 2
) -> List[Tuple[Note, int]]:
    """Snap notes onto a beat grid, returning each note with its grid slot.

    ``subdivisions`` of 2 puts notes on eighth notes, 4 on sixteenths.
    """
    if not beat_times:
        return [(note, index) for index, note in enumerate(notes)]
    grid: List[float] = []
    for index in range(len(beat_times) - 1):
        start, end = beat_times[index], beat_times[index + 1]
        for step in range(subdivisions):
            grid.append(start + (end - start) * step / subdivisions)
    grid.append(beat_times[-1])

    out: List[Tuple[Note, int]] = []
    for note in notes:
        slot = min(range(len(grid)), key=lambda i: abs(grid[i] - note.start))
        out.append((note, slot))
    return out
