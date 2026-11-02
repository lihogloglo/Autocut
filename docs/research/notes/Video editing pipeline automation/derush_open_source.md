# Open-source tools for derush / rough-cut automation of long talking-head recordings

Method note: star counts, last push dates, archived flags, language and license come from the GitHub REST API (`https://api.github.com/repos/{owner}/{repo}`), queried 2026-11-01. "pushed" is the last push to any branch, which is a proxy for last commit. Feature details come from each repo's README, fetched the same day. Unless stated otherwise, README claims were not verified by running the tools.

## Q1. Silence cutters (auto-editor, jumpcutter, unsilence, etc.): current state and Premiere XML export

### Takeaway
auto-editor is the only silence cutter that is actively maintained and has a real Premiere export. It writes an FCP7-style XML via `--export premiere`, plus Resolve, FCP, Shotcut and Kdenlive. carykh/jumpcutter and unsilence are effectively abandoned and only render media files, with no timeline export.

### Cited Findings
- **auto-editor** (WyattBlue): https://github.com/WyattBlue/auto-editor. 5,678 stars, pushed 2026-10-31, not archived, written in Nim (rewritten from Python), Unlicense (public domain). — [GitHub API](https://api.github.com/repos/WyattBlue/auto-editor); [repo](https://github.com/WyattBlue/auto-editor)
  - It cuts mainly on audio loudness and can also use motion. Thresholds are set in dB, and `--margin` adds padding (default 0.2s). — [repo](https://github.com/WyattBlue/auto-editor)
  - `--export` targets: `premiere` (an XML file importable into Premiere Pro), `resolve`, `final-cut-pro`, `shotcut`, `kdenlive`, `clip-sequence`. — [repo](https://github.com/WyattBlue/auto-editor)
  - It has an internal "label" system: 0 means silent (cut) and 1 means active (kept). Up to 255 classes can be defined with `--edit:N` / `--when:N`, and the higher label wins where classes overlap. `--when-active cut --when-inactive nil` exports the inverse, i.e. only the removed material. These are timeline-action classes, not Premiere colour labels. — [repo](https://github.com/WyattBlue/auto-editor)
  - It ships as an agent skill (`npx skills add WyattBlue/auto-editor`). — [repo](https://github.com/WyattBlue/auto-editor)
- **jumpcutter** (carykh): 3,146 stars, last push 2024-02-28, Python, MIT. It is the original jump-cut script and renders a new video, with no NLE export described. — [GitHub API](https://api.github.com/repos/carykh/jumpcutter)
- **jumpcutter** (kivancyuksel): a pip-installable Python CLI that jump-cuts silent parts. Search results mention no XML output. — [repo](https://github.com/kivancyuksel/jumpcutter)
- **unsilence** (lagmoellertim): 596 stars, last push 2023-03-28, Python, MIT. It speeds up silent parts (6x by default) rather than cutting them, and outputs only media files, with no XML or EDL. It has 14 open issues. — [GitHub API](https://api.github.com/repos/lagmoellertim/unsilence); [repo](https://github.com/lagmoellertim/unsilence)
- **unsilencevad** (rylefisher) is described as a VAD-based silence/pause remover that fast-forwards rather than cuts, to avoid clicks. The GitHub API returned 404 on 2026-11-01, so the repo is deleted, renamed or private. — [awesome.ecosyste.ms listing](https://awesome.ecosyste.ms/projects/github.com%2Frylefisher%2Funsilencevad)

### Inferences
- For a 1–2h single-shot recording, auto-editor's `--export premiere` is the most dependable open-source first pass for silence removal. It is loudness-based, not transcript-based, so it cannot detect retakes.
- jumpcutter and unsilence should be flagged as abandoned (no pushes for about 2.5 and 3.5 years). They are unsuitable for a Premiere workflow because they only produce rendered media.

### Gaps
- I did not inspect the exact XML auto-editor writes for Premiere (xmeml version, whether it emits `<labels>`, markers or one sequence per take). The README gives no details beyond "XML file".

## Q2. Transcript-based editors and retake / script-alignment tools

### Takeaway
A small number of 2026-era open-source projects explicitly detect repeated takes and keep the last one. They do it with text similarity (LCS, Jaccard, sentence similarity) or with an LLM. All are young, low-star projects. The most mature transcript editor, Rescript (about 1k stars), exports Premiere XML but does not detect retakes. No mature, widely used "script-to-take alignment with Premiere export" tool exists.

### Cited Findings
- **retake-cutter** (gkavtaradze92): https://github.com/gkavtaradze92/retake-cutter. 0 stars, pushed 2026-10-01, JavaScript, no license declared. — [GitHub API](https://api.github.com/repos/gkavtaradze92/retake-cutter)
  - It runs entirely in the browser. Whisper `Xenova/whisper-base.en` (via transformers.js) produces word timestamps, and an **LCS alignment of the script to the transcript** snaps repeated words to their **last occurrence, so the corrected retake wins**. Junk between two correct anchors is cut, and pauses longer than 1.2s are shortened rather than removed. — [repo](https://github.com/gkavtaradze92/retake-cutter)
  - An auto-detect mode (no script) splits speech into utterances on pauses and treats a later, closely repeated utterance as the retake. — [repo](https://github.com/gkavtaradze92/retake-cutter)
  - Export is a rendered video (ffmpeg.wasm trim and concat), with no XML. Limitations: matching is text-based, not phonetic. Retakes must repeat the words verbatim, so paraphrased retakes are missed. The default model is English-only. — [repo](https://github.com/gkavtaradze92/retake-cutter)
- **OpenRoughCut** (victinjr199xs-cyber): https://github.com/victinjr199xs-cyber/openroughcut. 0 stars, 3 commits, pushed 2026-10-17, Python, MIT. — [GitHub API](https://api.github.com/repos/victinjr199xs-cyber/openroughcut)
  - It "finds sentences you restarted or repeated and keeps the last attempt" using offline sentence similarity. An optional Claude pass (`--ai`) receives only the transcript text and picks sentences to drop by meaning. — [repo](https://github.com/victinjr199xs-cyber/openroughcut)
  - Exports: **FCP7 XML, EDL**, SRT/VTT, a JSON log of every cut and its reason, and an MP4 preview. An experimental UXP panel (Premiere 25.6+, connected via `orc serve`) is "not tested against every Premiere build". Whisper is prompted with a disfluent prompt to keep fillers. Colour labels and markers are not mentioned. — [repo](https://github.com/victinjr199xs-cyber/openroughcut)
- **Rescript** (wassgha): https://github.com/wassgha/rescript. 1,020 stars, pushed 2026-10-29, TypeScript (Next.js/React, plus an Electron desktop app), **PolyForm Noncommercial 1.0.0**, so no commercial use without a licence. — [GitHub API](https://api.github.com/repos/wassgha/rescript); [repo](https://github.com/wassgha/rescript)
  - You edit by deleting words, using Whisper (Base or Small) locally or an imported SRT/VTT/JSON transcript. It cuts fillers ("um", "uh") and pauses of 0.3s or more in one click. — [repo](https://github.com/wassgha/rescript)
  - Timeline exports: **DaVinci Resolve / Premiere XML, Final Cut FCPXML**, AAF, Reaper .rpp, Samplitude .edl and Blender. Retake detection is not mentioned. The README warns that word alignment can be off. — [repo](https://github.com/wassgha/rescript)
- **WhisperX** (m-bain): 24,986 stars, pushed 2026-10-22, BSD-2-Clause. It provides word-level timestamps via forced alignment, plus diarization, and serves as the timing layer for custom retake detectors. — [GitHub API](https://api.github.com/repos/m-bain/whisperX); [repo](https://github.com/m-bain/whisperx)
- **faster-whisper** (SYSTRAN): 26,362 stars, pushed 2026-10-31, MIT. — [GitHub API](https://api.github.com/repos/SYSTRAN/faster-whisper)
- **stable-ts** (jianfch): 2,281 stars, MIT. It does Whisper transcription with forced alignment of a known text, which is useful for script-to-audio alignment, but it is **archived** (last push 2026-05-30). — [GitHub API](https://api.github.com/repos/jianfch/stable-ts); [repo](https://github.com/jianfch/stable-ts)
- Other "retake" repos are not relevant. sergiojrdotnet/retake is a Linux teleprompter and recorder that follows your voice, and billyatminyawns/retake is pronunciation QA for AI voiceover. — [sergiojrdotnet/retake](https://github.com/sergiojrdotnet/retake); [billyatminyawns/retake](https://github.com/billyatminyawns/retake)

### Inferences
- The proven building blocks are WhisperX or faster-whisper (word timing), LCS or fuzzy alignment against the script (retake-cutter's "last occurrence wins" rule) and an XML writer. No single mature tool combines all three for 1–2h footage, so a custom pipeline is likely needed. retake-cutter's algorithm and OpenRoughCut's FCP7 XML exporter are good reference implementations.
- Text-only matching fails on paraphrased retakes. An embedding- or LLM-based similarity step (as in OpenRoughCut `--ai`) addresses this.
- Browser and transformers.js tools with whisper-base are unlikely to cope well with 1–2h files. This is inferred from the model size and in-browser processing, not tested.

### Gaps
- None of the retake tools publish accuracy figures on real retake-heavy footage.
- I did not find an open-source tool that scores multiple takes for "best" quality (delivery, fluency, energy). All of them use "keep last" or LLM judgment.

## Q3. Premiere XML with colour labels or markers, and open-source Premiere panels

### Takeaway
Several open-source Premiere panels (OpenCut, Ambar, VoidCutter, auto-cut-agent, OpenRoughCut) apply cuts directly in Premiere. Ambar uses review-first markers, and OpenCut can disable clips instead of deleting them. None documents setting clip colour labels or grouping alternate takes. FCP7 XML colour labels via `<labels><label2>` are reported to work by community users, but Adobe calls this unsupported.

### Cited Findings
- **OpenCut for Premiere Pro** (SysAdminDoc): https://github.com/SysAdminDoc/OpenCut. 64 stars, pushed 2026-09-26, Python backend (Flask), MIT. — [GitHub API](https://api.github.com/repos/SysAdminDoc/OpenCut)
  - It ships both a CEP panel (Premiere 2019+) and a UXP panel (Premiere 25.6+). — [repo](https://github.com/SysAdminDoc/OpenCut)
  - Features:
    - Silence removal via energy threshold or Silero VAD, with range review.
    - Filler detection via Whisper or **CrisperWhisper**.
    - **"Repeated Take Detection" via transcript Jaccard similarity**, producing reviewable proposals.
    - Optional local LLM via Ollama. — [repo](https://github.com/SysAdminDoc/OpenCut); [search summary](https://github.com/SysAdminDoc/OpenCut)
  - It applies cuts to the active sequence **as deletions or as disabled clips**. Exports include OTIO (clips, markers) and MLT. It can write beat markers as sequence markers, and colour labels are not mentioned. — [repo](https://github.com/SysAdminDoc/OpenCut)
  - Limitations: unsigned installers, UXP requires Developer Mode with no `.ccx` package, and FFmpeg must be 8.1.3 or later. The README says Adobe plans to end ExtendScript in September 2026, making UXP the long-term panel. On Premiere 2026, CEP panels appear under Window > Extensions (Legacy). — [repo](https://github.com/SysAdminDoc/OpenCut)
- **Ambar** (Robelob): https://github.com/Robelob/Ambar-AI-Video-Editor-Plugin-For-Premiere-Pro. 16 stars, pushed 2026-05-21, JavaScript, no licence declared. — [GitHub API](https://api.github.com/repos/Robelob/Ambar-AI-Video-Editor-Plugin-For-Premiere-Pro)
  - It is a UXP panel with a CEP/ExtendScript bridge. The pipeline is RMS silence detection, then Whisper (Groq, OpenAI or local whisper.cpp), then an LLM (Gemini by default; also Ollama, OpenAI, Claude, Groq) that returns cuts and retakes as JSON. — [repo](https://github.com/Robelob/Ambar-AI-Video-Editor-Plugin-For-Premiere-Pro)
  - **Analyze places orange markers** on the ruler without cutting. **Commit** razors and ripple-deletes via the QE DOM, working from the end of the timeline backward. — [repo](https://github.com/Robelob/Ambar-AI-Video-Editor-Plugin-For-Premiere-Pro)
  - Limitations: UXP cannot razor yet, so cutting needs the CEP bridge. Each cut is a separate undo step. The bridge has a 10s timeout, so committing many segments at once can fail. Crossfades must be added manually. — [repo](https://github.com/Robelob/Ambar-AI-Video-Editor-Plugin-For-Premiere-Pro)
- **VoidCutter** (Bulka0a): https://github.com/Bulka0a/VoidCutter. 0 stars, pushed 2026-08-21, JavaScript, MIT. — [GitHub API](https://api.github.com/repos/Bulka0a/VoidCutter); [site](https://voidcutter.pages.dev/)
  - It is a UXP panel (Premiere 25.6+). "Remove Silence" uses gaps in **Premiere's own transcript** with deterministic rules and needs no API key. "Remove Retakes" sends transcript words and timing to **Gemini**, which suggests repeated takes, abandoned fragments and chatter for user review. — [site](https://voidcutter.pages.dev/)
  - Limitations: it requires an existing Premiere transcript and a Gemini API key. Nested, multicam and speed-remapped timelines may misbehave. It works on a sequence copy for protection. — [site](https://voidcutter.pages.dev/)
- **auto-cut-agent / finaltake-agent** (rafcopy): https://github.com/rafcopy/finaltake-agent (the API resolves it to rafcopy/auto-cut-agent). 45 stars, pushed 2026-08-06, JavaScript, MIT. It is described as a UXP panel plus a local Node server doing "silence removal, repeated-take dedup (LLM), and minimal Hinglish captions". I did not fetch the README. — [GitHub API](https://api.github.com/repos/rafcopy/finaltake-agent); [repo](https://github.com/rafcopy/finaltake-agent)
- **FCP7 XML colour labels:**
  - Community users report setting a clip label with `<labels><label2>Forest</label2></labels>` (or Rose, etc.) inside `<clipitem>`. — [Adobe Community](https://community.adobe.com/t5/premiere-pro-discussions/using-xml-to-create-a-custom-label-color/m-p/12407825)
  - An Adobe Community Manager replied that editing XML to specify label colours is "unsupported" and not recommended. — [Adobe Community](https://community.adobe.com/t5/premiere-pro-discussions/using-xml-to-create-a-custom-label-color/m-p/12407852)
  - Another thread reports that Premiere does not keep existing labels and colours on imported clips. — [Adobe Community](https://community.adobe.com/t5/premiere-pro-discussions/color-labels-for-multi-track-audio-and-imports/td-p/12581197)

### Inferences
- The safest open-source pattern for a reviewable derush is "propose, then commit": markers (Ambar), disabled clips (OpenCut) or a duplicate sequence (VoidCutter). Disabled clips or markers in an FCP7 XML are a portable equivalent that avoids depending on panel APIs.
- `<label2>` colour labels in FCP7 XML may work, but they are undocumented and unsupported, so test them on the target Premiere version. Markers (`<marker>` in xmeml, supported by the OTIO FCP adapter) are the more reliable way to annotate takes.
- None of the tools found groups alternate takes, for example by stacking them on separate tracks or nesting them. A custom exporter could put rejected takes as disabled clips on V2/A2, or in a second sequence.

### Gaps
- I found no official Adobe documentation of the label names `<label2>` accepts. Community posts conflict on whether labels survive import.
- I did not verify whether auto-editor's or OpenRoughCut's FCP7 XML includes markers or labels.

## Q4. Filler-word and stutter detection models

### Takeaway
CrisperWhisper is the main open-source verbatim ASR model. It keeps fillers, repetitions, stutters and false starts and gives accurate word timestamps, but its weights are licensed for non-commercial use only. Standard Whisper tends to drop disfluencies, which tools work around with "disfluent" prompting.

### Cited Findings
- **CrisperWhisper** (nyrahealth): https://github.com/nyrahealth/CrisperWhisper. 1,470 stars, pushed 2026-09-22. The inference code is MIT, but the **model weights carry a non-commercial research licence**, and the "Pro" models are commercial-only. — [GitHub API](https://api.github.com/repos/nyrahealth/CrisperWhisper); [repo](https://github.com/nyrahealth/CrisperWhisper)
  - Verbatim mode captures fillers, repetitions, stutters, false starts and laughter, and an "intended" mode gives cleaned-up text. The authors report a 29.6 ms mean word-boundary error on TIMIT and about 41 ms on conversational speech. These are self-reported figures. Disfluency benchmarks cover 10 languages, while v1.0 was English and German only. — [repo](https://github.com/nyrahealth/CrisperWhisper)
  - Speculative decoding needs the CTranslate2 backend (NVIDIA on Linux). — [repo](https://github.com/nyrahealth/CrisperWhisper)
- OpenCut integrates CrisperWhisper as an optional filler detector. — [OpenCut repo](https://github.com/SysAdminDoc/OpenCut)
- OpenRoughCut notes that Whisper tends to drop hesitations and uses a disfluent prompt to keep fillers. — [OpenRoughCut repo](https://github.com/victinjr199xs-cyber/openroughcut)

### Inferences
- For mid-sentence restarts ("So the — so the reason is…"), verbatim transcription is essential. Otherwise Whisper normalises away the false start and the retake becomes invisible in the text. CrisperWhisper, or WhisperX with a disfluent prompt, is the practical choice. Check the CrisperWhisper weights licence before commercial use, such as a monetised YouTube channel.

### Gaps
- I found no independent benchmark comparing CrisperWhisper with disfluent-prompted Whisper or WhisperX on retake and false-start detection.
- I did not research other open disfluency models (e.g. dedicated stutter classifiers) because of the tool-call budget.

## Q5. OpenTimelineIO tooling for Premiere

### Takeaway
OTIO is active (about 2k stars, pushed 2026-10-31), but Premiere has no native OTIO import. The route is OTIO's FCP7 XML adapter (`otio-fcp-adapter`), which supports clips, gaps, multiple tracks, markers and nesting, but not transitions, effects or colour.

### Cited Findings
- **OpenTimelineIO** (AcademySoftwareFoundation): 2,050 stars, pushed 2026-10-31, C++ with Python bindings, Apache-2.0. — [GitHub API](https://api.github.com/repos/AcademySoftwareFoundation/OpenTimelineIO)
- **otio-fcp-adapter**: https://github.com/OpenTimelineIO/otio-fcp-adapter. 11 stars, pushed 2026-04-08, Apache-2.0. It reads and writes FCP7 XML. — [GitHub API](https://api.github.com/repos/OpenTimelineIO/otio-fcp-adapter); [repo](https://github.com/OpenTimelineIO/otio-fcp-adapter)
  - Supported: clips, multiple video and audio tracks, gaps, **markers**, nesting. — [repo](https://github.com/OpenTimelineIO/otio-fcp-adapter)
  - Not supported: transitions, effects, speed effects, CDL colour. The README says nothing about Premiere compatibility. — [repo](https://github.com/OpenTimelineIO/otio-fcp-adapter)
- OpenCut exports OTIO with clips and markers. — [OpenCut repo](https://github.com/SysAdminDoc/OpenCut)

### Inferences
- A custom pipeline could build an OTIO timeline (kept takes on V1, rejected takes on V2 or as markers) and convert it to FCP7 XML with otio-fcp-adapter for Premiere import. Clip colour labels would need a post-processing step on the XML, since the adapter does not handle them.

### Gaps
- I did not verify how well otio-fcp-adapter's output round-trips into current Premiere (2025/2026 builds).
- I did not check whether OTIO metadata maps to `<labels>`.

## Q6. LLM-based open-source rough-cut tools

### Takeaway
LLM-driven take selection is now common in open-source tools:
- **video-use** (30k stars) is a Claude Code agent workflow: an agent reads the transcript and makes the editing decisions, but it outputs a rendered MP4 and EDL rather than Premiere XML and needs ElevenLabs.
- Ambar, VoidCutter, auto-cut-agent, OpenCut (Ollama) and OpenRoughCut (`--ai`, Claude) add LLM retake judgment to Premiere panels or XML exporters.

### Cited Findings
- **video-use** (browser-use): https://github.com/browser-use/video-use. 30,289 stars, pushed 2026-10-08, Python, MIT. — [GitHub API](https://api.github.com/repos/browser-use/video-use)
  - An LLM running in a coding agent such as Claude Code reads a packed transcript (`takes_packed.md`) and makes the cuts. It "never watches the video", calling `timeline_view` only for visual checks at decision points such as retake comparisons. — [repo](https://github.com/browser-use/video-use)
  - It removes fillers, false starts and dead space between takes. — [search summary](https://github.com/browser-use/video-use)
  - Transcription uses **ElevenLabs Scribe**, which needs an API key and is not open-source. Output is `edit/final.mp4` plus an EDL in the pipeline, and no XML export is mentioned. A self-eval loop is capped at 3 re-renders. — [repo](https://github.com/browser-use/video-use)
- **OpenRoughCut `--ai`** runs an optional Claude pass that decides which sentences to drop "by meaning", using transcript text only. — [repo](https://github.com/victinjr199xs-cyber/openroughcut)
- **Ambar** has a multi-provider LLM that returns retakes and cuts as JSON, applied as markers and then cuts. — [repo](https://github.com/Robelob/Ambar-AI-Video-Editor-Plugin-For-Premiere-Pro)
- **VoidCutter** uses Gemini for retake suggestions. — [site](https://voidcutter.pages.dev/)
- **auto-cut-agent** uses an LLM for repeated-take deduplication. — [repo](https://github.com/rafcopy/finaltake-agent)
- **OpenCut** supports a local LLM via Ollama. — [OpenCut repo](https://github.com/SysAdminDoc/OpenCut)

### Inferences
- The dominant open-source architecture is: ASR with word timestamps, then a compact transcript sent to an LLM, then JSON keep/cut decisions, then markers, cuts or an XML export. For 1–2h recordings, the transcript must be chunked or packed (as video-use does) to fit context and keep costs down.
- video-use's popularity suggests the agent-driven approach has traction. Its lack of NLE XML export makes it a reference design rather than a drop-in tool for Premiere.

### Gaps
- None of these projects publishes evaluations of LLM take-selection accuracy.
- I did not review prompt templates (e.g. Ambar's `prompt-templates.js`).
- There may be more such projects in the GitHub topics video-editing-automation and talking-head. — [topic](https://github.com/topics/video-editing-automation); [topic](https://github.com/topics/talking-head?o=desc&s=updated)
