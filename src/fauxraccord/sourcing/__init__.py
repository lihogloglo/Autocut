"""fauxraccord-sources: gather B-roll candidates from a script's cited links and searches,
pick them on a contact sheet, export them with credits and a Premiere XML."""

from __future__ import annotations

import argparse
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse

from ..i18n import tr
from .collect import NO_SCREENSHOT, Ctx, harvest, rank_for
from .fetch import Fetcher
from .model import Asset, Manifest, add_note, date_note
from .script import ScriptDoc, parse_script


def default_out(script: Path) -> Path:
    return script.parent / f"{script.stem} - sources"


def _page_hints(doc: ScriptDoc) -> tuple[dict[str, list], dict[str, set[int]]]:
    """URL -> citing (sentence, link); URL -> PDF pages hinted by "(page N)" notes or anchors."""
    cites: dict[str, list] = {}
    hinted: dict[str, set[int]] = {}
    for s, link in doc.links():
        cites.setdefault(link.url, []).append((s, link))
        if link.page:
            hinted.setdefault(link.url, set()).add(link.page)
    for s in doc.sentences:
        if doc.sections[s.section].skip:
            continue
        for note in s.notes:
            m = re.fullmatch(r"(?:page|p\.)\s*(\d+)", note, re.I)
            if not m or any(link.page for link in s.links):
                continue
            # the most recent document cited a few sentences before, preferring PDFs
            recent = [(t, link) for t in doc.sentences[max(0, s.idx - 25):s.idx + 1][::-1]
                      if t.section == s.section for link in t.links]
            pick = next(((t, link) for t, link in recent if ".pdf" in link.url.lower()), recent[0] if recent else None)
            if pick:
                url = pick[1].url
                hinted.setdefault(url, set()).add(int(m.group(1)))
                if all(t.idx != s.idx for t, _ in cites.get(url, [])):
                    cites.setdefault(url, []).append((s, pick[1]))
    return cites, hinted


def collect(script: Path, out: Path | None = None, *, shots: bool = True, search: bool = True, web: bool = True,
            videos: bool = True, llm: str = "auto", judge: bool = True, brief: str = "", seg_len: float = 30, full_video_max: float = 600,
            shot_height: int = 4000, log=print) -> Path:
    """Harvest everything into <out>/manifest.json and write the contact sheet. Returns the output folder."""
    t0 = time.time()
    doc = parse_script(script)
    out = out or default_out(script)
    out.mkdir(parents=True, exist_ok=True)
    ctx = Ctx(Fetcher(out / "cache"), out, seg_len, full_video_max)
    cites, hinted = _page_hints(doc)
    steps = 3 + search
    log(tr("[1/{steps}] {title} : {n} phrases, {links} liens cités", steps=steps, title=doc.title,
           n=len(doc.sentences), links=len(cites)))

    worker = None
    if shots:
        from .shots import Job, ScreenshotWorker
        worker = ScreenshotWorker(ctx, log, shot_height)
        worker.start()

    assets: list[Asset] = []

    def one(url: str):
        sentences = [s for s, _ in cites[url]]
        try:
            cands = harvest(ctx, url, sentences, hinted.get(url, set()))
            err = None
        except Exception as e:
            cands, err = [], e
        res = [a for s, link in cites[url] for a in rank_for(ctx, s, link, cands)]
        is_pdf = any(c.asset.via == "pdf" for c in cands)
        if worker and not NO_SCREENSHOT.search(url) and not is_pdf:
            worker.jobs.put(Job(url, cites[url]))
        return url, res, err

    log(tr("[2/{steps}] collecte des liens (+ captures d'écran en parallèle)", steps=steps) if shots else
        tr("[2/{steps}] collecte des liens", steps=steps))
    with ThreadPoolExecutor(6) as ex:
        futures = [ex.submit(one, u) for u in cites]
        for i, f in enumerate(as_completed(futures), 1):
            url, res, err = f.result()
            assets += res
            host = urlparse(url).netloc.removeprefix("www.")
            short = (host + urlparse(url).path)[:70]
            if err:
                ctx.errors.append({"url": url, "error": f"{type(err).__name__}: {str(err)[:160]}"})
                log(f"  {i:3}/{len(cites)}  ✗ {short}  ({str(err)[:80]})")
            else:
                kinds = {}
                for a in res:
                    kinds[a.kind] = kinds.get(a.kind, 0) + 1
                desc = ", ".join(f"{n} {k}" for k, n in kinds.items()) or tr("rien")
                log(f"  {i:3}/{len(cites)}  {desc:<22} {short}")
    if worker:
        worker.jobs.put(None)

    from .search import heuristic_queries
    queries = heuristic_queries(doc)
    if search:
        from .search import llm_queries, search_paragraph
        log(tr("[3/{steps}] recherche pour {n} paragraphes", steps=steps, n=len(queries)))
        if brief.strip():
            log(tr("  consignes : {brief}", brief=brief.strip()[:200]))
        used, provider = llm_queries(queries, llm, log, doc.title, brief)
        if used == "heuristique":
            log(tr("  requêtes : heuristiques (noms propres, dates) — pour chercher l'événement plutôt que "
                   "les mots, connectez une IA (page IA de la fenêtre)"))
        judge_with = provider if judge else None
        if judge_with:
            from .llm import label
            log(tr("  tri : {engine} regarde les meilleures images de chaque paragraphe", engine=label(judge_with)))
        with ThreadPoolExecutor(4) as ex:
            futures = [ex.submit(search_paragraph, ctx, q, 10, videos, web, judge_with=judge_with, title=doc.title,
                                 brief=brief)
                       for q in queries]
            for i, f in enumerate(as_completed(futures), 1):
                assets += f.result()
                if i % 10 == 0 or i == len(queries):
                    log(tr("  {i}/{n} paragraphes", i=i, n=len(queries)))

    if worker:
        log(tr("[{steps}/{steps}] captures d'écran : {done} pages faites, attente de la fin…", steps=steps,
               done=worker.done))
        worker.join()
        assets += worker.assets
        log(tr("  {n} captures", n=sum(a.kind == 'screenshot' for a in worker.assets)))

    unique = {a.id: a for a in assets}
    # What time each paragraph is about, and a warning on pictures that can't be from then
    periods = {q.paragraph: (q.period, q.nature) for q in queries}
    for a in unique.values():
        period, nature = periods.get(a.paragraph, ("", ""))
        add_note(a, date_note(a, period, nature))
    manifest = Manifest(str(script), doc.title,
                        [asdict(s) for s in doc.sections],
                        [{"idx": s.idx, "text": s.text, "section": s.section, "paragraph": s.paragraph,
                          "links": [asdict(link) for link in s.links], "notes": s.notes,
                          "period": periods.get(s.paragraph, ("", ""))[0]} for s in doc.sentences],
                        list(unique.values()), ctx.errors)
    manifest.save(out / "manifest.json")
    from .sheet import write_page
    write_page(out)
    by_kind = {}
    for a in manifest.assets:
        by_kind[a.kind] = by_kind.get(a.kind, 0) + 1
    log("\n" + tr("{n} candidats ({kinds}), {problems} problèmes, {secs} s", n=len(manifest.assets),
                  kinds=", ".join(f"{n} {k}" for k, n in by_kind.items()), problems=len(ctx.errors),
                  secs=f"{time.time() - t0:.0f}"))
    from .llm import usage_summary
    if usage := usage_summary():
        log(tr("IA : {usage}", usage=usage.replace("\n", "\n     ")))
    log(tr("Dossier : {folder}", folder=out))
    return out


from .. import write_result  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="fauxraccord-sources", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="gather candidates for a script")
    c.add_argument("script", type=Path)
    c.add_argument("-o", "--out", type=Path, help="output folder (default: '<script> - sources' next to it)")
    c.add_argument("--no-shots", action="store_true", help="no page screenshots")
    c.add_argument("--no-search", action="store_true", help="cited links only")
    c.add_argument("--no-web", action="store_true", help="no DuckDuckGo image search (unknown licences)")
    c.add_argument("--no-videos", action="store_true", help="no YouTube search")
    c.add_argument("--llm", default="auto",
                   choices=["auto", "gemini", "claude", "claude-code", "codex", "antigravity", "ollama", "off"],
                   help="AI engine: auto = the first connected of Gemini (key), Claude (API), Claude Code, Codex, "
                        "Antigravity, Ollama; off = names and dates only")
    c.add_argument("--quality", default="best", choices=["best", "fast"], help="model tier of the AI engine")
    c.add_argument("--brief", default="", help="instructions for the search, e.g. 'favour historical documents'")
    c.add_argument("--no-judge", action="store_true",
                   help="don't have Gemini/Claude look at the pictures to drop the off-topic ones")
    c.add_argument("--segment", type=float, default=30, help="video excerpt length (s)")
    c.add_argument("--full-video-max", type=float, default=600, help="download whole videos up to this length (s)")
    c.add_argument("--shot-height", type=int, default=4000,
                   help="page screenshot height in page pixels, 1920 wide (the image is twice that: 3840 x 8000)")
    c.add_argument("--serve", action="store_true", help="open the contact sheet when done")
    s = sub.add_parser("sheet", help="open the contact sheet of an output folder")
    s.add_argument("folder", type=Path)
    e = sub.add_parser("export", help="Premiere XML of the selection at its sentences (downloads what is "
                                      "missing; run again on a newer edit)")
    e.add_argument("folder", type=Path)
    e.add_argument("--derush", type=Path, help="part 1 .fauxraccord.xml (its Sxxx markers give the sentence times)")
    e.add_argument("--edit", type=Path, help="current edit exported from Premiere (FCP7 XML): the B-roll follows "
                                             "the sentences wherever they are in it")
    e.add_argument("--edit-sequence", help="sequence of --edit to use (default: its only or last one)")
    e.add_argument("--model", default="large-v3", help="whisper model, when the sentences must be found by ear")
    e.add_argument("--auto", action="store_true", help="sentences without a choice get the AI's best candidate")
    f = sub.add_parser("fetch", help="download what placing needs (the choices; --auto: and the AI's picks)")
    f.add_argument("folder", type=Path)
    f.add_argument("--auto", action="store_true")
    pr = sub.add_parser("premiere", help="serve the Premiere panel (premiere/ folder) for this output folder")
    pr.add_argument("folder", type=Path)
    pr.add_argument("--derush", type=Path, help="part 1 .fauxraccord.xml")
    ip = sub.add_parser("install-panel", help="install or update the Premiere panel (needs Creative Cloud)")
    ip.add_argument("--force", action="store_true", help="reinstall even if this version is installed")
    return ap


def _serve_forever(folder: Path) -> None:
    from .sheet import serve
    server, url = serve(folder)
    print(tr("Planche : {url}  (Ctrl+C pour arrêter)", url=url))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.shutdown()


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    args = build_parser().parse_args()
    if args.cmd == "collect":
        from .llm import set_quality
        set_quality(args.quality)
        out = collect(args.script, args.out, shots=not args.no_shots, search=not args.no_search,
                      web=not args.no_web, videos=not args.no_videos, llm=args.llm, judge=not args.no_judge, brief=args.brief,
                      seg_len=args.segment,
                      full_video_max=args.full_video_max, shot_height=args.shot_height)
        write_result(out)
        if args.serve:
            _serve_forever(out)
    elif args.cmd == "sheet":
        _serve_forever(args.folder)
    elif args.cmd == "install-panel":
        from .bridge import install_panel
        install_panel(force=args.force)
    elif args.cmd == "premiere":
        from .bridge import PORT, start
        if not start(lambda kind="sources": {"out": args.folder, "derush": args.derush, "auto": False}):
            raise SystemExit(tr("port {port} déjà pris : FauxRaccord est-il déjà ouvert ?", port=PORT))
        print(tr("Panneau Premiere servi sur le port {port} (Ctrl+C pour arrêter)", port=PORT))
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    elif args.cmd == "fetch":
        from .library import fetch
        print("[1/1] " + tr("Téléchargement des images à placer"))
        n = fetch(args.folder, auto=args.auto)
        print(tr("{n} fichier(s) prêts", n=n))
        write_result(str(n))
    else:
        from .export import export
        write_result(export(args.folder, args.derush, args.edit, args.edit_sequence, model=args.model, auto=args.auto))
