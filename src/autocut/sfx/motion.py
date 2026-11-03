"""Animations baked inside rendered clips: what the XML cannot see.

A motion-design export (an After Effects render, a screen recording) is one clip in the timeline,
but things pop in, slide and get typed inside it. Each clip's used range is decoded small and gray,
and the frame is cut into a grid of regions: a sound-worthy moment is a region that jumps well above
what it was doing just before. Comparing each region with its own recent past (not the whole frame
with a fixed threshold) is what lets a title pop in next to a live-action inset that never stops
moving, while footage, grain overlays and scrolling, which are busy everywhere all the time, give
nothing.

Moves that ease in (a panel sliding up slowly at first) are caught when the region's activity has
grown past the threshold and keeps growing. Text being typed is a run of small changes that stay
on screen (a cursor's changes do not: where it was is clean again), reported once, as "text", with
the run's length.

Results are cached per file, range and frame rate: re-running on a re-exported edit only decodes
the clips that are new.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

import numpy as np

from .events import Event, VClip

W, H = 192, 108               # decoded size: enough for a letter (~4 px), cheap to decode
GX, GY = 8, 6                 # regions (24 × 18 px each)
PIX = 14                      # a pixel "changed" when it moves by more than this (0-255): above grain
BASE_FRAMES = 8               # a region's "before" = the median of this many previous frames
RATIO = 3.0                   # a region jumps when it moves this many times more than before …
MARGIN = 0.04                 # … plus this share of the region (so tiny flicker does not multiply up)
JUMP = 0.5                    # … and at least half of it is new since the previous frame
CALM_REG = 0.02               # … in a region that was still just before …
BUSY_S, BUSY_MAX = 2.0, 0.3   # … and moved on at most 30 % of the frames of the last 2 s
MERGE_S = 0.3                 # an event touching the previous one's regions this soon is the same animation
CUT_REG = 0.6                 # a cut inside the render: most of 2+ regions change at once, busy or not
ONSET_AREA = 0.006            # an event moves at least this share of the frame (~125 px of 20 736)
BIG_AREA = 0.25               # a change this large is a "full" event (a slide, a zoom, a cut)
MIN_GAP = 0.12                # s between two events of the same clip
KEY_AREA = 0.0004             # typing: one keystroke changes at least this share of the frame (~8 px) …
KEY_MAX = 0.006               # … and at most this
KEY_REG = 0.01                # (a letter can be split over two regions: a small share of each)
TYPE_RUN = 4                  # a run is at least this many keystrokes …
TYPE_GAP = 0.36               # … no more than this (s) apart (a caret blinks slower)
STILL = 0.0005                # typing happens in regions otherwise still: moving on at most …
STILL_MAX = 0.2               # … this share of the last 2 s, counting even the faintest change
TYPE_STAYS = 0.5              # … whose changes mostly stay on screen (a moving cursor's do not)
VERSION = 10                  # bump when the detector changes: old cache entries are ignored


def _decode(path: str, src_in: float, length: float, fps: float) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(src_in, 0):.3f}", "-i", path, "-t", f"{length:.3f}",
           "-vf", f"fps={fps},scale={W}:{H}:flags=area,format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    a = np.frombuffer(raw, np.uint8)
    return a[: len(a) // (W * H) * W * H].reshape(-1, H, W)


def regions(frames: np.ndarray) -> np.ndarray:
    """(frames, GY*GX): share of each region that changed since the previous frame (row 0 is zeros)."""
    n = len(frames)
    out = np.zeros((n, GY * GX))
    ch, cw = H // GY, W // GX
    for i in range(1, n, 256):            # in blocks: a long clip at full size would be big
        a = frames[i - 1: i + 256].astype(np.int16)
        d = np.abs(np.diff(a, axis=0)) > PIX
        d = d[:, : ch * GY, : cw * GX].reshape(len(d), GY, ch, GX, cw).mean(axis=(2, 4))
        out[i: i + len(d)] = d.reshape(len(d), -1)
    return out


def detect(frames: np.ndarray, fps: float) -> list[dict]:
    """Moments something starts moving on screen: [{frame, peak, frames, size}] in the clip's own
    frames; size is full / element / text."""
    reg = regions(frames)
    n = len(reg)
    cells = reg.shape[1]
    gap = max(1, round(MIN_GAP * fps))
    found: list[dict] = []
    keys: list[tuple[int, float, np.ndarray]] = []
    last = -gap
    last_mask = np.zeros(cells, bool)
    moving = reg > MARGIN
    window = max(2, round(BUSY_S * fps))
    csum = np.vstack([np.zeros(cells), np.cumsum(moving, axis=0)])
    lsum = np.vstack([np.zeros(cells), np.cumsum(reg > STILL, axis=0)])
    for k in range(2, n):
        base = np.median(reg[max(1, k - BASE_FRAMES):k], axis=0)
        a0 = max(1, k - window)
        busy = (csum[k] - csum[a0]) / max(k - a0, 1)
        now, prev = reg[k], reg[k - 1]
        rising = now - prev >= JUMP * now
        new = (now >= RATIO * base + MARGIN) & rising & (base <= CALM_REG) & (busy <= BUSY_MAX)
        cut = (now >= CUT_REG) & (now >= 2 * base + 0.3) & rising
        is_cut = cut.sum() >= 2
        if is_cut:
            new |= cut
        if not new.any():
            # a keystroke: too small for an event, in a still region, with the rest of the frame still
            key = (now >= RATIO * base + KEY_REG) & rising & (base <= STILL) & (busy <= BUSY_MAX)
            area = float(now[key].sum()) / cells
            if KEY_AREA <= area < KEY_MAX and key.sum() <= 3:
                still = (lsum[k - 1] - lsum[a0]) / max(k - 1 - a0, 1)
                if (still[key] <= STILL_MAX).all() and float(np.median(now[~key])) <= STILL:
                    keys.append((k, area, key))
                    continue
            # an ease-in: the region was calm, has been growing for 3 frames and is now clearly moving
            if k >= 5:
                calm = np.median(reg[max(1, k - BASE_FRAMES - 3):k - 3], axis=0)
                grow = (reg[k - 2] > reg[k - 3]) & (reg[k - 1] > reg[k - 2]) & (now > reg[k - 1])
                new = (grow & (now >= RATIO * calm + 2 * MARGIN) & (reg[k - 3] <= RATIO * calm + MARGIN)
                       & (calm <= CALM_REG) & (busy <= BUSY_MAX))
            if not new.any():
                continue
        area = float(now[new].sum()) / cells
        if (area >= ONSET_AREA and not is_cut and k - last < MERGE_S * fps
                and (new & _grow(last_mask)).any()):
            last_mask |= new          # the same animation spreading: one sound, already placed
            continue
        if area >= ONSET_AREA and k - last >= gap:
            j = k + 1
            while j < n and j - k < 4 * fps and (reg[j][new] > (RATIO * base[new] + MARGIN / 2)).any():
                j += 1
            peak = float(reg[k:j].sum(axis=1).max()) / cells
            found.append({"frame": k, "peak": round(peak, 4), "frames": j - k,
                          "size": "full" if peak >= BIG_AREA else "element"})
            last, last_mask = k, new.copy()
        elif KEY_AREA <= area < KEY_MAX and new.sum() <= 3:
            still = (lsum[k - 1] - lsum[a0]) / max(k - 1 - a0, 1)
            if (still[new] <= STILL_MAX).all() and float(np.median(now[~new])) <= STILL:
                keys.append((k, area, new))
    return sorted(found + _typing(keys, frames, fps, {f["frame"] for f in found}), key=lambda f: f["frame"])


def _grow(mask: np.ndarray) -> np.ndarray:
    """The regions and their 8 neighbours."""
    m = mask.reshape(GY, GX)
    g = m.copy()
    g[1:] |= m[:-1]
    g[:-1] |= m[1:]
    g[:, 1:] |= g[:, :-1].copy()
    g[:, :-1] |= g[:, 1:].copy()
    return g.reshape(-1)


def _typing(keys: list[tuple[int, float, np.ndarray]], frames: np.ndarray, fps: float, taken: set[int]) -> list[dict]:
    """Runs of small, quick changes in a few regions whose result stays on screen: text being typed."""
    out: list[dict] = []
    run: list[tuple[int, float, np.ndarray]] = []
    ch, cw = H // GY, W // GX

    def flush():
        if len(run) >= TYPE_RUN:
            a, b = run[0][0] - 1, min(run[-1][0] + 2, len(frames) - 1)
            mask = np.zeros(GY * GX, bool)
            for _, _, m in run:
                mask |= m
            d = np.abs(frames[b].astype(np.int16) - frames[a].astype(np.int16)) > PIX
            d = d[: ch * GY, : cw * GX].reshape(GY, ch, GX, cw).mean(axis=(1, 3)).reshape(-1)
            stays = float(d[mask].sum()) / max(sum(x for _, x, _ in run) * GY * GX, 1e-9)
            if stays >= TYPE_STAYS and not any(a <= t <= b for t in taken):
                out.append({"frame": run[0][0], "peak": round(max(x for _, x, _ in run), 4),
                            "frames": b - run[0][0], "size": "text"})
        run.clear()

    for k in keys:
        if run and (k[0] - run[-1][0]) / fps > TYPE_GAP:
            flush()
        run.append(k)
    flush()
    return out


def _key(c: VClip, fps: float) -> str:
    st = os.stat(c.path)
    raw = json.dumps([VERSION, c.path, st.st_size, st.st_mtime, round(c.src_in, 3), round(c.end - c.start, 3),
                      fps, W, H])
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def _clip_onsets(c: VClip, fps: float, cache: Path) -> list[dict]:
    hit = cache / f"{_key(c, fps)}.json"
    try:
        return json.loads(hit.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    res = detect(_decode(c.path, c.src_in, c.end - c.start, fps), fps)
    try:
        cache.mkdir(parents=True, exist_ok=True)
        hit.write_text(json.dumps(res), encoding="utf-8")
    except OSError:
        pass
    return res


def analyse(clips: list[VClip], fps: Fraction, cache: Path, log=print, progress=None) -> list[Event]:
    """Motion events of every clip, in sequence time, at most one per MIN_GAP per clip."""
    f = float(fps)
    todo = [c for c in clips if c.path and Path(c.path).is_file() and c.end - c.start >= 3 / f]
    rng = lambda c: (c.path, round(c.src_in, 3), round(c.end - c.start, 3))   # noqa: E731
    uniq = {rng(c): c for c in todo}          # the same file and range used twice is decoded once
    results: dict[tuple, list[dict]] = {}

    def work(item):
        k, c = item
        try:
            return k, _clip_onsets(c, f, cache)
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            log(f"  motion: {Path(c.path).name}: {e}")
            return k, []

    with ThreadPoolExecutor(max(1, min(6, (os.cpu_count() or 4) - 1))) as ex:
        for done, (k, res) in enumerate(ex.map(work, uniq.items()), 1):
            results[k] = res
            if progress:
                progress(done, len(uniq))
    events: list[Event] = []
    for c in todo:
        last = -1.0
        for o in results.get(rng(c), []):
            t = c.start + o["frame"] / f
            if t >= c.end - 1 / f or t - last < MIN_GAP:
                continue
            last = t
            strength = 0.6 if o["size"] == "text" else round(min(1.0, 0.45 + 1.2 * o["peak"]), 3)
            events.append(Event(t, "motion", c.track, strength, o["frames"] / f, o["size"], c.name, c.path,
                                c.src_in + o["frame"] / f))
    events.sort(key=lambda e: e.t)
    return events
