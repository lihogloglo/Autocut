# SFX on visual events: whooshes, pops and typing placed from what happens on screen

Research date: 2026-11-03. This continues `sfx_automation.md` (2026-11-01) and does not repeat it. **Verified** means I opened the repo source, the official doc or the licence. **Snippet** means search-result text only. **Inference** means my own reasoning.

## 1. Existing projects that detect visual events and place SFX

| Project | What it detects, and how (verified in source) | Placement and output | Licence, activity | Windows | Quality signal |
|---|---|---|---|---|---|
| **[SpicesFire/SoundFx](https://github.com/SpicesFire/SoundFx)** (new find) | Cuts: PySceneDetect `AdaptiveDetector`. Motion: OpenCV Farneback optical flow on 160 px grey frames at 20 fps. Mean magnitude above a median+4·MAD threshold counts as fast motion or a whip pan (the mean flow vector separates the two). Flow divergence gives zoom in/out, a brightness jump gives a flash, near-zero difference gives a freeze. Cuts are classified (flash, blur, zoom, stutter, hard). An optional vision LLM adds foley and "text pops". | An editable JSON cue sheet (`t`, role or query, `gain_db`, `align: sync/start/end`, trim, fades). The library is indexed by peak, attack and **sync point**, and the transient lands on the frame. Music is ducked, the mix is normalised to -14 LUFS and muxed with `-c:v copy`. **No Premiere output.** | MIT. 1 star. Commits only on 2026-09-02 and 09-03. Docs are in Turkish. | Yes (`.bat`, winget FFmpeg) | Real, sensible code. Rules were tuned on music-driven Instagram car edits. Text appearing and typing are not detected without the LLM. |
| **[RakibAhmed642/OpenCut-Enhanced](https://github.com/RakibAhmed642/OpenCut-Enhanced)** | The README claims "cuts, text reveals, camera moves". The code (`server/sound_designer.py`) only runs FFmpeg `select=gt(scene,0.35)` for cuts and `silencedetect` for pauses (which get impacts). | Peak-aligned (`start = cut - peak_ms`). The whooshes are FFmpeg-synthesised pink noise. Output is a rendered `_sfx_stem.wav` on A2. | MIT. 1 star. Created 2026-10-20, last push 10-21. | Windows only (CEP) | The README overclaims. Cuts only. |
| **[SysAdminDoc/OpenCut](https://github.com/SysAdminDoc/OpenCut)** (new) | `sound_design_ai.py` says it uses "frame differencing and optical flow". In the code, the "magnitude" is frame-timing irregularity **plus `random.uniform(5,25)`**, and the SFX category is picked at random. `foley_cue.py` uses the FFmpeg scene score. `transition_sfx.py` needs the transition list as input. | Mixes into a rendered file. | MIT. 65 stars. Last push 2026-09-26. Premiere CEP. | Yes | Wide but AI-generated breadth. Its motion detection is fake. Avoid. |
| **[AhsanAyaz/ossclip](https://github.com/AhsanAyaz/ossclip)** | Nothing visual for SFX. The LLM anchors each sound to a **transcript word** and optionally to a `sceneId` from the graphics plan it generated itself. | `pack.json` has a `whenToUse` sentence per sound. The code enforces a 1.5 s minimum gap and a budget of 2/4/8 per minute. Exports markers as Premiere XML. | Code MIT (GitHub shows NOASSERTION because of the Remotion terms). 57 stars. Last push 2026-09-29. | Yes | The cleanest "LLM plus deterministic gate" pattern. |
| **[Gahroot/cliporous](https://github.com/Gahroot/cliporous)** `scene-sfx.ts` (new) | No detection: its Remotion explainer scenes **emit cues** (tick, slide, thump, pop, flip, whoosh, rise). | A pure planner. Minimum gap 0.22 s, a priority order on collisions, thump at most once per 6 s and rise once per 10 s, file rotation per kind, per-kind dB relative to the voice. | MIT. 1 star. Push 2026-10-25. | Electron | Good guardrail code to copy. |
| **[Smaxhy/video-editing PR #21](https://github.com/Smaxhy/video-editing/pull/21)** | Beats (spectral flux) and its own scene list. A whoosh goes on non-cut transitions, a tick on text and lower thirds, a pop on emoji. | Sounds are FFmpeg-synthesised, placed 0.3 s early, at least 0.35 s apart, at volume 0.35 to 0.55. | **No licence**. 0 stars. Merged 2026-10-23. | Node | Events come from its own generator. |
| **[rameezimdad/Rameez-AI-Shorts-Editor](https://github.com/rameezimdad/Rameez-AI-Shorts-Editor)** | Nothing visual. The LLM plan lists `{at, kind}` across 13 kinds. | At least 4 s apart, `adelay`/`amix`, placeholder synthesised sounds. | MIT. 4 stars. Push 2026-10-28. | `run.bat` | Basic. |

GitHub searches found nothing else that is substantial. The searches were "auto sfx", "whoosh transitions", "auto foley" (these return silent-video foley ML projects), "premiere sound effects", "sfx keyframes", and code searches for whoosh together with scenedetect, optical flow and scene_score.

After Effects (snippet): AE has no keyframe event system. The community workarounds are expressions that time-remap an audio layer to the nearest keyframe, or iExpressions playing a sound on each marker ([Adobe community](https://community.adobe.com/questions-529/attaching-a-sound-to-a-keyframe-28596), [typing-sound thread](https://community.adobe.com/t5/after-effects-discussions/does-after-effects-have-an-expression-to-trigger-and-align-typewriter-effect-to-typing-sounds/m-p/12899485)). aescripts "MonkeySauce" is said to "automate triggering sound effects" (snippet, not opened). In Premiere, community answers say there is no native "SFX on every transition" ([Adobe community](https://community.adobe.com/questions-729/can-i-auto-add-a-sound-effect-between-all-clips-like-adding-a-video-transition-between-all-clips-1404779)).

Commercial products, for comparison. All are paid.
- **PremiereCopilot Auto SFX**: reads "what is said, and the picture around each cut". Triggers are "speech, cuts, or both". Sounds are AI-generated, and you pay credits per generated sound ([page](https://www.premierecopilot.com/auto-sfx), verified; no prices shown).
- **OpusClip Auto SFX**: a web tool on the Pro and Business plans. It "detects transitions… places sounds where the cuts happen" ([page](https://www.opus.pro/tools/transition-sound-effects)).
- Epidemic Studio and FireCut are covered in the earlier note.

## 2. Detection techniques for motion design and screen content

Ranked by reliability and cost for Autocut. This is inference, backed by the tools above.

1. **Autocut's own metadata (exact and free).** Autocut already knows when each illustration starts on the edit, and where its derush cuts and S-markers are. In every project above that works well (ossclip, cliporous, Smaxhy), the cues come from the generator and not from pixels. An illustration start can get a pop or whoosh, a chapter change a riser plus impact, and a jump cut nothing.
2. **The Premiere sequence XML.** In FCP7 xmeml, `transitionitem` marks slides and pushes, a `clipitem` start on V2+ marks an element appearing, and Motion (scale/position) and Opacity keyframes mark zoom punches, slide-ins and fade-ins. This is frame-exact and cheap, but blind to motion baked inside MOGRTs, AE renders, stock footage and screen recordings. That Premiere exports Motion and Opacity keyframes into xmeml is an inference; check it with one test export.
3. **Pixels, as a fallback on the rendered sequence or on individual clips.**
   - **Cuts:** PySceneDetect (BSD-3, 5.3k stars, active 2026-11-02). It ships Content, Adaptive, Threshold, Histogram and Hash detectors; ThresholdDetector is the one described as catching fades ([docs](https://www.scenedetect.com/docs/latest/api/detectors.html)). TransNetV2 (MIT, 1.1k stars, last push 2023) also handles gradual transitions. The FFmpeg `scene` score is the cheapest option.
   - **Whoosh candidates:** a spike in optical-flow magnitude. SoundFx shows a cheap recipe (Farneback at 160 px and 20 fps, MAD threshold, mean flow vector for pan direction, divergence for zoom). This fits slides and pushes in motion design well, because they are large uniform translations.
   - **Pops:** the frame difference is concentrated in a region that then stays static (new-object appearance). No ready tool was found.
   - **Typing:** OCR (PaddleOCR or EasyOCR, both Apache-2.0) at 5 to 10 fps, flagging regions whose character count grows steadily for 0.3 s or more. No existing tool was found. Inference: this costs the most of any option here, so run it only near V2+ text or graphics clips.
4. **Audio-visual sync research.**
   - "Visual Rhythm and Beat" (Davis & Agrawala, SIGGRAPH 2018) derives visual impacts from directional changes in motion. Its code, [visbeat](https://github.com/abedavis/visbeat), has an unclear licence and no push since 2021. It is the closest academic match to "align a sound peak to a motion peak".
   - [Synchformer](https://github.com/v-iashin/Synchformer) (MIT) estimates audio-visual offset. It could check placement afterwards, but is overkill.
   - The practical method is to store each SFX file's **sync point** (RMS peak or transient) and place `start = event - sync_point`, as SoundFx and OpenCut-Enhanced do.

## 3. Free SFX sources for monetized YouTube that a program can fetch

| Source | API | Licence for monetized YouTube | Notes |
|---|---|---|---|
| **Freesound** | Yes (verified). Token auth for search and previews. **OAuth2 for original files.** 60 req/min and 2,000/day; downloads 30/min and 500/day ([overview](https://freesound.org/docs/api/overview.html)). Has a `license` filter and **`similar_to` search in a `laion_clap` space** ([resources](https://freesound.org/docs/api/resources_apiv2.html)). | Licence is per sound. Filter to CC0 for no attribution (the exact value, likely `license:"Creative Commons 0"`, is inferred). | API terms: no full database copies, no scraping, one key per application, commercial use of the *API* negotiated with UPF ([ToS](https://freesound.org/help/tos_api/)). Inference: each user should bring their own key. |
| **Kenney** | No (zip downloads) | **CC0**. For example, Interface Sounds has 100 files ([page](https://kenney.nl/assets/interface-sounds)). | The only source here Autocut can **bundle** as a default starter pack. |
| **Sonniss GDC bundles** | No (large zips) | Commercial use and video allowed, **no attribution**. **AI training is prohibited**, and redistributing the sounds "as sound effects" (packs, SDKs) is prohibited ([licence](https://sonniss.com/gdc-bundle-license/)). | The user downloads them; Autocut indexes them locally. Do not bundle. |
| **Pixabay** | **No audio API**. The API covers images and videos only ([docs](https://pixabay.com/api/docs/)). | Commercial use, no attribution (FAQ, snippet). | Manual download only. |
| **Mixkit** | No public API (inference) | Free licence, commercial use, no attribution (via [llm-info](https://mixkit.co/llm-info/), snippet). No redistribution. | Manual download. |
| **Zapsplat** | No | Free tier **requires a credit** to "ZapSplat" (licence updated 2025-09-29, snippet). | Not attribution-free. |
| **BBC SFX** | No | RemArc licence: personal, educational and research use only. Commercial use needs a paid licence (snippet). | Excluded. |
| OpenGameArt and Wikimedia Commons | Commons has the MediaWiki API with per-file licence metadata. OpenGameArt has no official API (inference). | Mixed licences (CC0, CC-BY, GPL). | Low yield for UI and whoosh sounds. |

The only source that offers both a real API and attribution-free commercial use is Freesound filtered to CC0. The best route is local files: Kenney CC0 bundled, plus the user's own folder, plus the Sonniss bundles they download.

## 4. Local generation and local search on Windows with an NVIDIA GPU

- **Stable Audio 3.0 Small SFX** (released 2026-05-20, 0.6B parameters per its HF card). Under the Stability AI Community License it is free below $1M annual revenue, "you own outputs", and registration is required for commercial use ([licence](https://stability.ai/license), [announcement](https://stability.ai/news-updates/meet-stable-audio-3-the-model-family-built-for-artistic-experimentation-with-open-weight-models), [card](https://huggingface.co/stabilityai/stable-audio-3-small-sfx)). It is **gated** and also bound by the Gemma terms (T5Gemma conditioning). It supports inpainting and continuation, which helps for variations. It targets consumer hardware; no VRAM figure is published. Code is MIT (`stable-audio-3`, `stable-audio-tools`). Stable Audio Open Small (0.5B, 11 s, 44.1 kHz stereo) is under the same licence family.
- **Not commercial-OK** (HF licence tags, verified): AudioLDM2 (cc-by-nc-sa-4.0), Tango 2 (cc-by-nc-sa-4.0), TangoFlux (non-commercial research), AudioGen-medium (cc-by-nc-4.0), MMAudio weights (cc-by-nc-4.0; the code is MIT).
- **HunyuanVideo-Foley** uses the Tencent Hunyuan Community License, which **does not apply in the EU, UK or South Korea** and requires AI-generated content to be labelled ([licence](https://huggingface.co/tencent/HunyuanVideo-Foley/blob/main/LICENSE)). The repo's commit messages are French; if the user is in the EU, it is unlicensed for them.
- **CLAP search of a personal folder:**
  - LAION-CLAP: repo CC0-1.0, HF weights (`laion/clap-htsat-fused`, `larger_clap_general`) Apache-2.0.
  - MS-CLAP: code MIT, HF weights tagged MS-PL.
  - Both are fine for indexing a local folder. Freesound's own `laion_clap` similarity space means one query style works locally and online.

## 5. How editors actually do it: conventions and numbers

Reddit (r/editors, r/premiere) could not be reached; searches only returned mirror snapshots. The numbers below come from vendor guides and from constants in the code of the projects above.

- **Whoosh timing.**
  - Guides say the whoosh peak lands on the cut, or on the first frame of the new shot. Start it before the edit; a whoosh that starts after the cut feels late ([Morphic](https://morphic.com/resources/sounds/transition-sound-effects)).
  - SoundFx's rules say to start 100 to 250 ms before the cut, with length about equal to the move (0.3 to 0.8 s).
  - Its measurement of 4 reference edits: **the whoosh peak sits a median 177 ms before the event, and hits land +20 ms after it (IQR 4 to 41 ms)**.
  - Smaxhy places whooshes 0.3 s early; OpenCut-Enhanced uses a peak offset of 120 to 300 ms.
- **Sync tolerance.** ITU-R BT.1359 detectability is about 45 ms for audio early and 125 ms for audio late ([Wikipedia summary](https://en.wikipedia.org/wiki/Audio-to-video_synchronization)). So pops and clicks must sit within about 1 frame, while whooshes are anticipatory by design.
- **Levels.** Whooshes are put at -18 to -25 dB ([SFX Engine](https://sfxengine.com/blog/reels-audio-editing-tips), snippet), and SFX generally at -14 to -20 dB ([Filmstro](https://filmstro.com/?p=11364), snippet). Relative to the voice:
  - SoundFx: whoosh 6 to 12 dB below speech, pop or ding 3 to 6 dB below, typing -18 to -22 dB, ambience -26 to -32 dB.
  - cliporous: tick -26, slide -24, pop -24, whoosh -27, thump -20, rise -28 dB.
  - Music is ducked 3 to 6 dB under impacts ([Sonilo, 2026-07-17](https://sonilo.com/blog/guides/transition-effect-sound-video-edits)).
- **Density.**
  - Sonilo: do not put a whoosh on every cut, and "delete half of them on the second pass".
  - SoundFx: whooshes on 60% of transitions or fewer, about one SFX per 3 to 5 s in fast content, only on meaningful transitions in calm narration, and one or two big drops per video.
  - ossclip: 2, 4 or 8 per minute. cliporous: thump at most once per 6 s, rise once per 10 s.
- **Variation.** Rotate through 2 to 4 variants per kind (cliporous). Exclude the last 3 files used (SoundFx). Pick the sound by type: short whoosh for fast cuts, swell for fades, sweep plus a landing impact for scene changes (Sonilo).
- **Short UI sounds** are about 30 to 150 ms ([Violet Recording](https://violetrecording.com/how-to-design-ui-sounds/), snippet).

## 6. Placing the sounds in Premiere

- **FCP7 XML.**
  - Clip volume is the "Audio Levels" effect, whose `Level` parameter is **linear gain** (dB = 20·log10(Level)) ([Apple xmeml reference](https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/FinalCutPro_XML/Topics/Topics.html)).
  - Premiere clamps clip gain above +6 dB on import ([Larry Jordan](https://larryjordan.com/articles/fcp-7-move-projects-to-premiere-pro/)).
  - Keyframed levels and fades are a standard part of xmeml; OpenShot's FCP XML export writes volume keyframes ([OpenShot](https://en.openshot.org/files/user-guide/import_export.html)).
  - Inference: SFX clips on dedicated `<audio><track>`s will import reliably, the same way Autocut's existing XML does. Verify keyframe import with one test file.
- **UXP.**
  - `AudioClipTrackItem.getComponentChain()` returns an `AudioComponentChain`. `ComponentParam` has `createKeyframe`, `createAddKeyframeAction`, `createSetTimeVaryingAction` and `createSetValueAction` ([premierepro-types d.ts](https://github.com/adobe/premierepro-types)).
  - The chain exposes the "Volume" and "Channel Volume" components, but **clip Audio Gain is not exposed** ([Adobe community, Aug 2026](https://community.adobe.com/questions-729/control-audio-gain-with-uxp-plugin-1639453)).
  - Developers report that keyframes and values do not stick in 26.x ([forum](https://forums.creativeclouddeveloper.com/t/keyframes-and-componentparam-in-uxp-not-working/11697)).
  - Autocut's panel already uses `createOverwriteItemAction(pi, time, v, a)` (`premiere/index.js:248`), so placement works. Setting a static Volume level is plausible; keyframed fades are risky. Prefer trimmed, pre-faded files.

## Verdict

**Nothing does this well enough for this user.**
- The paid tools (PremiereCopilot, Epidemic Studio, OpusClip, FireCut) break the no-subscription rule.
- Among the open-source projects:
  - SoundFx is the only one with honest pixel detection (cuts, whip pans, zooms, flashes) and good sync-point placement. But it outputs a muxed MP4 rather than Premiere clips, has no pop or typing detection, is tuned for music-driven car edits, and is two days of work with 1 star.
  - OpenCut-Enhanced only detects cuts.
  - SysAdminDoc/OpenCut's motion detection is random numbers.
  - ossclip, cliporous and Smaxhy do not detect anything. They know their events because they generated the graphics, and that is exactly Autocut's situation for its own illustrations.

**The gap:**
1. Extract events from the **Premiere sequence** (Autocut's illustration placements, XML transitions, V2+ clip starts, Motion and Opacity keyframes). Fall back to pixels only for motion baked into clips.
2. Map events to kinds with editorial rules (density, variation, priority).
3. Resolve each cue against a **swappable source**: the user's folder via CLAP, bundled Kenney CC0, Freesound CC0, or optionally Stable Audio 3 Small SFX.
4. Place sync-point-aligned, *separate, editable* clips on dedicated audio tracks, through XML or the UXP panel, with a static level per clip.

**Reuse:**
- PySceneDetect `AdaptiveDetector` (BSD-3).
- SoundFx's Farneback, divergence and MAD motion detector, its library index with sync point, and its cue-sheet schema (MIT).
- cliporous `planSceneSfx` guardrails and per-kind dB table (MIT).
- ossclip's `whenToUse` pack metadata and per-minute budget (MIT).
- Kenney CC0 as the bundled default pack.
- The Freesound API, CC0-filtered with `laion_clap` similarity, using the user's own key.
- LAION-CLAP (CC0 code, Apache-2.0 weights) for local search.
- Stable Audio 3 Small SFX as the generation option (Community License, gated).

**Avoid:** the Hunyuan-Foley licence in the EU, the NC-licensed models (AudioLDM2, Tango, MMAudio weights, AudioGen), bundling Sonniss sounds, and BBC sounds.
