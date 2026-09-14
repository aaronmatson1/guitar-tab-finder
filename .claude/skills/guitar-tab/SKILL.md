---
name: guitar-tab
description: Find guitar tabs for a song, or work out the key, chords and tab from an audio file when no tab exists. Use when someone asks how to play a song on guitar, wants tabs or chords for a track, asks what key a song is in, or points at an audio file and wants to learn to play it.
---

# Guitar tab finder

Two paths. Pick based on what the user gave you.

## They named a song

```bash
tabfinder find "Artist - Title" --json
```

Exit code 0 means tabs were found; 1 means the search worked but found nothing.
Report the top two or three with their links — don't dump all ten.

## They gave you audio (or the search found nothing)

```bash
tabfinder analyze path/to/song.mp3 --json
```

Add `--melody` only for an isolated riff or intro; it is monophonic and will
produce nonsense on a full mix.

For the human-readable tab sheet (chord diagrams, rhythm tab, timeline), drop
`--json`. That output is meant to be shown as-is — it is already formatted.

## Both at once

```bash
tabfinder song "Title" --audio file.mp3 --json
```

Searches first, analyses the audio only if nothing turns up. Add
`--always-analyze` to do both regardless.

## Other useful commands

```bash
tabfinder chord Am7 F#m --shapes 3      # chord shapes
tabfinder key "E minor" --sevenths      # what's playable in a key
tabfinder tunings                       # list tunings
```

Global flags: `--tuning`, `--capo`, `--json`, `--markdown`, `--out FILE`.

## Reading the analysis JSON

- `key.confidence` under ~0.3 means the key is genuinely ambiguous — say so
  rather than stating it flatly, and mention `key.alternatives`.
- `progression.loop` is the repeating chord loop; `progression.numerals` is it
  in roman numerals, and `progression.name` names it when it's a well-known one.
- `capo` is worth passing on — it often turns a barre-chord song into open
  chords.
- `chords` is the full timeline with timestamps.

## When the chords look wrong

Chord recognition is a first draft. If the user says a chord is off:

- `--sensitivity` lower (e.g. `1.5`) catches quicker chord changes; higher
  (e.g. `6`) steadies jittery output.
- `--start` / `--duration` narrows analysis to one section.
- Suggest the relative major/minor or a sus chord — those are the usual misses.

Don't present detected chords as certain. The tool prints its own caveats; keep
them.
