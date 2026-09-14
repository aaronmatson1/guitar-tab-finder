---
name: guitar-tab
description: Find guitar tabs for a song, work out the key and chords from audio when no tab exists, or transcribe a guitar solo with its bends, slides and hammer-ons. Accepts a song title, a YouTube/Spotify/Apple Music link, or a local audio file. Use when someone asks how to play a song on guitar, wants tabs or chords for a track, asks what key a song is in, asks for a solo to be tabbed, or shares a music link or audio file and wants to learn to play it.
---

# Guitar tab finder

Two paths. Pick based on what the user gave you.

## They named a song, or pasted a link

```bash
tabfinder find "Artist - Title" --json
tabfinder find "https://youtu.be/VIDEO_ID" --json
```

Links (YouTube, Spotify, Apple Music) work anywhere a title does — the tool
resolves the track name itself. Don't try to guess the song from the URL.

Exit code 0 means tabs were found; 1 means the search worked but found nothing.
Report the top two or three with their links — don't dump all ten.

## They gave you audio or a link (or the search found nothing)

```bash
tabfinder analyze path/to/song.mp3 --json
tabfinder analyze "https://open.spotify.com/track/ID" --json
```

Add `--melody` only for an isolated riff or intro; it is monophonic and will
produce nonsense on a full mix.

For the human-readable tab sheet (chord diagrams, rhythm tab, timeline), drop
`--json`. That output is meant to be shown as-is — it is already formatted.

## Both at once — the usual best choice for a link

```bash
tabfinder song "https://youtu.be/VIDEO_ID" --json
tabfinder song "Title" --audio file.mp3 --json
```

Searches first, analyses the audio only if nothing turns up. Add
`--always-analyze` to do both regardless.

## What a link can and cannot give you

- **YouTube** — name always; full audio only with `--allow-download` (needs
  `yt-dlp` installed).
- **Apple Music** — name and a 30-second preview clip.
- **Spotify** — name only. The audio is DRM-protected and is never available.
  The tool automatically falls back to the same song's iTunes preview clip.

So by default an analysis from a link usually runs on a **30-second preview**.
Check `analysis.partial` in the JSON: when it is `true`, say so — the key and
main progression hold, but the intro/bridge/outro are not covered. Offer
`--allow-download` (YouTube only) or a local file if they want the whole song.

If audio cannot be had at all, the error explains why and what to do; pass that
on rather than retrying blindly.

## Tabbing a guitar solo

```bash
tabfinder solo song.mp3 --json
tabfinder solo "https://youtu.be/VIDEO_ID" --json
tabfinder solo song.mp3 --solo-from 2:14 --solo-to 2:48   # name the section
```

`--solo` on `analyze` does the same as part of a full analysis.

Read the caveats out rather than presenting the result as definitive:

- It finds the most prominent **lead line**, not "the guitar solo" specifically.
  During an instrumental break that is the solo; elsewhere it may be the vocal.
  If the section looks wrong, `solo_candidates` in the JSON lists the runners-up
  with timestamps, and `--solo-from` / `--solo-to` override the choice.
- Bends, slides and vibrato are reliable. Hammer-ons and pull-offs are
  deliberately under-reported, so their absence means nothing.
- On a bend the fret shown is the one held, not the pitch arrived at.

`--demucs` separates the lead from the mix first and helps a lot on a dense
recording, but it is slow and needs demucs installed. Suggest it if the result
looks noisy; don't use it by default.

## The web UI

```bash
tabfinder serve --open
```

Suggest this when someone wants to see results rather than read them, or is
going to try several songs. It does everything the CLI does, with SVG chord
diagrams and file drag-and-drop. Local only, no authentication.

## Other useful commands

```bash
tabfinder chord Am7 F#m --shapes 3      # chord shapes
tabfinder key "E minor" --sevenths      # what's playable in a key
tabfinder tunings                       # list tunings
```

Global flags: `--tuning`, `--capo`, `--json`, `--markdown`, `--out FILE`.
Link flags: `--allow-download`, `--no-preview`, `--keep-audio DIR`.

## Reading the analysis JSON

- `key.confidence` under ~0.3 means the key is genuinely ambiguous — say so
  rather than stating it flatly, and mention `key.alternatives`.
- `progression.loop` is the repeating chord loop; `progression.numerals` is it
  in roman numerals, and `progression.name` names it when it's a well-known one.
- `capo` is worth passing on — it often turns a barre-chord song into open
  chords.
- `partial` / `source_label` say whether only a clip was analysed, and where
  the audio came from. Don't present a preview-based analysis as the whole song.
- `solo` holds the transcribed solo; `solo_candidates` the other sections that
  looked like a lead line.
- A chord entry with `monophonic: true` is a stretch where only one note was
  sounding, so the chord named there describes the line being played, not the
  harmony. Those are already excluded from the progression - don't reintroduce
  them.
- `chords` is the full timeline with timestamps.

## When the chords look wrong

Chord recognition is a first draft. If the user says a chord is off:

- `--sensitivity` lower (e.g. `1.5`) catches quicker chord changes; higher
  (e.g. `6`) steadies jittery output.
- `--start` / `--duration` narrows analysis to one section.
- Suggest the relative major/minor or a sus chord — those are the usual misses.

Don't present detected chords as certain. The tool prints its own caveats; keep
them.
