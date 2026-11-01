"""Script loading and French text normalization shared by script and transcript."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from num2words import num2words

FILLERS = {"euh", "heu", "hum", "hmm", "mmh", "mh", "bah", "ben", "beh", "hein", "uh", "um"}

_MD_LINK = re.compile(r"\[([^\]]*)\]\(\s*((?:[^()\s]|\([^()\s]*\))*)\s*\)")   # URLs may hold (parens)
_WIKI_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
_URL = re.compile(r"https?://\S+|www\.\S+")
_CITATION = re.compile(r"\[\d+(?:[,\-–]\s*\d+)*\]|\[\^?\w+\]")
_SENTENCE_END = re.compile(r"(?<=[.!?…])[»”\"')\]]*\s+|\n\s*\n|\n(?=\s*[-*#•])")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_FRONT_MATTER = re.compile(r"\A\s*---\n.*?\n---\s*\n", re.S)
_HEADING = re.compile(r"^\s{0,3}(#+)\s(.*)$", re.M)


@dataclass
class Sentence:
    idx: int
    text: str
    tok_start: int  # first token index in the flat script token list
    tok_end: int    # exclusive

    @property
    def length(self) -> int:
        return self.tok_end - self.tok_start


def split_headings(text: str) -> tuple[str, list[tuple[int, int, str]]]:
    """Remove headings; return the body and (offset in body, level, title) of each heading."""
    headings: list[tuple[int, int, str]] = []
    removed = 0

    def drop(m: re.Match) -> str:
        nonlocal removed
        headings.append((m.start() - removed, len(m.group(1)), m.group(2).strip()))
        removed += len(m.group())
        return ""

    return _HEADING.sub(drop, text), headings


def read_markdown(path: Path) -> str:
    return _FRONT_MATTER.sub("", path.read_text(encoding="utf-8-sig"))


def read_script(path: Path) -> str:
    """Script text without headings (they are not spoken)."""
    if path.suffix.lower() == ".docx":
        import docx
        paragraphs = docx.Document(str(path)).paragraphs
        return "\n\n".join(p.text for p in paragraphs
                           if not p.style.name.lower().startswith(("heading", "titre", "title")))
    return split_headings(read_markdown(path))[0]


def strip_markup(text: str) -> str:
    text = _MD_LINK.sub(r"\1", text)
    text = _WIKI_LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    text = _CITATION.sub("", text)
    text = re.sub(r"[*_`]{1,3}", "", text)                   # emphasis
    return re.sub(r"\s+([.,;:!?)\]»])", r"\1", text)         # space left before punctuation


def _spell_number(match: re.Match) -> str:
    raw = match.group().replace(",", ".")
    try:
        value = float(raw) if "." in raw else int(raw)
        return " " + num2words(value, lang="fr") + " "
    except (ValueError, OverflowError, NotImplementedError):
        return " " + raw + " "


def normalize(text: str) -> list[str]:
    """Lowercase, numbers spelled out, accents and punctuation removed, split on apostrophes."""
    text = text.replace("%", " pour cent ")
    text = _NUMBER.sub(_spell_number, text)
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[’'`´\-–—]", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return text.split()


def sentence_chunks(text: str):
    """Yield (start offset, sentence, tokens, paragraph break before) for markup-free text."""
    pos, gap = 0, ""
    for m in [*_SENTENCE_END.finditer(text), None]:
        end = m.start() if m else len(text)
        chunk = " ".join(text[pos:end].split())
        toks = [t for t in normalize(chunk) if t not in FILLERS]
        if toks:
            yield pos, chunk, toks, gap.count("\n") >= 2
            gap = ""
        else:
            gap += text[pos:end]
        if m:
            gap += m.group()
            pos = m.end()


def load_sentences(path: Path) -> tuple[list[Sentence], list[str]]:
    sentences: list[Sentence] = []
    tokens: list[str] = []
    for _, chunk, toks, _ in sentence_chunks(strip_markup(read_script(path))):
        sentences.append(Sentence(len(sentences), chunk, len(tokens), len(tokens) + len(toks)))
        tokens.extend(toks)
    return sentences, tokens
