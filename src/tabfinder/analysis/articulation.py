"""Read guitar technique out of a pitch contour.

A list of note names is not a guitar tab. What makes tab readable is the
technique between the notes: that the player bent into a note rather than
fretting it, slid up to it, hammered on, let it ring with vibrato. All of that
lives in how the pitch moves, which is exactly what quantising to a list of
notes throws away.

Everything here reads the continuous pitch contour from
:func:`tabfinder.analysis.melody.pitch_contour` plus the loudness envelope, and
decides between:

===  ==========  ==================================================
``b``  bend        the pitch rises within one note and holds there
``~``  vibrato     the pitch oscillates around one note
``/``  slide up    the pitch glides into the next note
``\\``  slide down  the same, going down
``h``  hammer-on   the next note sounds without being picked, going up
``p``  pull-off    the same, going down
===  ==========  ==================================================

How well each of these works differs, and it is worth knowing which is which:
bends, slides and vibrato are read straight off the pitch contour and are
reliable. Hammer-ons and pull-offs depend on telling a picked note from an
unpicked one by loudness alone, which is a much weaker signal, so they are
detected conservatively and will be under-reported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .audio import AudioClip, require_audio
from .melody import PitchContour, pitch_contour

#: A pitch move of at least this many semitones is going somewhere.
MIN_MOVE_SEMITONES = 1.2

#: Beyond this, a continuous rise is a slide - nobody bends this far.
SLIDE_SEMITONES = 2.6

#: A move completed faster than this is a slide rather than a bend.
FAST_GLIDE_SECONDS = 0.12

#: Pitch steps faster than a glide, with stable ground either side, are legato.
STEP_SEMITONES = 0.7

#: Frame-to-frame movement below this counts as holding a pitch steady.
STEADY_SEMITONES = 0.3

#: Vibrato sits in this range; slower reads as a bend, faster as noise.
VIBRATO_RATE_HZ = (3.5, 9.5)
MIN_VIBRATO_DEPTH = 0.22

#: Hammer-ons and pull-offs only span a reachable stretch.
MAX_LEGATO_SEMITONES = 5

#: Energy must actually fall across a note boundary for it to read as legato.
#: Set below 1.0 deliberately: a missed hammer-on just shows two picked notes,
#: which still plays correctly, while a false one asks for the impossible.
LEGATO_ENERGY_RATIO = 0.9

#: The most a note can be separated from the next and still be tied to it.
MAX_LEGATO_GAP = 0.12

#: An onset only starts a new note if the energy actually rises with it.
#: Spectral-flux onset detection fires inside sustained notes - vibrato and
#: bends both move the spectrum - and those are not new notes.
REPICK_ENERGY_RATIO = 1.02

RMS_HOP = 256


@dataclass
class SoloNote:
    """A note in a solo, with the technique used to play it."""

    midi: int
    start: float
    end: float
    bend: int = 0                 # semitones bent up from the fretted pitch
    vibrato: bool = False
    link: Optional[str] = None    # how this note joins the next: h p / \\
    confidence: float = 1.0

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def legato(self) -> bool:
        """True when this note ties into the next on the same string."""
        return self.link in ("h", "p", "/", "\\")

    def annotate(self, fret: int) -> str:
        """The text for this note in a tab column, e.g. ``7b9~/``."""
        text = str(fret)
        if self.bend:
            text += f"b{fret + self.bend}"
        if self.vibrato:
            text += "~"
        if self.link:
            text += self.link
        return text

    def techniques(self) -> List[str]:
        """Plain-English names of what is going on, for a legend."""
        out: List[str] = []
        if self.bend:
            out.append(f"bend up {self.bend} semitone{'s' if self.bend > 1 else ''}")
        if self.vibrato:
            out.append("vibrato")
        name = {
            "h": "hammer-on", "p": "pull-off", "/": "slide up", "\\": "slide down"
        }.get(self.link or "", "")
        if name:
            out.append(name)
        return out


def transcribe_with_technique(
    clip: AudioClip,
    contour: Optional[PitchContour] = None,
    min_duration: float = 0.09,
    key=None,
) -> List[SoloNote]:
    """Transcribe a solo, keeping the technique as well as the notes.

    Notes are cut at picked onsets and at abrupt pitch steps, never at gradual
    pitch movement - a bend and a slide *are* pitch movement within a note, and
    segmenting on every semitone change is what destroys them.
    """
    librosa, np = require_audio()
    contour = contour or pitch_contour(clip)
    onsets = librosa.onset.onset_detect(
        y=clip.samples, sr=clip.sample_rate, units="time", backtrack=False
    )
    energy = _energy_envelope(librosa, np, clip)

    notes: List[SoloNote] = []
    for first, last in _segments(np, contour, onsets, min_duration, energy):
        notes.extend(_analyse_segment(np, contour, first, last))

    notes = [note for note in notes if note.duration >= min_duration]
    notes = _absorb_transitions(notes, min_duration)
    _link(np, energy, notes)
    if key is not None:
        notes = snap_to_key(notes, key)
    return notes


# --- cutting the contour into notes --------------------------------------


def _voiced_runs(np, contour: PitchContour) -> List[Tuple[int, int]]:
    """Stretches of consecutive frames where a pitch was actually tracked."""
    usable = np.asarray(contour.voiced) & np.isfinite(contour.midi)
    runs: List[Tuple[int, int]] = []
    start: Optional[int] = None
    for index, active in enumerate(usable):
        if active and start is None:
            start = index
        elif not active and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(usable) - 1))
    return runs


def _segments(np, contour: PitchContour, onsets, min_duration: float,
              energy=None) -> List[Tuple[int, int]]:
    """Cut the contour into notes at picks, silences and abrupt pitch steps."""
    times = contour.times
    hop = float(times[1] - times[0]) if len(times) > 1 else 0.01
    min_frames = max(2, int(min_duration / hop))

    segments: List[Tuple[int, int]] = []
    for first, last in _voiced_runs(np, contour):
        cuts = {first, last + 1}
        for onset in np.asarray(onsets):          # a pick starts a new note
            if not times[first] < onset <= times[last]:
                continue
            # ...but only if it was really struck. Vibrato and bends move the
            # spectrum enough to trip the onset detector without a new note.
            if energy is not None and _attack_ratio(np, energy, float(onset)) < REPICK_ENERGY_RATIO:
                continue
            cuts.add(int(np.argmin(np.abs(times - onset))))
        cuts.update(_step_indices(np, contour.midi, first, last))

        ordered = sorted(c for c in cuts if first <= c <= last + 1)
        for low, high in zip(ordered, ordered[1:]):
            if high - low >= min_frames:
                segments.append((low, high - 1))
    return segments


def _step_indices(np, midi, first: int, last: int) -> List[int]:
    """Frames where the pitch jumps rather than glides.

    A hammer-on is one big change with the pitch sitting still either side. A
    slide is a *run* of big changes. Only the first is a note boundary, so the
    neighbouring frames must be steady for a jump to count.
    """
    steps: List[int] = []
    width = 3
    deltas = np.abs(np.diff(midi))
    for index in range(first + width, last - width + 1):
        before = float(np.median(midi[index - width : index]))
        after = float(np.median(midi[index : index + width]))
        if abs(after - before) < STEP_SEMITONES:
            continue
        if index - 2 < 0 or index + 1 >= len(deltas):
            continue
        approach = float(np.max(deltas[max(0, index - width) : index - 1]))
        departure = float(np.max(deltas[index + 1 : index + width]))
        if approach > STEADY_SEMITONES or departure > STEADY_SEMITONES:
            continue
        steps.append(index)

    collapsed: List[int] = []
    for step in steps:
        if not collapsed or step - collapsed[-1] > width:
            collapsed.append(step)
    return collapsed


# --- reading one note ----------------------------------------------------


def _analyse_segment(np, contour: PitchContour, first: int, last: int) -> List[SoloNote]:
    """Read one note: its fretted pitch, and any bend or slide inside it."""
    midi = contour.midi[first : last + 1]
    times = contour.times
    if midi.size == 0:
        return []
    start = float(times[first])
    end = float(times[min(last + 1, len(times) - 1)])
    confidence = float(np.mean(contour.confidence[first : last + 1]))

    tail_len = max(2, int(midi.size * 0.3))
    head_len = max(2, int(midi.size * 0.3))

    # How far the pitch travelled, measured from the extremes it actually
    # reached rather than from its opening and closing medians: a bend that
    # starts rising immediately gives a borderline median difference, which
    # used to read as a plain note pitched halfway through the bend.
    low = float(np.percentile(midi, 8))
    high = float(np.percentile(midi, 92))
    direction = float(np.median(midi[-tail_len:]) - np.median(midi[:head_len]))
    base_pitch, target_pitch = (low, high) if direction >= 0 else (high, low)
    move = target_pitch - base_pitch if (high - low) >= MIN_MOVE_SEMITONES else 0.0
    if move == 0.0:
        base_pitch = target_pitch = float(np.median(midi))
    base = int(round(base_pitch))

    if move == 0.0:
        return [
            SoloNote(
                midi=base, start=start, end=end,
                vibrato=_detect_vibrato(np, midi, end - start),
                confidence=confidence,
            )
        ]

    # Something moved. How far and how fast says whether it was bent or slid.
    glide_seconds = _glide_duration(np, contour, first, last, base_pitch, target_pitch)
    is_slide = abs(move) >= SLIDE_SEMITONES or glide_seconds < FAST_GLIDE_SECONDS

    if not is_slide:
        return [
            SoloNote(
                midi=base, start=start, end=end, bend=int(round(move)),
                vibrato=_detect_vibrato(np, midi[-tail_len:], end - start),
                confidence=confidence,
            )
        ]

    split = start + max(0.02, (end - start) * 0.45)
    return [
        SoloNote(midi=base, start=start, end=split,
                 link="/" if move > 0 else "\\", confidence=confidence),
        SoloNote(midi=int(round(target_pitch)), start=split, end=end,
                 vibrato=_detect_vibrato(np, midi[-tail_len:], end - split),
                 confidence=confidence),
    ]


def _glide_duration(np, contour: PitchContour, first: int, last: int,
                    low_pitch: float, high_pitch: float) -> float:
    """How long the pitch spent travelling between two levels."""
    times = contour.times
    hop = float(times[1] - times[0]) if len(times) > 1 else 0.01
    midi = contour.midi[first : last + 1]
    low, high = min(low_pitch, high_pitch), max(low_pitch, high_pitch)
    travelling = np.sum((midi > low + 0.3) & (midi < high - 0.3))
    return float(travelling) * hop


def _detect_vibrato(np, segment, duration: float) -> bool:
    """Vibrato is a periodic wobble around one pitch, not a drift off it."""
    if segment.size < 8 or duration < 0.2:
        return False
    centred = segment - float(np.mean(segment))
    depth = float(np.max(centred) - np.min(centred))
    if depth < MIN_VIBRATO_DEPTH or depth > 2.0:
        return False
    crossings = int(np.sum(np.diff(np.signbit(centred)) != 0))
    if crossings < 3:
        return False
    rate = crossings / (2.0 * duration)
    return VIBRATO_RATE_HZ[0] <= rate <= VIBRATO_RATE_HZ[1]


def _absorb_transitions(notes: List[SoloNote], min_duration: float) -> List[SoloNote]:
    """Fold stray fragments back into the note they belong to."""
    if len(notes) < 2:
        return notes
    out: List[SoloNote] = []
    for note in notes:
        previous = out[-1] if out else None
        fragment = (
            previous is not None
            and note.duration < min_duration * 2.0
            and not previous.link
            and abs(note.midi - previous.midi) <= 2
            and note.start - previous.end <= 0.05
        )
        same_note = (
            previous is not None
            and note.midi == previous.midi
            and not previous.link
            and note.start - previous.end <= 0.05
        )
        if fragment or same_note:
            previous.end = note.end
            previous.link = note.link
            previous.vibrato = previous.vibrato or note.vibrato
            previous.bend = previous.bend or note.bend
            continue
        out.append(note)
    return out


# --- joining notes -------------------------------------------------------


def _energy_envelope(librosa, np, clip: AudioClip):
    """Loudness over time, as ``(times, rms)``.

    Spectral-flux onset detection is no help here: changing pitch produces a
    large flux whether or not the string was picked, so a hammer-on looks
    exactly like a pluck. What separates them is the amplitude transient - a
    pick jumps the energy, a hammer-on lets it carry on decaying.
    """
    rms = librosa.feature.rms(y=clip.samples, hop_length=RMS_HOP)[0]
    return librosa.times_like(rms, sr=clip.sample_rate, hop_length=RMS_HOP), rms


def _attack_ratio(np, envelope, when: float) -> float:
    """How much louder a moment is than the instant before it."""
    times, rms = envelope
    if len(times) == 0:
        return 1.0
    index = int(np.argmin(np.abs(times - when)))
    before = rms[max(0, index - 9) : max(1, index)]
    after = rms[index : index + 6]
    if before.size == 0 or after.size == 0:
        return 1.0
    return float(np.max(after)) / max(float(np.max(before)), 1e-9)


def _link(np, envelope, notes: List[SoloNote]) -> None:
    """Join notes the fretting hand sounded without the pick."""
    for index in range(len(notes) - 1):
        current, following = notes[index], notes[index + 1]
        if current.link:  # a slide already decided this
            continue
        interval = following.midi - current.midi
        if interval == 0 or abs(interval) > MAX_LEGATO_SEMITONES:
            continue
        if following.start - current.end > MAX_LEGATO_GAP:
            continue
        if _attack_ratio(np, envelope, following.start) >= LEGATO_ENERGY_RATIO:
            continue  # loud enough to have been picked
        current.link = "h" if interval > 0 else "p"


# --- tidying against the key ---------------------------------------------


def snap_to_key(notes: Sequence[SoloNote], key, tolerance: float = 0.6) -> List[SoloNote]:
    """Nudge weakly-tracked notes onto the key's scale.

    Pitch tracking slips by a semitone now and then, usually on short or quiet
    notes. Solos mostly stay inside the key's pentatonic or blues scale, so a
    low-confidence note a semitone off a scale tone is far more likely to be a
    tracking error than a deliberate chromatic one. Confident notes and bends
    are never touched - blue notes are the whole point of a solo.
    """
    if key is None:
        return list(notes)
    allowed = set(key.scale)
    blues_root = key.tonic if key.mode == "minor" else (key.tonic + 9) % 12
    allowed |= {(blues_root + step) % 12 for step in (0, 3, 5, 6, 7, 10)}

    out: List[SoloNote] = []
    for note in notes:
        if note.midi % 12 in allowed or note.confidence >= tolerance or note.bend:
            out.append(note)
            continue
        out.append(
            SoloNote(
                midi=_nearest_in(note.midi, allowed),
                start=note.start, end=note.end, bend=note.bend,
                vibrato=note.vibrato, link=note.link, confidence=note.confidence,
            )
        )
    return out


def _nearest_in(midi: int, allowed: set) -> int:
    """The closest pitch to ``midi`` whose pitch class is in ``allowed``."""
    for distance in (1, 2):
        for direction in (-1, 1):
            candidate = midi + direction * distance
            if candidate % 12 in allowed:
                return candidate
    return midi


def technique_legend(notes: Sequence[SoloNote]) -> List[str]:
    """Explain only the symbols that actually appear in this solo."""
    symbols = [
        ("b", "bend up to the pitch shown"),
        ("~", "vibrato"),
        ("h", "hammer-on"),
        ("p", "pull-off"),
        ("/", "slide up"),
        ("\\", "slide down"),
    ]
    used = set()
    for note in notes:
        if note.bend:
            used.add("b")
        if note.vibrato:
            used.add("~")
        if note.link:
            used.add(note.link)
    return [f"  {symbol}   {meaning}" for symbol, meaning in symbols if symbol in used]
