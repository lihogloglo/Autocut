"""Moments: index (chunks, resume), rules (stretches, sounds, examples, gauge), project marks, XML."""

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

from fauxraccord.media import ensure_ffmpeg
from fauxraccord.moments import Project, rules
from fauxraccord.moments.index import RushIndex, Settings
from fauxraccord.moments.rules import Moment, MomentType, Signals, find, stretches

GUN = "Gunshot, gunfire"
NAMES = ["Speech", GUN, "Explosion"]


class FakeSounds:
    """Gunfire wherever the track is loud."""

    def names(self):
        return NAMES

    def per_second(self, wave, seconds):
        out = np.zeros((seconds, len(NAMES)), np.float32)
        for s in range(min(seconds, -(-len(wave) // 16000))):
            rms = float(np.sqrt((wave[s * 16000:(s + 1) * 16000] ** 2).mean()))
            out[s, 1] = 1.0 if rms > 0.1 else 0.0
        return out


    def per_second_both(self, wave, seconds):
        tags = self.per_second(wave, seconds)
        fp = np.zeros((seconds, 1024), np.float32)
        fp[:, 0] = tags[:, 1]                    # loud: one direction, quiet: another
        fp[:, 1] = 1 - tags[:, 1]
        return tags, fp


class FakeVision:
    """A frame's vector is its mean colour."""
    name, dim = "clip", 3

    def __init__(self):
        self.calls = 0

    def images(self, frames):
        self.calls += len(frames)
        e = np.array([np.asarray(f, np.float32).reshape(-1, 3).mean(axis=0) + 1 for f in frames], np.float32)
        return e / np.linalg.norm(e, axis=1, keepdims=True)

    def words(self, texts):
        return np.tile(np.array([[1, 0, 0]], np.float32), (len(texts), 1))


@pytest.fixture(scope="module")
def video(tmp_path_factory) -> Path:
    """70 s at 30 fps: red, blue from 20 s to 40 s, red again; two audio tracks, the second one
    silent except a loud tone from 20 s to 30 s."""
    ensure_ffmpeg()
    out = tmp_path_factory.mktemp("rush") / "Session 1.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-y",
                    "-f", "lavfi", "-i", "color=red:size=320x180:rate=30:duration=20",
                    "-f", "lavfi", "-i", "color=blue:size=320x180:rate=30:duration=20",
                    "-f", "lavfi", "-i", "color=red:size=320x180:rate=30:duration=30",
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=70",
                    "-f", "lavfi", "-i", "aevalsrc=0.5*sin(2*PI*440*t)*between(t\\,20\\,30):d=70:s=48000",
                    "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
                    "-map", "[v]", "-map", "3:a", "-map", "4:a", "-c:v", "libx264", "-g", "30",
                    "-preset", "ultrafast", "-c:a", "aac", str(out)], check=True)
    return out


@pytest.fixture()
def index(video, tmp_path) -> RushIndex:
    ix = RushIndex(video, tmp_path / "index")
    ix.build(Settings(chunk=30, width=160), FakeVision(), FakeSounds())
    return ix


@pytest.fixture(autouse=True)
def sound_names(monkeypatch):
    monkeypatch.setattr(rules, "_SOUND_NAMES", NAMES)


def test_stretches_merge_and_drop():
    on = np.zeros(60, bool)
    on[[2, 3, 4, 8, 9, 30]] = True
    assert stretches(on, gap=4, min_len=1) == [(2, 10), (30, 31)]
    assert stretches(on, gap=2, min_len=2) == [(2, 5), (8, 10)]


def test_index_reads_frames_and_tracks(index):
    assert index.complete and len(index.spans()) == 3
    times, emb = index.frames()
    assert len(times) == 35 and times[0] == 0 and abs(times[-1] - 68) < 0.1
    assert emb.shape == (35, 3)
    assert index.audio_tracks == 2
    assert index.tags(0)[:, 1].max() == 0                       # the quiet sine is no gunfire
    assert index.tags(1)[20:30, 1].min() == 1 and index.tags(1)[:19, 1].max() == 0
    assert index.loud(1)[25] > -10 > index.loud(1)[5]
    assert index.jpeg(3)[:2] == b"\xff\xd8"


def test_index_resumes_only_missing_chunks(index, video):
    (index.dir / "c0001.npz").unlink()
    again = RushIndex(video, index.dir.parent)
    vision = FakeVision()
    again.build(Settings(chunk=30, width=160), vision, FakeSounds())
    assert again.complete and vision.calls == 15                # only the 30-60 s chunk was read again


def test_index_starts_over_when_the_shape_changes(index, video):
    again = RushIndex(video, index.dir.parent)
    vision = FakeVision()
    again.build(Settings(chunk=30, width=160, step=5), vision, FakeSounds())
    assert vision.calls == 14


def test_sound_rule_gives_a_state_with_margins(index):
    fight = MomentType("fight", "Combat", mode="state",
                       signals=[{"sound": [GUN], "track": "any", "window": 1, "min": 0.5}],
                       before=5, after=3, gap=5, min_len=2)
    [m] = find([index], [fight], FakeVision())
    assert (m.start, m.anchor, m.end) == (15, 20, 33)


def test_example_rule_finds_the_same_picture(index, video):
    blue = MomentType("blue", "Bleu", mode="event", signals=[{"like": [{"rush": str(video), "t": 30}], "min": 0.99}],
                      before=2, after=1, gap=3, min_len=1)
    [m] = find([index], [blue], FakeVision())
    assert abs(m.anchor - 20) <= 1 and m.end - m.start == 3


def test_stored_vector_examples(index):
    """Presets ship example vectors; those made by another image model are left out."""
    blue = FakeVision().images([np.full((4, 4, 3), (0, 0, 255), np.uint8)])[0].tolist()
    mt = MomentType("blue", "Bleu", combine="any", gap=0, before=0, after=0,
                    signals=[{"like": [{"vector": blue, "model": "clip"}], "min": 0.99}])
    [m] = find([index], [mt], FakeVision())
    assert np.allclose((m.start, m.end), (20, 40), atol=1.05)
    mt.signals[0]["like"][0]["model"] = "jina"
    assert find([index], [mt], FakeVision()) == []


def test_opposite_and_all(index):
    quiet_red = MomentType("x", "x", combine="all", signals=[
        {"opposite": {"sound": [GUN], "window": 1, "min": 0.5}},
        {"opposite": {"like": [{"rush": str(index.path), "t": 30}], "min": 0.99}}], before=0, after=0, gap=0)
    found = find([index], [quiet_red], FakeVision())
    # a frame every 2 s: edges are known to ±1 s
    assert np.allclose([(m.start, m.end) for m in found], [(0, 20), (40, 70)], atol=1.05)


def test_unready_types_are_skipped(index):
    low = MomentType("low", "Vie basse", signals=[{"zone": None, "below": 0.3}])
    assert not low.ready() and find([index], [low], FakeVision()) == []


def test_gauge_reads_the_fill(tmp_path):
    from PIL import Image
    from fauxraccord.moments import zones

    class Frames:
        dir = tmp_path

        def frames(self):
            return np.arange(5.0), np.zeros((5, 3))

        def picture(self, k):
            im = Image.new("RGB", (200, 100), (30, 30, 30))
            fill = [1.0, 0.8, 0.5, 0.2, 1.0][k]
            im.paste((90, 200, 60), (100, 80, 100 + int(80 * fill), 90))
            return im

    fill = zones.gauge(Frames(), [0.5, 0.8, 0.4, 0.1], "left")
    assert np.allclose(fill, [1.0, 0.8, 0.5, 0.2, 1.0], atol=0.03)


def test_project_keeps_marks(tmp_path):
    p = Project(tmp_path / "a.moments.json")
    p.use_preset("rust")
    p.moments = [Moment("death", "C:/r.mkv", 10, 40, 38, 0.9, kept=True), Moment("fight", "C:/r.mkv", 0, 5, 0, 0.5, kept=False)]
    p.save()
    p = Project(tmp_path / "a.moments.json")
    p.update([Moment("death", "C:/r.mkv", 12, 41, 39, 0.8), Moment("fight", "C:/r.mkv", 100, 110, 100, 0.5)])
    assert [m.kept for m in p.moments] == [True, None]
    assert {t.id for t in p.types} >= {"death", "fight", "low"}


def test_xml_string_outs_and_markers(index, video, tmp_path):
    from fauxraccord.moments.export import write
    types = [MomentType("fight", "Combat"), MomentType("death", "Mort")]
    ms = [Moment("fight", str(video), 15, 33, 20, 0.9), Moment("death", str(video), 40, 45, 44, 0.7, kept=True),
          Moment("death", str(video), 50, 55, 54, 0.6, kept=False)]
    out = tmp_path / "m.xml"
    names = write(out, ms, types, "test")
    assert names == ["Moments · Combat", "Moments · Mort", "Moments · ✓", "Session 1 · moments"]
    root = ET.parse(out).getroot()
    seqs = root.findall(".//sequence")
    ids = [e.get("id") for e in root.iter() if e.get("id") and e.tag in ("sequence", "clipitem")]
    assert len(ids) == len(set(ids))
    for ci in root.iter("clipitem"):
        assert ci.findtext("name") == "Session 1.mkv"           # the rush keeps its name and link
    fight = seqs[0].find("media/video/track/clipitem")
    assert (int(fight.findtext("in")), int(fight.findtext("out"))) == (15 * 30, 33 * 30)
    assert [m.findtext("name") for m in seqs[3].findall("marker")] == ["Combat 90%", "Mort 70%"]
    assert len(seqs[1].findall("media/video/track/clipitem")) == 1   # ✓ only, when the kind has some


def test_old_chunks_get_sound_fingerprints_without_reading_video(index, video):
    for i in index.done():
        f = index.dir / f"c{i:04d}.npz"
        with np.load(f) as z:
            arrays = {k: z[k] for k in z.files if not k.endswith("_emb")}
        np.savez(f, **arrays)
    again = RushIndex(video, index.dir.parent)
    vision = FakeVision()
    again.build(Settings(chunk=30, width=160), vision, FakeSounds())
    assert vision.calls == 0 and again._has(0, "a0_emb")
    fp = again.fingerprints()
    assert fp.shape == (71, 1024) and fp[25] @ fp[5] < 0.9


def test_a_kind_learned_from_one_example(index, video):
    """One stretch of the blue part, shown as an example: the blue part is found, the red is not."""
    mt = MomentType("u-blue", "Bleu", signals=[{"learn": True}], before=0, after=0, gap=3, min_len=2, user=True,
                    examples={"pos": [{"rush": str(video), "start": 22, "end": 28}], "neg": []})
    found = find([index], [mt], FakeVision())
    assert found and all(18 <= m.start and m.end <= 42 for m in found)
    assert any(m.start <= 22 and m.end >= 28 for m in found)
    assert mt.explain["examples"] == 6 and mt.explain["image"] > 2


def test_learned_kind_needs_an_example():
    mt = MomentType("u-x", "X", signals=[{"learn": True}], user=True)
    assert not mt.ready()


def test_marks_teach_a_filter_to_preset_kinds(index, video):
    """A rule kind with ✓ and ✗ is filtered: what is closer to the ✗ than to the ✓ is left out."""
    loud = MomentType("loud", "Fort", signals=[{"sound": [GUN], "window": 1, "min": 0.5}], before=0, after=0, gap=0)
    marks = [Moment("loud", str(video), 20, 23, 20, 0.9, kept=True), Moment("loud", str(video), 27, 30, 27, 0.9, kept=False)]
    found = find([index], [loud], FakeVision(), marks=marks)
    assert loud.explain.get("counter") and "alike" in loud.explain
    assert found      # the ✓ part is kept


def test_look_signal_finds_the_zone_as_it_was(index, video):
    """The zone looks like it did at 30 s (blue): the blue part is found."""
    mt = MomentType("u-look", "Bleu", signals=[{"zone": [0.1, 0.1, 0.3, 0.3], "look": {"rush": str(video), "t": 30}, "z": 3}],
                    before=0, after=0, gap=3, min_len=2)
    [m] = find([index], [mt], FakeVision())
    assert np.allclose((m.start, m.end), (20, 40), atol=1.05)


def test_text_only_kind_scans_sparsely_then_reads_around_hits(index, monkeypatch):
    """No other signal: a scan every 6 s finds the notification (20-30 s), then it is read every 2 s around it."""
    from fauxraccord.moments import zones
    reads = []

    def fake_text(ix, times, box, log=None):
        reads.extend(times)
        return {t: ("SULFUR ORE +98" if 20 <= t < 30 else "TOO COLD") for t in times}

    monkeypatch.setattr(zones, "text_at", fake_text)
    mt = MomentType("u-ore", "Récolte", signals=[{"text": ["ORE"], "zone": [0.8, 0.5, 0.2, 0.4], "window": 4}],
                    before=0, after=0, gap=3, min_len=1)
    [m] = find([index], [mt], FakeVision())
    assert m.start <= 21 and m.end >= 28 and m.start >= 15 and m.end <= 34
    assert len(reads) < 40          # 70 s: 12 scan reads + the dense ones around the hit, not 70


def test_a_zone_added_to_an_any_kind_becomes_a_condition(index, video):
    """{"any": [...]} groups: the old signals stay "or" among themselves, the new box is "and"."""
    mt = MomentType("k", "K", combine="all", before=0, after=0, gap=0, signals=[
        {"any": [{"sound": [GUN], "window": 1, "min": 0.5}, {"like": [{"rush": str(video), "t": 30}], "min": 0.99}]},
        {"zone": [0.1, 0.1, 0.3, 0.3], "look": {"rush": str(video), "t": 25}, "z": 3}])
    [m] = find([index], [mt], FakeVision())
    assert np.allclose((m.start, m.end), (20, 40), atol=1.05)


def test_describe_zone_signals():
    from fauxraccord.moments.rules import describe
    assert describe({"opposite": {"text": ["ORE"], "zone": [0, 0, 1, 1]}}) == {"box": [0, 0, 1, 1], "negate": True, "read": "text", "words": ["ORE"]}
    assert describe({"zone": [0, 0, 1, 1], "below": 0.3})["read"] == "gauge"
    assert describe({"sound": ["Speech"]}) is None


def test_intensity_peaks_on_the_gunfire(index):
    """The loud stretch (gunfire, 20-30 s) is the rush's most intense; the curve is ranked 0..1."""
    from fauxraccord.moments.intensity import curve
    index._cache.pop(("intensity",), None)
    c, parts = curve(index, NAMES)
    assert {"action", "voice", "loud", "pace"} <= set(parts)
    assert 15 <= int(np.nanargmax(c)) <= 35
    assert np.nanmin(c) == 0 and np.nanmax(c) == 1


def test_points_forts_kind_finds_the_intense_stretch(index):
    index._cache.pop(("intensity",), None)
    peaks = MomentType("peaks", "Points forts", signals=[{"intensity": "high", "min": 0.8}], before=0, after=0, gap=3, min_len=3)
    found = find([index], [peaks], FakeVision())
    assert found and any(m.start < 30 and m.end > 20 for m in found)


def test_old_projects_gain_new_preset_kinds(tmp_path):
    import json as _json
    p = Project(tmp_path / "x.moments.json")
    p.use_preset("rust")
    p.types = [t for t in p.types if t.id not in ("peaks", "calm")]
    p.save()
    again = Project(tmp_path / "x.moments.json")
    ids = [t.id for t in again.types]
    assert "peaks" in ids and "calm" in ids
    assert not next(t for t in again.types if t.id == "peaks").enabled
