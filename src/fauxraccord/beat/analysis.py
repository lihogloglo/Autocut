"""Where the beats of a piece of music are: tempo, beats, bars, strong hits, loudness.

Numpy + scipy only (the window's build leaves librosa out). The method is the classic one:
an onset-strength curve (positive change of a log-mel spectrogram), its autocorrelation for the
tempo (weighted towards 120 BPM so a double or half tempo needs real evidence), then Ellis' dynamic
programming beat tracker, which lays a regular grid on the strongest onsets. The bar's first beat is
the phase whose beats carry the most low-end and harmonic change. Results are cached per file.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from scipy.ndimage import maximum_filter1d, uniform_filter1d

SR = 22050
HOP = 256                    # 11.6 ms per frame
N_FFT = 2048
N_MELS = 64
FPS = SR / HOP
PEAKS_PER_S = 100            # waveform resolution sent to the page
CACHE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "fauxraccord" / "beats"
VERSION = 4                  # bump when the analysis changes: old cache entries are redone


@dataclass
class Analysis:
    path: str
    duration: float
    bpm: float
    beats: list[float]                   # seconds
    phase: int                           # index (mod meter) of the beats that start a bar
    meter: int
    beat_strength: list[float]           # 0..1 per beat (how marked it is)
    energy: list[float]                  # loudness per beat interval, 0..1 (quiet → loud)
    onsets: list[tuple[float, float]]    # (seconds, strength 0..1): hits, for the « accents » cut
    peaks: list[int] = field(default_factory=list)   # waveform, 0..255, PEAKS_PER_S per second
    version: int = VERSION

    @property
    def period(self) -> float:
        return 60.0 / self.bpm if self.bpm else 0.5


# --- audio -------------------------------------------------------------------------------------------

def decode(path: Path, sr: int = SR) -> np.ndarray:
    from ..media import ensure_ffmpeg
    ensure_ffmpeg()
    proc = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", str(sr),
                           "-f", "f32le", "-"], capture_output=True, check=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return np.frombuffer(proc.stdout, dtype=np.float32)


def _mel_filters(sr: int = SR, n_fft: int | None = None, n_mels: int = N_MELS, fmin: float = 30.0,
                 fmax: float = 8000.0) -> tuple[np.ndarray, np.ndarray]:
    """Triangular mel filters (n_mels × bins) and each band's centre frequency."""
    n_fft = n_fft or N_FFT
    mel = lambda f: 2595.0 * np.log10(1.0 + f / 700.0)          # noqa: E731
    hz = lambda m: 700.0 * (10 ** (m / 2595.0) - 1.0)           # noqa: E731
    edges = hz(np.linspace(mel(fmin), mel(fmax), n_mels + 2))
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    fb = np.zeros((n_mels, len(freqs)), dtype=np.float32)
    for i in range(n_mels):
        lo, mid, hi = edges[i], edges[i + 1], edges[i + 2]
        up = (freqs - lo) / max(mid - lo, 1e-9)
        down = (hi - freqs) / max(hi - mid, 1e-9)
        fb[i] = np.clip(np.minimum(up, down), 0, None)
    return fb, edges[1:-1]


def mel_db(y: np.ndarray, n_fft: int | None = None) -> np.ndarray:
    """Log-mel spectrogram (n_mels × frames); frame t is centred on sample t·HOP."""
    n_fft = n_fft or N_FFT
    y = np.pad(y.astype(np.float32), (n_fft // 2, n_fft // 2))
    n = max(1, 1 + (len(y) - n_fft) // HOP)
    win = np.hanning(n_fft).astype(np.float32)
    fb, _ = _mel_filters(n_fft=n_fft, fmin=30.0 if n_fft >= 2048 else 60.0)
    out = np.empty((N_MELS, n), dtype=np.float32)
    frames = np.lib.stride_tricks.as_strided(y, shape=(n, n_fft), strides=(y.strides[0] * HOP, y.strides[0]))
    for a in range(0, n, 2048):                     # in chunks: a long track stays light on memory
        spec = np.abs(np.fft.rfft(frames[a:a + 2048] * win, axis=1)) ** 2
        out[:, a:a + 2048] = (spec @ fb.T).T
    db = 10.0 * np.log10(np.maximum(out, 1e-10))
    return np.maximum(db, db.max() - 80.0)


def onset_strength(S: np.ndarray, bands: slice | None = None) -> np.ndarray:
    """How much louder each frame got than the previous one, summed over the bands."""
    S = S if bands is None else S[bands]
    flux = np.maximum(0.0, S[:, 1:] - S[:, :-1]).mean(axis=0)
    flux = np.concatenate([[0.0], flux])
    return flux - uniform_filter1d(flux, size=int(FPS * 1.0), mode="nearest") * 0.5   # slow swells don't count


# --- tempo and beats ----------------------------------------------------------------------------------

def tempo(env: np.ndarray, lo: float = 50.0, hi: float = 210.0, centre: float = 120.0) -> float:
    """Beats per minute from the autocorrelation of the onset curve, weighted by a log-normal prior."""
    x = np.maximum(env, 0) - np.maximum(env, 0).mean()
    n = len(x)
    if n < FPS * 2:
        return centre
    spec = np.fft.rfft(x, 2 * n)
    ac = np.fft.irfft(np.abs(spec) ** 2)[:n]
    lags = np.arange(int(FPS * 60 / hi), min(n // 2 - 1, int(FPS * 60 / lo)) + 1)
    if len(lags) < 3:
        return centre

    def at(lag):                                    # the autocorrelation between whole lags
        lag = np.asarray(lag, dtype=float)
        i = np.clip(np.floor(lag).astype(int), 0, n - 2)
        f = lag - i
        return ac[i] * (1 - f) + ac[i + 1] * f
    # a beat period also shows at its double and its half: counting them settles 3:2 confusions
    score = at(lags) + 0.5 * at(2 * lags) + 0.5 * at(lags / 2)
    bpm = 60.0 * FPS / lags
    score = score * np.exp(-0.5 * (np.log2(bpm / centre) / 0.9) ** 2)
    i = int(np.argmax(score))
    if 0 < i < len(lags) - 1:                       # parabolic refinement between lags
        a, b, c = score[i - 1], score[i], score[i + 1]
        d = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
        lag = lags[i] + float(np.clip(d, -0.5, 0.5))
    else:
        lag = float(lags[i])
    return float(60.0 * FPS / lag)


def track(env: np.ndarray, bpm: float, tightness: float = 100.0) -> np.ndarray:
    """Ellis (2007): the beat frames that best sit on strong onsets while keeping the tempo."""
    period = 60.0 * FPS / bpm
    sd = np.std(env)
    norm = env / sd if sd > 0 else env
    g = np.exp(-0.5 * ((np.arange(-int(period), int(period) + 1)) * 32.0 / period) ** 2)
    local = np.convolve(norm, g, mode="same")
    n = len(local)
    window = np.arange(-int(round(2 * period)), -int(round(period / 2)) + 1)
    txcost = -tightness * np.log(-window / period) ** 2
    cum = np.zeros(n)
    back = np.full(n, -1, dtype=np.int64)
    for i in range(n):
        idx = i + window
        ok = idx >= 0
        if not ok.any():
            cum[i] = local[i]
            continue
        cand = cum[idx[ok]] + txcost[ok]
        j = int(np.argmax(cand))
        cum[i] = local[i] + cand[j]
        back[i] = idx[ok][j]
    # last beat: the latest local maximum of the cumulated score that is still well supported
    maxima = np.flatnonzero((cum[1:-1] >= cum[:-2]) & (cum[1:-1] > cum[2:])) + 1
    if not len(maxima):
        return np.array([], dtype=np.int64)
    good = maxima[cum[maxima] >= 0.5 * np.median(cum[maxima])]
    beats = [int(good[-1] if len(good) else maxima[-1])]
    while back[beats[-1]] >= 0:
        beats.append(int(back[beats[-1]]))
    beats = np.array(beats[::-1])
    # trim weak beats at the edges (silence, fades)
    strength = local[beats]
    thr = 0.5 * np.sqrt(np.mean(strength ** 2)) if len(strength) else 0
    keep = np.flatnonzero(strength >= thr)
    return beats[keep[0]:keep[-1] + 1] if len(keep) else beats


def on_the_beat(frames: np.ndarray, env: np.ndarray, low: np.ndarray) -> np.ndarray:
    """The tracker can lock half a beat off (on the hi-hats between the kicks). Kicks and bass land on the
    beat: when the grid shifted by half a beat carries clearly more low end, that one is the beat."""
    if len(frames) < 8:
        return frames
    half = np.round((frames[1:] + frames[:-1]) / 2).astype(np.int64)
    lo = np.maximum(low, 0)
    at = lambda fr: np.median([lo[max(0, f - 2):f + 3].max() for f in fr])   # noqa: E731
    return half if at(half) > 1.5 * at(frames[:-1]) else frames


def sharpen(frames: np.ndarray, fine: np.ndarray) -> np.ndarray:
    """The long analysis window sees a hit ~25 ms early. The grid moves by the typical gap between its beats
    and the hits of a short-window analysis around them: one shift for the whole track, so it stays regular."""
    gaps = []
    for f in frames:
        a, b = max(0, f - 3), min(len(fine), f + 6)          # -35 ms .. +58 ms
        if b > a:
            seg = fine[a:b]
            j = int(np.argmax(seg))
            if seg[j] > 0.25 * (fine[max(0, f - 40):f + 40].max() or 1):
                gaps.append(a + j - f)
    shift = int(round(np.median(gaps))) if len(gaps) >= max(4, len(frames) // 4) else 2
    return np.clip(frames + shift, 0, len(fine) - 1)


def bar_phase(beats: np.ndarray, S: np.ndarray, n_low: int, meter: int) -> int:
    """Which beats (index mod meter) start a bar: the ones with the loudest bass and the most harmonic change."""
    if len(beats) < meter * 2:
        return 0
    n = S.shape[1]
    power = 10 ** (S[:n_low] / 10.0)                    # the bass as energy, not as a mean of decibels
    lo = np.array([10 * np.log10(power[:, max(0, b - 1):min(n, b + 4)].sum(axis=0).max() + 1e-10) for b in beats])
    # harmonic change: the spectrum of the beat after vs the beat before
    seg = [S[:, a:b].mean(axis=1) if b > a else S[:, a] for a, b in zip(beats[:-1], beats[1:])]
    change = np.zeros(len(beats))
    for i in range(1, len(seg)):
        change[i] = np.linalg.norm(seg[i] - seg[i - 1])
    z = lambda v: (v - v.mean()) / (v.std() or 1.0)   # noqa: E731
    score = z(lo) + z(change)
    return int(np.argmax([score[p::meter].mean() for p in range(meter)]))


def pick_onsets(env: np.ndarray, spacing: float = 0.1) -> list[tuple[float, float]]:
    """The hits: local maxima clearly above the curve's typical level, with their strength (0..1)."""
    w = max(3, int(FPS * spacing))
    peak = (env == maximum_filter1d(env, size=w)) & (env > 0)
    level = uniform_filter1d(env, size=int(FPS * 2), mode="nearest")
    spread = np.sqrt(uniform_filter1d((env - level) ** 2, size=int(FPS * 2), mode="nearest"))
    idx = np.flatnonzero(peak & (env > level + 1.0 * spread))
    if not len(idx):
        return []
    top = np.percentile(env[idx], 98) or 1.0
    return [(round(i / FPS, 4), round(float(min(1.0, env[i] / top)), 3)) for i in idx]


def analyse(path: Path, meter: int = 4) -> Analysis:
    y = decode(path)
    duration = len(y) / SR
    S = mel_db(y)
    env = onset_strength(S)
    _, centres = _mel_filters()
    n_low = int(np.searchsorted(centres, 160.0)) + 1
    low = onset_strength(S, slice(0, n_low))
    bpm = tempo(env)
    frames = track(env, bpm)
    frames = on_the_beat(frames, env, low)
    fine = onset_strength(mel_db(y, 512))           # short window: exact timing of the hits
    frames = sharpen(frames, fine)
    beats = frames / FPS
    if len(beats) > 4:                              # the grid's own tempo is more exact than the estimate
        bpm = 60.0 / float(np.median(np.diff(beats)))
    sd = np.std(env) or 1.0
    strength = np.array([env[max(0, f - 2):f + 3].max() / sd for f in frames]) if len(frames) else np.array([])
    strength = strength / (np.percentile(strength, 95) or 1.0) if len(strength) else strength
    # loudness per beat interval (RMS in dB), 0 = the quietest stretch, 1 = the loudest
    rms = np.sqrt(uniform_filter1d(y.astype(np.float64) ** 2, size=HOP)[::HOP] + 1e-12)
    db = 20 * np.log10(rms + 1e-9)
    edges = list(frames) + [len(db)]
    energy = np.array([db[a:max(a + 1, b)].mean() for a, b in zip(edges[:-1], edges[1:])]) if len(frames) else np.array([])
    if len(energy):
        lo_db, hi_db = np.percentile(energy, 5), np.percentile(energy, 95)
        energy = np.clip((energy - lo_db) / max(hi_db - lo_db, 1e-6), 0, 1)
    # waveform: peak per 1/PEAKS_PER_S s
    step = SR // PEAKS_PER_S
    n = len(y) // step
    pk = np.abs(y[: n * step]).reshape(n, step).max(axis=1) if n else np.zeros(0)
    pk = pk / (pk.max() or 1.0)
    return Analysis(path=str(path), duration=round(duration, 4), bpm=round(bpm, 2),
                    beats=[round(float(b), 4) for b in beats], phase=bar_phase(frames, S, n_low, meter), meter=meter,
                    beat_strength=[round(float(v), 3) for v in np.clip(strength, 0, 1)],
                    energy=[round(float(v), 3) for v in energy], onsets=pick_onsets(fine),
                    peaks=[int(v) for v in np.round(np.sqrt(pk) * 255)])


_MEM: dict[str, Analysis] = {}


def _key(path: Path, meter: int) -> str:
    st = path.stat()
    return hashlib.sha1(f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}|{meter}|{VERSION}".lower().encode()).hexdigest()[:20]


def load(path: Path, meter: int = 4) -> Analysis:
    """The analysis of a music file, from the cache when the file has not changed."""
    path = Path(path)
    key = _key(path, meter)
    if key in _MEM:                                  # every change on the page asks again: kept in memory
        return _MEM[key]
    f = CACHE / f"{key}.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("version") == VERSION:
            d["onsets"] = [tuple(o) for o in d["onsets"]]
            _MEM.clear()
            _MEM[key] = Analysis(**d)
            return _MEM[key]
    except (OSError, ValueError, TypeError):
        pass
    a = analyse(path, meter)
    _MEM.clear()
    _MEM[key] = a
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(asdict(a)), encoding="utf-8")
    except OSError:
        pass
    return a
