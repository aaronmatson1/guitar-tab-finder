"""The fretboard itself: tunings, capos, and where notes live on the neck."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..theory.notes import midi_to_name, name_to_midi, note_name

#: Tunings are listed low string first (6th string to 1st string).
TUNINGS: Dict[str, Tuple[str, ...]] = {
    "standard": ("E2", "A2", "D3", "G3", "B3", "E4"),
    "drop-d": ("D2", "A2", "D3", "G3", "B3", "E4"),
    "half-step-down": ("Eb2", "Ab2", "Db3", "Gb3", "Bb3", "Eb4"),
    "full-step-down": ("D2", "G2", "C3", "F3", "A3", "D4"),
    "drop-c": ("C2", "G2", "C3", "F3", "A3", "D4"),
    "open-g": ("D2", "G2", "D3", "G3", "B3", "D4"),
    "open-d": ("D2", "A2", "D3", "F#3", "A3", "D4"),
    "open-e": ("E2", "B2", "E3", "G#3", "B3", "E4"),
    "dadgad": ("D2", "A2", "D3", "G3", "A3", "D4"),
    "bass-standard": ("E1", "A1", "D2", "G2"),
    "ukulele": ("G4", "C4", "E4", "A4"),
}

DEFAULT_TUNING = "standard"


@dataclass(frozen=True)
class Position:
    """One place to play one note: a string, a fret, and the pitch it makes."""

    string: int  # 0 = lowest-pitched string
    fret: int
    midi: int

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"s{self.string + 1}f{self.fret}"


@dataclass(frozen=True)
class Fretboard:
    """A tuned neck. ``capo`` raises every open string and hides lower frets."""

    open_strings: Tuple[int, ...]
    frets: int = 20
    capo: int = 0
    tuning_name: str = DEFAULT_TUNING

    @classmethod
    def from_tuning(cls, name: str = DEFAULT_TUNING, frets: int = 20, capo: int = 0) -> "Fretboard":
        """Build a fretboard from a named tuning such as ``drop-d``."""
        key = name.strip().lower().replace("_", "-").replace(" ", "-")
        if key not in TUNINGS:
            known = ", ".join(sorted(TUNINGS))
            raise ValueError(f"unknown tuning {name!r}; known tunings: {known}")
        strings = tuple(name_to_midi(n) for n in TUNINGS[key])
        return cls(strings, frets=frets, capo=capo, tuning_name=key)

    @property
    def string_count(self) -> int:
        return len(self.open_strings)

    @property
    def lowest_fret(self) -> int:
        """The lowest fret available to the fretting hand (behind any capo)."""
        return self.capo

    def midi_at(self, string: int, fret: int) -> int:
        """The MIDI pitch sounded by a string/fret pair."""
        if not 0 <= string < self.string_count:
            raise IndexError(f"string {string} out of range")
        if not self.capo <= fret <= self.frets:
            raise IndexError(f"fret {fret} out of range (capo {self.capo}, {self.frets} frets)")
        return self.open_strings[string] + fret

    def open_midi(self, string: int) -> int:
        """The pitch of a string played open (behind the capo)."""
        return self.open_strings[string] + self.capo

    def positions_for_midi(self, midi: int) -> List[Position]:
        """Every place a given pitch can be played, low string first."""
        out = []
        for string in range(self.string_count):
            fret = midi - self.open_strings[string]
            if self.capo <= fret <= self.frets:
                out.append(Position(string, fret, midi))
        return out

    def positions_for_pitch_class(self, pc: int, max_fret: Optional[int] = None) -> List[Position]:
        """Every place a pitch class appears, in any octave."""
        limit = self.frets if max_fret is None else min(self.frets, max_fret)
        out = []
        for string in range(self.string_count):
            for fret in range(self.capo, limit + 1):
                midi = self.open_strings[string] + fret
                if midi % 12 == pc % 12:
                    out.append(Position(string, fret, midi))
        return out

    def pitch_range(self) -> Tuple[int, int]:
        """The lowest and highest MIDI notes this neck can play."""
        lowest = min(self.open_strings) + self.capo
        highest = max(self.open_strings) + self.frets
        return lowest, highest

    def can_play(self, midi: int) -> bool:
        """Whether a pitch is anywhere on the neck."""
        return bool(self.positions_for_midi(midi))

    def string_names(self) -> List[str]:
        """String names, low to high, e.g. ``['E2', 'A2', ...]``."""
        return [midi_to_name(m) for m in self.open_strings]

    def string_labels(self) -> List[str]:
        """String labels for tab rows, low to high.

        A string repeating a name an octave up is lowercased, following the
        usual ``E A D G B e`` convention.
        """
        labels: List[str] = []
        for midi in self.open_strings:
            name = note_name(midi % 12)
            if name in labels:
                name = name.lower()
            labels.append(name)
        return labels

    def describe(self) -> str:
        """A one-line summary for reports."""
        names = " ".join(midi_to_name(m + self.capo) for m in self.open_strings)
        text = f"{self.tuning_name} ({names})"
        if self.capo:
            text += f", capo {self.capo}"
        return text
