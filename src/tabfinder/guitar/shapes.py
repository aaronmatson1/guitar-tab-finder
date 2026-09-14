"""The shapes guitarists actually use.

A generated voicing can be technically correct and still not be what anybody
plays. This module holds the standard vocabulary: the movable barre forms
(E-shape, A-shape, D-shape) and the open-position chords, so common chords come
out looking familiar. Anything outside this vocabulary falls back to the
generator in :mod:`tabfinder.guitar.voicings`.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..theory.chords import Chord, QUALITY_BY_NAME
from .fretboard import Fretboard

Shape = Tuple[Optional[int], ...]

#: Interval pattern of standard tuning, low string to high.
STANDARD_INTERVALS = (5, 5, 5, 4, 5)

#: Movable forms, keyed by (quality name, which string carries the root).
#: Frets are relative to the form's own lowest position.
MOVABLE_SHAPES: Dict[Tuple[str, int], Shape] = {
    # Root on the 6th string (E shapes).
    ("major", 0): (0, 2, 2, 1, 0, 0),
    ("minor", 0): (0, 2, 2, 0, 0, 0),
    ("dominant 7th", 0): (0, 2, 0, 1, 0, 0),
    ("minor 7th", 0): (0, 2, 0, 0, 0, 0),
    ("major 7th", 0): (0, 2, 1, 1, 0, 0),
    ("suspended 4th", 0): (0, 2, 2, 2, 0, 0),
    ("suspended 2nd", 0): (0, 2, 4, 4, 0, 0),
    ("minor 6th", 0): (0, 2, 2, 0, 2, 0),
    ("6th", 0): (0, 2, 2, 1, 2, 0),
    ("power chord", 0): (0, 2, 2, None, None, None),
    # Root on the 5th string (A shapes).
    ("major", 1): (None, 0, 2, 2, 2, 0),
    ("minor", 1): (None, 0, 2, 2, 1, 0),
    ("dominant 7th", 1): (None, 0, 2, 0, 2, 0),
    ("minor 7th", 1): (None, 0, 2, 0, 1, 0),
    ("major 7th", 1): (None, 0, 2, 1, 2, 0),
    ("half-diminished", 1): (None, 0, 1, 0, 1, None),
    ("suspended 4th", 1): (None, 0, 2, 2, 3, 0),
    ("suspended 2nd", 1): (None, 0, 2, 2, 0, 0),
    ("6th", 1): (None, 0, 2, 2, 2, 2),
    ("minor 6th", 1): (None, 0, 2, 2, 1, 2),
    ("power chord", 1): (None, 0, 2, 2, None, None),
    # Root on the 4th string (D shapes).
    ("major", 2): (None, None, 0, 2, 3, 2),
    ("minor", 2): (None, None, 0, 2, 3, 1),
    ("dominant 7th", 2): (None, None, 0, 2, 1, 2),
    ("minor 7th", 2): (None, None, 0, 2, 1, 1),
    ("major 7th", 2): (None, None, 0, 2, 2, 2),
    ("suspended 4th", 2): (None, None, 0, 2, 3, 3),
    ("suspended 2nd", 2): (None, None, 0, 2, 3, 0),
    ("diminished", 2): (None, None, 0, 1, 3, 1),
    ("power chord", 2): (None, None, 0, 2, 3, None),
}

#: Open-position chords that no movable form produces. Frets are absolute,
#: assuming standard tuning at the nut.
OPEN_SHAPES: Dict[str, List[Shape]] = {
    "C": [(None, 3, 2, 0, 1, 0)],
    "C7": [(None, 3, 2, 3, 1, 0)],
    "Cmaj7": [(None, 3, 2, 0, 0, 0)],
    "Cadd9": [(None, 3, 2, 0, 3, 0)],
    "C5": [(None, 3, 5, 5, None, None)],
    "G": [(3, 2, 0, 0, 0, 3), (3, 2, 0, 0, 3, 3)],
    "G7": [(3, 2, 0, 0, 0, 1)],
    "Gmaj7": [(3, 2, 0, 0, 0, 2)],
    "G5": [(3, 5, 5, None, None, None)],
    "D": [(None, None, 0, 2, 3, 2)],
    "Dsus2": [(None, None, 0, 2, 3, 0)],
    "Dsus4": [(None, None, 0, 2, 3, 3)],
    "D7": [(None, None, 0, 2, 1, 2)],
    "Dmaj7": [(None, None, 0, 2, 2, 2)],
    "E": [(0, 2, 2, 1, 0, 0)],
    "Em": [(0, 2, 2, 0, 0, 0)],
    "Em7": [(0, 2, 0, 0, 0, 0)],
    "Esus4": [(0, 2, 2, 2, 0, 0)],
    "E7": [(0, 2, 0, 1, 0, 0)],
    "A": [(None, 0, 2, 2, 2, 0)],
    "Am": [(None, 0, 2, 2, 1, 0)],
    "Am7": [(None, 0, 2, 0, 1, 0)],
    "Amaj7": [(None, 0, 2, 1, 2, 0)],
    "Asus2": [(None, 0, 2, 2, 0, 0)],
    "Asus4": [(None, 0, 2, 2, 3, 0)],
    "F": [(1, 3, 3, 2, 1, 1), (None, None, 3, 2, 1, 1)],
    "Fmaj7": [(None, None, 3, 2, 1, 0)],
    "B7": [(None, 2, 1, 2, 0, 2)],
    "Dm": [(None, None, 0, 2, 3, 1)],
    "Dm7": [(None, None, 0, 2, 1, 1)],
}

#: Slash chords common enough to be worth spelling out.
OPEN_SLASH_SHAPES: Dict[str, List[Shape]] = {
    "D/F#": [(2, None, 0, 2, 3, 2)],
    "C/G": [(3, 3, 2, 0, 1, 0)],
    "C/E": [(0, 3, 2, 0, 1, 0)],
    "G/B": [(None, 2, 0, 0, 0, 3)],
    "Am/G": [(3, 0, 2, 2, 1, 0)],
    "Em/B": [(None, 2, 2, 0, 0, 0)],
    "F/C": [(None, 3, 3, 2, 1, 1)],
}


def has_standard_intervals(board: Fretboard) -> bool:
    """True when movable shapes transpose correctly on this tuning."""
    if board.string_count != 6:
        return False
    intervals = tuple(
        board.open_strings[i + 1] - board.open_strings[i] for i in range(board.string_count - 1)
    )
    return intervals == STANDARD_INTERVALS


def _sort_key(shape: Shape) -> Tuple[int, ...]:
    """A comparable key for a shape, treating a muted string as -1."""
    return tuple(-1 if f is None else f for f in shape)


def _shift(shape: Shape, offset: int) -> Shape:
    return tuple(None if f is None else f + offset for f in shape)


def _fits(shape: Shape, board: Fretboard) -> bool:
    """Whether every fret in a shape is reachable on this neck."""
    frets = [f for f in shape if f is not None]
    if not frets:
        return False
    return all(board.capo <= f <= board.frets for f in frets)


def _produces(shape: Shape, board: Fretboard, chord: Chord) -> bool:
    """Whether a shape really sounds the chord it claims to."""
    pcs = {
        (board.open_strings[i] + f) % 12 for i, f in enumerate(shape) if f is not None
    }
    if not pcs.issubset(set(chord.pitch_classes)):
        return False
    essential = set(chord.core_pitch_classes) - set(chord.optional_pitch_classes)
    if not essential.issubset(pcs):
        return False
    sounding = [i for i, f in enumerate(shape) if f is not None]
    bass_pc = min(board.open_strings[i] + shape[i] for i in sounding) % 12
    wanted = chord.bass if chord.bass is not None else chord.root
    return bass_pc == wanted


def canonical_shapes(chord: Chord, board: Fretboard, max_position: int = 12) -> List[Shape]:
    """Standard shapes for ``chord``, nearest the nut first.

    Returns an empty list for tunings the shape vocabulary does not apply to,
    or for chords outside the common vocabulary.
    """
    if not has_standard_intervals(board):
        return []

    found: List[Tuple[int, Shape]] = []

    # Open-position chords, which only make sense with no capo behind them.
    symbol = chord.symbol(prefer_flats=False)
    alt_symbol = chord.symbol(prefer_flats=True)
    table = OPEN_SLASH_SHAPES if chord.bass is not None else OPEN_SHAPES
    for name in (symbol, alt_symbol):
        for shape in table.get(name, []):
            shifted = _shift(shape, board.capo)
            if _fits(shifted, board) and _produces(shifted, board, chord):
                frets = [f for f in shifted if f is not None]
                found.append((min(frets), shifted))

    # Movable forms, rooted on each of the bottom three strings.
    if chord.bass is None or chord.bass == chord.root:
        for (quality_name, root_string), shape in MOVABLE_SHAPES.items():
            if QUALITY_BY_NAME[quality_name] is not chord.quality:
                continue
            root_open_pc = board.open_strings[root_string] % 12
            base = (chord.root - root_open_pc - board.capo) % 12
            for offset in (base, base + 12):
                shifted = _shift(shape, offset + board.capo)
                frets = [f for f in shifted if f is not None]
                if not frets or min(frets) > max_position + board.capo:
                    continue
                if _fits(shifted, board) and _produces(shifted, board, chord):
                    found.append((min(frets), shifted))

    # Nearest the nut first, de-duplicated.
    found.sort(key=lambda item: (item[0], _sort_key(item[1])))
    out: List[Shape] = []
    for _, shape in found:
        if shape not in out:
            out.append(shape)
    return out
