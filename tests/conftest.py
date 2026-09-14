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


def _voice(np, pitch_curve, picked=True):
    """Render a pitch curve as a guitar note, picked or sounded legato."""
    samples = len(pitch_curve)
    t = np.arange(samples) / 22050
    frequency = 440.0 * 2 ** ((pitch_curve - 69) / 12)
    phase = np.cumsum(2 * np.pi * frequency / 22050)
    signal = np.zeros(samples)
    for harmonic, gain in enumerate([1.0, 0.5, 0.33, 0.22, 0.15], start=1):
        signal += gain * np.sin(harmonic * phase)
    if picked:
        envelope = np.exp(-1.6 * t) * (1 - np.exp(-400 * t))
    else:
        # Legato: the string already rings, so it swells instead of restarting.
        envelope = 0.32 * np.exp(-1.6 * t) * (1 + 0.45 * (1 - np.exp(-60 * t)))
    return signal * envelope


def flat_curve(np, midi, duration):
    return np.full(int(22050 * duration), float(midi))


def bend_curve(np, midi, semitones, duration, hold=0.55):
    samples = int(22050 * duration)
    rising = int(samples * (1 - hold))
    return np.concatenate([
        np.linspace(midi, midi + semitones, rising),
        np.full(samples - rising, midi + semitones),
    ])


def vibrato_curve(np, midi, duration, rate=6.0, depth=0.35):
    t = np.linspace(0, duration, int(22050 * duration), endpoint=False)
    return midi + depth * np.sin(2 * np.pi * rate * t)


def glide_curve(np, start, end, duration):
    return np.linspace(float(start), float(end), int(22050 * duration))


@pytest.fixture
def make_phrase(np):
    """Build an AudioClip from (pitch curve, picked) pairs."""
    from tabfinder.analysis.audio import AudioClip

    def build(parts):
        audio = np.concatenate([_voice(np, curve, picked) for curve, picked in parts])
        audio = (audio / np.max(np.abs(audio)) * 0.85).astype("float32")
        return AudioClip(samples=audio, sample_rate=22050)

    return build


@pytest.fixture
def song_with_solo(np):
    """Verse chords, a solo using every technique, then chords again."""
    from tabfinder.analysis.audio import AudioClip

    phrase = [
        (flat_curve(np, 64, 0.32), True),
        (flat_curve(np, 67, 0.32), True),
        (bend_curve(np, 69, 2, 0.75), True),
        (vibrato_curve(np, 71, 0.75), True),
        (flat_curve(np, 67, 0.28), True),
        (flat_curve(np, 69, 0.28), False),
        (flat_curve(np, 71, 0.45), True),
        (glide_curve(np, 71, 76, 0.20), False),
        (flat_curve(np, 76, 0.55), False),
        (bend_curve(np, 74, 2, 0.70), True),
        (vibrato_curve(np, 71, 0.85), True),
    ]
    solo = np.concatenate([_voice(np, curve, picked) for curve, picked in phrase] * 2)
    verse = synth_progression(np, [SHAPES[n] for n in ["Em", "C", "G", "D"]], bpm=100)
    audio = np.concatenate([verse, solo, verse])
    audio = (audio / np.max(np.abs(audio)) * 0.85).astype("float32")
    clip = AudioClip(samples=audio, sample_rate=22050)
    return clip, len(verse) / 22050, (len(verse) + len(solo)) / 22050
