"""Cut to the beat (fauxraccord.beat): the detector on a click track, the cut rules, the shots, the XML."""

import subprocess
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

from fauxraccord.beat import analysis, compute, plan, write_xml
from fauxraccord.beat.analysis import Analysis
from fauxraccord.beat.plan import Source
from fauxraccord.media import ensure_ffmpeg


def click_track(path: Path, bpm: float = 120.0, seconds: float = 24.0, sr: int = 22050, lead: float = 0.5) -> list[float]:
    """Kick on every beat (louder and lower on the bar's first), hat on the off-beats. Returns the beat times."""
    y = np.zeros(int(seconds * sr), dtype=np.float32)
    period = 60.0 / bpm
    beats = list(np.arange(lead, seconds - 0.5, period))
    t = np.arange(int(0.12 * sr)) / sr
    for i, b in enumerate(beats):
        f = 60.0 if i % 4 == 0 else 110.0
        kick = np.sin(2 * np.pi * f * t) * np.exp(-t * 30) * (1.0 if i % 4 == 0 else 0.55)
        a = int(b * sr)
        y[a:a + len(kick)] += kick[: len(y) - a]
        h = int((b + period / 2) * sr)
        if h < len(y):
            n = min(int(0.03 * sr), len(y) - h)
            y[h:h + n] += np.random.default_rng(i).normal(0, 0.15, n).astype(np.float32) * np.exp(-np.arange(n) / sr * 120)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(y, -1, 1) * 32000).astype(np.int16).tobytes())
    return beats


def fake(beats: list[float], duration: float, phase: int = 0, onsets=None, energy=None) -> Analysis:
    return Analysis(path="m.wav", duration=duration, bpm=60 / float(np.median(np.diff(beats))), beats=beats, phase=phase,
                    meter=4, beat_strength=[1.0] * len(beats), energy=energy or [0.5] * len(beats), onsets=onsets or [])


# --- the detector ----------------------------------------------------------------------------------

def test_click_track_tempo_beats_and_bars(tmp_path):
    ensure_ffmpeg()
    truth = click_track(tmp_path / "click.wav", bpm=120.0)
    a = analysis.analyse(tmp_path / "click.wav")
    assert a.bpm == pytest.approx(120.0, rel=0.02)
    found = np.array(a.beats)
    # every detected beat sits on a real one (within 25 ms), and almost none are missed
    err = [min(abs(found - b)) for b in truth[1:-1]]
    assert np.median(err) < 0.02
    assert sum(e > 0.05 for e in err) <= 2
    # the bar's first beat is the loud low one (every 4th from the first)
    firsts = [b for i, b in enumerate(a.beats) if (i - a.phase) % 4 == 0]
    assert min(abs(np.array(truth[::4]) - firsts[2])) < 0.03


def test_analysis_is_cached(tmp_path, monkeypatch):
    ensure_ffmpeg()
    monkeypatch.setattr(analysis, "CACHE", tmp_path / "cache")
    click_track(tmp_path / "c.wav", seconds=8)
    a = analysis.load(tmp_path / "c.wav")
    monkeypatch.setattr(analysis, "analyse", lambda *_: (_ for _ in ()).throw(AssertionError("not cached")))
    assert analysis.load(tmp_path / "c.wav").beats == a.beats


# --- where the cuts go -------------------------------------------------------------------------------

BEATS = [1.0 + 0.5 * i for i in range(32)]       # 120 BPM from 1 s, bars start on beats 0, 4, 8…
A = fake(BEATS, duration=18.0)


def test_cut_kinds():
    s = {"min_len": 0.1}
    assert plan.cuts(A, {**s, "on": "beat", "every": 1})[:3] == [1.0, 1.5, 2.0]
    assert plan.cuts(A, {**s, "on": "off", "every": 1})[:2] == [1.25, 1.75]
    assert plan.cuts(A, {**s, "on": "half", "every": 1})[:3] == [1.0, 1.25, 1.5]
    assert plan.cuts(A, {**s, "on": "bar", "every": 1})[:3] == [1.0, 3.0, 5.0]


def test_one_in_n_counts_from_the_bar_and_can_shift():
    assert plan.cuts(A, {"on": "beat", "every": 2})[:3] == [1.0, 2.0, 3.0]          # on 1 and 3
    assert plan.cuts(A, {"on": "beat", "every": 2, "shift": 1})[:3] == [1.5, 2.5, 3.5]   # on 2 and 4
    assert plan.cuts(A, {"on": "beat", "every": 4})[:2] == [1.0, 3.0]
    # bars follow the phase
    assert plan.cuts(fake(BEATS, 18.0, phase=1), {"on": "bar", "every": 1})[:2] == [1.5, 3.5]


def test_tempo_correction():
    assert plan.cuts(A, {"on": "beat", "every": 1, "tempo": 2, "min_len": 0.1})[:3] == [1.0, 1.25, 1.5]
    assert plan.cuts(A, {"on": "beat", "every": 1, "tempo": 0.5})[:3] == [1.0, 2.0, 3.0]


def test_hand_cuts_nudge_range_and_min_len():
    s = {"on": "bar", "every": 1, "add": [4.0], "del": [5.01]}      # 5.01: a click a hair off the cut
    cuts = plan.cuts(A, s)
    assert 4.0 in cuts and 5.0 not in cuts and 3.0 in cuts
    assert plan.cuts(A, {"on": "bar", "every": 1, "nudge": -2}, fps=25)[0] == pytest.approx(0.92)    # two frames early
    assert plan.cuts(A, {"on": "bar", "every": 1, "range": [2.5, 9.0]}) == [3.0, 5.0, 7.0]
    assert plan.cuts(A, {"on": "half", "every": 1, "min_len": 0.4})[:3] == [1.0, 1.5, 2.0]


def test_a_hand_cut_next_to_a_computed_one_moves_it():
    cuts = plan.cuts(A, {"on": "bar", "every": 1, "add": [3.2]})        # the bar at 3.0 moves to 3.2
    assert 3.2 in cuts and 3.0 not in cuts
    cuts = plan.cuts(A, {"on": "bar", "every": 1, "add": [2.85]})       # also when it comes first
    assert 2.85 in cuts and 3.0 not in cuts


def test_no_cut_zones():
    cuts = plan.cuts(A, {"on": "beat", "every": 1, "holds": [[2.9, 5.1]], "add": [4.0]})
    assert [c for c in cuts if 2.5 < c < 5.5] == [4.0]               # only the hand cut inside the zone


def test_accents_keep_the_strongest():
    a = fake(BEATS, 18.0, onsets=[(2.1, 0.9), (2.4, 0.4), (3.3, 1.0), (4.2, 0.36), (6.0, 0.2)])
    assert plan.cuts(a, {"on": "accent", "every": 1}) == [2.1, 2.4, 3.3, 4.2]          # 0.2: too weak
    assert plan.cuts(a, {"on": "accent", "every": 2}) == [2.1, 3.3]


def test_follow_cuts_less_where_it_is_quiet():
    energy = [0.1] * 16 + [0.9] * 16
    a = fake(BEATS, 18.0, energy=energy)
    cuts = plan.cuts(a, {"on": "beat", "every": 1, "follow": True})
    quiet = [c for c in cuts if c < 9.0]
    loud = [c for c in cuts if c >= 9.0]
    assert len(loud) > 2 * len(quiet)


# --- what fills the shots ---------------------------------------------------------------------------

SRC = [Source("a", "a.mp4", "a.mp4", 0, 100), Source("b", "b.mp4", "b.mp4", 0, 50), Source("c", "c.mp4", "c.mp4", 10, 20)]


def test_shuffle_never_repeats_and_uses_every_rush():
    cuts = plan.cuts(A, {"on": "beat", "every": 1})
    shots = plan.shots(cuts, SRC, {"order": "shuffle"}, A.duration)
    assert len(shots) == len(cuts) + 1
    assert all(x["src"] != y["src"] for x, y in zip(shots, shots[1:]))
    assert {x["src"] for x in shots} == {"a", "b", "c"}
    assert shots[0]["t0"] == 0 and shots[-1]["t1"] == A.duration


def test_in_points_stay_inside_the_rush_and_switched_off_rushes_are_left_out():
    cuts = plan.cuts(A, {"on": "bar"})
    src = [Source(**{**vars(x)}) for x in SRC]
    src[0].on = False
    for take in ("start", "spread", "random"):
        shots = plan.shots(cuts, src, {"order": "order", "take": take}, A.duration)
        assert "a" not in {x["src"] for x in shots}
        for x in shots:
            s = next(y for y in src if y.id == x["src"])
            assert s.start <= x["in"] and x["in"] + (x["t1"] - x["t0"]) <= s.end + 1e-6


def test_from_the_start_plays_each_rush_on():
    cuts = [2.0, 4.0, 6.0, 8.0]
    shots = plan.shots(cuts, [SRC[0], SRC[1]], {"order": "order", "take": "start"}, 10.0)
    a = [x for x in shots if x["src"] == "a"]
    assert [x["in"] for x in a] == [0.0, 2.0, 4.0]


def test_a_shot_changed_by_hand_is_kept():
    cuts = [2.0, 4.0]
    s = {"order": "order", "shots": {"2000": {"src": "b", "in": 33.0}}}
    shots = plan.shots(cuts, SRC, s, 6.0)
    assert shots[1]["src"] == "b" and shots[1]["in"] == 33.0 and shots[1]["hand"]


def test_a_rush_too_short_gives_way():
    shots = plan.shots([5.0], [Source("tiny", "t.mp4", "t.mp4", 0, 1), SRC[0]], {"order": "order"}, 10.0)
    assert all(x["src"] == "a" for x in shots)


# --- the XML ------------------------------------------------------------------------------------------

def _video(path: Path, seconds: int = 12) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=25:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)


def test_export_two_sequences_with_original_names(tmp_path, monkeypatch):
    ensure_ffmpeg()
    monkeypatch.setattr(analysis, "CACHE", tmp_path / "cache")
    from fauxraccord.beat import sources
    monkeypatch.setattr(sources, "PROBES", tmp_path / "cache" / "probes.json")
    click_track(tmp_path / "music.wav", seconds=16)
    _video(tmp_path / "rush A.mp4")
    _video(tmp_path / "rush B.mp4")
    st = {"music": str(tmp_path / "music.wav"), "rushes": [str(tmp_path)], "audio": True,
          "settings": {"on": "bar", "every": 1}}
    view = compute(st)
    assert len(view["sources"]) == 2 and view["shots"]
    out = tmp_path / "cut.xml"
    r = write_xml(st, out)
    root = ET.parse(out).getroot()
    seqs = root.findall(".//sequence")
    assert [s.findtext("name") for s in seqs] == ["music · au rythme", "music · repères"]
    v1 = seqs[0].find("media/video/track")
    clips = v1.findall("clipitem")
    assert len(clips) == r["shots"] == len(view["shots"])
    assert {c.findtext("name") for c in clips} <= {"rush A.mp4", "rush B.mp4"}
    # shots butt against each other, and the cuts fall on the markers
    ends = [(int(c.findtext("start")), int(c.findtext("end"))) for c in clips]
    assert all(a[1] == b[0] for a, b in zip(ends, ends[1:]))
    marks = sorted(int(m.findtext("in")) for m in seqs[0].findall("marker"))
    assert [b[0] for b in ends[1:]] == marks
    # the music under it, on its own stereo pair; the rushes' sound linked to their picture
    audio = seqs[0].findall("media/audio/track")
    assert len(audio) == 4
    assert all(c.findtext("name") == "music.wav" for c in audio[2].findall("clipitem"))
    assert len(clips[0].findall("link")) == 3
    # markers only: the music and its markers
    write_xml(st, tmp_path / "marks.xml", only_marks=True)
    only = ET.parse(tmp_path / "marks.xml").getroot().findall(".//sequence")
    assert [s.findtext("name") for s in only] == ["music · repères"]


def test_sources_from_a_premiere_sequence(tmp_path):
    from fauxraccord.beat.sources import from_sequence
    p = Path(__file__).parent.parent / "example sequence"
    xmls = sorted(p.glob("*.xml")) if p.exists() else []
    if not xmls:
        pytest.skip("no example sequence")
    srcs = from_sequence(xmls[0])
    assert all(s.end > s.start for s in srcs)
