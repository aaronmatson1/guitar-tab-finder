"""Turn an analysis into something you can put on a music stand."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from .analysis.audio import format_time
from .analysis.pipeline import SongAnalysis
from .guitar.fretboard import Fretboard
from .guitar.render import (
    TabEvent,
    chord_diagrams_row,
    fretboard_map,
    notes_to_columns,
    render_tab,
    voicings_to_columns,
)
from .guitar.arrange import place_notes, position_summary
from .guitar.voicings import generate_voicings
from .search.base import SearchOutcome, TabResult
from .theory.scales import roman_numeral

RULE = "─" * 72

ACCURACY_NOTE = (
    "Chords are worked out from the audio, so treat them as a strong first "
    "draft rather than gospel:\n"
    "  • dense mixes, heavy distortion and busy drums all blur the analysis\n"
    "  • added notes (9ths, 11ths) and inversions often read as simpler chords\n"
    "  • if a chord sounds wrong, try its relative minor/major or a sus chord"
)


def heading(text: str) -> str:
    return f"\n{text}\n{RULE}"


def render_analysis(
    analysis: SongAnalysis,
    board: Optional[Fretboard] = None,
    show_tab: bool = True,
    show_diagrams: bool = True,
    show_timeline: bool = True,
    show_scale: bool = True,
    voicings_per_chord: int = 1,
) -> str:
    """The full tab sheet: key, progression, chord shapes and tab."""
    board = board or Fretboard.from_tuning()
    key = analysis.key
    out: List[str] = []

    title = analysis.title or (analysis.source.name if analysis.source else "untitled")
    out.append(f"{title}")
    out.append(RULE)
    out.append(
        f"  length {format_time(analysis.duration)}   "
        f"tempo {analysis.tempo:.0f} BPM   "
        f"tuning {board.describe()}"
    )

    # --- Key -------------------------------------------------------------
    out.append(heading("KEY"))
    confidence = key.confidence
    label = "confident" if confidence > 0.6 else ("likely" if confidence > 0.3 else "uncertain")
    out.append(f"  {key.key.name}  ({label}, {confidence:.0%})")
    alternatives = [c for c in key.top(4)[1:]]
    if alternatives:
        out.append(
            "  also possible: "
            + ", ".join(f"{c.name}" for c in alternatives[:3])
        )
    if show_scale:
        out.append(f"  scale:      {' '.join(key.key.scale_notes())}")
        out.append(f"  pentatonic: {' '.join(key.key.pentatonic())}   (safe notes for a solo)")
    if analysis.capo:
        out.append(f"  capo:       {analysis.capo.describe()}")

    # --- Progression ------------------------------------------------------
    loop = analysis.loop
    if loop:
        out.append(heading("PROGRESSION"))
        symbols = [chord.symbol(key.key.prefer_flats) for chord in loop]
        numerals = analysis.numerals or [roman_numeral(c, key.key) for c in loop]
        width = max(len(s) for s in symbols + numerals) + 2
        out.append("  " + "".join(s.ljust(width) for s in symbols))
        out.append("  " + "".join(n.ljust(width) for n in numerals))
        if analysis.progression_name:
            out.append(f"\n  That is {analysis.progression_name}.")

    # --- Chord shapes -----------------------------------------------------
    voicings = analysis.voicings(board, per_chord=voicings_per_chord)
    if show_diagrams and voicings:
        out.append(heading("CHORD SHAPES"))
        out.append(chord_diagrams_row(voicings))

    # --- Rhythm tab -------------------------------------------------------
    if show_tab and loop:
        loop_voicings = [
            v for chord in loop for v in generate_voicings(chord, board, limit=1)
        ]
        if loop_voicings:
            out.append(heading("RHYTHM TAB  (one bar of downstrokes per chord)"))
            columns, labels = voicings_to_columns(loop_voicings, strums_per_chord=4)
            out.append(render_tab(columns, board, labels, beats_per_bar=4))

    # --- Timeline ---------------------------------------------------------
    if show_timeline and analysis.chords:
        out.append(heading("CHORD TIMELINE"))
        beats_per_bar = analysis.beats.beats_per_bar if analysis.beats else 4
        for segment in analysis.chords:
            bars = segment.beats / beats_per_bar
            length = f"{bars:.0f} bar" + ("s" if bars >= 2 else "") if bars >= 1 else f"{segment.beats} beats"
            out.append(
                f"  {format_time(segment.start):>6}  "
                f"{segment.chord.symbol(key.key.prefer_flats):<8} {length}"
            )

    # --- Melody -----------------------------------------------------------
    if analysis.melody:
        out.append(heading("MELODY / RIFF"))
        placements = place_notes(analysis.melody, board)
        out.append(f"  {len(placements)} notes, {position_summary(placements)}")
        events = [TabEvent(p.string, p.fret) for p in placements]
        columns, labels = notes_to_columns(events)
        out.append("")
        out.append(render_tab(columns, board, labels, beats_per_bar=8))

    # --- Soloing ----------------------------------------------------------
    if show_scale:
        out.append(heading("SOLOING MAP  (pentatonic of the key, first 12 frets)"))
        from .theory.notes import pitch_class

        pentatonic = [pitch_class(n) for n in key.key.pentatonic()]
        out.append(fretboard_map(board, pentatonic, frets=12))

    out.append(heading("A NOTE ON ACCURACY"))
    out.append("  " + ACCURACY_NOTE.replace("\n", "\n  "))
    return "\n".join(out)


def render_chord_sheet(
    symbols: Sequence[str],
    board: Optional[Fretboard] = None,
    per_chord: int = 3,
) -> str:
    """Show the shapes for a list of chord symbols."""
    from .theory.chords import parse_chord

    board = board or Fretboard.from_tuning()
    out: List[str] = []
    for symbol in symbols:
        chord = parse_chord(symbol)
        voicings = generate_voicings(chord, board, limit=per_chord)
        if not voicings:
            out.append(f"{symbol}: no playable shape found on {board.describe()}")
            continue
        out.append(heading(f"{chord.symbol()}  ({chord.quality.name})"))
        notes = ", ".join(
            f"{name}" for name in _chord_note_names(chord, board)
        )
        out.append(f"  notes: {notes}")
        out.append("")
        out.append(chord_diagrams_row(voicings))
    return "\n".join(out).lstrip()


def _chord_note_names(chord, board) -> List[str]:
    from .theory.notes import note_name

    flats = chord.root in (1, 3, 5, 8, 10)
    return [note_name(pc, flats) for pc in chord.core_pitch_classes]


def render_key_sheet(key, board: Optional[Fretboard] = None, sevenths: bool = False) -> str:
    """Everything you need to play in a key: chords, scale and neck map."""
    from .theory.notes import pitch_class

    board = board or Fretboard.from_tuning()
    out: List[str] = [f"{key.name}", RULE]
    out.append(f"  scale:      {' '.join(key.scale_notes())}")
    out.append(f"  pentatonic: {' '.join(key.pentatonic())}")
    out.append(f"  relative:   {key.relative.name}")

    out.append(heading("CHORDS IN THIS KEY"))
    entries = key.diatonic_chords(sevenths=sevenths)
    width = max(len(c.symbol(key.prefer_flats)) for _, c in entries) + 3
    out.append("  " + "".join(c.symbol(key.prefer_flats).ljust(width) for _, c in entries))
    out.append("  " + "".join(n.ljust(width) for n, _ in entries))

    voicings = [v for _, chord in entries for v in generate_voicings(chord, board, limit=1)]
    out.append(heading("SHAPES"))
    out.append(chord_diagrams_row(voicings))

    out.append(heading("PENTATONIC ON THE NECK"))
    out.append(fretboard_map(board, [pitch_class(n) for n in key.pentatonic()], frets=12))
    return "\n".join(out)


def render_search(outcome: SearchOutcome, query: str, limit: int = 10,
                  links: Optional[Sequence[TabResult]] = None) -> str:
    """List published tabs, and say plainly when a source failed."""
    out: List[str] = [f"Tabs for: {query}", RULE]
    results = outcome.ranked(query, limit=limit)
    if results:
        for index, result in enumerate(results, start=1):
            out.append(f"  {index:>2}. {result.describe()}")
            out.append(f"      {result.source}: {result.url}")
    else:
        out.append("  No published tabs found.")

    if outcome.errors:
        out.append(heading("SOURCES THAT DID NOT ANSWER"))
        for source, error in outcome.errors.items():
            out.append(f"  {source}: {_short_error(error)}")

    if links:
        out.append(heading("SEARCH THESE YOURSELF"))
        for link in links:
            out.append(f"  {link.source:<18} {link.url}")

    if not results:
        out.append(heading("NOTHING OUT THERE?"))
        out.append(
            "  If nobody has tabbed this song, work it out from the recording:\n"
            "      tabfinder analyze path/to/song.mp3\n"
            "  That gives you the key, the chord progression and playable shapes."
        )
    return "\n".join(out)


def _short_error(error: str, width: int = 110) -> str:
    text = " ".join(error.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def to_json(payload: Any) -> str:
    """Serialise a report payload as indented JSON."""
    if isinstance(payload, SongAnalysis):
        payload = payload.to_dict()
    return json.dumps(payload, indent=2, ensure_ascii=False)


def search_to_dict(outcome: SearchOutcome, query: str, limit: int = 10) -> Dict[str, Any]:
    """A JSON-friendly view of search results."""
    return {
        "query": query,
        "results": [
            {
                "title": r.title,
                "artist": r.artist,
                "url": r.url,
                "source": r.source,
                "kind": r.kind,
                "rating": r.rating,
                "votes": r.votes,
                "relevance": round(r.relevance(query), 3),
            }
            for r in outcome.ranked(query, limit=limit)
        ],
        "errors": outcome.errors,
    }


def wrap_markdown(text: str, title: str) -> str:
    """Wrap an ASCII report in Markdown so it survives copy-paste."""
    return f"# {title}\n\n```\n{text}\n```\n"
