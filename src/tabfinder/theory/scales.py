"""Keys, scales, diatonic harmony and roman-numeral analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .chords import (
    Chord,
    DIM,
    DOM7,
    MAJ7,
    MAJOR,
    MIN7,
    MINOR,
    M7B5,
    QUALITY_BY_NAME,
    Quality,
)
from .notes import note_name, prefers_flats

MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
NATURAL_MINOR = (0, 2, 3, 5, 7, 8, 10)
HARMONIC_MINOR = (0, 2, 3, 5, 7, 8, 11)
MELODIC_MINOR = (0, 2, 3, 5, 7, 9, 11)
MAJOR_PENTATONIC = (0, 2, 4, 7, 9)
MINOR_PENTATONIC = (0, 3, 5, 7, 10)
BLUES = (0, 3, 5, 6, 7, 10)

SCALES: Dict[str, Tuple[int, ...]] = {
    "major": MAJOR_SCALE,
    "minor": NATURAL_MINOR,
    "harmonic minor": HARMONIC_MINOR,
    "melodic minor": MELODIC_MINOR,
    "major pentatonic": MAJOR_PENTATONIC,
    "minor pentatonic": MINOR_PENTATONIC,
    "blues": BLUES,
}

#: Krumhansl-Kessler key profiles, the standard weights for key finding.
KK_MAJOR = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
KK_MINOR = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)

MIN6 = QUALITY_BY_NAME["minor 6th"]

_MAJOR_TRIADS = (MAJOR, MINOR, MINOR, MAJOR, MAJOR, MINOR, DIM)
_MINOR_TRIADS = (MINOR, DIM, MAJOR, MINOR, MINOR, MAJOR, MAJOR)
_MAJOR_SEVENTHS = (MAJ7, MIN7, MIN7, MAJ7, DOM7, MIN7, M7B5)
_MINOR_SEVENTHS = (MIN7, M7B5, MAJ7, MIN7, MIN7, MAJ7, DOM7)

_MAJOR_NUMERALS = ("I", "ii", "iii", "IV", "V", "vi", "vii°")
_MINOR_NUMERALS = ("i", "ii°", "III", "iv", "v", "VI", "VII")


@dataclass(frozen=True)
class Key:
    """A tonal centre: a tonic pitch class plus a mode."""

    tonic: int
    mode: str = "major"

    def __post_init__(self) -> None:
        object.__setattr__(self, "tonic", self.tonic % 12)
        mode = self.mode.lower()
        if mode not in ("major", "minor"):
            raise ValueError(f"mode must be 'major' or 'minor', got {self.mode!r}")
        object.__setattr__(self, "mode", mode)

    @property
    def prefer_flats(self) -> bool:
        """Whether this key reads better with flat accidentals."""
        # A minor key borrows its signature from its relative major.
        reference = self.tonic if self.mode == "major" else (self.tonic + 3) % 12
        return prefers_flats(reference)

    @property
    def scale(self) -> Tuple[int, ...]:
        """The pitch classes of the key's scale, ascending from the tonic."""
        steps = MAJOR_SCALE if self.mode == "major" else NATURAL_MINOR
        return tuple((self.tonic + step) % 12 for step in steps)

    @property
    def name(self) -> str:
        return f"{note_name(self.tonic, self.prefer_flats)} {self.mode}"

    @property
    def relative(self) -> "Key":
        """The relative major or minor key, which shares this key's notes."""
        if self.mode == "major":
            return Key((self.tonic + 9) % 12, "minor")
        return Key((self.tonic + 3) % 12, "major")

    @property
    def parallel(self) -> "Key":
        """The same tonic in the other mode."""
        return Key(self.tonic, "minor" if self.mode == "major" else "major")

    def scale_notes(self) -> List[str]:
        """The scale spelled out as note names."""
        return [note_name(pc, self.prefer_flats) for pc in self.scale]

    def pentatonic(self) -> List[str]:
        """The matching pentatonic scale — the safe notes for a solo."""
        steps = MAJOR_PENTATONIC if self.mode == "major" else MINOR_PENTATONIC
        return [note_name((self.tonic + s) % 12, self.prefer_flats) for s in steps]

    def diatonic_chords(self, sevenths: bool = False) -> List[Tuple[str, Chord]]:
        """The seven chords built on the scale, with roman numerals."""
        if self.mode == "major":
            qualities = _MAJOR_SEVENTHS if sevenths else _MAJOR_TRIADS
            numerals = _MAJOR_NUMERALS
        else:
            qualities = _MINOR_SEVENTHS if sevenths else _MINOR_TRIADS
            numerals = _MINOR_NUMERALS
        out = []
        for degree, pc in enumerate(self.scale):
            numeral = numerals[degree]
            if sevenths:
                numeral = _seventh_numeral(numeral, qualities[degree])
            out.append((numeral, Chord(pc, qualities[degree])))
        return out

    def contains(self, chord: Chord) -> bool:
        """True when every note of ``chord`` belongs to the key."""
        return set(chord.core_pitch_classes).issubset(set(self.scale))

    def degree_of(self, pc: int) -> Optional[int]:
        """Scale degree (1-7) of a pitch class, or ``None`` if it is outside."""
        scale = self.scale
        pc %= 12
        return scale.index(pc) + 1 if pc in scale else None

    def __str__(self) -> str:
        return self.name


def _seventh_numeral(numeral: str, quality: Quality) -> str:
    """Decorate a triad numeral with its seventh-chord suffix."""
    if quality is MAJ7:
        return numeral + "maj7"
    if quality is M7B5:
        return numeral.replace("°", "") + "ø7"
    return numeral + "7"


def all_keys() -> List[Key]:
    """Every major and minor key, in a stable order."""
    return [Key(pc, mode) for mode in ("major", "minor") for pc in range(12)]


def roman_numeral(chord: Chord, key: Key) -> str:
    """Label ``chord`` relative to ``key``, marking borrowed chords with a *."""
    degree = key.degree_of(chord.root)
    if degree is None:
        # Not in the key at all: name it by distance above the tonic.
        offset = (chord.root - key.tonic) % 12
        base = _CHROMATIC_NUMERALS[offset]
        numeral = base.lower() if chord.quality in (MINOR, MIN7, DIM, M7B5) else base
        return numeral + _quality_mark(chord.quality) + "*"

    numerals = _MAJOR_NUMERALS if key.mode == "major" else _MINOR_NUMERALS
    expected = (_MAJOR_TRIADS if key.mode == "major" else _MINOR_TRIADS)[degree - 1]
    numeral = numerals[degree - 1]
    is_minorish = chord.quality in (MINOR, MIN7, DIM, M7B5, MIN6)
    base = numeral.rstrip("°")
    base = base.lower() if is_minorish else base.upper()
    if chord.quality in (DIM, M7B5):
        base += "°"
    text = base + _quality_mark(chord.quality)
    if not _same_family(chord.quality, expected):
        text += "*"
    return text


_CHROMATIC_NUMERALS = ("I", "bII", "II", "bIII", "III", "IV", "bV", "V", "bVI", "VI", "bVII", "VII")


def _quality_mark(quality: Quality) -> str:
    """The suffix shown after a roman numeral for non-triad qualities."""
    if quality in (MAJOR, MINOR, DIM):
        return ""
    if quality is MAJ7:
        return "maj7"
    if quality is M7B5:
        return "ø7"
    return quality.suffix.lstrip("m").lstrip("M") or quality.suffix


def _same_family(actual: Quality, expected: Quality) -> bool:
    """Whether a chord quality is the diatonic one, ignoring added sevenths."""
    minorish = {MINOR, MIN7}
    majorish = {MAJOR, MAJ7, DOM7}
    dimish = {DIM, M7B5}
    for family in (minorish, majorish, dimish):
        if actual in family and expected in family:
            return True
    return actual is expected


def progression_numerals(chords: Sequence[Chord], key: Key) -> List[str]:
    """Roman numerals for a chord sequence in a key."""
    return [roman_numeral(chord, key) for chord in chords]


#: Progressions worth calling out by name when they show up in a song.
KNOWN_PROGRESSIONS: Dict[Tuple[str, ...], str] = {
    ("I", "V", "vi", "IV"): "the 'four chord song' (I-V-vi-IV)",
    ("vi", "IV", "I", "V"): "pop-punk / sensitive-female (vi-IV-I-V)",
    ("I", "IV", "V", "IV"): "three-chord rock (I-IV-V-IV)",
    ("I", "IV", "V"): "three-chord rock (I-IV-V)",
    ("ii", "V", "I"): "the jazz turnaround (ii-V-I)",
    ("I", "vi", "IV", "V"): "'50s doo-wop (I-vi-IV-V)",
    ("I", "V", "vi", "iii", "IV", "I", "IV", "V"): "Pachelbel's canon",
    ("i", "VI", "III", "VII"): "the minor 'Andalusian pop' loop (i-VI-III-VII)",
    ("i", "VII", "VI", "VII"): "minor vamp (i-VII-VI-VII)",
    ("i", "iv", "v"): "minor three-chord (i-iv-v)",
    ("I", "IV", "I", "V"): "blues-style I-IV-I-V",
}


def identify_progression(numerals: Sequence[str]) -> Optional[str]:
    """Name a repeating chord loop if it matches a well-known progression."""
    cleaned = [n.rstrip("*") for n in numerals]
    # Collapse immediate repeats so "I I V V vi vi IV IV" still matches.
    collapsed: List[str] = []
    for numeral in cleaned:
        if not collapsed or collapsed[-1] != numeral:
            collapsed.append(numeral)
    for length in (8, 4, 3):
        if len(collapsed) < length:
            continue
        window = tuple(collapsed[:length])
        if window in KNOWN_PROGRESSIONS:
            return KNOWN_PROGRESSIONS[window]
        # Try every rotation, since a loop can be heard from any starting point.
        for shift in range(1, length):
            rotated = tuple(collapsed[shift:length] + collapsed[:shift])
            if rotated in KNOWN_PROGRESSIONS:
                return KNOWN_PROGRESSIONS[rotated]
    return None
