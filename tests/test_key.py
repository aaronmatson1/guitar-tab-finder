"""Key detection."""

from __future__ import annotations

import pytest

from tabfinder.analysis.key import (
    combine_estimates,
    estimate_key_from_chords,
    estimate_key_from_profile,
)
from tabfinder.theory.chords import parse_chord
from tabfinder.theory.scales import Key


def profile_for(pitch_classes, weights=None):
    profile = [0.0] * 12
    for index, pc in enumerate(pitch_classes):
        profile[pc] = weights[index] if weights else 1.0
    return profile


def test_c_major_scale_reads_as_c_major():
    profile = profile_for([0, 2, 4, 5, 7, 9, 11], [6, 2, 3, 2, 4, 3, 2])
    assert estimate_key_from_profile(profile).key == Key(0, "major")


def test_transposing_the_profile_transposes_the_key():
    base = profile_for([0, 2, 4, 5, 7, 9, 11], [6, 2, 3, 2, 4, 3, 2])
    for shift in range(12):
        rotated = [base[(i - shift) % 12] for i in range(12)]
        assert estimate_key_from_profile(rotated).key == Key(shift, "major")


def test_profile_must_have_twelve_bins():
    with pytest.raises(ValueError):
        estimate_key_from_profile([1.0] * 11)


def test_all_keys_are_ranked():
    estimate = estimate_key_from_profile([1.0] * 12)
    assert len(estimate.candidates) == 24


@pytest.mark.parametrize(
    "progression,expected",
    [
        (["C", "G", "Am", "F"], Key(0, "major")),
        (["G", "D", "Em", "C"], Key(7, "major")),
        (["Am", "Dm", "E", "Am"], Key(9, "minor")),
        (["Dm", "Gm", "A", "Dm"], Key(2, "minor")),
        (["E", "A", "B", "E"], Key(4, "major")),
    ],
)
def test_key_from_chords(progression, expected):
    chords = [parse_chord(symbol) for symbol in progression]
    assert estimate_key_from_chords(chords).key == expected


def test_cadence_breaks_the_relative_key_tie():
    # The same four chords, resolving to different tonics.
    major = estimate_key_from_chords([parse_chord(c) for c in ["C", "F", "G", "C"]])
    minor = estimate_key_from_chords([parse_chord(c) for c in ["Am", "Dm", "Em", "Am"]])
    assert major.key == Key(0, "major")
    assert minor.key == Key(9, "minor")


def test_confidence_ignores_the_relative_key():
    # C major and A minor share every note, so A minor placing a close second
    # should not be read as the answer being uncertain.
    estimate = estimate_key_from_profile(profile_for([0, 2, 4, 5, 7, 9, 11], [6, 2, 3, 2, 4, 3, 2]))
    assert estimate.key == Key(0, "major")
    assert estimate.candidates[1].key == Key(9, "minor")  # the relative minor
    lead_over_relative = estimate.correlation - estimate.candidates[1].correlation
    # Confidence is measured against the next *distinct* key, not the relative.
    assert estimate.confidence > lead_over_relative * 2.5 - 1e-9
    assert estimate.confidence > 0.5


def test_ambiguous_progressions_report_low_confidence():
    clear = estimate_key_from_chords([parse_chord(c) for c in ["C", "F", "G", "C"]])
    murky = estimate_key_from_chords([parse_chord(c) for c in ["Am", "F", "C", "G"]])
    assert murky.confidence < clear.confidence


def test_durations_weight_the_estimate():
    chords = [parse_chord(c) for c in ["C", "F#"]]
    # With F# barely sounding, the key should still read as C major.
    assert estimate_key_from_chords(chords, [30.0, 0.5]).key.tonic == 0


def test_empty_chords_are_rejected():
    with pytest.raises(ValueError):
        estimate_key_from_chords([])


def test_combine_prefers_agreement():
    audio = estimate_key_from_profile(profile_for([0, 2, 4, 5, 7, 9, 11]))
    chords = estimate_key_from_chords([parse_chord(c) for c in ["C", "F", "G", "C"]])
    combined = combine_estimates(audio, chords)
    assert combined.key == Key(0, "major")
    assert len(combined.candidates) == 24


def test_combine_without_chords_passes_audio_through():
    audio = estimate_key_from_profile(profile_for([0, 2, 4, 5, 7, 9, 11]))
    assert combine_estimates(audio, None) is audio
