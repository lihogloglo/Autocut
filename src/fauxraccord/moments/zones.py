"""Screen zones: a box drawn once on a gauge (a health bar) and read on every stored frame.

The box is in fractions of the picture (x, y, w, h), so it fits any stored frame size. A gauge is read
along its long side, from where it fills (`side`: left, right, bottom, top).

Game HUD bars are often see-through (Rust's health bar turns pale over snow), so a fixed colour does
not work. What stays is the bar's hue: each slice's colour minus its own grey level, projected on the
bar's hue (learned from the filling end over the whole rush, where the bar is nearly always lit).
A slice is lit when that projection is over half of the frame's own level at the filling end (with
a floor, so an empty bar reads empty). The fill is the lit run from the filling end, divided by what
a full bar reads in this rush (95th percentile: the bar is full most of the time), so a box drawn a
little wider than the bar still reads 1.0 when full. Results are cached per box in the index folder.
"""

from __future__ import annotations

import hashlib
import json

import numpy as np

from .index import RushIndex


def _crop(pic, box: list[float]) -> np.ndarray:
    w, h = pic.size
    x, y, bw, bh = box
    l, t = int(x * w), int(y * h)
    r, b = max(l + 1, int(round((x + bw) * w))), max(t + 1, int(round((y + bh) * h)))
    return np.asarray(pic.crop((l, t, r, b)), dtype=np.float32)


def _profile(crop: np.ndarray, side: str) -> np.ndarray:
    """Mean colour of each slice across the long side, ordered from the filling end: [slices, 3]."""
    horizontal = side in ("left", "right")
    prof = crop.mean(axis=0) if horizontal else crop.mean(axis=1)
    return prof[::-1] if side in ("right", "bottom") else prof


def read(profiles: np.ndarray, hue: np.ndarray | None = None) -> np.ndarray:
    """Raw fill (0..1 of the box) of each [slices, 3] profile in `profiles` [frames, slices, 3]."""
    n = profiles.shape[1]
    head = max(1, n // 10)
    chroma = profiles - profiles.mean(axis=2, keepdims=True)
    if hue is None:
        hue = np.median(chroma[:, :head].mean(axis=1), axis=0)
    hue = np.asarray(hue, np.float32)
    hue = hue / max(float(np.linalg.norm(hue)), 1e-6)
    s = (chroma * hue).sum(axis=2)                                  # [frames, slices]
    ref = float(np.median(s[:, :head].mean(axis=1)))
    level = np.maximum(np.median(s[:, : max(head, n // 3)], axis=1), 0.3 * ref)
    lit = s > 0.5 * level[:, None]
    fill = np.zeros(len(s), np.float32)
    allow = max(2, n // 25)                     # a few unlit slices: digits written over the bar
    for k, row in enumerate(lit):
        miss = end = 0
        for j, on in enumerate(row):
            if on:
                end, miss = j + 1, 0
            else:
                miss += 1
                if miss > allow:
                    break
        fill[k] = end / n
    return fill


def snap(pictures: list, box: list[float], side: str = "left") -> list[float]:
    """The box shrunk to the bar inside it: the rows and the columns where the bar's hue is strong on
    most frames. A box drawn roughly around a bar (catching the next bar, an icon, the background)
    then reads as well as one drawn to the pixel."""
    crops = [_crop(p, box) for p in pictures]
    h = min(c.shape[0] for c in crops)
    w = min(c.shape[1] for c in crops)
    stack = np.stack([c[:h, :w] for c in crops])                   # [frames, rows, cols, 3]
    chroma = stack - stack.mean(axis=3, keepdims=True)
    horizontal = side in ("left", "right")
    along = 2 if horizontal else 1
    n = stack.shape[along]
    head = slice(0, max(1, n // 4)) if side in ("left", "top") else slice(n - max(1, n // 4), n)
    sample = chroma[:, :, head] if horizontal else chroma[:, head]
    hue = np.median(sample.reshape(-1, 3), axis=0)
    hue = hue / max(float(np.linalg.norm(hue)), 1e-6)
    proj = (chroma * hue).sum(axis=3)                               # [frames, rows, cols]
    strength = np.median(proj, axis=0)                              # a typical frame: the bar's rows
    reach = np.percentile(proj, 90, axis=0)                         # as full as it gets: the bar's length
    across = strength.mean(axis=1 if horizontal else 0)            # per row (or column) across the bar
    keep = np.flatnonzero(across > 0.6 * across.max())
    if not len(keep):
        return box
    a0, a1 = int(keep[0]), int(keep[-1]) + 1

    def lit(a: np.ndarray) -> np.ndarray:
        band = a[a0:a1] if horizontal else a[:, a0:a1]
        prof = band.mean(axis=0 if horizontal else 1)
        return np.flatnonzero(prof > 0.4 * prof.max())

    typical, full = lit(strength), lit(reach)      # the filling end is lit on a typical frame,
    if not len(typical) or not len(full):          # the far end only when the bar is full
        b0, b1 = 0, n
    elif side in ("left", "top"):
        b0, b1 = int(typical[0]), int(full[-1]) + 1
    else:
        b0, b1 = int(full[0]), int(typical[-1]) + 1
    x, y, bw, bh = box
    if horizontal:
        return [x + bw * b0 / w, y + bh * a0 / h, bw * (b1 - b0) / w, bh * (a1 - a0) / h]
    return [x + bw * a0 / w, y + bh * b0 / h, bw * (a1 - a0) / w, bh * (b1 - b0) / h]


def gauge(ix: RushIndex, box: list[float], side: str = "left", hue: list[float] | None = None) -> np.ndarray:
    """Fill (0..1, 1 = full) of the gauge on every frame of the index, in frames() order."""
    times, _ = ix.frames()
    key = hashlib.sha1(json.dumps([5, box, side, hue, len(times)]).encode()).hexdigest()[:12]
    cache = ix.dir / f"zone-{key}.npy"
    if cache.exists():
        return np.load(cache)
    if not len(times):
        return np.zeros(0, np.float32)
    pictures = [ix.picture(k) for k in range(len(times))]
    tight = snap(pictures[:: max(1, len(pictures) // 60)], box, side)
    profiles = [_profile(_crop(p, tight), side) for p in pictures]
    n = min(len(p) for p in profiles)
    raw = read(np.stack([p[:n] for p in profiles]), hue)
    full = max(float(np.percentile(raw, 95)), 0.5)
    fill = np.minimum(1.0, raw / full).astype(np.float32)
    np.save(cache, fill)
    return fill


# --- words on screen (notifications, kill feeds) ------------------------------------------------
# Read at full resolution, straight from the rush, and only at the seconds a rule asks for: around the
# candidates its other signals found, or (a kind made of text only) a sparse scan first. A read costs
# ~0.13 s of text recognition (no orientation step: a HUD is never upside down) plus ~0.2 s to pull the
# frame out of the video, four at a time.

_ocr = None


def _reader():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


def _full_frame_crop(path, t: float, box: list[float], width: int, height: int):
    import subprocess
    import cv2
    x, y, w, h = box
    crop = f"crop={int(w * width)}:{int(h * height)}:{int(x * width)}:{int(y * height)}"
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(path), "-frames:v", "1",
                          "-vf", crop, "-f", "image2pipe", "-vcodec", "png", "-"],
                         capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    return cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR) if out else None


def text_at(ix: RushIndex, times: list[float], box: list[float], log=None) -> dict[float, str]:
    """The words read in `box` at each time (upper case), cached in the index folder."""
    from concurrent.futures import ThreadPoolExecutor
    key = hashlib.sha1(json.dumps(box).encode()).hexdigest()[:12]
    cache = ix.dir / f"text-{key}.json"
    known: dict[str, str] = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    w, h = int(ix.meta.get("width", 1920)), int(ix.meta.get("height", 1080))
    todo = [t for t in dict.fromkeys(times) if f"{t:.1f}" not in known]
    batch = 64
    with ThreadPoolExecutor(4) as pool:
        for a in range(0, len(todo), batch):
            part = todo[a: a + batch]
            for t, img in zip(part, pool.map(lambda x: _full_frame_crop(ix.path, x, box, w, h), part)):
                found = _reader()(img, use_cls=False)[0] if img is not None else None
                known[f"{t:.1f}"] = " ".join(r[1] for r in (found or [])).upper()
            cache.write_text(json.dumps(known, ensure_ascii=False), encoding="utf-8")
            if log and len(todo) > batch:
                log(f"  reading the zone {min(a + batch, len(todo))}/{len(todo)}")
    return {t: known[f"{t:.1f}"] for t in times}


# --- how a zone looks (an icon, a banner, a kill-feed line) ----------------------------------------
# Each stored frame's zone, shrunk to a few hundred values (colour, minus its own mean, unit length):
# enough to tell "the icon is there" from "it is not", cheap to keep for 10 hours.

LOOK_W = 24


def looks(ix: RushIndex, box: list[float]) -> np.ndarray:
    """[frames, D] the zone on every stored frame, as unit vectors (cached in the index folder)."""
    times, _ = ix.frames()
    key = hashlib.sha1(json.dumps(["look", 1, box, len(times)]).encode()).hexdigest()[:12]
    cache = ix.dir / f"zone-{key}.npy"
    if cache.exists():
        return np.load(cache)
    from PIL import Image
    if not len(times):
        return np.zeros((0, 3), np.float32)
    first = _crop(ix.picture(0), box)
    h = max(2, round(LOOK_W * first.shape[0] / max(1, first.shape[1])))
    out = []
    for k in range(len(times)):
        c = _crop(ix.picture(k), box).astype(np.uint8)
        v = np.asarray(Image.fromarray(c).resize((LOOK_W, h), Image.BILINEAR), np.float32).ravel()
        v -= v.mean()
        out.append(v / max(float(np.linalg.norm(v)), 1e-6))
    arr = np.stack(out).astype(np.float32)
    np.save(cache, arr)
    return arr


def look_shape(ix: RushIndex, box: list[float]) -> list[int]:
    """[rows, columns] of a zone's look vector on this rush's stored frames."""
    first = _crop(ix.picture(0), box)
    return [max(2, round(LOOK_W * first.shape[0] / max(1, first.shape[1]))), LOOK_W]


def fit_look(vector, shape, dim: int) -> np.ndarray | None:
    """A stored look (a game pack: the zone on someone else's rush) at this rush's look size: rows
    resampled when the stored frames' shape differs a little. None when it cannot fit."""
    v = np.asarray(vector, np.float32).ravel()
    if not dim or not len(v):
        return None
    if len(v) != dim:
        rows = int(shape[0]) if shape else len(v) // (LOOK_W * 3)
        if rows * LOOK_W * 3 != len(v) or dim % (LOOK_W * 3):
            return None
        want = dim // (LOOK_W * 3)
        grid = v.reshape(rows, LOOK_W * 3)
        at = np.linspace(0, rows - 1, want)
        lo = np.floor(at).astype(int)
        hi = np.minimum(lo + 1, rows - 1)
        f = (at - lo)[:, None]
        v = (grid[lo] * (1 - f) + grid[hi] * f).ravel()
        v -= v.mean()
    return v / max(float(np.linalg.norm(v)), 1e-6)
