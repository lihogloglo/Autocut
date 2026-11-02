# autocut

Sync camera and recorder files by sound, derush a long talking-head recording
against its script, and get one Premiere Pro XML back with three sequences. Then
gather illustrations from the script's links and place them on the edit at the
sentences they illustrate. Runs locally (faster-whisper on the GPU, or the CPU when
there is no NVIDIA card — much slower).

## The pipeline: every step works alone

| Step | In | Out | Alone? |
|---|---|---|---|
| Sync | rushes (camera + .wav) | `.sync.xml`: `1 sync` sequence | yes: no script |
| Derush | sync result, or any sequence exported from Premiere (raw or half derushed) + script | `.autocut.xml`: `2 triage`, `3 derush` | yes: give the Premiere XML |
| Illustrations: collect + pick | script (.md with links) | contact sheet, files per section, credits | yes: no derush needed |
| Illustrations: place | picks + `.autocut.xml` and/or your current edit (FCP7 XML) | B-roll at the sentence timecodes | re-run any time after re-editing |
| Illustrations: place, from Premiere | picks + the sequence open in Premiere ([panel](#premiere-panel)) | B-roll straight into the sequence | one click after each re-edit, no XML |
| Storyboard | script + a style in words (+ reference images) | a beat-by-beat storyboard: what to make, prompts, scenes; cards placed on the edit | yes: durations estimated without a derush |

The link between steps is the `Sxxx` sentence number: part 1 writes it in a marker over
every take, part 2 files every illustration under it.

## Window (for everyone)

Double-click **`Autocut.bat`** once: it installs uv and the Python packages, puts an
**Autocut** shortcut (🪓) on the desktop and opens the window. Afterwards, use the shortcut; run
the .bat again only after updating the code. The rest — ffmpeg, the transcription model (~3 GB),
a browser for page captures, the Premiere panel — is checked and installed from the window's
**Installation** page (bottom of the left column; it turns orange when something required is
missing). The **IA** page (just above it) picks the AI engine every step uses — see [AI engines](#ai-engines).

The window has one page per step (left column) and the script, shared by all steps, at the
bottom of that column. Drop files anywhere on the window: they go to the zone under the cursor,
or to the page you are on (a script always goes to the script, rushes to Synchro, a sequence to
Derush). Everything is remembered between sessions, and each step's result feeds the next.
Steps run in the background: the window stays responsive, a progress bar shows the step, the
percentage and the time left, and **Arrêter** stops the job at once.

1. **Synchro**: drop the rushes (camera videos + recorder .wav, or their folder), press
   **Synchroniser**. With the script set and *Enchaîner* ticked, the derush follows.
2. **Derush**: drop a sequence (the sync result, or anything exported from Premiere with
   File › Export › Final Cut Pro XML). The page reads it at once and says what it found:
   - raw: everything gets derushed;
   - **half derushed** (short clips, then long untouched rushes — people cut from left to
     right): it shows where you stopped and offers **Continuer** (keep everything before that
     point exactly as you cut it, derush the rest; the time can be changed) or **Tout refaire**;
   - how much audio still needs transcribing: transcripts are cached per rush file, so a
     re-exported or half-derushed sequence over the same rushes does not get transcribed again.
3. **Illustrations**: see [B-roll sourcing](#b-roll-sourcing-part-2). The output folder is shown
   on the page (**Ouvrir**).
4. **Storyboard**: see [Storyboard](#storyboard).

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
existing cuts are kept.

Half derushed by hand? `--keep-until auto` keeps the start of the sequence as you cut it
(clip for clip, colours and links included, gaps closed) up to where the long uncut rushes
begin, and derushes the rest; `--keep-until 3245.8` sets that point in sequence seconds. `--audio-track N` picks another track to transcribe,
`--sequence "name"` another sequence in the XML. Speed changes and nested
sequences are not supported.

## Output

Written next to the sources (`-o` for another folder):

| File | What |
|---|---|
| `Episode 12.sync.xml` | Sync only (no script): the `1 sync` sequence. |
| `Episode 12.autocut.xml` | **File → Import** in Premiere: a bin with three sequences, below. |
| `Episode 12.autocut.txt` | Sync report, then per script sentence: how many takes, where, how many failed, and which sentences were never recorded. |
| `Episode 12.sync.json` | Sync cache: re-runs skip the sync. |

Transcripts are cached per rush file (by name and size, so moving the rushes keeps them) in
`%LOCALAPPDATA%\autocut\transcripts`, with the source ranges already heard: any sequence built
from the same rushes reuses them and only never-heard parts get transcribed.

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
`--model large-v3` (or `large-v3-turbo`, faster) · `--drift-tolerance 0.005` · `--keep-until auto|<s>` · `-o <folder>`

## B-roll sourcing (part 2)

On the **Illustrations** page everything starts from the script: set it, press **1. Collecter**,
then **2. Choisir** (opens the contact sheet), click the thumbnails to keep and
**Exporter la sélection**. **3. Placer** needs one sequence (.xml): it is the derush result by
default; drop your current edit instead after re-editing, and the same picks go onto it (nothing
is downloaded again).

For every `[text](url)` in the script:

| Link | What comes back |
|---|---|
| Wikipedia | the article's images at full resolution, with author and licence from Commons (images of the `#section` first) |
| Article | its images at the largest size offered (`og:image`, `srcset`, WordPress / Cloudinary / CDN originals, Wikimedia originals), caption and credit; agency credits (AFP, Reuters, Getty…) flagged |
| PDF | the pages that match the sentence (and `(page 9)` / `[page 23](…)` hints) rendered as images, plus the figures inside |
| Video (YouTube, Facebook…) | the excerpt: `t=` in the link, else the minute whose captions match the sentence, or the whole video when short. Below 1080p, other uploads of the same video in higher resolution are offered too |
| Our World in Data, Archive.org | the chart (CC BY) / the item |
| Any page | tall lossless PNG screenshots (3840 × 8000 by default, up to 3840 × 16000; room to pan): top of page, the passage that supports the sentence (at ~40 % of the height), and the same passage highlighted |

Then a search per paragraph. Gemini or Claude reads the whole script and says, for each
paragraph, what can be shown (the event, its place and date — not the country or the theme),
the kind of picture wanted (map, portrait, photo, painting, document, filmed archive…), the
famous pictures of it it knows (a painting, a well-known photo, a map, with where they are
held), which Wikipedia articles cover it, catalogue queries, a YouTube query, and what the
ideal picture looks like. Searched, in that order: the images of those articles, their Commons
category and the Commons files tagged as depicting their subject (structured data, P180); the
famous pictures by name; Wikimedia Commons, Europeana; the Met (public domain) for paintings,
prints, portraits and photos; the David Rumsey Map Collection for maps; DuckDuckGo images
(unknown rights; video thumbnails and Pinterest reposts dropped); and all of YouTube (search
results only: a video is downloaded at export, if ticked). The candidates are ranked by what
their picture shows (CLIP, local), then the same model looks at the best 24 pictures and the
video thumbnails of each paragraph, scores them 0–10 and drops those under 5; its reason shows
on the contact sheet. An optional brief (window: « Consignes pour la recherche »; `--brief`) steers
both, e.g. « favour period documents: posters, front pages, engravings ». Without Gemini or Claude: Ollama writes the queries (no picture check),
else names and dates from the text (much weaker). Library of Congress and Gallica answer API
clients with a Cloudflare challenge, so they are reached through Commons and Europeana only.

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

Timings: each picture goes where its sentence is spoken in the sequence you give. In the
derush `.autocut.xml` the `Sxxx` markers say it directly. In your **current edit** (Premiere:
File → Export → Final Cut Pro XML) each sentence is found again wherever it is now — re-cut,
reordered, another take kept — by matching the rush time under the derush markers; and when
there is no derush at all (a sequence cut by hand), by listening to it: the voice is
transcribed (cached per rush, usually instant) and aligned to the script. Sentences cut out of
the edit are reported; their files are still exported. Without any XML, the illustrations go
one after the other.

```
uv run autocut-sources collect "episode 12.md" [--no-shots] [--no-search] [--no-web] [--llm auto|gemini|claude-code|codex|antigravity|claude|ollama|off] [--quality best|fast] [--no-judge] [--brief "…"] [--shot-height 4000]
uv run autocut-sources sheet "episode 12 - sources" [--derush "episode 12.autocut.xml"] [--edit "montage.xml"]
uv run autocut-sources export "episode 12 - sources" [--derush …] [--edit "montage.xml" [--edit-sequence name]]
```

Everything is cached in the output folder: re-running is fast and keeps the selection.
Screenshots use the Edge installed with Windows. The similarity model (~220 MB) and the
image model (~600 MB) are downloaded on first use. Recommended: a Gemini key (window, or
`GEMINI_API_KEY`; saved in `%APPDATA%\autocut\keys.json`; `AUTOCUT_GEMINI_MODEL` to change the
model, default `gemini-3.8-flash`) or `ANTHROPIC_API_KEY` for Claude (`AUTOCUT_CLAUDE_MODEL`).
"Auto" uses Gemini when a key is saved, else Claude. Otherwise `ollama serve` with any model
(`AUTOCUT_OLLAMA_MODEL` to choose).
`EUROPEANA_KEY` for your own free Europeana key.

Exports are always the best the source has: original image files (only formats Premiere
can't read are converted, losslessly; only images over 16384 px are reduced), videos at
their highest resolution and frame rate (4K60 included), re-encoded to visually lossless
H.264 only when needed (VP9/AV1 sources, or an excerpt cut between keyframes).

### Premiere panel

Instead of exporting the edit as XML and importing a B-roll XML back, the **Autocut** panel
works on the sequence open in Premiere (2025 v25.6 or later). **Placer les illustrations**
(or **Placer le storyboard**, with **Quoi › Storyboard**: the storyboard cards, at their beats)
reads the sequence, asks the Autocut window where each exported pick goes, imports the files
(bin `Illustrations - <title>`, one sub-bin per section; files already there are reused) and
puts them on the tracks above the edit, creating tracks when needed. Clicking it again after
re-editing first removes what it placed before (only files from the `export` folder: your
edit is never touched). **Retirer** removes them. Undo works, in a few steps.

The Autocut window must be open (the panel talks to it on `127.0.0.1:47820`), with the script
on the Illustrations page and the picks exported. Without the window:
`uv run autocut-sources premiere "episode 12 - sources" [--derush "episode 12.autocut.xml"]`.

Install (once, free):
1. Premiere: Preferences → Plugins → **Enable developer mode**, restart Premiere.
2. Install **UXP Developer Tools** from the Creative Cloud app (Apps → All apps).
3. In UXP Developer Tools: **Add Plugin** → pick `premiere/manifest.json` → **Load**. The panel
   is in Premiere's Window menu (UXP plugins → Autocut). To keep it without the tool,
   **Package** it there and double-click the `.ccx`.

## Storyboard

Not searching, suggesting: what to *make* to illustrate the script, in a style described in words
(« animations 3D lowpoly façon Blender, comme Fern et Lemmino, et motion design After Effects
épuré pour les chiffres et les cartes »), optionally with reference images.

1. **Style bible**: the AI turns the request into shared rules — palette (hex), light, materials,
   camera, typography, transitions, recurring motifs, the techniques and what each is for, what to
   avoid, and style keywords for image prompts. Names of creators become visual traits (image
   generators don't know them). Every later request carries the bible, so the shots stay coherent.
2. **Beats**: the script is cut into beats — one visual idea, consecutive sentences, ~6 s each
   (setting), with the real durations from the derush or the edit when there is one, else
   estimated from the text. Each beat: technique (or *face caméra*: keep the speaker; *archive*:
   a real document is stronger, see Illustrations), title, what we see, camera and animation, an
   image prompt and a video prompt (English), a structured scene (objects, environment, light,
   camera, palette: for Blender or a Blender MCP agent later), production notes, reuse of other
   beats' elements.
3. **Output** (`<script> - storyboard`): `storyboard.json`, `storyboard.md`, a 1920×1080 card per
   beat in `export/<section>/S014-01 B012 - <title>.png`, and `export/<title> Storyboard.xml`
   (the cards alone at their beats, and a copy of the edit with the cards above). Each card lasts
   its whole beat. In Premiere, the panel places the same cards in the open sequence (**Quoi ›
   Storyboard**).

The storyboard page (browser) shows the bible and every beat: edit any field (saved as you type,
the card is redrawn), change the technique, **verrouiller** a beat, **Refaire** one beat (with an
optional instruction: « plutôt une carte »), copy prompts and scenes, rewrite the XML. Running it
again with the same style keeps the bible and the locked beats.

```
uv run autocut-storyboard make "episode 12.md" --style "…" [--ref frame.png] [--pace 6] [--derush "episode 12.autocut.xml"] [--edit montage.xml] [--llm auto|gemini|claude-code|codex|antigravity|claude] [--quality best|fast]
uv run autocut-storyboard place "episode 12 - storyboard" [--edit montage.xml]
uv run autocut-storyboard page "episode 12 - storyboard"
```

## AI engines

Every step that needs an AI (illustration search, picture check, storyboard) uses the engine
chosen on the **IA** page (*Auto*: the first connected one, in this order):

| Engine | How | Notes |
|---|---|---|
| Gemini | API key pasted on the IA page (`%APPDATA%\autocut\keys.json`) | cheap; `AUTOCUT_GEMINI_MODEL` |
| Claude | API key (`ANTHROPIC_API_KEY`) | `AUTOCUT_CLAUDE_MODEL` |
| Claude subscription (Pro/Max) | the official Claude Code CLI, signed in | **Connecter** runs `claude auth login`; opus / sonnet |
| ChatGPT subscription | the official Codex CLI, signed in with ChatGPT | **Connecter** runs `codex login`; the model is taken from Codex's own list for the account |
| Gemini subscription (Google AI Pro/Ultra) | the official Antigravity CLI (`agy`), signed in | **Connecter** opens `agy` to sign in; Gemini models from `agy models` |
| Ollama | local | queries only: it does not look at pictures |

Subscriptions are used only by running the unmodified official CLIs with the user's own login,
on their machine; Autocut never reads their tokens. Missing CLIs install from the page
(**Installer**). **Tester** sends a tiny request with an image. **Qualité: Rapide** picks the
cheaper model of each engine. Subscription calls are slower (a few seconds each) and count against
the plan's usage limits.

## Tests

```
uv run --with pytest pytest tests
```
