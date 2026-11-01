"""autocut-sources: gather B-roll candidates from a script's cited links and searches,
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

from .collect import NO_SCREENSHOT, Ctx, harvest, rank_for
from .fetch import Fetcher
from .model import Asset, Manifest
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
            videos: bool = True, llm: str = "auto", seg_len: float = 30, full_video_max: float = 600,
            shot_height: int = 2400, log=print) -> Path:
    """Harvest everything into <out>/manifest.json and write the contact sheet. Returns the output folder."""
    t0 = time.time()
    doc = parse_script(script)
    out = out or default_out(script)
    out.mkdir(parents=True, exist_ok=True)
    ctx = Ctx(Fetcher(out / "cache"), out, seg_len, full_video_max)
    cites, hinted = _page_hints(doc)
    steps = 3 + search
    log(f"[1/{steps}] {doc.title} : {len(doc.sentences)} phrases, {len(cites)} liens cités")

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

    log(f"[2/{steps}] collecte des liens" + (" (+ captures d'écran en parallèle)" if shots else ""))
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
                desc = ", ".join(f"{n} {k}" for k, n in kinds.items()) or "rien"
                log(f"  {i:3}/{len(cites)}  {desc:<22} {short}")
    if worker:
        worker.jobs.put(None)

    if search:
        from .search import heuristic_queries, llm_queries, search_paragraph
        queries = heuristic_queries(doc)
        log(f"[3/{steps}] recherche pour {len(queries)} paragraphes")
        used = llm_queries(queries, llm, log)
        if used == "heuristique":
            log("  requêtes : heuristiques (noms propres, dates, mots-clés)")
        with ThreadPoolExecutor(4) as ex:
            futures = [ex.submit(search_paragraph, ctx, q, 10, videos, web) for q in queries]
            for i, f in enumerate(as_completed(futures), 1):
                assets += f.result()
                if i % 10 == 0 or i == len(queries):
                    log(f"  {i}/{len(queries)} paragraphes")

    if worker:
        log(f"[{steps}/{steps}] captures d'écran : {worker.done} pages faites, attente de la fin…")
        worker.join()
        assets += worker.assets
        log(f"  {sum(a.kind == 'screenshot' for a in worker.assets)} captures")

    unique = {a.id: a for a in assets}
    manifest = Manifest(str(script), doc.title,
                        [asdict(s) for s in doc.sections],
                        [{"idx": s.idx, "text": s.text, "section": s.section, "paragraph": s.paragraph,
                          "links": [asdict(link) for link in s.links], "notes": s.notes} for s in doc.sentences],
                        list(unique.values()), ctx.errors)
    manifest.save(out / "manifest.json")
    from .sheet import write_page
    write_page(out)
    by_kind = {}
    for a in manifest.assets:
        by_kind[a.kind] = by_kind.get(a.kind, 0) + 1
    log(f"\n{len(manifest.assets)} candidats ({', '.join(f'{n} {k}' for k, n in by_kind.items())}), "
        f"{len(ctx.errors)} problèmes, {time.time() - t0:.0f} s")
    log(f"Dossier : {out}")
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="autocut-sources", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="gather candidates for a script")
    c.add_argument("script", type=Path)
    c.add_argument("-o", "--out", type=Path, help="output folder (default: '<script> - sources' next to it)")
    c.add_argument("--no-shots", action="store_true", help="no page screenshots")
    c.add_argument("--no-search", action="store_true", help="cited links only")
    c.add_argument("--no-web", action="store_true", help="no DuckDuckGo image search (unknown licences)")
    c.add_argument("--no-videos", action="store_true", help="no YouTube search for '(extrait …)' notes")
    c.add_argument("--llm", default="auto", choices=["auto", "ollama", "claude", "off"],
                   help="query generation: Ollama if running, else Claude if ANTHROPIC_API_KEY is set, else heuristic")
    c.add_argument("--segment", type=float, default=30, help="video excerpt length (s)")
    c.add_argument("--full-video-max", type=float, default=600, help="download whole videos up to this length (s)")
    c.add_argument("--shot-height", type=int, default=2400,
                   help="page screenshot height in page pixels, 1920 wide (the image is twice that: 3840 x 4800)")
    c.add_argument("--serve", action="store_true", help="open the contact sheet when done")
    s = sub.add_parser("sheet", help="open the contact sheet of an output folder")
    s.add_argument("folder", type=Path)
    s.add_argument("--derush", type=Path, help="part 1 .autocut.xml, to place the B-roll at the sentence times")
    s.add_argument("--edit", type=Path, help="current edit exported from Premiere (FCP7 XML): place on it instead")
    e = sub.add_parser("export", help="export the current selection (again: re-places it, e.g. on a newer edit)")
    e.add_argument("folder", type=Path)
    e.add_argument("--derush", type=Path, help="part 1 .autocut.xml (its Sxxx markers give the sentence times)")
    e.add_argument("--edit", type=Path, help="current edit exported from Premiere (FCP7 XML): the B-roll follows "
                                             "the sentences wherever they are in it")
    e.add_argument("--edit-sequence", help="sequence of --edit to use (default: its only or last one)")
    return ap


def _serve_forever(folder: Path, derush: Path | None, edit: Path | None = None) -> None:
    from .sheet import serve
    server, url = serve(folder, derush, edit=edit)
    print(f"Planche : {url}  (Ctrl+C pour arrêter)")
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
        out = collect(args.script, args.out, shots=not args.no_shots, search=not args.no_search,
                      web=not args.no_web, videos=not args.no_videos, llm=args.llm, seg_len=args.segment,
                      full_video_max=args.full_video_max, shot_height=args.shot_height)
        if args.serve:
            _serve_forever(out, None)
    elif args.cmd == "sheet":
        _serve_forever(args.folder, args.derush, args.edit)
    else:
        from .export import export
        export(args.folder, args.derush, args.edit, args.edit_sequence)
