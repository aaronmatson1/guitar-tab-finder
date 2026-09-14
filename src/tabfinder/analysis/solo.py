"""Find the lead line in a song, so it can be tabbed.

There is no reliable way to tell a guitar solo from a sung melody without a
trained model, and this project does not ship one. What it can do honestly is
find the stretches where a single prominent melodic line dominates the mix —
which, during an instrumental break, is the solo. Candidates are ranked and
reported with timestamps so you can confirm which one you meant, and a time
range can always be given explicitly instead.

Detection runs on cheap spectral features across the whole song; the expensive
pitch tracking only ever runs on the section you settle on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .audio import AudioClip, format_time, require_audio

#: A solo shorter than this is more likely a fill than a section worth tabbing.
MIN_SECTION_SECONDS = 6.0

#: Guitar leads live here. Below is rhythm/bass, above is mostly harmonics.
LEAD_BAND_HZ = (250.0, 2600.0)

HOP_LENGTH = 512


@dataclass
class LeadSection:
    """A stretch of song where one melodic line stands out."""

    start: float
    end: float
    score: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def label(self) -> str:
        return f"{format_time(self.start)}-{format_time(self.end)}"

    def describe(self) -> str:
        return f"{self.label()} ({self.duration:.0f}s, confidence {self.score:.0%})"


def _zscore(np, values):
    """Standardise a feature against the song's own distribution."""
    spread = float(np.std(values))
    if spread < 1e-9:
        return np.zeros_like(values)
    return (values - float(np.mean(values))) / spread


def lead_salience(clip: AudioClip, hop_length: int = HOP_LENGTH):
    """Score every frame for how much it sounds like a single lead line.

    Returns ``(times, scores)`` with scores normalised to 0-1 across the song,
    so the result says "lead-like *for this song*" rather than relying on
    absolute thresholds that no two productions would agree on.
    """
    librosa, np = require_audio()
    y = clip.samples
    sr = clip.sample_rate

    harmonic = librosa.effects.harmonic(y)
    chroma = librosa.feature.chroma_cqt(y=harmonic, sr=sr, hop_length=hop_length)
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    flatness = librosa.feature.spectral_flatness(y=y, hop_length=hop_length)[0]
    spectrum = np.abs(librosa.stft(y, hop_length=hop_length))
    frequencies = librosa.fft_frequencies(sr=sr)

    frames = min(chroma.shape[1], len(rms), len(flatness), spectrum.shape[1])
    chroma, rms = chroma[:, :frames], rms[:frames]
    flatness, spectrum = flatness[:frames], spectrum[:, :frames]

    # 1. One note at a time concentrates the chroma; a chord spreads it out.
    totals = np.clip(chroma.sum(axis=0), 1e-9, None)
    concentration = chroma.max(axis=0) / totals

    # 2. A solo changes note every fraction of a second; chords hold for bars.
    flux = np.zeros(frames)
    if frames > 1:
        normalised = chroma / np.clip(np.linalg.norm(chroma, axis=0, keepdims=True), 1e-9, None)
        flux[1:] = np.linalg.norm(np.diff(normalised, axis=1), axis=0)

    # 3. A lead cuts through in its own register.
    band = (frequencies >= LEAD_BAND_HZ[0]) & (frequencies <= LEAD_BAND_HZ[1])
    energy = np.clip(spectrum.sum(axis=0), 1e-9, None)
    lead_band = spectrum[band[: spectrum.shape[0]], :].sum(axis=0) / energy

    # 4. A sustained pitch is tonal, not noisy.
    tonality = -flatness

    score = (
        1.1 * _zscore(np, concentration)
        + 1.3 * _zscore(np, flux)
        + 1.0 * _zscore(np, lead_band)
        + 0.6 * _zscore(np, tonality)
        + 0.5 * _zscore(np, rms)
    )

    # Solos last for bars, so smooth away anything shorter than a couple of
    # seconds before deciding.
    window = max(3, int(round(2.0 * sr / hop_length)) | 1)
    score = _smooth(np, score, window)

    lowest, highest = float(score.min()), float(score.max())
    if highest - lowest > 1e-9:
        score = (score - lowest) / (highest - lowest)
    else:
        score = np.zeros_like(score)

    times = librosa.frames_to_time(np.arange(frames), sr=sr, hop_length=hop_length)
    return times, score


def _smooth(np, values, window: int):
    """Moving average with the edges held, so nothing shifts in time."""
    if window <= 1 or values.size < window:
        return values
    kernel = np.ones(window) / window
    padded = np.pad(values, window // 2, mode="edge")
    return np.convolve(padded, kernel, mode="valid")[: values.size]


def find_lead_sections(
    clip: AudioClip,
    min_duration: float = MIN_SECTION_SECONDS,
    threshold: float = 0.55,
    limit: int = 3,
) -> List[LeadSection]:
    """Find the stretches most likely to be a solo, best first."""
    _librosa, np = require_audio()
    times, score = lead_salience(clip)
    if len(times) == 0:
        return []

    sections: List[LeadSection] = []
    for low, high in _above(np, score, threshold):
        start, end = float(times[low]), float(times[min(high, len(times) - 1)])
        if end - start < min_duration:
            continue
        sections.append(LeadSection(start, end, float(np.mean(score[low : high + 1]))))

    # Nothing cleared the bar: relax it rather than giving up, and say as much
    # through the score the caller sees.
    if not sections and threshold > 0.35:
        return find_lead_sections(clip, min_duration, threshold - 0.1, limit)

    sections.sort(key=lambda s: -(s.score * min(1.0, s.duration / 20.0)))
    return sections[:limit]


def _above(np, score, threshold: float) -> List[Tuple[int, int]]:
    """Contiguous runs of frames above a threshold, merged across small gaps."""
    mask = score >= threshold
    runs: List[Tuple[int, int]] = []
    start: Optional[int] = None
    for index, active in enumerate(mask):
        if active and start is None:
            start = index
        elif not active and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(mask) - 1))

    # A solo does not stop because one note was quiet; bridge short dips.
    merged: List[Tuple[int, int]] = []
    gap = 40  # frames, a little under a second at the default hop
    for run in runs:
        if merged and run[0] - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], run[1])
        else:
            merged.append(run)
    return merged


def isolate_lead(clip: AudioClip, use_demucs: bool = False) -> AudioClip:
    """Push the backing down so the lead line is easier to pitch-track.

    With ``demucs`` installed and ``use_demucs`` set, the real source
    separation is used. Otherwise this falls back to dropping the percussive
    layer and filtering to the lead register, which is cruder but needs no
    extra dependency.
    """
    librosa, np = require_audio()
    if use_demucs:
        separated = _demucs_lead(clip)
        if separated is not None:
            return separated

    harmonic = librosa.effects.harmonic(clip.samples, margin=3.0)
    filtered = _bandpass(np, harmonic, clip.sample_rate, *LEAD_BAND_HZ)
    return AudioClip(samples=filtered, sample_rate=clip.sample_rate, path=clip.path)


def _bandpass(np, samples, sample_rate: int, low: float, high: float):
    """Keep the lead register, roll off everything else."""
    from scipy.signal import butter, sosfiltfilt

    nyquist = sample_rate / 2.0
    low_cut = max(1e-4, min(low / nyquist, 0.99))
    high_cut = max(low_cut + 1e-4, min(high / nyquist, 0.99))
    sos = butter(4, [low_cut, high_cut], btype="band", output="sos")
    return sosfiltfilt(sos, samples).astype(samples.dtype)


def demucs_available() -> bool:
    """Whether the optional demucs separator is installed."""
    import importlib.util

    return importlib.util.find_spec("demucs") is not None


def _demucs_lead(clip: AudioClip) -> Optional[AudioClip]:
    """Run demucs and keep the stem a guitar solo lives in."""
    if not demucs_available():
        return None
    try:
        import subprocess
        import tempfile
        from pathlib import Path

        import soundfile as sf

        _librosa, np = require_audio()
        with tempfile.TemporaryDirectory(prefix="tabfinder-demucs-") as work:
            source = Path(work) / "input.wav"
            sf.write(str(source), clip.samples, clip.sample_rate)
            result = subprocess.run(
                ["python", "-m", "demucs", "-n", "htdemucs", "-o", work, str(source)],
                capture_output=True,
                text=True,
                timeout=900,
            )
            if result.returncode != 0:
                return None
            stems = list(Path(work).rglob("other.wav"))
            if not stems:
                return None
            import librosa as _lb

            samples, sr = _lb.load(str(stems[0]), sr=clip.sample_rate, mono=True)
            return AudioClip(samples=samples, sample_rate=int(sr), path=clip.path)
    except Exception:  # noqa: BLE001 - separation is a bonus, never required
        return None


def slice_clip(clip: AudioClip, start: float, end: float) -> AudioClip:
    """Cut a section out of a clip, keeping its sample rate."""
    _librosa, _np = require_audio()
    first = max(0, int(start * clip.sample_rate))
    last = min(len(clip.samples), int(end * clip.sample_rate))
    if last <= first:
        raise ValueError(f"empty section: {start:.2f}s to {end:.2f}s")
    return AudioClip(
        samples=clip.samples[first:last],
        sample_rate=clip.sample_rate,
        path=clip.path,
        offset=clip.offset + start,
    )


@dataclass
class SoloTranscription:
    """A tabbed solo: where it is, what is played, and how."""

    section: LeadSection
    notes: List["object"]          # SoloNote, typed loosely to avoid a cycle
    key: Optional["object"] = None
    separated: bool = False

    @property
    def note_count(self) -> int:
        return len(self.notes)

    def pitch_range(self) -> Tuple[int, int]:
        if not self.notes:
            return (0, 0)
        pitches = [note.midi for note in self.notes]
        return (min(pitches), max(pitches))

    def to_dict(self) -> dict:
        from ..theory.notes import midi_to_name

        return {
            "start": round(self.section.start, 2),
            "end": round(self.section.end, 2),
            "confidence": round(self.section.score, 3),
            "separated": self.separated,
            "notes": [
                {
                    "note": midi_to_name(note.midi),
                    "midi": note.midi,
                    "start": round(note.start, 3),
                    "end": round(note.end, 3),
                    "bend": note.bend,
                    "vibrato": note.vibrato,
                    "link": note.link,
                }
                for note in self.notes
            ],
        }


def transcribe_solo(
    clip: AudioClip,
    section: Optional[LeadSection] = None,
    key=None,
    use_demucs: bool = False,
) -> Optional[SoloTranscription]:
    """Tab the solo in a clip.

    With no ``section``, the most promising lead section is found first. The
    expensive pitch tracking only ever runs on that section, never the whole
    song.

    Note that the audio is *not* pre-filtered. Bandpassing to the lead register
    and stripping the percussive layer sounds like it should help, and measured
    worse: the filtering smears exactly the pitch detail that bends, slides and
    vibrato are read from. Only real source separation (demucs) is worth doing,
    and it stays opt-in because it is slow and an extra dependency.
    """
    from .articulation import transcribe_with_technique

    if section is None:
        candidates = find_lead_sections(clip)
        if not candidates:
            return None
        section = candidates[0]

    piece = slice_clip(clip, section.start, section.end)
    separated = False
    if use_demucs and demucs_available():
        isolated = _demucs_lead(piece)
        if isolated is not None:
            piece, separated = isolated, True

    notes = transcribe_with_technique(piece, key=key)
    notes = _trim_bleed(notes)
    # Timings come back relative to the slice; put them back on the song clock.
    for note in notes:
        note.start += section.start
        note.end += section.start
    return SoloTranscription(section=section, notes=notes, key=key, separated=separated)


def _trim_bleed(notes: List["object"]) -> List["object"]:
    """Drop notes at the edges that belong to what was playing either side.

    A section boundary rarely lands in silence, so the first or last note is
    often the tail of a chord ringing under the solo. Those sit far below the
    rest of the line, which is what gives them away.
    """
    if len(notes) < 3:
        return notes
    _librosa, np = require_audio()
    middle = float(np.median([note.midi for note in notes]))
    trimmed = list(notes)
    while len(trimmed) > 2 and middle - trimmed[0].midi > 9:
        trimmed.pop(0)
    while len(trimmed) > 2 and middle - trimmed[-1].midi > 9:
        trimmed.pop()
    return trimmed
