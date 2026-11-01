"""Script loading and French text normalization shared by script and transcript."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from num2words import num2words

FILLERS = {"euh", "heu", "hum", "hmm", "mmh", "mh", "bah", "ben", "beh", "hein", "uh", "um"}

_MD_LINK = re.compile(r"\[([^\]]*)\]\((?:[^()\s]|\([^()\s]*\))*\)")   # URLs may hold (parens)
_WIKI_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
_URL = re.compile(r"https?://\S+|www\.\S+")
_CITATION = re.compile(r"\[\d+(?:[,\-–]\s*\d+)*\]|\[\^?\w+\]")
_SENTENCE_END = re.compile(r"(?<=[.!?…])[»”\"')\]]*\s+|\n\s*\n|\n(?=\s*[-*#•])")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


@dataclass
class Sentence:
    idx: int
    text: str
    tok_start: int  # first token index in the flat script token list
    tok_end: int    # exclusive

    @property
    def length(self) -> int:
        return self.tok_end - self.tok_start


def read_script(path: Path) -> str:
    """Script text without headings (they are not spoken)."""
    if path.suffix.lower() == ".docx":
        import docx
        paragraphs = docx.Document(str(path)).paragraphs
        return "\n\n".join(p.text for p in paragraphs
                           if not p.style.name.lower().startswith(("heading", "titre", "title")))
    text = path.read_text(encoding="utf-8-sig")
    text = re.sub(r"\A\s*---\n.*?\n---\s*\n", "", text, flags=re.S)   # YAML front matter
    return re.sub(r"^\s{0,3}#+\s.*$", "", text, flags=re.M)


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


def load_sentences(path: Path) -> tuple[list[Sentence], list[str]]:
    text = strip_markup(read_script(path))
    sentences: list[Sentence] = []
    tokens: list[str] = []
    for chunk in _SENTENCE_END.split(text):
        chunk = " ".join(chunk.split())
        toks = [t for t in normalize(chunk) if t not in FILLERS]
        if not toks:
            continue
        sentences.append(Sentence(len(sentences), chunk, len(tokens), len(tokens) + len(toks)))
        tokens.extend(toks)
    return sentences, tokens
