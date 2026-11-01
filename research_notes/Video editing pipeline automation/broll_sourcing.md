# B-roll / Illustration Sourcing Automation for Documentary-Style YouTube (script -> per-paragraph candidates)

Research date: 2026-11-01. About 22 tool calls. Many pricing figures come from secondary or affiliate sites and are flagged as such. Items marked "(background knowledge, not re-verified this session)" come from the researcher's prior knowledge and should be checked before they are relied on.

## 1. Commercial tools that take a script/transcript and suggest/fetch B-roll (Premiere plugins, web apps)

### Takeaway
The Premiere-native auto-B-roll market is now crowded: AutoCut AutoB-Rolls, FireCut, B-Roll Genie, BuzzRolls, CaptionX (coming soon), plus the official Storyblocks panel and Adobe Firefly Boards. All of them match transcript keywords to stock libraries (mostly Storyblocks and Pexels) or generate AI images. None of them looks inside the creator's own cited source links, which is the creator's main workflow, so for a documentary that relies on citations a custom pipeline is still needed. Web apps (Pictory, InVideo, Submagic) are built for short-form or faceless video and don't integrate with Premiere.

### Cited Findings
- **AutoCut – AutoB-Rolls** (https://www.autocut.com): runs inside Premiere Pro as a panel next to the timeline, on Mac and Windows. It analyzes the transcript, generates search prompts, and pulls from integrated Storyblocks and Pexels libraries or from AI-generated visuals. Vendor claim: about 1h30 of footage analyzed in about 1 minute. 14-day free trial, no card required. Inserted clips are only roughly trimmed to the spoken moment, and the author says it works "especially well" for talking-head formats. — [AutoCut blog](https://www.autocut.com/en/blogs/best-b-roll-plugin-premiere-pro/)
- AutoCut added Storyblocks to AutoB-Rolls in December 2025. — [AutoCut: Storyblocks in Premiere](https://www.autocut.com/en/blogs/use-storyblocks-in-premiere-pro-autocut/)
- **FireCut – Find B-roll** (https://firecut.ai/features/b-roll): you click "Find B-roll", and FireCut finds concepts that stock footage could illustrate, selects Storyblocks clips, places them in the sequence, and lets you swap alternatives. It can also scan and AI-tag a folder of your own footage (a personal library). The Storyblocks usage license is included in the FireCut subscription because FireCut is a Storyblocks partner. Requires Premiere Pro 2022+ on Windows or macOS, with a DaVinci Resolve version also linked. 7-day trial. No price was listed on the feature page. — [FireCut B-roll](https://firecut.ai/features/b-roll)
- **B-Roll Genie**: a Premiere Pro extension that generates AI B-roll images from narration, inserts them in the timeline, and supports regeneration and a batch queue. Cost runs through your own Replicate or OpenAI API keys. — [parse.gl listing](https://parse.gl/brands/brollgenie-com) (secondary)
- **BuzzRolls**: launched on Product Hunt in December 2025. It searches for, downloads, and inserts stock footage based on clip segments. — [Product Hunt](https://www.producthunt.com/products/buzzrolls)
- **CaptionX auto B-roll for Premiere**: listed as "Coming Soon". — [caption-x.com](https://caption-x.com/auto-broll-premiere-pro)
- **B-Roll Selectr** (Eleven Percent): not a sourcing tool. It sorts your own B-roll by camera shake inside Premiere. — [Personal View](https://www.personal-view.com/news/articles/eleven-percent-releases-ai-“broll-selectr”-premiere-pro-plugin-automatically-cuts-out-shaky-footage)
- **Official Storyblocks plugin** for Premiere Pro and After Effects: search, preview, and download inside the editor, for Business and Pro plan members, distributed via Adobe's marketplace. Open it from Window > Extensions > Storyblocks. It does not read a script; it is manual search only. — [Storyblocks plugin](https://www.storyblocks.com/plugin); [Storyblocks help](https://help.storyblocks.com/en/articles/6406037-what-is-our-adobe-premiere-pro-plugin)
- **Adobe Firefly Boards -> Premiere Pro 26.2**: B-roll is storyboarded and generated in Firefly Boards, then pushed into a Premiere project without manual import. This comes from a third-party tutorial, not Adobe docs. — [anintent tutorial](https://anintent.pages.dev/blog/firefly-broll-generative-extend-premiere-pro/)
- **Submagic**: auto B-roll matches keywords in the transcript to a stock library. Premium B-roll and movie clips are reserved for Pro and above. One reviewer cites $39/mo Pro with Storyblocks B-roll. Built for short-form. — [toolsforhumans](https://www.toolsforhumans.ai/ai-tools/submagic); [GTM Directory](https://thegtmdirectory.com/compare/pictory-vs-submagic)
- **Pictory**: one source lists about $19/mo starter (30 videos/mo), while G2 shows $300/yr Standard. The sources conflict. — [aiagentrank](https://aiagentrank.io/ai-tools/compare/invideo-vs-pictory); [G2](https://www.g2.com/compare/pictory-ai-vs-submagic)
- **InVideo AI**: "from $20" per an aggregator. No reliable 2026 figure was found. — [aiagentrank](https://aiagentrank.io/ai-tools/compare/invideo-vs-submagic)
- **Descript**: free tier gives 1 h of media per month and 100 one-time AI credits. No reliable information was found on any Descript auto-B-roll feature. — [ToolQuestor](https://toolquestor.com/vs/descript-vs-pictory)
- FireCut's own 2026 roundup of Premiere plugins exists, but it is vendor-written. — [FireCut blog](https://firecut.ai/blog/top-premiere-pro-plugins-2026/)

### Inferences
- For a documentary that relies on citations, these plugins are useful only as a fallback for generic or atmospheric shots (cityscapes, "money", "laboratory"). They don't help find the specific photo of a named person, event, or document. That gap is what a custom pipeline has to fill.
- Bundled licensing (FireCut + Storyblocks) is the main legal advantage of the commercial tools: the footage is cleared. Footage scraped from articles or YouTube is not.
- Opus Clip and Captions are clipping and short-form tools. I found no evidence that they offer script-to-B-roll for long-form Premiere workflows (not researched in depth).

### Gaps
- No official 2026 price pages were fetched for AutoCut, FireCut, Pictory, InVideo, or Submagic.
- No Envato or Adobe Stock "script-aware" panel was found. Envato has an Elements plugin for Adobe apps (background knowledge, not re-verified this session), but nothing turned up showing it reads scripts.
- Reddit r/editors and r/NewTubers sentiment on these plugins was not gathered.

## 2. Open-source GitHub projects (script-to-video pipelines, B-roll finders, CLIP scene search)

### Takeaway
Several small 2025-2026 repos do almost exactly what this creator wants: an LLM reads the script, then the tool searches Pexels, Pixabay, Wikimedia, Openverse, and YouTube (via yt-dlp) and returns candidates per scene. All are small and young, and one disappeared during this research. MoneyPrinterTurbo is the large, well-maintained reference pipeline, but it is designed for short videos. For pulling the exact moment out of footage already downloaded, CLIP or VLM local search tools exist.

### Cited Findings
- **MoneyPrinterTurbo** (https://github.com/harry0703/MoneyPrinterTurbo): MIT license, about 137k stars and 1,223 commits as shown on the GitHub page in 2026-11 (the star figure is surprisingly high; verify it). Pipeline: topic -> LLM script -> search terms -> TTS -> subtitles -> stock clips from Pexels, Pixabay, Coverr, or local files -> MoviePy composition -> FFmpeg render. LLMs supported: OpenAI, Claude, Gemini, DeepSeek, Qwen, Moonshot, Grok, MiniMax, Ollama, OpenRouter, LiteLLM, and others. Showcased outputs run 14-59 s, so it is built for short-form. — [GitHub](https://github.com/harry0703/MoneyPrinterTurbo); [verdent guide](https://www.verdent.ai/guides/moneyprinterturbo-github)
- **erfsalehi/B-Roll-Finder**: described in search results as a local Python "AI director" that reads a script and returns timestamped B-roll suggestions from Pexels, Pixabay, YouTube (yt-dlp), and a local library. The LLM ranks candidates, a clip-quality gate filters them, and the LLM fallback runs across DeepSeek, Groq, and OpenRouter. **The repo returned HTTP 404 on 2026-11-01**, so it was deleted, renamed, or made private. Treat it as unavailable. — [search result](https://github.com/erfsalehi/B-Roll-Finder) (404 on fetch)
- **Yashrout07/broll-fetcher**: takes a `scenes.json` timeline and fetches a matching video or image per scene from Pexels, Pixabay, Wikimedia, and Openverse. MIT, Python 3.10+, cross-platform. Built for a "HyperFrames" YouTube pipeline. — [GitHub](https://github.com/Yashrout07/broll-fetcher)
- **louisedesadeleer/b-roll-finder**: a Claude Code agent skill. It reads the transcript, routes each beat to the right footage source, uses yt-dlp for YouTube search and a headless browser for screenshots, and places each cutaway on the exact word. — [GitHub](https://github.com/louisedesadeleer/b-roll-finder)
- **birol-dev/Pexels ("StockFinder AI")**: an Electron app. You paste a script, an AI agent finds Pexels footage, downloads it into organized folders, and exports attribution. — [GitHub](https://github.com/birol-dev/Pexels)
- **ClipForage** (Ry0x7): one search across YouTube (yt-dlp), Pexels, Pixabay, Mixkit, Internet Archive, and Wikimedia Commons, with the license shown on every result. Alpha. — [GitHub](https://github.com/Ry0x7/ClipForage-source)
- **NaufalRizqullah/opensource-clipping** and **Dovakiin0/clipmint**: long-to-short clippers (Whisper + LLM) with contextual B-roll. Not designed for documentary sourcing. — [opensource-clipping](https://github.com/NaufalRizqullah/opensource-clipping); [clipmint](https://github.com/Dovakiin0/clipmint)
- **CLIP / VLM scene search over local footage**:
  - **Semantic Eye** (GughanS): CLIP ViT-L-14, a motion filter, and a LanceDB index, with Docker support. — [GitHub](https://github.com/GughanS/semantic-eye)
  - **CLIFS** (johanmodin): CLIP text-to-frame matching plus OCR. — [sourcepulse](https://www.sourcepulse.org/projects/2336495)
  - **natural-language-youtube-search** (haltakov): samples YouTube frames and encodes them with CLIP. — [sourcepulse](https://www.sourcepulse.org/projects/1272962)
  - **SentrySearch** (ssrajadh): not CLIP. It uses Gemini, DashScope, or local Qwen3-VL embeddings, indexes local footage, and auto-trims the best match. A Reddit report says the local 8B model needs about 18 GB RAM. — [blog](https://themenonlab.blog/blog/sentrysearch-natural-language-video-search)
  - **goferclip**: the core search is unfinished. — [GitHub](https://github.com/qgofer/goferclip)

### Inferences
- ShortGPT (RayVentura), short-video-maker (gyoridavid, an MCP server built on Remotion and Pexels), and AutoShorts are other known script-to-video repos from background knowledge, not re-verified this session. Like MoneyPrinterTurbo, they target vertical shorts using Pexels. Their search-term-generation modules can be reused, but their rendering is irrelevant for a Premiere workflow.
- Best build path: reuse broll-fetcher's multi-source search (Pexels, Pixabay, Wikimedia, Openverse), add a "source-link scraper" stage (section 3) and a YouTube stage (section 4), and output a per-paragraph HTML or Markdown board plus a downloads folder. Optionally export an FCP XML or Premiere XML with markers. Then run CLIP or SentrySearch-style search over downloaded YouTube videos to find the exact seconds.
- Small single-author repos disappear (B-Roll-Finder went 404), so fork or vendor any repo you depend on.

### Gaps
- Current star counts and commit dates for ShortGPT, short-video-maker, and AutoShorts were not checked, so they were not confirmed as abandoned or active.
- Pexels and Pixabay API rate limits were not re-verified. From background knowledge: Pexels allows about 200 requests/hour and 20k/month by default, and Pixabay about 100 requests/60 s. Both are free with attribution encouraged.

## 3. Scraping cited source links for HD images; image search APIs; reverse image search

### Takeaway
Pulling the main image out of each cited article is straightforward with newspaper4k (`top_image` and all images) plus og:image and twitter:image meta tags. Generic image search is the area hit by deprecation: **Google's Custom Search JSON API, including image search, shuts down on 1 Jan 2027 (it will return HTTP 410)**, so a new build should use SerpApi, DataForSEO, Bright Data, Brave, or Serper. For reverse image search to find a higher-resolution copy, the options are Google Lens via SerpApi or Bright Data, or TinEye's API.

### Cited Findings
- **newspaper4k** (https://github.com/AndyTheFactory/newspaper4k): a fork of newspaper3k with a backwards-compatible API. Features include "top image extraction" (`article.top_image`) and "all image extraction" from HTML. Release line 0.9.x, Python 3.8+. — [PyPI](https://pypi.org/project/newspaper4k); [GitHub](https://www.github.com/AndyTheFactory/newspaper4k)
- **Google Custom Search JSON API**: Google announced in January 2026 that "The Custom Search JSON API will be discontinued on January 1, 2027". As of August 2026 it still works, and after the deadline it returns HTTP 410 Gone. No extension has been announced. Price was $5 per 1k queries after 100/day free. — [dev.to (NexGenData, a vendor with an interest)](https://dev.to/nexgendata/google-kills-custom-search-api-on-jan-1-2027-you-have-9-months-1jg1)
- The shutdown takes `searchType=image` with it. — [dev.to booyaka101](https://dev.to/booyaka101/googles-custom-search-image-api-dies-in-2027-two-traps-in-replacing-it-56cj)
- New customers: one source says the API was closed to new customers in 2025, and another just says it "no longer accepts new customers". The sources conflict on timing. Google points to Vertex AI Search, which searches your own corpus and is not a web or image search replacement. — [Apify blog](https://blog.apify.com/google-custom-search-api-alternative/); [Brave](https://brave.com/learn/google-api-shutdown/)
- Alternative prices as of Q3 2026, per a vendor-written article:

  | Provider | Price |
  |---|---|
  | SerpApi | $75/mo for 5k, $275/mo for 25k, $500/mo for 100k |
  | ScaleSerp | about $0.00075-0.001/query |
  | Bright Data SERP | about $5/1k |
  | Apify "google-cse-replacement" | $0.005/query |

  — [dev.to](https://dev.to/nexgendata/google-kills-custom-search-api-on-jan-1-2027-you-have-9-months-1jg1)
- **DataForSEO Google Images SERP API**: $0.002 per SERP page. — [DataForSEO](https://dataforseo.com/apis/serp-api/google-images-api)
- **Brave Search API** is pitched as a CSE alternative. — [Brave](https://brave.com/learn/google-api-shutdown/)
- **SerpApi Google Lens API**: active. The August 2026 changelog added organic results and short videos, and image uploads via image ID. A July 11, 2026 fix addressed high latency and a low success rate. Google replaced "search by image" with Lens entirely. — [SerpApi changelog](https://serpapi.com/blog/serpapi-weekly-changelog-august-03-09-2026/); [Lens release notes](https://serpapi.com/google-lens-api/release-notes); [SerpApi blog](https://serpapi.com/blog/how-google-replaced-search-by-image-with-google-lens/)
- **Bright Data Google Lens API**: charges only for successful results. **OrcaRouter** lists Lens reverse search at $0.0275/call. — [Bright Data](https://brightdata.com/products/serp-api/google-search/lens); [OrcaRouter](https://www.orcarouter.ai/tools/google/serp-images/x-google-images)
- **TinEye API**: an aggregator cites "from $200 for 5,000 searches, no free tier", while TinEye's blog mentions lowered API pricing. The $200 figure may be stale. — [ithy](https://ithy.com/article/affordable-image-search-apis-65o2gocf); [TinEye blog](https://blog.tineye.com/?p=7322)

### Inferences
- Recommended per-link routine (from background knowledge, not re-verified this session):
  1. Fetch the HTML.
  2. Collect og:image, twitter:image, JSON-LD `image`, and every `<img>` with `srcset`, then pick the largest `srcset` candidate.
  3. Remove CDN resize parameters, for example `?w=600` and WordPress `-300x200` suffixes, to recover the original file.
  4. Filter out results under about 1280 px wide.
  5. Run Lens or TinEye on the best result to find a larger or original copy, and note the original photographer or agency for credit and licensing.

  Tools for this:
  - trafilatura can extract metadata and images. gallery-dl handles galleries and social posts (Twitter/X, Instagram, Reddit, Flickr).
  - Playwright handles JS-heavy pages.
  - The Wikimedia Commons API (MediaWiki `action=query&generator=search&prop=imageinfo&iiprop=url|size|extmetadata`) returns full-resolution URLs together with license and author metadata. It is the best free source of licensed imagery for named people, places, and events.
- Anything built on Google CSE now will break in about 2 months. Don't build on it.

### Gaps
- Official SerpApi and TinEye 2026 price pages were not fetched.
- Brave Search API image endpoint pricing was not checked.
- Trafilatura's image-extraction capabilities were not verified this session.

## 4. YouTube search, clip extraction, transcript timestamp search, archival footage sources

### Takeaway
YouTube Data API search is quota-starved: about 100 searches per day per project by default. Most hobby tools therefore use yt-dlp's `ytsearchN:` to search, then pull auto-captions and search them to find the exact timestamps before downloading only that section. Archival footage is not free to reuse. British Pathé licenses per clip, now with a Content Creator Programme. Prelinger/Internet Archive footage is often public domain but comes with no permission or indemnity, which Getty sells.

### Cited Findings
- **YouTube Data API v3**: default 10,000 units/day. `search.list` costs 100 units, so about 100 searches per day per project. Every page costs full price, and even invalid requests cost at least 1 unit. Quota resets at midnight Pacific, and an exceeded quota returns 403 quotaExceeded. Extra quota requires the extension request form. — [Google docs](https://developers.google.com/youtube/v3/getting-started); [ChannelCrawler](https://channelcrawler.com/insights/youtube-api-daily-limit-quotas-costs-and-how-to-scale-beyond-10000-units-channelcrawler); [OutlierKit](https://outlierkit.com/resources/youtube-search-api/)
- In December 2025 the videos.insert cost dropped from about 1,600 to about 100 units. This doesn't affect search. — [getphyllo](https://www.getphyllo.com/post/is-the-youtube-api-free-in-2026-quota-limits-costs-when-to-pay)
- yt-dlp is the YouTube search and download backend in B-Roll-Finder, ClipForage, and louisedesadeleer/b-roll-finder. — [ClipForage](https://github.com/Ry0x7/ClipForage-source); [b-roll-finder skill](https://github.com/louisedesadeleer/b-roll-finder)
- **British Pathé**: footage is free to watch on YouTube (about 85k films uploaded in 2014), but the 2014 claim that it was Creative Commons was **retracted**. Licensing is per clip and priced by platform, territory, and term. A new "Content Creator Programme" serves eligible digital creators, but no prices were published. The company says it receives no public funding and can't provide footage free. — [British Pathé licensing](https://www.britishpathe.com/licensing/); [Boing Boing (with retraction)](https://boingboing.net/2014/04/18/british-pathe-puts-85000-news.html); [Open Culture](https://www.openculture.com/2014/04/free-british-pathe-puts-over-85000-historical-films-on-youtube.html)
- **Prelinger Archives / Internet Archive**: many films are freely accessible, but "the Internet Archive does not provide written permission… the user assumes all risk". About 5,000 Prelinger clips are licensable via **Getty Images**, which indemnifies against copyright claims for a fee. — [Prelinger stock footage](https://www.panix.com/~footage/stockfootage.html)
- **BFI** publishes archive footage licensing rates. — [BFI](https://www.bfi.org.uk/archive-content-sales-licensing/archive-footage-sales/archive-footage-licensing-rates)

### Inferences
- Practical pipeline, from background knowledge with flags as of 2025:
  1. Search with `yt-dlp "ytsearch20:<LLM query>" --flat-playlist -J`.
  2. Fetch captions with `--write-auto-subs --skip-download`, or use the `youtube-transcript-api` Python package.
  3. Use an LLM or embedding search over the timed transcript to locate the segment.
  4. Download the segment with `yt-dlp --download-sections "*00:12:30-00:12:50" -f "bv*[height>=1080]+ba"`.
  5. Optionally re-rank frames with CLIP (section 2).
- Caveat: YouTube's anti-bot measures (PO tokens, sign-in prompts, IP throttling) made yt-dlp less reliable through 2025. Expect to need cookies or frequent yt-dlp updates.
- Other archival sources (from background knowledge, not re-verified this session):
  - Pond5 (marketplace with public-domain collections)
  - Getty/iStock editorial
  - AP Archive and Reuters (both on YouTube; licensing is paid)
  - NARA and the Library of Congress (much US-government footage is public domain)
  - NASA (generally no copyright)
  - Europeana
  - Wikimedia Commons video

### Gaps
- The British Pathé Content Creator Programme pricing and terms were not obtained.
- Current yt-dlp YouTube reliability in late 2026 (PO token and SABR changes) was not verified.
- Pond5 and Getty creator pricing were not checked.

## 5. AI-agent approaches (LLM + browser/MCP) for a per-paragraph "illustration board"

### Takeaway
The agent pattern already exists in open source. louisedesadeleer/b-roll-finder is a Claude Code skill using yt-dlp and a headless browser, and short-video-style MCP servers exist. A per-paragraph board looks best built as an agent that splits the script into paragraphs, follows each inline citation link, scrapes images, runs targeted image, Wikimedia, and YouTube searches, and writes an HTML board with thumbnails, source URLs, resolution, and license status.

### Cited Findings
- louisedesadeleer/b-roll-finder: a Claude Code agent skill. It routes each transcript beat to the right source, uses yt-dlp for YouTube and a headless browser for screenshots, and places cutaways on exact words. — [GitHub](https://github.com/louisedesadeleer/b-roll-finder)
- birol-dev "StockFinder AI": an agent that turns a script into Pexels downloads in organized folders, with an attribution export. — [GitHub](https://github.com/birol-dev/Pexels)
- broll-fetcher's scenes.json timeline format is a convenient intermediate representation. — [GitHub](https://github.com/Yashrout07/broll-fetcher)
- ClipForage puts the license on every result, a useful design for the board. — [GitHub](https://github.com/Ry0x7/ClipForage-source)

### Inferences
- Suggested architecture (an inference):
  1. Parse the script (Markdown, DOCX, or Google Doc) into paragraphs and their hyperlinks.
  2. For each paragraph, the LLM extracts entities, dates, and visualizable concepts and writes 3-5 queries.
  3. Run the fetchers in parallel:
     - (a) the cited-link scraper (newspaper4k plus og:image and srcset)
     - (b) Wikimedia Commons
     - (c) a paid SERP image API, since CSE is dead in 2027
     - (d) yt-dlp search plus transcript timestamp match
     - (e) Pexels and Pixabay for generic shots
  4. Rank candidates with a vision-LLM or CLIP for relevance and filter on resolution.
  5. Output an HTML board grouped by paragraph and a folder per paragraph, plus optional Premiere markers or XML.
- Browser-automation MCPs (Playwright MCP, Chrome extension agents) help on JS-heavy or paywalled pages, but they are slower and cost more than direct HTTP. Use them only as a fallback.

### Gaps
- No commercial product was found that does citation-link-aware image harvesting per paragraph. This looks like an open gap in the market.

## 6. Automation helpers for the creator's own illustrations: Blender (MCP, scripting, AI 3D) and maps (GEOlayers 3 and alternatives)

### Takeaway
blender-mcp (ahujasid, MIT) lets an LLM drive Blender via Python. It integrates Poly Haven, Sketchfab, and Hyper3D Rodin, which suits low-poly explainer scenes. For AI 3D:
- Meshy and Tripo are hosted, with low-poly modes.
- Hunyuan3D's newest engines are hosted only.
- TRELLIS.2 (MIT) is cited as the best self-hostable option.

For maps:
- GEOlayers 3 (aescripts) is the AE standard. It needs MapTiler for full styling.
- Google Earth Studio can export a keyframed camera to AE, a free workflow.
- Blender-side, Blosm and BlenderGIS import OSM data and terrain.

### Cited Findings
- **blender-mcp** (https://github.com/ahujasid/blender-mcp): MIT. You install the `addon.py` Blender addon and the MCP server runs via `uvx blender-mcp`, over a socket on port 9876. The `execute_blender_code` tool runs arbitrary Python in Blender. Other features: viewport screenshots, Poly Haven and Sketchfab assets, and Hyper3D Rodin generation. Forks exist, for example CommonSenseMachines (CSM.ai) and a RetopoFlow variant. — [glama](https://glama.ai/mcp/servers/@ahujasid/blender-mcp/schema); [augmentcode](https://www.augmentcode.com/mcp/blender-mcp); [CSM fork](https://glama.ai/mcp/servers/@CommonSenseMachines/blender-mcp/tree/2a86e2e70daedab7f359dc624cf7aef71a9c1f30)
- **Meshy 6**: a dedicated Low Poly Mode and native quad remesh. Pro about $29/mo per an aggregator. — [krea](https://www.krea.ai/blog/best-ai-3d-model-generators-2026); [voxelforge](https://voxelforge-1gt.pages.dev/meshy.html)
- **Tripo**: "Smart Mesh" low-poly in about 2 s, versus Meshy at 5-8 min (a vendor claim). API credits are $0.01 each: textured image-to-3D costs 30, smart low-poly +10, parts +20, auto-rig +25. — [Tripo blog](https://www.tripo3d.ai/it/blog/meshy-alternative); [layer.ai](https://layer.ai/models/tripo3d-v2-5.md)
- **Hunyuan3D**: one source says engine 3.0 is not open-sourced and 3.1 is hosted (since January 2026). Another calls Hunyuan3D fully free and open. The sources conflict. The earlier 2.x open weights exist (background knowledge). **TRELLIS.2** (Microsoft, MIT) is cited as the best self-hostable option. — [cinevva guide](https://app.cinevva.com/es/guides/ai-3d-model-generators); [wavespeed](https://wavespeed.ai/blog/3d-model-access/best-meshy-ai-alternatives/)
- **GEOlayers 3** (aescripts):
  - map design and animation inside AE with many default styles
  - 3D camera scroll, zoom, pitch, and rotate via keyframes
  - styling of colors, lines, fonts, and hillshade
  - one-click labels from AE comp templates
  - CSV/TSV data import
  - full styling requires a MapTiler Cloud account
  - AE CC 2015 (13.6)+
  - GEOlayers 1/2 projects are not supported
  - upgrade from v2 $205 and from v1 $255 (SUL; full price not captured)
  - v1.5 update exists

  Beware the many piracy and SEO pages for "GeoLayers 3 v1.5.3". — [aescripts](https://aescripts.com/geolayers/); [Toolfarm v1.5](https://www.toolfarm.com/?p=79982)
- **Google Earth Studio** can export a keyframed AE camera, which makes it a free complementary map and fly-over workflow. — [search synthesis; lesterbanks](https://lesterbanks.com/?p=34203)
- **Blosm** (formerly blender-osm, vvoovv): imports OSM data, Google 3D cities, and global terrain into Blender. Free base version plus a paid Pro. — [GitHub](https://github.com/vvoovv/blosm)
- **BlenderGIS** (domlysz): OSM import from a file or via "Get OSM" on a georeferenced scene, plus basemaps. — [Wiki](https://github.com/domlysz/BlenderGIS/wiki/OSM-import)
- OSM data is licensed under ODbL, so attribution to OpenStreetMap is required. — [Blosm docs](https://github.com/vvoovv/blosm/wiki/Documentation)

### Inferences
- GEOlayers has an ExtendScript/expressions-friendly layer setup, but I found no documented public scripting API. Automation would go through AE ExtendScript driving GEOlayers effect properties. This is unverified.
- Other map options from background knowledge, not re-verified this session:
  - Mapbox Studio and MapTiler styles exported as tiles
  - kepler.gl (open source, Uber/OpenJS) for data-driven map animations, exported as video
  - "Animated route" web tools such as Mult.dev and TravelBoast
  - QGIS with Temporal Controller exports
- blender-mcp's arbitrary code execution is a security risk. Run it only with trusted prompts and models.

### Gaps
- GEOlayers 3 full price and scripting API docs were not found.
- Hunyuan3D 2.5 licensing (the Tencent community license excludes some regions, from background knowledge) was not verified.
- Kepler.gl and Mapbox-based AE plugins were not researched.

## 7. Copyright and fair use for documentary YouTubers using fetched imagery (brief)

### Takeaway
US courts often find documentary use of clips fair. A 2026 Tenth Circuit Tiger King ruling affirmed fair use of archival footage but on fact-specific grounds, with no categorical presumption. On YouTube, Content ID and DMCA takedowns put the burden on the creator, and even clearly fair uses can be taken down for weeks. Scraped article photos usually belong to agencies (Getty, AP, Reuters) that enforce aggressively. A pipeline should record provenance and license status for every asset and prefer CC, public-domain, licensed, or "subject of commentary" uses.

### Cited Findings
- Michael Moore's *Planet of the Humans* was removed from YouTube over a DMCA claim for about 4 seconds of footage from a UK photographer. It was restored after about 2 weeks. Claims can take months, and works may never be restored. — [Reclaim The Net](https://reclaimthenet.org/michael-moore-planet-of-the-humans-censored-youtube-copyright-claim); [IDA](https://documentary.org/online-feature/fair-use-documentary-never-ending-fight)
- Andrew Callaghan received a copyright strike from Fox 5 over a 1-minute clip in his documentary. Content ID and takedowns are automated, and the creator bears the burden of proving fair use. — [Techdirt](https://www.techdirt.com/2024/04/03/fox-station-copyright-strikes-youtubers-documentary-over-use-of-1-minute-clip)
- Courts usually deem documentaries fair use even when monetized. In 2026 the Tenth Circuit affirmed fair use of archival footage in the *Tiger King* dispute, but called it fact-specific with no categorical presumption for documentaries. — [pulse.bot (secondary)](https://www.pulse.bot/legal/news/tenth-circuit-affirms-fair-use-of-archival-footage-in-tiger-king-copyright-dispute-9984a3f5-94a9-426b-8690-a648c8fb1c53/)
- The Documentary Filmmakers' Statement of Best Practices in Fair Use, together with specialized counsel, is the recommended basis for fair-use claims. — [IDA](https://documentary.org/online-feature/fair-use-documentary-never-ending-fight)
- British Pathé on YouTube is not CC, and Prelinger/IA footage comes with no permission or indemnity (see section 4). — [British Pathé](https://www.britishpathe.com/licensing/); [Prelinger](https://www.panix.com/~footage/stockfootage.html)
- Pexels clip licenses carry conditions, so verify them before commercial use. — [verdent guide](https://www.verdent.ai/guides/moneyprinterturbo-github)
- OSM map data requires ODbL attribution. — [Blosm docs](https://github.com/vvoovv/blosm/wiki/Documentation)

### Inferences
- The board should store for each asset: source URL, original page, author or agency, license (CC type, PD, stock-licensed, or "unknown/fair-use claim"), and resolution. Unknown-license news photos should be used briefly, transformed (framed, annotated, discussed), and only when the image itself is the subject of commentary. Wikimedia Commons and government sources are safer substitutes.
- Agency photos (Getty, AP, Reuters, AFP) found via scraping are the highest-risk category. Getty runs automated enforcement (background knowledge).
- This is not legal advice. Fair use is US law, and other jurisdictions (UK and EU fair dealing, quotation exceptions) are narrower.

### Gaps
- YouTube's 2025-2026 policy changes on Content ID for still images were not researched.
- The specific Tiger King appellate citation was only found via a secondary aggregator.
