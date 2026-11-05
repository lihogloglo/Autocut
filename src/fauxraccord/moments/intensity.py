"""Intensity: how charged each moment of a rush is, compared with the rest of that same rush.

Highlight tools for games measure intensity (arousal), not whether the feeling is good or bad (valence):
spikes of game sound, of the player's voice, of on-screen action. Valence is left out on purpose (a
laughed « je suis mort » is a high point) and no new model is needed: every ingredient is already in
the index. Rare sounds (gunfire, shouts) count by how strongly they are heard; the continuous ones
(loudness, words per second, picture pace) against the rush's own usual level (robust z); and the
mix is ranked within the rush, so a calm strategy session and a frantic shooter both get their own
highs and lows.

  action   gunfire, explosions, impacts heard (YAMNet)
  voice    shouts, laughter, cheers (YAMNet)
  loud     louder than this rush usually is
  speech   words per second, when what is said has been read (speech.py)
  pace     how fast the picture changes (image fingerprints of consecutive frames)

The mix is smoothed (~20 s: a high point is a stretch, not a frame) and spread to 0..1 by rank within
the rush: 1 = the most intense few percent, 0 = the calmest. `parts` keeps each ingredient for the page.
"""

from __future__ import annotations

import numpy as np

from .index import RushIndex

# weapons and explosions only: generic impacts (Breaking, Glass, Smash…) fire on menu clicks and item sounds
ACTION = ["Gunshot, gunfire", "Machine gun", "Fusillade", "Artillery fire", "Cap gun", "Explosion", "Boom"]
VOICE = ["Laughter", "Giggle", "Chuckle, chortle", "Belly laugh", "Shout", "Yell", "Screaming", "Whoop", "Bellow",
         "Cheering", "Children shouting", "Battle cry"]
WEIGHTS = {"action": 0.3, "voice": 0.25, "loud": 0.15, "speech": 0.15, "pace": 0.15}
SMOOTH = 20            # seconds


def _z(x: np.ndarray, known: np.ndarray) -> np.ndarray:
    """How far above its usual level each second is (robust z, only upward, 0..1 for z in 0..4)."""
    ok = known & np.isfinite(x)
    out = np.zeros(len(x), np.float32)
    if ok.sum() < 10:
        return out
    med = float(np.median(x[ok]))
    mad = float(np.median(np.abs(x[ok] - med))) * 1.4826
    spread = max(mad, float(np.std(x[ok])) * 0.25, 1e-6)
    out[ok] = np.clip((x[ok] - med) / spread, 0, 4) / 4
    return out


def _smooth(x: np.ndarray, w: int) -> np.ndarray:
    if w <= 1 or len(x) < 2:
        return x
    k = np.hanning(w + 2)[1:-1]
    k /= k.sum()
    return np.convolve(np.pad(x, (w, w), mode="edge"), k, "same")[w:-w].astype(np.float32)


def _tags(ix: RushIndex, names: list[str], classes: list[str]) -> np.ndarray:
    cols = [names.index(c) for c in classes if c in names]
    per = [np.minimum(1, ix.tags(k)[:, cols].sum(axis=1)) for k in range(ix.audio_tracks)]
    return np.max(per, axis=0) if per and cols else np.zeros(ix.seconds(), np.float32)


def pace(ix: RushIndex) -> np.ndarray:
    """Per second: how different the picture is from the one ~2 s before (1 − cosine of fingerprints)."""
    times, emb = ix.frames()
    n = ix.seconds()
    out = np.full(n, np.nan, np.float32)
    if len(times) < 3:
        return out
    change = np.concatenate([[0.0], 1.0 - np.sum(emb[1:] * emb[:-1], axis=1)]).astype(np.float32)
    from .learn import frame_of_second
    k, ok = frame_of_second(ix)
    out[ok] = change[k[ok]]
    return out


def speech_rate(ix: RushIndex) -> np.ndarray | None:
    """Words said per second (over 5 s), or None when the speech has not been read."""
    try:
        from . import speech
        if not speech.done(ix.path, ix.dir.parent):
            return None
        ws = speech.words(ix.path, ix.dir.parent)
    except Exception:
        return None
    n = ix.seconds()
    count = np.zeros(n, np.float32)
    for w in ws:
        s = int(w.start)
        if 0 <= s < n:
            count[s] += 1
    return np.convolve(count, np.ones(5) / 5, "same").astype(np.float32)


def curve(ix: RushIndex, names: list[str] | None = None, weights: dict | None = None) -> tuple[np.ndarray, dict]:
    """(intensity per second 0..1, {ingredient: per second 0..1}); NaN where the rush is not read."""
    key = ("intensity",)
    if key in ix._cache:
        return ix._cache[key]
    if names is None:
        from .rules import sound_names
        names = sound_names()
    n = ix.seconds()
    known = ix.known()[:n]
    # rare sounds (silent most of the time): how strongly they are heard, 0.5 or more = full
    rare = lambda classes: np.clip(np.convolve(_tags(ix, names, classes), np.ones(3) / 3, "same") / 0.5, 0, 1) * known
    parts: dict[str, np.ndarray] = {"action": rare(ACTION).astype(np.float32), "voice": rare(VOICE).astype(np.float32)}
    if ix.audio_tracks:
        parts["loud"] = _z(np.max([ix.loud(k) for k in range(ix.audio_tracks)], axis=0)[:n], known)
    rate = speech_rate(ix)
    if rate is not None:
        parts["speech"] = _z(rate, known)
    p = pace(ix)
    parts["pace"] = _z(np.nan_to_num(p, nan=np.nanmedian(p) if np.isfinite(p).any() else 0.0), known)
    w = {k: v for k, v in (weights or WEIGHTS).items() if k in parts}
    total = sum(w.values()) or 1.0
    mix = sum(parts[k] * (v / total) for k, v in w.items())
    mix = _smooth(mix.astype(np.float32), SMOOTH)
    # spread by rank within the rush: 1 = its most intense few percent, 0 = its calmest
    out = np.full(n, np.nan, np.float32)
    if known.any():
        order = mix[known].argsort().argsort()
        out[known] = order / max(1, known.sum() - 1)
    parts = {k: _smooth(v, SMOOTH // 2) for k, v in parts.items()}
    ix._cache[key] = (out, parts)
    return out, parts
