"""Teaching Moments by example: no rule to write, the user shows.

Each second of a rush is described by what the index already holds: the image fingerprint of the nearest
frame (CLIP) and the sound fingerprint of that second (YAMNet). A kind taught by example keeps its
examples (stretches of a rush: "c'est ça", ✓ on a card) and its counter-examples (✗). At each search,
every second is compared with them (Model): nothing is trained on "the rest", so moments nobody has
marked yet are not learned as wrong, and one example is enough for a screen that always looks the same.

  new kind (signal {"learn": true})   likeness to the examples + ✓, pulled down near the ✗;
                                      the rest of the rushes only sets the bar
  preset kind with ✓ and ✗            a filter: closer to the ✓ than to the ✗ (unmarked moments are
                                      not counted as wrong)

What the software tells the user (explain): for the image and for the sound, how far the examples stand
out from the rest of the rushes (strong / medium / weak), and whether the ✗ look and sound like the ✓
(then only a screen zone can tell them apart: "draw a box on what differs").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .index import RushIndex

BACKGROUND = 3000          # seconds of "the rest" sampled to set the bar
PROTOS = 300               # example seconds kept per fingerprint
SOUND_DIM = 1024           # YAMNet fingerprint

# Stored example seconds (a game pack, packs.py): examples {"pos_vectors": {"model": "clip", "spans": n,
# "image": rows, "sound": rows}, "neg_vectors": …} stand for example stretches of rushes nobody else has.
# rows = [[...], ...] (plain) or {"q8": base64 int8, "dim": d, "scale": [per row], "repeat": [per row]}:
# each row scaled to ±127 (a unit vector loses nothing that matters), identical neighbours (two seconds
# showing the same stored frame) kept once with how many times they repeat.


def pack_rows(rows: np.ndarray) -> dict:
    import base64
    rows = np.asarray(rows, np.float32)
    keep, repeat = [], []
    for r in rows:
        if keep and np.array_equal(r, keep[-1]):
            repeat[-1] += 1
        else:
            keep.append(r)
            repeat.append(1)
    a = np.stack(keep) if keep else np.zeros((0, rows.shape[1] if rows.ndim == 2 else 0), np.float32)
    scale = np.maximum(np.abs(a).max(axis=1), 1e-9) / 127 if len(a) else np.zeros(0, np.float32)
    q = np.round(a / scale[:, None]).astype(np.int8) if len(a) else np.zeros(a.shape, np.int8)
    return {"q8": base64.b64encode(q.tobytes()).decode("ascii"), "dim": int(a.shape[1]) if a.ndim == 2 else 0,
            "scale": [float(f"{s:.6g}") for s in scale], "repeat": repeat}


def unpack_rows(block) -> np.ndarray:
    """Unit rows from a stored block (either form); an unreadable block gives no row."""
    import base64
    try:
        if isinstance(block, dict):
            dim = int(block["dim"])
            q = np.frombuffer(base64.b64decode(block["q8"]), np.int8).astype(np.float32)
            a = q.reshape(-1, dim) * np.asarray(block["scale"], np.float32)[:, None]
            a = np.repeat(a, np.asarray(block.get("repeat") or [1] * len(a), int), axis=0)
        else:
            a = np.asarray(block, np.float32)
        if a.ndim != 2 or not len(a):
            return np.zeros((0, a.shape[-1] if a.ndim == 2 else 0), np.float32)
        return (a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-9)).astype(np.float32)
    except (KeyError, ValueError, TypeError):
        return np.zeros((0, 0), np.float32)


def stored(vectors: dict | None, vision: str, dims: dict) -> dict:
    """{fingerprint: rows} of a stored side that fit these rushes: image rows only from the same image
    model, every block only at the index's own size."""
    out = {}
    for name, dim in dims.items():
        if not vectors or name not in vectors:
            continue
        if name == "image" and vectors.get("model", "clip") != vision:
            continue
        rows = unpack_rows(vectors[name])
        if len(rows) and rows.shape[1] == dim:
            out[name] = rows
    return out


@dataclass
class Model:
    """Likeness to examples, per fingerprint (image, sound). For each second and fingerprint:
    sim = closeness to the nearest example second; the bar sits halfway between how alike the examples
    are to each other (inside) and how alike the rest typically is to them (outside, its median). The
    margin is (sim − bar) / (inside − bar): 0 at the bar, 1 as alike as the examples. Fingerprints are
    weighted by how much the examples stand out in them. A second closer to a ✗ than to the ✓ loses
    twice the difference."""
    blocks: dict                          # name -> slice of the features
    pos: dict = field(default_factory=dict)      # name -> [k, dim] example seconds (unit vectors)
    neg: dict = field(default_factory=dict)      # name -> [k, dim] counter-example seconds
    bar: dict = field(default_factory=dict)
    inside: dict = field(default_factory=dict)
    weight: dict = field(default_factory=dict)
    filter_only: bool = False
    explain: dict = field(default_factory=dict)

    def margin(self, X: np.ndarray) -> np.ndarray:
        total = np.zeros(len(X), np.float32)
        for name, sl in self.blocks.items():
            w = self.weight.get(name, 0.0)
            if w <= 0 or name not in self.pos:
                continue
            x = X[:, sl]
            sp = _nearest(x, self.pos[name])
            neg = self.neg.get(name, np.zeros((0, x.shape[1]), np.float32))
            if self.filter_only:                 # ✓ against ✗ only: which one is it closer to
                span = max(self.inside[name] - float(np.median(_nearest(self.pos[name], neg))) if len(neg) else 0.05, 0.02)
                m = (sp - _nearest(x, neg)) / span
            else:
                span = max(self.inside[name] - self.bar[name], 0.02)
                m = (sp - self.bar[name]) / span
                if len(neg):
                    m -= 2 * np.maximum(0.0, _nearest(x, neg) - sp) / span
            missing = ~np.any(x != 0, axis=1)  # no frame or no audio for that second
            m[missing] = 0.0 if self.filter_only else -1.0
            total += w * m
        return total


def _nearest(x: np.ndarray, protos: np.ndarray) -> np.ndarray:
    if not len(protos) or not len(x):
        return np.zeros(len(x), np.float32)
    out = np.empty(len(x), np.float32)
    for a in range(0, len(x), 4096):
        out[a: a + 4096] = (x[a: a + 4096] @ protos.T).max(axis=1)
    return out


def frame_of_second(ix: RushIndex) -> tuple[np.ndarray, np.ndarray]:
    """For each second: the index of its nearest frame, and whether one is near enough."""
    times, _ = ix.frames()
    n = ix.seconds()
    if not len(times):
        return np.zeros(n, int), np.zeros(n, bool)
    centre = np.arange(n) + 0.5
    k = np.clip(np.searchsorted(times, centre), 0, len(times) - 1)
    left = np.maximum(k - 1, 0)
    k = np.where(np.abs(times[left] - centre) <= np.abs(times[k] - centre), left, k)
    reach = 1.5 * float(ix.meta.get("step", 2.0)) + 0.5
    return k, np.abs(times[k] - centre) <= reach


def features(ix: RushIndex) -> np.ndarray:
    """[seconds, image dim + 1024]: image fingerprint (zeros where no frame) and sound fingerprint."""
    key = ("learn-X",)
    if key not in ix._cache:
        _, emb = ix.frames()
        k, ok = frame_of_second(ix)
        img = np.zeros((ix.seconds(), emb.shape[1] if emb.ndim == 2 and emb.shape[1] else image_dim(ix)), np.float32)
        if len(emb):
            img[ok] = emb[k[ok]]
        snd = ix.fingerprints()[: ix.seconds()]
        if len(snd) < len(img):
            snd = np.vstack([snd, np.zeros((len(img) - len(snd), snd.shape[1]), np.float32)])
        ix._cache[key] = np.hstack([img, snd]).astype(np.float32)
    return ix._cache[key]


def image_dim(ix: RushIndex) -> int:
    return 512 if ix.meta.get("vision", "clip") == "clip" else 768


def seconds_of(spans: list[dict], ix: RushIndex) -> np.ndarray:
    """Seconds of `ix` covered by spans [{rush, start, end}] that belong to it."""
    out = np.zeros(ix.seconds(), bool)
    me = str(ix.path).lower()
    for s in spans:
        if str(Path(s["rush"]).resolve()).lower() == me:
            a, b = int(max(0, np.floor(s["start"]))), int(min(ix.seconds(), np.ceil(s["end"])))
            out[a:b] = True
    return out


def _stand_out(pos: np.ndarray, rest: np.ndarray) -> float:
    """How far the examples' similarity to their centre stands out from the rest's (in the rest's spread)."""
    c = pos.mean(axis=0)
    c = c / max(float(np.linalg.norm(c)), 1e-9)
    sp, sr = pos @ c, rest @ c
    return float((np.median(sp) - np.median(sr)) / max(float(sr.std()), 1e-3))


def _alike(pos: np.ndarray, neg: np.ndarray) -> float:
    """The ✗'s similarity to the ✓'s centre, as a share of the ✓'s own (1 = as alike as the ✓ themselves)."""
    c = pos.mean(axis=0)
    c = c / max(float(np.linalg.norm(c)), 1e-9)
    own = float(np.median(pos @ c))
    return float(np.median(neg @ c)) / max(own, 1e-6)


def level(z: float) -> str:
    return "forte" if z >= 4 else "moyenne" if z >= 2 else "faible"


def _sample(x: np.ndarray, k: int, seed: int) -> np.ndarray:
    return x if len(x) <= k else x[np.random.default_rng(seed).choice(len(x), k, replace=False)]


def _present(x: np.ndarray) -> np.ndarray:
    return x[np.any(x != 0, axis=1)]


def fit(indexes: list[RushIndex], pos: list[dict], neg: list[dict], filter_only: bool = False,
        seed: int = 0, pos_vectors: dict | None = None, neg_vectors: dict | None = None) -> Model | None:
    """Learn from the examples (pos) and counter-examples (neg), stretches of these rushes, and from
    stored example seconds (pos_vectors, neg_vectors: a game pack); the rest of the rushes sets the bar."""
    done = [ix for ix in indexes if ix.done()]
    if not done:
        return None
    width = features(done[0]).shape[1]
    d = width - SOUND_DIM
    blocks = {"image": slice(0, d), "sound": slice(d, width)}
    P = {k: [] for k in blocks}
    N = {k: [] for k in blocks}
    R, counted = [], [0, 0]
    for ix in done:
        X = features(ix)
        known = ix.known()[: len(X)]
        p, q = seconds_of(pos, ix)[: len(X)] & known, seconds_of(neg, ix)[: len(X)] & known
        counted[0] += int(p.sum())
        counted[1] += int(q.sum())
        for name, sl in blocks.items():
            P[name].append(X[p][:, sl])
            N[name].append(X[q][:, sl])
        R.append(X[known & ~p & ~q])
    dims = {k: sl.stop - sl.start for k, sl in blocks.items()}
    vision = done[0].meta.get("vision", "clip")
    for side, vectors, target in ((0, pos_vectors, P), (1, neg_vectors, N)):
        rows = stored(vectors, vision, dims)
        for name, r in rows.items():
            target[name].append(r)
        counted[side] += max((len(r) for r in rows.values()), default=0)
    P = {k: _present(np.vstack(v)) if v else np.zeros((0, dims[k]), np.float32) for k, v in P.items()}
    N = {k: _present(np.vstack(v)) if v else np.zeros((0, dims[k]), np.float32) for k, v in N.items()}
    if not any(len(v) for v in P.values()) or (filter_only and not any(len(v) for v in N.values())):
        return None
    rest = _sample(np.vstack(R), BACKGROUND, seed)
    model = Model(blocks, filter_only=filter_only)
    explain = {"examples": counted[0], "counter": counted[1]}
    for name, sl in model.blocks.items():
        pb, nb, rb = P[name], N[name], _present(rest[:, sl])
        if not len(pb):
            model.weight[name] = 0.0
            continue
        protos = _sample(pb, PROTOS, seed)
        model.pos[name], model.neg[name] = protos, _sample(nb, PROTOS, seed)
        # inside: each example second against the other ones (never itself)
        sims = pb @ pb.T
        np.fill_diagonal(sims, -1.0)
        inside = float(np.median(sims.max(axis=1))) if len(pb) > 1 else 1.0
        outside = float(np.median(_nearest(rb, protos))) if len(rb) else 0.0     # the typical rest
        model.inside[name] = inside
        model.bar[name] = (inside + outside) / 2
        z = _stand_out(pb, rb) if len(rb) else 0.0
        explain[name] = round(z, 1)
        if filter_only:
            model.weight[name] = max(0.0, 1.0 - (_alike(pb, nb) if len(nb) else 1.0)) + 0.05
        else:
            model.weight[name] = max(0.0, z - 1.0) ** 2      # a fingerprint that barely stands out is left out
    total = sum(model.weight.values())
    if total <= 0:
        model.weight = {k: 1.0 for k in model.blocks if len(P[k])}
        total = float(len(model.weight))
    model.weight = {k: v / total for k, v in model.weight.items()}
    explain["weight"] = {k: round(v, 2) for k, v in model.weight.items()}
    if counted[1]:
        alike = {name: _alike(P[name], N[name]) for name in model.blocks if len(P[name]) and len(N[name])}
        explain["alike"] = {k: round(v, 2) for k, v in alike.items()}
        explain["confused"] = bool(alike) and all(v > 0.97 for v in alike.values())
    model.explain = explain
    return model
