"""Tab search: result parsing, ranking and graceful failure."""

from __future__ import annotations

import html
import json

import pytest

from tabfinder.search import SOURCES, search_links, search_tabs
from tabfinder.search.base import SearchOutcome, TabResult, split_query
from tabfinder.search.songsterr import parse_songsterr
from tabfinder.search.ultimate_guitar import parse_ultimate_guitar


def ug_page(results):
    """Build a search page shaped like Ultimate Guitar's."""
    store = {"store": {"page": {"data": {"results": results}}}}
    return f'<div class="js-store" data-content="{html.escape(json.dumps(store))}"></div>'


UG_RESULT = {
    "song_name": "Creep",
    "artist_name": "Radiohead",
    "type": "Chords",
    "tab_url": "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169",
    "rating": 4.8,
    "votes": 1200,
    "version": 3,
}


@pytest.mark.parametrize(
    "query,expected",
    [
        ("Oasis - Wonderwall", ("Oasis", "Wonderwall")),
        ("Wonderwall by Oasis", ("Wonderwall", "Oasis")),
        ("Wonderwall", ("Wonderwall",)),
    ],
)
def test_split_query(query, expected):
    assert tuple(split_query(query)) == expected


def test_parse_ultimate_guitar_reads_results():
    results = parse_ultimate_guitar(ug_page([UG_RESULT]))
    assert len(results) == 1
    result = results[0]
    assert result.title == "Creep"
    assert result.artist == "Radiohead"
    assert result.rating == 4.8
    assert result.votes == 1200
    assert result.url.startswith("https://tabs.ultimate-guitar.com/")


def test_parse_ultimate_guitar_finds_relocated_results():
    # The same data, buried somewhere else in the store.
    store = {"store": {"page": {"data": {"something_new": {"tabs": [UG_RESULT]}}}}}
    page = f'<div class="js-store" data-content="{html.escape(json.dumps(store))}"></div>'
    assert len(parse_ultimate_guitar(page)) == 1


def test_parse_ultimate_guitar_skips_unhelpful_types():
    drums = dict(UG_RESULT, type="Drum Tabs")
    assert parse_ultimate_guitar(ug_page([drums])) == []


def test_parse_ultimate_guitar_survives_garbage():
    assert parse_ultimate_guitar("<html>nothing here</html>") == []
    assert parse_ultimate_guitar('<div class="js-store" data-content="not json"></div>') == []
    assert parse_ultimate_guitar(ug_page([{"missing": "fields"}])) == []


def test_parse_songsterr_reads_results():
    payload = [
        {"id": 123, "title": "Wonderwall", "artist": {"name": "Oasis"}, "tracks": []},
    ]
    results = parse_songsterr(payload)
    assert results[0].title == "Wonderwall"
    assert results[0].artist == "Oasis"
    assert "123" in results[0].url


def test_parse_songsterr_handles_shape_changes():
    assert parse_songsterr({"songs": [{"id": 1, "title": "X", "artistName": "Y"}]})[0].artist == "Y"
    assert parse_songsterr("not a list") == []
    assert parse_songsterr([{"no": "id"}]) == []


def test_parse_songsterr_respects_limit():
    payload = [{"id": i, "title": f"Song {i}", "artist": {"name": "A"}} for i in range(20)]
    assert len(parse_songsterr(payload, limit=5)) == 5


def test_relevance_prefers_the_right_song():
    right = TabResult("Creep", "Radiohead", "u1", "UG")
    wrong = TabResult("Creepin'", "Someone Else", "u2", "UG")
    assert right.relevance("Radiohead - Creep") > wrong.relevance("Radiohead - Creep")


def test_quality_discounts_thinly_voted_ratings():
    popular = TabResult("A", "B", "u1", "UG", rating=4.8, votes=1000)
    obscure = TabResult("A", "B", "u2", "UG", rating=5.0, votes=2)
    assert popular.quality() > obscure.quality()


def test_ranking_deduplicates_and_orders():
    outcome = SearchOutcome(
        results=[
            TabResult("Creepin'", "Nobody", "u2", "UG"),
            TabResult("Creep", "Radiohead", "u1", "UG", rating=4.9, votes=900),
            TabResult("Creep", "Radiohead", "u1", "Songsterr"),  # same URL
        ]
    )
    ranked = outcome.ranked("Radiohead - Creep")
    assert len(ranked) == 2
    assert ranked[0].url == "u1"


def test_search_links_always_returns_something():
    links = search_links("Some Extremely Obscure B-Side")
    assert len(links) >= 3
    assert all(link.url.startswith("https://") for link in links)
    assert all("+" in link.url or "%20" in link.url for link in links)


def test_unknown_source_is_rejected():
    with pytest.raises(ValueError, match="unknown source"):
        search_tabs("anything", sources=["myspace"])


def test_a_failing_source_does_not_sink_the_search(monkeypatch):
    class Boom:
        name = "boom"

        def search(self, query, limit=10, timeout=8.0):
            raise ConnectionError("ultimate-guitar is down")

    class Fine:
        name = "fine"

        def search(self, query, limit=10, timeout=8.0):
            return [TabResult("Creep", "Radiohead", "u1", "Songsterr")]

    monkeypatch.setitem(SOURCES, "ultimate-guitar", Boom())
    monkeypatch.setitem(SOURCES, "songsterr", Fine())
    outcome = search_tabs("Radiohead - Creep")
    assert outcome.found
    assert len(outcome.results) == 1
    assert outcome.errors  # the failure was recorded, not swallowed


def test_search_with_no_sources_is_empty():
    outcome = search_tabs("anything", sources=[])
    assert not outcome.found
    assert not outcome.errors
