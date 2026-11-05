"""Animations inside rendered clips: a box popping in is found, a still clip and noise give nothing."""

import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from fauxraccord.media import ensure_ffmpeg
from fauxraccord.sfx import motion
from fauxraccord.sfx.events import VClip


def _render(path: Path, vf: str, seconds: float = 3.0) -> Path:
    ensure_ffmpeg()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x202020:s=640x360:r=25:d={seconds}",
                    "-vf", vf, "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


@pytest.fixture(scope="module")
def videos(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("motion")
    return {
        "pop": _render(d / "pop.mp4", "drawbox=x=380:y=120:w=160:h=100:color=white:t=fill:enable='gte(t,1)'"),
        "still": _render(d / "still.mp4", "drawbox=x=100:y=100:w=200:h=100:color=white:t=fill"),
        "noise": _render(d / "noise.mp4", "noise=alls=60:allf=t"),
    }


def test_a_box_popping_in_is_one_event_at_its_frame(videos, tmp_path: Path):
    clip = VClip(str(videos["pop"]), 10.0, 13.0, 0.0, 3, "pop.mp4")
    events = motion.analyse([clip], Fraction(25), tmp_path / "cache")
    assert len(events) == 1
    e = events[0]
    assert e.kind == "motion" and e.track == 3 and e.size == "element"
    assert abs(e.t - 11.0) <= 0.08 and abs(e.src - 1.0) <= 0.08
    again = motion.analyse([clip], Fraction(25), tmp_path / "cache")      # from the cache
    assert [x.t for x in again] == [e.t]


def test_still_and_noisy_clips_give_nothing(videos, tmp_path: Path):
    clips = [VClip(str(videos["still"]), 0.0, 3.0, 0.0, 2, "still"), VClip(str(videos["noise"]), 3.0, 6.0, 0.0, 2, "noise")]
    assert motion.analyse(clips, Fraction(25), tmp_path / "cache") == []


def test_typing_is_one_text_event():
    """Letters appearing one by one on a still card: a single "text" event, not one per letter."""
    frames = np.full((60, motion.H, motion.W), 30, np.uint8)
    for i in range(8):                                   # a letter every 4 frames from frame 20
        x = 40 + i * 6
        frames[20 + i * 4:, 50:56, x:x + 4] = 230
    found = motion.detect(frames, 25)
    assert [f["size"] for f in found] == ["text"]
    assert found[0]["frame"] == 20 and found[0]["frames"] >= 28
