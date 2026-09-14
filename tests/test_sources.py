"""Resolving music links, and getting audio for them."""

from __future__ import annotations

from pathlib import Path

import pytest

from tabfinder.sources import (
    AudioNotAvailable,
    AudioPolicy,
    SourceError,
    TrackNotFound,
    UnsupportedURL,
    acquire_audio,
    identify,
    is_url,
    resolve_track,
)
from tabfinder.sources import apple, spotify, youtube
from tabfinder.sources.fetch import NATIVE_AUDIO_SUFFIXES, ensure_readable
from tabfinder.sources.refs import TrackRef, clean_title, split_artist_title

# --- recognising links ---------------------------------------------------


@pytest.mark.parametrize(
    "url,provider,track_id",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube", "dQw4w9WgXcQ"),
        ("https://youtu.be/bx1Bh8ZvH84?t=30", "youtube", "bx1Bh8ZvH84"),
        ("https://music.youtube.com/watch?v=abc12345678", "youtube", "abc12345678"),
        ("https://www.youtube.com/shorts/xyz98765432", "youtube", "xyz98765432"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "youtube", "dQw4w9WgXcQ"),
        ("https://open.spotify.com/track/7ygpwy2qP3?si=x", "spotify", "7ygpwy2qP3"),
        ("https://open.spotify.com/intl-de/track/1AbCdEf", "spotify", "1AbCdEf"),
        ("spotify:track:7ygpwy2qP3NbrxVkHvUhXY", "spotify", "7ygpwy2qP3NbrxVkHvUhXY"),
        ("https://music.apple.com/us/album/x/1440830900?i=1440831165", "apple", "1440831165"),
    ],
)
def test_identify_links(url, provider, track_id):
    assert identify(url) == (provider, track_id)


@pytest.mark.parametrize(
    "url,hint",
    [
        ("https://example.com/song.mp3", "unsupported link"),
        ("https://open.spotify.com/playlist/37i9", "playlist"),
        ("https://open.spotify.com/album/123", "album"),
        ("https://music.apple.com/us/album/whats-the-story/1440830900", "whole album"),
        ("spotify:album:123", "track links"),
        ("https://www.youtube.com/playlist?list=PL123", "playlist"),
    ],
)
def test_unsupported_links_explain_themselves(url, hint):
    with pytest.raises(UnsupportedURL, match=hint):
        identify(url)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("https://youtu.be/abc", True),
        ("spotify:track:abc", True),
        ("Oasis - Wonderwall", False),
        ("Wonderwall", False),
        ("", False),
    ],
)
def test_is_url(text, expected):
    assert is_url(text) is expected


# --- tidying titles ------------------------------------------------------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Oasis - Wonderwall (Official Video)", "Oasis - Wonderwall"),
        ("a-ha - Take On Me (Official Video) [Remastered in 4K]", "a-ha - Take On Me"),
        ("Creep [OFFICIAL MUSIC VIDEO] (HD)", "Creep"),
        ("Wonderwall (Remastered 2014)", "Wonderwall"),
        ("Some Song - Official Audio", "Some Song"),
    ],
)
def test_clean_title_strips_clutter(title, expected):
    assert clean_title(title) == expected


def test_clean_title_keeps_meaningful_brackets():
    # A live version is a different arrangement, so the label matters.
    assert clean_title("Come As You Are (Live at Reading 1992)").endswith("(Live at Reading 1992)")
    assert "feat" in clean_title("Song (feat. Another Artist)")


def test_split_uses_the_channel_when_there_is_no_dash():
    assert split_artist_title("Wonderwall", "OasisVEVO") == ("Oasis", "Wonderwall")
    assert split_artist_title("Wonderwall", "Oasis - Topic") == ("Oasis", "Wonderwall")


def test_split_fixes_a_reversed_title():
    # "Song - Artist" is as common as "Artist - Song"; the channel disambiguates.
    assert split_artist_title("Wonderwall - Oasis", "Oasis") == ("Oasis", "Wonderwall")
    assert split_artist_title("Oasis - Wonderwall", "Oasis") == ("Oasis", "Wonderwall")


# --- per-provider parsing ------------------------------------------------


def test_youtube_oembed_parsing():
    ref = youtube.parse_oembed(
        {"title": "Oasis - Wonderwall (Official Video)", "author_name": "OasisVEVO"},
        "abc",
        "https://youtu.be/abc",
    )
    assert (ref.artist, ref.title) == ("Oasis", "Wonderwall")
    assert ref.query == "Oasis - Wonderwall"
    assert ref.provider == "youtube"


def test_youtube_oembed_without_a_title_is_an_error():
    with pytest.raises(TrackNotFound):
        youtube.parse_oembed({"author_name": "x"}, "abc", "u")


def test_youtube_error_extraction():
    stderr = "WARNING: something\nERROR: Video unavailable\ntrailing noise"
    assert youtube._first_error(stderr) == "ERROR: Video unavailable"
    assert youtube._first_error("") == "unknown error"


def test_youtube_finds_its_downloaded_file(tmp_path):
    created = tmp_path / "abc.m4a"
    created.write_bytes(b"x")
    assert youtube._downloaded_path(str(created), tmp_path) == created
    # Falls back to scanning the folder when the output is not a path.
    assert youtube._downloaded_path("nonsense", tmp_path) == created
    assert youtube._downloaded_path("", tmp_path / "empty") is None


def test_youtube_download_without_yt_dlp_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(youtube, "yt_dlp_available", lambda: False)
    with pytest.raises(AudioNotAvailable, match="yt-dlp"):
        youtube.download_audio("https://youtu.be/abc", tmp_path)


def test_apple_lookup_parsing():
    payload = {
        "resultCount": 1,
        "results": [
            {
                "kind": "song",
                "trackId": 1440831165,
                "trackName": "Wonderwall",
                "artistName": "Oasis",
                "trackTimeMillis": 258613,
                "previewUrl": "https://audio-ssl.itunes.apple.com/x.m4a",
            }
        ],
    }
    ref = apple.parse_results(payload)[0]
    assert (ref.title, ref.artist) == ("Wonderwall", "Oasis")
    assert ref.duration == pytest.approx(258.6, abs=0.1)
    assert ref.preview_url.endswith(".m4a")


def test_apple_ignores_non_songs_and_garbage():
    assert apple.parse_results({"results": [{"kind": "podcast", "trackName": "x"}]}) == []
    assert apple.parse_results("not a dict") == []
    assert apple.parse_results({"results": "nope"}) == []


def test_apple_picks_the_closest_match():
    tracks = [
        TrackRef("apple", "u", "1", "Wonderwall (Live)", "Some Cover Band", preview_url="a"),
        TrackRef("apple", "u", "2", "Wonderwall", "Oasis", preview_url="b"),
    ]
    assert apple._best_match(tracks, "Wonderwall", "Oasis").track_id == "2"


def test_spotify_reads_opengraph_tags():
    page = (
        '<meta property="og:title" content="Wonderwall">'
        '<meta property="og:description" content="Oasis &#183; Song &#183; 1995">'
    )
    ref = spotify.parse_page(page, "id", "u")
    assert (ref.title, ref.artist) == ("Wonderwall", "Oasis")


def test_spotify_merges_partial_lookups():
    from_oembed = TrackRef("spotify", "u", "id", "Wonderwall", None)
    from_page = TrackRef("spotify", "u", "id", "Wonderwall", "Oasis")
    merged = spotify._merge(from_oembed, from_page, "id")
    assert merged.artist == "Oasis"
    assert spotify._merge(None, from_page, "id").artist == "Oasis"
    assert spotify._merge(from_oembed, None, "id").title == "Wonderwall"


def test_spotify_with_nothing_resolved_is_an_error():
    with pytest.raises(TrackNotFound, match="private, region-locked"):
        spotify._merge(None, None, "id")


def test_spotify_page_without_tags_returns_nothing():
    assert spotify.parse_page("<html></html>", "id", "u") is None


# --- getting audio -------------------------------------------------------


@pytest.fixture
def stub_download(monkeypatch):
    """Pretend a download succeeded, without touching the network."""
    import tabfinder.sources as sources

    def fake_download(url, destination, timeout=30.0, max_bytes=None):
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(b"fake audio")
        return Path(destination)

    monkeypatch.setattr(sources, "download", fake_download)
    monkeypatch.setattr(sources, "ensure_readable", lambda path: path)
    return fake_download


def test_preview_is_used_when_the_track_has_one(stub_download, tmp_path):
    ref = TrackRef("apple", "u", "1", "Wonderwall", "Oasis", preview_url="https://x/p.m4a")
    audio = acquire_audio(ref, tmp_path)
    assert audio.kind == "preview"
    assert audio.is_preview
    assert audio.path.exists()
    assert "preview" in audio.describe()


def test_spotify_borrows_a_preview_from_itunes(stub_download, tmp_path, monkeypatch):
    # Spotify gives no audio, so the same song is found on iTunes instead.
    found = TrackRef("apple", "u", "9", "Wonderwall", "Oasis", preview_url="https://x/p.m4a")
    monkeypatch.setattr(apple, "find_preview", lambda title, artist, timeout=10.0: found)

    ref = TrackRef("spotify", "u", "1", "Wonderwall", "Oasis")
    audio = acquire_audio(ref, tmp_path)
    assert audio.kind == "preview"
    assert "Apple Music" in audio.origin


def test_full_download_is_preferred_when_allowed(stub_download, tmp_path, monkeypatch):
    target = tmp_path / "full.m4a"
    target.write_bytes(b"x")
    monkeypatch.setattr(youtube, "download_audio", lambda url, d, timeout=300.0: target)

    ref = TrackRef("youtube", "https://youtu.be/abc", "abc", "Wonderwall", "Oasis")
    audio = acquire_audio(ref, tmp_path, AudioPolicy(allow_download=True))
    assert audio.kind == "full"
    assert "yt-dlp" in audio.origin


def test_download_failure_falls_back_to_a_preview(stub_download, tmp_path, monkeypatch):
    def boom(url, directory, timeout=300.0):
        raise SourceError("yt-dlp failed: Video unavailable")

    monkeypatch.setattr(youtube, "download_audio", boom)
    found = TrackRef("apple", "u", "9", "Wonderwall", "Oasis", preview_url="https://x/p.m4a")
    monkeypatch.setattr(apple, "find_preview", lambda title, artist, timeout=10.0: found)

    ref = TrackRef("youtube", "https://youtu.be/abc", "abc", "Wonderwall", "Oasis")
    audio = acquire_audio(ref, tmp_path, AudioPolicy(allow_download=True))
    assert audio.kind == "preview"  # degraded, but the user still gets something


def test_no_preview_allowed_and_no_download_means_no_audio(tmp_path):
    ref = TrackRef("spotify", "u", "1", "Wonderwall", "Oasis")
    with pytest.raises(AudioNotAvailable) as excinfo:
        acquire_audio(ref, tmp_path, AudioPolicy(allow_preview=False))
    assert "DRM" in str(excinfo.value)


def test_missing_audio_explains_the_youtube_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(apple, "find_preview", lambda title, artist, timeout=10.0: None)
    ref = TrackRef("youtube", "https://youtu.be/abc", "abc", "Wonderwall", "Oasis")
    with pytest.raises(AudioNotAvailable, match="--allow-download"):
        acquire_audio(ref, tmp_path)


def test_resolve_track_dispatches_per_provider(monkeypatch):
    monkeypatch.setattr(
        youtube, "resolve", lambda i, u, timeout=10.0: TrackRef("youtube", u, i, "T", "A")
    )
    ref = resolve_track("https://youtu.be/dQw4w9WgXcQ")
    assert ref.provider == "youtube"
    assert ref.track_id == "dQw4w9WgXcQ"


# --- decoding ------------------------------------------------------------


@pytest.mark.parametrize("suffix", sorted(NATIVE_AUDIO_SUFFIXES))
def test_natively_readable_files_pass_straight_through(tmp_path, suffix):
    path = tmp_path / f"song{suffix}"
    path.write_bytes(b"x")
    assert ensure_readable(path) == path


def test_undecodable_file_without_ffmpeg_explains_itself(tmp_path, monkeypatch):
    import tabfinder.sources.fetch as fetch

    monkeypatch.setattr(fetch, "have_ffmpeg", lambda: False)
    path = tmp_path / "clip.m4a"
    path.write_bytes(b"x")
    with pytest.raises(SourceError, match="ffmpeg"):
        ensure_readable(path)
