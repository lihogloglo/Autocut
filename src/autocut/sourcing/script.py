"""Script structure for sourcing: sections, paragraphs, sentences, with their links and stage notes.

Sentences are cut exactly as text.load_sentences does, so `idx` matches part 1 (derush) indices.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from ..text import _MD_LINK, read_markdown, sentence_chunks, split_headings, strip_markup

SKIP_SECTIONS = {"a virer", "sources", "notes", "brouillon", "references", "bibliographie"}

_PAGE = re.compile(r"\bp(?:age|\.)\s*(\d+)", re.I)
_NOTE = re.compile(r"\(\s*((?:extrait|page|p\.)[^()]*)\)|^(extraits?\b[^.]{0,40})$", re.I)


@dataclass
class Link:
    anchor: str
    url: str
    page: int | None = None     # PDF page hinted by the anchor, e.g. "[page 23](….pdf)"


@dataclass
class ScriptSentence:
    idx: int                    # same index as text.load_sentences
    text: str
    section: int
    paragraph: int
    links: list[Link] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # "extrait", "extrait Bigard", "page 9"


@dataclass
class Section:
    idx: int
    title: str
    level: int
    skip: bool = False          # "A virer", "Sources"…: not harvested


@dataclass
class ScriptDoc:
    title: str
    sections: list[Section]
    sentences: list[ScriptSentence]

    def links(self):
        """(sentence, link) for every link outside skipped sections."""
        for s in self.sentences:
            if not self.sections[s.section].skip:
                for link in s.links:
                    yield s, link


def _key(title: str) -> str:
    title = unicodedata.normalize("NFKD", title.lower())
    return "".join(c for c in title if not unicodedata.combining(c)).strip(" :.")


def parse_script(path: Path) -> ScriptDoc:
    raw = read_markdown(path)
    front = re.match(r"\A\s*---\n(.*?)\n---", path.read_text(encoding="utf-8-sig"), re.S)
    title_m = re.search(r"^title:\s*(.+)$", front.group(1), re.M) if front else None
    title = title_m.group(1).strip() if title_m else None
    body, headings = split_headings(raw)
    text = strip_markup(body)

    def to_text(offset: int) -> int:     # body offset -> offset in markup-free text
        return len(strip_markup(body[:offset]))

    sections = [Section(0, "", 0)]
    bounds: list[int] = []
    for offset, level, heading in headings:
        if level == 1 and title is None:
            title = heading
        if level == 1 and len(sections) == 1 and not bounds:
            continue                     # document title, not a section
        sections.append(Section(len(sections), heading, level, _key(heading) in SKIP_SECTIONS))
        bounds.append(to_text(offset))

    links = []                           # (offset in text, Link)
    for m in _MD_LINK.finditer(body):
        anchor = strip_markup(m.group(1)).strip()
        approx = to_text(m.start())
        found = text.find(anchor, max(0, approx - 3)) if anchor else -1
        page = _PAGE.search(anchor)
        links.append((found if found >= 0 else approx,
                      Link(anchor, m.group(2), int(page.group(1)) if page else None)))

    sentences: list[ScriptSentence] = []
    chunks = list(sentence_chunks(text))
    paragraph, section = -1, 0
    for i, (start, chunk, _, new_par) in enumerate(chunks):
        end = chunks[i + 1][0] if i + 1 < len(chunks) else len(text) + 1
        new_section = sum(b <= start for b in bounds)
        if new_par or new_section != section or not sentences:
            paragraph += 1
        section = new_section
        s = ScriptSentence(i, chunk, section, paragraph)
        s.links = [link for at, link in links if start <= at < end]
        s.notes = [" ".join(n for n in m.groups() if n).strip(" *") for m in _NOTE.finditer(chunk)]
        sentences.append(s)

    return ScriptDoc(title or path.stem, sections, sentences)
