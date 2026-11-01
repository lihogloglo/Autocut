# Commercial and built-in tools for automated derush / rough cut of talking-head footage (Premiere Pro focus)

Research date: 2026-11-01. All prices were checked in late October / early November 2026 unless noted. Vendor pricing pages change often, and third-party listings disagree.

## Q1. What does Premiere Pro do natively as of 2026 (Text-Based Editing, pauses, filler words, Media Intelligence, generative features)?

### Takeaway
Premiere has transcript-driven editing (Text-Based Editing since 2023, plus filler-word search and removal), on-device Media Intelligence search that can find "similar shots / alternate takes" (25.6 beta, then 26.x), and in 26.5 (Sept 2026) a transcript "Paper Edit" assembly tool and a new Voice Activity Detection transcription model. None of these detects repeated takes of the same sentence and keeps the best one automatically. That still needs a third-party plugin or a manual pass.

### Cited Findings
- Text-Based Editing launched in 2023. It transcribes source clips automatically, lets you build a rough cut by copying transcript text into the timeline, and removes clips when you delete text. You can search "um", "uh", "you know" across a sequence and Premiere lists every instance — [Editors Keys](https://www.editorskeys.com/blogs/news/adobe-brings-text-based-editing-yes-to-adobe-premiere); [TechRadar](https://www.techradar.com/news/adobe-premiere-pro-update-lets-you-edit-videos-like-its-a-word-doc)
- A 2026 plugin guide lists Text-Based Editing, transcription, filler-word detection, media intelligence, masking and generative features among Adobe's documented native features — [autoeditai.net](https://www.autoeditai.net/blog/best-ai-plugins-premiere-pro)
- Premiere 26.0 (Jan 2026): Media Intelligence lets you search footage by describing sounds. A community summary says it can also locate similar shots or alternate takes — [Kyler Holland 26.0](https://www.kylerholland.com/blog/premiere-pro-january-2026-whats-new); [Adobe community](https://community.adobe.com/product-updates/1546089)
- Release notes for 26.2.2 (May 2026) describe AI media intelligence that finds sound effects and alternate takes, and censors words with one click — [Adobe release notes](https://helpx.adobe.com/premiere/desktop/whats-new/release-notes.html) (seen in a search snippet; direct fetch returned 403)
- "Search Similar Frames" (right-click a visual result in the Search panel) and audio search first appeared in Premiere Beta v25.6. Analysis runs locally with no internet needed, and it can be turned off in Preferences > Media Analysis & Transcription — [Adobe community: Search panel updates](https://community.adobe.com/announcements-732/search-panel-updates-audio-search-and-search-similar-frames-311916); [Adobe help: Media intelligence and Search panel](https://helpx.adobe.com/premiere-pro/using/media-intelligence-and-search-panel.html); [ProVideo Coalition](https://www.provideocoalition.com/tool-tip-tuesday-for-adobe-premiere-pro-quick-finding-of-similar-shots-using-media-intelligence/)
- Adobe gives this as an example of where the feature is heading: with multiple takes of the same scene, AI could flag which ones have camera shake or something blocking the frame. This describes visual quality, not spoken repeats — [Adobe community 25.6 announcement](https://community.adobe.com/announcements-727/premiere-pro-v25-6-firefly-integration-smarter-search-and-more-1546583)
- Premiere 26.2 (Apr 16, 2026) added source-monitor waveforms, a Sequence Index panel, marker search by name/comment/color, and Color Mode beta. It had no new transcript or take features — [Adobe community 26.2](https://community.adobe.com/announcements-727/welcome-to-premiere-26-2-1557825)
- Premiere 26.5 (Sept 2026):
  - **Paper Edit:** in the Text panel, highlight lines across an interview, preview selects and total duration, then generate a new sequence in edit order.
  - **Generative Media Tool:** Generate Video into gaps using Firefly or partner models (Veo, Kling, Runway, Luma), and Generate Sound Effects.
  - Generative Extend now works on more formats. Object Masking was improved. A "Premiere AI Assistant" beta is mentioned.
  - [Kyler Holland 26.5](https://www.kylerholland.com/blog/premiere-pro-september-2026-whats-new/); [Adobe community 26.5](https://community.adobe.com/announcements-727/what-s-new-in-adobe-premiere-26-5-september-2026-1641187)
- 26.5 also adds a new Voice Activity Detection model for speech-to-text, and fixes Media Intelligence sidecar cache files (.prmi) not being reused — [Adobe release notes](https://helpx.adobe.com/premiere/desktop/whats-new/release-notes.html) (search snippet)
- AutoCut (a competitor, so biased) says Premiere natively "doesn't detect repeated takes"; you compare versions manually with markers, razor and waveforms — [AutoCut blog, Apr 15 2026](https://www.autocut.com/en/blogs/best-plugin-remove-repeat/)

### Inferences
- Native Premiere covers silence and filler removal through the transcript, and Paper Edit lets you pick takes by highlighting text. Choosing which take to keep is still a human decision. Media Intelligence's "alternate takes" is visual or semantic search, not automatic dedup with a best-take pick.
- The .prmi sidecar files and the on-device analysis suggest Premiere stores Media Intelligence data per media file. Whether a pipeline can read that data is unknown.

### Gaps
- I could not fetch Adobe's helpx "What's new" or release-notes pages (HTTP 403), so exact 26.x feature wording comes from snippets and third-party recaps.
- I found no official documentation of a one-click "delete all pauses" in 2026 builds. Older Text-Based Editing exposes pauses as "[...]" in the transcript with bulk deletion, but I did not re-verify this for 26.x.
- What the "Premiere AI Assistant" beta can do (for example, whether it can do a rough cut) was not found.

## Q2. Third-party tools: what each automates, pricing, integration type, sentiment

### Takeaway
Two Premiere-panel plugins handle repeated takes inside Premiere:
- **AutoCut Repeat:** AI Plan, $14.9/mo billed yearly.
- **FireCut "Remove repetition":** Pro plan, $14/mo billed yearly or $23 monthly.

Gling (standalone desktop app, then XML to Premiere) and Descript ("Remove Retakes", then XML/AAF) are the main external round-trip options. Cutback/Premiere Assistant (Auto Rough Cut, Oct 2026) and the Selects app, Eddie AI (MCP-driven, credit pricing) and DaVinci Resolve IntelliScript (best take on the timeline, alternates on extra tracks) cover script- or selects-based rough cuts. TimeBolt is a standalone silence cutter that exports XML.

### Comparison table (Premiere-relevant)

| Tool | Integration with Premiere | Silences | Filler words | Repeated / bad takes | Best/last take logic | Price (Nov 2026) |
|---|---|---|---|---|---|---|
| Premiere native (26.5) | Built in | Via transcript | Yes (search and delete) | No auto detection; Paper Edit is manual selection | Manual | Creative Cloud subscription |
| AutoCut (autocut.com, French) | Panel inside Premiere 2023–2026 and Resolve 18.6–21 | AutoCut Silences (Basic) | Yes (Repeat FAQ) | AutoCut Repeat (AI Plan); 80+ languages; optional reference script; review before cut | Vendor says the "best version is automatically selected"; criteria not documented; user reviews and picks | Basic $6.6/mo ($79/yr); AI Plan $14.9/mo ($178.8/yr); Enterprise $19.9/license/mo; 14-day trial |
| FireCut | Premiere Pro extension (2022+); also Resolve plugin | Unlimited on all plans | Pro and up | "Remove repetition" (Pro and up); experimental outside English | Lists all takes per repeated phrase; user ticks one and the others are deleted; docs say the last take is "usually best"; tunable phrase size, tolerance, search radius | PPro Starter $7/yr-mo ($13 monthly); Pro $14 ($23); Max $27 ($41); Team $34/user |
| Gling | Standalone desktop app (Mac/Win) with XML export to Premiere/FCP/Resolve (paid only) | Yes | Yes | "Remove bad takes" (YouTuber-focused) | Not documented on pricing page | Free 1h/mo, watermark, no XML; Plus $10/mo yearly ($20 monthly, 10h); Pro $20 ($40, 30h); Elite $50 ($100, 100h) |
| Descript | Standalone app with XML/AAF export to Premiere | Yes | Yes | Underlord "Remove Retakes" | Says it picks "the best, cleanest take" | Conflicting: ~$16–24 to $65/mo |
| Cutback / Premiere Assistant | Premiere plugin; Selects is a separate app pre-NLE | Yes | — | Auto Rough Cut (v2.35.0, Oct 17 2026): "select the best takes", cut to script, find highlights | Not documented | Selects Starter $16/mo yearly ($20 monthly); 7-day trial; Premiere Assistant priced separately |
| Eddie AI | Cloud/desktop app with NLE export (Premiere/Resolve/FCP); MCP server | — | — | Rough cuts from interviews, soundbite selection, multicam | Not documented | Pay-as-you-go since Aug 2026: $10/1k credits … $350/50k; ~500 credits per hour of footage imported; 1,000 free credits |
| TimeBolt | Standalone app with XML export to Premiere | Yes (precision focus) | — | Not core | — | Not verified |
| DaVinci Resolve 20 IntelliScript (comparison only) | Resolve only | — | — | Matches transcript to script | Best take on the timeline, alternates on extra tracks | Resolve free; Studio $295 one-time |
| Jumper | Premiere search panel, runs on-device | — | — | Search only (find shots or spoken words) | — | Conflicting ($99 one-time vs tiered) |

### Cited Findings
- **AutoCut pricing (USD, yearly billing):** Basic $6.6/mo ($79/yr, silences only); AI Plan $14.9/mo ($178.8/yr) including Captions, Repeat, Zoom, Podcast, Chapters, B-roll; Enterprise $19.9/mo per license. The page gives conflicting yearly savings ("up to 33%" vs "up to 25%"). No API mentioned — [AutoCut pricing](https://www.autocut.com/pricing)
- A GetApp listing (Sept 2026) shows monthly Basic 9.9 and AI Plan 19.8, currency unstated — [GetApp](https://www.getapp.com/all-software/a/autocut/)
- **AutoCut Repeat workflow:** set in/out, choose the language, optionally add a reference script, transcribe, review the detected takes, then cut. It supports 80+ languages and can remove filler words. Color labels and restart handling are not mentioned — [AutoCut Repeat](https://www.autocut.com/autocutrepeat)
- AutoCut claims Repeat works even when the speaker slightly rephrases, and that "the best version is automatically selected" — [AutoCut blog](https://www.autocut.com/en/blogs/best-plugin-remove-repeat/)
- **AutoCut compatibility:** Premiere Pro 2023–2026 and DaVinci Resolve 18.6/19/20/21, on Mac and Windows — [AutoCut](https://www.autocut.com)
- **FireCut pricing and plan features:** Premiere Starter has silence removal only. Pro (25 h/mo) and Max (100 h/mo) add repetition, filler, chapters and zooms. Resolve plans and a browser-based FireCut Shorts product also exist. Lifetime licenses are available on request — [FireCut pricing](https://firecut.ai/pricing)
- **FireCut repetition removal:** it lists every take of a repeated phrase, and you preview one (which marks it on the timeline) and tick it to keep it while the others are deleted. The docs note "the last take is usually the best". Advanced mode exposes minimum phrase size, tolerance, search radius and last-occurrence end-point detection, and you can scope the run with I/O. Non-English support is experimental. Markers or color labels are not mentioned, and FireCut can occasionally clip word starts or ends — [FireCut docs: remove repetition](https://learn.firecut.ai/features/remove-repetition.md); [FireCut repetition feature](https://firecut.ai/features/repetition)
- **Gling pricing:** Free / Plus / Pro / Elite as in the table. Unused hours don't roll over. XML export to Premiere is paid only. Multicam and separate-mic footage is supported only for Resolve/FCP export; for Premiere you must sync before upload. The app is desktop only and has no plugin — [Gling pricing](https://gling.ai/pricing)
- Gling has no public developer API (third-party claim) — [techjockey](https://www.techjockey.com/detail/gling)
- **Descript:** "Remove Retakes" is an Underlord quick tool that "identifies the retakes and decides the best, cleanest take". XML/AAF export goes to Premiere/Resolve. Prices conflict across reviews ($16, $24, $24–65/mo) — [stigstack review](https://stigstack.pages.dev/reviews/descript-review); [shade.inc](https://shade.inc/blog/descript-for-post-production); [aiproductivity.ai](https://aiproductivity.ai/tools/descript/)
- **Cutback:** update 2.35.0 (Oct 17, 2026) added Auto Rough Cut, which can "find highlights, cut video based on script, select the best takes" with a preview before finalizing, and changed pricing — [Cutback blog 2.35.0](https://cutback.video/blog/2-35-0-auto-rough-cut-open-mode-separation-and-pricing-updates)
- Selects Starter is $16/mo yearly or $20 monthly, with a 7-day trial. Selects is bought separately from Premiere Assistant. Selects debuted at NAB 2026 — [Cutback llms.txt](https://cutback.video/llms.txt); [Cutback Selects intro](https://cutback.video/blog/cutback-selects-ai-rough-cut-tool-for-video-editors-using-davinci-premiere-pro-final-cut)
- **Eddie AI (CineD, Aug 28 2026):**
  - Subscriptions were replaced with credit packs: $10 = 1,000; $45 = 5,000; $120 = 15,000; $350 = 50,000.
  - Import costs about 500 credits per hour of footage, billed in 15-minute blocks. Credits never expire.
  - Eddie runs as an MCP server with about 100 tools (transcripts, soundbite selection, assembly, b-roll, captions, multicam, NLE export) that Claude or ChatGPT can drive.
  - [CineD](https://www.cined.com/eddie-ai-overhauled-pay-as-you-go-pricing-editing-from-claude-and-chatgpt-and-an-iphone-app/)
- Eddie integrates with Premiere, Resolve and FCP — [heyeddie llm.txt](https://www.heyeddie.ai/llm.txt). One G2 user reports a timeline-length cap and an XML export bug — [G2](https://www.g2.com/products/eddie-eddie/reviews)
- **TimeBolt:** a standalone app, not a plugin, that exports XML to NLEs. Seen as the "precision + control" choice for silences — [thegtmdirectory](https://thegtmdirectory.com/tools/timebolt); [Parse summary](https://www.parse.gl/prompts/p/we-use-a-specific-video-editor-who-offers-a-plugin-for-removing-silence-automatically--da889fb2-1130-4123-8cac-a7f761862dc8)
- **DaVinci Resolve 20 IntelliScript:** matches transcribed audio to a script, puts the best takes on the timeline and alternates on additional tracks for review. Resolve Studio is $295 — [Engadget](https://www.engadget.com/apps/davinci-resolve-20s-latest-ai-feature-can-create-an-entire-timeline-based-on-a-script-120009351.html)
- **Jumper:** an on-device AI search panel in Premiere for visuals and spoken words. Pricing listings conflict — [ProVideo Coalition review](https://www.provideocoalition.com/review-ai-driven-video-search-with-jumper/)
- **Speed benchmark (by Cutback, so biased):** Premiere Assistant and FireCut finished silence removal in under 30 s. AutoCut and AutoPod were slower; AutoCut took 15 minutes on a multitrack test — [Cutback benchmark](https://cutback.video/blog/the-best-auto-silence-removal-plugin-for-premiere-pro)

### Sentiment
- A Toksta aggregation of Reddit reviews says FireCut delivers "real efficiency, but expect a learning curve and a few rough edges" — [Toksta FireCut](https://www.toksta.com/products/firecut)
- A 2026 comparison says AutoCut has a cleaner creator workflow, FireCut has the broadest automation toolset, and "most creators would be happy with either". AutoCut Repeat is "an automated first pass rather than a creative cut" — [autoeditai.net comparison](https://www.autoeditai.net/blog/autoedit-vs-autocut-vs-firecut-vs-autopod); [autoeditai best auto-cut plugin](https://autoeditai.net/blog/best-auto-cut-plugin-premiere-pro)
- Most comparison content is vendor- or affiliate-authored (AutoCut, FireCut, Cutback and autoeditai blogs all rank themselves first).

### Inferences
- For "multiple takes of the same sentence → keep the last one" inside Premiere, FireCut's repetition tool fits most closely: it groups takes per phrase, the docs recommend the last take, and it exposes tunable parameters. AutoCut Repeat is similar, with an optional reference script and 80+ languages, which matters for French content. Both still need human review.
- Gling, Descript and Eddie require leaving Premiere and round-tripping through XML. They are better suited as a pre-pass than for working on an existing Premiere sequence.

### Gaps
- No Reddit threads were retrieved directly; sentiment is second-hand.
- I did not verify current pricing for TimeBolt, Recut, Autopod, Quickture, Simon Says, Spuce, Kapwing or CapCut (no calls left in budget). From prior knowledge only, unverified:
  - Recut and TimeBolt are standalone silence cutters with XML export.
  - Autopod is a Premiere multicam/podcast plugin.
  - Quickture and Simon Says are AI transcript/rough-cut services with Premiere panels.
- Whether AutoCut, FireCut and Cutback are UXP or CEP panels is not stated on the pages fetched.
- How Gling detects bad takes, and which take it keeps, is not documented on the pages fetched.

## Q3. Which tools handle "multiple takes of the same sentence → keep best/last" and color-label or group alternates?

### Takeaway
The tools that detect same-sentence repeats are AutoCut Repeat, FireCut Remove Repetition, Gling, Descript Remove Retakes and Cutback Auto Rough Cut. None of the fetched sources documents color-labeling alternate takes in Premiere: every Premiere plugin deletes the rejected takes. The only documented "keep alternates" behavior is DaVinci Resolve IntelliScript, which puts alternates on extra tracks.

### Cited Findings
- FireCut groups takes per repeated phrase and deletes the unselected ones, and notes the last take is usually best. Markers or labels are not mentioned — [FireCut docs](https://learn.firecut.ai/features/remove-repetition.md)
- AutoCut Repeat lets you review the detected takes before cutting; the best one is auto-selected. Color labels are not mentioned — [AutoCut Repeat](https://www.autocut.com/autocutrepeat); [AutoCut blog](https://www.autocut.com/en/blogs/best-plugin-remove-repeat/)
- IntelliScript puts the best take on the timeline and alternates on additional tracks — [Engadget](https://www.engadget.com/apps/davinci-resolve-20s-latest-ai-feature-can-create-an-entire-timeline-based-on-a-script-120009351.html)
- Premiere 26.2 added marker search by color, which helps review if a custom tool applies colored markers — [Adobe community 26.2](https://community.adobe.com/announcements-727/welcome-to-premiere-26-2-1557825)

### Inferences
- A custom pipeline could fill a gap here. Instead of deleting, it would group alternates and color-label them (or move them to a separate track, as IntelliScript does) and keep the last take. No Premiere tool in this survey documents that.
- None of the sources explicitly documents handling mid-sentence restarts ("I went to the — I went to the store"). FireCut's minimum-phrase-size and last-occurrence end-point settings suggest it can catch partial-phrase repeats.

### Gaps
- Not verified whether AutoCut Repeat has a "disable instead of delete" or label option; the help center was not fetched.

## Q4. Do any offer an API or scripting for a larger pipeline?

### Takeaway
Only Eddie AI exposes a documented programmatic interface: an MCP server with about 100 tools. AutoCut, FireCut, Gling and Cutback document no public API. The practical integration path for the others is XML round-trip (Gling, Descript, TimeBolt) or the interactive Premiere panel.

### Cited Findings
- Eddie AI exposes about 100 MCP tools, including NLE export, that Claude or ChatGPT can drive — [CineD](https://www.cined.com/eddie-ai-overhauled-pay-as-you-go-pricing-editing-from-claude-and-chatgpt-and-an-iphone-app/)
- The AutoCut pricing page doesn't mention an API — [AutoCut pricing](https://www.autocut.com/pricing)
- Gling has no public developer API (third-party) — [techjockey](https://www.techjockey.com/detail/gling)
- Gling, Descript and TimeBolt export XML for Premiere — [Gling pricing](https://gling.ai/pricing); [shade.inc](https://shade.inc/blog/descript-for-post-production); [thegtmdirectory](https://thegtmdirectory.com/tools/timebolt)

### Inferences
- In a custom pipeline, the most composable approach is to generate a Premiere-importable XML (FCP7 XML / xmeml) yourself, or to drive Premiere via UXP scripting. The commercial plugins are GUI-driven and cannot be scripted.

### Gaps
- Not checked: whether Descript's API (it has had a limited partner API in the past) exposes Remove Retakes, and whether Premiere's UXP API exposes Media Intelligence or transcript data.
