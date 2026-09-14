"""A local web front end for tabfinder.

Everything the command line does, in a browser: search for a tab, paste a
music link, drop an audio file, get the key, the chords, the shapes and the
solo. Analysis runs on a worker thread and the page polls for the result, so a
long job never holds a request open.

This is a local tool. It binds to localhost by default and has no
authentication; do not expose it to a network you do not trust.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from ..guitar.fretboard import TUNINGS, Fretboard
from ..guitar.render import render_tab, voicings_to_columns
from ..guitar.voicings import generate_voicings
from ..search import search_links, search_tabs
from ..sources import AudioPolicy, SourceError, acquire_audio, is_url, resolve_track
from ..theory.chords import parse_chord
from ..theory.notes import NoteParseError, note_name
from ..theory.scales import Key
from .jobs import Job, JobRegistry

#: Uploads bigger than this are refused outright.
MAX_UPLOAD_BYTES = 80 * 1024 * 1024

ALLOWED_AUDIO = {".wav", ".mp3", ".flac", ".ogg", ".oga", ".m4a", ".aiff", ".aif", ".aac", ".wma"}


def create_app(upload_dir: Optional[str] = None) -> "object":
    """Build the Flask application."""
    try:
        from flask import Flask, jsonify, request
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            "The web UI needs Flask. Install it with:\n"
            "    pip install 'guitar-tab-finder[web]'"
        ) from exc

    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    jobs = JobRegistry()
    uploads = Path(upload_dir) if upload_dir else Path(tempfile.gettempdir()) / "tabfinder-uploads"
    uploads.mkdir(parents=True, exist_ok=True)

    # --- pages ------------------------------------------------------------

    @app.route("/")
    def index():
        from flask import render_template

        return render_template("index.html", tunings=sorted(TUNINGS))

    # --- fast, synchronous endpoints --------------------------------------

    @app.post("/api/search")
    def api_search():
        payload = request.get_json(silent=True) or {}
        query = str(payload.get("query", "")).strip()
        if not query:
            return jsonify({"error": "Type a song name, or paste a link."}), 400

        track = None
        if is_url(query):
            try:
                ref = resolve_track(query, timeout=10.0)
                track = {"title": ref.title, "artist": ref.artist, "provider": ref.provider,
                         "display": ref.display}
                query = ref.query
            except SourceError as exc:
                return jsonify({"error": str(exc)}), 400

        outcome = search_tabs(query, limit=8, timeout=8.0)
        return jsonify({
            "query": query,
            "track": track,
            "results": [
                {"title": r.title, "artist": r.artist, "url": r.url, "source": r.source,
                 "kind": r.kind, "rating": r.rating, "votes": r.votes}
                for r in outcome.ranked(query, limit=8)
            ],
            "errors": outcome.errors,
            "links": [{"source": l.source, "url": l.url} for l in search_links(query)],
        })

    @app.get("/api/chord")
    def api_chord():
        symbol = request.args.get("symbol", "").strip()
        board = _board(request.args.get("tuning"), request.args.get("capo"))
        if not symbol:
            return jsonify({"error": "no chord given"}), 400
        try:
            chord = parse_chord(symbol)
        except NoteParseError as exc:
            return jsonify({"error": str(exc)}), 400
        shapes = generate_voicings(chord, board, limit=int(request.args.get("limit", 3)))
        return jsonify({
            "chord": chord.symbol(),
            "quality": chord.quality.name,
            "notes": [note_name(pc) for pc in chord.core_pitch_classes],
            "shapes": [_shape(v) for v in shapes],
            "strings": board.string_labels(),
        })

    @app.get("/api/key")
    def api_key():
        try:
            key = _parse_key(request.args.get("key", "C"))
        except (ValueError, NoteParseError) as exc:
            return jsonify({"error": str(exc)}), 400
        board = _board(request.args.get("tuning"), request.args.get("capo"))
        sevenths = request.args.get("sevenths") == "true"
        return jsonify({
            "key": key.name,
            "scale": key.scale_notes(),
            "pentatonic": key.pentatonic(),
            "relative": key.relative.name,
            "chords": [
                {"numeral": numeral, "chord": chord.symbol(key.prefer_flats),
                 "shapes": [_shape(v) for v in generate_voicings(chord, board, limit=1)]}
                for numeral, chord in key.diatonic_chords(sevenths=sevenths)
            ],
            "strings": board.string_labels(),
        })

    # --- background analysis ----------------------------------------------

    @app.post("/api/analyze")
    def api_analyze():
        payload = request.get_json(silent=True) or {}
        source = str(payload.get("source", "")).strip()
        if not source:
            return jsonify({"error": "Paste a YouTube, Spotify or Apple Music link."}), 400
        if not is_url(source):
            return jsonify({
                "error": "That is not a link. Search for it by name, or upload an audio file."
            }), 400
        options = _options(payload)
        job = jobs.submit("analyze", lambda job: _analyze_link(job, source, options))
        return jsonify(job.to_dict()), 202

    @app.post("/api/upload")
    def api_upload():
        upload = request.files.get("audio")
        if upload is None or not upload.filename:
            return jsonify({"error": "No file was sent."}), 400
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in ALLOWED_AUDIO:
            return jsonify({
                "error": f"{suffix or 'That file type'} is not audio. "
                         f"Try {', '.join(sorted(ALLOWED_AUDIO))}."
            }), 400

        target = uploads / f"{os.urandom(8).hex()}{suffix}"
        upload.save(str(target))
        options = _options(request.form)
        options["title"] = Path(upload.filename).stem
        job = jobs.submit("analyze", lambda job: _analyze_file(job, target, options, cleanup=True))
        return jsonify(job.to_dict()), 202

    @app.get("/api/jobs/<job_id>")
    def api_job(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            return jsonify({"error": "That job has expired or never existed."}), 404
        return jsonify(job.to_dict())

    @app.get("/api/tunings")
    def api_tunings():
        return jsonify({"tunings": sorted(TUNINGS)})

    @app.errorhandler(413)
    def too_large(_exc):
        return jsonify({
            "error": f"That file is bigger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        }), 413

    return app


# --- the work itself ------------------------------------------------------


def _options(payload) -> Dict[str, Any]:
    """Read analysis options out of a JSON body or a form."""
    def flag(name: str) -> bool:
        value = payload.get(name)
        return value in (True, "true", "on", "1", 1)

    return {
        "tuning": payload.get("tuning") or "standard",
        "capo": int(payload.get("capo") or 0),
        "solo": flag("solo"),
        "melody": flag("melody"),
        "allow_download": flag("allow_download"),
        "title": payload.get("title") or None,
    }


def _analyze_link(job: Job, source: str, options: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve a link, fetch what audio we are allowed to, and analyse it."""
    import tempfile as _tempfile

    job.progress = "Looking up the link..."
    ref = resolve_track(source, timeout=10.0)

    job.progress = f"Getting audio for {ref.display}..."
    with _tempfile.TemporaryDirectory(prefix="tabfinder-web-") as work:
        audio = acquire_audio(
            ref, Path(work),
            AudioPolicy(allow_download=options["allow_download"], timeout=30.0),
        )
        result = _run_analysis(job, audio.path, options, title=ref.display)
    result["source_label"] = audio.describe()
    result["partial"] = audio.is_preview
    result["track"] = {"title": ref.title, "artist": ref.artist, "provider": ref.provider}
    return result


def _analyze_file(job: Job, path: Path, options: Dict[str, Any], cleanup: bool = False) -> Dict[str, Any]:
    """Analyse a file the user uploaded."""
    try:
        return _run_analysis(job, path, options, title=options.get("title"))
    finally:
        if cleanup:
            path.unlink(missing_ok=True)


def _run_analysis(job: Job, path: Path, options: Dict[str, Any], title: Optional[str]) -> Dict[str, Any]:
    """The shared analysis body, whatever the audio came from."""
    from ..analysis.pipeline import analyze_file

    job.progress = "Listening for the key and chords..."
    analysis = analyze_file(
        str(path),
        with_melody=options["melody"],
        with_solo=options["solo"],
        title=title,
    )
    if options["solo"]:
        job.progress = "Working out the solo..."

    board = _board(options["tuning"], options["capo"])
    payload = analysis.to_dict()
    payload["tuning"] = board.describe()
    payload["shapes"] = [
        _shape(voicing) for voicing in analysis.voicings(board, per_chord=1)
    ]
    payload["strings"] = board.string_labels()
    payload["rhythm_tab"] = _rhythm_tab(analysis, board)
    payload["solo_tab"] = _solo_tab(analysis, board)
    return payload


def _rhythm_tab(analysis, board: Fretboard) -> Optional[str]:
    """One bar of downstrokes per chord in the loop, as monospace tab."""
    loop = analysis.loop
    if not loop:
        return None
    voicings = [v for chord in loop for v in generate_voicings(chord, board, limit=1)]
    if not voicings:
        return None
    columns, labels = voicings_to_columns(voicings, strums_per_chord=4)
    return render_tab(columns, board, labels, beats_per_bar=4, line_width=76)


def _solo_tab(analysis, board: Fretboard) -> Optional[Dict[str, Any]]:
    """The solo as tab, plus a legend for whatever technique it uses."""
    solo = getattr(analysis, "solo", None)
    if solo is None or not solo.notes:
        return None
    from ..analysis.articulation import technique_legend
    from ..guitar.arrange import place_notes, position_summary
    from ..guitar.render import solo_to_columns

    placements = place_notes(solo.notes, board)
    columns, labels = solo_to_columns(placements, solo.notes)
    return {
        "section": solo.section.label(),
        "start": round(solo.section.start, 2),
        "end": round(solo.section.end, 2),
        "notes": solo.note_count,
        "position": position_summary(placements),
        "separated": solo.separated,
        "tab": render_tab(columns, board, labels, beats_per_bar=8, line_width=76),
        "legend": [line.strip() for line in technique_legend(solo.notes)],
    }


# --- small helpers --------------------------------------------------------


def _board(tuning: Optional[str], capo: Optional[Any]) -> Fretboard:
    try:
        fret = max(0, int(capo or 0))
    except (TypeError, ValueError):
        fret = 0
    try:
        return Fretboard.from_tuning(tuning or "standard", capo=fret)
    except ValueError:
        return Fretboard.from_tuning("standard", capo=fret)


def _shape(voicing) -> Dict[str, Any]:
    """A chord shape in the form the browser draws diagrams from."""
    return {
        "chord": voicing.chord.symbol(),
        "frets": list(voicing.frets),
        "text": voicing.fret_string(),
        "difficulty": voicing.difficulty,
        "barre": voicing.barre,
        "position": voicing.position_label(),
        "notes": voicing.note_names(),
    }


def _parse_key(text: str) -> Key:
    from ..cli import parse_key

    return parse_key(text)
