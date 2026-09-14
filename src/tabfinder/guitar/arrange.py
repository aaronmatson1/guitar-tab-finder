"""Choose where on the neck to play a line.

Any note can be played in several places on a guitar. This picks the sequence
of positions that keeps the fretting hand still — the same thing a player does
by instinct — using dynamic programming over the whole phrase rather than
deciding note by note.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .fretboard import Fretboard, Position

#: Penalty weights, in arbitrary units that only matter relative to each other.
OPEN_STRING_BONUS = 1.2
HIGH_FRET_COST = 0.09
STRING_CHANGE_COST = 0.45
HAND_MOVE_COST = 1.0
STRETCH_COST = 0.6


@dataclass
class PlacedNote:
    """A note, and the string and fret chosen to play it."""

    midi: int
    string: int
    fret: int
    start: float = 0.0
    end: float = 0.0
    label: str = ""

    @property
    def is_open(self) -> bool:
        return self.fret == 0


def _transition_cost(previous: Position, current: Position, anchor: float) -> float:
    """What it costs the fretting hand to move from one position to the next."""
    cost = 0.0
    if current.fret > 0:
        # Moving the hand up or down the neck is the expensive part.
        cost += HAND_MOVE_COST * abs(current.fret - anchor) ** 0.9
    if current.string != previous.string:
        cost += STRING_CHANGE_COST * abs(current.string - previous.string) ** 0.7
    return cost


def _position_cost(position: Position) -> float:
    """The standing cost of a position, ignoring what came before it."""
    if position.fret == 0:
        return -OPEN_STRING_BONUS
    return HIGH_FRET_COST * position.fret


#: A hammer-on, pull-off or slide only works along one string, so moving
#: across strings for a tied note has to cost more than any hand movement.
TIED_STRING_PENALTY = 25.0


def arrange_notes(
    midis: Sequence[int],
    board: Optional[Fretboard] = None,
    prefer_position: Optional[int] = None,
    tied: Optional[Sequence[bool]] = None,
) -> List[Tuple[int, int]]:
    """Pick a ``(string, fret)`` for each note, keeping the hand in one place.

    Returns one pair per input note. Notes that do not exist on the neck are
    moved by whole octaves until they fit. ``tied[i]`` marks a note that must
    be played on the same string as the note before it, which is what a
    hammer-on, pull-off or slide physically requires.
    """
    board = board or Fretboard.from_tuning()
    if not midis:
        return []

    options: List[List[Position]] = []
    for midi in midis:
        positions = board.positions_for_midi(midi)
        if not positions:
            positions = board.positions_for_midi(_fold_into_range(midi, board))
        if not positions:
            raise ValueError(f"MIDI note {midi} cannot be played on this instrument")
        options.append(positions)

    # DP state: the cost of arriving at each candidate position, plus the hand
    # anchor (the fret the hand is centred on) that came with it.
    costs: List[float] = []
    anchors: List[float] = []
    for position in options[0]:
        start_cost = _position_cost(position)
        if prefer_position is not None and position.fret > 0:
            start_cost += HAND_MOVE_COST * abs(position.fret - prefer_position) * 0.5
        costs.append(start_cost)
        anchors.append(float(position.fret) if position.fret > 0 else float(prefer_position or 0))
    back: List[List[int]] = [[-1] * len(options[0])]

    for step in range(1, len(options)):
        new_costs: List[float] = []
        new_anchors: List[float] = []
        pointers: List[int] = []
        for position in options[step]:
            best_cost = float("inf")
            best_index = 0
            best_anchor = float(position.fret)
            must_tie = bool(tied[step - 1]) if tied is not None and step - 1 < len(tied) else False
            for index, previous in enumerate(options[step - 1]):
                anchor = anchors[index]
                total = costs[index] + _transition_cost(previous, position, anchor)
                if must_tie and previous.string != position.string:
                    total += TIED_STRING_PENALTY
                if total < best_cost:
                    best_cost = total
                    best_index = index
                    # The hand drifts towards wherever it is actually playing.
                    best_anchor = anchor if position.fret == 0 else 0.7 * position.fret + 0.3 * anchor
            new_costs.append(best_cost + _position_cost(position))
            new_anchors.append(best_anchor)
            pointers.append(best_index)
        costs, anchors = new_costs, new_anchors
        back.append(pointers)

    # Walk the cheapest path back to the start.
    index = min(range(len(costs)), key=lambda i: costs[i])
    chosen: List[Position] = []
    for step in range(len(options) - 1, -1, -1):
        chosen.append(options[step][index])
        index = back[step][index]
        if index < 0:
            break
    chosen.reverse()
    return [(p.string, p.fret) for p in chosen]


def _fold_into_range(midi: int, board: Fretboard) -> int:
    """Shift a note by octaves until the instrument can play it."""
    low, high = board.pitch_range()
    value = midi
    while value < low:
        value += 12
    while value > high:
        value -= 12
    return value


def place_notes(
    notes: Sequence["object"],
    board: Optional[Fretboard] = None,
    prefer_position: Optional[int] = None,
) -> List[PlacedNote]:
    """Arrange transcribed notes onto the neck, keeping their timings.

    Notes carrying a legato ``link`` are kept on one string, since that is the
    only way a hammer-on, pull-off or slide can actually be played.
    """
    board = board or Fretboard.from_tuning()
    midis = [int(getattr(note, "midi")) for note in notes]
    tied = [bool(getattr(note, "legato", False)) for note in notes]
    placements = arrange_notes(midis, board, prefer_position=prefer_position, tied=tied)
    out: List[PlacedNote] = []
    for note, (string, fret) in zip(notes, placements):
        out.append(
            PlacedNote(
                midi=int(getattr(note, "midi")),
                string=string,
                fret=fret,
                start=float(getattr(note, "start", 0.0)),
                end=float(getattr(note, "end", 0.0)),
            )
        )
    return out


def position_summary(placements: Sequence[PlacedNote]) -> str:
    """Describe where on the neck an arrangement sits."""
    frets = [p.fret for p in placements if p.fret > 0]
    if not frets:
        return "all open strings"
    low, high = min(frets), max(frets)
    if low == high:
        return f"fret {low}"
    return f"frets {low}-{high}"
