"""Finding a guitar solo and tabbing it, technique and all."""

from __future__ import annotations

import pytest

pytest.importorskip("librosa")

from conftest import bend_curve, flat_curve, glide_curve, vibrato_curve  # noqa: E402

from tabfinder.analysis.articulation import (  # noqa: E402
    SoloNote,
    snap_to_key,
    technique_legend,
    transcribe_with_technique,
)
from tabfinder.analysis.solo import (  # noqa: E402
    LeadSection,
    find_lead_sections,
    lead_salience,
    slice_clip,
    transcribe_solo,
)
from tabfinder.theory.scales import Key  # noqa: E402

pytestmark = pytest.mark.audio


# --- finding the solo ----------------------------------------------------


def test_finds_the_solo_between_the_verses(song_with_solo):
    clip, solo_start, solo_end = song_with_solo
    sections = find_lead_sections(clip)
    assert sections, "no lead section found at all"
    best = sections[0]
    # The detected section should cover most of the real solo and little else.
    overlap = max(0.0, min(best.end, solo_end) - max(best.start, solo_start))
    assert overlap > 0.8 * (solo_end - solo_start)
    assert best.duration < 1.4 * (solo_end - solo_start)


def test_salience_peaks_during_the_solo(song_with_solo):
    np = pytest.importorskip("numpy")
    clip, solo_start, solo_end = song_with_solo
    times, score = lead_salience(clip)
    during = score[(times >= solo_start) & (times <= solo_end)]
    outside = score[(times < solo_start) | (times > solo_end)]
    assert float(np.mean(during)) > float(np.mean(outside))


def test_sections_are_ranked_and_capped(song_with_solo):
    clip, _start, _end = song_with_solo
    sections = find_lead_sections(clip, limit=2)
    assert len(sections) <= 2
    assert sections == sorted(sections, key=lambda s: -s.score * min(1.0, s.duration / 20.0))


def test_slice_clip_extracts_a_window(song_with_solo):
    clip, start, end = song_with_solo
    piece = slice_clip(clip, start, end)
    assert piece.duration == pytest.approx(end - start, abs=0.05)
    with pytest.raises(ValueError):
        slice_clip(clip, 5.0, 5.0)


# --- reading the technique -----------------------------------------------


def test_a_plain_note_is_plain(make_phrase, np):
    clip = make_phrase([(flat_curve(np, 67, 0.6), True)])
    notes = transcribe_with_technique(clip)
    assert len(notes) == 1
    assert notes[0].midi == 67
    assert not notes[0].bend and not notes[0].vibrato and notes[0].link is None


def test_a_bend_keeps_the_fretted_pitch_and_records_the_rise(make_phrase, np):
    # Bent from A4 up a whole step. The tab must show the fret you hold (A4),
    # not the pitch you arrive at.
    clip = make_phrase([(bend_curve(np, 69, 2, 0.8), True)])
    notes = transcribe_with_technique(clip)
    assert len(notes) == 1
    assert notes[0].midi == 69
    assert notes[0].bend == 2


def test_vibrato_is_not_mistaken_for_a_bend(make_phrase, np):
    clip = make_phrase([(vibrato_curve(np, 71, 0.9), True)])
    notes = transcribe_with_technique(clip)
    assert len(notes) == 1
    assert notes[0].midi == 71
    assert notes[0].vibrato
    assert notes[0].bend == 0


def test_a_wide_glide_reads_as_a_slide(make_phrase, np):
    clip = make_phrase([
        (flat_curve(np, 69, 0.4), True),
        (glide_curve(np, 69, 76, 0.2), False),
        (flat_curve(np, 76, 0.5), False),
    ])
    notes = transcribe_with_technique(clip)
    assert any(note.link == "/" for note in notes), [n.techniques() for n in notes]
    assert notes[-1].midi == 76


def test_a_soft_attack_reads_as_a_hammer_on(make_phrase, np):
    clip = make_phrase([
        (flat_curve(np, 64, 0.35), True),
        (flat_curve(np, 67, 0.35), False),
    ])
    notes = transcribe_with_technique(clip)
    assert len(notes) == 2
    assert notes[0].link == "h"


def test_a_picked_note_is_never_called_legato(make_phrase, np):
    clip = make_phrase([
        (flat_curve(np, 64, 0.35), True),
        (flat_curve(np, 67, 0.35), True),
    ])
    notes = transcribe_with_technique(clip)
    assert all(note.link is None for note in notes)


def test_notes_an_octave_apart_are_never_tied(make_phrase, np):
    clip = make_phrase([
        (flat_curve(np, 52, 0.35), True),
        (flat_curve(np, 76, 0.35), False),
    ])
    notes = transcribe_with_technique(clip)
    # Too far to hammer on to, whatever the attack looked like.
    assert all(note.link not in ("h", "p") for note in notes)


# --- notation ------------------------------------------------------------


@pytest.mark.parametrize(
    "note,fret,expected",
    [
        (SoloNote(69, 0, 1), 5, "5"),
        (SoloNote(69, 0, 1, bend=2), 5, "5b7"),
        (SoloNote(69, 0, 1, vibrato=True), 5, "5~"),
        (SoloNote(69, 0, 1, link="h"), 5, "5h"),
        (SoloNote(69, 0, 1, link="/"), 5, "5/"),
        (SoloNote(69, 0, 1, bend=1, vibrato=True, link="p"), 7, "7b8~p"),
    ],
)
def test_note_annotation(note, fret, expected):
    assert note.annotate(fret) == expected


def test_legend_only_explains_symbols_that_appear():
    notes = [SoloNote(69, 0, 1, bend=2), SoloNote(71, 1, 2, vibrato=True)]
    legend = "\n".join(technique_legend(notes))
    assert "bend" in legend and "vibrato" in legend
    assert "hammer-on" not in legend
    assert technique_legend([SoloNote(69, 0, 1)]) == []


def test_legato_flag_matches_the_link():
    assert SoloNote(69, 0, 1, link="h").legato
    assert SoloNote(69, 0, 1, link="/").legato
    assert not SoloNote(69, 0, 1).legato


# --- key-aware tidying ---------------------------------------------------


def test_snap_moves_only_weakly_tracked_notes():
    key = Key(4, "minor")  # E minor
    stray = SoloNote(midi=63, start=0, end=1, confidence=0.2)   # D# - out of key
    confident = SoloNote(midi=63, start=1, end=2, confidence=0.9)
    snapped = snap_to_key([stray, confident], key)
    assert snapped[0].midi != 63          # nudged onto the scale
    assert snapped[1].midi == 63          # confidently played, so left alone


def test_snap_never_touches_a_bend():
    key = Key(4, "minor")
    bent = SoloNote(midi=63, start=0, end=1, confidence=0.1, bend=2)
    assert snap_to_key([bent], key)[0].midi == 63


def test_snap_allows_the_blue_note():
    # The b5 is outside the scale but entirely at home in a solo.
    key = Key(4, "minor")
    blue = SoloNote(midi=58, start=0, end=1, confidence=0.1)  # Bb, the b5 of Em
    assert snap_to_key([blue], key)[0].midi == 58


def test_snap_without_a_key_changes_nothing():
    notes = [SoloNote(63, 0, 1, confidence=0.1)]
    assert snap_to_key(notes, None)[0].midi == 63


# --- end to end ----------------------------------------------------------


def test_transcribe_solo_tabs_the_section(song_with_solo):
    clip, solo_start, _end = song_with_solo
    solo = transcribe_solo(clip)
    assert solo is not None
    assert solo.note_count > 10
    low, high = solo.pitch_range()
    assert low >= 60 and high <= 84          # the phrase lives around E4-E5
    # Timings are on the song's clock, not the slice's.
    assert solo.notes[0].start >= solo_start - 1.0
    techniques = [note for note in solo.notes if note.bend or note.vibrato or note.link]
    assert techniques, "no technique detected anywhere in the solo"


def test_transcribe_solo_honours_an_explicit_range(song_with_solo):
    clip, solo_start, solo_end = song_with_solo
    section = LeadSection(solo_start, solo_start + 4.0, 1.0)
    solo = transcribe_solo(clip, section)
    assert solo is not None
    assert solo.section.end == pytest.approx(solo_start + 4.0)
    assert all(note.start < solo_start + 4.5 for note in solo.notes)


def test_solo_serialises_to_json(song_with_solo):
    import json

    clip, _start, _end = song_with_solo
    payload = transcribe_solo(clip).to_dict()
    json.dumps(payload)
    assert payload["notes"]
    assert set(payload["notes"][0]) >= {"note", "midi", "start", "end", "bend", "vibrato", "link"}


def test_legato_notes_stay_on_one_string():
    from tabfinder.guitar.arrange import place_notes
    from tabfinder.guitar.fretboard import Fretboard

    # A hammer-on can only happen along a single string.
    notes = [SoloNote(64, 0.0, 0.3, link="h"), SoloNote(67, 0.3, 0.6)]
    placed = place_notes(notes, Fretboard.from_tuning())
    assert placed[0].string == placed[1].string
