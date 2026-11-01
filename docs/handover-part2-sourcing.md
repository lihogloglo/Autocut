# Handover: Autocut part 2, automatic sourcing of illustrations from script citations

## Who I am and how I work
- French-language documentary/essay YouTuber (Lemmino / Fern style). Editing in **Premiere Pro 2026** + **After Effects 2026** on **Windows 11**, laptop **RTX 4060 8 GB**.
- My own illustrations: low-poly Blender scenes, maps with GeoLayers in AE. Everything else is fetched: images and video.
- **Hard constraint: no paid plugins, especially no subscriptions.** Open source and local first. If a paid service is truly unavoidable (e.g. pay-per-use search), say so clearly and propose a free alternative.
- Others will use the tools too → keep a simple GUI (French labels) + a double-click launcher, like part 1.

## Part 1 (done): the derush tool, in this repo
Python package managed with **uv** (Python 3.12), `src/autocut/`:
- `transcribe.py` (faster-whisper large-v3, word timestamps, cached JSON), `align.py` (Viterbi alignment of the transcript to the script with jumps), `takes.py` (classification take/failed/impro/adlib), `timeline.py`, `xmeml.py` + `premiere_xml.py` (FCP7 XML read/write, input = exported Premiere sequence), `text.py` (script reading: .md/.txt/.docx, YAML front matter and headings removed, Markdown/wiki links reduced to their text, URLs and `[1]` stripped, French sentence splitting, num2words normalisation), `gui.py` (Tk, French), `Autocut.bat` (installs uv + deps, launches the GUI).
- Tests: `uv run --with pytest pytest tests` (10 pass).
- **Don't break part 1.** Part 2 can live in the same repo (new module + new GUI tab or a second window) — your call, ask me if unsure.

## Part 2: what I want
My scripts are Markdown with inline sources: `[text](url)`. Today, for each passage:
1. I click the links in the passage and look for usable **HD images** (and videos) on the source page;
2. then I search Google Images and YouTube for illustrations of my point;
3. I download what I keep.

→ Goal: automate this pre-selection. For each paragraph/sentence of the script, gather candidate images and videos (from the cited links first, then searches), at the best available resolution, recording **source page, author/agency, licence, resolution** for every asset (copyright matters for YouTube: DMCA claims). The final output (folder per paragraph? HTML contact sheet? Premiere bin? markers on the derush sequence?) is to be discussed with me before you build it.

## Real test data
- Script: `C:\Users\leogloglo\Desktop\Révolution\La révolte en France n'est pas que politique.md` (204 sentences, many links: snes.edu, Wikipedia FR/EN with URLs containing parentheses, etc.). Use it as the reference case.
- The script also contains stage notes like `(extrait Bigard)`, `(page 9)`, `extrait` that hint at what to fetch (e.g. a TV clip): worth using.
- `text.py` currently **throws the URLs away**. Part 2 needs a parser that keeps each link attached to its sentence/paragraph (reuse the splitting, don't duplicate it).

## Research already done (read it before searching again)
- Full report: `reports/Video editing pipeline automation.md`
- B-roll notes: `research_notes/Video editing pipeline automation/broll_sourcing.md`

Key findings:
- **Nothing on the market follows the script's citation links**: an open gap. Closest blueprint: the **Sima 1.0** paper (arXiv 2604.07721, April 2026; Claude agents, no code released).
- Building blocks:
  - `newspaper4k` (top_image + all article images), parsing og:image / srcset for the largest version;
  - Wikimedia Commons API;
  - `gallery-dl`;
  - `yt-dlp` (search, captions to find the timestamp, partial download of a section);
  - repos `louisedesadeleer/b-roll-finder` (Claude Code skill), `Yashrout07/broll-fetcher` (Pexels/Pixabay/Wikimedia/Openverse), `ClipForage` (licence shown per result);
  - CLIP for searching inside downloaded footage.
- **Google Custom Search JSON API (image search included) shuts down on 2027-01-01** and is already closed to new customers. The alternatives are paid (SerpApi $75/month, DataForSEO ~$0.002/request pay-per-use, Brave, Serper) → discuss with me; look for free options (DuckDuckGo images, Bing, Openverse, Wikimedia, Flickr CC…).
- The YouTube Data API allows ~100 searches/day → that's why everyone uses yt-dlp search. yt-dlp is getting less reliable on YouTube (anti-bot): check its state in late 2026.
- Rights: British Pathé YouTube = not Creative Commons; Internet Archive/Prelinger = no guarantee.

## Questions to ask me before coding
1. Output format and how it fits into Premiere (folder / HTML contact sheet / bin / markers).
2. Granularity: per sentence, per paragraph, per `##` section?
3. Paid search APIs acceptable if pay-per-use and cheap, or 100% free?
4. Videos: full download, the relevant segment only, or just links + timestamps?
5. Any role for a local LLM (Ollama) or Claude API to generate search queries from the text? (For part 1 I chose 100% local.)

## Working preferences
- Test on real data, verify before claiming it works, report the limits honestly.
- Short explanations; tables are fine.
