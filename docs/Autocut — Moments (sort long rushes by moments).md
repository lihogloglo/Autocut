# Autocut — Moments (sort long rushes by moments)

Nov 2, 2026 · @Leo

## Need

A Rust player wants Autocut to sort 10-hour gameplay sessions by moments, not by text. Marking or noting moments by hand is not feasible at that length.

- **Moments he wants:** building a house, life low, being shot at, shooting someone, dying.
- **Generalization:** the same tool should sort B-roll for documentary makers who have to sift through many hours of rushes.
- **Constraint:** keep Autocut's rules: free and open-source parts, rushes stay on the PC by default, never rename clips or create new media in the Premiere output.

## Prior art

No free tool sorts hours of your own rushes by moments you define and sends them to Premiere. Tools that work well either target one game or rely on a large cloud model.

| Approach | Examples | Why it doesn't fit 10 h of Rust |
| --- | --- | --- |
| The game sends events | [NVIDIA Highlights](https://www.nvidia.com/en-gb/geforce/news/shadowplay-highlights-tutorial/), [Overwolf/Outplayed](https://overwolf.com/app/insights_gaming-insights_capture), [Medal](https://medal.tv/developer/valorant) | The game's developer must add support; Rust has none. Works only while recording, not on existing files. |
| Reading the kill feed (text recognition or icon matching) | [Montage Maker](https://github.com/rlmsinclair/montage_maker), [GameVideoEdit](https://github.com/Friend-Xu/GameVideoEdit/), [EZClips](https://github.com/corp14x3/EZClips), [Highlightly](https://github.com/CGodiksen/highlightly), NiceShot (YOLO + RapidOCR) | One game at a time. Vanilla Rust has no kill feed; only [server mods](https://umod.org/plugins/kill-feed) add one. Montage Maker skips deaths on purpose. |
| A network trained per game | [Crispy](https://github.com/Flowtter/crispy), [X-CLIP fine-tuned (paper)](https://arxiv.org/abs/2505.07721), over 90 % on shooters | Needs a labelled dataset per game. The paper's code is not published. |
| Matching sounds | pop1-auto-editor, about 75 % on the kill sound | Too many false hits on its own. |
| Footage search (paid) | [Jumper](https://provideocoalition.com/review-ai-driven-video-search-with-jumper/amp) (local, in Premiere, about $99 one-off), [Eddie AI](https://www.heyeddie.ai/features/broll-logging), Kino, [Twelve Labs](https://www.forasoft.com/blog/article/ai-powered-video-editing-solutions) (about $2.50 per video hour) | Paid. Eddie, Kino and Twelve Labs run in the cloud on a subscription. |
| Footage search (open source) | [SearchLightAI](https://dev.to/kiranbaby14/i-built-a-video-search-engine-that-understands-what-youre-looking-for-51m7), [video-rag-bot](https://github.com/di37/video-rag-bot) | One frame every few seconds, embedded with SigLIP or CLIP, searched by words with timestamps. Building blocks, not an editing tool. |

Video AI models now write timestamps ([Qwen3-VL](https://arxiv.org/pdf/2512.14698v2), [TimeLens2](https://huggingface.co/papers/2607.17423.md); Gemini reads one frame per second, about 100 tokens per second at [low resolution](https://ai.google.dev/gemini-api/docs/media-resolution?authuser=1)). Their start and end times stay loose over long videos, so they fit checking a candidate better than scanning 10 hours.

## Design

Index each rush once, slowly and generically. Then each type of moment is a cheap re-score of that index, taught by the user from their own footage. No per-game engineering is needed.

&#91;embedded content: Moments pipeline · 5 steps, 1 teaching loop\]

The slow pass runs once per rush; everything after it is a re-score you can repeat as often as you like.

**The index (cached per rush file, like the transcripts).** An image embedding every 1–2 s, audio tags every second (the 527 AudioSet classes: gunshot, explosion, hammer, laughter…), loudness, cuts between shots, and the transcript that already exists. Adding a moment type later never re-reads the 10 hours.

**Four signals define a moment type, in any mix:**

| Signal | Good at | Rust example |
| --- | --- | --- |
| Words (image–text zero-shot) | General scenes | "building a wooden structure with a blueprint", "night", "boat" |
| Examples: pick 1–3, then ✓/✗ the results ("more like this") | Fixed screens, visuals hard to put into words | The death screen: one full-screen interface, the same every time |
| Sound | Combat, tools | Gunshot density = a fight; hammer and building sounds |
| Screen zone: draw a box once on a gauge or number | Game interfaces | Health bottom right gives a life curve: under 30 % = life low, a sharp drop = being hit |

Signals combine: being shot at = gunfire + a health drop; shooting = loud close gunfire, no drop. Telling those two apart is the hardest call, so "fight" is the reliable moment and the split is best effort.

**Presets bundle these definitions.** Rust: death, building, fight, life low, being hit. Generic shooter: death, fight, life low. Documentary: interview, wide landscape, close-up on people, drone, animals, vehicles, signs and text, plus "unusable" flags (shaky, blurry, badly exposed). The user's ✓/✗ adapt a preset to their game or camera.

**Optional AI check, off by default.** Only candidate moments (a few frames each) go to the engine chosen on the IA page. It confirms them and writes a short description into the marker ("builds a stone foundation"). The cost is shown before the run. Off by default because the README promises rushes never leave the PC.

**Bonus for documentaries.** An indexed B-roll folder becomes a source for Illustrations: each script paragraph also searches your own rushes.

## UX

A new **Moments** page next to Derush, usable on its own: it starts from rushes, not from a script. The name reads the same in French and English.

1. **Drop** the rushes: a folder of OBS recordings or a Premiere sequence.
2. **Pick a preset**. It fills in the moment types as editable chips; **+** adds one in plain words ("when I'm on a boat").
3. **Analyser**: indexing with progress, time left and Stop, like the other jobs. The first time only, draw the health box on a sample frame.
4. **The board** opens in its own window, like the contact sheet:
   - On top, one long strip per rush with a coloured lane per moment type: the whole 10 hours at a glance, click to jump.
   - Below, moment cards with hover-to-scrub, duration and confidence, plus ✓ / ✗, "more like this" and a free search box ("on a horse").
   - Per type, sliders for sensitivity and for the seconds kept before and after (a death with 8 s before it).
5. **Into Premiere, keeping the link to the rushes** (no renamed clips, no new media):
   - range markers, one colour per type, on the sequence (XML or panel);
   - one string-out sequence per type (every death end to end, with the extra seconds), copying the original clipitems as Derush does;
   - a **Moments** entry in the panel's *Quoi* menu.

## Plan

Start with a test on real footage. It decides the models before any page is built.

| Step | Work | Delivers |
| --- | --- | --- |
| 0 | Test on 1–2 h of Rust and one documentary rush folder | Measured decoding speed (keyframes only vs. hardware decoding), CLIP vs. SigLIP on each moment type, death-screen example matching, health-box reading. A small HTML report of hits and misses. |
| 1 | `moments/index.py` | ffmpeg at 1 frame per 1–2 s; frames shrunk for the image model, HUD crops at full resolution; image embeddings (ONNX); audio tags (PANNs/AST as ONNX, the AudioSet classes earshot uses, no torch); shot changes from embedding differences. Cache in `%LOCALAPPDATA%\autocut\index`. |
| 2 | `moments/types.py` + `presets/*.json` | Moment definitions (words and words to exclude, sounds, zone rule, examples) give a score per second, then time ranges (two thresholds, small gaps merged, minimum length, extra seconds). ✓/✗ train a small numpy classifier on the embeddings. Labels through i18n. |
| 3 | `web/moments.html` + a page in `index.html` | Lanes, cards, ✓/✗, similar, search; saved in `<rushes>.moments.json` |
| 4 | Premiere output | XML with coloured range markers and string-outs (`premiere_xml`, `xmeml`); a Moments mode in the panel, which already reads markers and must learn to write them |
| 5 | AI check (optional) | Candidates to the chosen engine, confirmed and described, cost shown first |
| 6 | Documentary extras | Quality flags per shot; your own B-roll as an Illustrations source |

**Timing, to confirm in step 0.** 10 h is about 36,000 frames: a few minutes of embedding on an NVIDIA card, about half an hour on the processor alone.

**Main risk: decoding.** Every frame of 10 h of 1080p60 takes about 45 min even with hardware decoding. Reading only keyframes is much faster; full decoding is used only around candidates to place start and end precisely.

What we know of Rust's interface (no kill feed, health bottom right, the death screen, the building blueprint) comes from memory, not a checked source. Step 0 must confirm it on real footage.

## Open questions

- [ ] Can the Rust player send a 1–2 h recording? Is there a documentary rush folder to test on? Step 0 depends on it.
- [ ] Output: range markers, string-out sequences, or both?
- [ ] Privacy: may the optional AI check send a few frames of the rushes, or does the first version stay 100 % local?

## Sources

- Game clippers: [Montage Maker](https://github.com/rlmsinclair/montage_maker), [GameVideoEdit](https://github.com/Friend-Xu/GameVideoEdit/), [Crispy](https://github.com/Flowtter/crispy), [Highlightly](https://github.com/CGodiksen/highlightly), [EZClips](https://github.com/corp14x3/EZClips), [Gameplay Highlights Generation](https://arxiv.org/abs/2505.07721)
- Game integrations: [NVIDIA Highlights](https://www.nvidia.com/en-gb/geforce/news/shadowplay-highlights-tutorial/), [Overwolf Insights](https://overwolf.com/app/insights_gaming-insights_capture), [Medal on Valorant](https://medal.tv/developer/valorant)
- Rust: [kill-feed mods](https://umod.org/plugins/kill-feed), [hit markers patch notes](https://www.pcgamer.com/uk/rust-devblog-details-bandanas-quiver-hitbox-fixes-and-more)
- Footage search: [Jumper review](https://provideocoalition.com/review-ai-driven-video-search-with-jumper/amp), [Eddie AI](https://www.heyeddie.ai/features/broll-logging), [Fora Soft guide](https://www.forasoft.com/blog/article/ai-powered-video-editing-solutions), [SearchLightAI](https://dev.to/kiranbaby14/i-built-a-video-search-engine-that-understands-what-youre-looking-for-51m7), [video-rag-bot](https://github.com/di37/video-rag-bot), [FastEmbed image embedding](https://qdrant.github.io/fastembed/examples/Image_Embedding), [AutoTag (Springer)](https://link.springer.com/content/pdf/10.1007/s11042-023-15565-w.pdf), [Resolve range keywording](https://www.provideocoalition.com/davinci-resolve-is-a-few-steps-away-from-range-based-keywording/)
- Video models: [Qwen3-VL report](https://arxiv.org/pdf/2512.14698v2), [TimeLens2](https://huggingface.co/papers/2607.17423.md), [Gemini media resolution](https://ai.google.dev/gemini-api/docs/media-resolution?authuser=1)
