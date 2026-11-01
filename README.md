# autocut

Sync camera and recorder files by sound, derush a long talking-head recording
against its script, and get one Premiere Pro XML back with three sequences. Then
gather illustrations from the script's links and place them on the edit at the
sentences they illustrate. Runs locally (faster-whisper on the GPU, or the CPU when
there is no NVIDIA card — much slower).

## The pipeline: every step works alone

| Step | In | Out | Alone? |
|---|---|---|---|
| Sync | rushes (camera + .wav) | `1 sync` sequence | yes: no script |
| Derush | sync result, or a sequence you synced yourself (FCP7 XML) + script | `2 triage`, `3 derush` | yes: give the Premiere XML |
| Illustrations: collect + pick | script (.md with links) | contact sheet, files per section, credits | yes: no derush needed |
| Illustrations: place | picks + `.autocut.xml` and/or your current edit (FCP7 XML) | B-roll at the sentence timecodes | re-run any time after re-editing |
| Illustrations: place, from Premiere | picks + the sequence open in Premiere ([panel](#premiere-panel)) | B-roll straight into the sequence | one click after each re-edit, no XML |

The link between steps is the `Sxxx` sentence number: part 1 writes it in a marker over
every take, part 2 files every illustration under it.

## Window (for everyone)

Double-click **`Autocut.bat`** once: it installs what it needs (uv, Python packages, ffmpeg if
missing), puts an **Autocut** shortcut on the desktop and opens the window (one tab per step).
Afterwards, use the shortcut. The transcription model downloads on the first run (~3 GB).

Files are dropped on the window (or picked with **Fichiers…**); each one goes where it belongs
by its type. The next step's button is highlighted, with one line saying what it does;
settings and the log are folded away (**▸ Réglages**, **▸ Détails**).

1. **Synchro & derush**: drop the rushes (camera videos + recorder .wav, or their folder — or
   a sequence exported from Premiere) and the script, press **Lancer**. Without a script,
   only the sync is made. When done, the illustrations tab picks up the `.autocut.xml` and
   the script.
2. **Illustrations**: see [B-roll sourcing](#b-roll-sourcing-part-2).

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

In the **Illustrations** tab: drop the Markdown script (and the `.autocut.xml` / your edit), press
**1. Collecter**, then **2. Choisir** (opens the contact sheet). Click the thumbnails to keep, then
**Exporter la sélection**. After re-editing in Premiere, **3. Placer sur le montage**
puts the same picks on the new edit (nothing is downloaded again).

For every `[text](url)` in the script:

| Link | What comes back |
|---|---|
| Wikipedia | the article's images at full resolution, with author and licence from Commons (images of the `#section` first) |
| Article | its images at the largest size offered (`og:image`, `srcset`, WordPress originals), caption and credit; agency credits (AFP, Reuters, Getty…) flagged |
| PDF | the pages that match the sentence (and `(page 9)` / `[page 23](…)` hints) rendered as images, plus the figures inside |
| Video (YouTube, Facebook…) | the excerpt: `t=` in the link, else the minute whose captions match the sentence, or the whole video when short |
| Our World in Data, Archive.org | the chart (CC BY) / the item |
| Any page | tall screenshots (3840 × 4800 by default, room to pan): top of page, the passage that supports the sentence (at ~40 % of the height), and the same passage highlighted |

Then a search per paragraph (names, dates, keywords; or Ollama/Claude queries):
Wikimedia Commons, Europeana, DuckDuckGo images (unknown rights), and YouTube for
paragraphs with an `(extrait …)` note.

Rights badges: **libre** (public domain / CC, credit needed), **citation** (screenshot
or excerpt), **à vérifier** (unknown, NC/ND), **protégé** (agency or stock site detected).

Export (`<script> - sources\export`): one folder per `##` section (import the folder in
Premiere: one bin per section; files are named `S014-01 …` after their sentence),
`credits.txt` ready for the video description, `credits.csv`, and `<title> B-roll.xml`
with two sequences:

| Sequence | What |
|---|---|
| `<title> B-roll` | the illustrations alone, each starting on its sentence, images lasting as long as the sentence (3–12 s); alternatives for one sentence stacked on V1, V2… To paste into your edit: select all, copy, put the playhead at the timecode the log gives, target V2, paste. |
| `<sequence> + B-roll` | a copy of `3 derush` (or of your edit) with the illustrations on the tracks above: open it and keep editing. |

Timings: give the part 1 `.autocut.xml` (its `Sxxx` markers say where each sentence is in
the rushes). Give also your **current edit** (Premiere: File → Export → Final Cut Pro XML)
and each sentence is found again wherever it is now — re-cut, reordered, another take
kept — by matching the rush time under it. Sentences cut out of the edit are reported;
their files are still exported. Without any XML, the illustrations go one after the other.

```
uv run autocut-sources collect "episode 12.md" [--no-shots] [--no-search] [--no-web] [--llm off|ollama|claude] [--shot-height 2400]
uv run autocut-sources sheet "episode 12 - sources" [--derush "episode 12.autocut.xml"] [--edit "montage.xml"]
uv run autocut-sources export "episode 12 - sources" [--derush …] [--edit "montage.xml" [--edit-sequence name]]
```

Everything is cached in the output folder: re-running is fast and keeps the selection.
Screenshots use the Edge installed with Windows. The similarity model (~220 MB) is
downloaded on first use. Optional: `ollama serve` with any model for better queries
(`AUTOCUT_OLLAMA_MODEL` to choose), or `ANTHROPIC_API_KEY` for Claude (paid, a few
cents per script); `EUROPEANA_KEY` for your own free Europeana key.

### Premiere panel

Instead of exporting the edit as XML and importing a B-roll XML back, the **Autocut** panel
works on the sequence open in Premiere (2025 v25.6 or later). **Placer les illustrations**
reads the sequence, asks the Autocut window where each exported pick goes, imports the files
(bin `Illustrations - <title>`, one sub-bin per section; files already there are reused) and
puts them on the tracks above the edit, creating tracks when needed. Clicking it again after
re-editing first removes what it placed before (only files from the `export` folder: your
edit is never touched). **Retirer** removes them. Undo works, in a few steps.

The Autocut window must be open (the panel talks to it on `127.0.0.1:47820`), with the script
in the Illustrations tab and the picks exported. Without the window:
`uv run autocut-sources premiere "episode 12 - sources" [--derush "episode 12.autocut.xml"]`.

Install (once, free):
1. Premiere: Preferences → Plugins → **Enable developer mode**, restart Premiere.
2. Install **UXP Developer Tools** from the Creative Cloud app (Apps → All apps).
3. In UXP Developer Tools: **Add Plugin** → pick `premiere/manifest.json` → **Load**. The panel
   is in Premiere's Window menu (UXP plugins → Autocut). To keep it without the tool,
   **Package** it there and double-click the `.ccx`.

## Tests

```
uv run --with pytest pytest tests
```
