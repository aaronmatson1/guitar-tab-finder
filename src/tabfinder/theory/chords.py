"""Chord qualities, chord objects and a chord-symbol parser."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .notes import NoteParseError, note_name, pitch_class, prefers_flats


@dataclass(frozen=True)
class Quality:
    """A chord quality: its printed suffix and its intervals above the root."""

    name: str
    suffix: str
    intervals: Tuple[int, ...]
    aliases: Tuple[str, ...] = ()
    # Intervals that may be dropped when a voicing cannot fit them all.
    optional: Tuple[int, ...] = ()

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name


QUALITIES: Tuple[Quality, ...] = (
    Quality("major", "", (0, 4, 7), ("maj", "M", "ma")),
    Quality("minor", "m", (0, 3, 7), ("min", "-", "mi")),
    Quality("dominant 7th", "7", (0, 4, 7, 10), ("dom7",), optional=(7,)),
    Quality("major 7th", "maj7", (0, 4, 7, 11), ("M7", "ma7", "Maj7", "△7"), optional=(7,)),
    Quality("minor 7th", "m7", (0, 3, 7, 10), ("min7", "-7", "mi7"), optional=(7,)),
    Quality("minor major 7th", "mMaj7", (0, 3, 7, 11), ("mM7", "minmaj7"), optional=(7,)),
    Quality("diminished", "dim", (0, 3, 6), ("o", "°")),
    Quality("diminished 7th", "dim7", (0, 3, 6, 9), ("o7", "°7")),
    Quality("half-diminished", "m7b5", (0, 3, 6, 10), ("ø", "min7b5", "m7-5")),
    Quality("augmented", "aug", (0, 4, 8), ("+", "#5")),
    Quality("suspended 2nd", "sus2", (0, 2, 7), ("sus9",)),
    Quality("suspended 4th", "sus4", (0, 5, 7), ("sus",)),
    Quality("6th", "6", (0, 4, 7, 9), ("maj6", "M6"), optional=(7,)),
    Quality("minor 6th", "m6", (0, 3, 7, 9), ("min6",), optional=(7,)),
    Quality("added 9th", "add9", (0, 2, 4, 7), ("add2",), optional=(7,)),
    Quality("minor added 9th", "madd9", (0, 2, 3, 7), ("minadd9",), optional=(7,)),
    Quality("dominant 9th", "9", (0, 4, 7, 10, 2), (), optional=(7,)),
    Quality("power chord", "5", (0, 7), ("no3",)),
)

QUALITY_BY_SUFFIX: Dict[str, Quality] = {}
for _q in QUALITIES:
    QUALITY_BY_SUFFIX[_q.suffix] = _q
    for _alias in _q.aliases:
        QUALITY_BY_SUFFIX.setdefault(_alias, _q)

QUALITY_BY_NAME: Dict[str, Quality] = {q.name: q for q in QUALITIES}

MAJOR = QUALITY_BY_NAME["major"]
MINOR = QUALITY_BY_NAME["minor"]
DOM7 = QUALITY_BY_NAME["dominant 7th"]
MAJ7 = QUALITY_BY_NAME["major 7th"]
MIN7 = QUALITY_BY_NAME["minor 7th"]
DIM = QUALITY_BY_NAME["diminished"]
AUG = QUALITY_BY_NAME["augmented"]
SUS2 = QUALITY_BY_NAME["suspended 2nd"]
SUS4 = QUALITY_BY_NAME["suspended 4th"]
M7B5 = QUALITY_BY_NAME["half-diminished"]
DIM7 = QUALITY_BY_NAME["diminished 7th"]

#: Qualities the audio chord recogniser will consider. Keeping this set small
#: avoids over-fitting noisy chroma to exotic spellings.
DETECTION_QUALITIES: Tuple[Quality, ...] = (MAJOR, MINOR, DOM7, MIN7, MAJ7, SUS4, DIM)


@dataclass(frozen=True)
class Chord:
    """A chord: a root pitch class, a quality, and an optional slash bass."""

    root: int
    quality: Quality = MAJOR
    bass: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root % 12)
        if self.bass is not None:
            object.__setattr__(self, "bass", self.bass % 12)

    @property
    def pitch_classes(self) -> Tuple[int, ...]:
        """Every pitch class the chord contains, bass note included."""
        pcs = [(self.root + i) % 12 for i in self.quality.intervals]
        if self.bass is not None and self.bass not in pcs:
            pcs.append(self.bass)
        return tuple(dict.fromkeys(pcs))

    @property
    def core_pitch_classes(self) -> Tuple[int, ...]:
        """Chord tones without the slash bass."""
        return tuple(dict.fromkeys((self.root + i) % 12 for i in self.quality.intervals))

    @property
    def optional_pitch_classes(self) -> Tuple[int, ...]:
        """Chord tones a voicing is allowed to leave out."""
        return tuple((self.root + i) % 12 for i in self.quality.optional)

    def symbol(self, prefer_flats: Optional[bool] = None) -> str:
        """Print the chord, e.g. ``F#m7`` or ``C/G``."""
        flats = prefers_flats(self.root) if prefer_flats is None else prefer_flats
        text = f"{note_name(self.root, flats)}{self.quality.suffix}"
        if self.bass is not None and self.bass != self.root:
            text += f"/{note_name(self.bass, flats)}"
        return text

    def transposed(self, semitones: int) -> "Chord":
        """Move the whole chord by ``semitones``."""
        bass = None if self.bass is None else (self.bass + semitones) % 12
        return Chord((self.root + semitones) % 12, self.quality, bass)

    def __str__(self) -> str:
        return self.symbol()


_CHORD_RE = re.compile(
    r"^\s*([A-Ga-g][#b♯♭]*)\s*([^/\s]*)\s*(?:/\s*([A-Ga-g][#b♯♭]*))?\s*$"
)


def parse_chord(symbol: str) -> Chord:
    """Parse a chord symbol such as ``Am7``, ``F#dim`` or ``C/G``."""
    match = _CHORD_RE.match(symbol)
    if not match:
        raise NoteParseError(f"cannot parse chord symbol: {symbol!r}")
    root_text, suffix, bass_text = match.groups()
    root = pitch_class(root_text)
    suffix = suffix.strip()
    if suffix == "":
        quality = MAJOR
    elif suffix in QUALITY_BY_SUFFIX:
        quality = QUALITY_BY_SUFFIX[suffix]
    else:
        lowered = {k.lower(): v for k, v in QUALITY_BY_SUFFIX.items()}
        if suffix.lower() not in lowered:
            raise NoteParseError(f"unknown chord quality: {suffix!r} (in {symbol!r})")
        quality = lowered[suffix.lower()]
    bass = pitch_class(bass_text) if bass_text else None
    return Chord(root, quality, bass)


def chord_template(chord: Chord, root_weight: float = 1.0) -> List[float]:
    """A 12-bin pitch-class profile for template matching against chroma."""
    template = [0.0] * 12
    for idx, interval in enumerate(chord.quality.intervals):
        pc = (chord.root + interval) % 12
        # The root and fifth dominate what a chroma vector actually sees.
        weight = root_weight if idx == 0 else 1.0
        template[pc] = max(template[pc], weight)
    return template


def detection_chords() -> List[Chord]:
    """Every chord the recogniser can output, in a stable order."""
    return [Chord(root, quality) for quality in DETECTION_QUALITIES for root in range(12)]


def chord_distance(a: Chord, b: Chord) -> int:
    """How many pitch classes two chords fail to share."""
    set_a, set_b = set(a.pitch_classes), set(b.pitch_classes)
    return len(set_a ^ set_b)
