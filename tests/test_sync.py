from fractions import Fraction
from pathlib import Path

import numpy as np

from fauxraccord.media import MediaInfo
from fauxraccord.sync import SR, make_track, pcm_from_float, sync_tracks

FPS = 25


def _speech(seconds: float, seed: int) -> np.ndarray:
    """Noise bursts with a syllable-like on/off envelope: enough structure to sync on."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    env = np.zeros(n, np.float32)
    t = 0
    while t < n:
        on = int(rng.uniform(0.05, 0.4) * SR)
        env[t: t + on] = rng.uniform(0.2, 1.0)
        t += on + int(rng.exponential(0.25) * SR)
    env = np.convolve(env, np.ones(80) / 80, mode="same")
    return (rng.standard_normal(n).astype(np.float32) * env).astype(np.float32)


def _recorder(world: np.ndarray, start: float, seconds: float, drift_ppm: float, seed: int) -> np.ndarray:
    """What another device hears: different colouration, own noise floor, own clock."""
    rng = np.random.default_rng(seed)
    t = start + np.arange(int(seconds * SR)) / SR * (1 + drift_ppm * 1e-6)
    x = np.interp(t * SR, np.arange(len(world)), world).astype(np.float32)
    x = np.convolve(x, [0.6, 0.3, 0.1], mode="same")   # another mic
    return (x + 0.05 * rng.standard_normal(len(x))).astype(np.float32)


def _info(name: str, seconds: float, video: bool) -> MediaInfo:
    return MediaInfo(Path(f"D:/Rushes/{name}"), seconds, Fraction(FPS), 1920, 1080, 2, 48000, video)


def _track(name, x, video):
    return make_track(_info(name, len(x) / SR, video), pcm_from_float(x))


def _timeline_of(result, file: int, src: float) -> float:
    """Timeline time (s) where source time `src` of `file` plays."""
    for p in result.placed:
        if p.file == file and p.src <= src <= p.src + p.length / FPS:
            return p.start / FPS + (src - p.src)
    raise AssertionError(f"source time {src} of file {file} is not on the timeline")


def test_camera_and_drifting_recorder():
    world = _speech(700, seed=1)
    cam = _track("C0001.MP4", _recorder(world, 30.0, 600, 0, seed=2), True)
    wav = _track("ZOOM0001.WAV", _recorder(world, 12.345, 660, 40, seed=3), False)
    r = sync_tracks([cam, wav])
    assert r.synced == [True, True]
    # a sound at world time w: camera time w - 30, recorder time (w - 12.345) / (1 + 40e-6)
    for w in (60.0, 300.0, 620.0):
        t_cam = _timeline_of(r, 0, w - 30.0)
        t_wav = _timeline_of(r, 1, (w - 12.345) / (1 + 40e-6))
        assert abs(t_cam - t_wav) < 0.006, (w, t_cam - t_wav)   # drift tolerance 5 ms + rounding
    assert sum(p.file == 1 for p in r.placed) > 1   # 40 ppm over 11 min needs segments
    assert "+40 ppm" in " ".join(r.report) or "+39 ppm" in " ".join(r.report) or "+41 ppm" in " ".join(r.report)
    # segments of the recorder never overlap on the timeline
    segs = sorted((p.start, p.start + p.length) for p in r.placed if p.file == 1)
    assert all(a[1] <= b[0] for a, b in zip(segs, segs[1:]))


def test_two_camera_files_one_recorder():
    world = _speech(800, seed=4)
    c1 = _track("C0001.MP4", _recorder(world, 20.0, 300, 0, seed=5), True)
    c2 = _track("C0002.MP4", _recorder(world, 400.0, 300, 0, seed=6), True)
    wav = _track("ZOOM0001.WAV", _recorder(world, 10.0, 780, -25, seed=7), False)
    r = sync_tracks([c1, c2, wav])
    assert r.synced == [True, True, True]
    for cam, start, w in ((0, 20.0, 150.0), (1, 400.0, 600.0)):
        t_cam = _timeline_of(r, cam, w - start)
        t_wav = _timeline_of(r, 2, (w - 10.0) / (1 - 25e-6))
        assert abs(t_cam - t_wav) < 0.006, (cam, t_cam - t_wav)
    starts = {p.file: p.start for p in r.placed if p.file in (0, 1)}
    assert starts[1] - starts[0] == 380 * FPS
    lanes = {p.file: p.lane for p in r.placed if p.file in (0, 1)}
    assert lanes[0] == lanes[1] == 0   # consecutive camera files share V1


def test_unrelated_file_is_not_synced():
    cam = _track("C0001.MP4", _recorder(_speech(300, seed=8), 0.0, 290, 0, seed=9), True)
    other = _track("other.wav", _recorder(_speech(300, seed=10), 0.0, 290, 0, seed=11), False)
    r = sync_tracks([cam, other])
    assert r.synced == [False, False]
    assert any("NOT SYNCED" in line for line in r.report)
    cam_end = max(p.start + p.length for p in r.placed if p.file == 0)
    assert min(p.start for p in r.placed if p.file == 1) >= cam_end   # parked after the end


def test_single_file():
    cam = _track("C0001.MP4", _speech(30, seed=12), True)
    r = sync_tracks([cam])
    assert r.synced == [True]
    assert [(p.start, p.length, p.src) for p in r.placed] == [(0, 30 * FPS, 0.0)]
