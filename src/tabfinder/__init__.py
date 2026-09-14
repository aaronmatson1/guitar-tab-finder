"""guitar-tab-finder: find a song's tab, or work it out from the audio.

Two ways in:

    from tabfinder import search_tabs, analyze_file
    outcome = search_tabs("Oasis - Wonderwall")
    analysis = analyze_file("riff.wav")        # needs the [audio] extra

or the ``tabfinder`` command line tool.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .guitar.fretboard import TUNINGS, Fretboard
from .guitar.voicings import Voicing, best_voicing, generate_voicings
from .search import SearchOutcome, TabResult, search_tabs
from .theory.chords import Chord, parse_chord
from .theory.scales import Key

__all__ = [
    "__version__",
    "Chord",
    "Fretboard",
    "Key",
    "SearchOutcome",
    "TUNINGS",
    "TabResult",
    "Voicing",
    "analyze_file",
    "best_voicing",
    "generate_voicings",
    "parse_chord",
    "search_tabs",
]


def analyze_file(*args, **kwargs):
    """Analyse an audio file. Imported lazily so librosa stays optional."""
    from .analysis.pipeline import analyze_file as _analyze_file

    return _analyze_file(*args, **kwargs)
