# autocut

Derush a long continuous talking-head recording against its script and get a
Premiere Pro timeline back. Runs fully locally (faster-whisper on the GPU, or the
CPU when there is no NVIDIA card — much slower).

## Window (for everyone)

Double-click **`Autocut.bat`**. The first time it installs what it needs (uv,
Python packages, ffmpeg if missing) and the transcription model downloads on the
first run (~3 GB). Then: pick the script, pick the XML exported from Premiere,
press **Lancer le derush**.

To give it to someone: copy this folder without `.venv`, `research_notes` and
`reports`.

## Command line

```
uv run autocut "D:\Rushes\episode 12.mp4" "D:\Scripts\episode 12.docx"
```

### From a Premiere sequence (camera + external mic)

Sync the a7s3 clip with the recorder's .wav in a sequence (or start from a
sequence you have already partly cut), then **File → Export → Final Cut Pro XML**:

```
uv run autocut "D:\Exports\Episode 12.xml" "D:\Scripts\episode 12.docx"
```

The .wav track is transcribed as it plays in the sequence; the output cuts
every track (video, camera audio, .wav) at the same points, so sync and your
existing cuts are kept. `--audio-track N` picks another track to transcribe,
`--sequence "name"` another sequence in the XML. Speed changes and nested
sequences are not supported.

Writes next to the source:

| File | What |
|---|---|
| `episode 12.derush.xml` | The derush: silences, failed takes, cut-off attempts and chatter removed. Every complete take is kept, in recording order. |
| `episode 12.backup.xml` | Backup: silences removed but every take kept, failed takes in Rose and chatter in Brown. To recover anything the derush dropped. |
| `episode 12.derush.txt` | Per script sentence: how many takes, where, how many failed, and which sentences were never recorded. |
| `episode 12.transcript.json` | Cached transcript; re-runs with other settings skip transcription. |

In Premiere: **File → Import** the XML. Clip names read `S012 T2/3 · <sentence>`
(script sentence 12, take 2 of 3).

## Colors

| Label | Meaning |
|---|---|
| Iris, Forest, Mango, Lavender, ... | Take 1, 2, 3, 4 ... of a sentence |
| Magenta | No complete take exists; best attempt kept (`INCOMPLETE`) |
| Tan | Off-script speech of 5+ words (`ADLIB`), kept for you to judge |
| Rose / Brown | Backup XML only: failed take / chatter |

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
`--model large-v3` (or `large-v3-turbo`, faster) · `-o <folder>`

## Tests

```
uv run --with pytest pytest tests
```
