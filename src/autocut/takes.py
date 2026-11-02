"""Turn the word→script alignment into per-sentence takes.

A *run* is a stretch of speech that moves forward through the script. A
backward jump (or a big forward skip) starts a new run. Each run is split into
*pieces*, one per script sentence it touches. Off-script words spoken in the
same breath as a piece are glued to it (improvised wording stays inside its
take); the rest becomes ADLIB or CHATTER. Per sentence, pieces are then grouped
into takes:

- a piece starting at the sentence start opens a new take;
- a piece spoken in the same breath as the previous one and covering new words
  joins it (reordered wording);
- a piece starting mid-sentence, right where the previous attempt had got to,
  is a pickup ("le traité, signé en... signé en 1919"): the previous attempt
  is trimmed at the pickup point and the two pieces form one take.

A take is complete if it reaches the end of the script sentence, or if it ends
on improvised wording (IMPRO). An attempt that stops short is failed only if the
sentence is attempted again later; if the speaker moved on, it is kept as
INCOMPLETE. If a sentence has no kept take, its best attempt is kept as
INCOMPLETE.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .align import WordMap
from .text import Sentence, normalize
from .transcribe import Word

SLACK = 2            # tokens of tolerance at sentence start/end (misheard words)
FORWARD_BREAK = 8    # skipping more script tokens than this starts a new run
MIN_COVERAGE = 0.6
GLUE_GAP = 0.5       # seconds; words closer than this are the same breath
IMPRO_TAIL = 3       # off-script words after the last script match that make an improvised ending
RESTART_CUES = {"non", "attends", "attend", "pardon", "recommence", "recommencer", "reprends", "reprendre",
                "merde", "putain", "zut", "mince", "ok", "okay", "coupe", "coupez",
                # English
                "sorry", "wait", "again", "restart", "redo", "cut", "no", "damn", "shit", "fuck", "oops"}

TAKE, INCOMPLETE, FAILED, ADLIB, CHATTER = "take", "incomplete", "failed", "adlib", "chatter"


@dataclass
class Piece:
    words: list[int]
    sentence: int | None = None   # None for off-script speech
    status: str = FAILED
    take: int = 0
    total: int = 0
    impro: bool = False

    @property
    def first_word(self) -> int:
        return self.words[0]


@dataclass
class SentenceResult:
    sentence: Sentence
    takes: list[list[Piece]] = field(default_factory=list)   # kept takes, in order
    failed: int = 0
    incomplete: bool = False
    impro: int = 0


def _span(piece: Piece, maps: list[WordMap]) -> tuple[int, int]:
    toks = [(maps[w].tok_min, maps[w].tok_max) for w in piece.words if maps[w].tok_min is not None]
    return min(t[0] for t in toks), max(t[1] for t in toks)


def _covered(take: list[Piece], maps: list[WordMap]) -> set[int]:
    out: set[int] = set()
    for p in take:
        for w in p.words:
            if maps[w].tok_min is not None:
                out.update(range(maps[w].tok_min, maps[w].tok_max + 1))
    return out


def _spoken(idxs: list[int], maps: list[WordMap]) -> int:
    return sum(not maps[i].filler for i in idxs)


def _is_cue(idxs: list[int], words: list[Word], maps: list[WordMap]) -> bool:
    """A short fragment containing a restart cue word."""
    if _spoken(idxs, maps) >= IMPRO_TAIL + 2:
        return False
    return any(t in RESTART_CUES for i in idxs for t in normalize(words[i].text))


def _tail_words(take: list[Piece], maps: list[WordMap]) -> int:
    """Spoken off-script words after the take's last script match."""
    tail: list[int] = []
    for w in reversed(take[-1].words):
        if maps[w].tok_min is not None:
            break
        tail.append(w)
    return _spoken(tail, maps)


def split_pieces(words: list[Word], maps: list[WordMap], tok_sentence: list[int],
                 adlib_words: int) -> list[Piece]:
    mapped = [i for i, m in enumerate(maps) if m.tok_min is not None]
    pieces: list[Piece] = []
    piece_of: dict[int, Piece] = {}
    by_key: dict[tuple[int, int], Piece] = {}
    run, last_max = 0, None
    for i in mapped:
        m = maps[i]
        if last_max is not None and (m.tok_min <= last_max or m.tok_min > last_max + FORWARD_BREAK):
            run += 1
        last_max = m.tok_max
        key = (run, tok_sentence[m.tok_min])
        if key not in by_key:
            by_key[key] = Piece([], key[1])
            pieces.append(by_key[key])
        by_key[key].words.append(i)
        piece_of[i] = by_key[key]

    def offscript(idxs: list[int]) -> None:
        while idxs and maps[idxs[0]].filler:
            idxs.pop(0)
        while idxs and maps[idxs[-1]].filler:
            idxs.pop()
        if idxs:
            spoken = sum(not maps[i].filler for i in idxs)
            pieces.append(Piece(idxs, None, ADLIB if spoken >= adlib_words else CHATTER))

    def breath(a: int, b: int) -> bool:
        return words[b].start - words[a].end < GLUE_GAP

    bounds = [-1] + mapped + [len(words)]
    for a, b in zip(bounds, bounds[1:]):
        gap = list(range(a + 1, b))
        if not gap:
            continue
        pa, pb = piece_of.get(a), piece_of.get(b)
        if pa is not None and pa is pb:
            pa.words.extend(gap)
            continue
        head: list[int] = []   # same breath as the piece before
        if pa is not None:
            prev = a
            for k in gap:
                if not breath(prev, k):
                    break
                head.append(k)
                prev = k
        tail: list[int] = []   # same breath as the piece after
        if pb is not None:
            nxt = b
            for k in reversed(gap[len(head):]):
                if not breath(k, nxt):
                    break
                tail.insert(0, k)
                nxt = k
        # A short trailing remark is not an improvised ending, and a restart cue
        # ("non, attends") never belongs to a take.
        flows_on = len(head) == len(gap) and pb is not None
        if head and (_is_cue(head, words, maps) or (_spoken(head, maps) < IMPRO_TAIL and not flows_on)):
            head = []
        if tail and _is_cue(tail, words, maps):
            tail = []
        rest = gap[len(head):len(gap) - len(tail)]
        if pa is not None:
            pa.words.extend(head)
        if pb is not None:
            pb.words.extend(tail)
        offscript(rest)

    for p in pieces:
        p.words.sort()
    pieces.sort(key=lambda p: p.first_word)
    return pieces


def _trim(take: list[Piece], cut_tok: int, maps: list[WordMap], dropped: list[Piece]) -> None:
    """Remove everything from the first word at/after script token `cut_tok`."""
    while take:
        p = take[-1]
        cut = next((k for k, w in enumerate(p.words)
                    if maps[w].tok_min is not None and maps[w].tok_min >= cut_tok), None)
        if cut is None:
            return
        tail, p.words = p.words[cut:], p.words[:cut]
        dropped.append(Piece(tail, p.sentence, FAILED))
        if p.words:
            return
        take.pop()


def resolve_takes(pieces: list[Piece], sentences: list[Sentence], maps: list[WordMap],
                  words: list[Word]) -> tuple[list[Piece], list[SentenceResult]]:
    results = [SentenceResult(s) for s in sentences]
    per_sentence: dict[int, list[Piece]] = {}
    for p in pieces:
        if p.sentence is not None:
            per_sentence.setdefault(p.sentence, []).append(p)

    extra: list[Piece] = []
    for sid, plist in per_sentence.items():
        s = sentences[sid]
        candidates: list[list[Piece]] = []
        for p in plist:
            first, last = _span(p, maps)
            if candidates and candidates[-1]:
                cur = candidates[-1]
                prev_word = cur[-1].words[-1]
                same_breath = (p.first_word == prev_word + 1
                               and words[p.first_word].start - words[prev_word].end < GLUE_GAP)
                if same_breath and not (_covered(cur, maps) & _covered([p], maps)):
                    cur.append(p)
                    continue
            if first - s.tok_start <= SLACK or not candidates:
                candidates.append([p])
                continue
            cur = candidates[-1]
            reached = max(_span(q, maps)[1] for q in cur)
            if reached >= first - SLACK and last > reached:
                _trim(cur, first, maps, extra)
                cur.append(p)
            else:
                candidates.append([p])

        candidates = [c for c in candidates if c]
        res = results[sid]
        kept: list[tuple[list[Piece], bool, bool]] = []   # (take, impro, incomplete)
        scored = []
        for n, c in enumerate(candidates):
            cov = _covered(c, maps)
            coverage = len(cov) / s.length
            reaches_end = max(cov) >= s.tok_end - 1 - SLACK
            superseded = n < len(candidates) - 1
            scored.append((c, coverage))
            if reaches_end and coverage >= MIN_COVERAGE:
                kept.append((c, False, False))
            elif _tail_words(c, maps) >= IMPRO_TAIL:
                kept.append((c, True, False))
            elif not superseded:
                kept.append((c, False, True))
        if not kept:
            kept = [(max(scored, key=lambda x: x[1])[0], False, True)]
        kept_ids = {id(c) for c, _, _ in kept}
        for c in candidates:
            if id(c) not in kept_ids:
                res.failed += 1
        for n, (c, impro, incomplete) in enumerate(kept, 1):
            for p in c:
                p.status = INCOMPLETE if incomplete else TAKE
                p.take, p.total, p.impro = n, len(kept), impro
        res.takes = [c for c, _, _ in kept]
        res.impro = sum(impro for _, impro, _ in kept)
        res.incomplete = all(inc for _, _, inc in kept)

    out = [p for p in pieces + extra if p.words]
    out.sort(key=lambda p: p.first_word)
    return out, results
