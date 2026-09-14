# guitar-tab-finder

Give it a song. It finds the guitar tab — and if nobody has ever tabbed that
song, it listens to the recording and works the tab out for you.

That second half is the point. Plenty of tools search Ultimate Guitar. This one
also handles the obscure B-side, the local band, the thing you recorded on your
phone: it finds the key, tracks the chord progression, and hands you playable
chord shapes and tab.

```
$ tabfinder song https://youtu.be/dQw4w9WgXcQ
```

Paste a YouTube, Spotify or Apple Music link and it takes it from there:
resolves what the song is, looks for a tab, and works one out from the audio if
there isn't one. A local file works just as well.

## What it does

**Find** — searches Ultimate Guitar and Songsterr at once, ranks results by how
well they match and how the host site's own users rated them, and links out. It
reads search listings only; tab content stays on the sites that host it.

**Follow a link** — give it a YouTube, Spotify or Apple Music URL instead of a
title. It resolves the track name (cleaning up the `(Official Video) [4K]`
clutter that would otherwise wreck the search) and carries on from there.

**Analyse** — when there's no tab to find, point it at audio:

- **Key detection** — Krumhansl-Schmuckler profile matching, cross-checked
  against the chords that were actually detected, with a cadence heuristic so
  it can tell A minor from C major (they use the same seven notes).
- **Chord recognition** — harmonic separation, beat-synchronous chroma,
  template matching over 84 chords, then Viterbi decoding so the output changes
  chord only when the music does.
- **Tempo and bar tracking**, so chords land on bars instead of raw seconds.
- **Chord shapes** — the standard vocabulary a guitarist actually plays (open
  chords, E/A/D-shape barres), falling back to a fretboard search that can
  voice any chord in any tuning.
- **Capo suggestions** — "capo 1 and play E shapes" beats fighting an F barre.
- **Melody transcription** — pitch-tracks a single-note riff and arranges it on
  the neck with dynamic programming, so the fretting hand stays in one place.

## Install

```bash
pip install -e .            # search, chords, keys, shapes
pip install -e '.[audio]'   # + audio analysis (librosa, numpy, scipy)
```

Audio analysis is an optional extra because librosa is a heavy dependency and
half the tool doesn't need it. Ask for it without installing it and you get a
clear message telling you what to run.

## Use

```bash
# Is there already a tab?
tabfinder find "Oasis - Wonderwall"

# Just paste a link — it works out the rest.
tabfinder song https://youtu.be/dQw4w9WgXcQ
tabfinder song "https://open.spotify.com/track/7ygpwy2qP3NbrxVkHvUhXY"
tabfinder analyze "https://music.apple.com/us/album/x/1440830900?i=1440831165"

# Or point it at audio you already have.
tabfinder analyze bside.mp3
tabfinder song "Some Obscure B-Side" --audio bside.mp3

# Pull the full track off a video rather than using a 30-second preview.
tabfinder song https://youtu.be/dQw4w9WgXcQ --allow-download

# Look up chord shapes, in any tuning, with or without a capo.
tabfinder chord Am7 Cmaj7 F#m --shapes 3
tabfinder chord D --tuning drop-d

# What can I play in this key?
tabfinder key "E minor" --sevenths

tabfinder tunings
```

Every command takes `--json` (for piping into something else), `--markdown`,
and `--out FILE`. Link-aware commands also take `--allow-download`,
`--no-preview` and `--keep-audio DIR`.

## What each service can actually give you

This is the part worth understanding, because it decides what you get:

| Service | Track name | Audio |
| --- | --- | --- |
| **YouTube** | public oEmbed, no API key | full track, via `yt-dlp`, opt-in with `--allow-download` |
| **Apple Music** | public iTunes API, no key | 30-second preview clip |
| **Spotify** | public oEmbed + page metadata | **none** — the streams are DRM-protected |

Spotify will never hand over audio, and this tool does not try to make it. What
it does instead: resolve the track name from the link, then look the same song
up on iTunes and use *its* preview clip. So a Spotify link still ends in a real
analysis, without going anywhere near the DRM.

A 30-second preview is usually lifted from the middle of a song. That is
normally enough to pin down the key and the main chord loop, but an intro,
bridge or outro simply isn't in it — so the report says clearly when it only
had a clip. For the whole song, use `--allow-download` on a YouTube link, or
supply a file yourself.

`--allow-download` shells out to [yt-dlp](https://github.com/yt-dlp/yt-dlp),
which you install separately (`pip install yt-dlp`). It is off by default, and
whether you have the right to download a given video is your call, not the
tool's.

**ffmpeg**: preview clips are AAC, which libsndfile can't read, so decoding
them needs `ffmpeg` on your PATH. Local wav, mp3, flac and ogg files need
nothing extra. If ffmpeg is missing you get a message saying so rather than a
confusing decoder error.

### What the output looks like

```
KEY
────────────────────────────────────────────────────────────────────────
  G major  (confident, 78%)
  also possible: E minor, C major
  scale:      G A B C D E F#
  pentatonic: G A B D E   (safe notes for a solo)
  capo:       no capo needed — play in G major

PROGRESSION
────────────────────────────────────────────────────────────────────────
  G   D   Em  C
  I   V   vi  IV

  That is the 'four chord song' (I-V-vi-IV).

CHORD SHAPES
────────────────────────────────────────────────────────────────────────
G  320003     C  x32010     D  xx0232     Em  022000
    o o o     x     o   o   x x o         o     o o o
┬═┬═┬═┬═┬═┬   ┬═┬═┬═┬═┬═┬   ┬═┬═┬═┬═┬═┬   ┬═┬═┬═┬═┬═┬
│─│─│─│─│─│   │─│─│─│─●─│   │─│─│─│─│─│   │─│─│─│─│─│
│─●─│─│─│─│   │─│─●─│─│─│   │─│─│─●─│─●   │─●─●─│─│─│
●─│─│─│─│─●   │─●─│─│─│─│   │─│─│─│─●─│   │─│─│─│─│─│
E A D G B e   E A D G B e   E A D G B e   E A D G B e

RHYTHM TAB  (one bar of downstrokes per chord)
────────────────────────────────────────────────────────────────────────
   G                D                Em               C
e |3---3---3---3---|2---2---2---2---|0---0---0---0---|0---0---0---0---|
B |0---0---0---0---|3---3---3---3---|0---0---0---0---|1---1---1---1---|
G |0---0---0---0---|2---2---2---2---|0---0---0---0---|0---0---0---0---|
D |0---0---0---0---|0---0---0---0---|2---2---2---2---|2---2---2---2---|
A |2---2---2---2---|----------------|2---2---2---2---|3---3---3---3---|
E |3---3---3---3---|----------------|0---0---0---0---|----------------|
```

Plus a chord-by-chord timeline with timestamps, and a fretboard map of the
key's pentatonic scale for soloing over it.

## As a library

```python
from tabfinder import search_tabs, analyze_file, parse_chord, generate_voicings
from tabfinder.sources import resolve_track, acquire_audio

ref = resolve_track("https://youtu.be/dQw4w9WgXcQ")
print(ref.artist, ref.title, ref.query)     # "Oasis - Wonderwall"

outcome = search_tabs(ref.query)
for result in outcome.ranked(ref.query):
    print(result.describe(), result.url)

analysis = analyze_file("bside.mp3")          # needs the [audio] extra
print(analysis.key.key.name, analysis.tempo)
print([c.symbol() for c in analysis.loop])
print(analysis.to_dict())                     # JSON-ready

for voicing in generate_voicings(parse_chord("F#m7"), limit=3):
    print(voicing.fret_string(), voicing.difficulty)
```

## As an agent

`.claude/skills/guitar-tab/SKILL.md` wires this up as a Claude Code skill, so
you can just ask for a song by name and let the agent pick between searching
and analysing. Every command speaks `--json`, which is what the agent reads.

## Tunings

`standard`, `drop-d`, `drop-c`, `half-step-down`, `full-step-down`, `open-g`,
`open-d`, `open-e`, `dadgad`, `bass-standard`, `ukulele`. Chord shapes are
generated from the fretboard, so they are correct in any of them; the familiar
open and barre shapes are used wherever the tuning's intervals allow.

## How accurate is it?

Honest answer: the chords are a strong first draft, not a transcription.

It is reliable on clean, chord-driven recordings — an acoustic guitar, a piano
demo, a simple band mix. It gets less reliable with heavy distortion, dense
production, busy drums, or lots of extended harmony. Added 9ths and 11ths tend
to read as simpler chords, and inversions usually read as root position.

Two knobs help when it is wrong: `--sensitivity` (lower catches faster chord
changes, higher steadies the output) and `--start`/`--duration` to analyse just
the section you care about. Every report prints the caveats alongside the
result rather than pretending to certainty.

Melody transcription is monophonic only. Point it at an isolated riff or intro,
not a full mix, or it will track whichever partial happens to be loudest.

## Development

```bash
pip install -e '.[audio,dev]'
pytest                  # 250 tests
pytest -m "not audio"   # skip the ones that synthesise audio
```

The audio tests synthesise their own plucked-string chord progressions, so the
suite needs no audio files and no network.

## Notes on sources

The search sources read public search listings to find *where* a tab lives, and
link to it. They don't copy tab bodies. Ultimate Guitar has no public API, so
that source reads the JSON its own search page embeds; if the page layout
changes, that source returns nothing and the rest of the search carries on. The
`links` fallback never touches the network at all.

For analysis: preview clips come from the public iTunes API, which serves them
for exactly this kind of use. Full downloads happen only behind
`--allow-download`, only via yt-dlp, and only on links you point it at — having
the right to do that is your call. No DRM is circumvented anywhere; Spotify
audio is simply never fetched.

## Licence

MIT. See [LICENSE](LICENSE).
