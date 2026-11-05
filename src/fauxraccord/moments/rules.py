"""Kinds of moment: rules over the index that give stretches of time.

A kind of moment (MomentType, JSON in presets/ and in the project) is a few signals combined with
"all" (and) or "any" (or). Every signal gives one value per second of the rush and a threshold:

  words  {"words": [...], "not": [...], "z": 3}         frames that look like the words, compared
                                                          to the rest of the rush (robust z-score)
  like   {"like": [{"rush": path, "t": s}], "unlike": [...], "min": 0.85}
                                                          frames close to examples picked by the user;
                                                          an example can also be a stored image vector
                                                          {"vector": [...], "model": "clip"} (presets ship
                                                          screens that look the same for every player)
  sound  {"sound": [AudioSet names], "track": "any"|k, "window": s, "min": p}
                                                          how strongly those sounds are heard, averaged
  loud   {"loud": "any"|k, "min_db": -15, "window": s}  the loudest 100 ms of each second
  zone   {"zone": [x, y, w, h], "side": "left", "below": 0.3}   a gauge under a level (life low)
         {"zone": [...], "side": ..., "drop": 0.15, "within": 3}  …or falling fast (being hit)
  text   {"text": [words], "zone": [x, y, w, h], "window": 4, "every": 2, "scan": 6}
                                                          one of the words written in the zone (a
                                                          notification, a kill feed), read at full
                                                          resolution only where the kind's other signals
                                                          already pass, or (a kind made of text only)
                                                          around what a scan every 6 s found: reading
                                                          costs ~0.3 s a frame
  look   {"zone": [x, y, w, h], "look": {"rush": path, "t": s}, "z": 3}
                                                          the zone looks like it did at that moment (an
                                                          icon, a banner, a kill-feed line appears);
                                                          a game pack stores {"vector": [...], "shape": [h, w]}
  learn  {"learn": true}                               taught by example (learn.py): the kind's examples
                                                          and ✓ against its ✗ and the rest of the rushes
                                                          (a game pack stores them as fingerprints:
                                                          examples "pos_vectors" / "neg_vectors")
  said   {"said": ["je suis mort", "on raid"], "window": 3}
                                                          one of the phrases is said (± window / 2), from
                                                          the rush's transcript (speech.py); unknown (NaN)
                                                          while the speech has not been read: never
                                                          transcribes on its own
  intensity {"intensity": "high", "min": 0.85} / {"intensity": "low", "max": 0.15}
                                                          the rush's most / least intense stretches
                                                          (intensity.py: action, voice, pace, words…)
  opposite {"opposite": {signal}}                      the opposite of a signal

A preset kind with both ✓ and ✗ also gets a filter trained on ✓ against ✗ (learn.py): its moments must
look and sound more like the ✓ than like the ✗.

The margin of a signal is how far its value is past the threshold, in that signal's own unit
(SCALE). `sensitivity` (0..1, 0.5 = as written) moves every threshold by up to 1.5 units.
Seconds where the combined margin is ≥ 0 form stretches: closer than `gap` are merged, shorter
than `min_len` dropped. An "event" (death) is anchored on its first second and keeps `before` and
`after` around it; a "state" (fight, building) keeps the whole stretch plus the margins.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .index import RushIndex
from .models import Sounds, Vision

PRESETS = Path(__file__).with_name("presets")
SCALE = {"intensity": 0.05, "look": 1.0, "learn": 0.5, "text": 1.0, "words": 1.0, "like": 0.05, "sound": 0.1, "loud": 6.0, "below": 0.1, "drop": 0.1,
         "said": 0.3}   # said: 0 or 1, so the sensitivity (±0.45) never flips it
_SOUND_NAMES: list[str] | None = None


@dataclass
class MomentType:
    id: str
    name: str
    color: str = "#e0a040"
    mode: str = "state"              # "event" | "state"
    combine: str = "all"             # "all" | "any"
    signals: list[dict] = field(default_factory=list)
    before: float = 3.0
    after: float = 3.0
    gap: float = 5.0
    min_len: float = 1.0
    sensitivity: float = 0.5
    enabled: bool = True
    remove: bool = False             # dead time (menus, loading): the XML also gives each rush without it
    hint: str = ""
    examples: dict = field(default_factory=lambda: {"pos": [], "neg": []})   # [{rush, start, end}]
    explain: dict = field(default_factory=dict)       # what the last search learned (learn.Model.explain)
    user: bool = False               # made by the user (can be deleted)                   # what the user still has to do for it to work (e.g. draw a box)

    @classmethod
    def from_json(cls, d: dict) -> "MomentType":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def to_json(self) -> dict:
        return asdict(self)

    def ready(self) -> bool:
        if any("learn" in s for s in self.signals) and not (self.examples.get("pos") or self.examples.get("pos_vectors")):
            return False
        return self.enabled and bool(self.signals) and all(_ready(s) for s in self.signals)

    def core(self, m: "Moment") -> dict:
        """What a marked moment shows, without the seconds kept around it."""
        if self.mode == "event":
            a, b = m.anchor, min(m.end, m.anchor + max(1.0, min(self.after, 3.0)))
        else:
            a, b = m.start + self.before, m.end - self.after
            if b - a < 1:
                a, b = m.anchor, m.anchor + 1
        return {"rush": m.rush, "start": round(a, 2), "end": round(b, 2)}


def _has_text(sig: dict) -> bool:
    return "text" in sig or ("opposite" in sig and _has_text(sig["opposite"]))


def _ready(sig: dict) -> bool:
    if "any" in sig:
        return any(_ready(x) for x in sig["any"])
    if "opposite" in sig:
        return _ready(sig["opposite"])
    if "zone" in sig:
        return bool(sig["zone"])
    if "like" in sig:
        return bool(sig["like"])
    if "said" in sig:
        return bool(sig["said"])
    return True


@dataclass
class Moment:
    type: str
    rush: str
    start: float
    end: float
    anchor: float
    score: float            # 0..1, how far past the thresholds at its strongest
    kept: bool | None = None   # the user's ✓ (True) or ✗ (False)

    def to_json(self) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def describe(sig: dict) -> dict | None:
    """A zone signal as the page shows it: {read, words|below|drop, negate, box}; None for the others."""
    neg = False
    while "opposite" in sig:
        sig, neg = sig["opposite"], not neg
    if "said" in sig:                    # words said (speech.py): a tag too, without a box
        return {"read": "said", "words": list(sig["said"]), "negate": neg, "box": None}
    if not sig.get("zone"):
        return None
    out = {"box": sig["zone"], "negate": neg}
    if "text" in sig:
        out.update(read="text", words=list(sig["text"]))
    elif "look" in sig:
        out.update(read="look", t=sig["look"].get("t"))
    elif "drop" in sig:
        out.update(read="gauge", drop=sig["drop"])
    else:
        out.update(read="gauge", below=sig.get("below", 0.3))
    return out


def load_preset(name: str) -> list[MomentType]:
    """A built-in preset (presets/<name>.json) or an imported game pack ("pack:<id>", packs.py)."""
    if name.startswith("pack:"):
        from .packs import load
        data = load(name)
    else:
        data = json.loads((PRESETS / f"{name}.json").read_text(encoding="utf-8"))
    return [MomentType.from_json(d) for d in data["types"]]


def presets() -> list[dict]:
    """The built-in presets, then the imported game packs ({"pack": True, "game": …})."""
    from .packs import imported
    out = []
    for f in sorted(PRESETS.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        out.append({"id": f.stem, "name": d.get("name", f.stem), "types": len(d.get("types", []))})
    return out + imported()


def sound_names() -> list[str]:
    global _SOUND_NAMES
    if _SOUND_NAMES is None:
        _SOUND_NAMES = Sounds().names()
    return _SOUND_NAMES


# --- per-second values ----------------------------------------------------------------------

def _hold(times: np.ndarray, values: np.ndarray, seconds: int, reach: float) -> np.ndarray:
    """Frame values spread to the seconds grid (nearest frame within `reach` s; NaN beyond)."""
    out = np.full(seconds, np.nan, np.float32)
    if not len(times):
        return out
    centre = np.arange(seconds) + 0.5
    k = np.clip(np.searchsorted(times, centre), 1, len(times) - 1) if len(times) > 1 else np.zeros(seconds, int)
    if len(times) > 1:
        left = k - 1
        k = np.where(np.abs(times[left] - centre) <= np.abs(times[k] - centre), left, k)
    near = np.abs(times[k] - centre) <= reach
    out[near] = values[k[near]]
    return out


def _smooth(x: np.ndarray, window: float) -> np.ndarray:
    w = max(1, int(round(window)))
    if w <= 1:
        return x
    return np.convolve(x, np.ones(w) / w, mode="same").astype(np.float32)


def _robust_z(x: np.ndarray) -> np.ndarray:
    ok = np.isfinite(x)
    if ok.sum() < 5:
        return np.zeros_like(x)
    med = np.median(x[ok])
    mad = np.median(np.abs(x[ok] - med)) * 1.4826
    return (x - med) / max(mad, 1e-4)


class Signals:
    """Computes signals for one rush, keeping what can be reused (frame vectors, word vectors)."""

    def __init__(self, ix: RushIndex, vision: Vision | None = None, examples: dict | None = None):
        self.ix = ix
        self.vision = vision
        self.n = ix.seconds()
        self.reach = 1.5 * float(ix.meta.get("step", 2.0)) + 0.5
        self._examples = examples if examples is not None else {}
        self.candidates: np.ndarray | None = None     # seconds where text may be read
        self.models: dict = {}       # kind id -> learn.Model of its {"learn"} signal
        self.filters: dict = {}      # kind id -> learn.Model trained on ✓ against ✗
        self._kind = ""

    def _vision(self) -> Vision:
        if self.vision is None:
            self.vision = Vision(self.ix.meta.get("vision", "clip"))
        return self.vision

    def example(self, e: dict) -> np.ndarray:
        if "vector" in e:
            v = np.asarray(e["vector"], np.float32)
            return v / max(float(np.linalg.norm(v)), 1e-9)
        rush, t = e["rush"], e["t"]
        key = (str(Path(rush).resolve()).lower(), round(float(t), 2))
        if key not in self._examples:
            other = self.ix if str(self.ix.path).lower() == key[0] else RushIndex(Path(rush), self.ix.dir.parent)
            times, emb = other.frames()
            self._examples[key] = emb[int(np.abs(times - t).argmin())]
        return self._examples[key]

    def _fits(self, e: dict) -> bool:
        """A stored vector only compares with frames read by the same image model."""
        return "vector" not in e or e.get("model", "clip") == self.ix.meta.get("vision", "clip")

    def tracks(self, which) -> list[int]:
        n = self.ix.audio_tracks
        if which in (None, "any", "all"):
            return list(range(n))
        return [int(which)] if int(which) < n else []

    def value(self, sig: dict) -> tuple[np.ndarray, float, str]:
        """(value per second, threshold, unit), the threshold not yet moved by the sensitivity."""
        times, emb = self.ix.frames()
        if "words" in sig:
            v = self._vision()
            pos = v.words(list(sig["words"]))
            sim = (emb @ pos.T).max(axis=1) if len(emb) else np.zeros(0)
            if sig.get("not"):
                sim = sim - (emb @ v.words(list(sig["not"])).T).max(axis=1)
            return _hold(times, _robust_z(sim), self.n, self.reach), float(sig.get("z", 3.0)), "words"
        if "like" in sig:
            pos = np.array([self.example(e) for e in sig["like"] if self._fits(e)])
            if not len(pos) or not len(emb):     # only examples for another image model
                return np.full(self.n, np.nan, np.float32), float(sig.get("min", 0.85)), "like"
            sim = (emb @ pos.T).max(axis=1) if len(emb) else np.zeros(0)
            if any(self._fits(e) for e in sig.get("unlike", [])):
                neg = (emb @ np.array([self.example(e) for e in sig["unlike"] if self._fits(e)]).T).max(axis=1)
                sim = sim - 2 * np.maximum(0.0, neg - sim)
            return _hold(times, sim, self.n, self.reach), float(sig.get("min", 0.85)), "like"
        if "sound" in sig:
            names = sound_names()
            cols = [names.index(s) for s in sig["sound"] if s in names]
            per = [np.minimum(1.0, self.ix.tags(k)[:, cols].sum(axis=1)) for k in self.tracks(sig.get("track"))]
            x = np.max(per, axis=0) if per and cols else np.zeros(self.n, np.float32)
            return _smooth(x, sig.get("window", 1)), float(sig.get("min", 0.2)), "sound"
        if "loud" in sig:
            per = [self.ix.loud(k) for k in self.tracks(sig.get("loud"))]
            x = np.max(per, axis=0) if per else np.full(self.n, -100.0, np.float32)
            return _smooth(x, sig.get("window", 1)), float(sig.get("min_db", -15.0)), "loud"
        if "said" in sig:                 # never transcribes: unknown until the speech has been read
            from .speech import said_seconds
            x = said_seconds(self.ix, list(sig["said"]), self.n, sig.get("window", 3))
            return (np.full(self.n, np.nan, np.float32) if x is None else x), 0.5, "said"
        if "learn" in sig:
            model = self.models.get(self._kind)
            if model is None:
                return np.full(self.n, np.nan, np.float32), 0.0, "learn"
            from .learn import features
            return model.margin(features(self.ix)[: self.n]).astype(np.float32), 0.0, "learn"
        if "intensity" in sig:
            from .intensity import curve
            x = curve(self.ix)[0][: self.n]
            if sig["intensity"] == "low":
                return x, float(sig.get("max", 0.15)), "below"
            return x, float(sig.get("min", 0.85)), "intensity"
        if "look" in sig:
            from .zones import looks
            v = looks(self.ix, sig["zone"])
            ex = sig["look"]
            if "vector" in ex:            # stored by a game pack: the zone as it looked on someone else's rush
                from .zones import fit_look
                one = fit_look(ex["vector"], ex.get("shape"), v.shape[1] if v.ndim == 2 else 0)
                if not len(v) or one is None:
                    return np.full(self.n, np.nan, np.float32), float(sig.get("z", 3.0)), "look"
                sim = v @ one
                return _hold(times, _robust_z(sim), self.n, self.reach), float(sig.get("z", 3.0)), "look"
            other = self.ix if str(Path(ex["rush"]).resolve()).lower() == str(self.ix.path).lower() \
                else RushIndex(Path(ex["rush"]), self.ix.dir.parent)
            ref = looks(other, sig["zone"])
            if not len(v) or not len(ref):
                return np.full(self.n, np.nan, np.float32), float(sig.get("z", 3.0)), "look"
            sim = v @ ref[other.frame_at(float(ex["t"]))]
            return _hold(times, _robust_z(sim), self.n, self.reach), float(sig.get("z", 3.0)), "look"
        if "text" in sig:
            from .zones import text_at
            x = np.zeros(self.n, np.float32)
            words = [w.upper() for w in sig["text"]]
            if self.candidates is None and sig.get("zone"):
                # a kind made of text only: a sparse scan first (notifications stay up several seconds),
                # then the usual reading around what it found
                scan = max(2, int(sig.get("scan", 6)))
                known = self.ix.known()
                secs = [int(t) for t in range(0, self.n, scan) if known[t]]
                read = text_at(self.ix, [float(t) + 0.5 for t in secs], sig["zone"], log=print)
                hits = np.zeros(self.n, bool)
                for t in secs:
                    hits[t] = any(w in read[float(t) + 0.5] for w in words)
                self.candidates = np.convolve(hits.astype(float), np.ones(2 * scan + 1), "same") > 0
            if self.candidates is not None and self.candidates.any():
                half = max(1, int(round(sig.get("window", 4) / 2)))
                near = np.convolve(self.candidates.astype(float), np.ones(2 * half + 1), "same") > 0
                every = max(1, int(sig.get("every", 2)))      # notifications stay several seconds
                secs = np.flatnonzero(near)
                secs = secs[secs % every == 0]
                read = text_at(self.ix, [float(t) + 0.5 for t in secs], sig["zone"], log=print)
                hit = np.zeros(self.n, bool)
                for t in secs:
                    hit[t] = any(w in read[float(t) + 0.5] for w in words)
                x = (np.convolve(hit.astype(float), np.ones(2 * half + 1), "same") > 0).astype(np.float32)
            return x, 0.5, "text"
        if "zone" in sig:
            from .zones import gauge
            fill = _hold(times, gauge(self.ix, sig["zone"], sig.get("side", "left"), sig.get("hue")),
                         self.n, self.reach)
            if "drop" in sig:
                w = max(1, int(round(sig.get("within", 3))))
                prev = np.concatenate([np.full(w, np.nan, np.float32), fill[:-w]])
                return prev - fill, float(sig["drop"]), "drop"
            return fill, float(sig.get("below", 0.3)), "below"
        raise ValueError(f"unknown signal {sig}")

    def margin(self, sig: dict, sensitivity: float = 0.5) -> np.ndarray:
        """How far each second is past the threshold, in the signal's units (NaN: not known)."""
        if "opposite" in sig:
            return -self.margin(sig["opposite"], sensitivity)
        if "any" in sig:                     # a group: the best of its signals
            st = np.stack([self.margin(x, sensitivity) for x in sig["any"]])
            out = np.where(np.isnan(st), -np.inf, st).max(axis=0)
            return np.where(np.isfinite(out), out, np.nan).astype(np.float32)
        x, thr, unit = self.value(sig)
        scale = SCALE[unit]
        shift = (sensitivity - 0.5) * 3.0 * scale       # more sensitive = easier to pass
        if unit == "below":
            return ((thr + shift) - x) / scale
        return (x - (thr - shift)) / scale

    def combined(self, mt: MomentType) -> np.ndarray:
        self._kind = mt.id
        out = self._combined(mt)
        f = self.filters.get(mt.id)
        if f is not None:                 # ✓ against ✗: what looks like the ✗ is left out
            from .learn import features
            fm = f.margin(features(self.ix)[: self.n]) + (mt.sensitivity - 0.5) * 1.5
            out = np.where(np.isfinite(out), np.minimum(out, fm), out)
        return out

    def _combined(self, mt: MomentType) -> np.ndarray:
        plain = [s for s in mt.signals if not _has_text(s)]
        ms = [self.margin(s, mt.sensitivity) for s in plain]
        if len(plain) < len(mt.signals):
            # words on screen are read only where the other signals already pass (candidates)
            if ms:
                st = np.stack(ms)
                base = np.nan_to_num(st, nan=-1).min(axis=0) if mt.combine == "all" else np.nan_to_num(st, nan=-1).max(axis=0)
                self.candidates = base >= 0
            else:
                self.candidates = None
            ms += [self.margin(s, mt.sensitivity) for s in mt.signals if _has_text(s)]
            self.candidates = None
        stack = np.stack(ms)
        filled = np.where(np.isnan(stack), np.inf if mt.combine == "all" else -np.inf, stack)
        out = filled.min(axis=0) if mt.combine == "all" else filled.max(axis=0)
        out[~np.isfinite(out)] = np.nan
        if mt.combine == "all":           # an unknown value (no frame there) cannot pass an "all"
            out[np.isnan(stack).any(axis=0)] = np.nan
        known = self.ix.known()
        out[~known[: len(out)]] = np.nan
        return out


# --- stretches -------------------------------------------------------------------------------

def stretches(on: np.ndarray, gap: float, min_len: float) -> list[tuple[int, int]]:
    """[start, end) seconds of the runs of `on`, runs closer than `gap` merged, shorter than `min_len` dropped."""
    edges = np.flatnonzero(np.diff(np.concatenate([[0], on.astype(np.int8), [0]])))
    runs = list(zip(edges[::2], edges[1::2]))
    merged: list[list[int]] = []
    for s, e in runs:
        if merged and s - merged[-1][1] <= gap:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return [(int(s), int(e)) for s, e in merged if e - s >= min_len]


def moments_of(mt: MomentType, sig: Signals) -> list[Moment]:
    m = sig.combined(mt)
    with np.errstate(invalid="ignore"):
        on = np.nan_to_num(m, nan=-1.0) >= 0
    out: list[Moment] = []
    dur = sig.ix.duration
    for s, e in stretches(on, mt.gap, mt.min_len):
        peak = float(np.nan_to_num(m[s:e], nan=-np.inf).max())
        score = float(1 / (1 + np.exp(-1.5 * peak)))
        if mt.mode == "event":
            start, end, anchor = max(0.0, s - mt.before), min(dur, s + mt.after), float(s)
        else:
            start, end, anchor = max(0.0, s - mt.before), min(dur, e + mt.after), float(s)
        if out and start <= out[-1].end:          # padding made two overlap: one moment
            out[-1].end = max(out[-1].end, end)
            out[-1].score = max(out[-1].score, score)
        else:
            out.append(Moment(mt.id, str(sig.ix.path), float(start), float(end), anchor, score))
    return out


def teach(indexes: list[RushIndex], types: list[MomentType], marks: list[Moment] | None = None,
          log=print) -> tuple[dict, dict]:
    """Train what the examples and ✓ / ✗ teach: (models, filters) by kind id; each kind's explain is set."""
    from . import learn
    models, filters = {}, {}
    marks = marks or []
    for mt in types:
        if not mt.enabled:
            continue
        mine = [m for m in marks if m.type == mt.id and m.kept is not None]
        pos = list(mt.examples.get("pos", [])) + [mt.core(m) for m in mine if m.kept]
        neg = list(mt.examples.get("neg", [])) + [mt.core(m) for m in mine if not m.kept]
        learned = any("learn" in s for s in mt.signals)
        pv, nv = mt.examples.get("pos_vectors"), mt.examples.get("neg_vectors")    # from a game pack
        try:
            if learned and (pos or pv):
                models[mt.id] = learn.fit(indexes, pos, neg, pos_vectors=pv, neg_vectors=nv)
            elif (pos or pv) and (neg or nv):
                filters[mt.id] = learn.fit(indexes, pos, neg, filter_only=True, pos_vectors=pv, neg_vectors=nv)
            else:
                mt.explain = {}
                continue
        except Exception as exc:
            log(f"  {mt.id}: {exc}")
            continue
        model = models.get(mt.id) or filters.get(mt.id)
        mt.explain = model.explain if model else {}
    return {k: v for k, v in models.items() if v}, {k: v for k, v in filters.items() if v}


def find(indexes: list[RushIndex], types: list[MomentType], vision: Vision | None = None,
         log=print, marks: list[Moment] | None = None) -> list[Moment]:
    """Every moment of every ready type in every rush, in rush then time order. `marks` (the moments
    the user ticked ✓ or ✗) teach the kinds, with the kinds' own examples."""
    shared: dict = {}
    vision = vision or (Vision(indexes[0].meta.get("vision", "clip")) if indexes else None)
    models, filters = teach(indexes, types, marks, log)
    out: list[Moment] = []
    for ix in indexes:
        sig = Signals(ix, vision, shared)
        sig.models, sig.filters = models, filters
        for mt in types:
            if not mt.ready():
                continue
            try:
                out += moments_of(mt, sig)
            except Exception as exc:      # one broken rule must not lose the others
                log(f"  {mt.id}: {exc}")
    out.sort(key=lambda m: (m.rush, m.start))
    return out


def tracks_for_board(ix: RushIndex, types: list[MomentType], vision: Vision | None = None,
                     step: int = 5) -> dict:
    """Each ready type's margin, one value every `step` s (the board's lanes)."""
    sig = Signals(ix, vision)
    out = {}
    for mt in types:
        if mt.ready():
            m = sig.combined(mt)
            n = len(m) // step * step
            blocks = m[:n].reshape(-1, step) if n else np.zeros((0, step))
            v = np.where(np.isnan(blocks), -np.inf, blocks).max(axis=1) if len(blocks) else np.zeros(0)
            out[mt.id] = [None if not np.isfinite(x) else round(float(x), 2) for x in v]
    return out
