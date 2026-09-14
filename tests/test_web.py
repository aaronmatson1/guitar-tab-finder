"""The web UI's API."""

from __future__ import annotations

import json
import time

import pytest

pytest.importorskip("flask")

from tabfinder.search import SOURCES  # noqa: E402
from tabfinder.search.base import TabResult  # noqa: E402
from tabfinder.web.app import create_app  # noqa: E402
from tabfinder.web.jobs import JobRegistry  # noqa: E402


@pytest.fixture
def client(tmp_path):
    app = create_app(upload_dir=str(tmp_path / "uploads"))
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def offline_sources(monkeypatch):
    """Stub the tab sources so no test touches the network."""

    def install(results):
        class Stub:
            name = "stub"

            def search(self, query, limit=10, timeout=8.0):
                return list(results)

        for name in list(SOURCES):
            monkeypatch.setitem(SOURCES, name, Stub())

    return install


def wait_for(client, job_id, timeout=180.0):
    """Poll a job until it finishes, the way the browser does."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = json.loads(client.get(f"/api/jobs/{job_id}").data)
        if payload["status"] in ("done", "error"):
            return payload
        time.sleep(0.3)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


# --- pages and static ----------------------------------------------------


def test_index_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.data.decode()
    assert "guitar-tab-finder" in body
    assert 'id="query"' in body
    assert "standard" in body  # the tuning list was filled in


def test_static_assets_are_served(client):
    for path in ("/static/app.js", "/static/style.css"):
        assert client.get(path).status_code == 200


# --- chords and keys -----------------------------------------------------


def test_chord_endpoint_returns_drawable_shapes(client):
    payload = json.loads(client.get("/api/chord?symbol=Am7&limit=2").data)
    assert payload["chord"] == "Am7"
    assert payload["notes"] == ["A", "C", "E", "G"]
    assert payload["shapes"][0]["frets"] == [None, 0, 2, 0, 1, 0]
    assert payload["shapes"][0]["text"] == "x02010"
    assert payload["strings"] == ["E", "A", "D", "G", "B", "e"]


def test_chord_endpoint_honours_tuning_and_capo(client):
    payload = json.loads(client.get("/api/chord?symbol=C&capo=3&limit=1").data)
    frets = [f for f in payload["shapes"][0]["frets"] if f is not None]
    assert all(f >= 3 for f in frets)

    payload = json.loads(client.get("/api/chord?symbol=D&tuning=drop-d&limit=1").data)
    assert payload["shapes"]


def test_chord_endpoint_rejects_nonsense(client):
    assert client.get("/api/chord?symbol=Zq9").status_code == 400
    assert client.get("/api/chord?symbol=").status_code == 400


def test_chord_endpoint_survives_a_bad_tuning(client):
    # An unknown tuning falls back to standard rather than erroring.
    payload = json.loads(client.get("/api/chord?symbol=C&tuning=klingon&limit=1").data)
    assert payload["shapes"][0]["text"] == "x32010"


def test_key_endpoint(client):
    payload = json.loads(client.get("/api/key?key=E+minor").data)
    assert payload["key"] == "E minor"
    assert [c["chord"] for c in payload["chords"]][0] == "Em"
    assert payload["chords"][0]["shapes"][0]["frets"] == [0, 2, 2, 0, 0, 0]


def test_key_endpoint_rejects_nonsense(client):
    assert client.get("/api/key?key=H+lydian").status_code == 400


# --- search --------------------------------------------------------------


def test_search_returns_ranked_results(client, offline_sources):
    offline_sources([TabResult("Creep", "Radiohead", "https://x/1", "Songsterr", rating=4.9, votes=900)])
    payload = json.loads(client.post("/api/search", json={"query": "Radiohead - Creep"}).data)
    assert payload["results"][0]["url"] == "https://x/1"
    assert payload["links"]  # manual search links are always offered


def test_search_needs_a_query(client):
    assert client.post("/api/search", json={"query": "  "}).status_code == 400


def test_search_resolves_a_link(client, offline_sources, monkeypatch):
    import tabfinder.web.app as web_app
    from tabfinder.sources.refs import TrackRef

    ref = TrackRef("youtube", "https://youtu.be/abc", "abc", "Wonderwall", "Oasis")
    monkeypatch.setattr(web_app, "resolve_track", lambda url, timeout=10.0: ref)
    offline_sources([])
    payload = json.loads(client.post("/api/search", json={"query": "https://youtu.be/abc"}).data)
    assert payload["track"]["artist"] == "Oasis"
    assert payload["query"] == "Oasis - Wonderwall"


def test_search_reports_a_bad_link(client, monkeypatch):
    payload = client.post("/api/search", json={"query": "https://example.com/nope"})
    assert payload.status_code == 400
    assert "unsupported" in json.loads(payload.data)["error"].lower()


# --- analysis ------------------------------------------------------------


def test_analyze_rejects_a_plain_title(client):
    response = client.post("/api/analyze", json={"source": "wonderwall"})
    assert response.status_code == 400
    assert "not a link" in json.loads(response.data)["error"]


def test_analyze_needs_a_source(client):
    assert client.post("/api/analyze", json={}).status_code == 400


def test_upload_rejects_a_non_audio_file(client, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("not audio")
    with open(bad, "rb") as handle:
        response = client.post("/api/upload", data={"audio": (handle, "notes.txt")},
                               content_type="multipart/form-data")
    assert response.status_code == 400
    assert "not audio" in json.loads(response.data)["error"]


def test_upload_needs_a_file(client):
    assert client.post("/api/upload", data={}, content_type="multipart/form-data").status_code == 400


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/doesnotexist").status_code == 404


@pytest.mark.audio
def test_upload_and_analyse_end_to_end(client, tmp_path, np):
    """The whole browser flow: upload audio, poll, get a tab back."""
    pytest.importorskip("librosa")
    soundfile = pytest.importorskip("soundfile")
    from conftest import SHAPES, synth_progression

    audio = synth_progression(np, [SHAPES[n] for n in ["G", "D", "Em", "C"]], bpm=100)
    path = tmp_path / "demo.wav"
    soundfile.write(str(path), audio, 22050)

    with open(path, "rb") as handle:
        response = client.post(
            "/api/upload",
            data={"audio": (handle, "demo.wav"), "solo": "false", "tuning": "standard"},
            content_type="multipart/form-data",
        )
    assert response.status_code == 202
    job = json.loads(response.data)

    finished = wait_for(client, job["id"])
    assert finished["status"] == "done", finished.get("error")
    result = finished["result"]
    assert result["key"]["name"] == "G major"
    assert result["progression"]["loop"] == ["G", "D", "Em", "C"]
    assert result["rhythm_tab"] and "e |" in result["rhythm_tab"]
    # Every shape must be drawable by the browser.
    assert result["shapes"] and all(len(s["frets"]) == 6 for s in result["shapes"])
    assert result["title"] == "demo"


# --- the job registry ----------------------------------------------------


def test_jobs_run_and_report_results():
    registry = JobRegistry()
    job = registry.submit("test", lambda job: {"answer": 42})
    for _ in range(100):
        if registry.get(job.id).status == "done":
            break
        time.sleep(0.02)
    assert registry.get(job.id).to_dict()["result"] == {"answer": 42}


def test_jobs_capture_failures_as_messages():
    registry = JobRegistry()

    def explode(job):
        raise ValueError("that link is region-locked")

    job = registry.submit("test", explode)
    for _ in range(100):
        if registry.get(job.id).status == "error":
            break
        time.sleep(0.02)
    payload = registry.get(job.id).to_dict()
    assert payload["status"] == "error"
    assert payload["error"] == "that link is region-locked"


def test_jobs_report_progress():
    registry = JobRegistry()
    started = []

    def slow(job):
        job.progress = "halfway"
        started.append(True)
        return "ok"

    job = registry.submit("test", slow)
    for _ in range(100):
        if registry.get(job.id).status == "done":
            break
        time.sleep(0.02)
    assert registry.get(job.id).progress == "halfway"
