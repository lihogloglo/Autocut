"""Align the transcript to the script, allowing jumps back (retakes) and forward (skips).

Viterbi over script positions: state j means "the next script token is j".
Each transcript token either matches the next script token, is an insertion
(off-script / misheard), and script tokens may be skipped (deletion). A jump to
any position costs a fixed penalty, cheaper after a pause, which is how a
restart ("le traité de... le traité de Versailles") gets explained.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from rapidfuzz import fuzz, process

from .text import FILLERS, normalize
from .transcribe import Word

MATCH, FUZZY, MISMATCH = 2.0, 1.0, -1.0
INSERT, DELETE = 1.0, 0.6
JUMP, JUMP_AFTER_PAUSE = 5.0, 3.0
PAUSE = 0.3
MIN_CHAIN = 3

DIAG, INS, DEL, JUMPED = 0, 1, 2, 4


@dataclass
class WordMap:
    filler: bool
    tok_min: int | None = None  # script token span this word matched, if any
    tok_max: int | None = None


def _score_table(t_vocab: list[str], s_vocab: list[str]) -> np.ndarray:
    ratio = process.cdist(t_vocab, s_vocab, scorer=fuzz.ratio, dtype=np.uint8, workers=-1)
    t_len = np.array([len(t) for t in t_vocab])[:, None]
    s_len = np.array([len(s) for s in s_vocab])[None, :]
    table = np.full(ratio.shape, MISMATCH, dtype=np.float32)
    table[(ratio >= 80) & (t_len >= 4) & (s_len >= 4)] = FUZZY
    table[ratio == 100] = MATCH
    return table


def _anchored(matched: list[int], tok_of: np.ndarray) -> list[int]:
    """Keep matches that sit in a near-diagonal chain of at least MIN_CHAIN.

    Short common words ("la", "à", "de") match somewhere in any script; on
    their own they are noise, inside a chain of real matches they are signal.
    """
    keep: list[int] = []
    chain: list[int] = []
    for ti in matched:
        if chain and 0 < ti - chain[-1] <= 3 and 0 < tok_of[ti] - tok_of[chain[-1]] <= 3:
            chain.append(ti)
            continue
        if len(chain) >= MIN_CHAIN:
            keep.extend(chain)
        chain = [ti]
    if len(chain) >= MIN_CHAIN:
        keep.extend(chain)
    return keep


def align(words: list[Word], script_tokens: list[str]) -> list[WordMap]:
    maps: list[WordMap] = []
    t_tokens: list[str] = []
    t_word: list[int] = []
    t_jump: list[float] = []
    prev_end = -1.0
    for wi, w in enumerate(words):
        toks = [t for t in normalize(w.text) if t not in FILLERS]
        maps.append(WordMap(filler=not toks))
        for k, t in enumerate(toks):
            pause = k == 0 and w.start - prev_end >= PAUSE
            t_tokens.append(t)
            t_word.append(wi)
            t_jump.append(JUMP_AFTER_PAUSE if pause else JUMP)
        prev_end = w.end
    if not t_tokens or not script_tokens:
        return maps

    s_vocab = sorted(set(script_tokens))
    t_vocab = sorted(set(t_tokens))
    s_ids = np.searchsorted(s_vocab, script_tokens)
    t_ids = np.searchsorted(t_vocab, t_tokens)
    table = _score_table(t_vocab, s_vocab)

    n, m = len(t_tokens), len(script_tokens)
    ops = np.zeros((n, m + 1), dtype=np.uint8)
    jump_from = np.zeros(n, dtype=np.int64)
    del_ramp = np.arange(m + 1, dtype=np.float32) * DELETE
    prev = np.zeros(m + 1, dtype=np.float32)  # free start anywhere

    for i in range(n):
        best = int(prev.argmax())
        jump_from[i] = best
        jumped = prev[best] - t_jump[i] > prev
        pre = np.where(jumped, prev[best] - t_jump[i], prev)

        diag = np.empty(m + 1, dtype=np.float32)
        diag[0] = -np.inf
        diag[1:] = pre[:-1] + table[t_ids[i]][s_ids]
        ins = pre - INSERT
        cur = np.maximum(diag, ins)
        op = np.where(diag >= ins, DIAG, INS).astype(np.uint8)

        swept = np.maximum.accumulate(cur + del_ramp) - del_ramp
        deleted = swept > cur + 1e-4
        op[deleted] = DEL
        ops[i] = op | (jumped.astype(np.uint8) * JUMPED)
        prev = swept

    i, j = n - 1, int(prev.argmax())
    tok_of = np.full(n, -1, dtype=np.int64)
    while i >= 0:
        op = ops[i, j] & 3
        if op == DEL:
            j -= 1
            continue
        if op == DIAG:
            tok_of[i] = j - 1
            k = j - 1
        else:
            k = j
        if ops[i, k] & JUMPED:
            k = int(jump_from[i])
        i, j = i - 1, k

    matched = [ti for ti, tok in enumerate(tok_of) if tok >= 0 and table[t_ids[ti]][s_ids[tok]] > 0]
    for ti in _anchored(matched, tok_of):
        tok = tok_of[ti]
        wm = maps[t_word[ti]]
        wm.tok_min = tok if wm.tok_min is None else min(wm.tok_min, tok)
        wm.tok_max = tok if wm.tok_max is None else max(wm.tok_max, tok)
    return maps
