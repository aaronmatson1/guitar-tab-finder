"""The command line interface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tabfinder.cli import main, parse_key
from tabfinder.search import SOURCES
from tabfinder.search.base import TabResult
from tabfinder.theory.scales import Key


@pytest.fixture(scope="module")
def wav_file(tmp_path_factory):
    """A short synthetic progression on disk, for the link tests to analyse."""
    pytest.importorskip("librosa")
    np = pytest.importorskip("numpy")
    soundfile = pytest.importorskip("soundfile")
    from conftest import SHAPES, synth_progression

    audio = synth_progression(np, [SHAPES[n] for n in ["G", "D", "Em", "C"]], bpm=100)
    path = tmp_path_factory.mktemp("audio") / "clip.wav"
    soundfile.write(str(path), audio, 22050)
    return path


@pytest.fixture
def offline(monkeypatch):
    """Replace the live sources with a stub, so no test touches the network."""

    class Stub:
        name = "stub"

        def __init__(self, results):
            self._results = results

        def search(self, query, limit=10, timeout=8.0):
            return list(self._results)

    def install(results):
        for name in list(SOURCES):
            monkeypatch.setitem(SOURCES, name, Stub(results if name == "songsterr" else []))

    return install


@pytest.mark.parametrize(
    "text,expected",
    [
        ("C", Key(0, "major")),
        ("E minor", Key(4, "minor")),
        ("Bb major", Key(10, "major")),
        ("f# minor", Key(6, "minor")),
        ("Am", Key(9, "minor")),
    ],
)
def test_parse_key(text, expected):
    assert parse_key(text) == expected


def test_parse_key_rejects_unknown_mode():
    with pytest.raises(ValueError, match="unknown mode"):
        parse_key("C lydian")


def test_tunings_command_lists_tunings(capsys):
    assert main(["tunings"]) == 0
    out = capsys.readouterr().out
    assert "standard" in out and "drop-d" in out


def test_chord_command_shows_shapes(capsys):
    assert main(["chord", "Am7"]) == 0
    out = capsys.readouterr().out
    assert "x02010" in out
    assert "E A D G B e" in out


def test_chord_command_json(capsys):
    assert main(["chord", "C", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["chord"] == "C"
    assert payload[0]["shapes"][0]["frets"] == "x32010"


def test_chord_command_respects_tuning_and_capo(capsys):
    assert main(["chord", "D", "--tuning", "drop-d", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["shapes"]

    assert main(["chord", "C", "--capo", "3", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    frets = payload[0]["shapes"][0]["frets"]
    digits = [int(c) for c in frets.replace("-", " ").split() if c.isdigit()] or [
        int(c) for c in frets if c.isdigit()
    ]
    assert all(f >= 3 for f in digits)


def test_chord_command_rejects_nonsense(capsys):
    assert main(["chord", "Hmmm7"]) == 2
    assert "error" in capsys.readouterr().err


def test_key_command(capsys):
    assert main(["key", "E", "minor"]) == 0
    out = capsys.readouterr().out
    assert "E minor" in out
    assert "Em" in out and "Bm" in out


def test_key_command_json_with_sevenths(capsys):
    assert main(["key", "C", "--sevenths", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["key"] == "C major"
    assert payload["chords"][4]["chord"] == "G7"
    assert payload["pentatonic"] == ["C", "D", "E", "G", "A"]


def test_find_command_lists_results(offline, capsys):
    offline([TabResult("Creep", "Radiohead", "https://x/1", "Songsterr", rating=4.9, votes=900)])
    assert main(["find", "Radiohead", "-", "Creep"]) == 0
    out = capsys.readouterr().out
    assert "Radiohead - Creep" in out
    assert "https://x/1" in out


def test_find_command_json(offline, capsys):
    offline([TabResult("Creep", "Radiohead", "https://x/1", "Songsterr")])
    assert main(["find", "Creep", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["url"] == "https://x/1"


def test_find_command_reports_nothing_found(offline, capsys):
    offline([])
    # Exit code 1 says "searched fine, found nothing" - useful in a script.
    assert main(["find", "An Obscure B-Side"]) == 1
    out = capsys.readouterr().out
    assert "No published tabs found" in out
    assert "tabfinder analyze" in out  # points at the fallback
    assert "ultimate-guitar.com/search" in out  # and offers manual links


def test_find_command_writes_to_a_file(offline, capsys, tmp_path):
    offline([TabResult("Creep", "Radiohead", "https://x/1", "Songsterr")])
    target = tmp_path / "tabs.md"
    assert main(["find", "Creep", "--out", str(target), "--markdown"]) == 0
    text = target.read_text()
    assert text.startswith("# Creep")
    assert "```" in text
    assert "wrote" in capsys.readouterr().out


def test_song_command_without_audio_suggests_analysis(offline, capsys):
    offline([])
    assert main(["song", "Nobody Has Tabbed This"]) == 0
    out = capsys.readouterr().out
    assert "--audio" in out


def test_song_command_skips_analysis_when_a_tab_exists(offline, capsys):
    offline([TabResult("Creep", "Radiohead", "https://x/1", "Songsterr")])
    # No --audio given, so nothing to analyse; it should still succeed.
    assert main(["song", "Creep"]) == 0
    assert "https://x/1" in capsys.readouterr().out


def test_missing_audio_file_is_reported(capsys):
    assert main(["analyze", "/nonexistent/song.mp3"]) == 2
    assert "error" in capsys.readouterr().err


def test_unknown_tuning_is_reported(capsys):
    assert main(["chord", "C", "--tuning", "klingon"]) == 2
    assert "unknown tuning" in capsys.readouterr().err


# --- music links ---------------------------------------------------------


@pytest.fixture
def stub_link(monkeypatch, tmp_path):
    """Make a link resolve to a known track, with audio already on disk."""
    import tabfinder.cli as cli
    from tabfinder.sources import AudioSource
    from tabfinder.sources.refs import TrackRef

    def install(audio_path=None, kind="preview", title="Wonderwall", artist="Oasis"):
        ref = TrackRef("youtube", "https://youtu.be/abc", "abc", title, artist)
        monkeypatch.setattr(cli, "resolve_track", lambda url, timeout=10.0: ref)
        if audio_path is not None:
            source = AudioSource(
                path=Path(audio_path), kind=kind, origin="Apple Music", seconds=30.0
            )
            monkeypatch.setattr(
                cli, "acquire_audio", lambda r, directory, policy=None: source
            )
        return ref

    return install


def test_find_accepts_a_link(offline, stub_link, capsys):
    stub_link()
    offline([TabResult("Wonderwall", "Oasis", "https://x/1", "Songsterr")])
    assert main(["find", "https://youtu.be/abc"]) == 0
    captured = capsys.readouterr()
    assert "link resolves to: Wonderwall — Oasis" in captured.err
    assert "https://x/1" in captured.out


def test_song_with_a_link_searches_by_the_resolved_name(offline, stub_link, capsys):
    stub_link()
    offline([TabResult("Wonderwall", "Oasis", "https://x/1", "Songsterr")])
    assert main(["song", "https://youtu.be/abc"]) == 0
    out = capsys.readouterr().out
    assert "Tabs for: Oasis - Wonderwall" in out
    assert "https://x/1" in out


def test_song_with_a_link_analyses_when_no_tab_is_found(offline, stub_link, wav_file, capsys):
    stub_link(audio_path=wav_file)
    offline([])
    assert main(["song", "https://youtu.be/abc"]) == 0
    out = capsys.readouterr().out
    assert "No published tabs found" in out
    assert "KEY" in out and "CHORD SHAPES" in out


def test_analyze_accepts_a_link_and_flags_a_preview(stub_link, wav_file, capsys):
    stub_link(audio_path=wav_file)
    assert main(["analyze", "https://youtu.be/abc"]) == 0
    out = capsys.readouterr().out
    assert "source 30s preview clip from Apple Music" in out
    assert "this is a clip, not the whole song" in out
    assert "preview clip" in out  # and again in the accuracy notes


def test_analyze_link_json_records_provenance(stub_link, wav_file, capsys):
    stub_link(audio_path=wav_file)
    assert main(["analyze", "https://youtu.be/abc", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["partial"] is True
    assert "Apple Music" in payload["source_label"]
    assert payload["title"] == "Wonderwall — Oasis"


def test_full_audio_is_not_flagged_as_partial(stub_link, wav_file, capsys):
    stub_link(audio_path=wav_file, kind="full")
    assert main(["analyze", "https://youtu.be/abc", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["partial"] is False


def test_song_reports_when_audio_cannot_be_had(offline, monkeypatch, capsys):
    import tabfinder.cli as cli
    from tabfinder.sources import AudioNotAvailable
    from tabfinder.sources.refs import TrackRef

    ref = TrackRef("spotify", "https://open.spotify.com/track/x", "x", "Obscure", "Nobody")
    monkeypatch.setattr(cli, "resolve_track", lambda url, timeout=10.0: ref)

    def no_audio(r, directory, policy=None):
        raise AudioNotAvailable("Spotify streams are DRM-protected")

    monkeypatch.setattr(cli, "acquire_audio", no_audio)
    offline([])
    assert main(["song", "https://open.spotify.com/track/x"]) == 1
    out = capsys.readouterr().out
    assert "COULD NOT ANALYSE THE AUDIO" in out
    assert "DRM" in out


def test_a_bad_link_is_a_clean_error(capsys):
    assert main(["find", "https://example.com/not-music"]) == 2
    assert "unsupported link" in capsys.readouterr().err
