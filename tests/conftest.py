"""Shared fixtures, including synthetic audio so the audio tests need no files."""

from __future__ import annotations

import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "audio: needs the optional audio extra")


@pytest.fixture(scope="session")
def np():
    return pytest.importorskip("numpy")


def _pluck(np, midi, sr, duration, amp=1.0):
    """A plucked-string tone: a few harmonics under a decaying envelope."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    f0 = 440.0 * 2 ** ((midi - 69) / 12)
    signal = np.zeros_like(t)
    for harmonic, gain in enumerate([1.0, 0.5, 0.33, 0.22, 0.15, 0.1], start=1):
        if f0 * harmonic > sr / 2:
            break
        signal += gain * np.sin(2 * np.pi * f0 * harmonic * t)
    envelope = np.exp(-2.6 * t) * (1 - np.exp(-300 * t))
    return amp * signal * envelope


def synth_progression(np, chords_midi, sr=22050, beats_per_chord=4, bpm=100):
    """Render a chord progression as strummed audio with a click track."""
    beat = 60.0 / bpm
    duration = beat * beats_per_chord
    blocks = []
    for notes in chords_midi:
        block = np.zeros(int(sr * duration))
        for index, midi in enumerate(notes):
            voice = _pluck(np, midi, sr, duration, amp=0.9 ** index)
            offset = int(sr * 0.012 * index)  # stagger the strings into a strum
            block[offset : offset + len(voice) - offset] += voice[: len(voice) - offset]
        for beat_index in range(beats_per_chord):
            start = int(beat_index * beat * sr)
            length = int(0.01 * sr)
            click = (
                np.random.RandomState(beat_index).randn(length)
                * 0.12
                * np.exp(-np.linspace(0, 6, length))
            )
            block[start : start + length] += click
        blocks.append(block)
    audio = np.concatenate(blocks)
    return (audio / np.max(np.abs(audio)) * 0.85).astype("float32")


def synth_melody(np, midis, sr=22050, note_duration=0.35):
    """Render a monophonic line, one note after another."""
    blocks = [_pluck(np, midi, sr, note_duration) for midi in midis]
    audio = np.concatenate(blocks)
    return (audio / np.max(np.abs(audio)) * 0.85).astype("float32")


#: Standard voicings as MIDI notes, for building test audio.
SHAPES = {
    "C": [48, 52, 55, 60, 64],
    "G": [43, 47, 50, 55, 59, 67],
    "D": [50, 57, 62, 66, 74],
    "A": [45, 52, 57, 61, 64],
    "E": [40, 47, 52, 56, 59, 64],
    "Am": [45, 52, 57, 60, 64],
    "Em": [40, 47, 52, 55, 59, 64],
    "Dm": [50, 57, 62, 65, 69],
    "F": [41, 48, 53, 57, 60, 65],
}


@pytest.fixture
def make_progression(np):
    """Build an AudioClip for a progression of chord names."""
    from tabfinder.analysis.audio import AudioClip

    def build(names, bpm=100, beats_per_chord=4):
        audio = synth_progression(
            np, [SHAPES[n] for n in names], bpm=bpm, beats_per_chord=beats_per_chord
        )
        return AudioClip(samples=audio, sample_rate=22050)

    return build


@pytest.fixture
def make_melody(np):
    """Build an AudioClip for a sequence of MIDI notes."""
    from tabfinder.analysis.audio import AudioClip

    def build(midis, note_duration=0.35):
        audio = synth_melody(np, midis, note_duration=note_duration)
        return AudioClip(samples=audio, sample_rate=22050)

    return build
