"""From what happens on screen to sound cues: which kind of sound, which take, where and how loud.

Gold standard, not the bare minimum: every visible change can get a sound; density only decides how
small a change still deserves one and how close two sounds may come. Takes rotate from a pool per kind
(never the same one twice in a row) and their level varies slightly, as a sound editor would do by hand.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import library as L
from .events import Event

RULES = {   # what happens on screen -> kind of sound ("" = nothing)
    "transition": "whoosh",
    "appear.full": "whoosh",
    "appear.element": "pop",
    "appear.layer": "whoosh",
    "title": "pop",
    "move": "whoosh",
    "motion.full": "whoosh",
    "motion.element": "click",
    "motion.text": "typing",
    "exit": "whoosh",
}
DENSITY = {1: (0.70, 0.50), 2: (0.45, 0.25), 3: (0.25, 0.12)}    # level -> (min strength, min gap s)
MIN_GAP = {"whoosh": 0.60, "hit": 0.8}                              # a kind never closer to itself than this
TARGET_PEAK = {"whoosh": -15.0, "click": -17.0, "pop": -17.0, "typing": -15.0, "hit": -13.0}
# clip gain in Premiere: always in this range, whatever the file's mastering (the user's own edits: whooshes
# -5 / -10, clicks and typing around -15, never under -20 or over -5 for a hot or a quiet file)
SFX_GAIN = (-20.0, -5.0)
LEAD = {"whoosh": 0.04}          # a whoosh peaks just after the cut; attacks land on the frame
POOL = 8                         # takes per kind
MAX_DUR = {"whoosh": 1.8, "click": 0.8, "pop": 1.2, "hit": 3.5, "typing": 12.0}   # longer takes: search only


def rule_key(e: Event) -> str:
    if e.kind in ("appear", "motion"):
        return f"{e.kind}.{e.size or 'element'}"
    return e.kind


def learn(events: list[Event], min_votes: int = 4, share: float = 0.6) -> dict[str, str]:
    """The user's own habits, from the sounds already in their edit: for each kind of moment that got
    enough sounds, the kind of sound they chose most (a clear majority only)."""
    votes: dict[str, dict[str, int]] = {}
    seen: set[tuple[str, int]] = set()
    for e in sorted(events, key=lambda e: -e.strength):     # a sound votes once, for the strongest moment
        kind = L.kind_of(e.covered) if e.covered else ""
        if kind and (e.covered, round(e.t * 4)) not in seen:
            seen.add((e.covered, round(e.t * 4)))
            v = votes.setdefault(rule_key(e), {})
            v[kind] = v.get(kind, 0) + 1
    out = {}
    for key, v in votes.items():
        kind, n = max(v.items(), key=lambda kv: kv[1])
        if n >= min_votes and n / sum(v.values()) >= share:
            out[key] = kind
    return out


@dataclass
class Cue:
    id: int
    t: float                   # the moment it hits (sequence s)
    kind: str
    rule: str                  # which rule placed it (appear.full …)
    event: dict
    sound: dict                # library.Snd as JSON
    start: float = 0.0         # file start in the sequence
    src_in: float = 0.0        # where in the file
    length: float = 0.0
    gain_db: float = 0.0
    on: bool = True
    edited: bool = False       # touched on the page: kept as it is when planning again

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class Settings:
    density: int = 2
    volume: float = 0.0                          # dB on every cue
    rules: dict = field(default_factory=lambda: dict(RULES))
    keep_existing: bool = True                   # no sound where the edit already has one
    seed: int = 1


def fit(cue: Cue, snd: L.Snd, s: Settings, rng: random.Random | None = None) -> Cue:
    """Put a take on a cue: sync point on the frame, length, level."""
    lead = LEAD.get(cue.kind, 0.0)
    start = cue.t + lead - snd.sync
    src_in = 0.0
    if start < 0:
        src_in, start = -start, 0.0
    length = snd.dur - src_in
    if cue.kind == "typing":
        length = min(length, max(0.5, cue.event.get("dur") or 0.8))
    length = max(0.05, min(length, 4.0))
    jitter = (rng.uniform(-1.5, 1.5) if rng else 0.0)
    weight = (cue.event.get("strength", 0.7) - 0.7) * 5           # bigger change, a little louder
    extra = -4.0 if cue.rule == "exit" else 0.0
    gain = sfx_gain(cue.kind, snd.peak_db, weight + extra + jitter) + s.volume
    cue.sound, cue.start, cue.src_in, cue.length = snd.to_json(), round(start, 4), round(src_in, 4), round(length, 4)
    cue.gain_db = round(max(-40.0, min(6.0, gain)), 2)        # Premiere caps clip gain at +6 dB
    return cue


def sfx_gain(kind: str, peak_db: float, nudge: float = 0.0) -> float:
    """The clip gain a sound effect gets: its peak brought to its kind's level, kept in SFX_GAIN."""
    lo, hi = SFX_GAIN
    return round(max(lo, min(hi, TARGET_PEAK.get(kind, -17.0) - peak_db + nudge)), 1)


class Bag:
    """Takes of one kind in shuffled rounds: every take before any repeats, never twice in a row."""

    def __init__(self, items: list[L.Snd], rng: random.Random):
        self.items, self.rng, self.left, self.last = items, rng, [], None

    def draw(self) -> L.Snd:
        if not self.left:
            self.left = self.items[:]
            self.rng.shuffle(self.left)
            if len(self.left) > 1 and self.left[-1].id == getattr(self.last, "id", None):
                self.left[0], self.left[-1] = self.left[-1], self.left[0]
        self.last = self.left.pop()
        return self.last


def plan(events: list[Event], pools: dict[str, list[L.Snd]], s: Settings,
         keep: list[Cue] | None = None) -> list[Cue]:
    """Cues for the events, strongest first so density drops the small ones. `keep`: cues edited on
    the page, kept as they are (their neighbours make room)."""
    floor, gap = DENSITY.get(s.density, DENSITY[2])
    rng = random.Random(s.seed)
    chosen: list[tuple[Event, str, str]] = []
    taken: list[tuple[float, str]] = [(c.t, c.kind) for c in keep or [] if c.on]
    for e in sorted(events, key=lambda e: -e.strength):
        key = rule_key(e)
        kind = s.rules.get(key, RULES.get(key, ""))
        if not kind or kind not in pools or not pools[kind] or e.strength < floor:
            continue
        if s.keep_existing and e.covered:
            continue
        if any(abs(t - e.t) < gap or (k == kind and abs(t - e.t) < MIN_GAP.get(kind, 0)) for t, k in taken):
            continue
        taken.append((e.t, kind))
        chosen.append((e, kind, key))
    chosen.sort(key=lambda c: c[0].t)
    bags = {k: Bag(v, random.Random(f"{s.seed}-{k}")) for k, v in pools.items() if v}
    cues = [c for c in keep or []]
    n = max((c.id for c in cues), default=0)
    for e, kind, key in chosen:
        n += 1
        cues.append(fit(Cue(n, round(e.t, 4), kind, key, e.to_json(), {}), bags[kind].draw(), s, rng))
    cues.sort(key=lambda c: c.t)
    return cues


# --- pools -----------------------------------------------------------------------------------------

def pools(kinds: set[str], sources: list[str], folders: list[str], dest: Path, log=print) -> dict[str, list[L.Snd]]:
    """Up to POOL ready takes per kind, from the sources in the user's order: their folders, their
    Epidemic subscription, then the built-in bank."""
    out: dict[str, list[L.Snd]] = {k: [] for k in kinds}
    scanned = None
    ep = None
    for src in sources:
        need = [k for k in kinds if len(out[k]) < POOL]
        if not need:
            break
        if src == "folder" and folders:
            if scanned is None:
                log(f"  dossiers de sons : {len(folders)}")
                scanned = L.scan(folders, log)
            for k in need:
                mine = [x for x in scanned if x.kind == k and x.dur <= MAX_DUR.get(k, 4)]
                random.Random(k).shuffle(mine)
                out[k] += mine[: POOL - len(out[k])]
        elif src == "epidemic" and L.epidemic_key():
            try:
                ep = ep or L.Epidemic(L.epidemic_key())
                for k in need:
                    found = [x for x in ep.search(L.EPIDEMIC_QUERIES[k], k, n=POOL * 2) if x.dur <= MAX_DUR.get(k, 4)]
                    log(f"  Epidemic « {L.EPIDEMIC_QUERIES[k]} » : {len(found)} sons")
                    for snd in found[: POOL - len(out[k])]:
                        try:
                            out[k].append(ep.download(snd, dest))
                        except Exception as exc:          # one refused file: the others still come
                            log(f"    {snd.name[:50]} : {exc}")
            except Exception as exc:
                log(f"  Epidemic : {exc}")
        elif src == "earshot" and L.earshot_ok():
            for k in need:
                members = L.earshot_sounds(k)
                random.Random(f"es-{k}").shuffle(members)
                want = POOL - len(out[k])
                for i in range(want):
                    m = members[i % len(members)]
                    log(f"  earshot : {m.name} ({k})")
                    out[k].append(L.render_take(m, seed=101 + i))
    return out
