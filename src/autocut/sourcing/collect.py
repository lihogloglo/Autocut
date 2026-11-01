"""Collectors for cited links: what each kind of page can give.

Each collector harvests one URL once and returns candidates (asset, text describing it, prior);
`rank_for` then picks the best ones for every sentence that cites the URL."""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bs4 import BeautifulSoup
from PIL import Image

from . import embed
from .fetch import Fetcher
from .model import CHECK, FREE, PROTECTED, QUOTE, Asset, agency, rights_for
from .script import Link, ScriptSentence

VIDEO_HOSTS = re.compile(r"(youtube\.com|youtu\.be|dailymotion\.com|dai\.ly|vimeo\.com|facebook\.com/(watch|.*/videos)|"
                         r"fb\.watch|tiktok\.com|twitch\.tv|ina\.fr|francetv|arte\.tv|x\.com/.*/status|"
                         r"twitter\.com/.*/status|reddit\.com/r/|v\.redd\.it|instagram\.com/(reel|p)/)")
NO_SCREENSHOT = re.compile(r"(youtube\.com|youtu\.be|dailymotion\.com|vimeo\.com|facebook\.com/watch|fb\.watch|"
                           r"tiktok\.com|\.(pdf|jpe?g|png|gif|webp|svg|mp4)(\?|$))", re.I)
_WIKI_SKIP = re.compile(r"icon|logo|symbol|pictogram|picto|ambox|question.book|edit-|wiki(source|quote|media|data|"
                        r"tionary|books|news|versity|voyage|species)|commons-|padlock|crystal|nuvola|disambig|"
                        r"portal|flag_of|blank|arrow|loudspeaker|speaker|audio|\.(ogg|oga|wav|mp3|webm|ogv)$|"
                        r"red_pog|location_dot|_dot\.svg|transparent|placeholder|signature", re.I)
_IMG_SKIP = re.compile(r"logo|icon|avatar|sprite|pixel|tracking|favicon|badge|banner-pub|emoji|gravatar|"
                       r"spacer|blank\.|placeholder|\.svg(\?|$)|/ads?/|doubleclick|data:image", re.I)
_WP_SIZE = re.compile(r"-\d{2,4}x\d{2,4}(?=\.(jpe?g|png|webp)$)", re.I)


@dataclass
class Ctx:
    fetch: Fetcher
    out: Path                      # output folder (manifest, renders, thumbs)
    seg_len: float = 30.0          # default excerpt length, seconds
    full_video_max: float = 600.0  # whole video when not longer than this (seconds)
    per_link: int = 10             # candidates kept per sentence and link
    errors: list[dict] = field(default_factory=list)

    def rel(self, path: Path) -> str:
        return path.relative_to(self.out).as_posix()


@dataclass
class Cand:
    asset: Asset
    text: str = ""       # what the image shows (caption, alt, description) for ranking
    prior: float = 0.0   # collector confidence: lead image, inside the cited section, ...
    sentence: int | None = None   # chosen for one specific citing sentence only


def _strip_html(s: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", s or "").split())


def thumb(ctx: Ctx, src: Path, width: int = 480) -> str:
    """JPEG preview next to the contact sheet, path relative to the output folder."""
    dst = ctx.out / "thumbs" / (src.stem + ".jpg")
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail((width, width * 3))
            im.save(dst, quality=82)
    return ctx.rel(dst)


def image_size(ctx: Ctx, url: str) -> tuple[int, int] | None:
    for limit in (65536, 524288):
        try:
            r = ctx.fetch.get(url, max_bytes=limit, timeout=15)
            if not r.ok or "html" in r.headers.get("content-type", ""):
                return None
            with Image.open(io.BytesIO(r.content)) as im:
                return im.size
        except Exception:
            continue
    return None


# --- Wikipedia ----------------------------------------------------------------------------------

def wikipedia(ctx: Ctx, url: str) -> list[Cand]:
    p = urlparse(url)
    title = unquote(p.path.split("/wiki/", 1)[1])
    frag = unquote(p.fragment).replace(" ", "_") if p.fragment else None
    api = f"https://{p.netloc}/w/api.php"
    base = {"format": "json", "formatversion": 2, "redirects": 1}
    page = ctx.fetch.json(api, {**base, "action": "parse", "page": title, "prop": "images|sections|displaytitle"})
    if "error" in page:
        raise RuntimeError(page["error"].get("info", "page introuvable"))
    page = page["parse"]
    order = page["images"]
    in_section: set[str] = set()
    if frag:
        sec = next((s for s in page["sections"] if s["anchor"] == frag), None)
        if sec and str(sec.get("index", "")).isdigit():
            part = ctx.fetch.json(api, {**base, "action": "parse", "page": title, "prop": "images",
                                        "section": sec["index"]})
            in_section = set(part.get("parse", {}).get("images", []))
    names = [n for n in order if not _WIKI_SKIP.search(n)]
    cands: list[Cand] = []
    for i in range(0, len(names), 50):
        chunk = names[i:i + 50]
        info = ctx.fetch.json(api, {**base, "action": "query", "titles": "|".join("File:" + n for n in chunk),
                                    "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
                                    "iiurlwidth": 480, "iiextmetadatafilter":
                                    "LicenseShortName|LicenseUrl|Artist|Credit|ImageDescription|ObjectName"})
        for pg in info.get("query", {}).get("pages", []):
            ii = (pg.get("imageinfo") or [None])[0]
            if not ii:
                continue
            mime = ii.get("mime", "")
            w, h = ii.get("width", 0), ii.get("height", 0)
            if not mime.startswith("image/") or (mime != "image/svg+xml" and max(w, h) < 500):
                continue
            md = {k: _strip_html(v.get("value", "")) for k, v in ii.get("extmetadata", {}).items()}
            name = pg["title"].split(":", 1)[1].replace(" ", "_")
            pos = names.index(name) if name in names else len(names)
            desc = md.get("ImageDescription", "")[:400]
            obj = md.get("ObjectName", "") or name.rsplit(".", 1)[0].replace("_", " ")
            licence = md.get("LicenseShortName", "")
            a = Asset(id="", kind="image", via="wikipedia", origin="lien", sentence=-1, paragraph=-1,
                      url=ii["url"], thumb=ii.get("thumburl", ii["url"]), source_page=ii.get("descriptionurl", ""),
                      title=obj[:120], author=md.get("Artist", "")[:120], licence=licence,
                      licence_url=md.get("LicenseUrl", ""), credit=md.get("Credit", "")[:200],
                      rights=rights_for(licence or None), width=w, height=h,
                      note="svg" if mime == "image/svg+xml" else ("tiff" if "tif" in mime else ""))
            prior = 0.15 * (1 - pos / max(len(names), 1)) + (0.35 if name in in_section else 0)
            prior += 0.1 * min(1.0, max(w, h) / 3000)
            cands.append(Cand(a, f"{obj}. {desc}", prior))
    return cands


# --- Ordinary web pages -------------------------------------------------------------------------

def _best_src(img) -> str | None:
    best, best_w = None, -1.0
    for attr in ("srcset", "data-srcset", "data-lazy-srcset"):
        for part in (img.get(attr) or "").split(","):
            bits = part.strip().split()
            if not bits:
                continue
            w = float(re.sub(r"[^\d.]", "", bits[1]) or 0) if len(bits) > 1 else 0
            if w > best_w:
                best, best_w = bits[0], w
    return best or img.get("data-src") or img.get("data-lazy-src") or img.get("data-original") or img.get("src")


def _bigger(url: str) -> list[str]:
    """Likely full-size variants of a resized image URL, best first."""
    out = []
    if _WP_SIZE.search(url):
        out.append(_WP_SIZE.sub("", url))
    q = re.sub(r"([?&])(w|width|h|height|resize|fit|quality|q)=[^&]*", r"\1", url).rstrip("?&")
    if q != url:
        out.append(q)
    return out + [url]


def html_page(ctx: Ctx, url: str, resp) -> tuple[list[Cand], list[str]]:
    """Images of an article (+ embedded videos to follow)."""
    soup = BeautifulSoup(resp.text, "lxml")
    base = resp.url
    page_title = ""
    meta = {}
    for m in soup.find_all("meta"):
        k = (m.get("property") or m.get("name") or "").lower()
        if k and m.get("content"):
            meta.setdefault(k, m["content"])
    page_title = meta.get("og:title") or (soup.title.string.strip() if soup.title and soup.title.string else "")
    author = meta.get("author") or meta.get("article:author") or ""
    site = meta.get("og:site_name") or urlparse(base).netloc
    page_licence = ""
    lic = soup.find("a", rel="license") or soup.find("link", rel="license")
    if lic and lic.get("href"):
        page_licence = lic["href"]
    text = soup.get_text(" ", strip=True)
    page_agencies = sorted({m.group(0) for m in re.finditer(r"\b(AFP|Reuters|Getty|AP|EPA|Sipa|Abaca|MaxPPP)\b",
                                                             text)})

    found: dict[str, tuple[str, str, float]] = {}   # src -> (caption/alt, credit, prior)

    def add(src, caption="", credit="", prior=0.0):
        if not src:
            return
        src = urljoin(base, src.strip())
        if _IMG_SKIP.search(src) or not src.startswith("http"):
            return
        if src not in found:
            found[src] = (caption, credit, prior)

    for k in ("og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src"):
        if meta.get(k):
            add(meta[k], page_title, "", 0.2)
    for s in soup.find_all("script", type="application/ld+json"):
        for u in re.findall(r'"(?:url|contentUrl)"\s*:\s*"([^"]+\.(?:jpe?g|png|webp)[^"]*)"', s.string or ""):
            add(u.replace("\\/", "/"), page_title, "", 0.15)
    for img in soup.find_all("img"):
        fig = img.find_parent("figure")
        caption = fig.get_text(" ", strip=True)[:300] if fig else ""
        credit_el = fig.find(class_=re.compile("credit|copyright|source|author", re.I)) if fig else None
        credit = credit_el.get_text(" ", strip=True) if credit_el else ""
        add(_best_src(img), caption or img.get("alt") or img.get("title") or "", credit or caption, 0.05 if fig else 0)

    cands = []
    for src, (caption, credit, prior) in list(found.items())[:20]:
        size, full = None, src
        for variant in _bigger(src):
            size = image_size(ctx, variant)
            if size:
                full = variant
                break
        if not size or max(size) < 500 or min(size) < 200:
            continue
        ag = agency(credit) or agency(caption)
        licence = page_licence if "creativecommons" in page_licence else ""
        rights = PROTECTED if ag else rights_for(licence or None)
        note = f"agences citées sur la page : {', '.join(page_agencies)}" if not ag and page_agencies else ""
        a = Asset(id="", kind="image", via="page", origin="lien", sentence=-1, paragraph=-1, url=full, thumb=src,
                  source_page=url, title=(caption or page_title)[:120], author=ag or author or site,
                  licence=licence, credit=credit[:200], rights=rights, width=size[0], height=size[1], note=note)
        cands.append(Cand(a, caption or page_title, prior + 0.1 * min(1.0, max(size) / 2500)))

    embeds = []
    for f in soup.find_all("iframe", src=True) + soup.find_all("iframe", attrs={"data-src": True}):
        src = f.get("src") or f.get("data-src") or ""
        m = re.search(r"(?:youtube(?:-nocookie)?\.com/embed/|dailymotion\.com/embed/video/|player\.vimeo\.com/video/)"
                      r"([\w-]+)", src)
        if m:
            embeds.append(urljoin(base, src.split("?")[0]))
    return cands, list(dict.fromkeys(embeds))[:3]


# --- PDF ----------------------------------------------------------------------------------------

def pdf(ctx: Ctx, url: str, data: bytes, cites: list[ScriptSentence], hinted: set[int]) -> list[Cand]:
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    key = Asset.make_id(url)
    pages_text = [p.get_text()[:3000] for p in doc]
    chosen: dict[int, tuple[float, int | None]] = {}   # 0-based page -> (prior, sentence it was chosen for)
    for n in hinted:
        if 1 <= n <= len(doc):
            chosen[n - 1] = (1.0, None)
    for s in cites:
        sims = embed.similarity(s.text, pages_text)
        figs = embed.numbers(s.text)
        for i in range(len(doc)):
            sims[i] += 0.1 * len(figs & embed.numbers(pages_text[i]))
        for i in sims.argsort()[::-1][:2]:
            if i not in chosen:
                chosen[int(i)] = (float(sims[i]), s.idx)
    if not chosen:
        chosen[0] = (0.0, None)

    folder = ctx.out / "pdf"
    folder.mkdir(parents=True, exist_ok=True)
    meta = doc.metadata or {}
    title = meta.get("title") or Path(urlparse(url).path).name
    cands = []
    for i, (prior, sidx) in sorted(chosen.items()):
        dst = folder / f"{key}_p{i + 1:03d}.png"
        if not dst.exists():
            doc[i].get_pixmap(dpi=220).save(dst)
        with Image.open(dst) as im:
            w, h = im.size
        a = Asset(id="", kind="page", via="pdf", origin="lien", sentence=-1, paragraph=-1, url=url,
                  file=ctx.rel(dst), thumb=thumb(ctx, dst), source_page=f"{url}#page={i + 1}",
                  title=f"{title} — page {i + 1}", author=meta.get("author", ""), rights=QUOTE, width=w, height=h)
        cands.append(Cand(a, pages_text[i][:1000], prior, sidx))
        for j, img in enumerate(doc[i].get_images(full=True)[:6]):
            if min(img[2], img[3]) < 400:
                continue
            idst = folder / f"{key}_p{i + 1:03d}_img{j + 1}.png"
            if not idst.exists():
                pix = pymupdf.Pixmap(doc, img[0])
                if pix.n - pix.alpha >= 4:
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                pix.save(idst)
            b = replace(a, kind="image", file=ctx.rel(idst), thumb=thumb(ctx, idst), width=img[2], height=img[3],
                        title=f"{title} — illustration p. {i + 1}", rights=CHECK)
            cands.append(Cand(b, pages_text[i][:1000], prior - 0.05, sidx))
    return cands


# --- Specific sites -----------------------------------------------------------------------------

def owid(ctx: Ctx, url: str) -> list[Cand]:
    p = urlparse(url)
    slug = p.path.split("/grapher/", 1)[1].strip("/")
    png = f"https://ourworldindata.org/grapher/{slug}.png" + (f"?{p.query}" if p.query else "")
    title = slug.replace("-", " ")
    a = Asset(id="", kind="image", via="owid", origin="lien", sentence=-1, paragraph=-1, url=png, thumb=png,
              source_page=url, title=title, author="Our World in Data", licence="CC BY 4.0",
              licence_url="https://creativecommons.org/licenses/by/4.0/", rights=FREE, width=3400, height=2400,
              note="graphique : le .svg est aussi disponible (remplacer .png par .svg)")
    return [Cand(a, title, 0.5)]


def archive_org(ctx: Ctx, url: str) -> list[Cand]:
    ident = urlparse(url).path.split("/details/", 1)[1].split("/")[0]
    md = ctx.fetch.json(f"https://archive.org/metadata/{ident}").get("metadata", {})
    first = lambda v: v[0] if isinstance(v, list) else (v or "")   # noqa: E731
    title, licence = first(md.get("title")), first(md.get("licenseurl"))
    img = f"https://archive.org/services/img/{ident}"
    a = Asset(id="", kind="image", via="archive", origin="lien", sentence=-1, paragraph=-1, url=img, thumb=img,
              source_page=url, title=title[:120], author=first(md.get("creator"))[:120], licence=licence,
              licence_url=licence, rights=rights_for(licence or None),
              note="Internet Archive : aucune garantie sur les droits, vérifier")
    return [Cand(a, title, 0.2)]


# --- Videos -------------------------------------------------------------------------------------

def _start_param(url: str) -> float | None:
    p = urlparse(url)
    q = parse_qs(p.query)
    raw = (q.get("t") or q.get("start") or [None])[0] or (p.fragment[2:] if p.fragment.startswith("t=") else None)
    if not raw:
        return None
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?", raw)
    if not m or not any(m.groups()):
        return None
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def _vtt_cues(text: str) -> list[tuple[float, str]]:
    cues, seen = [], set()
    for block in re.split(r"\n\s*\n", text):
        m = re.search(r"(\d+):(\d\d):(\d\d)[.,](\d+)\s*-->", block) or re.search(r"(\d\d):(\d\d)[.,](\d+)\s*-->", block)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        t = g[0] * 3600 + g[1] * 60 + g[2] if len(g) == 4 else g[0] * 60 + g[1]
        lines = [re.sub(r"<[^>]+>", "", ln).strip() for ln in block.splitlines()[1:] if "-->" not in ln]
        for ln in lines:
            if ln and ln not in seen:
                seen.add(ln)
                cues.append((float(t), ln))
    return cues


def _caption_window(ctx: Ctx, info: dict, query: str, lang: str = "fr") -> tuple[float, float] | None:
    tracks = {**info.get("automatic_captions", {}), **info.get("subtitles", {})}
    orig = info.get("language") or ""
    for code in (lang, f"{lang}-orig", orig, f"{orig}-orig", "en", "en-orig"):
        fmt = next((f for f in tracks.get(code, []) if f.get("ext") == "vtt"), None)
        if fmt:
            break
    else:
        return None
    r = ctx.fetch.get(fmt["url"])
    cues = _vtt_cues(r.text) if r.ok else []
    if not cues:
        return None
    windows = []
    for i, (t, _) in enumerate(cues):
        words = " ".join(c for tt, c in cues[i:] if tt < t + ctx.seg_len)
        windows.append((t, words))
    windows = windows[::2]
    sims = embed.similarity(query, [w for _, w in windows])
    best = windows[int(sims.argmax())][0]
    return max(0.0, best - 2), best - 2 + ctx.seg_len


def video(ctx: Ctx, url: str, query: str) -> list[Cand]:
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True,
            "socket_timeout": 20, "logger": _Quiet()}
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=False)
    if info.get("_type") == "playlist" and info.get("entries"):
        info = next(iter(info["entries"]))
    duration = float(info.get("duration") or 0)
    start = _start_param(url)
    end = None
    if start is not None:
        end = start + ctx.seg_len
    elif duration and duration > ctx.full_video_max:
        window = _caption_window(ctx, info, query)
        if window:
            start, end = window
        else:
            start, end = 0.0, ctx.seg_len
    licence = info.get("license") or ""
    heights = [f.get("height") or 0 for f in info.get("formats") or []]
    a = Asset(id="", kind="video", via="video", origin="lien", sentence=-1, paragraph=-1,
              url=info.get("webpage_url") or url, thumb=info.get("thumbnail") or "", source_page=url,
              title=(info.get("title") or "")[:120], author=info.get("uploader") or info.get("channel") or "",
              licence=licence, rights=FREE if "creative commons" in licence.lower() else QUOTE,
              width=info.get("width") or 0, height=info.get("height") or max(heights, default=0),
              duration=duration, start=start, end=end)
    return [Cand(a, a.title, 0.6)]


class _Quiet:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


# --- Dispatch -----------------------------------------------------------------------------------

def harvest(ctx: Ctx, url: str, cites: list[ScriptSentence], hinted_pages: set[int]) -> list[Cand]:
    host = urlparse(url).netloc
    query = " ".join(s.text for s in cites)
    if host.endswith("wikipedia.org") and "/wiki/" in url:
        return wikipedia(ctx, url)
    if "ourworldindata.org/grapher/" in url:
        return owid(ctx, url)
    if host.endswith("archive.org") and "/details/" in url:
        cands = archive_org(ctx, url)
        try:
            cands += video(ctx, url, query)
        except Exception:
            pass
        return cands
    if VIDEO_HOSTS.search(url):
        try:
            return video(ctx, url, query)
        except Exception as e:
            if "reddit.com" not in host:
                raise
            ctx.errors.append({"url": url, "error": f"vidéo inaccessible ({str(e)[:120]}) : capture seulement"})
            return []
    r = ctx.fetch.get(url)
    ctype = r.headers.get("content-type", "")
    if r.ok and ("pdf" in ctype or r.content[:5] == b"%PDF-"):
        return pdf(ctx, url, r.content, cites, hinted_pages)
    if r.ok and ctype.startswith("image/"):
        size = image_size(ctx, url) or (0, 0)
        a = Asset(id="", kind="image", via="page", origin="lien", sentence=-1, paragraph=-1, url=url, thumb=url,
                  source_page=url, title=Path(urlparse(url).path).name, rights=CHECK, width=size[0], height=size[1])
        return [Cand(a, "", 0.5)]
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status} (page protégée ou introuvable) : capture d'écran seulement")
    cands, embeds = html_page(ctx, url, r)
    for e in embeds:
        try:
            cands += [Cand(c.asset, c.text, c.prior - 0.2) for c in video(ctx, e, query)]
        except Exception:
            pass
    return cands


def rank_for(ctx: Ctx, s: ScriptSentence, link: Link, cands: list[Cand]) -> list[Asset]:
    """Best candidates of one link for one citing sentence, as assets bound to that sentence."""
    pool = [c for c in cands if c.sentence in (None, s.idx)]
    if not pool:
        return []
    sims = embed.similarity(f"{link.anchor}. {s.text}", [c.text for c in pool])
    scored = sorted(zip(pool, sims), key=lambda cs: -(cs[0].prior + cs[1]))
    out, seen = [], set()
    for c, sim in scored:
        key = (c.asset.url, c.asset.file)
        if key in seen:
            continue
        seen.add(key)
        a = replace(c.asset, sentence=s.idx, paragraph=s.paragraph, score=round(float(c.prior + sim), 3))
        a.id = Asset.make_id(a.kind, a.url, a.file, s.idx)
        out.append(a)
        if len(out) >= ctx.per_link:
            break
    return out


def json_dump(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
