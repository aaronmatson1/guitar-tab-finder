# guitar-tab-finder

Give it a song. It finds the guitar tab — and if nobody has ever tabbed that
song, it listens to the recording and works the tab out for you.

That second half is the point. Plenty of tools search Ultimate Guitar. This one
also handles the obscure B-side, the local band, the thing you recorded on your
phone: it finds the key, tracks the chord progression, and hands you playable
chord shapes and tab.

```
$ tabfinder song "Some Obscure B-Side" --audio bside.mp3
```

## What it does

**Find** — searches Ultimate Guitar and Songsterr at once, ranks results by how
well they match and how the host site's own users rated them, and links out. It
reads search listings only; tab content stays on the sites that host it.

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

# There isn't. Work it out from the recording.
tabfinder analyze bside.mp3

# Do both: search, and analyse the audio if the search comes up empty.
tabfinder song "Some Obscure B-Side" --audio bside.mp3

# Look up chord shapes, in any tuning, with or without a capo.
tabfinder chord Am7 Cmaj7 F#m --shapes 3
tabfinder chord D --tuning drop-d

# What can I play in this key?
tabfinder key "E minor" --sevenths

tabfinder tunings
```

Every command takes `--json` (for piping into something else), `--markdown`,
and `--out FILE`.

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

outcome = search_tabs("Oasis - Wonderwall")
for result in outcome.ranked("Oasis - Wonderwall"):
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
pytest                  # 185 tests
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

For analysis, supply your own audio — a file you own, recorded, or otherwise
have the right to use.

## Licence

MIT. See [LICENSE](LICENSE).
