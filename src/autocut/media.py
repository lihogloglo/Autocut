"""ffprobe/ffmpeg helpers: media properties and decoded audio."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000


@dataclass
class MediaInfo:
    path: Path
    duration: float
    fps: Fraction
    width: int
    height: int
    audio_channels: int
    audio_rate: int

    @property
    def timebase(self) -> int:
        """Integer timebase as FCP7 XML wants it (30 for 29.97, etc.)."""
        return round(float(self.fps))

    @property
    def ntsc(self) -> bool:
        return self.fps.denominator == 1001

    def frames(self, seconds: float) -> int:
        return round(seconds * float(self.fps))


def ensure_ffmpeg() -> None:
    """Use the system ffmpeg if there is one, else download a static build once."""
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    print("  ffmpeg not found: downloading a static build (once)")
    import static_ffmpeg
    static_ffmpeg.add_paths()


def probe(path: Path) -> MediaInfo:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    if audio is None:
        raise ValueError(f"{path} has no audio stream")
    fps = Fraction(video["r_frame_rate"]) if video else Fraction(25)
    return MediaInfo(
        path=path.resolve(),
        duration=float(data["format"]["duration"]),
        fps=fps,
        width=int(video["width"]) if video else 1920,
        height=int(video["height"]) if video else 1080,
        audio_channels=int(audio.get("channels", 2)),
        audio_rate=int(audio.get("sample_rate", 48000)),
    )


def load_audio(path: Path) -> np.ndarray:
    """Decode the first audio stream to 16 kHz mono float32."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"],
        capture_output=True, check=True,
    )
    return np.frombuffer(proc.stdout, dtype=np.float32)


def rms_envelope(audio: np.ndarray, hop: float = 0.01) -> np.ndarray:
    """RMS per `hop` seconds, used to snap cut points into quiet spots."""
    n = int(SAMPLE_RATE * hop)
    frames = len(audio) // n
    blocks = audio[: frames * n].reshape(frames, n)
    return np.sqrt((blocks.astype(np.float64) ** 2).mean(axis=1))
