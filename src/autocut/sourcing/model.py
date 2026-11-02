"""Candidate assets and the manifest that the contact sheet and the export read."""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import date as _date, datetime, timezone
from pathlib import Path

# Rights levels shown as coloured badges on the contact sheet.
FREE = "libre"          # public domain, CC0, CC BY, CC BY-SA: usable with the credit line
CHECK = "à vérifier"    # unknown licence, NC/ND, or a CC licence we could not confirm
PROTECTED = "protégé"   # press agency / stock credit found next to the image
QUOTE = "citation"      # screenshot of the source or short excerpt (fair use / droit de citation)

KINDS = ("image", "screenshot", "page", "video")

_AGENCY = re.compile(
    r"\b(AFP|Reuters|Getty|AP Photo|Associated Press|EPA|Sipa|Hans Lucas|Abaca|Shutterstock|"
    r"Alamy|MaxPPP|Belga|Anadolu|NurPhoto|IP3|Bridgeman|Gamma|Rapho|Leemage|Photononstop|"
    r"Roger[- ]Viollet|Keystone|Magnum|iStock|Adobe Stock|Dreamstime)\b", re.I)


def agency(text: str) -> str | None:
    m = _AGENCY.search(text or "")
    return m.group(0) if m else None


def rights_for(licence: str | None, credit: str = "") -> str:
    if agency(credit):
        return PROTECTED
    lic = (licence or "").lower()
    if not lic:
        return CHECK
    if re.search(r"\b(nc|nd)\b|non.?commercial|no.?deriv", lic):
        return CHECK
    if re.search(r"public domain|domaine public|\bpd\b|cc0|pdm|no restrictions|cc[ -]?by|"
                 r"creative ?commons|licence ouverte|open licen[cs]e|attribution", lic):
        return FREE
    return CHECK


# --- Dates ---------------------------------------------------------------------------------------

_MONTHS = {n: i for i, names in enumerate((
    "janvier january jan janv", "février fevrier february feb fév fev févr", "mars march mar",
    "avril april apr avr", "mai may", "juin june jun", "juillet july jul juil", "août aout august aug",
    "septembre september sep sept", "octobre october oct", "novembre november nov",
    "décembre decembre december dec déc"), 1) for n in names.split()}
_MON = "|".join(sorted(map(re.escape, _MONTHS), key=len, reverse=True))
_DATE_PATTERNS = [      # (regex, what each group is: y m d, M = month name)
    (re.compile(r"(?<!\d)(\d{4})[-:/.](\d{1,2})[-:/.](\d{1,2})(?!\d)"), "ymd"),      # ISO, EXIF
    (re.compile(r"(?<!\d)(\d{1,2})[/.](\d{1,2})[/.](\d{4})(?!\d)"), "dmy"),
    (re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?:\d{4}|\d{6})?(?!\d)"), "ymd"),       # YouTube, PDF "D:2019…"
    (re.compile(rf"(?<!\d)(\d{{1,2}})(?:er|st|nd|rd|th)?\s+({_MON})\b\.?,?\s+(\d{{4}})(?!\d)", re.I), "dMy"),
    (re.compile(rf"\b({_MON})\b\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})(?!\d)", re.I), "Mdy"),
    (re.compile(rf"\b({_MON})\b\.?,?\s+(\d{{4}})(?!\d)", re.I), "My"),
    (re.compile(r"(?<!\d)(\d{4})-(\d{2})(?![\d-])"), "ym"),
]
_YEAR_ONLY = re.compile(r"(?<!\d)(\d{4})(\s*(?:[-–—/]|à|to|and|et|or|ou)\s*(?:circa\s+|ca\.\s*|c\.\s*|vers\s+)?"
                        r"\d{2,4}(?!\d))?(?!\d)")
_DECADE = re.compile(r"(?<!\d)(\d{3}0)'?s\b|années\s+(\d{3}0)\b", re.I)
_APPROX = re.compile(r"\bca\.|\bc\.(?=\s*\d)|\b(?:circa|vers|env\.|environ|about|around|approx\w*|between|entre|"
                     r"before|avant|after|après|probabl\w+|possibl\w+|peut-être)\b|~|\?", re.I)


def _ymd(y, m=None, d=None) -> str:
    y = int(y)
    if not 1000 <= y <= _date.today().year + 1:
        return ""
    if m is None:
        return str(y)
    m = int(m)
    if not 1 <= m <= 12:
        return ""
    if d is None:
        return f"{y}-{m:02d}"
    d = int(d)
    return f"{y}-{m:02d}-{d:02d}" if 1 <= d <= 31 else ""


def norm_date(raw) -> str:
    """Any date a source gives -> "2019", "2019-03" or "2019-03-16" ("~1850" when approximate or a range),
    "" when there is none. The first date in the text wins (Commons: "1871-03-18 (original), 2010 (scan)")."""
    if isinstance(raw, (list, tuple)):          # Europeana's year lists
        ds = [d for d in map(norm_date, raw) if d]
        years = {d.lstrip("~")[:4] for d in ds}
        if not ds:
            return ""
        return max(ds, key=len) if len(years) == 1 else "~" + min(years)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        if raw > 10 ** 8:                       # Unix timestamp
            return datetime.fromtimestamp(raw, timezone.utc).date().isoformat()
        return _ymd(int(raw)) if raw >= 1000 else ""
    s = str(raw or "")
    s = re.sub(r"(?is)<(\w+)[^>]*display:\s*none[^>]*>.*?</\1>", " ", s)   # Commons' hidden "date QS:" data
    m = re.search(r'datetime="([^"]+)"', s)
    if m and (d := norm_date(m.group(1))):
        return d
    s = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())
    found = []                                  # (position, -precision, date)
    for rx, order in _DATE_PATTERNS:
        for m in rx.finditer(s):
            g = dict(zip(order, m.groups()))
            mo = _MONTHS[g["M"].lower()] if "M" in g else g.get("m")
            day = g.get("d")
            if order == "dmy" and int(mo) > 12 >= int(day):     # 03/16/2019
                mo, day = day, mo
            if d := _ymd(g["y"], mo, day):
                found.append((m.start(), -d.count("-"), d))
    for m in _DECADE.finditer(s):
        if d := _ymd(m.group(1) or m.group(2)):
            found.append((m.start(), -1, "~" + d))     # beats the bare year of "1890s"
    for m in _YEAR_ONLY.finditer(s):
        if d := _ymd(m.group(1)):
            found.append((m.start(), 0, "~" + d if m.group(2) else d))
    if not found:
        return ""
    d = min(found)[2]
    if not d.startswith("~") and d.count("-") < 2 and _APPROX.search(s):    # "ca. 1850", "between 1790 and…"
        return "~" + d[:4]
    return d


def year_of(d: str) -> int | None:
    m = re.match(r"~?(\d{4})", d or "")
    return int(m.group(1)) if m else None


def _roman(s: str) -> int:
    vals = {"I": 1, "V": 5, "X": 10, "L": 50}
    n = 0
    for a, b in zip(s, s[1:] + " "):
        n += -vals[a] if vals.get(b, 0) > vals[a] else vals[a]
    return n


def period_range(period: str) -> tuple[int, int] | None:
    """First and last year of a period as written by the AI or the heuristic: "2026", "mars 2026",
    "1789-1794", "1914-18", "années 1960", "XIXe siècle"; None when it names no year."""
    p = period or ""
    if m := _DECADE.search(p):
        y = int(m.group(1) or m.group(2))
        return y, y + 9
    if m := re.search(r"\b([IVXL]+|\d{1,2})\s*(?:e|è|ème|eme|er|th|st|nd|rd)\s+(?:siècle|century)", p, re.I):
        c = int(m.group(1)) if m.group(1).isdigit() else _roman(m.group(1).upper())
        return (c - 1) * 100 + 1, c * 100
    years = [int(y) for y in re.findall(r"(?<!\d)(\d{4})(?!\d)", p) if 1000 <= int(y) <= 2100]
    if m := re.search(r"(?<!\d)(\d\d)(\d\d)\s*[-–]\s*(\d\d)(?!\d)", p):     # 1914-18
        years.append(int(m.group(1) + m.group(3)))
    return (min(years), max(years)) if years else None


TIMELESS = ("portrait", "carte", "lieu", "objet")   # natures where an older picture is still right


def date_note(a: Asset, period: str, nature: str = "") -> str:
    """Short French note when the asset's date cannot match the period of its paragraph, else "".
    Before the period: it can't show what happened then (a photo of earlier, similar protests).
    After it: only for pictures dated when they were taken, of the photo era (paintings are made later,
    videos are re-uploaded archives, a page can carry an older picture)."""
    rng, y = period_range(period), year_of(a.date)
    if not rng or y is None or a.kind not in ("image", "video") or nature in TIMELESS:
        return ""
    lo, hi = rng
    approx = a.date.startswith("~")
    slack = 2 if approx else 0
    published = a.kind == "video" or (a.via in ("web", "page") and not approx)
    if not (y < lo - slack or (not published and hi >= 1900 and y > hi + 1 + slack)):
        return ""
    from ..i18n import tr
    year = f"{'~' if approx else ''}{y}"
    if a.kind == "video":
        return tr("vidéo de {year}, le passage parle de {period}", year=year, period=period)
    if published:
        return tr("image publiée en {year}, le passage parle de {period}", year=year, period=period)
    return tr("image de {year}, le passage parle de {period}", year=year, period=period)


def add_note(a: Asset, text: str) -> None:
    if text and text not in a.note:
        a.note = " · ".join(x for x in (a.note, text) if x)


@dataclass
class Asset:
    id: str
    kind: str                  # image | screenshot | page (PDF page render) | video
    via: str                   # collector: wikipedia, page, pdf, owid, archive, video, capture, commons, ...
    origin: str                # "lien" (cited link) or "recherche"
    sentence: int              # first sentence it illustrates
    paragraph: int
    url: str = ""              # full resolution image / video page
    thumb: str = ""            # small preview: URL, or path relative to the output folder
    file: str = ""             # already local (screenshots, PDF renders), relative to the output folder
    source_page: str = ""      # page to credit / open
    title: str = ""
    author: str = ""
    licence: str = ""
    licence_url: str = ""
    credit: str = ""           # caption / credit text found next to the image
    rights: str = CHECK
    width: int = 0
    height: int = 0
    duration: float = 0.0      # videos
    start: float | None = None  # suggested excerpt (seconds); None = whole video
    end: float | None = None
    score: float = 0.0
    note: str = ""
    date: str = ""             # "2019", "2019-03" or "2019-03-16"; "~1850" = approximate or estimated by the AI.
                               # Photo taken / work made; for web & page images, videos: when published

    @staticmethod
    def make_id(*parts) -> str:
        return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12]


@dataclass
class Manifest:
    script: str
    title: str
    sections: list[dict]
    sentences: list[dict]
    assets: list[Asset] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    def save(self, path: Path) -> None:
        data = asdict(self)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> Manifest:
        data = json.loads(path.read_text(encoding="utf-8"))
        names = {f.name for f in fields(Asset)}
        data["assets"] = [Asset(**{k: v for k, v in a.items() if k in names}) for a in data["assets"]]
        return cls(**data)
