"""Pitch classes, note names and MIDI/frequency conversions."""

from __future__ import annotations

import math
from typing import Optional

SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

_LETTER_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

A4_MIDI = 69
A4_HZ = 440.0

# Keys whose signatures use flats; used to pick readable accidentals.
FLAT_TONICS = {1, 3, 5, 8, 10}  # Db, Eb, F, Ab, Bb


class NoteParseError(ValueError):
    """Raised when a note or chord name cannot be understood."""


def pitch_class(name: str) -> int:
    """Return the 0-11 pitch class for a note name such as ``F#`` or ``Bbb``."""
    text = name.strip()
    if not text:
        raise NoteParseError("empty note name")
    letter = text[0].upper()
    if letter not in _LETTER_PC:
        raise NoteParseError(f"unknown note letter: {name!r}")
    pc = _LETTER_PC[letter]
    for char in text[1:]:
        if char in "#♯":
            pc += 1
        elif char in "b♭":
            pc -= 1
        else:
            raise NoteParseError(f"unexpected accidental in {name!r}: {char!r}")
    return pc % 12


def note_name(pc: int, prefer_flats: bool = False) -> str:
    """Name a pitch class, choosing sharps or flats."""
    names = FLAT_NAMES if prefer_flats else SHARP_NAMES
    return names[pc % 12]


def prefers_flats(tonic_pc: int) -> bool:
    """True when a key centred on ``tonic_pc`` reads better with flats."""
    return tonic_pc % 12 in FLAT_TONICS


def midi_to_name(midi: int, prefer_flats: bool = False) -> str:
    """Name a MIDI note with its octave, e.g. 64 -> ``E4``."""
    return f"{note_name(midi % 12, prefer_flats)}{midi // 12 - 1}"


def name_to_midi(name: str) -> int:
    """Parse a note name with octave (``E4``, ``C#3``) into a MIDI number."""
    text = name.strip()
    idx = len(text)
    while idx > 0 and (text[idx - 1].isdigit() or text[idx - 1] == "-"):
        idx -= 1
    if idx == len(text):
        raise NoteParseError(f"missing octave in {name!r}")
    pc = pitch_class(text[:idx])
    octave = int(text[idx:])
    # Re-derive the letter's own pitch class so that e.g. Cb3 lands below C3.
    natural = _LETTER_PC[text[0].upper()]
    offset = (pc - natural + 6) % 12 - 6
    return (octave + 1) * 12 + natural + offset


def midi_to_freq(midi: float) -> float:
    """Equal-tempered frequency for a (possibly fractional) MIDI number."""
    return A4_HZ * (2.0 ** ((midi - A4_MIDI) / 12.0))


def freq_to_midi(freq: float) -> float:
    """Fractional MIDI number for a frequency in Hz."""
    if freq <= 0:
        raise ValueError("frequency must be positive")
    return A4_MIDI + 12.0 * math.log2(freq / A4_HZ)


def interval_name(semitones: int) -> str:
    """Human name for an interval size in semitones (mod octave)."""
    names = [
        "unison", "minor 2nd", "major 2nd", "minor 3rd", "major 3rd",
        "perfect 4th", "tritone", "perfect 5th", "minor 6th", "major 6th",
        "minor 7th", "major 7th",
    ]
    return names[semitones % 12]


def transpose(pc: int, semitones: int) -> int:
    """Move a pitch class by ``semitones``."""
    return (pc + semitones) % 12


def parse_optional_pc(name: Optional[str]) -> Optional[int]:
    """Parse a note name that may be ``None``."""
    return None if name is None else pitch_class(name)
