# autocut

Sync camera and recorder files by sound, derush a long talking-head recording
against its script, and get one Premiere Pro XML back with three sequences.
Runs fully locally (faster-whisper on the GPU, or the CPU when there is no NVIDIA
card — much slower).

## Window (for everyone)

Double-click **`Autocut.bat`**. The first time it installs what it needs (uv,
Python packages, ffmpeg if missing) and the transcription model downloads on the
first run (~3 GB). Then: add the rushes (camera videos + recorder .wav, or their
folder — or a sequence exported from Premiere), pick the script, press **Lancer**.
Without a script, only the sync is made.

To give it to someone: copy this folder without `.venv`, `research_notes` and
`reports`.

## Command line

```
uv run autocut "D:\Rushes\Episode 12" "D:\Scripts\episode 12.docx"
uv run autocut C0001.MP4 C0002.MP4 ZOOM0001.WAV "episode 12.md"
uv run autocut "D:\Rushes\Episode 12"            # sync only
```

Inputs can come in any order: the script is recognised by its extension
(`.md`, `.txt`, `.docx`), a folder means every video/audio file in it.

### Or from a Premiere sequence

If you already synced (or partly cut) in Premiere, **File → Export → Final Cut
Pro XML** and give that instead of the rushes:

```
uv run autocut "D:\Exports\Episode 12.xml" "D:\Scripts\episode 12.docx"
```

The .wav track is transcribed as it plays in the sequence; the output cuts
every track (video, camera audio, .wav) at the same points, so sync and your
existing cuts are kept. `--audio-track N` picks another track to transcribe,
`--sequence "name"` another sequence in the XML. Speed changes and nested
sequences are not supported.

## Output

Written next to the sources (`-o` for another folder):

| File | What |
|---|---|
| `Episode 12.autocut.xml` | **File → Import** in Premiere: a bin with three sequences, below. |
| `Episode 12.autocut.txt` | Sync report, then per script sentence: how many takes, where, how many failed, and which sentences were never recorded. |
| `Episode 12.transcript.json`, `.sync.json` | Caches; re-runs with other settings skip transcription and sync. |

| Sequence | What |
|---|---|
| `1 sync` | The rushes synced: cameras on V1 (V2… if they overlap), their own audio, then the recorder. With an XML input, your sequence as it was. |
| `2 triage` | The whole recording, nothing removed: cut at every take, coloured by category (below), silences of 1 s or more as their own Blue clips. |
| `3 derush` | Good takes only, in recording order: silences, failed takes, cut-off attempts and chatter removed. |

All three use the same master clips, and clips keep their original names, so
proxies and the link to the rushes are kept. The take info is in a sequence marker
spanning each clip, reading `S012 T2/3 · <sentence>` (script sentence 12, take 2
of 3).

## Sync

Like PluralEyes: the audio of every file is compared with every other, so any
mix works — one camera file and one .wav, a camera that was stopped and restarted,
a recorder that split its file, two cameras. Files that share no sound with the
rest (a test clip) are reported `NOT SYNCED` and parked after the end of `1 sync`.

Recorder and camera clocks drift apart (a few to ~50 ppm: up to 0.3 s over 2 h).
The drift is measured and the recorder clip is cut at quiet spots into segments,
each re-aligned, so the error stays under `--drift-tolerance` (5 ms). The source
files are never modified or resampled. Recorder clips are placed to the sample
(Premiere's sub-frame `pproTicks`); videos sit on the frame grid.

Cameras with different frame rates in the same sync are not supported.

## Colors

| Label | Meaning |
|---|---|
| Iris, Forest, Mango, Lavender, ... | Take 1, 2, 3, 4 ... of a sentence |
| Magenta | No complete take exists; best attempt kept (`INCOMPLETE`) |
| Tan | Off-script speech of 5+ words (`ADLIB`), kept for you to judge |
| Rose / Brown / Blue | `2 triage` only: failed take / chatter / silence |

## How it decides

1. Word-level transcript (Whisper large-v3, French, prompted to keep false starts verbatim).
2. Alignment to the script that allows jumping back (a retake) or forward (a skipped line).
3. Per script sentence, attempts that reach the end are takes. An attempt that stops
   short is failed only if you retried the sentence afterwards; if you moved on it is
   kept as `INCOMPLETE`. A restart from mid-sentence ("signé en... signé en 1919") is
   joined to the start of the previous attempt, so the take reads cleanly.
4. Improvisation: changed or added words inside a sentence stay in the take; words
   said in the same breath as a take (reordered start, improvised ending) are glued
   to it, and a take with an improvised ending is labelled `IMPRO`. Short restart
   cues ("non, attends", "je reprends") are never glued. Fully improvised passages
   with no script match come out as `ADLIB`.
5. Pauses longer than `--max-pause` inside a take are cut; cut points are padded and
   snapped to the quietest spot.

Script: `.txt`, `.md` or `.docx`. Headings, links, URLs and `[1]` citations are ignored.

## Options

`--max-pause 0.6` · `--pad-in 0.12` · `--pad-out 0.25` · `--adlib-words 5` ·
`--model large-v3` (or `large-v3-turbo`, faster) · `--drift-tolerance 0.005` · `-o <folder>`

## B-roll sourcing (part 2)

Double-click **`Sources.bat`**, pick the Markdown script, press **1. Collecter**, then
**2. Ouvrir la planche**. Click the thumbnails to keep, then **Exporter la sélection**.

For every `[text](url)` in the script:

| Link | What comes back |
|---|---|
| Wikipedia | the article's images at full resolution, with author and licence from Commons (images of the `#section` first) |
| Article | its images at the largest size offered (`og:image`, `srcset`, WordPress originals), caption and credit; agency credits (AFP, Reuters, Getty…) flagged |
| PDF | the pages that match the sentence (and `(page 9)` / `[page 23](…)` hints) rendered as images, plus the figures inside |
| Video (YouTube, Facebook…) | the excerpt: `t=` in the link, else the minute whose captions match the sentence, or the whole video when short |
| Our World in Data, Archive.org | the chart (CC BY) / the item |
| Any page | 4K screenshots: top of page, the passage that supports the sentence, and the same passage highlighted |

Then a search per paragraph (names, dates, keywords; or Ollama/Claude queries):
Wikimedia Commons, Europeana, DuckDuckGo images (unknown rights), and YouTube for
paragraphs with an `(extrait …)` note.

Rights badges: **libre** (public domain / CC, credit needed), **citation** (screenshot
or excerpt), **à vérifier** (unknown, NC/ND), **protégé** (agency or stock site detected).

Export (`<script> - sources\export`): one folder per `##` section (import the folder in
Premiere: one bin per section), `credits.txt` ready for the video description,
`credits.csv`, and `<title> B-roll.xml`: a sequence with the picks at the derush
times when the part 1 `.autocut.xml` is given (from its `Sxxx` markers), else one after
the other.

```
uv run autocut-sources collect "episode 12.md" [--no-shots] [--no-search] [--no-web] [--llm off|ollama|claude]
uv run autocut-sources sheet "episode 12 - sources" [--derush "episode 12.autocut.xml"]
uv run autocut-sources export "episode 12 - sources" [--derush …]
```

Everything is cached in the output folder: re-running is fast and keeps the selection.
Screenshots use the Edge installed with Windows. The similarity model (~220 MB) is
downloaded on first use. Optional: `ollama serve` with any model for better queries
(`AUTOCUT_OLLAMA_MODEL` to choose), or `ANTHROPIC_API_KEY` for Claude (paid, a few
cents per script); `EUROPEANA_KEY` for your own free Europeana key.

## Tests

```
uv run --with pytest pytest tests
```
