"""Audio-based sync of camera and recorder files (what PluralEyes does).

1. Every file is decoded once to 8 kHz mono; a 100 Hz onset curve (rises in
   loudness) is the matching feature, robust to different mics and rooms.
2. For each pair of files, the shorter one is cut into ~2 min chunks and each
   chunk is located in the other file by FFT cross-correlation. Chunks vote, so
   partial overlaps work and clock drift cannot smear the match away.
3. The lag is refined on the raw audio (sub-millisecond) in windows spread over
   the overlap, and a line is fitted through them: offset + drift (ppm).
4. Files are placed through the strongest matches (maximum spanning tree),
   starting from the longest video. Videos sit on the frame grid. Recorder
   files are cut into segments at quiet spots so that drift never exceeds
   `tolerance` - the source files are never altered or resampled.
5. Files that match nothing go after the end of the timeline, reported.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .media import MediaInfo

SR = 8000           # analysis sample rate
HOP = 80            # 10 ms feature hop
FPS_FEAT = SR // HOP
CHUNK = 120.0       # seconds per located chunk
MIN_Z = 9.0         # chunk accepted if its correlation peak is this many sigmas above the rest
LAG_SPREAD = 1.0    # seconds; chunk lags further than this from the median are outliers (drift <= ~140 ppm over 2 h)
WINDOW = 4.0        # refinement window (s)
SEARCH = 0.03       # refinement search around the chunk-lag line (s)
MIN_NCC = 0.15      # refinement window kept if its normalised correlation reaches this
UNSYNCED_GAP = 5.0  # seconds between the synced block and files that matched nothing


@dataclass
class Track:
    """What sync needs of a file: its decoded audio and features."""
    info: MediaInfo
    pcm: np.ndarray       # int16, SR Hz, high-passed
    onset: np.ndarray     # float32, FPS_FEAT Hz, zero-mean unit-variance
    energy: np.ndarray    # float32, FPS_FEAT Hz, log energy (for quiet cut points)

    @property
    def duration(self) -> float:
        return self.info.duration


@dataclass
class Relation:
    """t_i = alpha + beta * t_j over the overlap, from file j to file i."""
    i: int
    j: int
    alpha: float
    beta: float
    score: float          # summed z of agreeing chunks
    chunks: int
    windows: int          # refinement windows that agreed
    overlap: tuple[float, float]   # in j's time


@dataclass
class Placed:
    """One clipitem of the sync sequence. Times in seconds; frames on the sequence grid."""
    file: int
    lane: int             # video lane for videos, recorder lane for audio-only files
    start: int            # timeline start, frames
    length: int           # frames
    src: float            # exact source time at the clip's first frame (s)


@dataclass
class SyncResult:
    fps_num: int
    fps_den: int
    placed: list[Placed]
    report: list[str]
    synced: list[bool] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"fps": [self.fps_num, self.fps_den], "placed": [asdict(p) for p in self.placed],
                "report": self.report, "synced": self.synced}

    @classmethod
    def from_json(cls, d: dict) -> "SyncResult":
        return cls(d["fps"][0], d["fps"][1], [Placed(**p) for p in d["placed"]], d["report"], d["synced"])


# --- features ------------------------------------------------------------------------------

def decode(path: Path) -> np.ndarray:
    """Whole first audio stream as 8 kHz mono, high-passed (first difference), int16."""
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1",
                             "-ar", str(SR), "-f", "f32le", "-"], stdout=subprocess.PIPE)
    parts = []
    while chunk := proc.stdout.read(SR * 4 * 60):
        parts.append(np.frombuffer(chunk, dtype=np.float32))
    proc.wait()
    x = np.concatenate(parts) if parts else np.zeros(0, np.float32)
    return pcm_from_float(x)


def pcm_from_float(x: np.ndarray) -> np.ndarray:
    hp = np.diff(x, prepend=x[:1] if len(x) else 0).astype(np.float32)
    peak = float(np.abs(hp).max()) if len(hp) else 0.0
    return (hp * (32000.0 / peak)).astype(np.int16) if peak > 0 else hp.astype(np.int16)


def make_track(info: MediaInfo, pcm: np.ndarray) -> Track:
    n = len(pcm) // HOP
    if n < 2:
        z = np.zeros(0, np.float32)
        return Track(info, pcm, z, z)
    blocks = pcm[: n * HOP].astype(np.float32).reshape(n, HOP)
    energy = np.log10((blocks ** 2).mean(axis=1) + 1.0).astype(np.float32)
    onset = np.maximum(0.0, np.diff(energy, prepend=energy[:1] if n else 0)).astype(np.float32)
    std = onset.std() if n else 0.0
    onset = (onset - onset.mean()) / std if std > 0 else onset * 0
    return Track(info, pcm, onset.astype(np.float32), energy)


# --- pair matching -------------------------------------------------------------------------

def _xcorr(long: np.ndarray, short: np.ndarray) -> np.ndarray:
    """c[k] = sum_t long[t + k] * short[t] for k in [-(len(short)-1), len(long)-1], index shifted."""
    n = 1 << int(math.ceil(math.log2(len(long) + len(short))))
    c = np.fft.irfft(np.fft.rfft(long, n) * np.conj(np.fft.rfft(short, n)), n)
    return np.concatenate([c[n - len(short) + 1:], c[: len(long)]])


def _chunk_lags(a: Track, b: Track) -> list[tuple[float, float, float]]:
    """Locate chunks of b inside a: (b time of chunk start, lag = t_a - t_b, z)."""
    out = []
    step = int(CHUNK * FPS_FEAT)
    n = 1 << int(math.ceil(math.log2(len(a.onset) + step)))
    fa = np.fft.rfft(a.onset, n)
    for s in range(0, max(1, len(b.onset) - step // 4), step):
        seg = b.onset[s: s + step]
        if len(seg) < 5 * FPS_FEAT or seg.std() == 0:
            continue
        seg = (seg - seg.mean()) / seg.std()
        c = np.fft.irfft(fa * np.conj(np.fft.rfft(seg, n)), n)
        c = np.concatenate([c[n - len(seg) + 1:], c[: len(a.onset)]])
        k = int(np.argmax(c))
        med = float(np.median(c))
        mad = float(np.median(np.abs(c - med))) * 1.4826 or 1e-9
        z = (c[k] - med) / mad
        if z >= MIN_Z:
            lag_frames = k - (len(seg) - 1)
            out.append((s / FPS_FEAT, (lag_frames - s) / FPS_FEAT, z))
    return out


def _refine(a: Track, b: Track, coarse: list[tuple[float, float, float]]) -> list[tuple[float, float]]:
    """Sub-ms lag (t_a - t_b) at windows along b, searched around the chunk-lag line."""
    tb = np.array([c[0] + CHUNK / 2 for c in coarse])
    lags = np.array([c[1] for c in coarse])
    if len(coarse) >= 2 and np.ptp(tb) > 0:
        slope, icpt = np.polyfit(tb, lags, 1)
    else:
        slope, icpt = 0.0, float(lags.mean())
    w, m = int(WINDOW * SR), int(SEARCH * SR)
    lo = max(0.0, -icpt) + 1.0
    hi = min(b.duration, a.duration - icpt) - WINDOW - 1.0
    if hi <= lo:
        return []
    n_win = int(min(60, max(3, (hi - lo) / 30)))
    out = []
    for t in np.linspace(lo, hi, n_win):
        guess = icpt + slope * t
        jb = int(t * SR)
        ja = int((t + guess) * SR) - m
        if ja < 0 or ja + w + 2 * m > len(a.pcm) or jb + w > len(b.pcm):
            continue
        sb = b.pcm[jb: jb + w].astype(np.float64)
        sa = a.pcm[ja: ja + w + 2 * m].astype(np.float64)
        nb = np.sqrt((sb ** 2).sum())
        if nb == 0:
            continue
        c = _xcorr(sa, sb)[w - 1: w - 1 + 2 * m + 1]
        cs = np.concatenate([[0.0], np.cumsum(sa ** 2)])
        na = np.sqrt(cs[w: w + 2 * m + 1] - cs[: 2 * m + 1])
        ncc = c / np.maximum(na * nb, 1e-9)
        k = int(np.argmax(ncc))
        if ncc[k] < MIN_NCC or k in (0, len(ncc) - 1):
            continue
        y0, y1, y2 = ncc[k - 1], ncc[k], ncc[k + 1]   # parabolic sub-sample peak
        den = y0 - 2 * y1 + y2
        frac = 0.5 * (y0 - y2) / den if den != 0 else 0.0
        out.append((t + WINDOW / 2, (ja + k + frac - jb) / SR))
    return out


def _fit(points: list[tuple[float, float]]) -> tuple[float, float, int]:
    """Robust line lag = icpt + slope * t; returns (icpt, slope, inliers)."""
    t = np.array([p[0] for p in points])
    y = np.array([p[1] for p in points])
    keep = np.ones(len(t), bool)
    for _ in range(4):
        if keep.sum() >= 3 and np.ptp(t[keep]) >= 60:
            slope, icpt = np.polyfit(t[keep], y[keep], 1)
        else:
            slope, icpt = 0.0, float(np.median(y[keep]))
        res = np.abs(y - (icpt + slope * t))
        new = res <= max(0.002, 3 * 1.4826 * float(np.median(res[keep])))
        if (new == keep).all():
            break
        keep = new
    return float(icpt), float(slope), int(keep.sum())


def match(tracks: list[Track], i: int, j: int) -> Relation | None:
    """Relation t_i = alpha + beta t_j, or None if the files do not overlap."""
    a, b = tracks[i], tracks[j]
    swap = b.duration > a.duration
    if swap:   # chunk the shorter file
        a, b = b, a
    coarse = _chunk_lags(a, b)
    if not coarse:
        return None
    med = float(np.median([c[1] for c in coarse]))
    agree = [c for c in coarse if abs(c[1] - med) <= LAG_SPREAD]
    whole_file = len(b.onset) <= CHUNK * FPS_FEAT * 1.25
    if len(agree) < 2 and not (whole_file and agree and agree[0][2] >= 1.5 * MIN_Z):
        return None
    fine = _refine(a, b, agree)
    if len(fine) >= 2:
        icpt, slope, n_ok = _fit(fine)
    else:
        icpt, slope, n_ok = float(np.median([c[1] for c in agree])), 0.0, 0
    # t_a = t_b + icpt + slope t_b
    alpha, beta = icpt, 1.0 + slope
    lo, hi = max(0.0, -alpha / beta), min(b.duration, (a.duration - alpha) / beta)
    if swap:   # a = tracks[j]: overlap into j's time, then invert to t_i = f(t_j)
        lo, hi = alpha + beta * lo, alpha + beta * hi
        alpha, beta = -alpha / beta, 1.0 / beta
    return Relation(i, j, alpha, beta, sum(c[2] for c in agree), len(agree), n_ok, (lo, hi))


# --- placement -----------------------------------------------------------------------------

def _quiet(track: Track, t: float, radius: float) -> float:
    a = max(0, int((t - radius) * FPS_FEAT))
    b = min(len(track.energy), int((t + radius) * FPS_FEAT) + 1)
    if b <= a:
        return t
    return (a + int(np.argmin(track.energy[a:b]))) / FPS_FEAT


def _lanes(spans: list[tuple[int, int, int]]) -> dict[int, int]:
    """Greedy lane per item: (key, start, end) -> lane, lowest lane without overlap."""
    ends: list[int] = []
    lane = {}
    for key, s, e in sorted(spans, key=lambda x: (x[1], x[2])):
        for k, end in enumerate(ends):
            if end <= s:
                ends[k] = e
                lane[key] = k
                break
        else:
            lane[key] = len(ends)
            ends.append(e)
    return lane


def place(tracks: list[Track], relations: list[Relation], tolerance: float = 0.005) -> SyncResult:
    infos = [t.info for t in tracks]
    videos = [k for k, m in enumerate(infos) if m.has_video]
    fps = next((infos[k].fps for k in videos), None)
    if fps is None:
        from fractions import Fraction
        fps = Fraction(25)
    f = float(fps)
    report: list[str] = []
    if len({infos[k].fps for k in videos}) > 1:
        report.append("WARNING: videos have different frame rates; using " + f"{f:.3f} fps")

    # Maximum spanning tree over match scores (Kruskal).
    parent = list(range(len(tracks)))

    def root(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    adj: dict[int, list[Relation]] = {k: [] for k in range(len(tracks))}
    for r in sorted(relations, key=lambda r: -r.score):
        ri, rj = root(r.i), root(r.j)
        if ri != rj:
            parent[ri] = rj
            adj[r.i].append(r)
            adj[r.j].append(r)

    # Linear map source time -> timeline time per file: T = A + B t (videos keep B = 1).
    maps: dict[int, tuple[float, float]] = {}
    comps: list[list[int]] = []
    order = sorted(range(len(tracks)), key=lambda k: (not infos[k].has_video, -tracks[k].duration))
    for start in order:
        if start in maps:
            continue
        maps[start] = (0.0, 1.0)
        comp, queue = [start], [start]
        while queue:
            x = queue.pop(0)
            ax, bx = maps[x]
            for r in adj[x]:
                y = r.j if r.i == x else r.i
                if y in maps:
                    continue
                if r.i == x:   # t_x = alpha + beta t_y
                    a, b = ax + bx * r.alpha, bx * r.beta
                else:          # t_y = alpha + beta t_x  ->  t_x = (t_y - alpha) / beta
                    a, b = ax - bx * r.alpha / r.beta, bx / r.beta
                if infos[y].has_video:   # slope 1, exact at the middle of the overlap
                    c = (r.overlap[0] + r.overlap[1]) / 2   # in j's time
                    if r.i == y:
                        c = r.alpha + r.beta * c
                    a, b = a + (b - 1.0) * c, 1.0
                maps[y] = (a, b)
                comp.append(y)
                queue.append(y)
        comps.append(comp)

    synced = [False] * len(tracks)
    main = max(comps, key=lambda c: (len(c) > 1, sum(tracks[k].duration for k in c)))
    for k in main:
        synced[k] = len(main) > 1 or len(tracks) == 1

    # Lay components end to end: the main one first, the rest after a gap.
    offset = 0.0
    shifted: dict[int, tuple[float, float]] = {}
    for comp in [main] + [c for c in comps if c is not main]:
        lo = min(maps[k][0] for k in comp)
        hi = max(maps[k][0] + maps[k][1] * tracks[k].duration for k in comp)
        shift = math.ceil((offset - lo) * f) / f   # whole frames: the root video stays on the grid
        for k in comp:
            a, b = maps[k]
            shifted[k] = (a + shift, b)
        offset = shift + hi + UNSYNCED_GAP

    # Videos on the frame grid, recorder files split against drift.
    placed: list[Placed] = []
    video_shift: list[tuple[float, float, float]] = []   # (timeline start, end, rounding residual) per video
    for k in videos:
        a, _ = shifted[k]
        fr = round(a * f)
        placed.append(Placed(k, 0, fr, int(math.floor(infos[k].duration * f)), 0.0))
        video_shift.append((a, a + infos[k].duration, fr / f - a))
    for k in range(len(tracks)):
        if infos[k].has_video:
            continue
        a, b = shifted[k]
        dur = infos[k].duration
        cuts = [0.0]
        drift = abs(b - 1.0)
        if drift * dur > tolerance:
            seg = 2 * tolerance / drift
            t = seg
            while t < dur - seg / 4:
                cuts.append(_quiet(tracks[k], t, min(5.0, seg / 4)))
                t = cuts[-1] + seg
        cuts.append(dur)
        segs = []
        for t0, t1 in zip(cuts, cuts[1:]):
            mid = (t0 + t1) / 2
            at = a + b * mid
            # follow the frame rounding of the video playing there, so lip sync is exact
            under = [r for s0, s1, r in video_shift if s0 <= at <= s1]
            start_time = at - (mid - t0) + (under[0] if under else 0.0)   # exact at the segment middle
            fr = math.ceil(start_time * f - 1e-6)
            segs.append((fr, t0 + (fr / f - start_time)))
        for n, (fr, src) in enumerate(segs):
            avail = fr + int(math.floor((dur - src) * f))
            end = min(segs[n + 1][0], avail) if n + 1 < len(segs) else avail
            if end > fr:
                placed.append(Placed(k, 0, fr, end - fr, src))

    lo = min(p.start for p in placed)
    for p in placed:
        p.start -= lo
    vid = _lanes([(n, p.start, p.start + p.length) for n, p in enumerate(placed) if infos[p.file].has_video])
    aud = _lanes([(k, min(p.start for p in placed if p.file == k),
                   max(p.start + p.length for p in placed if p.file == k))
                  for k in range(len(tracks)) if not infos[k].has_video])
    for n, p in enumerate(placed):
        p.lane = vid[n] if infos[p.file].has_video else aud[p.file]
    placed.sort(key=lambda p: (not infos[p.file].has_video, p.lane, p.start))

    # Report.
    for k in range(len(tracks)):
        name = infos[k].path.name
        first = min((p for p in placed if p.file == k), key=lambda p: p.start)
        at = _tc(first.start / f)
        if not synced[k]:
            report.append(f"  {name:<28} NOT SYNCED (no common sound found) - placed at {at}")
            continue
        a, b = shifted[k]
        segs = sum(p.file == k for p in placed)
        rel = [r for r in relations if k in (r.i, r.j) and r in adj[k]]
        conf = max((r.score for r in rel), default=0.0)
        line = f"  {name:<28} at {at}"
        if not infos[k].has_video:
            line += f", drift {(b - 1.0) * 1e6:+.0f} ppm"
            if segs > 1:
                line += f" (corrected in {segs} segments)"
        if rel:
            line += f", match score {conf:.0f}"
        report.append(line)
    return SyncResult(fps.numerator, fps.denominator, placed, report, synced)


def _tc(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}"


# --- entry point ---------------------------------------------------------------------------

def _signature(infos: list[MediaInfo], tolerance: float) -> str:
    parts = [f"{m.path}|{m.path.stat().st_size}|{m.path.stat().st_mtime}" for m in infos]
    return hashlib.sha1(("\n".join(parts) + f"|{tolerance}|v1").encode()).hexdigest()


def sync(infos: list[MediaInfo], cache: Path | None = None, tolerance: float = 0.005) -> SyncResult:
    key = _signature(infos, tolerance)
    if cache and cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("key") == key:
                print(f"  using cached sync {cache.name}")
                return SyncResult.from_json(data["result"])
        except (ValueError, KeyError, TypeError):
            pass
    tracks = []
    for m in infos:
        print(f"  reading audio of {m.path.name}")
        pcm = decode(m.path) if m.audio_channels else np.zeros(0, np.int16)
        tracks.append(make_track(m, pcm))
    result = sync_tracks(tracks, tolerance)
    if cache:
        cache.write_text(json.dumps({"key": key, "result": result.to_json()}, indent=0), encoding="utf-8")
    return result


def sync_tracks(tracks: list[Track], tolerance: float = 0.005) -> SyncResult:
    relations = []
    pairs = [(i, j) for i in range(len(tracks)) for j in range(i + 1, len(tracks))]
    for n, (i, j) in enumerate(pairs):
        print(f"\r  matching {n + 1}/{len(pairs)}", end="", flush=True)
        if len(tracks[i].pcm) and len(tracks[j].pcm):
            r = match(tracks, i, j)
            if r:
                relations.append(r)
    if pairs:
        print()
    return place(tracks, relations, tolerance)
