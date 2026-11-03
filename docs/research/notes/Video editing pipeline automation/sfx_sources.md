# Pluggable SFX sources: which subscriptions and free banks a desktop program can use

Research date: 2026-11-03. This follows `sfx_automation.md` and `sfx_visual_events.md` and does not repeat them. **Verified** means I read the official doc or saw the live API's response. **Snippet** means search-result text only. **Inference** means my own reasoning.

The question for each source: from Autocut on the user's PC, using the user's own account, can we (a) search, (b) preview, (c) download the original, (d) use it in a monetized YouTube video, and (e) do the terms allow automation?

## 1. Epidemic Sound: closing the MCP gap

**This is the one subscription a personal subscriber can reach from code.** Verified on the [MCP developer docs](https://developers.epidemicsound.com/docs/mcp/):

- **Tools** (from `tools/list`):
  - SFX: `SearchSoundEffects`, `SearchSimilarToSoundEffect`
  - Downloads: `DownloadSoundEffect`, `DownloadRecording`
  - Music: `SearchRecordings`, `SearchSimilarToRecording`, `SearchExternalReferences`
  - Adapt: `EditRecording`, `PollEditRecordingJob`, `DownloadRecordingEdit`
  - Voices: `ListVoices`, `GenerateVoiceover`, `DownloadVoiceover`, and others
- **Transport:** Streamable HTTP at `https://www.epidemicsound.com/a/mcp-service/mcp`. Requests are JSON-RPC POSTs and replies come as SSE. After `initialize`, clients send `Mcp-Session-Id`. The docs give curl examples for `initialize` and `tools/list`.
- **Auth for a non-Claude client:** "Any MCP client that can send an `Authorization` header should use an API key." The header is `Authorization: Bearer <key>`. The user creates the key under Account → API keys, and it is "valid for one year" (a search snippet said 30 days; the docs win).
- **OAuth is closed to us:** it uses Dynamic Client Registration with a fixed allowlist of redirect URIs for established clients, and Epidemic "does not issue OAuth client IDs".
- **Rules that fit Autocut's model:**
  - Keys are per account. Do not share keys or generate them for end users; each person uses their own.
  - Do not call the server from browser JavaScript; proxy it through your backend. For Autocut, that means the Python side, not `web/app.js`.
  - Searching is free; downloading needs a paid subscription.
  - Rate limits are not published.
- **I probed the endpoint without a key.** It returns `401` with `WWW-Authenticate: Bearer resource_metadata=…/.well-known/oauth-protected-resource`. So a Python client using the official `mcp` SDK (`streamablehttp_client(url, headers={"Authorization": …})`) should work. The SDK detail is inference from the SDK; it is not stated in Epidemic's docs.
- **Still unknown:** what `DownloadSoundEffect` returns (a signed URL, a format choice, MP3 or WAV). The docs list the tool but do not describe its output. The voiceover flow says "download the file with `DownloadVoiceover`, or get the playback URL". Inference: it most likely returns a time-limited URL that Autocut then saves to disk itself. **The way to settle it is a 5-minute test:** run `tools/list` with the user's key and read the input and output schemas.
- **Licence terms:** a separate [MCP Server Software License Agreement](https://www.epidemicsound.com/policy/epidemic-sound-mcp-server-software-license-agreement/) governs use. The page is client-rendered and I could not read its text. Epidemic's product page says the MCP "doesn't change any of your licensing or usage terms" ([tools/mcp](https://www.epidemicsound.com/tools/mcp/)). The catalogue is 250k+ SFX (MCP page). Personal plan is about $9.99/month billed yearly (official referral page, snippet).
- **Local folder (verified, [Windows app page](https://www.epidemicsound.com/app/windows)):** the desktop app saves downloads "to your local Documents folder" by default, "saved and sorted automatically". The location can be changed in ☰ → Settings. So a watched-folder fallback also works. Where the Premiere plugin stores its downloads was not found.

**Verdict:** direct integration over MCP with the user's API key, plus watching the desktop app's download folder as a fallback.

## 2. Other subscriptions

- **Artlist.**
  - Its MCP (`mcp.artlist.io`, beta, 120 requests/min) only does image and video *generation*. "Music generation, catalog search… are not available through MCP yet" ([help, 2026-08-27](https://help.artlist.io/hc/en-us/articles/38948588333469-Artlist-MCP-Connect-Claude-ChatGPT-and-VS-Code-to-Artlist)).
  - The Enterprise API is partner-only and covers music.
  - The Music+SFX plans cover monetized social channels (support article, snippet).
  - Verdict: **watched folder** (the user's browser download folder).
- **Envato Elements.**
  - There is an official MCP at `mcp.envato.com/mcp`, with no auth, described as an "early proof-of-concept" (3 Jul 2026). It only searches and links to item pages, and asked whether it downloads, the answer is "No, not currently" ([Envato article](https://elements.envato.com/learn/envato-mcp-server)).
  - The public API (build.envato.com) covers Envato Market, not Elements.
  - The Premiere extension lets you "choose where to save assets" ([Adobe Exchange](https://exchange.adobe.com/apps/cc/200494), snippet).
  - The Elements licence requires registering each project; the terms page returned 403 to me.
  - Verdict: **watched folder**. MCP search could be used only to deep-link the user to items.
- **Motion Array.** No API. Its Library extension (Window → Extensions → Motion Array Library) saves to Downloads by default and can be changed ([help](https://help.motionarray.com/hc/en-us/articles/25428948393501-How-to-install-the-Motion-Array-Library-Extension), snippet). Verdict: **watched folder**.
- **Storyblocks.** The [API](https://www.storyblocks.com/api) is B2B: free test keys, "contact us" for production, and an "API license" that is separate from the subscriber licence. There is a community MCP wrapper (`rocksfrow/storyblocks-mcp`, unaffiliated). Verdict: **watched folder** only.
- **Soundstripe.** It has a real SFX API: list, search, categories, and around 100k SFX ([docs](https://docs.soundstripe.com/reference/list-sound-effects)). Access is negotiated with the partnerships team (snippet). Verdict: **no** for individuals, so watched folder.
- **Pond5.** The API is for resellers and partners ([pond5.com/api](https://www.pond5.com/api)), and the content is pay-per-clip. Verdict: **no**, watched folder.
- **Uppbeat.** No API found. Free-plan downloads carry a credit code to paste into the video description. Verdict: **watched folder**.
- **Adobe Stock.**
  - Premiere 24.6 and later can search Adobe Stock SFX in Essential Sound → Browse, and "~11K" of them are free for Creative Cloud users ([Adobe community beta post](https://community.adobe.com/announcements-732/now-in-beta-free-sfx-and-music-from-adobe-stock-313793), 2024).
  - Audio may not be distributed on its own ([Stock terms](https://www.adobe.com/go/stockterms)).
  - I found no documented Stock API support for audio.
  - Verdict: **no direct route**. The user places these by hand in Premiere.
- **Soundly.**
  - No public API found.
  - Cloud sounds go to a configurable "Download" folder in Settings, and guides suggest pointing it at the Premiere scratch folder ([A Sound Effect guide](https://www.asoundeffect.com/organize-sound-libraries-soundly/), snippet).
  - The local index is `Users/<you>/Soundly Data/LocalFilesDB` ([FAQ](https://getsoundly.com/faq/where-is-my-local-library-stored), 2020).
  - Verdict: **watched folder**.
- **Splice.**
  - No public API. Its SFX catalogue is small; Splice is music-sample focused.
  - The licence is royalty-free for commercial projects, but sounds cannot be resold "as sound effects" ([licensing FAQ](https://intercom.help/splice-b7a2d5b83f2e/en/articles/8652642-splice-sounds-licensing-faq)).
  - Downloads go to `C:\Documents\Splice` (as written by Splice; in practice likely `%USERPROFILE%\Documents\Splice`), "organized by pack" ([support](https://support.splice.com/en/articles/8652631-where-do-my-downloaded-samples-presets-midi-files-go)). The plugin uses `%APPDATA%\Splice\Plug-in\samples`.
  - Verdict: **watched folder**, which is easy because the path is known.
- **Soundsnap and A Sound Effect.** No API. Soundsnap has one unified licence ([licence](https://www.soundsnap.com/licence)). A Sound Effect sells libraries as zip files. Verdict: **watched folder**.
- **ElevenLabs** (generation, not a library).
  - Official REST API with the user's personal key; the earlier note covers SFX v2 at 40 credits per second.
  - Paid plans carry a commercial licence: Starter $6/month for 30k credits, Creator $22/month for 121k ([pricing](https://elevenlabs.io/pricing)). The FAQ puts one generation at about 200 credits, so Starter gives roughly 150 SFX a month.
  - The free plan requires credit to "elevenlabs.io" for commercial use ([ElevenLabs SFX page](https://elevenlabs.io/sound-effects/commercial)). You may not use output to build competing products.
  - Verdict: **direct integration** as a "generate" source.
- **Freepik AI SFX.** Its API lists audio generation (header `x-freepik-api-key`), but the docs are migrating to Magnific (snippet). Low priority.

**Automation in the terms.** Zapsplat's licence explicitly bans "automated access (bots, scrapers, scripts)" (licence updated 2025-09-29, snippet; the page returned 403 to me). I did not read the scraping clauses of the other consumer sites. Inference: none of them give an individual sanctioned programmatic access except Epidemic (through MCP) and ElevenLabs. So Autocut must **not** script their websites. Indexing files the user downloaded is fine, because the user's licence covers those files.

## 3. Free banks

- **Freesound** (verified, [auth](https://freesound.org/docs/api/authentication.html), [resources](https://freesound.org/docs/api/resources_apiv2.html)).
  - **Token auth** (the user's API key) is enough for search, metadata and `previews` (`preview-hq-mp3`, 128 kbps).
  - **Originals** come from `/sounds/<id>/download/`, which "requires OAuth2". The authorization-code flow lets Freesound itself act as the redirect, which "displays the code on screen" for the user to paste. That suits a desktop app with no local web server. Access tokens last 24 hours and refresh tokens rotate.
  - **Licence filter:** the values are `Attribution`, `Attribution NonCommercial` and `Creative Commons 0`, so the filter is `filter=license:"Creative Commons 0"`. Durations take `duration:[0.1 TO 0.6]`.
  - **Similarity:** `similar_to` takes a sound ID *or a vector* in the `laion_clap` (512-d) or `freesound_classic` space. Inference: a LAION-CLAP *text* embedding computed locally can be passed as the vector, which gives text-to-audio semantic search without any text encoder on Freesound's side. Test this.
  - **Limits and terms:** 60 requests/min and 2,000/day; 30 downloads/min and 500/day. The API terms require one key per application and forbid copying the database (earlier note). Since the licence covers the sound in any form, a CC0 HQ preview is legally usable, but the user wants maximum quality, so use OAuth originals.
  - **Size:** Openverse indexes 591,898 Freesound items.
  - Community MCP: `mushan-bit/freesound-mcp` (Node; search and download).
  - Verdict: **direct integration, first among the free banks**.
- **Openverse** (verified by a live call). `GET https://api.openverse.org/v1/audio/?q=whoosh&license=cc0` returned 240 results, each with licence, attribution string, tags, duration, a preview URL and `alt_files` (the Freesound original-download URL). The `/audio/stats/` endpoint lists three sources: Wikimedia (3,986,828 items, mostly speech and music), Jamendo (644,709, music) and Freesound (591,898).
  - Anonymous limits, seen in response headers: **20/min and 200/day**. Registering a client-credentials app unlocks the "standard" tier ([throttling doc](https://docs.openverse.org/api/reference/authentication_and_throttling.html)).
  - `category=sound_effect` returned 0 results because Freesound items have `category: null`.
  - Openverse does not re-verify upstream licences (snippet).
  - Its Freesound index looks stale (indexed 2024-05).
  - Verdict: **optional**; querying Freesound directly is better.
- **Wikimedia Commons.**
  - It has the MediaWiki API (`list=search`, `srnamespace=6`, CirrusSearch `filemime:`) and per-file licence data in `extmetadata`.
  - Licences are mixed, and much is CC-BY-SA, which needs attribution.
  - Its useful SFX are already reachable through Openverse.
  - Verdict: **no**; it adds little.
- **Internet Archive.**
  - It has `advancedsearch.php` and a metadata API, with `mediatype:audio` and `licenseurl` fields (from my knowledge of the API; not re-checked).
  - Licences are inconsistent and mostly music or radio.
  - Verdict: **no**.
- **Pixabay.** The API covers images and video only (earlier note). Verdict: **watched folder**.
- **Mixkit.** No API. Verdict: watched folder.
- **Zapsplat.** No API. Automation is banned and the free tier requires credit. Verdict: watched folder.
- **Kenney.** CC0 zip files, so they can be **bundled**.
- **Sonniss GDC bundles.** Zip files; they cannot be redistributed or used for AI training. Verdict: watched folder.
- **99Sounds.** Royalty-free and no attribution required ([about](https://99sounds.org/about/)). Zip files. Verdict: watched folder.
- **OpenGameArt.** No API (inference) and mixed licences. Verdict: watched folder.
- **itch.io packs.** The API only covers your own uploads and purchases; there is no catalogue search. Licences are per pack. Verdict: watched folder.
- **GameSounds.xyz.** I could not confirm its licence. Skip.
- **Lotsofsounds** (new find, [site](https://www.lotsofsounds.com/)).
  - It has a REST API and an MCP at `api.lotsofsounds.com/mcp` (Streamable HTTP, `x-api-key` header). Tools: `search_sounds`, `get_sound`, and `download_sound`, which returns a 1-hour signed URL (Glama listing).
  - About 15k sounds, all marked CC0. Files are MP3 only. Pro costs $15/month for 2,500 requests a day.
  - **Where the sounds come from is not stated**, so treat the CC0 claim with caution.
  - Verdict: **maybe later**.

**Sound-library MCP servers that exist:** Epidemic (official, downloads), Envato (official, search only), Artlist (official, generation only), Lotsofsounds (official, CC0), and the community-built Freesound (`mushan-bit`) and Storyblocks (`rocksfrow`) servers. ElevenLabs also has an official MCP server that includes text-to-SFX (from my knowledge; not re-checked). Autocut does not need MCP for any source except Epidemic, where MCP is the only route.

## 4. Summary table

| Source | API for an individual | Auth | Search / preview / original | Monetized YouTube | Automation OK | Cost | SFX catalogue | Autocut verdict |
|---|---|---|---|---|---|---|---|---|
| Epidemic Sound | **Yes, MCP** (REST is partner-only) | Account API key, Bearer, 1 year | Yes / yes / `DownloadSoundEffect` (output format unknown) | Yes (subscription) | Yes, sanctioned. Own key only, called from the backend | ~$10/month Personal | 250k+ | **Direct (MCP) + watched folder** (Documents by default) |
| Artlist | No (MCP is generation only) | — | — | Yes | No | ~$10–25/month | Large | Watched folder |
| Envato Elements | MCP search only, no download | None | Search / — / — | Yes (register per project) | Not for downloads | Subscription | Large | Watched folder (extension's save folder) |
| Motion Array | No | — | — | Yes | No | Subscription | — | Watched folder (Downloads by default) |
| Storyblocks | Partner API | Contract | — | Yes | Partner only | B2B | — | Watched folder |
| Soundstripe | Partner API with SFX | Contract | — | Yes | Partner only | B2B | ~100k | Watched folder |
| Pond5 | Partner API | Contract | — | Per clip | Partner only | Per clip | 1M+ | Watched folder |
| Uppbeat | No | — | — | Free plan needs a credit code | No | Free / paid | — | Watched folder |
| Adobe Stock | No audio API found | — | Inside Premiere only | Yes (synced to picture only) | — | ~11k free with CC | 15k+ | No (manual in Premiere) |
| Soundly | No | — | — | Per library | No | Subscription | — | Watched folder (configurable Download folder) |
| Splice | No | — | — | Yes (no resale as SFX) | No | Subscription | Small for SFX | Watched folder (`Documents\Splice`) |
| Soundsnap / A Sound Effect | No | — | — | Yes | No | Paid | Large | Watched folder |
| ElevenLabs | **Yes** | Personal API key | Generates WAV/MP3 | Paid plans yes; free plan needs credit | Yes | $6+/month | Generated | **Direct (generate)** |
| **Freesound** | **Yes** | Token; **OAuth2 for originals** | Yes / HQ MP3 / original via OAuth | Filter to CC0 for no attribution | Yes. Own key, no DB copy, 500 downloads/day | Free | ~600k (all licences) | **Direct, first** |
| Openverse | Yes | None or client credentials | Yes / yes / via upstream | Filter `license=cc0` | Yes, 200/day anonymous | Free | Mirrors Freesound | Optional |
| Wikimedia / Internet Archive | Yes | None | Yes | Mixed, often attribution | Yes | Free | Low SFX yield | No |
| Lotsofsounds | Yes (REST + MCP) | `x-api-key` | Yes / yes / signed URL (MP3) | Claimed CC0 | Yes | $15/month for the API | ~15k | Later, after checking provenance |
| Pixabay, Mixkit, Zapsplat, Sonniss, 99Sounds, OpenGameArt, itch.io | No | — | — | Mostly yes; Zapsplat free tier needs a credit | Zapsplat bans it | Free | — | Watched folder |
| Kenney | No | — | — | CC0 | — | Free | ~100s | **Bundle** |

## 5. Recommendation

1. **Build a "Local folders" source first.** It indexes any folder with LAION-CLAP plus filename and UCS tags, and stores each file's sync point. Ship preset paths for the Epidemic app (`Documents`, as set in the app), Splice (`Documents\Splice`), and the user's Downloads folder, plus an "add folder" button. This one feature covers every subscription that has no API, legally, because the user downloaded the files under their own licence. Bundle Kenney CC0 as the default pack.
2. **Freesound next, with the user's own key.** Search with `license:"Creative Commons 0"` and short durations. Use OAuth2 with the paste-the-code flow so downloads are originals. Try the local CLAP text vector with `similar_to` in `laion_clap` space. Cache downloads locally and respect the 500 downloads/day limit.
3. **Epidemic over MCP**, for subscribers. The user pastes their account MCP key, the same way as the existing AI-engine keys. Autocut calls `SearchSoundEffects`, then `DownloadSoundEffect`, from Python. First run one `tools/list` with a real key to pin down the download output schema.
4. **ElevenLabs as the "generate when nothing fits" fallback**, with the user's key. Warn when the key belongs to a free plan, because then attribution is required.
5. **Skip for now:** the partner APIs (Storyblocks, Soundstripe, Pond5, the Epidemic REST API), Envato's search-only MCP, Openverse, Commons, Internet Archive, and Lotsofsounds. Never script the websites of Zapsplat or any other subscription that has no API.
