"""What is said in a rush: transcribed once, then searched like a text.

The words come from faster-whisper through transcribe.py and are kept in its per-rush cache
(%LOCALAPPDATA%\\fauxraccord\\transcripts), so a rush the Derush already heard is not heard again and a
stopped transcription goes on where it stopped (it is saved every 10 minutes of rush).

Which audio track: the only one, or (OBS with the game, the mic and Discord on separate tracks) the one
the index heard the most "Speech" on. speech.json in the rush's index folder remembers the model,
language and track used, so the rules (the "said" signal) find the words without knowing them.

Searching is accent- and case-blind and forgives small spelling differences (rapidfuzz): "je suis
mort" finds "J'suis mort", "on raid" finds "on raide". A query of several words is matched as a phrase.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

import numpy as np

from ..transcribe import SourceTranscript, Word
from . import reader
from .index import ROOT, RushIndex

STRETCH = 600.0      # seconds transcribed at once (and saved)
OVERLAP = 1.0        # each stretch reaches this far into its neighbours, for words on the seam
MODELS = ("large-v3", "large-v3-turbo")
LANGUAGES = ("fr", "en", "auto")
CONTEXT = 8          # words shown around a hit

_MEMO: dict = {}     # transcript file -> (mtime, SourceTranscript, tokens, token -> word, candidates by size)


# --- where the words are ---------------------------------------------------------------------

def _ix(rush, root: Path = ROOT) -> RushIndex:
    return rush if isinstance(rush, RushIndex) else RushIndex(Path(rush), root)


def label(model: str, track: int) -> str:
    """The cache's model name: track 0 shares the Derush's transcripts, the others get their own."""
    return model if not track else f"{model}#a{track}"


def track_for(ix: RushIndex) -> int:
    """The audio track to transcribe: the one with the most YAMNet "Speech" in the index."""
    n = ix.audio_tracks
    if n <= 1 or not ix.done():
        return 0
    from .rules import sound_names
    names = sound_names()
    if "Speech" not in names:
        return 0
    col = names.index("Speech")
    return int(np.argmax([float(ix.tags(k)[:, col].sum()) for k in range(n)]))


def _duration(ix: RushIndex) -> float:
    return ix.duration or reader.probe(ix.path).duration


def _covers(st: SourceTranscript, duration: float) -> bool:
    return bool(st.covered) and not st.missing([(0.0, max(0.0, duration - 1.0))])


def transcript(rush, root: Path = ROOT, duration: float | None = None) -> SourceTranscript | None:
    """The transcript of the whole rush, or None when it has not been read (completely) yet."""
    ix = _ix(rush, root)
    if not ix.path.exists():
        return None
    try:
        known = json.loads((ix.dir / "speech.json").read_text(encoding="utf-8"))
        tries = [(label(known["model"], int(known.get("track", 0))), known["language"])]
    except (OSError, ValueError, KeyError, TypeError):
        tries = []
    tries += [(m, lang) for m in MODELS for lang in LANGUAGES]      # e.g. a rush the Derush transcribed
    dur = duration or _duration(ix)
    for model, lang in tries:
        st = _load(ix.path, model, lang)
        if st is not None and _covers(st, dur):
            return st
    return None


def _cache_file(path: Path, model: str, language: str) -> Path:
    """transcribe.SourceTranscript's file, without reading it."""
    import hashlib
    from .. import transcribe
    ident = hashlib.sha1(f"{path.name.lower()}|{path.stat().st_size}|{model}|{language}".encode()).hexdigest()
    return transcribe.CACHE_DIR / f"{ident}.json"


def _load(path: Path, model: str, language: str) -> SourceTranscript | None:
    """The cached transcript (read again only when its file changed), None when there is none."""
    file = _cache_file(path, model, language)
    try:
        mtime = file.stat().st_mtime_ns
    except OSError:
        return None
    memo = _MEMO.get(str(file))
    if memo and memo["mtime"] == mtime:
        return memo["st"]
    st = SourceTranscript(path, model, language)
    _MEMO[str(file)] = {"mtime": mtime, "st": st}
    return st


def done(rush, root: Path = ROOT) -> bool:
    return transcript(rush, root) is not None


def words(rush, root: Path = ROOT) -> list[Word]:
    """Every word said in the rush, in time order ([] when it has not been read yet: see done())."""
    st = transcript(rush, root)
    return list(st.words) if st else []


def status(rush, root: Path = ROOT, duration: float | None = None) -> dict:
    """What the page shows: {"done": bool, "words": n}."""
    st = transcript(rush, root, duration)
    return {"done": st is not None, "words": len(st.words) if st else 0}


# --- reading it ------------------------------------------------------------------------------

def transcribe(rush, transcriber, root: Path = ROOT, log=print, should_stop=None) -> SourceTranscript | None:
    """Transcribe what the cache does not hold yet, 10 minutes at a time (saved after each).
    `transcriber` is a transcribe.Transcriber (its language None: whisper finds it)."""
    ix = _ix(rush, root)
    rec = reader.probe(ix.path)
    if not rec.audio:
        log(f"  {ix.path.name}: no audio track")
        return None
    k = min(track_for(ix), len(rec.audio) - 1)
    lang = transcriber.language or "auto"
    model = label(transcriber.model_name, k)
    st = SourceTranscript(ix.path, model, lang)
    pieces = []
    for a, b in st.missing([(0.0, rec.duration)]):
        x = a
        while x < b - 0.5:
            pieces.append((x, min(b, x + STRETCH)))
            x = pieces[-1][1]
    total = sum(b - a for a, b in pieces)
    if not pieces:
        log("  already transcribed")
    elif total < rec.duration - 1:
        log(f"  {(rec.duration - total) / 60:.0f} min already transcribed, {total / 60:.0f} min to go")
    if len(rec.audio) > 1:
        log(f"  audio track {k + 1} of {len(rec.audio)} (the most speech)")
    done_s = 0.0
    for a, b in pieces:
        if should_stop and should_stop():
            return None
        s0, s1 = max(0.0, a - OVERLAP), min(rec.duration, b + OVERLAP)
        audio = reader.audio(rec, k, s0, s1 - s0)
        end = s0 + len(audio) / reader.SR

        def progress(t, base=done_s, s0=s0, a=a):
            seen = max(0.0, min(t + s0 - a, b - a))
            log("\r" + f"  transcribing {min(1.0, (base + seen) / max(total, 1e-9)):6.1%}", end="", flush=True)

        heard = transcriber(audio, progress) if len(audio) else []
        st.add(s0, max(end, s0), [Word(w.text, round(w.start + s0, 3), round(w.end + s0, 3), w.prob) for w in heard])
        st.save()
        done_s += b - a
    if pieces:
        log("\r" + f"  transcribing {1:6.1%}")
    ix.dir.mkdir(parents=True, exist_ok=True)
    tmp = ix.dir / "speech.tmp"
    tmp.write_text(json.dumps({"model": transcriber.model_name, "language": lang, "track": k,
                               "words": len(st.words)}), encoding="utf-8")
    os.replace(tmp, ix.dir / "speech.json")
    return st


# --- searching it ----------------------------------------------------------------------------

def norm(text: str) -> list[str]:
    """Lower case, no accents, no punctuation: the tokens a text is matched on ("J'suis" -> j, suis)."""
    s = unicodedata.normalize("NFKD", text.lower().replace("œ", "oe").replace("æ", "ae"))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", s)


def _tokenize(ws: list[Word]) -> tuple[list[str], list[int], dict]:
    """(tokens, the word each token comes from, candidate strings by window size: filled by find_in)."""
    toks, owner = [], []
    for i, w in enumerate(ws):
        for tok in norm(w.text):
            toks.append(tok)
            owner.append(i)
    return toks, owner, {}


def _tokens(st: SourceTranscript) -> tuple[list[str], list[int], dict]:
    """_tokenize(st.words), kept with the memoized transcript (a 10 h rush: ~100 000 words)."""
    memo = next((m for m in _MEMO.values() if m["st"] is st), None)
    if memo is None:
        return _tokenize(st.words)
    if "tokens" not in memo:
        memo["tokens"] = _tokenize(st.words)
    return memo["tokens"]


def join(ws: list[Word]) -> str:
    """Words as a phrase: whisper's "d" + "'ici" give "d'ici", "Peut" + "-être" "Peut-être"."""
    out = ""
    for w in ws:
        out += w.text if not out or w.text[:1] in "'’-" or out[-1:] in "'’" else " " + w.text
    return out


def _cutoff(q: str) -> float:
    """How alike a stretch of the transcript must be (rapidfuzz ratio) to count, by query length."""
    n = len(q.replace(" ", ""))
    return 100.0 if n <= 3 else 85.0 if n <= 5 else 87.0


def find_in(ws: list[Word], query: str, tokens=None) -> list[dict]:
    """Where `query` is said among `ws`: [{start, end, text, match, score}] in time order."""
    from rapidfuzz import fuzz, process
    q = norm(query)
    if not q or not ws:
        return []
    toks, owner, cands = tokens if tokens is not None else _tokenize(ws)
    if not toks:
        return []
    qs, qf = " ".join(q), "".join(q)
    cutoff = _cutoff(qs)
    found = []
    for size in sorted({max(1, len(q) - 1), len(q), len(q) + 1}):
        if size > len(toks):
            continue
        if size not in cands:
            cands[size] = ([" ".join(toks[i:i + size]) for i in range(len(toks) - size + 1)],
                           ["".join(toks[i:i + size]) for i in range(len(toks) - size + 1)])
        spaced, flat = cands[size]
        a = process.cdist([qs], spaced, scorer=fuzz.ratio, score_cutoff=cutoff, workers=1)[0]
        b = process.cdist([qf], flat, scorer=fuzz.ratio, score_cutoff=cutoff, workers=1)[0]
        best = np.maximum(a, b) - (0 if size == len(q) else 5)    # a word more or less: a little less alike
        for i in np.flatnonzero(best >= cutoff):
            found.append((float(best[i]), -abs(size - len(q)), int(i), size))
    found.sort(reverse=True)
    taken: list[tuple[int, int]] = []
    hits = []
    for score, _, i, size in found:
        w0, w1 = owner[i], owner[i + size - 1]
        if any(w0 <= b and a <= w1 for a, b in taken):
            continue
        taken.append((w0, w1))
        c0 = max(0, w0 - 3)
        c1 = min(len(ws) - 1, max(w1 + 3, c0 + CONTEXT - 1))
        while c0 > 0 and ws[c0].text[:1] in "'’-":                   # not half a word ("'est")
            c0 -= 1
        while c1 < len(ws) - 1 and ws[c1 + 1].text[:1] in "'’-":
            c1 += 1
        # whisper sometimes dates a segment's first word long before the rest ("Oh" 22 s before "my god"):
        # the phrase is where its last words are
        s0 = max((k for k in range(w0 + 1, w1 + 1) if ws[k].start - ws[k - 1].end > 2.0), default=w0)
        hits.append({"start": ws[s0].start, "end": ws[w1].end, "score": round(score / 100, 3),
                     "match": join(ws[w0:w1 + 1]),
                     "text": ("… " if c0 > 0 else "") + join(ws[c0:c1 + 1])
                             + (" …" if c1 < len(ws) - 1 else "")})
    hits.sort(key=lambda h: h["start"])
    return hits


def search(rush, query: str, root: Path = ROOT) -> list[dict]:
    """Where `query` is said in the rush ([] when its speech has not been read yet)."""
    st = transcript(rush, root)
    if st is None:
        return []
    return find_in(st.words, query, _tokens(st))


def said_seconds(rush, phrases: list[str], seconds: int, window: float = 3.0,
                 root: Path = ROOT) -> np.ndarray | None:
    """1 on the seconds where one of the phrases is said (± window / 2), 0 elsewhere; None when the
    speech of the rush has not been read yet (the rule cannot know)."""
    st = transcript(rush, root)
    if st is None:
        return None
    x = np.zeros(seconds, np.float32)
    half = max(0.0, float(window)) / 2
    for p in phrases:
        for h in find_in(st.words, p, _tokens(st)):
            a, b = int(np.floor(h["start"] - half)), int(np.ceil(h["end"] + half))
            x[max(0, a): max(0, min(seconds, b))] = 1.0
    return x
