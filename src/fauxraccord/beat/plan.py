"""Where the cuts go on the music, and which rush (and which moment of it) fills each shot.

Everything the page can change is in one dict, `settings` (per project, saved by the window):

    on       "beat" | "off" (between two beats) | "half" (both) | "bar" (first beat of each bar) | "accent" (hits)
    every    keep one cut in N of those
    shift    which one of the N (0..N-1): « every 2 beats » on 1-3 or on 2-4
    follow   cut more where the music is loud, less where it is quiet
    tempo    1, 2 (double) or 0.5 (half): when the detected tempo is twice or half the felt one
    phase    which beat starts a bar (0..meter-1), detected, can be moved
    nudge    frames added to every cut (negative: the picture changes a bit before the beat)
    min_len  shortest shot (s)
    range    [start, end] of the music used (s), None: all of it
    add/del  cuts placed or removed by hand (seconds on the music)
    holds    [[a, b], …] stretches of the music with no cut (« pas de coupe ici »); a cut added by hand inside wins
    order    "order" | "shuffle"  the rushes one after the other, or mixed (never twice in a row)
    take     "start" | "spread" | "random"  where in each rush: from its start on, spread over all of it, anywhere
    seed     the draw for shuffle/random (« Autre tirage » adds one)
    shots    {"<start ms>": {"src": id, "in": s}}  a shot changed by hand: its rush and its in-point
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .analysis import Analysis

DEFAULTS = {"on": "beat", "every": 2, "shift": 0, "follow": False, "tempo": 1, "phase": None, "nudge": 0,
            "min_len": 0.3, "range": None, "add": [], "del": [], "holds": [], "order": "shuffle", "take": "spread", "seed": 0,
            "shots": {}}
SNAP = 0.03          # a hand-removed cut matches a computed one this close (s)


@dataclass
class Source:
    """A usable stretch of one rush: a whole file, or one clip of a sequence (its in and out)."""
    id: str
    path: str
    name: str
    start: float
    end: float
    on: bool = True

    @property
    def length(self) -> float:
        return max(0.0, self.end - self.start)


def settings_of(saved: dict | None) -> dict:
    out = {**DEFAULTS, **(saved or {})}
    out["every"] = max(1, int(out.get("every") or 1))
    out["shift"] = int(out.get("shift") or 0) % out["every"]
    return out


# --- the grid ---------------------------------------------------------------------------------------

def grid(a: Analysis, tempo: float = 1, phase: int | None = None) -> tuple[list[float], list[bool]]:
    """The beats (after a tempo correction) and which of them start a bar."""
    beats = list(a.beats)
    phase = a.phase if phase is None else int(phase) % a.meter
    down = [(i - phase) % a.meter == 0 for i in range(len(beats))]
    if tempo == 2 and len(beats) > 1:
        b2, d2 = [], []
        for i, b in enumerate(beats):
            b2.append(b)
            d2.append(down[i])
            if i + 1 < len(beats):
                b2.append((b + beats[i + 1]) / 2)
                d2.append(False)
        beats, down = b2, d2
    elif tempo == 0.5 and len(beats) > 1:
        keep = phase % 2                             # keep the beats that carry the bar starts
        beats, down = beats[keep::2], down[keep::2]
    return beats, down


def offbeats(beats: list[float]) -> list[float]:
    return [(a + b) / 2 for a, b in zip(beats[:-1], beats[1:])]


def energy_at(a: Analysis, t: float) -> float:
    """The music's loudness (0..1) at t: that of the beat interval it falls in."""
    if not a.energy or not a.beats:
        return 0.5
    import bisect
    i = max(0, min(len(a.energy) - 1, bisect.bisect_right(a.beats, t) - 1))
    return a.energy[i]


def candidates(a: Analysis, s: dict) -> list[float]:
    """Every place the chosen kind of cut could go, before « one in N »."""
    beats, down = grid(a, s["tempo"], s["phase"])
    on = s["on"]
    if on == "off":
        return offbeats(beats)
    if on == "half":
        return sorted(beats + offbeats(beats))
    if on == "bar":
        return [b for b, d in zip(beats, down) if d]
    if on == "accent":
        thr = 0.35
        return [t for t, v in a.onsets if v >= thr]
    return beats


def cuts(a: Analysis, s: dict, fps: float = 25.0) -> list[float]:
    """The cut times on the music (s, not shifted by the range start), sorted."""
    s = settings_of(s)
    lo, hi = s["range"] or (0.0, a.duration)
    cand = candidates(a, s)
    # count « one in N » from a bar start, so « every 2 beats » lands on 1 and 3, « every 4 » on the 1
    beats, down = grid(a, s["tempo"], s["phase"])
    first_bar = next((b for b, d in zip(beats, down) if d), beats[0] if beats else 0.0)
    anchor = next((i for i, t in enumerate(cand) if t >= first_bar - 1e-6), 0)
    every = s["every"]
    if s["on"] == "accent":                          # hits are not regular: N means the strongest 1/N
        strength = dict(a.onsets)
        if every > 1 and cand:
            ranked = sorted(cand, key=lambda t: -strength.get(t, 0))
            cand = sorted(ranked[: max(1, len(cand) // every)])
        picked = cand
    elif s["follow"]:
        picked, last = [], None
        for i, t in enumerate(cand):
            e = energy_at(a, t)
            step = every * (1 if e >= 0.66 else 2 if e >= 0.33 else 4)
            if (i - anchor - s["shift"]) % step == 0 and (last is None or i - last >= step // 2):
                picked.append(t)
                last = i
    else:
        picked = [t for i, t in enumerate(cand) if (i - anchor - s["shift"]) % every == 0]
    dels = sorted(float(x) for x in s["del"])
    holds = [(min(a, b), max(a, b)) for a, b in (s["holds"] or [])]
    picked = [t for t in picked if not any(abs(t - d) <= SNAP for d in dels)
              and not any(a <= t <= b for a, b in holds)]
    hand = {round(float(x), 4) for x in s["add"]}
    # a computed cut too close to a hand one gives way to it (clicking next to a cut moves it)
    picked = [t for t in picked if not any(abs(t - h) < s["min_len"] for h in hand)]
    picked = sorted(set(round(t, 4) for t in picked) | hand)
    nudge = s["nudge"] / fps
    out, prev = [], lo
    for t in picked:
        t = t + nudge
        if lo + s["min_len"] - 1e-6 <= t <= hi - s["min_len"] + 1e-6 and t - prev >= s["min_len"] - 1e-6:
            out.append(round(t, 4))
            prev = t
    return out


# --- the shots ----------------------------------------------------------------------------------------

def _no_repeat(ids: list[str], n: int, rng: random.Random) -> list[str]:
    """n picks, every rush once per round in a random order, never the same twice in a row."""
    out: list[str] = []
    while len(out) < n:
        bag = ids[:]
        rng.shuffle(bag)
        if out and len(bag) > 1 and bag[0] == out[-1]:
            bag[0], bag[-1] = bag[-1], bag[0]
        out.extend(bag)
    return out[:n]


def key(t0: float) -> str:
    return str(int(round(t0 * 1000)))


def shots(cut_times: list[float], sources: list[Source], s: dict, duration: float) -> list[dict]:
    """The shots between the cuts: {t0, t1 (on the music), src, in (in the rush), hand, short}."""
    s = settings_of(s)
    lo, hi = s["range"] or (0.0, duration)
    bounds = [lo, *cut_times, hi]
    pool = [x for x in sources if x.on and x.length > 0]
    if not pool:
        return [{"t0": a, "t1": b, "src": "", "in": 0.0, "hand": False, "short": False} for a, b in zip(bounds[:-1], bounds[1:])]
    by_id = {x.id: x for x in sources}
    rng = random.Random(s["seed"])
    n = len(bounds) - 1
    hand = {}
    for k, v in (s["shots"] or {}).items():
        try:
            hand[int(k)] = v
        except (TypeError, ValueError):
            pass

    def manual(t0: float):
        ms = int(round(t0 * 1000))
        for d in (0, *range(1, int(SNAP * 1000) + 1)):
            for m in (ms - d, ms + d):
                if m in hand and hand[m].get("src") in by_id:
                    return hand[m]
        return None

    ids = [x.id for x in pool]
    order = _no_repeat(ids, n, rng) if s["order"] == "shuffle" else [ids[i % len(ids)] for i in range(n)]
    lengths = [b - a for a, b in zip(bounds[:-1], bounds[1:])]
    # how many shots each rush gets (for « spread »), and a cursor per rush (for « start »)
    uses: dict[str, int] = {}
    for i in range(n):
        if not manual(bounds[i]):
            uses[order[i]] = uses.get(order[i], 0) + 1
    seen: dict[str, int] = {}
    cursor: dict[str, float] = {x.id: x.start for x in pool}
    out = []
    for i in range(n):
        t0, t1, ln = bounds[i], bounds[i + 1], lengths[i]
        m = manual(t0)
        if m:
            src = by_id[m["src"]]
            start = float(m.get("in", src.start))
        else:
            src = by_id[order[i]]
            if src.length < ln:                      # too short for this shot: the next rush that fits
                fit = [x for x in pool if x.length >= ln]
                if fit:
                    src = fit[(ids.index(src.id) + i) % len(fit)] if src.id in ids else fit[0]
            k = seen.get(src.id, 0)
            seen[src.id] = k + 1
            room = max(0.0, src.length - ln)
            if s["take"] == "start":
                start = cursor[src.id]
                if start + ln > src.end:             # came to its end: from the top again
                    start = src.start
                cursor[src.id] = start + ln
            elif s["take"] == "random":
                start = src.start + rng.random() * room
            else:                                    # spread: the k-th of u uses at the middle of its 1/u part
                u = max(1, uses.get(src.id, 1))
                start = src.start + room * ((k + 0.5) / u)
        start = min(max(src.start, start), max(src.start, src.end - ln))
        out.append({"t0": round(t0, 4), "t1": round(t1, 4), "src": src.id, "in": round(start, 3),
                    "hand": bool(m), "short": src.length + 1e-6 < ln})
    return out
