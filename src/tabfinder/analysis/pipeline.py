"""Put the analysis together: audio in, a playable arrangement out."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..guitar.fretboard import Fretboard
from ..guitar.voicings import Voicing, generate_voicings
from ..theory.chords import Chord
from ..theory.scales import Key, identify_progression, progression_numerals
from .audio import AudioClip, load_audio
from .chords import BeatGrid, ChordSegment, beat_track, chord_histogram, detect_chords
from .key import KeyEstimate, combine_estimates, estimate_key_from_chords, estimate_key_from_profile
from .melody import Note, transcribe_melody

#: Keys a guitarist can play with open chords, in rough order of comfort.
#: Keys needing a barre chord for their tonic (B minor, F major) are left out
#: on purpose: the whole point of a capo is to avoid those.
FRIENDLY_KEYS: Tuple[Tuple[int, str], ...] = (
    (7, "major"),   # G
    (0, "major"),   # C
    (4, "minor"),   # Em
    (2, "major"),   # D
    (9, "minor"),   # Am
    (9, "major"),   # A
    (4, "major"),   # E
    (2, "minor"),   # Dm
)

#: How much one fret of capo costs relative to one step down the comfort list.
#: Well under 1, so a familiar shape is worth a fret or two of capo, but a key
#: that is already easy never gets a capo recommended for no reason.
COMFORT_WEIGHT = 0.4


@dataclass
class CapoSuggestion:
    """A capo position, and the key it lets you play in."""

    fret: int
    shape_key: Key

    def describe(self) -> str:
        if self.fret == 0:
            return f"no capo needed — play in {self.shape_key.name}"
        return f"capo {self.fret} and play the shapes of {self.shape_key.name}"


@dataclass
class SongAnalysis:
    """Everything the analyser worked out about a piece of audio."""

    source: Optional[Path]
    duration: float
    tempo: float
    key: KeyEstimate
    chords: List[ChordSegment] = field(default_factory=list)
    beats: Optional[BeatGrid] = None
    melody: List[Note] = field(default_factory=list)
    capo: Optional[CapoSuggestion] = None
    progression_name: Optional[str] = None
    numerals: List[str] = field(default_factory=list)
    title: Optional[str] = None
    #: Where the audio came from, when it was not a local file.
    source_label: Optional[str] = None
    #: True when only a clip of the song was analysed, not the whole thing.
    partial: bool = False

    @property
    def chord_vocabulary(self) -> List[Tuple[Chord, float]]:
        """Distinct chords in the song, the most-used first."""
        return chord_histogram(self.chords)

    @property
    def loop(self) -> List[Chord]:
        """The repeating chord loop, if the song has an obvious one."""
        return _find_loop([segment.chord for segment in self.chords])

    def voicings(self, board: Optional[Fretboard] = None, per_chord: int = 1) -> List[Voicing]:
        """A shape for each chord in the song's vocabulary."""
        board = board or Fretboard.from_tuning()
        out: List[Voicing] = []
        for chord, _duration in self.chord_vocabulary:
            out.extend(generate_voicings(chord, board, limit=per_chord))
        return out

    def to_dict(self) -> Dict[str, Any]:
        """A JSON-serialisable summary, for piping into other tools."""
        return {
            "title": self.title,
            "source": str(self.source) if self.source else None,
            "source_label": self.source_label,
            "partial": self.partial,
            "duration": round(self.duration, 2),
            "tempo": round(self.tempo, 1),
            "key": {
                "name": self.key.key.name,
                "tonic": self.key.key.tonic,
                "mode": self.key.key.mode,
                "confidence": round(self.key.confidence, 3),
                "scale": self.key.key.scale_notes(),
                "pentatonic": self.key.key.pentatonic(),
                "alternatives": [
                    {"name": c.name, "correlation": round(c.correlation, 3)}
                    for c in self.key.top(4)[1:]
                ],
            },
            "capo": (
                {"fret": self.capo.fret, "shape_key": self.capo.shape_key.name}
                if self.capo
                else None
            ),
            "progression": {
                "name": self.progression_name,
                "numerals": self.numerals,
                "loop": [chord.symbol() for chord in self.loop],
            },
            "chords": [
                {
                    "chord": segment.symbol,
                    "start": round(segment.start, 2),
                    "end": round(segment.end, 2),
                    "bars": segment.beats / (self.beats.beats_per_bar if self.beats else 4),
                    "confidence": round(segment.confidence, 3),
                }
                for segment in self.chords
            ],
            "vocabulary": [
                {"chord": chord.symbol(), "seconds": round(seconds, 1)}
                for chord, seconds in self.chord_vocabulary
            ],
            "melody": [
                {
                    "note": note.name,
                    "midi": note.midi,
                    "start": round(note.start, 3),
                    "end": round(note.end, 3),
                }
                for note in self.melody
            ],
        }


def suggest_capo(key: Key, max_fret: int = 7) -> CapoSuggestion:
    """Find a capo position that turns an awkward key into open chords.

    A capo raises everything, so to *sound* in ``key`` while fingering shapes
    from an easier key, the shape key sits ``fret`` semitones below.
    """
    best: Optional[CapoSuggestion] = None
    best_cost = float("inf")
    for fret in range(0, max_fret + 1):
        shape_key = Key((key.tonic - fret) % 12, key.mode)
        token = (shape_key.tonic, shape_key.mode)
        if token not in FRIENDLY_KEYS:
            continue
        cost = FRIENDLY_KEYS.index(token) * COMFORT_WEIGHT + fret
        # Ties go to the lower capo position, which leaves more neck to play on.
        if cost < best_cost:
            best, best_cost = CapoSuggestion(fret, shape_key), cost
    return best or CapoSuggestion(0, key)


def _find_loop(chords: Sequence[Chord], max_length: int = 8) -> List[Chord]:
    """Spot the repeating chord loop a song is built on."""
    if len(chords) < 4:
        return list(chords)
    for length in range(2, max_length + 1):
        if len(chords) < length * 2:
            break
        candidate = list(chords[:length])
        repeats = 0
        index = 0
        while index + length <= len(chords):
            if list(chords[index : index + length]) == candidate:
                repeats += 1
                index += length
            else:
                break
        # Two full turns around the loop is enough to call it a loop.
        if repeats >= 2:
            return candidate
    # Otherwise just report the distinct chords in the order they first appear.
    seen: List[Chord] = []
    for chord in chords:
        if chord not in seen:
            seen.append(chord)
    return seen[:max_length]


def analyze_clip(
    clip: AudioClip,
    beats_per_bar: int = 4,
    change_penalty: float = 3.0,
    with_melody: bool = False,
    title: Optional[str] = None,
) -> SongAnalysis:
    """Run the full analysis over already-loaded audio."""
    grid = beat_track(clip, beats_per_bar=beats_per_bar)
    segments, grid = detect_chords(clip, grid, change_penalty=change_penalty)

    chord_key = None
    if segments:
        chord_key = estimate_key_from_chords(
            [s.chord for s in segments], [s.duration for s in segments]
        )
    audio_key = _key_from_audio(clip)
    key = combine_estimates(audio_key, chord_key)

    loop = _find_loop([s.chord for s in segments])
    numerals = progression_numerals(loop, key.key) if loop else []
    name = identify_progression(numerals) if numerals else None

    melody: List[Note] = []
    if with_melody:
        melody = transcribe_melody(clip)

    return SongAnalysis(
        source=clip.path,
        duration=clip.duration,
        tempo=grid.tempo,
        key=key,
        chords=segments,
        beats=grid,
        melody=melody,
        capo=suggest_capo(key.key),
        progression_name=name,
        numerals=numerals,
        title=title,
    )


def _key_from_audio(clip: AudioClip) -> KeyEstimate:
    """Key estimate straight from the average chroma of the recording."""
    librosa, np = _np()
    signal = librosa.effects.harmonic(clip.samples)
    chroma = librosa.feature.chroma_cqt(y=signal, sr=clip.sample_rate, bins_per_octave=36)
    profile = np.mean(chroma, axis=1)
    return estimate_key_from_profile([float(v) for v in profile])


def _np():
    from .audio import require_audio

    return require_audio()


def analyze_file(
    path: str,
    offset: float = 0.0,
    duration: Optional[float] = None,
    beats_per_bar: int = 4,
    change_penalty: float = 3.0,
    with_melody: bool = False,
    sample_rate: int = 22050,
    title: Optional[str] = None,
) -> SongAnalysis:
    """Analyse an audio file from disk."""
    clip = load_audio(path, sample_rate=sample_rate, offset=offset, duration=duration)
    analysis = analyze_clip(
        clip,
        beats_per_bar=beats_per_bar,
        change_penalty=change_penalty,
        with_melody=with_melody,
        title=title or Path(path).stem,
    )
    return analysis
