"""Command line interface for guitar-tab-finder."""

from __future__ import annotations

import argparse
import sys
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional, Sequence, Tuple

from . import __version__
from .guitar.fretboard import TUNINGS, Fretboard
from .report import (
    heading,
    render_analysis,
    render_solo,
    render_chord_sheet,
    render_key_sheet,
    render_search,
    search_to_dict,
    to_json,
    wrap_markdown,
)
from .search import SOURCES, search_links, search_tabs
from .sources import (
    AudioPolicy,
    AudioSource,
    SourceError,
    TrackRef,
    acquire_audio,
    is_url,
    resolve_track,
)
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
            "  tabfinder song https://youtu.be/6hzrDeceEKc\n"
            "  tabfinder analyze https://open.spotify.com/track/1AbCd...\n"
            "  tabfinder analyze demo.mp3 --melody\n"
            "  tabfinder solo song.mp3\n"
            "  tabfinder solo song.mp3 --solo-from 2:14 --solo-to 2:48\n"
            "  tabfinder song \"Some Obscure B-side\" --audio bside.wav\n"
            "  tabfinder chord Am7 Cmaj7 F#m --capo 2\n"
            "  tabfinder key \"E minor\" --sevenths\n"
            "  tabfinder serve --open\n"
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

    link = argparse.ArgumentParser(add_help=False)
    link.add_argument(
        "--allow-download", action="store_true",
        help=(
            "allow fetching full audio from a video link with yt-dlp; you are "
            "responsible for having the right to do so"
        ),
    )
    link.add_argument(
        "--no-preview", action="store_true",
        help="do not fall back to a 30-second preview clip",
    )
    link.add_argument(
        "--keep-audio", metavar="DIR",
        help="keep downloaded audio in DIR instead of a temporary folder",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    find = subparsers.add_parser(
        "find", parents=[common], help="search for published tabs"
    )
    find.add_argument(
        "query", nargs="+",
        help='song to look for, e.g. "Oasis - Wonderwall", or a music link',
    )
    find.add_argument("--limit", type=int, default=10, help="how many results to show")
    find.add_argument(
        "--source", action="append", choices=sorted(SOURCES),
        help="restrict to one source (repeatable)",
    )
    find.add_argument("--timeout", type=float, default=8.0, help="per-source timeout in seconds")

    analyze = subparsers.add_parser(
        "analyze", parents=[common, link],
        help="work out the key, chords and tab from audio or a music link",
    )
    analyze.add_argument(
        "audio",
        help=(
            "an audio file (wav, mp3, flac, ogg, m4a) or a YouTube, Spotify or "
            "Apple Music link"
        ),
    )
    analyze.add_argument(
        "--timeout", type=float, default=10.0, help="network timeout in seconds"
    )
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
    _add_solo_options(analyze)

    song = subparsers.add_parser(
        "song", parents=[common, link],
        help="search for a tab, and fall back to analysing audio if there is none",
    )
    song.add_argument(
        "query", nargs="+",
        help=(
            "a song title (ideally with the artist), or a YouTube, Spotify or "
            "Apple Music link"
        ),
    )
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

    solo = subparsers.add_parser(
        "solo", parents=[common, link],
        help="find the guitar solo in a song and tab it",
    )
    solo.add_argument("audio", help="an audio file, or a YouTube/Spotify/Apple Music link")
    solo.add_argument("--title", help="name to print at the top of the report")
    solo.add_argument("--timeout", type=float, default=10.0, help="network timeout in seconds")
    _add_solo_options(solo, standalone=True)

    web = subparsers.add_parser("serve", help="run the web UI in a browser")
    web.add_argument("--host", default="127.0.0.1",
                     help="address to bind to (default: localhost only)")
    web.add_argument("--port", type=int, default=5000, help="port to listen on")
    web.add_argument("--open", action="store_true", help="open a browser window too")
    web.add_argument("--debug", action="store_true", help="run Flask in debug mode")

    subparsers.add_parser("tunings", help="list the tunings that are available")

    return parser


def _add_solo_options(parser: argparse.ArgumentParser, standalone: bool = False) -> None:
    """Options controlling solo detection, shared by `analyze` and `solo`."""
    if not standalone:
        parser.add_argument(
            "--solo", action="store_true",
            help="also find the guitar solo and tab it",
        )
    parser.add_argument(
        "--solo-from", type=_timestamp, metavar="TIME",
        help="start of the solo, as seconds or m:ss (skips auto-detection)",
    )
    parser.add_argument(
        "--solo-to", type=_timestamp, metavar="TIME", help="end of the solo",
    )
    parser.add_argument(
        "--demucs", action="store_true",
        help="separate the lead from the mix with demucs first (much slower, much better)",
    )


def _timestamp(text: str) -> float:
    """Parse ``90``, ``1:30`` or ``1:30.5`` into seconds."""
    parts = text.strip().split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    except ValueError:
        pass
    raise argparse.ArgumentTypeError(f"cannot read {text!r} as a time (use seconds or m:ss)")


def _solo_range(args: argparse.Namespace):
    """The explicit solo range, if the user gave a complete one."""
    start, end = getattr(args, "solo_from", None), getattr(args, "solo_to", None)
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise ValueError("give both --solo-from and --solo-to, or neither")
    if end <= start:
        raise ValueError(f"--solo-to ({end:g}s) must come after --solo-from ({start:g}s)")
    return (start, end)


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


def _audio_policy(args: argparse.Namespace) -> AudioPolicy:
    return AudioPolicy(
        allow_preview=not getattr(args, "no_preview", False),
        allow_download=getattr(args, "allow_download", False),
        timeout=getattr(args, "timeout", 10.0),
    )


def _obtain_audio(
    source: str, args: argparse.Namespace, stack: ExitStack
) -> Tuple[str, Optional[TrackRef], Optional[AudioSource]]:
    """Resolve a path or a music link into a local audio file.

    A plain path is used as-is. A link is resolved to a track, then to the best
    audio the policy allows; downloads land in a temporary folder that is
    cleaned up when ``stack`` closes, unless ``--keep-audio`` says otherwise.
    """
    if not is_url(source):
        return source, None, None

    ref = resolve_track(source, timeout=getattr(args, "timeout", 10.0))
    if getattr(args, "keep_audio", None):
        directory = Path(args.keep_audio)
        directory.mkdir(parents=True, exist_ok=True)
    else:
        directory = Path(stack.enter_context(TemporaryDirectory(prefix="tabfinder-")))
    audio = acquire_audio(ref, directory, _audio_policy(args))
    return str(audio.path), ref, audio


def _label_analysis(analysis, ref: Optional[TrackRef], audio: Optional[AudioSource]) -> None:
    """Record on the analysis where its audio came from."""
    if ref is not None and not analysis.title:
        analysis.title = ref.display
    if audio is not None:
        analysis.source_label = audio.describe()
        analysis.partial = audio.is_preview


def cmd_find(args: argparse.Namespace) -> int:
    query = " ".join(args.query)
    if is_url(query):
        ref = resolve_track(query, timeout=args.timeout)
        print(f"link resolves to: {ref.display}\n", file=sys.stderr)
        query = ref.query
    outcome = search_tabs(query, sources=args.source, limit=args.limit, timeout=args.timeout)
    if args.json:
        _emit(to_json(search_to_dict(outcome, query, limit=args.limit)), args, query)
        return 0
    links = search_links(query) if not outcome.found else None
    _emit(render_search(outcome, query, limit=args.limit, links=links), args, query)
    return 0 if outcome.found else 1


def cmd_analyze(args: argparse.Namespace) -> int:
    from .analysis.pipeline import analyze_file

    with ExitStack() as stack:
        path, ref, audio = _obtain_audio(args.audio, args, stack)
        if audio is not None:
            print(f"analysing {audio.describe()}", file=sys.stderr)
        analysis = analyze_file(
            path,
            offset=args.start,
            duration=args.duration,
            beats_per_bar=args.beats_per_bar,
            change_penalty=args.sensitivity,
            with_melody=args.melody,
            # Name the report after the track, not after the temp file it
            # happened to be downloaded to.
            title=args.title or (ref.display if ref else None),
            with_solo=args.solo,
            solo_range=_solo_range(args),
            use_demucs=args.demucs,
        )
    _label_analysis(analysis, ref, audio)
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
    given = " ".join(args.query)
    ref: Optional[TrackRef] = None
    query = given

    # A link tells us both what to search for and where to get audio.
    if is_url(given):
        ref = resolve_track(given, timeout=args.timeout)
        query = ref.query
        print(f"link resolves to: {ref.display}\n", file=sys.stderr)

    outcome = search_tabs(query, limit=args.limit, timeout=args.timeout)
    links = search_links(query) if not outcome.found else None

    # Analyse when asked to, or when the search came up empty and we have a
    # way to get the audio.
    have_audio_source = bool(args.audio) or ref is not None
    should_analyze = have_audio_source and (args.always_analyze or not outcome.found)

    sections: List[str] = [
        render_search(
            outcome, query, limit=args.limit, links=links,
            suggest_analysis=not should_analyze,
        )
    ]
    if should_analyze:
        from .analysis.pipeline import analyze_file

        with ExitStack() as stack:
            source = args.audio or given
            try:
                path, audio_ref, audio = _obtain_audio(source, args, stack)
            except SourceError as exc:
                sections.append(heading("COULD NOT ANALYSE THE AUDIO"))
                sections.append("  " + str(exc).replace("\n", "\n  "))
                _emit("\n".join(sections), args, query)
                return 1
            if audio is not None:
                print(f"analysing {audio.describe()}", file=sys.stderr)
            analysis = analyze_file(path, with_melody=args.melody, title=query)
        _label_analysis(analysis, audio_ref or ref, audio)
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
    elif not outcome.found:
        sections.append(
            "\n  Tip: pass a YouTube, Spotify or Apple Music link (or --audio with a\n"
            "  local file) and this will work out the key and chords for you."
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


def cmd_solo(args: argparse.Namespace) -> int:
    from .analysis.pipeline import analyze_file

    solo_range = _solo_range(args)
    with ExitStack() as stack:
        path, ref, audio = _obtain_audio(args.audio, args, stack)
        if audio is not None:
            print(f"analysing {audio.describe()}", file=sys.stderr)
        if solo_range is None:
            print("looking for the solo...", file=sys.stderr)
        analysis = analyze_file(
            path,
            title=args.title or (ref.display if ref else None),
            with_solo=True,
            solo_range=solo_range,
            use_demucs=args.demucs,
        )
    _label_analysis(analysis, ref, audio)

    if args.json:
        _emit(to_json(analysis), args, analysis.title or "solo")
        return 0
    if analysis.solo is None:
        print(
            "error: no lead line stood out clearly enough to tab.\n"
            "Try naming the section yourself:  --solo-from 2:14 --solo-to 2:48",
            file=sys.stderr,
        )
        return 1
    _emit(
        render_solo(analysis.solo, _board(args), analysis.solo_candidates),
        args,
        analysis.title or "Solo",
    )
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


def cmd_serve(args: argparse.Namespace) -> int:
    from .web import create_app

    url = f"http://{args.host}:{args.port}"
    print(f"tabfinder web UI on {url}")
    if args.host not in ("127.0.0.1", "localhost"):
        print(
            "  note: this binds beyond localhost and has no authentication.\n"
            "  Only do this on a network you trust.",
            file=sys.stderr,
        )
    if args.open:
        import threading
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    create_app().run(host=args.host, port=args.port, debug=args.debug, threaded=True)
    return 0


def cmd_tunings(_args: argparse.Namespace) -> int:
    print("Available tunings (low string first):\n")
    for name, strings in sorted(TUNINGS.items()):
        print(f"  {name:<18} {' '.join(strings)}")
    return 0


COMMANDS = {
    "find": cmd_find,
    "analyze": cmd_analyze,
    "solo": cmd_solo,
    "song": cmd_song,
    "chord": cmd_chord,
    "key": cmd_key,
    "serve": cmd_serve,
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
    except (NoteParseError, ValueError, FileNotFoundError, SourceError) as exc:
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
