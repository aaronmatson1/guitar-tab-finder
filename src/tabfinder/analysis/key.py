"""Key detection from a pitch-class profile.

Uses the Krumhansl-Schmuckler algorithm: correlate the song's average
pitch-class distribution against the 24 major and minor key profiles and rank
the results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from ..theory.scales import KK_MAJOR, KK_MINOR, Key


@dataclass
class KeyCandidate:
    """One possible key, with the correlation that put it there."""

    key: Key
    correlation: float

    @property
    def name(self) -> str:
        return self.key.name


@dataclass
class KeyEstimate:
    """The detected key plus the runners-up."""

    candidates: List[KeyCandidate]

    @property
    def key(self) -> Key:
        return self.candidates[0].key

    @property
    def correlation(self) -> float:
        return self.candidates[0].correlation

    @property
    def confidence(self) -> float:
        """0-1 confidence, from how far the winner leads the next distinct key.

        The relative major/minor of the winner shares all of its notes, so it
        is skipped when measuring the lead.
        """
        best = self.candidates[0]
        relative = best.key.relative
        for other in self.candidates[1:]:
            if other.key == relative:
                continue
            lead = best.correlation - other.correlation
            return max(0.0, min(1.0, lead * 2.5))
        return 1.0

    @property
    def alternatives(self) -> List[KeyCandidate]:
        return self.candidates[1:]

    def top(self, n: int = 3) -> List[KeyCandidate]:
        return self.candidates[:n]


def _pearson(a: Sequence[float], b: Sequence[float]) -> float:
    """Pearson correlation between two equal-length sequences."""
    n = len(a)
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    da = [x - mean_a for x in a]
    db = [y - mean_b for y in b]
    num = sum(x * y for x, y in zip(da, db))
    den = (sum(x * x for x in da) ** 0.5) * (sum(y * y for y in db) ** 0.5)
    return num / den if den else 0.0


def estimate_key_from_profile(profile: Sequence[float]) -> KeyEstimate:
    """Rank all 24 keys against a 12-bin pitch-class profile."""
    if len(profile) != 12:
        raise ValueError(f"expected 12 pitch classes, got {len(profile)}")
    total = sum(profile)
    values = list(profile) if total <= 0 else [v / total for v in profile]

    candidates: List[KeyCandidate] = []
    for tonic in range(12):
        # Rotate the profile so the candidate tonic sits at index 0.
        rotated = [values[(tonic + i) % 12] for i in range(12)]
        candidates.append(KeyCandidate(Key(tonic, "major"), _pearson(rotated, KK_MAJOR)))
        candidates.append(KeyCandidate(Key(tonic, "minor"), _pearson(rotated, KK_MINOR)))

    candidates.sort(key=lambda c: -c.correlation)
    return KeyEstimate(candidates)


#: How strongly the first and last chord of a song argue for being the tonic.
CADENCE_BONUS = 0.10


def estimate_key_from_chords(
    chords: Sequence["object"],
    durations: Optional[Sequence[float]] = None,
    use_cadence: bool = True,
) -> KeyEstimate:
    """Estimate a key from detected chords, weighted by how long each sounds.

    Chord symbols are much cleaner evidence than raw audio, so this usually
    beats running the profile straight off the chroma. Pitch content alone
    cannot separate a key from its relative (C major and A minor use the same
    notes), so ``use_cadence`` also credits the chords a song opens and closes
    on, which is where the tonic almost always sits.
    """
    profile = [0.0] * 12
    for idx, chord in enumerate(chords):
        weight = durations[idx] if durations is not None and idx < len(durations) else 1.0
        pcs = getattr(chord, "core_pitch_classes", None)
        if pcs is None:
            continue
        for position, pc in enumerate(pcs):
            # The root carries the most weight in establishing a key.
            profile[pc % 12] += weight * (1.6 if position == 0 else 1.0)
    if sum(profile) == 0:
        raise ValueError("no chord information to estimate a key from")

    estimate = estimate_key_from_profile(profile)
    if not use_cadence or not chords:
        return estimate

    hints = _cadence_hints(chords)
    if not hints:
        return estimate
    adjusted = [
        KeyCandidate(c.key, c.correlation + hints.get((c.key.tonic, c.key.mode), 0.0))
        for c in estimate.candidates
    ]
    adjusted.sort(key=lambda c: -c.correlation)
    return KeyEstimate(adjusted)


def _cadence_hints(chords: Sequence["object"]) -> dict:
    """Bonus scores for keys whose tonic matches the first or last chord."""
    hints: dict = {}
    edges = [(chords[-1], 1.0), (chords[0], 0.7)]  # the final chord matters most
    for chord, share in edges:
        root = getattr(chord, "root", None)
        quality = getattr(chord, "quality", None)
        if root is None or quality is None:
            continue
        intervals = getattr(quality, "intervals", ())
        if len(intervals) < 2:
            continue
        mode = "minor" if intervals[1] == 3 else "major"
        token = (root % 12, mode)
        hints[token] = hints.get(token, 0.0) + CADENCE_BONUS * share
    return hints


def combine_estimates(
    audio: KeyEstimate, chords: Optional[KeyEstimate], chord_weight: float = 0.6
) -> KeyEstimate:
    """Blend a chroma-based estimate with a chord-based one."""
    if chords is None:
        return audio
    scores = {}
    for candidate in audio.candidates:
        scores[(candidate.key.tonic, candidate.key.mode)] = candidate.correlation * (1 - chord_weight)
    for candidate in chords.candidates:
        token = (candidate.key.tonic, candidate.key.mode)
        scores[token] = scores.get(token, 0.0) + candidate.correlation * chord_weight
    merged = [KeyCandidate(Key(t, m), score) for (t, m), score in scores.items()]
    merged.sort(key=lambda c: -c.correlation)
    return KeyEstimate(merged)
