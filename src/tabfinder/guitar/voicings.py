"""Turn a chord into playable shapes on a given fretboard.

Voicings are generated rather than looked up in a table, so the tool can
handle unusual chords and alternate tunings. Each candidate is scored for
playability and musical balance; the best few are returned.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Dict, List, Optional, Sequence, Tuple

from ..theory.chords import Chord
from ..theory.notes import midi_to_name
from .fretboard import Fretboard
from .shapes import canonical_shapes

#: ``None`` in a fret tuple means the string is muted or simply not played.
FretList = Tuple[Optional[int], ...]

MAX_FINGERS = 4
MAX_SPAN = 4


@dataclass(frozen=True)
class Voicing:
    """One chord shape: a fret per string, low string first."""

    chord: Chord
    frets: FretList
    board: Fretboard
    score: float = 0.0

    @property
    def sounding(self) -> List[int]:
        """Indices of the strings that actually ring."""
        return [i for i, f in enumerate(self.frets) if f is not None]

    @property
    def midi_notes(self) -> List[int]:
        """The pitches this shape produces, low to high."""
        return [self.board.open_strings[i] + self.frets[i] for i in self.sounding]

    @property
    def pitch_classes(self) -> List[int]:
        return [m % 12 for m in self.midi_notes]

    @property
    def bass_note(self) -> Optional[int]:
        """The lowest pitch this shape sounds, whichever string carries it."""
        notes = self.midi_notes
        return min(notes) if notes else None

    @property
    def fretted(self) -> List[int]:
        """Fret numbers that need a finger (open strings excluded)."""
        return [f for f in self.frets if f is not None and f > self.board.capo]

    @property
    def min_fret(self) -> int:
        return min(self.fretted) if self.fretted else self.board.capo

    @property
    def max_fret(self) -> int:
        return max(self.fretted) if self.fretted else self.board.capo

    @property
    def span(self) -> int:
        return self.max_fret - self.min_fret if self.fretted else 0

    @property
    def is_open(self) -> bool:
        """True when the shape uses open strings and sits at the nut."""
        return any(f == self.board.capo for f in self.frets if f is not None) and self.max_fret <= self.board.capo + 4

    @property
    def barre(self) -> Optional[int]:
        """The barred fret, if this shape needs one."""
        return _barre_fret(self.frets, self.board.capo)

    @property
    def fingers(self) -> int:
        """Rough count of fretting fingers this shape needs."""
        return _finger_count(self.frets, self.board.capo)

    @property
    def difficulty(self) -> str:
        """A one-word playability label."""
        if self.barre is not None or self.fingers >= 4 or self.span >= 4:
            return "hard"
        if self.fingers <= 2 and self.span <= 2:
            return "easy"
        return "moderate"

    @property
    def missing(self) -> List[int]:
        """Chord tones this shape leaves out."""
        present = set(self.pitch_classes)
        return [pc for pc in self.chord.core_pitch_classes if pc not in present]

    def fret_string(self) -> str:
        """Compact shape notation, e.g. ``x32010`` or ``10-12-12-11-x-x``."""
        cells = ["x" if f is None else str(f) for f in self.frets]
        if all(len(c) == 1 for c in cells):
            return "".join(cells)
        return "-".join(cells)

    def note_names(self) -> List[str]:
        return [midi_to_name(m, self.chord.root in (1, 3, 5, 8, 10)) for m in self.midi_notes]

    def position_label(self) -> str:
        """Where on the neck this shape sits."""
        if not self.fretted:
            return "open"
        if self.is_open:
            return "open position"
        return f"{self.min_fret}{_ordinal_suffix(self.min_fret)} position"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.chord.symbol()} {self.fret_string()}"


def _ordinal_suffix(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _barre_fret(frets: FretList, capo: int) -> Optional[int]:
    """The fret to lay a finger flat across, if the shape needs one.

    A barre is what you reach for when one finger has to cover three or more
    strings at the same fret, or when the shape would otherwise need a fifth
    finger. Two strings at the low fret with spare fingers above — a D chord,
    say — is not a barre.
    """
    fretted = [(i, f) for i, f in enumerate(frets) if f is not None and f > capo]
    if len(fretted) < 2:
        return None
    low = min(f for _, f in fretted)
    at_low = [i for i, f in fretted if f == low]
    if len(at_low) < 2:
        return None
    # A barre cannot leave a string inside its span ringing open.
    if any(frets[i] == capo for i in range(min(at_low), max(at_low) + 1)):
        return None
    if len(at_low) >= 3 or len(fretted) > MAX_FINGERS:
        return low
    return None


def _finger_count(frets: FretList, capo: int) -> int:
    """How many fingers a shape needs, allowing for a barre."""
    fretted = [(i, f) for i, f in enumerate(frets) if f is not None and f > capo]
    if not fretted:
        return 0
    barre = _barre_fret(frets, capo)
    if barre is None:
        return len(fretted)
    # One finger covers the barred fret; each note above it takes another.
    return 1 + sum(1 for _, f in fretted if f > barre)


def _has_internal_mute(frets: FretList) -> bool:
    """True when a muted string sits between two ringing strings."""
    sounding = [i for i, f in enumerate(frets) if f is not None]
    if len(sounding) < 2:
        return False
    return any(frets[i] is None for i in range(sounding[0], sounding[-1] + 1))


def _score(voicing: Voicing, chord: Chord, board: Fretboard) -> float:
    """Lower is better. Balances playability against a full, correct sound."""
    frets = voicing.frets
    notes = voicing.midi_notes
    score = 0.0

    # Playability.
    score += voicing.min_fret * 0.55          # prefer shapes near the nut
    score += voicing.span * 1.2               # prefer compact shapes
    score += voicing.fingers * 0.8            # prefer fewer fingers
    if voicing.barre is not None:
        score += 1.6
    open_strings = sum(1 for f in frets if f == board.capo)
    score -= open_strings * 0.7               # open strings ring and are free

    # Fullness: more strings is usually a better rhythm-guitar chord.
    sounding = voicing.sounding
    score -= len(sounding) * 1.1
    # Guitarists mute from the bass side ("x32010") far more readily than from
    # the treble side, so dropping high strings costs much more.
    score += sounding[0] * 0.35 if sounding else 0.0
    score += (board.string_count - 1 - sounding[-1]) * 1.9 if sounding else 0.0
    if _has_internal_mute(frets):
        score += 2.5                          # awkward to mute mid-chord

    # Harmony.
    for pc in voicing.missing:
        score += 4.0 if pc in (chord.root, (chord.root + chord.quality.intervals[1]) % 12) else 1.5
    bass_pc = min(notes) % 12 if notes else None
    wanted_bass = chord.bass if chord.bass is not None else chord.root
    if bass_pc != wanted_bass:
        # An accidental inversion changes the chord's character; only accept one
        # when nothing rooted is playable.
        score += 9.0 if chord.bass is not None else 6.0
    # A doubled root or fifth low down sounds solid; a doubled third muddies.
    third = (chord.root + chord.quality.intervals[1]) % 12 if len(chord.quality.intervals) > 1 else None
    if third is not None and [m % 12 for m in notes].count(third) > 1:
        score += 0.6
    # Voices should not be bunched into a narrow band at the top of the neck.
    if notes:
        score += max(0, (min(notes) - 52)) * 0.05

    return score


def _candidate_frets(board: Fretboard, chord: Chord, string: int, base: int) -> List[Optional[int]]:
    """Fret options for one string within a hand position (plus open/mute)."""
    allowed = set(chord.pitch_classes)
    options: List[Optional[int]] = [None]
    open_fret = board.capo
    if (board.open_strings[string] + open_fret) % 12 in allowed:
        options.append(open_fret)
    for fret in range(max(base, board.capo), min(base + MAX_SPAN, board.frets) + 1):
        if fret == open_fret:
            continue
        if (board.open_strings[string] + fret) % 12 in allowed:
            options.append(fret)
    return options


def generate_voicings(
    chord: Chord,
    board: Optional[Fretboard] = None,
    limit: int = 4,
    max_base_fret: int = 12,
    require_full: bool = True,
    prefer_canonical: bool = True,
) -> List[Voicing]:
    """Return the best playable shapes for ``chord``, easiest first.

    Standard guitar shapes are offered first so common chords look the way a
    player expects; anything outside that vocabulary is worked out from the
    fretboard. ``require_full`` insists that every chord tone is present,
    except the ones the quality marks optional (typically the fifth of a
    seventh chord).
    """
    board = board or Fretboard.from_tuning()

    known: List[Voicing] = []
    if prefer_canonical:
        for shape in canonical_shapes(chord, board, max_position=max_base_fret):
            voicing = Voicing(chord, shape, board)
            object.__setattr__(voicing, "score", _score(voicing, chord, board))
            known.append(voicing)
        if len(known) >= limit:
            return _spread(known, limit)

    core = set(chord.core_pitch_classes)
    optional = set(chord.optional_pitch_classes)
    essential = core - optional
    min_strings = 2 if len(core) <= 2 else 3

    seen: Dict[FretList, Voicing] = {}
    for base in range(board.capo, min(max_base_fret, board.frets - MAX_SPAN) + 1):
        options = [_candidate_frets(board, chord, s, base) for s in range(board.string_count)]
        for combo in product(*options):
            frets: FretList = tuple(combo)
            if frets in seen:
                continue
            sounding = [i for i, f in enumerate(frets) if f is not None]
            if len(sounding) < min_strings:
                continue
            fretted = [f for f in frets if f is not None and f > board.capo]
            if fretted and max(fretted) - min(fretted) > MAX_SPAN:
                continue
            if _finger_count(frets, board.capo) > MAX_FINGERS:
                continue
            pcs = {(board.open_strings[i] + frets[i]) % 12 for i in sounding}
            if require_full and not essential.issubset(pcs):
                continue
            if not require_full and not pcs:
                continue
            voicing = Voicing(chord, frets, board)
            object.__setattr__(voicing, "score", _score(voicing, chord, board))
            seen[frets] = voicing

    if not seen and require_full:
        # Nothing complete fits — fall back to partial shapes rather than fail.
        return generate_voicings(chord, board, limit, max_base_fret, require_full=False)

    for voicing in known:
        seen.pop(voicing.frets, None)
    ranked = sorted(seen.values(), key=lambda v: (v.score, v.min_fret, v.fret_string()))
    return (known + _diversify(ranked, limit))[:limit] if known else _diversify(ranked, limit)


def _spread(voicings: Sequence[Voicing], limit: int) -> List[Voicing]:
    """Keep shapes that sit in genuinely different hand positions."""
    chosen: List[Voicing] = []
    for voicing in voicings:
        if len(chosen) >= limit:
            break
        if any(v.min_fret == voicing.min_fret and v.frets != voicing.frets for v in chosen):
            continue
        chosen.append(voicing)
    return chosen[:limit]


def _diversify(ranked: Sequence[Voicing], limit: int) -> List[Voicing]:
    """Pick the top shapes, spreading them out along the neck."""
    chosen: List[Voicing] = []
    for voicing in ranked:
        if len(chosen) >= limit:
            break
        # Skip shapes that sit in the same hand position as one already chosen,
        # so the user gets real alternatives instead of near-duplicates.
        if any(abs(v.min_fret - voicing.min_fret) < 2 for v in chosen):
            continue
        chosen.append(voicing)
    if len(chosen) < limit:
        for voicing in ranked:
            if voicing not in chosen:
                chosen.append(voicing)
            if len(chosen) >= limit:
                break
    return chosen[:limit]


def best_voicing(chord: Chord, board: Optional[Fretboard] = None) -> Optional[Voicing]:
    """The single most playable shape for a chord, or ``None`` if impossible."""
    shapes = generate_voicings(chord, board, limit=1)
    return shapes[0] if shapes else None
