"""Searches for paragraphs: query generation (heuristic, Ollama or Claude) + free image/video sources."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, replace
from urllib.parse import unquote, urlparse

from . import embed
from .collect import Ctx, video
from .model import CHECK, PROTECTED, Asset, rights_for
from .script import ScriptDoc, ScriptSentence

STOP = set("""
a à au aux avec ce ces cet cette ceci cela ça celle celles celui ceux chez comme dans de des du elle elles en
et eux il ils je la le les leur leurs lui ma mais me même mes moi mon ne nos notre nous on ou où par pas pour
qu que qui sa se ses son sur ta te tes toi ton tu un une vos votre vous y été être avoir avait ont fait faire
plus moins très tout tous toute toutes aussi alors donc bref ben bon bah ok oui non si quand puis car comment
pourquoi parce encore déjà après avant depuis pendant entre sans sous vers selon chaque autre autres quelque
quelques beaucoup peu trop assez ainsi enfin voilà voici c'est qu'il qu'on d'un d'une l'on n'est s'il est sont
était étaient sera seront peut peuvent doit va vont dit disait mal bien rien personne gens chose choses truc
trucs fois temps moment cas exemple façon manière genre heu euh hein mouvement monde point aujourd'hui demain
hier ici là-bas the of and in to for on with by from at as is are was were
""".split())
STOP_START = STOP | {"mais", "et", "donc", "or", "ni", "car", "puis", "ensuite", "enfin", "pire", "bref", "évidemment",
                     "effectivement", "rappelez", "faut", "on", "en", "au", "selon", "par", "pour", "dès", "juste",
                     "par", "plus", "déjà", "ce", "cette", "ces", "un", "une", "des", "le", "la", "les", "il", "elle"}
_CAP = re.compile(r"[A-ZÀÂÉÈÊÎÔÛÇ][\w’'\-]+(?:\s+(?:de|du|des|d'|d’|la|le|von|van|di|da)?\s*[A-ZÀÂÉÈÊÎÔÛÇ][\w’'\-]+)*")
_YEAR = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
_STOCK = re.compile(r"gettyimages|afp\.|reuters|alamy|shutterstock|istockphoto|dreamstime|123rf|depositphotos|"
                    r"adobestock|stock\.adobe|agefotostock|bridgemanimages|sipa|abacapress|maxppp", re.I)


@dataclass
class Query:
    paragraph: int
    sentence: int           # first sentence of the paragraph
    text: str               # paragraph text (for ranking)
    fr: list[str]
    en: list[str]
    video: str | None       # YouTube query when an excerpt is wanted


def paragraphs(doc: ScriptDoc) -> dict[int, list[ScriptSentence]]:
    out: dict[int, list[ScriptSentence]] = {}
    for s in doc.sentences:
        if not doc.sections[s.section].skip:
            out.setdefault(s.paragraph, []).append(s)
    return out


def _entities(sentences: list[ScriptSentence]) -> list[str]:
    found = []
    for s in sentences:
        for m in _CAP.finditer(s.text):
            words = m.group().split()
            if m.start() == 0 or s.text[:m.start()].rstrip().endswith((".", "!", "?", ":", "«", "\"", "-")):
                while words and words[0].lower().strip("’'") in STOP_START:
                    words = words[1:]
            name = " ".join(words).strip("’'-")
            if len(name) > 2 and name.lower() not in STOP_START:
                found.append(name)
    return [n for n, _ in Counter(found).most_common()]


def _wiki_titles(sentences: list[ScriptSentence]) -> list[tuple[str, str]]:
    out = []
    for s in sentences:
        for link in s.links:
            p = urlparse(link.url)
            if p.netloc.endswith("wikipedia.org") and "/wiki/" in p.path:
                title = unquote(p.path.split("/wiki/", 1)[1]).replace("_", " ")
                out.append((p.netloc.split(".")[0], re.sub(r"\s*\(.*?\)", "", title)))
    return out


def heuristic_queries(doc: ScriptDoc) -> list[Query]:
    pars = paragraphs(doc)
    doc_freq = Counter()
    words_of = {}
    for p, ss in pars.items():
        ws = [w.lower() for s in ss for w in re.findall(r"[\wÀ-ÿ’'-]{6,}", s.text)]
        ws = [w for w in ws if w not in STOP and not w.isdigit()]
        words_of[p] = ws
        doc_freq.update(set(ws))
    out = []
    for p, ss in pars.items():
        text = " ".join(s.text for s in ss)
        ents = _entities(ss)
        years = list(dict.fromkeys(_YEAR.findall(text)))
        tf = Counter(words_of[p])
        keys = sorted(tf, key=lambda w: -tf[w] / (1 + doc_freq[w]))[:3]
        wiki = _wiki_titles(ss)
        fr = []
        if ents:
            fr.append(" ".join(ents[:2] + years[:1]))
        fr.append(" ".join((ents[:1] + keys[:2]) or keys[:3]))
        en = [t for lang, t in wiki if lang == "en"][:2] + ents[:1]
        wants_video = any(re.match(r"extrait", n, re.I) for s in ss for n in s.notes)
        vq = None
        if wants_video:
            note = next(n for s in ss for n in s.notes if re.match(r"extrait", n, re.I))
            subject = note[len("extrait"):].strip() or " ".join(ents[:2] or keys[:2])
            vq = f"{subject} {' '.join(keys[:2])}".strip()
        out.append(Query(p, ss[0].idx, text, [q for q in dict.fromkeys(fr) if q.strip()],
                         [q for q in dict.fromkeys(en) if q.strip()], vq))
    return out


# --- LLM query generation (optional) ------------------------------------------------------------

LLM_INSTRUCTIONS = (
    "Tu aides un vidéaste documentaire à trouver des illustrations (photos, archives, cartes, tableaux, "
    "extraits vidéo) pour chaque paragraphe de son script. Pour chaque paragraphe, propose : 'fr' = 1 à 2 "
    "requêtes d'images courtes en français, 'en' = 1 à 2 requêtes courtes en anglais adaptées à Wikimedia "
    "Commons (noms propres, événements, lieux, objets concrets, dates), 'youtube' = une requête YouTube si un "
    "extrait vidéo serait utile (discours, archive télé, scène de film), sinon une chaîne vide. Des requêtes "
    "visuelles et concrètes, pas des concepts abstraits."
)
_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["queries"], "properties": {
    "queries": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                           "required": ["id", "fr", "en", "youtube"], "properties": {
        "id": {"type": "integer"}, "fr": {"type": "array", "items": {"type": "string"}},
        "en": {"type": "array", "items": {"type": "string"}}, "youtube": {"type": "string"}}}}}}


def ollama_available() -> str | None:
    import httpx
    try:
        tags = httpx.get("http://localhost:11434/api/tags", timeout=2).json().get("models", [])
    except Exception:
        return None
    wanted = os.environ.get("AUTOCUT_OLLAMA_MODEL")
    names = [m["name"] for m in tags if "embed" not in m["name"]]
    if wanted and wanted in names:
        return wanted
    return names[0] if names else None


def _apply(queries: list[Query], answers: list[dict]) -> int:
    by_id = {a.get("id"): a for a in answers}
    n = 0
    for q in queries:
        a = by_id.get(q.paragraph)
        if not a:
            continue
        q.fr = [x for x in a.get("fr", []) if x][:2] or q.fr
        q.en = [x for x in a.get("en", []) if x][:2] or q.en
        q.video = a.get("youtube") or q.video
        n += 1
    return n


def llm_queries(queries: list[Query], mode: str, log=print) -> str:
    """Refine heuristic queries with an LLM. mode: auto | ollama | claude | off. Returns what was used."""
    if mode == "off":
        return "heuristique"
    if mode in ("auto", "ollama"):
        model = ollama_available()
        if model:
            import httpx
            log(f"  requêtes : Ollama ({model})")
            done = 0
            for q in queries:
                try:
                    r = httpx.post("http://localhost:11434/api/chat", timeout=120, json={
                        "model": model, "stream": False, "format": _SCHEMA,
                        "messages": [{"role": "system", "content": LLM_INSTRUCTIONS},
                                     {"role": "user", "content": json.dumps(
                                         {"paragraphes": [{"id": q.paragraph, "texte": q.text}]}, ensure_ascii=False)}]})
                    done += _apply([q], json.loads(r.json()["message"]["content"]).get("queries", []))
                except Exception:
                    pass
            return f"Ollama {model} ({done}/{len(queries)})"
        if mode == "ollama":
            log("  Ollama introuvable (http://localhost:11434) : requêtes heuristiques")
            return "heuristique"
    if mode in ("auto", "claude") and (os.environ.get("ANTHROPIC_API_KEY") or mode == "claude"):
        try:
            import anthropic
            client = anthropic.Anthropic()
            payload = json.dumps({"paragraphes": [{"id": q.paragraph, "texte": q.text} for q in queries]},
                                 ensure_ascii=False)
            response = client.beta.messages.create(
                model=os.environ.get("AUTOCUT_CLAUDE_MODEL", "claude-opus-5-5"),
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": _SCHEMA}},
                system=LLM_INSTRUCTIONS,
                messages=[{"role": "user", "content": payload}],
            )
            if response.stop_reason == "refusal":
                raise RuntimeError("requête refusée")
            text = next(b.text for b in response.content if b.type == "text")
            n = _apply(queries, json.loads(text).get("queries", []))
            log(f"  requêtes : Claude ({n}/{len(queries)} paragraphes)")
            return "Claude"
        except Exception as e:
            log(f"  Claude indisponible ({type(e).__name__}: {str(e)[:100]}) : requêtes heuristiques")
    return "heuristique"


# --- Sources ------------------------------------------------------------------------------------

def _strip(s: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", s or "").split())


def commons(ctx: Ctx, q: str, n: int = 12) -> list[tuple[Asset, str]]:
    data = ctx.fetch.json("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "format": "json", "formatversion": 2, "generator": "search",
        "gsrsearch": f"{q} filetype:bitmap|drawing", "gsrnamespace": 6, "gsrlimit": n, "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 480,
        "iiextmetadatafilter": "LicenseShortName|LicenseUrl|Artist|Credit|ImageDescription|ObjectName"})
    out = []
    for pg in data.get("query", {}).get("pages", []):
        ii = (pg.get("imageinfo") or [None])[0]
        if not ii or max(ii.get("width", 0), ii.get("height", 0)) < 800:
            continue
        md = {k: _strip(v.get("value", "")) for k, v in ii.get("extmetadata", {}).items()}
        title = md.get("ObjectName") or pg["title"].split(":", 1)[1].rsplit(".", 1)[0]
        lic = md.get("LicenseShortName", "")
        mime = ii.get("mime", "")
        a = Asset(id="", kind="image", via="commons", origin="recherche", sentence=-1, paragraph=-1, url=ii["url"],
                  thumb=ii.get("thumburl", ""), source_page=ii.get("descriptionurl", ""), title=title[:120],
                  author=md.get("Artist", "")[:120], licence=lic, licence_url=md.get("LicenseUrl", ""),
                  credit=md.get("Credit", "")[:200], rights=rights_for(lic or None), width=ii.get("width", 0),
                  height=ii.get("height", 0), note="svg" if "svg" in mime else ("tiff" if "tif" in mime else ""))
        out.append((a, f"{title}. {md.get('ImageDescription', '')[:300]}"))
    return out


def europeana(ctx: Ctx, q: str, n: int = 10) -> list[tuple[Asset, str]]:
    key = os.environ.get("EUROPEANA_KEY", "api2demo")
    data = ctx.fetch.json("https://api.europeana.eu/record/v2/search.json", {
        "wskey": key, "query": q, "media": "true", "reusability": "open", "qf": "TYPE:IMAGE", "rows": n,
        "profile": "rich"})
    out = []
    for it in data.get("items", []):
        full = (it.get("edmIsShownBy") or [""])[0]
        if not full:
            continue
        title = (it.get("title") or [""])[0]
        lic = (it.get("rights") or [""])[0]
        creator = (it.get("dcCreator") or [""])[0]
        a = Asset(id="", kind="image", via="europeana", origin="recherche", sentence=-1, paragraph=-1, url=full,
                  thumb=(it.get("edmPreview") or [full])[0], source_page=it.get("guid", ""), title=title[:120],
                  author=(creator or (it.get("dataProvider") or [""])[0])[:120], licence=lic, licence_url=lic,
                  rights=rights_for(lic or None))
        desc = " ".join((it.get("dcDescription") or [""])[:1])[:300]
        out.append((a, f"{title}. {desc}"))
    return out


_ddg_lock = threading.Lock()
_ddg_state = {"last": 0.0, "off": False}


def ddg_images(ctx: Ctx, q: str, n: int = 12) -> list[tuple[Asset, str]]:
    if _ddg_state["off"]:
        return []
    from ddgs import DDGS
    with _ddg_lock:
        wait = _ddg_state["last"] + 2.0 - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            results = DDGS().images(q, region="fr-fr", safesearch="moderate", max_results=n)
        except Exception as e:
            _ddg_state["off"] = True
            ctx.errors.append({"url": "duckduckgo", "error": f"recherche DuckDuckGo arrêtée : {str(e)[:120]}"})
            return []
        finally:
            _ddg_state["last"] = time.monotonic()
    out = []
    for r in results:
        w, h = int(r.get("width") or 0), int(r.get("height") or 0)
        if max(w, h) < 800:
            continue
        page = r.get("url", "")
        stock = _STOCK.search(r.get("image", "") + " " + page)
        a = Asset(id="", kind="image", via="web", origin="recherche", sentence=-1, paragraph=-1, url=r["image"],
                  thumb=r.get("thumbnail") or r["image"], source_page=page, title=(r.get("title") or "")[:120],
                  author=r.get("source") or urlparse(page).netloc, rights=PROTECTED if stock else CHECK,
                  width=w, height=h, note="banque d'images / agence" if stock else "licence inconnue (recherche web)")
        out.append((a, a.title))
    return out


def youtube(ctx: Ctx, q: str, query_text: str, n: int = 3) -> list[tuple[Asset, str]]:
    import yt_dlp
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True}) as y:
        res = y.extract_info(f"ytsearch{n}:{q}", download=False)
    out = []
    for e in res.get("entries") or []:
        url = e.get("url") or f"https://www.youtube.com/watch?v={e.get('id')}"
        try:
            for c in video(ctx, url, query_text):
                c.asset.via, c.asset.origin = "youtube", "recherche"
                out.append((c.asset, c.asset.title))
        except Exception:
            continue
    return out


def search_paragraph(ctx: Ctx, q: Query, keep: int, videos: bool, web: bool) -> list[Asset]:
    found: list[tuple[Asset, str]] = []
    jobs = [(commons, x) for x in q.en[:2] + q.fr[:1]] + [(europeana, x) for x in (q.en or q.fr)[:1]]
    if web:
        jobs += [(ddg_images, x) for x in q.fr[:1]]
    for fn, query in jobs:
        try:
            found += fn(ctx, query)
        except Exception as e:
            ctx.errors.append({"url": f"{fn.__name__}: {query}", "error": str(e)[:150]})
    vids = []
    if q.video and videos:
        try:
            vids = youtube(ctx, q.video, q.text)
        except Exception as e:
            ctx.errors.append({"url": f"youtube: {q.video}", "error": str(e)[:150]})
    seen, unique = set(), []
    for a, text in found:
        if a.url not in seen:
            seen.add(a.url)
            unique.append((a, text))
    sims = embed.similarity(q.text, [t for _, t in unique])
    ranked = []
    for (a, _), sim in zip(unique, sims):
        bonus = {"libre": 0.1, "protégé": -0.25}.get(a.rights, 0) + 0.05 * min(1.0, max(a.width, a.height) / 3000)
        ranked.append((float(sim) + bonus, a))
    ranked.sort(key=lambda x: -x[0])
    out = []
    for score, a in ranked[:keep] + [(0.5, v) for v, _ in vids]:
        a = replace(a, sentence=q.sentence, paragraph=q.paragraph, score=round(score, 3))
        a.id = Asset.make_id(a.via, a.url, q.paragraph)
        a.note = (a.note + " · " if a.note else "") + "requête : " + (
            q.video if a.kind == "video" else next((x for x in q.en + q.fr), ""))
        out.append(a)
    return out
