"""Notes, chords, keys and roman numerals."""

from __future__ import annotations

import pytest

from tabfinder.theory.chords import (
    MAJOR,
    Chord,
    chord_template,
    detection_chords,
    parse_chord,
)
from tabfinder.theory.notes import (
    NoteParseError,
    freq_to_midi,
    midi_to_freq,
    midi_to_name,
    name_to_midi,
    note_name,
    pitch_class,
)
from tabfinder.theory.scales import (
    Key,
    identify_progression,
    progression_numerals,
    roman_numeral,
)


@pytest.mark.parametrize(
    "name,expected",
    [("C", 0), ("c", 0), ("F#", 6), ("Gb", 6), ("B#", 0), ("Cb", 11), ("Bbb", 9)],
)
def test_pitch_class(name, expected):
    assert pitch_class(name) == expected


def test_pitch_class_rejects_nonsense():
    with pytest.raises(NoteParseError):
        pitch_class("H")
    with pytest.raises(NoteParseError):
        pitch_class("")


def test_note_name_respects_accidental_preference():
    assert note_name(6) == "F#"
    assert note_name(6, prefer_flats=True) == "Gb"


@pytest.mark.parametrize("name,midi", [("E2", 40), ("A2", 45), ("C4", 60), ("A4", 69), ("E4", 64)])
def test_name_to_midi_round_trip(name, midi):
    assert name_to_midi(name) == midi
    assert name_to_midi(midi_to_name(midi)) == midi


def test_a440_anchor():
    assert midi_to_freq(69) == pytest.approx(440.0)
    assert freq_to_midi(440.0) == pytest.approx(69.0)
    assert freq_to_midi(midi_to_freq(52)) == pytest.approx(52.0)


def test_cb_sits_below_c():
    # Cb3 is a semitone under C3, not eleven above it.
    assert name_to_midi("Cb3") == name_to_midi("C3") - 1
    assert name_to_midi("B#2") == name_to_midi("C3")


@pytest.mark.parametrize(
    "symbol,root,quality_name,bass",
    [
        ("C", 0, "major", None),
        ("Am", 9, "minor", None),
        ("F#m7", 6, "minor 7th", None),
        ("Bbmaj7", 10, "major 7th", None),
        ("C/G", 0, "major", 7),
        ("Gsus4", 7, "suspended 4th", None),
        ("E5", 4, "power chord", None),
        ("Bdim", 11, "diminished", None),
    ],
)
def test_parse_chord(symbol, root, quality_name, bass):
    chord = parse_chord(symbol)
    assert chord.root == root
    assert chord.quality.name == quality_name
    assert chord.bass == bass


def test_parse_chord_rejects_unknown_quality():
    with pytest.raises(NoteParseError):
        parse_chord("Cwobble")


def test_chord_pitch_classes():
    assert set(parse_chord("C").pitch_classes) == {0, 4, 7}
    assert set(parse_chord("Am7").pitch_classes) == {9, 0, 4, 7}
    assert set(parse_chord("C/G").pitch_classes) == {0, 4, 7}
    assert set(parse_chord("D/F#").pitch_classes) == {2, 6, 9}


def test_chord_symbol_round_trips():
    for symbol in ["C", "Am", "F#m7", "Bbmaj7", "Gsus4", "C/G", "Bdim"]:
        assert parse_chord(parse_chord(symbol).symbol()).symbol() == parse_chord(symbol).symbol()


def test_chord_transposition():
    assert parse_chord("C").transposed(2).symbol() == "D"
    assert parse_chord("Am").transposed(3).symbol() == "Cm"
    assert parse_chord("C/G").transposed(5).symbol() == "F/C"


def test_chord_template_marks_chord_tones():
    template = chord_template(Chord(0, MAJOR))
    assert [i for i, v in enumerate(template) if v > 0] == [0, 4, 7]


def test_detection_chords_are_unique():
    chords = detection_chords()
    assert len(chords) == len({(c.root, c.quality.name) for c in chords})


def test_major_scale_and_diatonic_chords():
    key = Key(0, "major")
    assert key.scale_notes() == ["C", "D", "E", "F", "G", "A", "B"]
    symbols = [chord.symbol() for _, chord in key.diatonic_chords()]
    assert symbols == ["C", "Dm", "Em", "F", "G", "Am", "Bdim"]


def test_minor_scale_and_diatonic_chords():
    key = Key(9, "minor")
    assert key.scale_notes() == ["A", "B", "C", "D", "E", "F", "G"]
    symbols = [chord.symbol() for _, chord in key.diatonic_chords()]
    assert symbols == ["Am", "Bdim", "C", "Dm", "Em", "F", "G"]


def test_seventh_chords_in_major():
    symbols = [chord.symbol() for _, chord in Key(0, "major").diatonic_chords(sevenths=True)]
    assert symbols == ["Cmaj7", "Dm7", "Em7", "Fmaj7", "G7", "Am7", "Bm7b5"]


def test_flat_keys_spell_with_flats():
    assert Key(10, "major").scale_notes() == ["Bb", "C", "D", "Eb", "F", "G", "A"]
    # A minor key borrows the accidentals of its relative major.
    assert Key(7, "minor").scale_notes()[0] == "G"


def test_relative_and_parallel_keys():
    assert Key(0, "major").relative == Key(9, "minor")
    assert Key(9, "minor").relative == Key(0, "major")
    assert Key(0, "major").parallel == Key(0, "minor")


def test_pentatonic_scales():
    assert Key(0, "major").pentatonic() == ["C", "D", "E", "G", "A"]
    assert Key(9, "minor").pentatonic() == ["A", "C", "D", "E", "G"]


@pytest.mark.parametrize(
    "symbol,expected",
    [("C", "I"), ("Dm", "ii"), ("G7", "V7"), ("Am", "vi"), ("Bdim", "vii°")],
)
def test_roman_numerals_in_c_major(symbol, expected):
    assert roman_numeral(parse_chord(symbol), Key(0, "major")) == expected


def test_borrowed_chords_are_flagged():
    # Bb is not in C major, so it is marked as borrowed.
    assert roman_numeral(parse_chord("Bb"), Key(0, "major")).endswith("*")
    assert roman_numeral(parse_chord("C"), Key(0, "major")) == "I"


def test_identify_known_progressions():
    key = Key(0, "major")
    numerals = progression_numerals([parse_chord(c) for c in ["C", "G", "Am", "F"]], key)
    assert identify_progression(numerals) == "the 'four chord song' (I-V-vi-IV)"


def test_identify_progression_handles_rotation():
    key = Key(0, "major")
    numerals = progression_numerals([parse_chord(c) for c in ["Am", "F", "C", "G"]], key)
    # Same loop, started in a different place.
    assert identify_progression(numerals) is not None


def test_identify_progression_returns_none_for_unknown():
    key = Key(0, "major")
    numerals = progression_numerals([parse_chord(c) for c in ["C", "Bb", "Bdim"]], key)
    assert identify_progression(numerals) is None


def test_key_contains():
    key = Key(0, "major")
    assert key.contains(parse_chord("Dm"))
    assert not key.contains(parse_chord("D"))
