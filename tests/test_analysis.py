"""End-to-end analysis, run against synthesised audio.

These need the optional audio extra; they are skipped without it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("librosa")

from tabfinder.analysis.chords import chord_histogram, detect_chords  # noqa: E402
from tabfinder.analysis.melody import quantize_to_beats, transcribe_melody  # noqa: E402
from tabfinder.analysis.pipeline import analyze_clip, suggest_capo  # noqa: E402
from tabfinder.theory.notes import name_to_midi  # noqa: E402
from tabfinder.theory.scales import Key  # noqa: E402

pytestmark = pytest.mark.audio


@pytest.fixture(scope="module")
def four_chord_analysis(request):
    """Analyse one G-D-Em-C clip and share it across the tests below."""
    np = pytest.importorskip("numpy")
    from conftest import SHAPES, synth_progression
    from tabfinder.analysis.audio import AudioClip

    names = ["G", "D", "Em", "C"] * 2
    audio = synth_progression(np, [SHAPES[n] for n in names], bpm=96)
    clip = AudioClip(samples=audio, sample_rate=22050)
    return names, analyze_clip(clip)


def test_detects_the_chord_progression(four_chord_analysis):
    names, analysis = four_chord_analysis
    detected = [segment.symbol for segment in analysis.chords]
    assert detected == names


def test_detects_the_key(four_chord_analysis):
    _names, analysis = four_chord_analysis
    assert analysis.key.key == Key(7, "major")


def test_detects_the_tempo(four_chord_analysis):
    _names, analysis = four_chord_analysis
    assert analysis.tempo == pytest.approx(96, abs=6)


def test_finds_the_repeating_loop(four_chord_analysis):
    _names, analysis = four_chord_analysis
    assert [chord.symbol() for chord in analysis.loop] == ["G", "D", "Em", "C"]
    assert analysis.numerals == ["I", "V", "vi", "IV"]
    assert analysis.progression_name is not None


def test_offers_a_shape_for_every_chord(four_chord_analysis):
    _names, analysis = four_chord_analysis
    voicings = analysis.voicings()
    assert {v.chord.symbol() for v in voicings} == {"G", "D", "Em", "C"}
    for voicing in voicings:
        assert voicing.fingers <= 4


def test_analysis_serialises_to_json(four_chord_analysis):
    _names, analysis = four_chord_analysis
    payload = analysis.to_dict()
    assert payload["key"]["name"] == "G major"
    assert payload["progression"]["loop"] == ["G", "D", "Em", "C"]
    assert len(payload["chords"]) == len(analysis.chords)

    import json

    json.dumps(payload)  # must be serialisable


def test_chord_histogram_totals_time(four_chord_analysis):
    _names, analysis = four_chord_analysis
    histogram = chord_histogram(analysis.chords)
    assert len(histogram) == 4
    total = sum(seconds for _chord, seconds in histogram)
    assert total == pytest.approx(analysis.chords[-1].end - analysis.chords[0].start, abs=0.1)


def test_detects_a_minor_progression(make_progression):
    clip = make_progression(["Am", "F", "C", "G"] * 2)
    segments, _grid = detect_chords(clip)
    assert [s.symbol for s in segments] == ["Am", "F", "C", "G"] * 2


def test_sensitivity_controls_how_often_chords_change(make_progression):
    clip = make_progression(["C", "G"] * 3)
    steady, _ = detect_chords(clip, change_penalty=50.0)
    twitchy, _ = detect_chords(clip, change_penalty=0.1)
    assert len(steady) <= len(twitchy)


def test_transcribes_a_monophonic_line(make_melody):
    midis = [name_to_midi(n) for n in ["E3", "G3", "A3", "B3", "D4"]]
    notes = transcribe_melody(make_melody(midis))
    assert len(notes) >= 3
    detected = [note.midi for note in notes]
    # Every detected note should be one we actually played.
    assert set(detected).issubset(set(midis))
    assert detected[0] == midis[0]


def test_quantize_to_beats_assigns_slots():
    class FakeNote:
        def __init__(self, start):
            self.start = start

    notes = [FakeNote(0.0), FakeNote(0.5), FakeNote(1.0)]
    slots = quantize_to_beats(notes, [0.0, 0.5, 1.0, 1.5], subdivisions=2)
    assert [slot for _note, slot in slots] == [0, 2, 4]


def test_quantize_without_beats_falls_back_to_order():
    class FakeNote:
        start = 0.0

    slots = quantize_to_beats([FakeNote(), FakeNote()], [])
    assert [slot for _n, slot in slots] == [0, 1]


@pytest.mark.parametrize(
    "key,fret,shape",
    [
        (Key(0, "major"), 0, "C major"),      # already easy, no capo
        (Key(7, "major"), 0, "G major"),
        (Key(5, "major"), 1, "E major"),      # avoid the F barre
        (Key(11, "minor"), 2, "A minor"),     # avoid the Bm barre
        (Key(1, "minor"), 4, "A minor"),
    ],
)
def test_capo_suggestions(key, fret, shape):
    suggestion = suggest_capo(key)
    assert suggestion.fret == fret
    assert suggestion.shape_key.name == shape


def test_capo_shape_key_sounds_the_real_key():
    for tonic in range(12):
        for mode in ("major", "minor"):
            key = Key(tonic, mode)
            suggestion = suggest_capo(key)
            # Fingering the shape key behind the capo must sound the real key.
            assert (suggestion.shape_key.tonic + suggestion.fret) % 12 == key.tonic
            assert suggestion.shape_key.mode == key.mode
