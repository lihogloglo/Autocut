# SFX Selection & Placement Automation for YouTube Documentary/Essay Editing (Premiere Pro focus)

Research date: 2026-11-01. Pricing and features are as found on that date unless noted. The ~15-call budget meant many items come from search snippets, not full-page reads. Those are flagged.

## 1. Epidemic Sound: Premiere plugin, AI features, API, MCP

### Takeaway
Epidemic Sound is the most automation-ready source for this creator. Its Premiere plugin now includes Studio, which scans the video and drafts synced music plus SFX that it places on the timeline in one click (Dec 2025). It also has an AI Assistant that recommends SFX from natural language (Apr 2026). The official MCP server (public beta) works with individual subscriptions through an API key in Claude Code. The REST Partner API, by contrast, is partner-contract only; it has a free prototyping key capped at 50 downloads with no commercial licence.

### Cited Findings
- Studio was integrated into the Premiere Pro plugin on Dec 16, 2025. You select a section of the video and get an AI first draft synced to the visuals with music, sound effects and transitions. "All tracks and sound effects are added to the correct spot on your Premiere Pro timeline with one click." — [Epidemic press release 2025](https://corporate.epidemicsound.com/press-and-media/press-releases/2025/epidemic-sound-integrates-ai-powered-studio-within-adobe-premiere-pro-plugin/)
- How Studio works: it "scans your video to understand the mood, pacing, and specific actions" and syncs SFX "to specific visual cues" (e.g., footsteps for a walking person). You can add context in a description box (mood, narrative beats). "Timeline Sync" lets you audition against the edit. You can solo, mute, swap, trim and move clips, then click "Add to Timeline". Each clip has 9 alternative suggestions. Limits: plugin selection up to 4 min, web upload MP4/MOV/WebM up to 600 MB or 4 min. Available on the Creator, Pro and Business plans; Enterprise needs an AI Addendum. The page does not mention whooshes on transitions specifically, and aligning to cuts is done by moving clips manually. — [How to use Studio (Epidemic blog)](https://www.epidemicsound.com/blog/how-to-use-studio)
- On Apr 15, 2026, the AI Assistant came to the Premiere Pro and DaVinci Resolve plugins. It recommends music and SFX from natural-language requests, with drag-to-timeline. A desktop app covers Final Cut Pro, Pro Tools and others. — [Epidemic press release 2026 (snippet)](https://corporate.epidemicsound.com/press-and-media/press-releases/2026/epidemic-sound-integrates-ai-assistant-into-plugins-for-adobe-premiere-and-davinci-resolve-studio/); [Cision](https://news.cision.com/epidemic-sound/r/epidemic-sound-integrates-ai-assistant-into-plugins-for-adobe-premiere-and-davinci-resolve-studio,c4336355)
- Plugin v2.0 added faster music and SFX search plus stem separation. It opens via Window > Extensions > Epidemic Sound, needs an active subscription, and covers Premiere Pro, After Effects, Audition and DaVinci Resolve Studio. Since 2024 it has been available to all subscribers. — [Epidemic plugin blog](https://www.epidemicsound.com/blog/introducing-the-epidemic-sound-plugin-for-adobe-premiere-pro/); [PRNewswire 2024](https://prnewswire.com/news-releases/epidemic-sound-extends-adobe-premiere-pro-plugin-access-to-all-subscribers-alongside-numerous-updates-302114443.html)
- Adapt is an AI text-prompt tool that edits music tracks: mood, length, genre, style, instrumentation, per-stem edits, and generating missing stems (Nov 2025 expansion). It is music-focused, not SFX. — [Epidemic Adapt expansion PR 2025](https://corporate.epidemicsound.com/press-and-media/press-releases/2025/epidemic-sound-expands-adapt-functionality-to-give-creators-and-brands-more-creative-control/); [How to use Adapt](https://www.epidemicsound.com/blog/how-to-use-adapt)
- MCP Server (public beta):
  - Capabilities: music search (mood, BPM, genre, key, instrument, reference track), finding SFX in a 250,000+ catalog, recutting and looping tracks to target length, stems, Adapt, and AI voiceovers in 70+ languages. Example workflow: "read a brief, find music, cut to runtime… add transitions, save files".
  - Auth: Claude Code uses an API key generated in account settings. Claude Desktop and ChatGPT use OAuth. The endpoint is `https://www.epidemicsound.com/a/mcp-service/mcp`.
  - Plans: connecting and searching are free. Downloading needs a paid subscription. It is "not a new license" and there is nothing new to buy.
  - The Voices tool is not in the Claude directory version; it needs a custom connector.
  - Source: [Epidemic MCP page](https://www.epidemicsound.com/tools/mcp/); [MCP blog](https://www.epidemicsound.com/blog/mcp-server/)
- Partner Content API:
  - Using it needs a partnership agreement. Credentials go through the Developer Portal.
  - A free API key exists for prototyping. It covers the full catalogue and all endpoints except safelisting, with up to 50 downloads and no commercial licence.
  - SFX endpoints: collections, categories, tracks by category, search (`/v0/sound-effects/search`) and download (MP3). There is an `x-partner-user-id` header.
  - Base URL is `api.epidemicsound.com`. Older docs use `partner-content-api.epidemicsound.com`.
  - The docs also have a "soundtracking with LLM" guide.
  - Source: [Partner API docs](https://developers.epidemicsound.com/docs/); [API reference](https://developers.epidemicsound.com/docs/api-reference/); [SFX search endpoint](https://developers.epidemicsite.com/docs/Endpoints/get-sound-effect-search); [Soundtracking with LLM guide](https://developers.epidemicsound.com/docs/soundtracking-with-llm/)

### Inferences
- For an individual creator, the MCP server (via API key in Claude Code) is the only sanctioned programmatic route to search and download Epidemic SFX under the personal licence. The REST API is for platforms.
- A pipeline could look like this: an LLM proposes cues, the Epidemic MCP finds and downloads files, then a script inserts them into Premiere. Whether the MCP exposes a raw SFX file download to disk (rather than a link) is not confirmed (see Gaps).
- Studio covers Foley-ish visual-action SFX automatically, but it does not explicitly target whooshes on cuts or doc-style transitions. Those still need a cut-detection step.

### Gaps
- No primary-source list of the exact MCP tool names, or confirmation of SFX download to a local path through MCP.
- No confirmation that Adapt runs inside the Premiere panel, or that any "SFX matching to reference" feature exists.
- Epidemic plan prices for 2026 were not checked.

## 2. Generative SFX: ElevenLabs, Adobe Firefly in Premiere, open models

### Takeaway
ElevenLabs SFX v2 (`eleven_text_to_sound_v2`) is the default API model. It generates up to 30 s per call, supports seamless loops (useful for ambiences) and WAV 48 kHz output, and costs 40 credits/s. v3 is in limited access. ElevenLabs also launched a Video-to-Music API around mid-Oct 2026 that can add event-synced SFX as a separate stem. Premiere 26.5 (Sept 2026) has a native Generative Media Tool for text-to-SFX in the timeline. The open video-to-audio models with released weights are HunyuanVideo-Foley, MMAudio and ThinkSound, and their licences differ (see the open-model bullets below).

### Cited Findings
- ElevenLabs Sound Effects:
  - Models: `eleven_text_to_sound_v2` is the default. `eleven_text_to_sound_v3` (SFX v3) follows multi-part prompts better but is limited access and region-dependent ("Unknown model" error without access).
  - Duration: 0.1–30 s per generation, or automatic.
  - Looping: supported for seamless loops; the docs suggest generating 30 s and looping it.
  - Prompt influence control: high is literal, low is creative.
  - Output: MP3, plus WAV 48 kHz for non-looping effects.
  - Pricing: 40 credits per second when duration is specified.
  - Exact repetition counts (e.g., "4 times") are not reliably followed.
  - Source: [ElevenLabs SFX docs](https://elevenlabs.io/docs/overview/capabilities/sound-effects.md); [docs (html)](https://elevenlabs.io/docs/capabilities/sound-effects)
- An aggregator says ElevenLabs lists SFX at $0.12/min on its API pricing page — [modelslab aggregator](https://modelslab.com/best-sound-effects-api-2026.md); [ElevenLabs API pricing](https://elevenlabs.io/pricing/api). (Not verified directly; the snippet reports this figure.)
- Third-party hosts of ElevenLabs SFX v2 cap duration at 0.5–22 s. fal charges $0.002/s and WaveSpeed $0.0022/s, and loop and prompt_influence cost nothing extra. — [fal](https://fal.ai/models/fal-ai/elevenlabs/sound-effects/v2/llms.txt); [WaveSpeed](https://wavespeed.ai/docs/docs-api/elevenlabs/elevenlabs-sound-effects-v2)
- ElevenLabs Video to Music API (about 15 days before 2026-11-01, per search snippet): it takes video file(s), composes a score, and "can add sound effects synchronized to on-screen events". `separate_tracks` returns a ZIP with separate music and SFX files. — [AlphaSignal news](https://alphasignal.ai/news/elevenlabs-ships-video-to-music-api-that-auto-scores-footage-with-synced-effects) (secondary source; verify in ElevenLabs docs)
- An older ElevenLabs open-source "Video to Sound Effects" tool sends frames plus a prompt to GPT-4o, which writes an SFX prompt, which then goes to the SFX API. — [VentureBeat](https://venturebeat.com/ai/elevenlabs-unveils-open-source-creator-tool-for-adding-sound-effects-to-videos); [ElevenLabs blog](https://elevenlabs.io/blog/how-to-add-sound-effects-to-your-video-with-elevenlabs-video-to-sound-generator)
- Adobe Premiere Generative Media Tool:
  - It generates sound effects and video directly in the timeline. It went to beta on July 10, 2026, and a user reports it shipped in Premiere 26.5 on Sept 16, 2026.
  - SFX come from a text description, optionally guided by a voice recording for timing and intensity.
  - Length follows the selected timeline range.
  - Video models: Firefly plus partners (Veo 3.1 default; users mention Kling 3.0).
  - The SFX model and credits are not stated, and video-aware SFX are not described.
  - Content Credentials are attached at export.
  - Source: [Adobe Community announcement](https://community.adobe.com/announcements-732/now-released-generate-sound-effects-and-video-in-the-premiere-timeline-1631426)
- Firefly web "Generate Sound Effects": text prompt plus optional voice timing, a set duration, 4 variations, in the Firefly video editor (beta). — [Adobe HelpX](https://helpx.adobe.com/firefly/web/firefly-video-editor/generate-audio/generate-sound-effects.html); [Adobe Learn](https://www.adobe.com/learn/firefly/web/text-to-sound-effects)
- HunyuanVideo-Foley (Tencent): inference code and weights are released, including an XL variant with offload. The XXL needs about 20 GB VRAM (12 GB with offload). It claims SOTA on its own benchmarks (MovieGen-Audio-Bench, Kling-Audio-Eval, VGGSound). — [GitHub](https://github.com/Tencent-Hunyuan/HunyuanVideo-Foley); [HF](https://huggingface.co/tencent/HunyuanVideo-Foley); [arXiv 2508.16930](https://arxiv.org/pdf/2508.16930); [Replicate](https://replicate.com/tencent/hunyuanvideo-foley/readme)
- Stability's Foley Control paper compares MMAudio, HunyuanVideo-Foley and ThinkSound. MMAudio is best on KL-PANNs, FD-VGG and DeSync; Hunyuan is better on IB and KL-PaSST; ThinkSound trails. Foley Control itself is a frozen Stable Audio backbone plus a V-JEPA2 bridge. — [Foley Control arXiv](https://arxiv.org/pdf/2510.21581); [project page](https://stability-ai.github.io/foleycontrol.github.io/)
- Licences per a third-party repo PR: MMAudio is CC-BY-NC-4.0 and ThinkSound is research-only. Not verified upstream. — [reeleehq/foley PR #174](https://github.com/reeleehq/foley/pull/174)
- Stability: Stable Audio 3.0 publishes weights for Small, Small SFX and Medium variants. The Community License is free below $1M revenue. — [Stability explainer](https://stability.ai/explainers/stable-audio-vs-competitors-licensing-export-rights-and-self-hosting-compared)

### Inferences
- For documentary-style SFX (whooshes, paper, keyboard, room tone), text-to-SFX (ElevenLabs, Firefly, Stable Audio Small SFX) fits better than video-to-audio. B-roll in essays is often stock footage or graphics, where Foley models add little. Video-to-audio models are most useful on live-action B-roll lacking audio.
- ElevenLabs looping makes 30 s seamless ambience beds that can be tiled across long scenes.
- HunyuanVideo-Foley's licence terms should be checked before commercial (monetized YouTube) use.

### Gaps
- AudioGen/AudioCraft (Meta) and MMAudio licence and status were not verified this session. My prior knowledge, unverified: AudioCraft weights are CC-BY-NC.
- Kling/Veo native audio pricing was not researched.
- Firefly SFX credit cost and max duration were not found.

## 3. Tools that auto-place SFX on the timeline

### Takeaway
The commercial options inside Premiere are Epidemic Studio (video-aware draft placement) and third-party plugins such as PremiereCopilot ("Auto SFX": whooshes, impacts and risers) and FireCut (SFX synced to its zoom cuts and transitions, per its own blog). AutoCut uses SFX only for profanity bleeps. Short-form tools (Submagic, CapCut, Captions) auto-add whooshes and pops but sit outside Premiere. Open-source attempts exist but are young.

### Cited Findings
- PremiereCopilot: a native Premiere plugin "powered by Claude, GPT, and Gemini". It has an "Auto SFX" feature placing whooshes, impacts and risers, and supports Premiere 2022+ on macOS and Windows. Vendor claims only. — [premierecopilot.com](https://www.premierecopilot.com/en)
- FireCut: its blog says its library of effects (whooshes, clicks) is "automatically synced to your chosen transitions". Main features are silence removal, captions, zoom cuts and chapters. — [FireCut blog](https://firecut.ai/blog/3-premiere-pro-plugins-every-editor-needs/); [firecut.ai](https://firecut.ai/)
- AutoCut: the AutoProfanity filter masks expletives with SFX. No auto-whoosh feature was found. — [CineD on AutoCut](https://www.cined.com/autocut-plugin-now-integrates-ai-directly-into-premiere-pro-to-automatically-handle-time-consuming-tasks/)
- Submagic: one review says it "adds whooshes, dings and impacts on cuts", but a competitor's comparison calls the SFX manual (10 sounds plus uploads). The sources conflict. — [fastcoding review](https://www.fastcoding.dev/blog/submagic-co-review-ai-short-form-video-captions-2026); [storycut comparison](https://www.storycut.com/compare/captions-ai-vs-submagic)
- Captions app: "AI Sounds" text-to-SFX on the Max tier, mainly in the iPhone app. CapCut lists "Automated Sound Effects" and AI SFX on mobile. — [storycut comparison](https://www.storycut.com/compare/captions-ai-vs-submagic); [Submagic CapCut page](https://www.submagic.co/apps/capcut)
- Open source (from search snippets; repos not opened):
  - OpenCut-Enhanced: a Premiere extension that places whooshes, risers and impacts on visual cuts, text reveals and camera moves, with ducking. — [GitHub](https://github.com/RakibAhmed642/OpenCut-Enhanced)
  - ossclip: an LLM places SFX from a metadata-described library, gated by a deterministic density check. — [GitHub releases](https://github.com/AhsanAyaz/ossclip/releases)
  - Rameez-AI-Shorts-Editor: a two-pass LLM edit plan with 13 SFX kinds (whoosh, pop, riser, click…) placed on beats, rendered with ffmpeg. — [GitHub](https://github.com/rameezimdad/Rameez-AI-Shorts-Editor)
  - Smaxhy/video-editing PR #21: beat tracking plus a whoosh on non-cut transitions, with SFX synthesized in FFmpeg. — [PR](https://github.com/Smaxhy/video-editing/pull/21)

### Inferences
- No single mature tool reads a documentary transcript, picks semantically appropriate SFX (paper, keyboard, ambience) from a personal or Epidemic library, and places them in Premiere. Building that is a realistic custom project: cut and zoom detection for whooshes, plus an LLM over the transcript for semantic cues, plus a library search.
- The ossclip "density gate" is a pattern worth copying, to avoid SFX overload.

### Gaps
- aescripts tools (e.g., Sound Keys is an AE audio-to-keyframes tool, not a placer; an "Auto SFX" product) were not verified.
- Descript and Opus auto-SFX capabilities were not verified.
- No pricing collected for PremiereCopilot or FireCut.

## 4. Personal SFX library management & semantic search

### Takeaway
Commercial managers (Soundly, BaseHead, Curlo) now offer natural-language search and AI or UCS auto-tagging. The open-source route is CLAP embeddings plus a vector DB, and a user study shows CLAP search beats keyword search for professionals.

### Cited Findings
- Soundly: plain-language description search plus keywords, and a metadata editor supporting UCS for local libraries. — [getsoundly.com](https://getsoundly.com/)
- BaseHead: "Skills" runs 5 built-in AI tools across a selection to create, fix and tag metadata at scale. It has a UCS tab and a free tier. — [baseheadinc.com](https://baseheadinc.com/); [VI-Control thread](https://vi-control.net/community/threads/free-sample-organization-management-tool-updated-today-basehead-free.152681/)
- Curlo (macOS): local AI conversational search ("tense ambient drone"), plus auto-analysis that suggests and batch-assigns tags and UCS codes. — [ProductCool listing](https://www.productcool.com/product/curlo)
- In a CLAP-UI study with 20 audio professionals, CLAP search reduced frustration and improved efficiency compared with BBC SFX keyword search. — [arXiv 2504.15575](https://arxiv.org/pdf/2504.15575)
- AISearchSoundLibExplorer: local-first CLAP + Qdrant + RRF hybrid with segment-level retrieval. Metaphoric queries retrieve poorly. — [GitHub](https://github.com/Yuuichu/AISearchSoundLibExplorer-Showcase)
- ISMIR 2022 work on representation learning for auto-indexing SFX libraries notes that UCS-compliant datasets use the taxonomy non-uniformly. — [ISMIR paper](https://archives.ismir.net/ismir2022/paper/000104.pdf)

### Inferences
- A DIY stack fits a personal library well: LAION-CLAP or MS-CLAP embeddings, a FAISS or Qdrant index, UCS CatID filenames, and the LLM's cue text as the query. It can also index downloaded Epidemic SFX files.

### Gaps
- Sononym, SoundMiner, AudioFinder, Krotos/Sound Ideas and Splice AI features and pricing were not verified this session.
- LAION-CLAP and Microsoft CLAP repo details were not fetched. Likely URLs, unverified: github.com/LAION-AI/CLAP and github.com/microsoft/CLAP.

## 5. Programmatic SFX insertion in Premiere

### Takeaway
ExtendScript `Track.insertClip()` and `Track.overwriteClip()` / `Sequence.overwriteClip()` work today but are frozen legacy. UXP exposes `SequenceEditor.createInsertProjectItemAction(projectItem, time, videoTrackIndex, audioTrackIndex, limitShift)`, and its overwrite counterpart and edge cases need testing. XML import is the safe offline alternative.

### Cited Findings
- ExtendScript documents `Track.insertClip()` and `overwriteClip()`, which take a projectItem, a time, and zero-based track indices. Adobe plans no further ExtendScript changes ahead of the move to UXP. — [PPro Scripting Guide, Track](https://ppro-scripting.docsforadobe.dev/sequence/track/); [Sequence](https://ppro-scripting.docsforadobe.dev/sequence/sequence/)
- UXP `SequenceEditor` lists `createInsertProjectItemAction` (projectItem, time, videoTrackIndex, audioTrackIndex, limitShift). Actions run in a transaction. — [Adobe UXP SequenceEditor ref](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/sequenceeditor)
- Bug report (about Aug 2026): UXP `createCloneTrackItemAction` with isInsert=true can collapse an adjacent audio clip to zero duration. — [CC Developer Forums](https://forums.creativeclouddeveloper.com/t/premiere-pro-uxp-createclonetrackitemaction-with-isinsert-true-collapses-the-following-audio-clip-to-zero-duration/12077)
- Earlier, UXP lacked insertClip. That has since been addressed via actions. — [Adobe community thread](https://community.adobe.com/t5/premiere-pro-discussions/how-to-insertclip-in-uxp-plugin/m-p/15097904); [forum: add clips via UXP](https://forums.creativeclouddeveloper.com/t/how-to-add-clips-to-a-sequence-using-premiere-pro-uxp-api/8977)
- Workaround for audio-only insertion in ExtendScript: lock the other tracks. — [Adobe community](https://community.adobe.com/t5/premiere-pro/extendscript-videotrack-insertclip-for-video-or-audio-only/td-p/11145379); [PremiereOnScript log](https://premiereonscript.com/log-11/)

### Inferences
- For SFX, use overwrite rather than insert, so the edit does not ripple. Put SFX on dedicated audio tracks (e.g., A4–A6) to avoid touching dialogue.
- An alternative is to generate FCP7 XML or OTIO with SFX on new tracks and import it, or import an XML sequence and nest it. That has no plugin dependency, but it creates a new sequence rather than editing in place.

### Gaps
- No UXP code sample for audio-only overwrite was found. OTIO adapter support for Premiere XML was not verified this session.

## 6. LLM-driven transcript → SFX cue workflows

### Takeaway
Pieces exist: Epidemic's MCP server with its documented "read a brief… add transitions" workflow, the Epidemic "soundtracking with LLM" developer guide, ossclip's LLM SFX placement with a density gate, the ElevenLabs GPT-4o frame-to-prompt tool, and PremiereCopilot (an LLM-powered plugin). No published end-to-end documentary workflow outputs timestamped SFX cues into Premiere.

### Cited Findings
- Epidemic MCP example workflow: read a brief, find music, cut to runtime, add transitions, save files. — [Epidemic MCP page](https://www.epidemicsound.com/tools/mcp/)
- Epidemic developer guide "soundtracking with LLM". — [developers.epidemicsound.com](https://developers.epidemicsound.com/docs/soundtracking-with-llm/)
- ossclip: an LLM places SFX from a metadata library with a deterministic density check. — [GitHub](https://github.com/AhsanAyaz/ossclip/releases)
- ElevenLabs video-to-SFX: frames go to GPT-4o, which writes an SFX prompt for the SFX API. — [VentureBeat](https://venturebeat.com/ai/elevenlabs-unveils-open-source-creator-tool-for-adding-sound-effects-to-videos)
- Rameez-AI-Shorts-Editor: a two-pass LLM edit plan that includes SFX. — [GitHub](https://github.com/rameezimdad/Rameez-AI-Shorts-Editor)

### Inferences
- A suggested pipeline:
  1. Export the transcript with word timestamps (Premiere text-based editing or Whisper) and the cut list (from the sequence via script or XML).
  2. Detect cuts and zooms with PySceneDetect, keyframe reading, or similar.
  3. Have the LLM emit JSON cues (`{t, type, query, duration, gain}`) with category rules (whoosh on graphic transitions, keyboard under "typed/searched", paper under document B-roll, ambience per location) and a density cap.
  4. Resolve each cue against the local CLAP index, then Epidemic via MCP, then ElevenLabs generation as fallback.
  5. Insert with UXP overwrite onto dedicated SFX tracks, or emit XML.

### Gaps
- No Reddit (r/editors, r/sounddesign) practitioner opinions were gathered within the tool budget.
