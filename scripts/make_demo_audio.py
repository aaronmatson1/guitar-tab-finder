#!/usr/bin/env python3
"""Generate demo audio so you can try the analyser without hunting for a file.

Synthesises plucked-string chord progressions and a single-note riff, writing
them as .wav files you can point ``tabfinder analyze`` at. The expected answer
is printed alongside each file, so you can check the analyser against it.

    python scripts/make_demo_audio.py            # writes into ./demo-audio
    python scripts/make_demo_audio.py --out /tmp/x
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Sequence

try:
    import numpy as np
    import soundfile as sf
except ImportError:  # pragma: no cover - depends on the environment
    raise SystemExit(
        "This script needs the audio extra:\n"
        "    pip install 'guitar-tab-finder[audio]'"
    )

SAMPLE_RATE = 22050

#: Real guitar voicings, as the MIDI notes each open/barre shape sounds.
SHAPES: Dict[str, List[int]] = {
    "C": [48, 52, 55, 60, 64],
    "G": [43, 47, 50, 55, 59, 67],
    "D": [50, 57, 62, 66, 74],
    "A": [45, 52, 57, 61, 64],
    "E": [40, 47, 52, 56, 59, 64],
    "F": [41, 48, 53, 57, 60, 65],
    "Am": [45, 52, 57, 60, 64],
    "Em": [40, 47, 52, 55, 59, 64],
    "Dm": [50, 57, 62, 65, 69],
    "Bb": [46, 53, 58, 62, 65],
}

#: Each demo: filename, chord names, tempo, and what the analyser should say.
PROGRESSIONS = [
    ("four-chord-G.wav", ["G", "D", "Em", "C"] * 3, 96, "G major, I-V-vi-IV"),
    ("minor-Am.wav", ["Am", "Dm", "E", "Am"] * 3, 104, "A minor, i-iv-V-i"),
    ("blues-E.wav", ["E", "A", "E", "A", "E"] * 2, 88, "E major, I-IV"),
    # A key full of barre chords, so the capo suggestion has something to do.
    ("capo-song-F.wav", ["F", "Bb", "C", "F"] * 3, 100, "F major -> capo 1, E shapes"),
    # Genuinely ambiguous: the same notes as C major, so confidence drops.
    ("ambiguous-AmF.wav", ["Am", "F", "C", "G"] * 3, 108, "C major / A minor, low confidence"),
]

#: A riff for the --melody path: the E minor pentatonic, up and back down.
RIFF = [40, 43, 45, 47, 50, 52, 50, 47, 45, 43, 40]


def pluck(midi: int, duration: float, amplitude: float = 1.0) -> "np.ndarray":
    """One plucked string: a few harmonics under a decaying envelope."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    f0 = 440.0 * 2 ** ((midi - 69) / 12)
    signal = np.zeros_like(t)
    for harmonic, gain in enumerate([1.0, 0.5, 0.33, 0.22, 0.15, 0.1], start=1):
        if f0 * harmonic > SAMPLE_RATE / 2:
            break
        signal += gain * np.sin(2 * np.pi * f0 * harmonic * t)
    envelope = np.exp(-2.6 * t) * (1 - np.exp(-300 * t))
    return amplitude * signal * envelope


def strum_progression(names: Sequence[str], bpm: int, beats_per_chord: int = 4) -> "np.ndarray":
    """Render chords as strums, with a click on each beat for the beat tracker."""
    beat = 60.0 / bpm
    duration = beat * beats_per_chord
    blocks = []
    for name in names:
        block = np.zeros(int(SAMPLE_RATE * duration))
        for index, midi in enumerate(SHAPES[name]):
            voice = pluck(midi, duration, amplitude=0.9 ** index)
            offset = int(SAMPLE_RATE * 0.012 * index)  # stagger strings into a strum
            block[offset : offset + len(voice) - offset] += voice[: len(voice) - offset]
        for beat_index in range(beats_per_chord):
            start = int(beat_index * beat * SAMPLE_RATE)
            length = int(0.01 * SAMPLE_RATE)
            click = (
                np.random.RandomState(beat_index).randn(length)
                * 0.12
                * np.exp(-np.linspace(0, 6, length))
            )
            block[start : start + length] += click
        blocks.append(block)
    return np.concatenate(blocks)


def play_riff(midis: Sequence[int], note_duration: float = 0.35) -> "np.ndarray":
    """Render a single-note line, one note after another."""
    return np.concatenate([pluck(midi, note_duration) for midi in midis])


def normalise(audio: "np.ndarray") -> "np.ndarray":
    peak = np.max(np.abs(audio))
    return (audio / peak * 0.85).astype("float32") if peak else audio.astype("float32")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="demo-audio", help="where to write the files")
    args = parser.parse_args()

    directory = Path(args.out)
    directory.mkdir(parents=True, exist_ok=True)

    print(f"Writing demo audio to {directory}/\n")
    for filename, chords, bpm, expected in PROGRESSIONS:
        path = directory / filename
        sf.write(str(path), normalise(strum_progression(chords, bpm)), SAMPLE_RATE)
        print(f"  {filename:22s} {bpm} BPM   expect: {expected}")

    riff_path = directory / "riff-Em.wav"
    sf.write(str(riff_path), normalise(play_riff(RIFF)), SAMPLE_RATE)
    print(f"  {'riff-Em.wav':22s} single notes   expect: E minor pentatonic")

    print(f"\nTry it:\n    tabfinder analyze {directory}/four-chord-G.wav")
    print(f"    tabfinder analyze {directory}/riff-Em.wav --melody")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
