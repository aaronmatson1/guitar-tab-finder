"""Fretboard, chord shapes, arranging and rendering."""

from __future__ import annotations

import pytest

from tabfinder.guitar.arrange import arrange_notes, place_notes, position_summary
from tabfinder.guitar.fretboard import TUNINGS, Fretboard
from tabfinder.guitar.render import (
    TabEvent,
    chord_chart,
    chord_diagram,
    chord_diagrams_row,
    fretboard_map,
    notes_to_columns,
    render_tab,
    voicings_to_columns,
)
from tabfinder.guitar.shapes import canonical_shapes, has_standard_intervals
from tabfinder.guitar.voicings import Voicing, best_voicing, generate_voicings
from tabfinder.theory.chords import parse_chord
from tabfinder.theory.notes import name_to_midi


@pytest.fixture
def board():
    return Fretboard.from_tuning("standard")


def test_standard_tuning_pitches(board):
    assert board.string_names() == ["E2", "A2", "D3", "G3", "B3", "E4"]
    assert board.string_labels() == ["E", "A", "D", "G", "B", "e"]


def test_unknown_tuning_is_rejected():
    with pytest.raises(ValueError, match="unknown tuning"):
        Fretboard.from_tuning("klingon")


def test_every_listed_tuning_loads():
    for name in TUNINGS:
        assert Fretboard.from_tuning(name).string_count >= 4


def test_midi_at_matches_positions(board):
    assert board.midi_at(0, 5) == board.midi_at(1, 0)  # 5th fret low E == open A
    assert board.midi_at(5, 0) == name_to_midi("E4")


def test_positions_for_midi_finds_every_place(board):
    positions = board.positions_for_midi(name_to_midi("C4"))
    assert {(p.string, p.fret) for p in positions} >= {(1, 15), (2, 10), (3, 5), (4, 1)}
    assert all(board.midi_at(p.string, p.fret) == name_to_midi("C4") for p in positions)


def test_capo_raises_open_strings_and_blocks_lower_frets():
    capoed = Fretboard.from_tuning("standard", capo=2)
    assert capoed.open_midi(0) == name_to_midi("F#2")
    assert capoed.lowest_fret == 2
    with pytest.raises(IndexError):
        capoed.midi_at(0, 1)


def test_drop_d_lowers_only_the_sixth_string():
    drop = Fretboard.from_tuning("drop-d")
    standard = Fretboard.from_tuning("standard")
    assert drop.open_strings[0] == standard.open_strings[0] - 2
    assert drop.open_strings[1:] == standard.open_strings[1:]


# --- voicings ------------------------------------------------------------

#: The shapes any guitarist would name for these chords.
EXPECTED_SHAPES = {
    "C": "x32010",
    "G": "320003",
    "D": "xx0232",
    "A": "x02220",
    "E": "022100",
    "Am": "x02210",
    "Em": "022000",
    "Dm": "xx0231",
    "Am7": "x02010",
    "Cmaj7": "x32000",
    "G7": "320001",
    "Dsus4": "xx0233",
    "F#m": "244222",
    "Bb": "x13331",
}


@pytest.mark.parametrize("symbol,shape", sorted(EXPECTED_SHAPES.items()))
def test_common_chords_get_their_standard_shape(board, symbol, shape):
    voicings = generate_voicings(parse_chord(symbol), board, limit=3)
    assert shape in [v.fret_string() for v in voicings]


@pytest.mark.parametrize("symbol", ["C", "Am", "F#m7", "Bbmaj7", "Gsus4", "Bdim", "E5", "Caug"])
def test_generated_shapes_actually_sound_the_chord(board, symbol):
    chord = parse_chord(symbol)
    essential = set(chord.core_pitch_classes) - set(chord.optional_pitch_classes)
    for voicing in generate_voicings(chord, board, limit=4):
        sounded = set(voicing.pitch_classes)
        # Nothing outside the chord, and nothing essential missing.
        assert sounded.issubset(set(chord.pitch_classes)), voicing.fret_string()
        assert essential.issubset(sounded), voicing.fret_string()


@pytest.mark.parametrize("symbol", ["C", "G", "Am", "F", "Bb", "Bm", "F#m7", "Dsus4"])
def test_shapes_are_physically_playable(board, symbol):
    for voicing in generate_voicings(parse_chord(symbol), board, limit=4):
        assert voicing.fingers <= 4, voicing.fret_string()
        assert voicing.span <= 4, voicing.fret_string()


def test_root_is_in_the_bass_for_common_chords(board):
    for symbol in ["C", "G", "D", "A", "E", "Am", "Em", "Dm", "F", "Bb"]:
        chord = parse_chord(symbol)
        voicing = best_voicing(chord, board)
        assert min(voicing.midi_notes) % 12 == chord.root, symbol


def test_slash_chord_puts_the_named_note_in_the_bass(board):
    voicing = best_voicing(parse_chord("D/F#"), board)
    assert min(voicing.midi_notes) % 12 == parse_chord("F#").root


@pytest.mark.parametrize(
    "shape,symbol,expected",
    [
        ("133211", "F", 1),      # the full barre F
        ("x13331", "Bb", 1),
        ("575555", "Am7", 5),
        ("xx0232", "D", None),   # two fingers at fret 2 is not a barre
        ("x32010", "C", None),
        ("022000", "Em", None),
    ],
)
def test_barre_detection(board, shape, symbol, expected):
    frets = tuple(None if c == "x" else int(c) for c in shape)
    assert Voicing(parse_chord(symbol), frets, board).barre == expected


def test_open_chords_are_easier_than_barre_chords(board):
    easy = best_voicing(parse_chord("Em"), board)
    hard = best_voicing(parse_chord("Bb"), board)
    assert easy.difficulty == "easy"
    assert hard.difficulty == "hard"
    assert easy.score < hard.score


def test_voicings_spread_along_the_neck(board):
    shapes = generate_voicings(parse_chord("C"), board, limit=3)
    positions = sorted(v.min_fret for v in shapes)
    assert len(set(positions)) == len(positions)


def test_fret_string_formats_wide_shapes(board):
    low = Voicing(parse_chord("C"), (None, 3, 2, 0, 1, 0), board)
    high = Voicing(parse_chord("C"), (8, 10, 10, 9, 8, 8), board)
    assert low.fret_string() == "x32010"
    assert high.fret_string() == "8-10-10-9-8-8"


def test_voicings_work_in_alternate_tunings():
    drop = Fretboard.from_tuning("drop-d")
    voicing = best_voicing(parse_chord("D"), drop)
    assert voicing is not None
    assert set(voicing.pitch_classes).issubset({2, 6, 9})


def test_capo_shapes_stay_behind_the_capo():
    capoed = Fretboard.from_tuning("standard", capo=3)
    for voicing in generate_voicings(parse_chord("C"), capoed, limit=3):
        assert all(f >= 3 for f in voicing.frets if f is not None), voicing.fret_string()


# --- canonical shapes ----------------------------------------------------


def test_movable_shapes_only_apply_to_standard_intervals():
    assert has_standard_intervals(Fretboard.from_tuning("standard"))
    assert has_standard_intervals(Fretboard.from_tuning("half-step-down"))
    assert not has_standard_intervals(Fretboard.from_tuning("drop-d"))
    assert canonical_shapes(parse_chord("C"), Fretboard.from_tuning("drop-d")) == []


def test_barre_shapes_transpose(board):
    # F#m is the Em shape moved up two frets.
    shapes = canonical_shapes(parse_chord("F#m"), board)
    assert (2, 4, 4, 2, 2, 2) in shapes


# --- arranging -----------------------------------------------------------


def test_arrange_keeps_the_hand_in_one_place(board):
    midis = [name_to_midi(n) for n in ["A4", "C5", "D5", "E5", "G5", "A5"]]
    placements = arrange_notes(midis, board)
    frets = [f for _, f in placements if f > 0]
    assert max(frets) - min(frets) <= 5


def test_arrange_produces_the_right_pitches(board):
    midis = [name_to_midi(n) for n in ["E3", "G3", "A3", "B3", "D4", "E4"]]
    placements = arrange_notes(midis, board)
    assert [board.midi_at(s, f) for s, f in placements] == midis


def test_arrange_prefers_open_strings_low_down(board):
    placements = arrange_notes([name_to_midi("E2"), name_to_midi("A2")], board)
    assert placements[0] == (0, 0)


def test_arrange_folds_out_of_range_notes_into_the_neck(board):
    very_low = name_to_midi("E1")
    (string, fret), = arrange_notes([very_low], board)
    # Played an octave (or more) up, since the guitar cannot go that low.
    assert (board.midi_at(string, fret) - very_low) % 12 == 0
    assert board.midi_at(string, fret) > very_low


def test_arrange_handles_empty_input(board):
    assert arrange_notes([], board) == []


def test_place_notes_keeps_timings(board):
    class FakeNote:
        def __init__(self, midi, start, end):
            self.midi, self.start, self.end = midi, start, end

    notes = [FakeNote(64, 0.0, 0.5), FakeNote(67, 0.5, 1.0)]
    placed = place_notes(notes, board)
    assert [p.midi for p in placed] == [64, 67]
    assert placed[1].start == 0.5
    assert "fret" in position_summary(placed) or position_summary(placed) == "all open strings"


# --- rendering -----------------------------------------------------------


def test_chord_diagram_shows_shape_and_strings(board):
    text = chord_diagram(best_voicing(parse_chord("C"), board))
    assert "x32010" in text
    assert "E A D G B e" in text
    lines = text.split("\n")
    # Marker row, nut and five fret rows all line up to the same width.
    grid = [line for line in lines if "│" in line or "┬" in line]
    assert len({len(line) for line in grid}) == 1


def test_chord_diagram_marks_barres(board):
    text = chord_diagram(best_voicing(parse_chord("Bb"), board))
    assert "barre" in text


def test_chord_diagram_labels_position_up_the_neck(board):
    high = Voicing(parse_chord("C"), (8, 10, 10, 9, 8, 8), board)
    assert "8fr" in chord_diagram(high)


def test_diagrams_row_places_shapes_side_by_side(board):
    voicings = [best_voicing(parse_chord(s), board) for s in ["C", "G", "Am", "F"]]
    text = chord_diagrams_row(voicings)
    assert text.split("\n")[0].count("  ") >= 3
    for symbol in ["C", "G", "Am", "F"]:
        assert symbol in text


def test_render_tab_has_a_row_per_string_high_first(board):
    voicings = [best_voicing(parse_chord("C"), board)]
    columns, labels = voicings_to_columns(voicings, strums_per_chord=4)
    text = render_tab(columns, board, labels)
    rows = [line for line in text.split("\n") if "|" in line and line[0] != " "]
    assert len(rows) == 6
    assert rows[0].startswith("e")
    assert rows[-1].startswith("E")


def test_render_tab_never_splits_a_bar(board):
    voicings = [best_voicing(parse_chord(s), board) for s in ["C", "G", "Am", "F"] * 3]
    columns, labels = voicings_to_columns(voicings, strums_per_chord=4)
    text = render_tab(columns, board, labels, beats_per_bar=4)
    for line in text.split("\n"):
        if line.startswith("e |"):
            # Every stave line ends on a bar line.
            assert line.rstrip().endswith("|")


def test_render_tab_of_single_notes(board):
    events = [TabEvent(0, 0), TabEvent(0, 3), TabEvent(1, 0)]
    columns, labels = notes_to_columns(events)
    rows = render_tab(columns, board, labels).split("\n")
    low_e = next(r for r in rows if r.startswith("E "))
    a_string = next(r for r in rows if r.startswith("A "))
    # Two notes on the low E, then one on the A, each in its own column.
    assert low_e.startswith("E |0")
    assert "3" in low_e
    assert "0" in a_string
    # A note only ever appears on the string it was placed on.
    assert "3" not in a_string


def test_chord_chart_lays_out_bars():
    text = chord_chart([("C", "0:00"), ("G", "0:02")])
    assert "| C" in text and "| G" in text
    assert "0:00" in text


def test_fretboard_map_marks_scale_notes(board):
    text = fretboard_map(board, [0, 2, 4, 7, 9], frets=12)
    lines = text.split("\n")
    assert len(lines) == 7  # header plus six strings
    assert "●" in text
