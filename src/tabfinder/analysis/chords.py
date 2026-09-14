"""Recognise chords in audio.

The pipeline is the standard one: separate the harmonic content, fold it into
a beat-synchronous chroma (how much of each of the twelve pitch classes is
sounding), match every beat against a bank of chord templates, then smooth the
result with Viterbi decoding so the output changes chord only when the audio
really does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from ..theory.chords import Chord, detection_chords
from .audio import AudioClip, require_audio


#: Above this, a beat's chroma energy is concentrated in too few pitch classes
#: for anything polyphonic to be sounding - a solo or an unaccompanied line.
#: Measured at ~0.75 for a monophonic passage against ~0.43 for strummed chords.
MONOPHONIC_CONCENTRATION = 0.60


@dataclass
class ChordSegment:
    """One chord, and the stretch of the song where it sounds."""

    chord: Chord
    start: float
    end: float
    confidence: float = 0.0
    beats: int = 1
    #: True when only one note at a time was sounding, so the chord label here
    #: is whatever the single notes happened to imply rather than a real chord.
    monophonic: bool = False
    #: How many of this segment's beats looked monophonic, used to decide it.
    mono_beats: int = 0

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def symbol(self) -> str:
        return self.chord.symbol()

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.symbol} ({self.start:.1f}-{self.end:.1f}s)"


@dataclass
class BeatGrid:
    """Where the beats and bars fall."""

    tempo: float
    beat_times: List[float]
    beats_per_bar: int = 4

    @property
    def beat_count(self) -> int:
        return len(self.beat_times)

    def bar_of(self, time: float) -> int:
        """Which bar a timestamp falls in, counting from 1."""
        index = sum(1 for t in self.beat_times if t <= time + 1e-6) - 1
        return max(0, index) // self.beats_per_bar + 1


def _templates(np) -> Tuple[List[Chord], "object"]:
    """Build the L2-normalised template bank the matcher scores against."""
    chords = detection_chords()
    matrix = np.zeros((len(chords), 12), dtype=float)
    for row, chord in enumerate(chords):
        for position, interval in enumerate(chord.quality.intervals):
            pc = (chord.root + interval) % 12
            # The root and fifth dominate what a chroma actually shows, and the
            # third is what distinguishes major from minor, so weight it up.
            if position == 0:
                weight = 1.0
            elif interval in (3, 4):
                weight = 0.9
            elif interval == 7:
                weight = 0.75
            else:
                weight = 0.6
            matrix[row, pc] = max(matrix[row, pc], weight)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return chords, matrix / norms


def beat_track(clip: AudioClip, beats_per_bar: int = 4) -> BeatGrid:
    """Find the tempo and the beat positions."""
    librosa, np = require_audio()
    tempo, beats = librosa.beat.beat_track(
        y=clip.samples, sr=clip.sample_rate, units="time", trim=False
    )
    tempo_value = float(np.atleast_1d(tempo)[0])
    times = [float(t) for t in np.atleast_1d(beats)]
    if len(times) < 2:
        # Percussion-free recordings can defeat the beat tracker; fall back to
        # a steady grid so the rest of the analysis still has something to use.
        step = 60.0 / (tempo_value if tempo_value > 0 else 120.0)
        count = max(2, int(clip.duration / step))
        times = [i * step for i in range(count)]
    return BeatGrid(tempo=tempo_value, beat_times=times, beats_per_bar=beats_per_bar)


def beat_chroma(clip: AudioClip, grid: BeatGrid, harmonic: bool = True):
    """A 12 x n_beats chroma matrix, one column per beat."""
    librosa, np = require_audio()
    signal = clip.samples
    if harmonic:
        # Drop the percussive layer: drums smear energy across all twelve bins.
        signal = librosa.effects.harmonic(signal)
    chroma = librosa.feature.chroma_cqt(y=signal, sr=clip.sample_rate, bins_per_octave=36)
    frames = librosa.time_to_frames(grid.beat_times, sr=clip.sample_rate)
    frames = np.clip(frames, 0, chroma.shape[1] - 1)
    synced = librosa.util.sync(chroma, frames, aggregate=np.median)
    return synced


def _viterbi(scores, np, sharpness: float = 20.0, change_penalty: float = 3.0):
    """Pick the most likely chord path, penalising needless chord changes.

    Template similarities all sit fairly close together (a wrong chord still
    shares notes with the right one), so ``sharpness`` exaggerates the gaps
    before decoding and ``change_penalty`` is the cost, in the same units, of
    switching chord between beats. Raise it for steadier output, lower it to
    catch quick changes.

    The transition matrix has only two distinct values — stay, or move to any
    other chord — so the usual O(states^2) step collapses to two maxima
    per frame.
    """
    n_states, n_frames = scores.shape
    if n_frames == 0:
        return []
    emission = sharpness * np.log(np.clip(scores, 1e-6, None))

    trellis = emission[:, 0].copy()
    back = np.zeros((n_states, n_frames), dtype=int)
    states = np.arange(n_states)

    for frame in range(1, n_frames):
        if n_states > 1:
            order = np.argpartition(trellis, -2)[-2:]
            best_idx, second_idx = (
                (int(order[1]), int(order[0]))
                if trellis[order[1]] >= trellis[order[0]]
                else (int(order[0]), int(order[1]))
            )
        else:
            best_idx = second_idx = 0
        # For each destination, the best arrival from a *different* chord comes
        # from the overall best state, unless that state is the destination.
        source = np.where(states == best_idx, second_idx, best_idx)
        jump = trellis[source] - change_penalty
        keep = trellis >= jump
        back[:, frame] = np.where(keep, states, source)
        trellis = np.where(keep, trellis, jump) + emission[:, frame]

    path = [int(np.argmax(trellis))]
    for frame in range(n_frames - 1, 0, -1):
        path.append(int(back[path[-1], frame]))
    path.reverse()
    return path


def detect_chords(
    clip: AudioClip,
    grid: Optional[BeatGrid] = None,
    change_penalty: float = 3.0,
    min_duration: float = 0.25,
) -> Tuple[List[ChordSegment], BeatGrid]:
    """Detect the chord progression of a clip, beat by beat."""
    librosa, np = require_audio()
    grid = grid or beat_track(clip)
    chroma = beat_chroma(clip, grid)
    chords, templates = _templates(np)

    # Cosine similarity between each beat's chroma and each chord template.
    columns = chroma / np.clip(np.linalg.norm(chroma, axis=0, keepdims=True), 1e-9, None)
    scores = templates @ columns  # (n_chords, n_beats)
    scores = np.clip(scores, 0.0, None)

    # How much of each beat's energy sits in its single loudest pitch class.
    # A chord spreads it; one note at a time does not.
    concentration = columns.max(axis=0) / np.clip(columns.sum(axis=0), 1e-9, None)

    path = _viterbi(scores, np, change_penalty=change_penalty)

    # Beat boundaries: the nth chroma column covers beat n to beat n+1.
    edges = list(grid.beat_times)
    if len(edges) < scores.shape[1] + 1:
        step = (edges[-1] - edges[0]) / max(1, len(edges) - 1) if len(edges) > 1 else 0.5
        while len(edges) < scores.shape[1] + 1:
            edges.append(edges[-1] + step)

    segments: List[ChordSegment] = []
    for index, state in enumerate(path):
        start, end = edges[index], edges[index + 1]
        confidence = float(scores[state, index])
        mono = bool(concentration[index] >= MONOPHONIC_CONCENTRATION)
        if segments and segments[-1].chord == chords[state]:
            segments[-1].end = end
            segments[-1].beats += 1
            segments[-1].confidence = (segments[-1].confidence + confidence) / 2
            segments[-1].mono_beats += int(mono)
            # A segment counts as monophonic when most of it was.
            segments[-1].monophonic = segments[-1].mono_beats * 2 > segments[-1].beats
        else:
            segments.append(
                ChordSegment(chords[state], start, end, confidence=confidence, beats=1,
                             monophonic=mono, mono_beats=int(mono))
            )

    return _merge_short(segments, min_duration), grid


def _merge_short(segments: List[ChordSegment], min_duration: float) -> List[ChordSegment]:
    """Absorb blink-and-you-miss-it chords into their neighbours."""
    if len(segments) <= 1:
        return segments
    out: List[ChordSegment] = []
    for segment in segments:
        if out and segment.duration < min_duration:
            out[-1].end = segment.end
            out[-1].beats += segment.beats
            out[-1].mono_beats += segment.mono_beats
            out[-1].monophonic = out[-1].mono_beats * 2 > out[-1].beats
            continue
        out.append(segment)
    # A short first chord gets folded forwards instead.
    if len(out) > 1 and out[0].duration < min_duration:
        out[1].start = out[0].start
        out[1].beats += out[0].beats
        out[1].mono_beats += out[0].mono_beats
        out[1].monophonic = out[1].mono_beats * 2 > out[1].beats
        out.pop(0)
    return out


def chord_histogram(segments: Sequence[ChordSegment]) -> List[Tuple[Chord, float]]:
    """How much total time each distinct chord holds, most used first.

    Monophonic stretches are left out: a solo over no backing produces chord
    labels that describe the notes of the line, not the harmony of the song.
    """
    totals: dict = {}
    for segment in segments:
        if segment.monophonic:
            continue
        totals[segment.chord] = totals.get(segment.chord, 0.0) + segment.duration
    if not totals:  # the whole recording was a single line; report it anyway
        for segment in segments:
            totals[segment.chord] = totals.get(segment.chord, 0.0) + segment.duration
    return sorted(totals.items(), key=lambda item: -item[1])
