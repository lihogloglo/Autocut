"""Kept pieces → timeline clips with padded, quiet-snapped cut points."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from .takes import ADLIB, CHATTER, FAILED, INCOMPLETE, TAKE, Piece
from .text import Sentence
from .transcribe import Word

# Premiere label names, one per take number (cycled).
TAKE_COLORS = ["Iris", "Forest", "Mango", "Lavender", "Caribbean", "Yellow", "Cerulean", "Purple"]
STATUS_COLORS = {INCOMPLETE: "Magenta", FAILED: "Rose", ADLIB: "Tan", CHATTER: "Brown"}
SILENCE_COLOR = "Blue"
ALL = {TAKE, INCOMPLETE, FAILED, ADLIB, CHATTER}


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
    label: str   # take info for the sequence marker; clipitems keep their original names
    color: str
    first_word: int
    last_word: int
    keep: bool = False   # copy this stretch of the sequence as it is (already derushed by hand)
    markers: list[tuple[str, float, float]] = field(default_factory=list)   # (label, in, out), sequence s


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


def build_triage(pieces: list[Piece], words: list[Word], sentences: list[Sentence], env: np.ndarray,
                 duration: float, opt: Options, min_silence: float = 1.0) -> list[Clip]:
    """The whole recording, nothing removed: one clip per take/attempt/chatter (pauses
    inside it kept), silences of `min_silence` or more as their own clips, shorter gaps
    split at their quietest point between the neighbours."""
    clips = sorted(build_clips(pieces, ALL, words, sentences, env, duration, replace(opt, max_pause=math.inf)),
                   key=lambda c: c.src_in)
    out: list[Clip] = []
    t = 0.0
    for c in clips:
        if c.src_in - t >= min_silence:
            out.append(Clip(t, c.src_in, "", SILENCE_COLOR, -1, -1))
        elif out:
            lo, hi = sorted((t, c.src_in))
            cut = _quietest(env, lo, hi)
            out[-1].src_out = c.src_in = t = cut
        else:
            c.src_in = 0.0
        if c.src_out > c.src_in:
            out.append(c)
            t = c.src_out
    if duration - t >= min_silence or not out:
        out.append(Clip(t, duration, "", SILENCE_COLOR, -1, -1))
    else:
        out[-1].src_out = duration
    return out
