"""Reading very long recordings cheaply: what is in the file, a small frame every few seconds,
and each audio track on its own (OBS records the game, the mic and Discord on separate tracks).

Frames come from ffmpeg as raw RGB on stdout; their times come from the `showinfo` filter on
stderr. `select` keeps one frame every `step` seconds. With `keyframes=True` the decoder skips
every frame that is not a keyframe, which is many times faster on a 60 fps recording: frames are
then only as dense as the recording's keyframes (OBS: every 2 s when set for streaming, ~4 s by
default), which is why the step-0 test measures the spacing first.
"""

from __future__ import annotations

import json
import queue
import re
import subprocess
import threading
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Iterator

import numpy as np

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SR = 16000
VIDEO_EXT = {".mp4", ".mov", ".mxf", ".mkv", ".avi", ".mts", ".m2ts", ".flv", ".ts", ".webm"}


@dataclass
class AudioTrack:
    index: int            # n-th audio stream (ffmpeg's 0:a:n)
    channels: int
    rate: int
    title: str = ""


@dataclass
class Recording:
    path: Path
    duration: float
    fps: Fraction
    width: int
    height: int
    vcodec: str
    audio: list[AudioTrack] = field(default_factory=list)

    @property
    def has_video(self) -> bool:
        return self.width > 0


def probe(path: Path) -> Recording:
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                          str(path)], capture_output=True, text=True, check=True, creationflags=NO_WINDOW).stdout
    data = json.loads(out)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    audio = [s for s in data["streams"] if s["codec_type"] == "audio"]
    dur = float(data["format"].get("duration") or 0) or max(
        (float(s.get("duration") or 0) for s in data["streams"]), default=0.0)
    return Recording(
        path=Path(path).resolve(), duration=dur,
        fps=Fraction(video["r_frame_rate"]) if video else Fraction(25),
        width=int(video["width"]) if video else 0, height=int(video["height"]) if video else 0,
        vcodec=video.get("codec_name", "") if video else "",
        audio=[AudioTrack(k, int(s.get("channels", 2)), int(s.get("sample_rate", 48000)),
                          (s.get("tags") or {}).get("title", "")) for k, s in enumerate(audio)],
    )


def keyframe_times(path: Path, seconds: float = 120.0, start: float = 0.0) -> np.ndarray:
    """Times of the keyframes in [start, start + seconds) (read from the packets: no decoding)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-read_intervals", f"{start}%+{seconds}",
         "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, creationflags=NO_WINDOW).stdout
    times = []
    for line in out.splitlines():
        parts = line.strip().split(",")
        if len(parts) >= 2 and "K" in parts[1]:
            try:
                times.append(float(parts[0]))
            except ValueError:
                pass
    return np.array(sorted(times))


def keyframe_spacing(path: Path, seconds: float = 120.0, start: float = 0.0) -> float | None:
    t = keyframe_times(path, seconds, start)
    return float(np.median(np.diff(t))) if len(t) > 2 else None


def frame_size(rec: Recording, width: int) -> tuple[int, int]:
    w = min(width, rec.width) // 2 * 2
    return w, max(2, round(w * rec.height / rec.width / 2) * 2)


_PTS = re.compile(r"pts_time:\s*([-\d.]+)")


def frames(rec: Recording, start: float, length: float, step: float, width: int = 512,
           keyframes: bool = True, hwaccel: str | None = None) -> Iterator[tuple[float, np.ndarray]]:
    """(time in the file, H×W×3 uint8) about every `step` seconds of [start, start + length)."""
    w, h = frame_size(rec, width)
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "info"]
    if keyframes:
        cmd += ["-skip_frame", "nokey"]
    if hwaccel:
        cmd += ["-hwaccel", hwaccel]
    vf = (f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{step - 0.05:.3f})',"
          f"scale={w}:{h}:flags=area,showinfo")
    cmd += ["-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(rec.path), "-map", "0:v:0", "-an", "-sn",
            "-vf", vf, "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                            creationflags=NO_WINDOW)
    times: queue.Queue = queue.Queue()
    errors: list[str] = []

    def read_err() -> None:
        for raw in proc.stderr:
            line = raw.decode("utf-8", "replace")
            if "Parsed_showinfo" in line and (m := _PTS.search(line)):
                times.put(float(m[1]))
            elif "rror" in line:
                errors.append(line.strip())
        times.put(None)

    threading.Thread(target=read_err, daemon=True).start()
    size = w * h * 3
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            t = times.get(timeout=60)
            if t is None:
                break
            yield start + t, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()
    if proc.returncode not in (0, None, 1, -9) and errors and not keyframes:
        raise RuntimeError(errors[-1])


def audio(rec: Recording, track: int, start: float, length: float) -> np.ndarray:
    """One audio track of [start, start + length) as 16 kHz mono float32."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(rec.path),
         "-map", f"0:a:{track}", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        capture_output=True, creationflags=NO_WINDOW)
    return np.frombuffer(proc.stdout, dtype=np.float32)


def loudness(wave: np.ndarray, seconds: int, hop: float = 0.1) -> np.ndarray:
    """Loudest 100 ms of each second, in dBFS (−100 for silence or missing audio)."""
    n = int(SR * hop)
    per = int(round(1 / hop))
    out = np.full(seconds, -100.0, dtype=np.float32)
    blocks = len(wave) // n
    if blocks:
        rms = np.sqrt((wave[: blocks * n].astype(np.float64).reshape(blocks, n) ** 2).mean(axis=1))
        db = 20 * np.log10(np.maximum(rms, 1e-5))
        k = min(seconds, -(-blocks // per))
        padded = np.full(k * per, -100.0)
        padded[: min(blocks, k * per)] = db[: k * per]
        out[:k] = padded.reshape(k, per).max(axis=1)
    return out


def recordings(paths: list[Path]) -> list[Path]:
    """The video files among `paths`, folders read at their top level, in name order."""
    out: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out += sorted(f for f in p.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXT)
        elif p.suffix.lower() in VIDEO_EXT:
            out.append(p)
    return out
