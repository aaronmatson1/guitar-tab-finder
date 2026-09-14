"""Render chords and notes as the ASCII art guitarists actually read."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .fretboard import Fretboard
from .voicings import Voicing

#: One moment in a tab: which fret to play on which string, plus a label.
Column = Dict[int, int]


@dataclass
class TabEvent:
    """A single strike in a tab: string, fret, and when it happens."""

    string: int
    fret: int
    beat: float = 0.0
    label: str = ""


def chord_diagram(voicing: Voicing, width: int = 5, title: Optional[str] = None) -> str:
    """Draw a chord box diagram, the kind printed above song sheets.

    Strings run left to right (low to high) as columns; frets run down the
    page. ``o`` marks an open string and ``x`` one that is not played.
    """
    board = voicing.board
    strings = board.string_count
    capo = board.capo
    fretted = voicing.fretted

    # Open shapes are drawn against the nut; shapes further up the neck get a
    # fret number beside the top row.
    if not fretted or voicing.max_fret <= capo + width:
        start = capo + 1
    else:
        start = voicing.min_fret
    rows = list(range(start, start + width))
    at_nut = start == capo + 1

    label = title or voicing.chord.symbol()
    lines = [f"{label}  {voicing.fret_string()}"]

    markers = []
    for i in range(strings):
        fret = voicing.frets[i]
        markers.append("x" if fret is None else ("o" if fret == capo else " "))
    lines.append(" ".join(markers).rstrip())

    # The nut is a double rule; further up the neck it is a plain fret wire.
    nut_char = "\u2550" if at_nut else "\u2500"
    lines.append(nut_char.join(["\u252c"] * strings))

    for fret in rows:
        cells = ["\u25cf" if voicing.frets[i] == fret else "\u2502" for i in range(strings)]
        row = "\u2500".join(cells)
        if fret == start and not at_nut:
            row += f"  {fret}fr"
        lines.append(row)

    lines.append(" ".join(board.string_labels()))
    if voicing.barre is not None:
        lines.append(f"barre {voicing.barre}fr")
    return "\n".join(lines)


def chord_diagrams_row(voicings: Sequence[Voicing], per_row: int = 4) -> str:
    """Lay several chord diagrams out side by side."""
    if not voicings:
        return ""
    out: List[str] = []
    for start in range(0, len(voicings), per_row):
        group = voicings[start : start + per_row]
        blocks = [chord_diagram(v).split("\n") for v in group]
        height = max(len(b) for b in blocks)
        widths = [max(len(line) for line in b) for b in blocks]
        for row in range(height):
            cells = []
            for block, width in zip(blocks, widths):
                text = block[row] if row < len(block) else ""
                cells.append(text.ljust(width))
            out.append("   ".join(cells).rstrip())
        out.append("")
    return "\n".join(out).rstrip()


def render_tab(
    columns: Sequence[Column],
    board: Fretboard,
    labels: Optional[Sequence[str]] = None,
    beats_per_bar: int = 4,
    columns_per_beat: int = 1,
    line_width: int = 68,
    spacing: int = 2,
) -> str:
    """Render tab columns as the classic six-line stave.

    ``columns`` is a list of ``{string_index: fret}`` maps, one per time slot.
    ``labels`` may name a chord above each column.
    """
    strings = board.string_count
    names = board.string_labels()
    gutter = max(len(n) for n in names) + 1

    # One width for every column, so bars line up down the page.
    needed = 1
    for idx, column in enumerate(columns):
        needed = max([needed] + [len(str(f)) for f in column.values()])
        if labels and idx < len(labels) and labels[idx]:
            needed = max(needed, len(labels[idx]))
    widths = [needed + spacing] * len(columns)

    bar_every = max(1, beats_per_bar * columns_per_beat)
    # Group columns into bars, then pack whole bars onto each printed line so
    # a bar is never split across two staves.
    bars: List[List[int]] = [
        list(range(start, min(start + bar_every, len(columns))))
        for start in range(0, len(columns), bar_every)
    ]
    chunks: List[List[int]] = []
    current: List[int] = []
    used = gutter + 1
    for bar in bars:
        bar_width = sum(widths[i] for i in bar) + 1  # +1 for the bar line
        if current and used + bar_width > line_width:
            chunks.append(current)
            current = []
            used = gutter + 1
        current.extend(bar)
        used += bar_width
    if current:
        chunks.append(current)

    out: List[str] = []
    for chunk in chunks:
        label_line = " " * (gutter + 1)
        rows = [f"{names[s]:<{gutter}}|" for s in range(strings)]
        for idx in chunk:
            column = columns[idx]
            width = widths[idx]
            text = labels[idx] if labels and idx < len(labels) and labels[idx] else ""
            label_line += text.ljust(width)
            for s in range(strings):
                if s in column:
                    cell = str(column[s]).ljust(width, "-")
                else:
                    cell = "-" * width
                rows[s] += cell
            if (idx + 1) % bar_every == 0 or idx == len(columns) - 1:
                label_line += " "
                for s in range(strings):
                    rows[s] += "|"
        # Print high strings at the top, the way tab is always written.
        if label_line.strip():
            out.append(label_line.rstrip())
        out.extend(reversed(rows))
        out.append("")
    return "\n".join(out).rstrip()


def voicings_to_columns(
    voicings: Sequence[Voicing], strums_per_chord: int = 1
) -> Tuple[List[Column], List[str]]:
    """Turn chord shapes into tab columns — one stacked strike per strum."""
    columns: List[Column] = []
    labels: List[str] = []
    for voicing in voicings:
        for strum in range(max(1, strums_per_chord)):
            column = {
                i: f for i, f in enumerate(voicing.frets) if f is not None
            }
            columns.append(column)
            labels.append(voicing.chord.symbol() if strum == 0 else "")
    return columns, labels


def notes_to_columns(events: Sequence[TabEvent]) -> Tuple[List[Column], List[str]]:
    """Turn single notes into one tab column each."""
    columns: List[Column] = []
    labels: List[str] = []
    for event in events:
        columns.append({event.string: event.fret})
        labels.append(event.label)
    return columns, labels


def chord_chart(
    entries: Sequence[Tuple[str, str]],
    per_line: int = 4,
    cell_width: int = 14,
) -> str:
    """A bar-by-bar chord chart: ``| C      | G      | Am     | F      |``."""
    if not entries:
        return ""
    lines: List[str] = []
    for start in range(0, len(entries), per_line):
        group = entries[start : start + per_line]
        time_row = "  "
        chord_row = "|"
        for label, timing in group:
            chord_row += " " + label.ljust(cell_width - 2) + "|"
            time_row += " " + timing.ljust(cell_width - 1)
        lines.append(time_row.rstrip())
        lines.append(chord_row)
    return "\n".join(lines)


def fretboard_map(board: Fretboard, pitch_classes: Sequence[int], frets: int = 12,
                  labels: Optional[Dict[int, str]] = None) -> str:
    """Draw where a set of notes sits on the neck — handy for solos."""
    names = board.string_labels()
    gutter = max(len(n) for n in names) + 1
    wanted = {pc % 12 for pc in pitch_classes}
    header = " " * (gutter + 1) + "".join(f"{f:<4}" for f in range(0, frets + 1))
    rows = []
    for s in range(board.string_count):
        row = f"{names[s]:<{gutter}}|"
        for fret in range(0, frets + 1):
            pc = (board.open_strings[s] + fret) % 12
            if pc in wanted:
                mark = labels.get(pc, "●") if labels else "●"
                row += f"{mark:-<4}"
            else:
                row += "----"
        rows.append(row)
    return "\n".join([header] + list(reversed(rows)))
