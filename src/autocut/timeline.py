"""Kept pieces → timeline clips with padded, quiet-snapped cut points."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .takes import ADLIB, CHATTER, FAILED, INCOMPLETE, TAKE, Piece
from .text import Sentence
from .transcribe import Word

# Premiere label names, one per take number (cycled).
TAKE_COLORS = ["Iris", "Forest", "Mango", "Lavender", "Caribbean", "Yellow", "Cerulean", "Purple"]
STATUS_COLORS = {INCOMPLETE: "Magenta", FAILED: "Rose", ADLIB: "Tan", CHATTER: "Brown"}


@dataclass
class Options:
    max_pause: float = 0.6   # longer pauses inside a take are cut out
    pad_in: float = 0.12
    pad_out: float = 0.25
    snap: float = 0.06       # search window for the quietest cut point


@dataclass
class Clip:
    src_in: float
    src_out: float
    name: str
    color: str
    first_word: int
    last_word: int


def _spoken(p: Piece, words: list[Word]) -> str:
    return " ".join(words[i].text for i in p.words).replace(" '", "'")[:60]


def _label(p: Piece, sentences: list[Sentence], words: list[Word], last_sentence: int | None) -> str:
    if p.sentence is None:
        return f"{p.status.upper()} · {_spoken(p, words)}"
    s = sentences[p.sentence]
    first = f"S{p.sentence + 1:03d}"
    span = first if last_sentence in (None, p.sentence) else f"{first}–S{last_sentence + 1:03d}"
    if p.status == FAILED:
        return f"FAILED {span} · {_spoken(p, words)}"
    tag = f"T{p.take}/{p.total}" + (" IMPRO" if p.impro else "") + (" INCOMPLETE" if p.status == INCOMPLETE else "")
    return f"{span} {tag} · {s.text[:60]}"


def _color(p: Piece) -> str:
    if p.status == TAKE:
        return TAKE_COLORS[(p.take - 1) % len(TAKE_COLORS)]
    return STATUS_COLORS[p.status]


def _quietest(env: np.ndarray, lo: float, hi: float, hop: float = 0.01) -> float:
    a, b = int(lo / hop), int(hi / hop) + 1
    if b <= a or a >= len(env):
        return (lo + hi) / 2
    return (a + int(np.argmin(env[a:b]))) * hop


def build_clips(pieces: list[Piece], include: set[str], words: list[Word],
                sentences: list[Sentence], env: np.ndarray, duration: float, opt: Options) -> list[Clip]:
    # Split pieces at long internal pauses into spans of word indices.
    spans: list[tuple[Piece, list[int]]] = []
    for p in pieces:
        if p.status not in include:
            continue
        cur = [p.words[0]]
        for a, b in zip(p.words, p.words[1:]):
            if words[b].start - words[a].end > opt.max_pause:
                spans.append((p, cur))
                cur = []
            cur.append(b)
        spans.append((p, cur))

    # Merge neighbours that are contiguous in the recording and share a label.
    merged: list[tuple[Piece, list[int], int | None]] = []
    for p, ws in spans:
        if merged:
            q, qws, _ = merged[-1]
            same = (p.status, p.take, p.total, p.impro) == (q.status, q.take, q.total, q.impro) \
                and p.status == TAKE
            contiguous = ws[0] == qws[-1] + 1 and words[ws[0]].start - words[qws[-1]].end <= opt.max_pause
            if same and contiguous:
                merged[-1] = (q, qws + ws, p.sentence)
                continue
        merged.append((p, ws, p.sentence))

    clips: list[Clip] = []
    for p, ws, last_sentence in merged:
        first, last = ws[0], ws[-1]
        lo = words[first - 1].end + 0.02 if first > 0 else 0.0
        hi = words[last + 1].start - 0.02 if last + 1 < len(words) else duration
        start = max(lo, words[first].start - opt.pad_in)
        end = min(hi, words[last].end + opt.pad_out)
        start = _quietest(env, max(lo, start - opt.snap), min(words[first].start, start + opt.snap))
        end = _quietest(env, max(words[last].end, end - opt.snap), min(hi, end + opt.snap))
        if end <= start:
            continue
        clips.append(Clip(start, end, _label(p, sentences, words, last_sentence), _color(p), first, last))
    return clips
