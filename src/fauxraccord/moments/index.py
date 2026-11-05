"""The index of a rush: read once, slowly, then every kind of moment is a cheap re-score of it.

Cached per rush file (like the transcripts) in %LOCALAPPDATA%\\fauxraccord\\index\\<name>-<key>\\, cut into
10-minute chunks written as they are done. Stopping, a crash or a rush added later never starts the
reading over: chunks already there are kept, and the board can show the first hour while the rest
is still being read.

Each chunk holds
  cNNNN.npz   t          frame times in the file (s), about one every `step` s
              img        one unit vector per frame (the image model in meta.json)
              jpg        offsets of the frames' JPEGs in cNNNN.jpg (n + 1 values)
              aK_tags    audio track K: 521 AudioSet scores per second (float16)
              aK_loud    audio track K: loudest 100 ms of each second (dBFS)
              aK_emb     audio track K: YAMNet's sound fingerprint of each second (1024, unit, float16):
                         what "sounds like this" compares (added to older chunks without re-reading video)
  cNNNN.jpg   the frames, `width` px wide, JPEG one after another: thumbnails for the board and
              the pictures that screen zones (a health bar) are read from.
The .npz is written last: a chunk without it is redone.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import reader
from .models import Sounds, Vision

ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "fauxraccord" / "index"
VERSION = 1


@dataclass
class Settings:
    step: float = 2.0          # seconds between frames
    chunk: float = 600.0       # seconds per chunk file
    width: int = 512           # stored frame width (thumbnails and screen zones)
    vision: str = "clip"
    keyframes: bool | None = None   # None: decided from the recording's keyframe spacing
    hwaccel: str | None = "auto"    # "auto": a short trial picks between software and d3d11va
    quality: int = 80          # JPEG


def pick_decoder(rec: reader.Recording, keyframes: bool, step: float, seconds: float = 20.0) -> str | None:
    """The faster of software and Windows hardware decoding on a stretch from the middle of the rush.
    On a real 1080p60 export, keyframes + d3d11va read 2.4× faster; on easy synthetic video, software
    did. So it is measured, not assumed."""
    start = max(0.0, rec.duration / 2 - seconds / 2)
    best, best_time, best_n = None, float("inf"), -1
    for hw in (None, "d3d11va"):
        t0 = time.time()
        try:
            n = sum(1 for _ in reader.frames(rec, start, seconds, step, 256, keyframes=keyframes, hwaccel=hw))
        except Exception:
            continue
        dt = time.time() - t0
        if n >= best_n and (n > best_n or dt < best_time):
            best, best_time, best_n = hw, dt, n
    return best


def file_key(path: Path) -> str:
    st = path.stat()
    raw = f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}".lower()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


class RushIndex:
    def __init__(self, path: Path, root: Path = ROOT):
        self.path = Path(path).resolve()
        self.dir = Path(root) / f"{self.path.stem[:40]}-{file_key(self.path)}"
        self._meta: dict | None = None
        self._cache: dict = {}

    # --- what is there -----------------------------------------------------------------------

    @property
    def meta(self) -> dict:
        if self._meta is None:
            f = self.dir / "meta.json"
            self._meta = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        return self._meta

    @property
    def duration(self) -> float:
        return float(self.meta.get("duration", 0.0))

    @property
    def audio_tracks(self) -> int:
        return len(self.meta.get("audio", []))

    def spans(self) -> list[tuple[int, float, float]]:
        """(chunk number, start, length) covering the whole rush."""
        d, c = self.duration, float(self.meta.get("chunk", 600.0))
        n = max(1, int(np.ceil(d / c))) if d else 0
        return [(i, i * c, min(c, d - i * c)) for i in range(n)]

    def _npz(self, i: int) -> Path:
        return self.dir / f"c{i:04d}.npz"

    def done(self) -> list[int]:
        return [i for i, *_ in self.spans() if self._npz(i).exists()]

    @property
    def complete(self) -> bool:
        spans = self.spans()
        return bool(spans) and len(self.done()) == len(spans)

    def progress(self) -> float:
        spans = self.spans()
        return len(self.done()) / len(spans) if spans else 0.0

    # --- reading the rush --------------------------------------------------------------------

    def prepare(self, settings: Settings) -> dict:
        """meta.json for this rush (kept if the settings that shape the chunks have not changed)."""
        rec = reader.probe(self.path)
        spacing = reader.keyframe_spacing(self.path) if rec.has_video else None
        keyframes = settings.keyframes
        if keyframes is None:
            keyframes = spacing is not None and spacing <= 2.5 * settings.step
        hwaccel = settings.hwaccel
        if hwaccel == "auto":
            old = self.meta
            if old.get("hwaccel") != "auto" and old.get("keyframes") == keyframes and "hwaccel" in old:
                hwaccel = old["hwaccel"]
            else:
                hwaccel = pick_decoder(rec, keyframes, settings.step) if rec.has_video else None
        meta = {
            "version": VERSION, "path": str(self.path), "duration": rec.duration,
            "fps": [rec.fps.numerator, rec.fps.denominator], "width": rec.width, "height": rec.height,
            "vcodec": rec.vcodec, "audio": [{"channels": a.channels, "rate": a.rate, "title": a.title}
                                            for a in rec.audio],
            "keyframe_spacing": spacing, "keyframes": keyframes, "hwaccel": hwaccel,
            "step": settings.step, "chunk": settings.chunk, "width_stored": settings.width,
            "vision": settings.vision, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        old = self.meta
        shape = ("version", "duration", "step", "chunk", "width_stored", "vision")
        if old and any(old.get(k) != meta[k] for k in shape):
            for f in self.dir.glob("c*.*"):
                f.unlink()
        elif old:
            meta["created"] = old.get("created", meta["created"])
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        self._meta, self._cache = meta, {}
        return meta

    def build(self, settings: Settings, vision: Vision | None = None, sounds: Sounds | None = None,
              on_chunk=None, should_stop=None, only: tuple[float, float] | None = None) -> None:
        """Read every chunk not read yet (or only those meeting the `only` (start, end) seconds).
        on_chunk(done, total) after each one."""
        meta = self.prepare(settings)
        rec = reader.probe(self.path)
        vision = vision or Vision(meta["vision"])
        sounds = sounds or Sounds()
        spans = self.spans()
        if only:
            spans = [(i, s, n) for i, s, n in spans if s < only[1] and s + n > only[0]]
        for i, start, length in spans:
            if should_stop and should_stop():
                return
            if not self._npz(i).exists():
                self._build_chunk(rec, i, start, length, meta, vision, sounds)
            elif meta["audio"] and not self._has(i, "a0_emb"):
                self._add_fingerprints(rec, i, start, length, meta, sounds)
            if on_chunk:
                on_chunk(sum(self._npz(k).exists() for k, *_ in spans), len(spans))
        self._cache = {}

    def _build_chunk(self, rec: reader.Recording, i: int, start: float, length: float, meta: dict,
                     vision: Vision, sounds: Sounds) -> None:
        from PIL import Image
        arrays: dict[str, np.ndarray] = {}
        times, pics, offsets = [], [], [0]
        jpg = io.BytesIO()
        for hw in dict.fromkeys([meta["hwaccel"], None]) if rec.has_video else ():
            for t, rgb in reader.frames(rec, start, length, meta["step"], meta["width_stored"],
                                        keyframes=meta["keyframes"], hwaccel=hw):
                if times and t <= times[-1]:
                    continue
                pic = Image.fromarray(rgb)
                pic.save(jpg, "JPEG", quality=80)
                offsets.append(jpg.tell())
                times.append(t)
                pics.append(pic)
            if times or length < 2 * meta["step"]:
                break               # hardware decoding gave nothing: read the chunk again in software
        emb = vision.images(pics) if pics else np.zeros((0, vision.dim), np.float32)
        arrays["t"] = np.array(times, dtype=np.float64)
        arrays["img"] = emb.astype(np.float16)
        arrays["jpg"] = np.array(offsets, dtype=np.int64)
        seconds = int(np.ceil(length - 1e-6))
        for k in range(len(meta["audio"])):
            wave = reader.audio(rec, k, start, length)
            tags, fp = sounds.per_second_both(wave, seconds)
            arrays[f"a{k}_tags"] = tags.astype(np.float16)
            arrays[f"a{k}_emb"] = fp.astype(np.float16)
            arrays[f"a{k}_loud"] = reader.loudness(wave, seconds)
        (self.dir / f"c{i:04d}.jpg").write_bytes(jpg.getvalue())
        tmp = self.dir / f"c{i:04d}.tmp.npz"
        np.savez(tmp, **arrays)
        os.replace(tmp, self._npz(i))

    def _has(self, i: int, key: str) -> bool:
        with np.load(self._npz(i)) as z:
            return key in z.files

    def _add_fingerprints(self, rec, i: int, start: float, length: float, meta: dict, sounds: Sounds) -> None:
        """Sound fingerprints for a chunk read before they existed: only its audio is read again."""
        with np.load(self._npz(i)) as z:
            arrays = {k: z[k] for k in z.files}
        seconds = int(np.ceil(length - 1e-6))
        for k in range(len(meta["audio"])):
            _, fp = sounds.per_second_both(reader.audio(rec, k, start, length), seconds)
            arrays[f"a{k}_emb"] = fp.astype(np.float16)
        tmp = self.dir / f"c{i:04d}.tmp.npz"
        np.savez(tmp, **arrays)
        os.replace(tmp, self._npz(i))
        self._cache.pop(("chunk", i), None)

    # --- what the rules read -----------------------------------------------------------------

    def _load(self, i: int) -> dict:
        key = ("chunk", i)
        if key not in self._cache:
            with np.load(self._npz(i)) as z:
                self._cache[key] = {k: z[k] for k in z.files}
        return self._cache[key]

    def frames(self) -> tuple[np.ndarray, np.ndarray]:
        """(times, unit vectors) of every frame read so far."""
        if "frames" not in self._cache:
            ts, es = [], []
            for i in self.done():
                c = self._load(i)
                ts.append(c["t"])
                es.append(c["img"].astype(np.float32))
            dim = 512 if self.meta.get("vision", "clip") == "clip" else 768
            self._cache["frames"] = (np.concatenate(ts) if ts else np.zeros(0),
                                     np.concatenate(es) if es else np.zeros((0, dim), np.float32))
        return self._cache["frames"]

    def seconds(self) -> int:
        return int(np.ceil(self.duration - 1e-6))

    def _per_second(self, name: str, fill: float, width: int | None = None) -> np.ndarray:
        """A per-second array over the whole rush; seconds of chunks not read yet hold `fill`."""
        key = ("sec", name)
        if key not in self._cache:
            n = self.seconds()
            out = None
            for i, start, length in self.spans():
                if not self._npz(i).exists():
                    continue
                c = self._load(i)
                if name not in c:
                    continue
                a = c[name].astype(np.float32)
                if out is None:
                    out = np.full((n,) + a.shape[1:], fill, np.float32)
                s = int(round(start))
                out[s: s + len(a)] = a[: n - s]
            if out is None:
                out = np.full((n,) if width is None else (n, width), fill, np.float32)
            self._cache[key] = out
        return self._cache[key]

    def tags(self, track: int) -> np.ndarray:
        """[seconds, 521] AudioSet scores of one audio track."""
        return self._per_second(f"a{track}_tags", 0.0, 521)

    def fingerprints(self) -> np.ndarray:
        """[seconds, 1024] sound fingerprint of each second, all audio tracks together (zeros where unread)."""
        if "fp" not in self._cache:
            per = [self._per_second(f"a{k}_emb", 0.0, 1024) for k in range(self.audio_tracks)]
            fp = np.mean(per, axis=0) if per else np.zeros((self.seconds(), 1024), np.float32)
            self._cache["fp"] = fp / np.maximum(np.linalg.norm(fp, axis=1, keepdims=True), 1e-9)
        return self._cache["fp"]

    def loud(self, track: int) -> np.ndarray:
        return self._per_second(f"a{track}_loud", -100.0)

    def known(self) -> np.ndarray:
        """True for the seconds whose chunk has been read."""
        n = self.seconds()
        out = np.zeros(n, bool)
        for i, start, length in self.spans():
            if self._npz(i).exists():
                out[int(round(start)): int(round(start + length + 0.5))] = True
        return out

    def jpeg(self, k: int) -> bytes:
        """The k-th frame (in frames() order) as JPEG bytes."""
        for i in self.done():
            c = self._load(i)
            n = len(c["t"])
            if k < n:
                off = c["jpg"]
                with open(self.dir / f"c{i:04d}.jpg", "rb") as fh:
                    fh.seek(int(off[k]))
                    return fh.read(int(off[k + 1] - off[k]))
            k -= n
        raise IndexError(k)

    def frame_at(self, t: float) -> int:
        """Index of the frame nearest to time t."""
        times, _ = self.frames()
        if not len(times):
            raise IndexError("no frame read yet")
        return int(np.abs(times - t).argmin())

    def picture(self, k: int):
        from PIL import Image
        return Image.open(io.BytesIO(self.jpeg(k))).convert("RGB")


def build_all(paths: list[Path], settings: Settings, progress=print, should_stop=None,
              root: Path = ROOT) -> list[RushIndex]:
    """Index several rushes, one after the other, printing progress lines the window understands."""
    vision, sounds = Vision(settings.vision), Sounds()
    out = []
    for n, p in enumerate(paths, 1):
        ix = RushIndex(p, root)
        progress(f"[{n}/{len(paths)}] reading {p.name}")
        t0 = time.time()

        def on_chunk(done: int, total: int, ix=ix, t0=t0) -> None:
            progress(f"  {done}/{total} chunks ({done / total:.0%}) — {time.time() - t0:.0f} s")

        ix.build(settings, vision, sounds, on_chunk=on_chunk, should_stop=should_stop)
        out.append(ix)
    return out
