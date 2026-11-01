"""Candidate assets and the manifest that the contact sheet and the export read."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, fields
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
