"""Searches for paragraphs: what to look for (Gemini, Claude, Ollama or a heuristic: the event, the famous
pictures of it, the kind of picture wanted), where (the Wikipedia article of the event, the Commons files
that depict it, then Commons, Europeana, the Met, David Rumsey for maps, web image search and YouTube),
and ranking by what the pictures actually show: CLIP first, then a vision model looks at the best ones
and drops what is off-topic."""

from __future__ import annotations

import html
import json
import os
import re
import threading
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field, replace
from urllib.parse import unquote, urlparse

from . import embed
from .collect import Ctx, video, wikipedia
from .model import CHECK, FREE, PROTECTED, QUOTE, Asset, rights_for
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
hier ici là-bas ouais the of and in to for on with by from at as is are was were
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
    fr: list[str]           # image queries in French (heuristic: names + year)
    en: list[str]           # Commons queries (English when an LLM wrote them)
    video: str | None       # YouTube query when an excerpt is wanted
    section: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)       # (anchor, url) cited in the paragraph
    cited_wiki: list[tuple[str, str]] = field(default_factory=list)  # (lang, title) of cited articles
    wiki: list[tuple[str, str]] = field(default_factory=list)        # (lang, title) of articles on the subject
    wiki_search: str | None = None   # heuristic: find the article with this (names + year)
    web: list[str] = field(default_factory=list)                     # web image search queries
    visual: str = ""                 # English description of the ideal picture, for CLIP
    nature: str = ""                 # kind of picture wanted: carte, portrait, photo, peinture, ...
    known: list[tuple[str, str]] = field(default_factory=list)       # (famous picture, where it is held)
    archives: list[str] = field(default_factory=list)                # museum / library catalogue queries
    extract_note: bool = False       # "(extrait …)" in the paragraph
    video_covered: bool = False      # the cited video is the excerpt asked for
    by: str = "heuristique"


def paragraphs(doc: ScriptDoc) -> dict[int, list[ScriptSentence]]:
    out: dict[int, list[ScriptSentence]] = {}
    for s in doc.sentences:
        if not doc.sections[s.section].skip:
            out.setdefault(s.paragraph, []).append(s)
    return out


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _proper_nouns(doc: ScriptDoc) -> set[str]:
    """Capitalised words seen in the middle of a sentence (or as a link anchor) somewhere in the script:
    a capital at the start of a sentence alone says nothing ("Evidemment", "Commençons")."""
    out = set()
    for s in doc.sentences:
        out |= set(re.findall(r"(?<=[\w,;’')»] )([A-ZÀÂÉÈÊÎÔÛÇ][\w’'\-]+)", s.text))
        out |= {w for link in s.links for w in link.anchor.split() if w[:1].isupper()}
    return {w for w in out if w.lower() not in STOP_START}


def _entities(sentences: list[ScriptSentence], proper: set[str]) -> list[str]:
    found = []
    for s in sentences:
        for m in _CAP.finditer(s.text):
            words = m.group().split()
            if m.start() == 0 or s.text[:m.start()].rstrip().endswith((".", "!", "?", ":", "«", "\"", "-", "(")):
                while words and words[0] not in proper:
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
    """Queries from what a paragraph names: proper nouns, years, cited Wikipedia titles. Paragraphs that
    name nothing concrete get no query (keywords alone bring back noise); an LLM does much better."""
    from .collect import VIDEO_HOSTS
    pars = paragraphs(doc)
    proper = _proper_nouns(doc)
    # A name found all over the script ("France", "État") is the topic, not what this paragraph shows.
    spread = Counter(_fold(e) for ss in pars.values() for e in set(_entities(ss, proper)))
    common = {e for e, n in spread.items() if n > max(3, len(pars) * 0.06)}
    out = []
    order = sorted(pars)
    for k, p in enumerate(order):
        ss = pars[p]
        text = " ".join(s.text for s in ss)
        ents = [e for e in _entities(ss, proper) if _fold(e) not in common]
        years = list(dict.fromkeys(_YEAR.findall(text)))
        wiki = _wiki_titles(ss)
        fr = []
        if ents:
            fr.append(" ".join(ents[:2] + years[:1]))
        fr += [t for lang, t in wiki if lang == "fr"][:1]
        # a lone name is ambiguous ("Chili" = Chile, but also chili peppers): give it its context
        en = [t for lang, t in wiki if lang == "en"][:2] + ([" ".join(ents[:2] + years[:1])] if ents else [])

        vq, covered = None, False
        note = next((n for s in ss for n in s.notes if re.match(r"extraits?\b", n, re.I)), None)
        if note:
            # "(extrait)" alone refers to what was just said: the previous paragraph's subject
            prev = pars[order[k - 1]] if k else []
            near = ss + prev
            has_video = any(VIDEO_HOSTS.search(link.url) and "reddit.com" not in link.url
                            for s in near for link in s.links)
            subject = re.sub(r"^extraits?\s*", "", note, flags=re.I).strip()
            if not subject:
                subject = " ".join((ents or _entities(prev, proper))[:2] + years[:1])
            if subject and not (has_video and not re.sub(r"^extraits?\s*", "", note, flags=re.I).strip()):
                vq = subject
            if has_video and subject and any(subject.lower() in link.anchor.lower()
                                             for s in near for link in s.links):
                vq = None   # the cited video is the excerpt
            covered = vq is None
        fr = [q for q in dict.fromkeys(fr) if q.strip()]
        q = Query(p, ss[0].idx, text, fr, [q for q in dict.fromkeys(en) if q.strip()], vq,
                  section=doc.sections[ss[0].section].title,
                  links=[(link.anchor, link.url) for s in ss for link in s.links], cited_wiki=wiki,
                  web=fr[:1], extract_note=note is not None, video_covered=covered)
        # a name alone finds the country, the person or the brand, not the event: only with a year
        if ents and years:
            q.wiki_search = " ".join(ents[:2] + years[:1])
        out.append(q)
    return out


# --- What to look for: Gemini, Claude, Ollama ----------------------------------------------------

NATURES = ["rien", "carte", "portrait", "photo", "peinture", "gravure", "document", "objet", "lieu", "archive vidéo"]

LLM_INSTRUCTIONS = """Tu es documentaliste iconographe : tu aides un vidéaste documentaire à illustrer son script \
(photos d'archives, tableaux, gravures, cartes anciennes, documents, extraits vidéo). Tu reçois le script entier, en \
paragraphes numérotés, avec leur section et les liens qu'ils citent, et la liste des paragraphes à traiter.

Pour chaque paragraphe, trouve ce qui est montrable : l'événement précis (lieu, date), la personne, le lieu, \
l'objet, le document. Sers-toi des paragraphes voisins et du sujet du script pour situer et dater : par exemple \
« Au Chili, une hausse de 4 % du ticket de métro… » dans une liste de révoltes récentes, c'est le soulèvement \
chilien d'octobre 2019, pas le Chili en général. Une image du pays, une vidéo touristique ou une photo sur le \
thème général ne servent à rien : le monteur veut des images de ce dont le texte parle.

Champs :
- nature : le type d'image qui illustre le mieux le paragraphe. carte (territoire, frontières, itinéraire, \
plan de ville ancien, expansion d'un empire), portrait (une personne), photo (événement photographié, après \
1850 environ), peinture ou gravure (événement ou scène d'avant la photo, ou représentation célèbre), document \
(texte, traité, affiche, une de journal, manuscrit), objet, lieu (bâtiment, paysage), archive vidéo (événement \
filmé : actualités, discours, reportage télé), rien (paragraphe abstrait).
- connues : 0 à 3 images précises et réputées que tu sais exister et qui montrent exactement le sujet : un \
tableau (titre, peintre), une photo célèbre (titre usuel, photographe), une carte (titre, cartographe, année), une \
affiche, une une de journal. title : son titre usuel, tel qu'il apparaît sur Wikimedia Commons ou dans un \
catalogue ; holder : où elle est conservée (musée, bibliothèque), vide si tu ne sais pas. N'invente rien : \
seulement des images dont tu es sûr qu'elles existent. C'est la meilleure piste, celle que suit un \
iconographe professionnel.
- wikipedia : 0 à 3 articles Wikipédia consacrés exactement à ce dont parle le paragraphe (l'événement, \
la personne, l'objet ; pas le pays ni le thème général), titre exact de l'article tel qu'il existe, langue 'en' \
ou 'fr' (celle où l'article est le plus complet). Inutile de répéter les articles déjà cités en lien.
- commons : 0 à 2 requêtes courtes en anglais pour Wikimedia Commons (sujet précis + lieu + année).
- archives : 0 à 2 requêtes courtes en anglais pour des catalogues de musées et bibliothèques (le Met, Europeana, \
la collection de cartes David Rumsey), avec le vocabulaire d'un catalogue : « map of Paris 1871 », « barricade \
Paris Commune photograph », « portrait of Louise Michel ».
- web : 0 à 2 requêtes de recherche d'images, précises (événement, lieu, date), dans la langue où le sujet est \
le mieux couvert.
- youtube : une requête YouTube dès qu'une vidéo peut servir : archive filmée, actualités d'époque, reportage, \
discours, interview, émission ou film annoncé par le texte (« extrait »), ou une vidéo qui montre le lieu, l'objet, \
le phénomène. Dans la langue où le sujet est le mieux couvert (le français pour un sujet français). Chaîne vide si \
le paragraphe est abstrait, ou si l'extrait annoncé est déjà un lien vidéo cité.
- visual : une phrase en anglais qui décrit ce qu'on voit sur l'image idéale (pour un modèle image-texte, \
ex. « protesters setting fire to a government building at night »), vide s'il n'y a rien de concret.

Un paragraphe abstrait (raisonnement, transition, aparté) sans rien de concret à montrer : nature « rien », tout \
le reste vide. Réponds pour chaque paragraphe à traiter, avec son id.

Si le vidéaste donne des consignes, elles priment : suis-les dans le choix de la nature, des images connues et de toutes les requêtes."""


def _with_brief(payload: dict, brief: str) -> dict:
    return {"consignes du vidéaste": brief.strip(), **payload} if brief.strip() else payload

_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["queries"], "properties": {
    "queries": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "nature", "connues", "wikipedia", "commons", "archives", "web", "youtube", "visual"],
        "properties": {
            "id": {"type": "integer"},
            "nature": {"type": "string", "enum": NATURES},
            "connues": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["title", "holder"],
                "properties": {"title": {"type": "string"}, "holder": {"type": "string"}}}},
            "wikipedia": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["lang", "title"],
                "properties": {"lang": {"type": "string", "enum": ["en", "fr"]}, "title": {"type": "string"}}}},
            "commons": {"type": "array", "items": {"type": "string"}},
            "archives": {"type": "array", "items": {"type": "string"}},
            "web": {"type": "array", "items": {"type": "string"}},
            "youtube": {"type": "string"},
            "visual": {"type": "string"}}}}}}

BATCH = 30      # paragraphs answered per request (the whole script is always sent, for context)


def _paragraph_payload(q: Query) -> dict:
    d = {"id": q.paragraph, "section": q.section, "texte": q.text}
    if q.links:
        d["liens"] = [f"{anchor} -> {url}" for anchor, url in q.links]
    return d


def _clean(xs, n: int) -> list[str]:
    return [x.strip() for x in xs or [] if isinstance(x, str) and x.strip()][:n]


def _apply(queries: list[Query], answers: list[dict], by: str) -> int:
    by_id = {a.get("id"): a for a in answers}
    n = 0
    for q in queries:
        a = by_id.get(q.paragraph)
        if not a:
            continue
        cited = {(lang, _fold(t)) for lang, t in q.cited_wiki}
        q.wiki = [(w["lang"], w["title"].strip()) for w in a.get("wikipedia", [])
                  if w.get("title", "").strip() and (w.get("lang"), _fold(w["title"].strip())) not in cited][:3]
        q.wiki_search = None
        q.en = _clean(a.get("commons"), 2)
        q.fr = []
        q.web = _clean(a.get("web"), 2)
        q.archives = _clean(a.get("archives"), 2)
        q.known = [(k["title"].strip(), (k.get("holder") or "").strip()) for k in a.get("connues") or []
                   if isinstance(k, dict) and (k.get("title") or "").strip()][:3]
        q.nature = a.get("nature") or ""
        q.visual = (a.get("visual") or "").strip()
        yt = (a.get("youtube") or "").strip()
        q.video = None if q.video_covered else (yt or (q.video if q.extract_note else None))
        q.by = by
        n += 1
    return n


def _plan(provider: str, queries: list[Query], title: str, log, brief: str = "") -> int:
    """Whole script as context in every request, answers asked for BATCH paragraphs at a time."""
    from concurrent.futures import ThreadPoolExecutor

    from . import llm
    script = [_paragraph_payload(q) for q in queries]
    batches = [queries[i:i + BATCH] for i in range(0, len(queries), BATCH)]

    def one(batch: list[Query]) -> int:
        content = [json.dumps(_with_brief({"script": title, "paragraphes": script,
                                           "à traiter": [q.paragraph for q in batch]}, brief), ensure_ascii=False)]
        answer = llm.ask(provider, LLM_INSTRUCTIONS, content, _SCHEMA)
        return _apply(batch, answer.get("queries", []), llm.ENGINES[provider]["label"])

    done, errors = 0, []
    with ThreadPoolExecutor(2 if llm.ENGINES[provider].get("exe") else 4) as ex:
        for f in [ex.submit(one, b) for b in batches]:
            try:
                done += f.result()
            except Exception as e:
                errors.append(e)
    if errors and not done:
        raise errors[0]
    if errors:
        log(f"  {len(errors)} lot(s) sans réponse ({type(errors[0]).__name__}: {str(errors[0])[:100]})")
    return done


def _ollama(queries: list[Query], model: str, title: str, brief: str = "") -> int:
    """One paragraph at a time (small local models lose track of long inputs), neighbours as context."""
    from . import llm
    done = 0
    for i, q in enumerate(queries):
        around = [_paragraph_payload(x) for x in queries[max(0, i - 2):i + 2] if x is not q]
        try:
            answer = llm.ollama_json(LLM_INSTRUCTIONS, [json.dumps(_with_brief(
                {"script": title, "contexte": around, "paragraphes": [_paragraph_payload(q)],
                 "à traiter": [q.paragraph]}, brief), ensure_ascii=False)], _SCHEMA, model=model)
            done += _apply([q], answer.get("queries", []), "Ollama")
        except Exception:
            pass
    return done


def llm_queries(queries: list[Query], mode: str, log=print, title: str = "",
                brief: str = "") -> tuple[str, str | None]:
    """Rewrite the heuristic queries with an AI engine. mode: auto, off, or an engine of llm.ENGINES.
    Returns (what was used, the engine that can also look at the pictures, or None)."""
    from . import llm
    for engine in llm.candidates(mode):
        try:
            if engine == "ollama":
                model = llm.ollama_available()
                log(f"  requêtes : Ollama ({model})")
                n = _ollama(queries, model, title, brief)
                return f"Ollama {model} ({n}/{len(queries)})", None
            log(f"  requêtes : {llm.label(engine)}, {len(queries)} paragraphes…")
            n = _plan(engine, queries, title, log, brief)
            log(f"  requêtes : {llm.label(engine)} ({n}/{len(queries)} paragraphes)")
            return llm.label(engine), engine if llm.ENGINES[engine]["vision"] else None
        except Exception as e:
            log(f"  {llm.label(engine)} indisponible ({type(e).__name__}: {str(e)[:160]})")
    if mode not in ("off", "auto") and not llm.available(mode):
        log(f"  {llm.label(mode)} : pas connecté (page IA de la fenêtre)")
    return "heuristique", None


# --- Looking at the pictures: the vision model drops what is off-topic -------------------------------

JUDGE_INSTRUCTIONS = """Tu es documentaliste iconographe pour un documentaire. Tu reçois un paragraphe du script \
et des images candidates numérotées, chacune avec son titre et sa source. Note chaque image de 0 à 10 selon \
qu'elle peut illustrer CE paragraphe à l'écran :
- 9-10 : montre exactement ce dont le texte parle (l'événement, la personne, le lieu, la carte de l'époque), \
image d'archive ou document authentique, bonne qualité ;
- 6-8 : pertinente et utilisable ;
- 3-5 : vaguement liée (le thème général, le pays, une autre époque) ;
- 0-2 : hors sujet, illustration générique ou décorative, logo, schéma sans rapport, image d'un autre lieu ou \
d'une autre époque, montage racoleur, mème, image floue ou minuscule, page de texte illisible.
Une vidéo est jugée sur sa miniature, son titre et sa chaîne : une archive, des actualités, un reportage, une \
émission ou un discours sur le sujet sont bons ; un vlog, une réaction, une vidéo d'opinion face caméra ou sur \
un autre sujet sont hors sujet.
Si le vidéaste donne des consignes, note aussi selon elles : une image qui ne les suit pas perd des points.
why : quelques mots en français (ce que montre l'image, pourquoi elle convient ou non)."""

_JUDGE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["verdicts"], "properties": {
    "verdicts": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["n", "score", "why"],
        "properties": {"n": {"type": "integer"}, "score": {"type": "integer", "minimum": 0, "maximum": 10},
                       "why": {"type": "string"}}}}}}

JUDGE_POOL = 24         # images shown to the vision model per paragraph (plus the videos)
JUDGE_MIN = 5           # below this, the candidate is dropped


def judge(provider: str, q: Query, items: list[tuple[Asset, object]], title: str = "",
          brief: str = "") -> dict[int, tuple[int, str]]:
    """{index in items: (score 0-10, why)} for the items whose picture could be shown to the model."""
    from . import llm
    content = [(f"Consignes du vidéaste : {brief.strip()}\n" if brief.strip() else "") +
               f"Script : {title}\nSection : {q.section}\nParagraphe : {q.text}" +
               (f"\nImage idéale : {q.visual}" if q.visual else "")]
    shown = []
    for i, (a, im) in enumerate(items):
        if im is None:
            continue
        n = len(shown) + 1
        src = a.via + (f", {a.author}" if a.author else "")
        desc = (f"vidéo YouTube, {a.title} — chaîne {a.author or '?'}, {int(a.duration // 60)} min"
                if a.kind == "video" else f"{a.title} — {src}")
        content += [f"Image {n} : {desc[:240]}", llm.jpeg(im, 448)]
        shown.append(i)
    if not shown:
        return {}
    answer = llm.ask(provider, JUDGE_INSTRUCTIONS, content, _JUDGE_SCHEMA, effort="low")
    out = {}
    for v in answer.get("verdicts", []):
        k = v.get("n", 0) - 1
        if 0 <= k < len(shown):
            out[shown[k]] = (max(0, min(10, int(v.get("score", 0)))), (v.get("why") or "").strip()[:160])
    return out


# --- Sources ------------------------------------------------------------------------------------

def _strip(s: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


_II = {"prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 480,
       "iiextmetadatafilter": "LicenseShortName|LicenseUrl|Artist|Credit|ImageDescription|ObjectName"}


def _commons_pages(data: dict, origin_note: str = "") -> list[tuple[Asset, str]]:
    out = []
    for pg in data.get("query", {}).get("pages", []):
        ii = (pg.get("imageinfo") or [None])[0]
        if not ii or max(ii.get("width", 0), ii.get("height", 0)) < 800:
            continue
        mime = ii.get("mime", "")
        if not mime.startswith("image/"):
            continue
        md = {k: _strip(v.get("value", "")) for k, v in ii.get("extmetadata", {}).items()}
        title = md.get("ObjectName") or pg["title"].split(":", 1)[1].rsplit(".", 1)[0]
        lic = md.get("LicenseShortName", "")
        kind = "svg" if "svg" in mime else ("tiff" if "tif" in mime else "")
        a = Asset(id="", kind="image", via="commons", origin="recherche", sentence=-1, paragraph=-1, url=ii["url"],
                  thumb=ii.get("thumburl", ""), source_page=ii.get("descriptionurl", ""), title=title[:120],
                  author=md.get("Artist", "")[:120], licence=lic, licence_url=md.get("LicenseUrl", ""),
                  credit=md.get("Credit", "")[:200], rights=rights_for(lic or None), width=ii.get("width", 0),
                  height=ii.get("height", 0), note=" · ".join(x for x in (kind, origin_note) if x))
        out.append((a, f"{title}. {md.get('ImageDescription', '')[:300]}"))
    return out


def commons(ctx: Ctx, q: str, n: int = 12) -> list[tuple[Asset, str]]:
    data = ctx.fetch.json("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "format": "json", "formatversion": 2, "generator": "search",
        "gsrsearch": f"{q} filetype:bitmap|drawing", "gsrnamespace": 6, "gsrlimit": n, **_II})
    return _commons_pages(data)


def resolve_wiki(ctx: Ctx, lang: str, title: str) -> str | None:
    """The real title of an article an LLM named (redirects followed), or the closest search hit."""
    api = f"https://{lang}.wikipedia.org/w/api.php"
    data = ctx.fetch.json(api, {"action": "query", "format": "json", "formatversion": 2, "titles": title,
                                "redirects": 1})
    page = (data.get("query", {}).get("pages") or [{}])[0]
    if page.get("pageid") and not page.get("missing"):
        return page["title"]
    hits = ctx.fetch.json(api, {"action": "query", "format": "json", "formatversion": 2, "list": "search",
                                "srsearch": title, "srlimit": 3}).get("query", {}).get("search", [])
    if not hits:
        return None
    sims = embed.similarity(title, [h["title"] for h in hits])
    best = int(sims.argmax())
    return hits[best]["title"] if sims[best] >= 0.6 else None


def search_wiki(ctx: Ctx, lang: str, text: str) -> str | None:
    hits = ctx.fetch.json(f"https://{lang}.wikipedia.org/w/api.php", {
        "action": "query", "format": "json", "formatversion": 2, "list": "search", "srsearch": text,
        "srlimit": 1}).get("query", {}).get("search", [])
    return hits[0]["title"] if hits else None


def wiki_article(ctx: Ctx, lang: str, title: str) -> list[tuple[Asset, str, float]]:
    url = f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
    return [(replace(c.asset, origin="recherche", note=f"article : {title}"), c.text, 0.25 + c.prior)
            for c in wikipedia(ctx, url)]


def wiki_qid(ctx: Ctx, lang: str, title: str) -> str | None:
    data = ctx.fetch.json(f"https://{lang}.wikipedia.org/w/api.php", {
        "action": "query", "format": "json", "formatversion": 2, "titles": title, "redirects": 1,
        "prop": "pageprops", "ppprop": "wikibase_item"})
    return ((data.get("query", {}).get("pages") or [{}])[0].get("pageprops") or {}).get("wikibase_item")


def commons_depicts(ctx: Ctx, lang: str, title: str, n: int = 30) -> list[tuple[Asset, str]]:
    """Commons files whose structured data says they depict the article's subject (P180 = its Wikidata
    item): tagged by people, so far more precise than words in a file name."""
    qid = wiki_qid(ctx, lang, title)
    if not qid:
        return []
    data = ctx.fetch.json("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "format": "json", "formatversion": 2, "generator": "search",
        "gsrsearch": f"haswbstatement:P180={qid} filetype:bitmap|drawing", "gsrnamespace": 6, "gsrlimit": n, **_II})
    return _commons_pages(data, f"représente : {title}")


def commons_category(ctx: Ctx, lang: str, title: str, n: int = 40) -> list[tuple[Asset, str]]:
    """Photos filed under the article's Commons category (Wikidata P373): the event's own pictures."""
    qid = wiki_qid(ctx, lang, title)
    if not qid:
        return []
    claims = ctx.fetch.json("https://www.wikidata.org/w/api.php", {
        "action": "wbgetclaims", "format": "json", "entity": qid, "property": "P373"}).get("claims", {})
    cats = [c["mainsnak"]["datavalue"]["value"] for c in claims.get("P373", []) if "datavalue" in c["mainsnak"]]
    if not cats:
        return []
    data = ctx.fetch.json("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "format": "json", "formatversion": 2, "generator": "categorymembers",
        "gcmtitle": f"Category:{cats[0]}", "gcmtype": "file", "gcmlimit": n, **_II})
    return _commons_pages(data, f"catégorie Commons : {cats[0]}")


def rumsey(ctx: Ctx, q: str, n: int = 12) -> list[tuple[Asset, str]]:
    """David Rumsey Map Collection (LUNA search, JSON): 150 000+ historical maps in high resolution."""
    data = ctx.fetch.json("https://www.davidrumsey.com/luna/servlet/as/search",
                          {"q": q, "lc": "RUMSEY~8~1", "os": 0, "bs": n})
    out = []
    for r in data.get("results") or []:
        if r.get("mediaType") != "Image" or not r.get("urlSize4"):
            continue
        f = {k: v[0] for fv in r.get("fieldValues") or [] for k, v in fv.items() if v}
        title = f.get("Full Title") or f.get("Short Title") or r.get("displayName", "")
        date = f.get("Date") or f.get("Pub Date") or ""
        m = re.search(r"width%3D(\d+)%26height%3D(\d+)", r.get("relayButtonUrl", ""))
        w, h = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        scale = 4000 / max(w, h, 1)        # Size4 is about 4000 px on its long side
        a = Asset(id="", kind="image", via="rumsey", origin="recherche", sentence=-1, paragraph=-1,
                  url=r["urlSize4"], thumb=r.get("urlSize2") or r["urlSize4"],
                  source_page=f"https://www.davidrumsey.com/luna/servlet/detail/{r.get('id', '')}",
                  title=f"{title} ({date})"[:120] if date else title[:120], author=f.get("Author", "")[:120],
                  licence="CC BY-NC-SA 3.0", licence_url="https://creativecommons.org/licenses/by-nc-sa/3.0/",
                  credit="David Rumsey Map Collection, David Rumsey Map Center, Stanford Libraries",
                  rights=CHECK, width=round(w * min(1, scale)), height=round(h * min(1, scale)),
                  note="carte ancienne (usage commercial : à demander)")
        out.append((a, f"{title}. {date}. {f.get('Type', '')}. {f.get('Note', '')[:200]}"))
    return out


def met(ctx: Ctx, q: str, n: int = 8) -> list[tuple[Asset, str]]:
    """The Metropolitan Museum's Open Access (public domain: paintings, prints, photographs)."""
    api = "https://collectionapi.metmuseum.org/public/collection"
    ids = ctx.fetch.json(f"{api}/v1.1/search", {"q": q, "hasImages": "true", "limit": n}).get("objectIDs") or []
    from concurrent.futures import ThreadPoolExecutor

    def obj(oid):
        try:
            return ctx.fetch.json(f"{api}/v1/objects/{oid}")
        except Exception:
            return {}
    out = []
    with ThreadPoolExecutor(4) as ex:
        objects = list(ex.map(obj, ids[:n]))
    for o in objects:
        if not o.get("isPublicDomain") or not o.get("primaryImage"):
            continue
        title = o.get("title") or o.get("objectName") or ""
        date = o.get("objectDate") or ""
        a = Asset(id="", kind="image", via="met", origin="recherche", sentence=-1, paragraph=-1,
                  url=o["primaryImage"], thumb=o.get("primaryImageSmall") or o["primaryImage"],
                  source_page=o.get("objectURL", ""), title=(f"{title} ({date})" if date else title)[:120],
                  author=(o.get("artistDisplayName") or "")[:120], licence="CC0 (Met Open Access)",
                  licence_url="https://creativecommons.org/publicdomain/zero/1.0/",
                  credit="The Metropolitan Museum of Art", rights=FREE)
        out.append((a, f"{title}. {date}. {o.get('objectName', '')}. {o.get('medium', '')}"))
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
# Video thumbnails and social reposts: a still from someone else's video, never the event itself.
_NOT_A_PHOTO = re.compile(r"ytimg\.com|youtube\.com|youtu\.be|tiktok|dailymotion\.com/thumbnail|vimeocdn|"
                          r"pinimg\.com|pinterest\.|fbcdn\.net|instagram\.", re.I)


def ddg_images(ctx: Ctx, q: str, n: int = 20) -> list[tuple[Asset, str]]:
    if _ddg_state["off"]:
        return []
    from ddgs import DDGS
    with _ddg_lock:
        wait = _ddg_state["last"] + 2.0 - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            results = DDGS().images(q, region="wt-wt", safesearch="moderate", size="Large", max_results=n)
        except Exception as e:
            _ddg_state["off"] = True
            ctx.errors.append({"url": "duckduckgo", "error": f"recherche DuckDuckGo arrêtée : {str(e)[:120]}"})
            return []
        finally:
            _ddg_state["last"] = time.monotonic()
    out = []
    for r in results:
        w, h = int(r.get("width") or 0), int(r.get("height") or 0)
        page, title = r.get("url", ""), r.get("title") or ""
        if max(w, h) < 1000 or _NOT_A_PHOTO.search(r.get("image", "") + " " + page) or \
                re.search(r"[-|]\s*YouTube\s*$", title):
            continue
        stock = _STOCK.search(r.get("image", "") + " " + page)
        a = Asset(id="", kind="image", via="web", origin="recherche", sentence=-1, paragraph=-1, url=r["image"],
                  thumb=r.get("thumbnail") or r["image"], source_page=page, title=title[:120],
                  author=r.get("source") or urlparse(page).netloc, rights=PROTECTED if stock else CHECK,
                  width=w, height=h, note="banque d'images / agence" if stock else "licence inconnue (recherche web)")
        out.append((a, a.title))
    return out


def youtube(ctx: Ctx, q: str, n: int = 10) -> list[tuple[Asset, str]]:
    """All of YouTube, search results only (title, channel, length, thumbnail): nothing is downloaded until
    the video is ticked on the contact sheet and exported."""
    import yt_dlp

    from .collect import _Quiet
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True, "logger": _Quiet()}) as y:
        res = y.extract_info(f"ytsearch{n}:{q}", download=False)
    out = []
    for e in res.get("entries") or []:
        vid = e.get("id")
        duration = float(e.get("duration") or 0)
        if not vid or e.get("live_status") in ("is_live", "is_upcoming") or (duration and duration < 8):
            continue
        a = Asset(id="", kind="video", via="youtube", origin="recherche", sentence=-1, paragraph=-1,
                  url=f"https://www.youtube.com/watch?v={vid}", thumb=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                  source_page=f"https://www.youtube.com/watch?v={vid}", title=(e.get("title") or "")[:120],
                  author=e.get("channel") or e.get("uploader") or "", rights=QUOTE, duration=duration)
        out.append((a, a.title))
    return out


def _video_details(ctx: Ctx, a: Asset, query_text: str) -> Asset:
    """Best resolution and, for a long video, the minute that matches the paragraph (from its captions)."""
    try:
        (c,) = video(ctx, a.url, query_text)
    except Exception:
        return a
    return replace(c.asset, via="youtube", origin="recherche")


# --- Ranking ------------------------------------------------------------------------------------

CLIP_POOL = 32          # best candidates (by text) whose thumbnails are looked at
CLIP_NEUTRAL = 0.22     # CLIP similarity that counts as neither for nor against
CLIP_WEIGHT = 2.5
MAX_VIDEOS = 4          # videos kept per paragraph


def _thumb_image(ctx: Ctx, url: str):
    import io

    from PIL import Image
    if not url.startswith("http"):
        return None
    try:
        r = ctx.fetch.get(url, timeout=20)
        if not r.ok or "html" in r.headers.get("content-type", ""):
            return None
        im = Image.open(io.BytesIO(r.content))
        im.thumbnail((448, 448))
        return im.convert("RGB")
    except Exception:
        return None


def search_paragraph(ctx: Ctx, q: Query, keep: int, videos: bool, web: bool, clip: bool = True,
                     judge_with: str | None = None, title: str = "", brief: str = "") -> list[Asset]:
    from concurrent.futures import ThreadPoolExecutor
    found: list[tuple[Asset, str, float]] = []    # asset, text describing it, source confidence
    jobs: list[tuple] = []

    def run(fn, *args, prior=0.0):
        jobs.append((fn, args, prior))

    def call(job):
        fn, args, prior = job
        try:
            return [x if len(x) == 3 else (*x, prior) for x in fn(ctx, *args)]
        except Exception as e:
            ctx.errors.append({"url": f"{fn.__name__}: {' '.join(map(str, args))}"[:200], "error": str(e)[:150]})
            return []

    # 1. Articles about the subject, the photos filed with them and the files that depict their subject
    articles = []
    for lang, wt in q.wiki:
        try:
            real = resolve_wiki(ctx, lang, wt)
        except Exception:
            real = None
        if real:
            articles.append((lang, real))
    if q.wiki_search and not articles:
        for lang in ("fr", "en"):
            try:
                hit = search_wiki(ctx, lang, q.wiki_search)
            except Exception:
                hit = None
            if hit:
                articles.append((lang, hit))
                break
    cited = {(lang, _fold(t)) for lang, t in q.cited_wiki}
    for lang, wt in dict.fromkeys(articles):
        if (lang, _fold(wt)) not in cited:      # cited articles are already harvested as links
            run(wiki_article, lang, wt)
        run(commons_category, lang, wt, prior=0.2)
        run(commons_depicts, lang, wt, prior=0.2)
    for lang, wt in q.cited_wiki[:2]:
        run(commons_category, lang, wt, prior=0.15)
        run(commons_depicts, lang, wt, prior=0.15)
    # 2. The famous pictures the model named
    for name, holder in q.known:
        run(commons, name, 6, prior=0.25)
        if web:
            run(ddg_images, f"{name} {holder}".strip(), 10, prior=0.15)
    # 3. Searches, sent where that kind of picture lives
    for x in q.en[:2] + q.fr[:1]:
        run(commons, x)
    for x in (q.archives or q.en or q.fr)[:1]:
        run(europeana, x)
    if q.nature == "carte":
        for x in (q.archives or q.en)[:2]:
            run(rumsey, x, prior=0.1)
    elif q.nature in ("peinture", "gravure", "portrait", "photo", "objet", "document"):
        for x in q.archives[:1]:
            run(met, x)
    if web:
        for x in q.web[:2]:
            run(ddg_images, x)
    if q.video and videos:
        run(youtube, q.video)
    with ThreadPoolExecutor(6) as ex:
        for res in ex.map(call, jobs):          # in order: the same candidates come first on every run
            found.extend(res)
    vids = [(a, text) for a, text, _ in found if a.via == "youtube"]       # only youtube() gives these
    found = [x for x in found if x[0].via != "youtube"]

    seen, unique = set(), []
    for a, text, prior in found:
        if a.url not in seen:
            seen.add(a.url)
            unique.append((a, text, prior))
    if not unique and not vids:
        return []
    ranked = []      # [score, asset, clip match, thumbnail]
    if unique:
        sims = embed.similarity(q.text, [t for _, t, _ in unique])
        for (a, _, prior), sim in zip(unique, sims):
            bonus = {"libre": 0.1, "protégé": -0.25}.get(a.rights, 0) + 0.05 * min(1.0, max(a.width, a.height) / 3000)
            ranked.append([float(sim) + prior + bonus, a, None, None])
        ranked.sort(key=lambda x: -x[0])

    # 4. What the pictures show: CLIP on the thumbnails of the best candidates
    look = q.visual or (" ".join(q.en) if q.by != "heuristique" else "")
    pool = ranked[:max(CLIP_POOL, JUDGE_POOL)] if (clip or judge_with) else []
    with ThreadPoolExecutor(8) as ex:
        for r, im in zip(pool, ex.map(lambda r: _thumb_image(ctx, r[1].thumb), pool)):
            r[3] = im
    if clip and look and pool:
        try:
            matches = embed.image_match(look, [r[3] for r in pool])
        except Exception as e:
            ctx.errors.append({"url": "clip", "error": f"classement par l'image impossible : {str(e)[:120]}"})
            matches = [float("nan")] * len(pool)
        for r, m in zip(pool, matches):
            if m == m:          # not nan
                r[0] += CLIP_WEIGHT * (float(m) - CLIP_NEUTRAL)
                r[2] = float(m)
        ranked.sort(key=lambda x: -x[0])

    vranked = []     # [score, asset, verdict]
    if vids:
        vsims = embed.similarity(q.text, [t for _, t in vids])
        vranked = sorted(([float(s), v, None] for (v, _), s in zip(vids, vsims)), key=lambda x: -x[0])

    # 5. A vision model looks at the best pictures and the video thumbnails, and drops what is off-topic
    verdicts: dict[int, tuple[int, str]] = {}
    judged = False
    if judge_with:
        images = [r for r in ranked[:JUDGE_POOL]]
        with ThreadPoolExecutor(8) as ex:
            for v, im in zip(vranked[:10], ex.map(lambda v: _thumb_image(ctx, v[1].thumb), vranked[:10])):
                v.append(im)
        items = [(r[1], r[3]) for r in images] + [(v[1], v[3]) for v in vranked[:10]]
        try:
            verdicts = judge(judge_with, q, items, title, brief)
            judged = bool(verdicts)
        except Exception as e:
            ctx.errors.append({"url": f"tri par l'IA, paragraphe {q.paragraph}",
                               "error": f"{type(e).__name__}: {str(e)[:150]}"})
    if judged:
        n_img = len(images)
        kept = []
        for i, r in enumerate(images):
            if i in verdicts:
                score, why = verdicts[i]
                if score >= JUDGE_MIN:
                    r[0] = score + 0.3 * r[0]          # the verdict decides, the earlier score breaks ties
                    r[2] = (score, why)
                    kept.append(r)
        ranked = sorted(kept, key=lambda x: -x[0])
        vkept = []
        for j, v in enumerate(vranked[:10]):
            if n_img + j in verdicts:
                score, why = verdicts[n_img + j]
                if score >= JUDGE_MIN:
                    v[0], v[2] = score + 0.3 * v[0], (score, why)
                    vkept.append(v)
        vranked = sorted(vkept, key=lambda x: -x[0])
    else:
        vranked = [v for v in vranked if v[0] >= 0.25]
    vranked = vranked[:MAX_VIDEOS if judged else 3]

    asked = " / ".join(q.web[:1] + q.en[:1] + [t for _, t in articles[:1]]) or next(iter(q.fr), "")
    with ThreadPoolExecutor(4) as ex:
        details = list(ex.map(lambda v: _video_details(ctx, v[1], q.text), vranked))
    out = []
    for score, a, m, *_ in ranked[:keep] + [[v[0], d, v[2]] for v, d in zip(vranked, details)]:
        a = replace(a, sentence=q.sentence, paragraph=q.paragraph, score=round(score, 3))
        a.id = Asset.make_id(a.via, a.url, q.paragraph)
        bits = [a.note] if a.note else []
        if isinstance(m, tuple):
            bits.append(f"IA : {m[0]}/10 — {m[1]}" if m[1] else f"IA : {m[0]}/10")
        bits.append(f"requête ({q.by}) : " + ((q.video or "") if a.kind == "video" else asked))
        if isinstance(m, float):
            bits.append(f"image ≈ texte : {m:.2f}")
        a.note = " · ".join(bits)
        out.append(a)
    return out
