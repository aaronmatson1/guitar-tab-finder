"""Command line interface for guitar-tab-finder."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from . import __version__
from .guitar.fretboard import TUNINGS, Fretboard
from .report import (
    render_analysis,
    render_chord_sheet,
    render_key_sheet,
    render_search,
    search_to_dict,
    to_json,
    wrap_markdown,
)
from .search import SOURCES, search_links, search_tabs
from .theory.notes import NoteParseError, pitch_class
from .theory.scales import Key


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tabfinder",
        description=(
            "Find guitar tabs for a song -- or work them out from the audio "
            "when nobody has tabbed it."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  tabfinder find \"Oasis - Wonderwall\"\n"
            "  tabfinder analyze demo.mp3 --melody\n"
            "  tabfinder song \"Some Obscure B-side\" --audio bside.wav\n"
            "  tabfinder chord Am7 Cmaj7 F#m --capo 2\n"
            "  tabfinder key \"E minor\" --sevenths\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"tabfinder {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--tuning", default="standard",
        help=f"one of: {', '.join(sorted(TUNINGS))} (default: standard)",
    )
    common.add_argument("--capo", type=int, default=0, metavar="FRET", help="capo position")
    common.add_argument("--json", action="store_true", help="output JSON instead of text")
    common.add_argument("--markdown", action="store_true", help="wrap the report in Markdown")
    common.add_argument("--out", metavar="FILE", help="write the report to a file")

    subparsers = parser.add_subparsers(dest="command", required=True)

    find = subparsers.add_parser(
        "find", parents=[common], help="search for published tabs"
    )
    find.add_argument("query", nargs="+", help='song to look for, e.g. "Oasis - Wonderwall"')
    find.add_argument("--limit", type=int, default=10, help="how many results to show")
    find.add_argument(
        "--source", action="append", choices=sorted(SOURCES),
        help="restrict to one source (repeatable)",
    )
    find.add_argument("--timeout", type=float, default=8.0, help="per-source timeout in seconds")

    analyze = subparsers.add_parser(
        "analyze", parents=[common], help="work out the key, chords and tab from audio"
    )
    analyze.add_argument("audio", help="path to an audio file (wav, mp3, flac, ogg, m4a)")
    analyze.add_argument("--title", help="name to print at the top of the report")
    analyze.add_argument("--start", type=float, default=0.0, metavar="SEC", help="skip to this point")
    analyze.add_argument("--duration", type=float, metavar="SEC", help="analyse only this many seconds")
    analyze.add_argument(
        "--melody", action="store_true",
        help="also transcribe a single-note line (use on a riff, not a full mix)",
    )
    analyze.add_argument(
        "--beats-per-bar", type=int, default=4, metavar="N", help="time signature numerator"
    )
    analyze.add_argument(
        "--sensitivity", type=float, default=3.0, metavar="X",
        help="lower catches quicker chord changes, higher gives steadier output (default 3.0)",
    )
    analyze.add_argument("--shapes", type=int, default=1, metavar="N",
                         help="chord shapes to show per chord (default 1)")

    song = subparsers.add_parser(
        "song", parents=[common],
        help="search for a tab, and fall back to analysing audio if there is none",
    )
    song.add_argument("query", nargs="+", help="song title, ideally with the artist")
    song.add_argument("--audio", help="audio to analyse if no tab turns up")
    song.add_argument("--limit", type=int, default=5, help="how many search results to show")
    song.add_argument("--timeout", type=float, default=8.0, help="per-source timeout in seconds")
    song.add_argument("--melody", action="store_true", help="also transcribe a single-note line")
    song.add_argument(
        "--always-analyze", action="store_true",
        help="analyse the audio even when a published tab is found",
    )

    chord = subparsers.add_parser("chord", parents=[common], help="show shapes for chords")
    chord.add_argument("symbols", nargs="+", help="chord symbols, e.g. Am7 Cmaj7 F#m")
    chord.add_argument("--shapes", type=int, default=3, metavar="N",
                       help="how many shapes per chord (default 3)")

    key_cmd = subparsers.add_parser(
        "key", parents=[common], help="show the chords and scales of a key"
    )
    key_cmd.add_argument("name", nargs="+", help='e.g. "E minor", "Bb major", "C"')
    key_cmd.add_argument("--sevenths", action="store_true", help="show seventh chords")

    subparsers.add_parser("tunings", help="list the tunings that are available")

    return parser


def _board(args: argparse.Namespace) -> Fretboard:
    capo = max(0, getattr(args, "capo", 0) or 0)
    return Fretboard.from_tuning(args.tuning, capo=capo)


def _emit(text: str, args: argparse.Namespace, title: str = "Tab") -> None:
    """Print a report, or write it to a file when asked."""
    if getattr(args, "markdown", False) and not getattr(args, "json", False):
        text = wrap_markdown(text, title)
    destination = getattr(args, "out", None)
    if destination:
        Path(destination).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {destination}")
    else:
        print(text)


def parse_key(text: str) -> Key:
    """Parse ``"E minor"``, ``"Bb"`` or ``"c# minor"`` into a key."""
    parts = text.replace(",", " ").split()
    if not parts:
        raise ValueError("no key given")
    tonic_text, mode = parts[0], "major"

    if len(parts) > 1:
        word = parts[1].lower()
        if word.startswith("min") or word in ("m", "aeolian"):
            mode = "minor"
        elif word.startswith("maj") or word == "ionian":
            mode = "major"
        else:
            raise ValueError(f"unknown mode: {parts[1]!r} (use 'major' or 'minor')")
    elif len(tonic_text) > 1 and tonic_text.endswith("m"):
        # A bare "Am" or "F#m" means the minor key.
        tonic_text, mode = tonic_text[:-1], "minor"

    return Key(pitch_class(tonic_text), mode)


def cmd_find(args: argparse.Namespace) -> int:
    query = " ".join(args.query)
    outcome = search_tabs(query, sources=args.source, limit=args.limit, timeout=args.timeout)
    if args.json:
        _emit(to_json(search_to_dict(outcome, query, limit=args.limit)), args, query)
        return 0
    links = search_links(query) if not outcome.found else None
    _emit(render_search(outcome, query, limit=args.limit, links=links), args, query)
    return 0 if outcome.found else 1


def cmd_analyze(args: argparse.Namespace) -> int:
    from .analysis.pipeline import analyze_file

    analysis = analyze_file(
        args.audio,
        offset=args.start,
        duration=args.duration,
        beats_per_bar=args.beats_per_bar,
        change_penalty=args.sensitivity,
        with_melody=args.melody,
        title=args.title,
    )
    if args.json:
        _emit(to_json(analysis), args, analysis.title or "analysis")
        return 0
    board = _board(args)
    _emit(
        render_analysis(analysis, board, voicings_per_chord=args.shapes),
        args,
        analysis.title or "Tab",
    )
    return 0


def cmd_song(args: argparse.Namespace) -> int:
    query = " ".join(args.query)
    outcome = search_tabs(query, limit=args.limit, timeout=args.timeout)
    sections: List[str] = []
    links = search_links(query) if not outcome.found else None
    sections.append(render_search(outcome, query, limit=args.limit, links=links))

    should_analyze = bool(args.audio) and (args.always_analyze or not outcome.found)
    if should_analyze:
        from .analysis.pipeline import analyze_file

        analysis = analyze_file(args.audio, with_melody=args.melody, title=query)
        board = _board(args)
        if args.json:
            payload = {
                "search": search_to_dict(outcome, query, limit=args.limit),
                "analysis": analysis.to_dict(),
            }
            _emit(to_json(payload), args, query)
            return 0
        sections.append("\n" + "=" * 72)
        sections.append(render_analysis(analysis, board))
    elif args.json:
        _emit(to_json(search_to_dict(outcome, query, limit=args.limit)), args, query)
        return 0
    elif not outcome.found and not args.audio:
        sections.append(
            "\n  Tip: point --audio at a recording of the song and this will work "
            "out\n  the key and chords for you."
        )

    _emit("\n".join(sections), args, query)
    return 0


def cmd_chord(args: argparse.Namespace) -> int:
    board = _board(args)
    if args.json:
        from .theory.chords import parse_chord
        from .guitar.voicings import generate_voicings

        payload = []
        for symbol in args.symbols:
            chord = parse_chord(symbol)
            payload.append(
                {
                    "chord": chord.symbol(),
                    "quality": chord.quality.name,
                    "notes": list(chord.core_pitch_classes),
                    "shapes": [
                        {
                            "frets": v.fret_string(),
                            "difficulty": v.difficulty,
                            "position": v.position_label(),
                            "barre": v.barre,
                            "notes": v.note_names(),
                        }
                        for v in generate_voicings(chord, board, limit=args.shapes)
                    ],
                }
            )
        _emit(to_json(payload), args, "chords")
        return 0
    _emit(render_chord_sheet(args.symbols, board, per_chord=args.shapes), args, "Chords")
    return 0


def cmd_key(args: argparse.Namespace) -> int:
    key = parse_key(" ".join(args.name))
    board = _board(args)
    if args.json:
        payload = {
            "key": key.name,
            "scale": key.scale_notes(),
            "pentatonic": key.pentatonic(),
            "relative": key.relative.name,
            "chords": [
                {"numeral": numeral, "chord": chord.symbol(key.prefer_flats)}
                for numeral, chord in key.diatonic_chords(sevenths=args.sevenths)
            ],
        }
        _emit(to_json(payload), args, key.name)
        return 0
    _emit(render_key_sheet(key, board, sevenths=args.sevenths), args, key.name)
    return 0


def cmd_tunings(_args: argparse.Namespace) -> int:
    print("Available tunings (low string first):\n")
    for name, strings in sorted(TUNINGS.items()):
        print(f"  {name:<18} {' '.join(strings)}")
    return 0


COMMANDS = {
    "find": cmd_find,
    "analyze": cmd_analyze,
    "song": cmd_song,
    "chord": cmd_chord,
    "key": cmd_key,
    "tunings": cmd_tunings,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = COMMANDS[args.command]
    try:
        return handler(args)
    except KeyboardInterrupt:  # pragma: no cover
        print("\ninterrupted", file=sys.stderr)
        return 130
    except (NoteParseError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        from .analysis.audio import AudioUnavailable

        if isinstance(exc, AudioUnavailable):
            print(f"error: {exc}", file=sys.stderr)
            return 3
        raise


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
