# End-to-end pipelines and the Premiere Pro / Adobe automation layer (status as of 2026-11-01)

Scope: tools and agents that cover more than one of (1) derushing a long talking-head take, (2) sourcing B-roll and illustrations from a script with citations, (3) placing sound effects. Plus the technical ways to build a custom pipeline around Premiere Pro.

## Q1. Premiere Pro scripting and automation in 2026: UXP, ExtendScript/CEP, MCP servers, Adobe's own agent

### Takeaway
UXP for Premiere Pro is officially released. It shipped as a public beta in 25.2 (Dec 2024) and went to "official release" in 25.6. Since then 26.x builds have added real timeline-editing APIs: insert, overwrite and remove track items, in/out points, markers with GUIDs, transcripts, subclips and AAF export. CEP/ExtendScript still works and is still what the most mature community MCP servers rely on. Adobe's stated hard cutoff is that CEP stops shipping after December 2029. Several open-source Premiere MCP servers let Claude drive the timeline today. The official Adobe connector for Claude (Apr 2026) and the Firefly AI Assistant (public beta, 2026) are not yet a precise timeline-editing layer.

### Cited Findings
**UXP status and APIs**
- Premiere UXP changelog: 25.2.0 (Dec 4, 2024) was the "initial public beta". 25.6.0 is "official release of UXP extensibility", described as approaching parity with CEP/ExtendScript. 26.2.0 added UXP Hybrid Plugins (native C++ `.uxpaddon`). 26.3.0 has a breaking change: `create*Action` calls must run inside `lockedAccess`, and `Sequence.setSelection` became synchronous. It also added `createSetNameAction` for tracks, `ClipProjectItem.createSubClipAction`, a marker `guid` property, transcript `querySupportedLanguages`/`hasTranscript`, AME `EncoderManager`, `ObjectMaskUtils`, `createSequenceWithPresetPath`, AAF export and `SourceMonitor.setPosition`. 26.5.0 added `transcribeClipProjectItem`, `isLanguagePackAvailable`, synchronous Media `getDuration`/`getStart`, a marker color enum fix (`MAGNETA` changed to `MAGENTA`), and the `C2PAService`, `MediaManager` and `WorkAreaUtils` classes — [Adobe Premiere UXP changelog](https://developer.adobe.com/premiere-pro/uxp/changelog/)
- The beta-era API additions (March 2025) were insert, overwrite and remove of track items via `createOverwriteItemAction`, `createInsertProjectItemAction` and `createRemoveItemsAction`. September 2025 added `Sequence.createSetInPointAction()`/`createSetOutPointAction()` and a SequenceSettings API (frame rect, pixel aspect ratio) — [CC Developer forum: New UXP APIs](https://forums.creativeclouddeveloper.com/t/new-uxp-apis-available-in-premiere-pro/10890); [New APIs available in Premiere Pro](https://forums.creativeclouddeveloper.com/t/new-apis-available-in-premiere-pro/11397)
- A developer reported that the in/out actions failed silently in Beta 25.4.0 / UXP 8.1.0. A later reply said trimming worked on a later Mac build — [CC Developer forum](https://forums.creativeclouddeveloper.com/t/new-apis-available-in-premiere-pro/11397)
- Version coupling: a plugin that uses an API from a newer UXP version will fail on an older Premiere — [Adobe: Understanding UXP APIs](https://developer.adobe.com/premiere-pro/uxp/resources/fundamentals/apis)
- An older Adobe partner page (copyright 2024) set UXP 1.0 GA as a target for "a Premiere Pro 25.x release". It promised CEP support for at least one more major cycle after UXP 1.0, and called the timelines "targets, not commitments" — [Adobe Video Partner: Extensibility update](https://www.adobevideopartner.com/customer-stories/extensibility-update/)
- Clip color labels: the changelog extract did not mention a UXP color-label API. The leancoderkavy MCP README says its UXP bridge adds "source-item color labels", so some label support exists via UXP. Exact API names are unverified — [leancoderkavy/premiere-pro-mcp](https://github.com/leancoderkavy/premiere-pro-mcp)

**ExtendScript/CEP deprecation**
- An Adobe developer forum post dated Sept 25, 2026 says CEP "stops shipping in any of these apps after December 2029". It says each flagship app "gets a guaranteed two year runway from its own UXP beta" and that Premiere "already support[s] UXP", while After Effects "will follow" — [CC Developer forum: CEP to UXP – What Developers Need to Know](https://forums.creativeclouddeveloper.com/t/cep-to-uxp-what-developers-need-to-know/12189)
- A March 2026 community question claims "ExtendScript support is ending September 2026". This is a user claim and is not confirmed by Adobe. It conflicts with the December 2029 CEP statement above, unless it refers to a narrower ExtendScript-specific change — [Adobe Community: ExtendScript to UXP for Premiere Pro](https://community.adobe.com/questions-729/extendscript-to-uxp-for-premiere-pro-1553924)

**Premiere MCP servers (community, not Adobe)**
- **hetpatel-11/Adobe_Premiere_Pro_MCP** (~798 stars, 150 forks, catalog status dated Aug 31, 2026). A Node MCP server generates ExtendScript, and a CEP panel executes it through a temp-dir bridge. "CEP is the supported production bridge; UXP remains experimental." It exposes 283 tools, including `add_to_timeline`, `insert_from_source`, `overwrite_from_source`, `add_marker`/`update_marker`/`list_markers`, `set_color_label`/`get_color_label`, `split_clip`, `razor_timeline_at_time`, `razor_all_tracks`, `create_sequence` and `get_sequence_structure`. Tested on Premiere 26.0. Its stated limits: Premiere 26 has no scripting API to remove effects, caption text is often unreadable via the DOM, titles need MOGRTs, and the CEP .zxp is self-signed — [GitHub](https://github.com/hetpatel-11/Adobe_Premiere_Pro_MCP)
- **leancoderkavy/premiere-pro-mcp** (MIT, npm `premiere-pro-mcp` v1.25.0, ~468 stars, 1,374 commits). It has a CEP/ExtendScript production bridge plus a UXP "preview" bridge: an authenticated WebSocket on 127.0.0.1:7777 that needs Premiere 25.6+ and adds 97 tools. It lists 444 tools (insert/overwrite, split, ripple delete, roll/slide/slip, move clip to track, marker CRUD, color labels) and 29 guided workflows. Its stated limits: QE DOM tools are experimental, and some 26.3 installs silently ignore QE structural edits (the server verifies and errors instead). There is no setter for clip speed or reverse, and `add_text_overlay` is disabled because no raw-text-to-caption API exists — [GitHub](https://github.com/leancoderkavy/premiere-pro-mcp)
- Other repos: antipaster/Adobe-Premiere-Pro-MCP (Windows, 170+ tools, Premiere 2023+). morim3/mcp_adobe_premiere (Python fastmcp + UXP, Premiere Beta 25.3+, only 3 commits). ayushozha/AdobePremiereProMCP (Go server + TS bridge). toonyai premiere-mcp finds clips via transcription and visual analysis and inserts them, and needs FFmpeg and an Anthropic key — [antipaster](https://github.com/antipaster/Adobe-Premiere-Pro-MCP); [morim3](https://github.com/morim3/mcp_adobe_premiere); [ayushozha](https://github.com/ayushozha/AdobePremiereProMCP); [lobehub listing](https://lobehub.com/mcp/toonyai-premiere-mcp)

**Adobe's own AI / agent features**
- On Apr 28, 2026, Anthropic launched 9 creative connectors, including an Adobe "for creativity" connector (an MCP server) reported to expose 50+ tools across Photoshop, Illustrator, Firefly, Express, Premiere, Lightroom, InDesign and Stock — [AlternativeTo](https://alternativeto.net/news/2026/4/anthropic-launches-claude-connectors-for-adobe-blender-ableton-and-more/); [No Film School](https://nofilmschool.com/adobe-claude-connector-announced); [letsdatascience](https://letsdatascience.com/news/adobe-integrates-creative-cloud-tools-into-anthropic-claude-a7c4eae3)
- Counterpoint (May 1, 2026): MindStudio's hands-on review says the connector "operates at Adobe Express level, not Photoshop or Premiere". It found no timeline control, audio mixing or grading. A 9x16 reframe took 3m14s and mis-centered the subject — [MindStudio](https://www.mindstudio.ai/blog/claude-mcp-adobe-vs-photoshop-premiere-what-it-does)
- Firefly AI Assistant is a chat agent that coordinates tools across Photoshop, Lightroom, Premiere Pro, Illustrator and others. It is a **public beta** for CC Pro and paid Firefly plans, with daily refreshed credits during the beta — [FoneArena](https://www.fonearena.com/blog/481226); [RedShark News](https://www.redsharknews.com/adobe-firefly-ai-assistant-public-beta); [t2online, 28 Apr 2026](https://t2online.in/tech/tech-news/adobe-launches-firefly-ai-assistant-public-beta-for-creative-cloud-users/2004851)
- Reports say the assistant was later embedded inside Premiere, Photoshop, Illustrator, InDesign and Frame.io as public betas. The Premiere features described are clip organization and asset renaming. The dates are inconsistent (one report says June 18, 2026) and I found no official Adobe Premiere feature list — [WebProNews](https://www.webpronews.com/adobe-puts-its-firefly-ai-agent-inside-premiere-photoshop-and-illustrator/) (403 on fetch; snippet only); [pulse.bot](https://www.pulse.bot/ai/news/adobe-adds-its-ai-assistant-to-premiere-illustrator-and-indesign-0a327057-b8c6-44d6-9936-cba6a9f09ce5/)

### Inferences
- For a custom Claude-driven pipeline today, the most capable path is either a community MCP server on the CEP bridge (most tools, deprecated but supported until 2029) or a custom UXP panel (future-proof, but you must handle `lockedAccess`/action semantics and version gating). leancoderkavy's dual-bridge design shows the transition pattern.
- MCP servers report silent failures (QE edits in 26.3, in/out actions in 25.4). Any pipeline should read the timeline state back after each write.
- Adobe's first-party agents (Firefly AI Assistant, the Claude connector) do not cover the three target stages at timeline precision. Treat them as beta and not suitable for derush, B-roll or SFX placement.

### Gaps
- No official Adobe date for removing ExtendScript from Premiere specifically. The Sept 2026 claim and the Dec 2029 statement conflict.
- I did not verify the exact UXP API for project-item or track-item color labels, or whether UXP can add audio clips to specific tracks with keyframed levels (relevant for SFX).
- The concrete Premiere tool list of the official Adobe Claude connector is unverified.

## Q2. Interchange formats: FCP7 XML, OTIO, EDL, .prproj manipulation

### Takeaway
FCP7 XML (xmeml) remains the de facto robust route into Premiere, used by Gling, Eddie AI and OTIO's `fcp_xml` adapter. Premiere also has native OTIO import/export (beta Oct 2024, later announced as released), which carries markers with name, color and comments. Users still report XML as more robust. `.prproj` is gzipped XML, and a Python library (py-premiere) claims round-trip editing.

### Cited Findings
- OpenTimelineIO's `fcp_xml` adapter supports interchange with Premiere via FCP7 XML, "based on guidance from Adobe". A `cmx_3600` EDL adapter also exists, and the contrib `fcpx_xml` adapter supports markers but not transitions or effects — [OTIO repo mirror](https://github.com/bashesenaxis/OpenTimelineIO); [otio-fcpx-xml-adapter PyPI](https://pypi.org/project/otio-fcpx-xml-adapter/1.0.0)
- Native OTIO import/export in Premiere was introduced in beta in Oct 2024. Sequence markers carry start, duration, name and color, and clip markers also carry comments. Export is under File > Export > OpenTimelineIO. A later announcement is titled "Now released: OTIO import and export" — [Adobe Community beta post](https://community.adobe.com/t5/premiere-pro-beta-discussions/new-in-beta-otio-import-and-export/m-p/14937493); [Now released](https://community.adobe.com/announcements-732/now-released-otio-import-and-export-311699)
- Forum users report that XML is far more robust than OTIO. OTIO exported from Premiere uses a `file://` prefix that other NLEs may reject — [Adobe Community](https://community.adobe.com/t5/premiere-pro-beta-discussions/now-in-beta-otio-import-and-export/m-p/14985932)
- editingtools.io converts OTIO marker files to FCP7 XML for import into Premiere via File > Import, a workaround for getting markers in — [editingtools.io guide](https://fr.editingtools.io/guides/convert-otio-to-pr-marker)
- Commercial tools use XML as the hand-off. Gling exports XML to Premiere, FCP and Resolve, including on the free tier (1 h/month, watermark) — [Gling](https://www.gling.ai/aini). Eddie AI exports XML/FCPXML, and now also has a Premiere extension that imports and exports sequences without XML — [Eddie help](https://intercom.help/ed-9a7825885c52/en/articles/9944870-import-your-edit-s-xml-into-adobe-premiere)
- `.prproj` is GZIP-compressed XML in recent versions — [convert.guru](https://convert.guru/ko/prproj-byeonhwangi); [Adobe Community 2013](https://community.adobe.com/t5/premiere-pro-discussions/premiere-pro-cc-project-file-prproj-no-longer-xml/m-p/5350277). The `py-premiere` package (PyPI, repo Pouf/py-premiere) parses .prproj, edits items such as sequence names, and claims byte-identical round-trip saving — [py-premiere](https://pypi.org/project/py-premiere/)

### Inferences
- Lowest-risk custom pipeline: generate FCP7 xmeml (or OTIO, then convert to `fcp_xml`) with cuts, B-roll on V2+, SFX on A3+ and sequence markers carrying citations, then import into Premiere. Labels in xmeml are carried by `<labels><label2>` elements in the FCP7 spec. Premiere's mapping of those to its label colors was not confirmed in sources, so test it empirically.
- Direct .prproj editing is possible but fragile, because the format is undocumented. Use it only for metadata tweaks.

### Gaps
- No source confirmed how Premiere maps xmeml `label2` values to its color labels, or whether marker colors survive FCP7 XML import (OTIO import is documented to carry marker color).
- py-premiere's maturity and supported Premiere versions are unverified.

## Q3. After Effects, GeoLayers and Blender automation

### Takeaway
After Effects is still on ExtendScript/CEP: per Adobe's Sept 2026 post it has no UXP yet ("will follow"). Several AE MCP servers exist. Blender has multiple mature MCP servers that drive bpy over local sockets. I found nothing on GeoLayers 3 scripting.

### Cited Findings
- After Effects "will follow" Premiere onto UXP. The Dec 2029 CEP cutoff applies generally — [CC Developer forum](https://forums.creativeclouddeveloper.com/t/cep-to-uxp-what-developers-need-to-know/12189)
- AE MCP servers: Dakkshin/after-effects-mcp (ExtendScript; compositions, text, shapes, solids, properties; AE 2022+, bridge panel), TheLlamainator fork (adds presets, markers, audio levels, waveform analysis, effect discovery), kumoproductions/mcp-aftereffects (no in-AE plugin or panel needed, npm, ~44 stars), sunqirui1987/ae-mcp (Go, runs a .jsx in AE) — [Dakkshin](https://awesome.ecosyste.ms/projects/github.com%2Fdakkshin%2Fafter-effects-mcp); [TheLlamainator](https://mcpservers.org/servers/thellamainator/after-effects-mcp); [kumoproductions](https://github.com/kumoproductions/mcp-aftereffects); [sunqirui1987](https://awesome.ecosyste.ms/projects/github.com%2Fsunqirui1987%2Fae-mcp)
- Blender MCP servers: kleer001/blender-mcp (175 tools, integration-tested on Blender 4.2.5 LTS, TCP socket to a bpy addon). emeryporter/blender-mcp (Blender 4.0+ addon, localhost:9876, code execution). An "official Blender MCP server" skill listing (Blender 5.1+, arbitrary bpy execution, API doc lookup). Anthropic's Apr 2026 creative connectors included Blender — [kleer001 (Glama)](https://glama.ai/mcp/servers/kleer001/blender-mcp); [emeryporter](https://github.com/emeryporter/blender-mcp); [implexa listing](https://implexa.ai/s/clawhub/blender-skill); [AlternativeTo](https://alternativeto.net/news/2026/4/anthropic-launches-claude-connectors-for-adobe-blender-ableton-and-more/)

### Inferences
- For documentary-style animated maps and graphics, the scriptable options are AE via ExtendScript/MCP (render to clips, then import into Premiere) and Blender via bpy (headless rendering is easy). Both fit an "agent renders assets, then XML/MCP places them" design.

### Gaps
- GeoLayers 3 scripting API: no sources found. Whether it exposes ExtendScript-callable functions is unknown.

## Q4. All-in-one and multi-step AI video editing agents (2025-2026)

### Takeaway
No single tool covers derush, cited B-roll sourcing from a script, and SFX placement together for Premiere. Eddie AI is the closest for (1) plus partial (2). It builds the A-roll rough cut, then places your own B-roll over it, and outputs XML or a Premiere extension, but it does not source external B-roll with citations. Descript Underlord and Gling cover derush. Open-source agents (video-use, Director, VideoAgent) are ffmpeg/hosted pipelines that output MP4, not NLE timelines. Script-to-video tools (InVideo, Morphic) generate or stock-fill B-roll and sound, but are faceless-video generators without citations.

### Cited Findings
- **Eddie AI**: logs B-roll, picks sub-clips and places them over the A-roll spine automatically, using only your real footage (RedShark, Apr 26, 2026, NAB 2026). It exports XML/FCPXML for Premiere, Resolve and FCP, and has a Premiere extension. Rough-cut export includes chapter names as ranged markers. One review cites limits of 5 A-roll and 25 B-roll files up to 10 minutes each — [RedShark News](https://www.redsharknews.com/eddie-ai-nab-2026-ai-video-editing-rough-cut); [Eddie rough cuts](https://www.heyeddie.ai/features/roughcuts); [No Film School](https://nofilmschool.com/eddie-ai-new-features); [Eddie documentaries](https://www.heyeddie.ai/types/documentaries)
- **Descript Underlord** (labelled **beta** in Descript help): an agentic co-editor that executes multi-step instructions. Newer media understanding lets it "see" video, not just the transcript. Usage is metered, charging for both the agent and the tool — [Descript help](https://help.descript.com/hc/en-us/articles/36803785502221-Underlord-beta-Your-AI-co-editor-in-Descript); [Descript blog](https://www.descript.com/blog/article/underlord-ai-can-watch-videos); [Descript agent](https://www.descript.com/agent)
- A critique: Underlord and Eddie are "agentic over a transcript". They reorganize what is said, not what the camera holds, and cinematic intent still needs a human as of May 2026 — [Tella: Best agentic video editors 2026](https://www.tella.com/blog/best-agentic-video-editors); see also [a16z: It's time for agentic video editing](https://a16z.news/p/its-time-for-agentic-video-editing)
- **Gling**: bad-take, silence and filler removal, captions/SRT, auto framing, multicam and "AI B-roll", with XML export to Premiere, FCP and Resolve. Pricing is $10, $20 and $50 per month billed annually — [Gling](https://www.gling.ai/aini)
- **video-use** (browser-use; MIT; ~30.3k stars): a Claude Code / Codex skill. "Drop raw footage in a folder, chat with Claude Code, get final.mp4." It cuts fillers and dead space, burns captions, grades, adds 30 ms audio fades, generates animation overlays (Remotion, Manim, HyperFrames, PIL) via parallel sub-agents, and self-evaluates cut boundaries with up to 3 re-renders. It uses ElevenLabs Scribe for transcripts and ffmpeg. MP4 output only, with no Premiere XML export and no B-roll or SFX stage mentioned — [GitHub](https://github.com/gregpr07/video-use)
- **Director by VideoDB**: a Python framework for video agents (search, edit, compile, generate) with a chat UI and multi-agent coordination, built on the hosted VideoDB API. VideoDB also publishes agent skills (video-db/skills) — [GitHub](https://github.com/video-db/Director)
- **HKUDS VideoAgent**: breaks natural-language instructions into sub-intents mapped to a graph of tool-call nodes, run with a self-evaluating loop. The license is unclear (MIT according to one listing) — [SourcePulse](https://www.sourcepulse.org/projects/18043151); [wiki](https://github.com/dennislwm/playradar/wiki/VideoAgent)
- **Script-to-video generators**: InVideo AI converts scripts into documentary-style videos with stock footage and AI voiceover. Morphic storyboards a script, then generates scenes, B-roll and narration and "lays in sound" — [InVideo](https://info.invideo.io/how-can-i-make-faceless-film-analysis-videos); [Morphic](https://morphic.com/resources/tools/ai-documentary-video-maker)
- **Firefly AI Assistant** is described as "the most credible bet", agentic across Premiere, After Effects and Firefly (public beta Apr 2026), in a May 2026 review — [Tella](https://www.tella.com/blog/best-agentic-video-editors)

### Inferences
- No surveyed tool sources external B-roll with citation tracking, and none does SFX placement synced to edit events at NLE level. These are the gaps a custom pipeline would fill.
- A practical hybrid: use Gling or Eddie (or a video-use-style transcript cutter) for the derush, export XML, then post-process the XML or drive Premiere via MCP to add B-roll and SFX tracks plus citation markers.

### Gaps
- Not researched due to budget: Cutback Selects, Opus Agent, CapCut agent features, and Adobe Firefly's browser video editor. No data was gathered on these.

## Q5. Creators and blog posts that automate a documentary or YouTube workflow with AI

### Takeaway
The most relevant documented case is the arXiv paper "Sima 1.0" (Apr 2026). It is a multi-agent Claude Code setup for producing 1-2 hour documentaries: caption polishing, asset collection from URLs in the script, and parallel "senior" editing agents in DaVinci Resolve. Practitioner blogs consistently say Claude should decide cuts while ffmpeg or the NLE executes them. I found no posts from Lemmino- or Fern-style channels describing such automation.

### Cited Findings
- **Sima 1.0** (Zhao Song, arXiv 2604.07721, Apr 9, 2026; experience Oct 2025-Mar 2026). The human selects the topic, writes the script, records the A-roll, and annotates the script with image/video insertion cues and source URLs. A junior agent polishes captions and removes long pauses and redundant takes. An asset agent downloads assets, transcodes them to H.264/AAC and checks integrity. Senior agents edit in parallel splits: they overlay B-roll, time-remap, place images, choose fullscreen or PiP, and source extra public images to fill gaps. Output is made in DaVinci Resolve, with no Premiere XML. Credits come from source-URL comments in the script. No SFX stage and no code released. Uses Claude Code and the CC Switch routing tool — [arXiv](https://arxiv.org/html/2604.07721v1)
- Mejba Ahmed walkthrough: Claude Code orchestrates a talking-head pipeline (ffmpeg 16 kHz mono WAV extraction, Descript, music via ffmpeg `amix`). He found audio-level-only automation put cuts on consonants, and keeps taste and pacing human — [mejba.me](https://www.mejba.me/blog/claude-code-video-editing-workflow)
- Motionbox (Aug 2026): Claude is good at deciding what belongs in a cut but "not good at cutting". Claude Code + ffmpeg is the most flexible route but easy to point at the wrong file, so work on copies — [Motionbox](https://motionbox.io/blog/connect-claude-to-video-editing)
- An n8n workflow pattern: Claude writes the script, then sends it to InVideo (B-roll) and HeyGen (avatars) via API — [dailyaiworld](https://dailyaiworld.com/workflow/automated-youtube-production-agent). An open-source shorts pipeline uses Claude, Gemini Imagen and ElevenLabs — [dev.to](https://dev.to/tsensei/i-open-sourced-an-ai-pipeline-that-turns-any-topic-into-a-youtube-short-e77)
- A sourcing caveat: generated visuals "are not evidence", so factual documentary claims need sourced material — [Dreamina guide](https://dreamina.capcut.com/ai-video/best-ai-video-generators-for-youtube-creators)

### Inferences
- Sima's design (the human annotates insertion cues and URLs in the script, agents fetch and place) is the closest public blueprint for stage (2) with citations. Carrying source URLs into Premiere markers would extend it to a Premiere workflow.

### Gaps
- No public write-ups found from established essay or documentary channels (Lemmino, Fern, etc.) on AI automation of their editing.
- Automated SFX placement (whooshes on cuts, hits on graphics) is almost absent from the sources. No tool or post documents it at NLE level.
