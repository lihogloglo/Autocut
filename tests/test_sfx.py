"""Sound effects: moments read from an edit, cues planned on them, the XML written."""

import json
import random
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from autocut.media import ensure_ffmpeg
from autocut.sfx import library as L
from autocut.sfx.events import Event, read
from autocut.sfx.export import export
from autocut.sfx.plan import Bag, Cue, Settings, fit, learn, plan

FPS = 25


def clip(track, cid, name, start, end, fid, path=None, scale=None, src_in=0, w=1920, h=1080, audio=False):
    ci = ET.SubElement(track, "clipitem", id=cid)
    for tag, val in (("name", name), ("enabled", "TRUE"), ("start", start), ("end", end), ("in", src_in),
                     ("out", src_in + end - start)):
        ET.SubElement(ci, tag).text = str(val)
    f = ET.SubElement(ci, "file", id=fid)
    if path:
        ET.SubElement(f, "name").text = Path(path).name
        ET.SubElement(f, "pathurl").text = "file://localhost/" + str(path).replace("\\", "/")
        if not audio:
            sc = ET.SubElement(ET.SubElement(ET.SubElement(f, "media"), "video"), "samplecharacteristics")
            ET.SubElement(sc, "width").text = str(w)
            ET.SubElement(sc, "height").text = str(h)
    if scale is not None:
        fx = ET.SubElement(ET.SubElement(ci, "filter"), "effect")
        ET.SubElement(fx, "effectid").text = "basic"
        p = ET.SubElement(fx, "parameter")
        ET.SubElement(p, "parameterid").text = "scale"
        if isinstance(scale, tuple):          # keyframes: (frame, value), ...
            for when, v in scale:
                k = ET.SubElement(p, "keyframe")
                ET.SubElement(k, "when").text = str(when)
                ET.SubElement(k, "value").text = str(v)
        else:
            ET.SubElement(p, "value").text = str(scale)
    return ci


def edit_xml(tmp: Path) -> Path:
    """V1 talking head; V2 a full-screen video, a small image, a zoom punch; a transition; A1 voice, A2 a whoosh."""
    root = ET.Element("xmeml", version="5")
    seq = ET.SubElement(ET.SubElement(ET.SubElement(root, "project"), "children"), "sequence", id="seq-1")
    ET.SubElement(seq, "name").text = "montage"
    ET.SubElement(seq, "duration").text = str(20 * FPS)
    ET.SubElement(ET.SubElement(seq, "rate"), "timebase").text = str(FPS)
    media = ET.SubElement(seq, "media")
    video, audio = ET.SubElement(media, "video"), ET.SubElement(media, "audio")
    v1, v2 = ET.SubElement(video, "track"), ET.SubElement(video, "track")
    clip(v1, "c1", "cam.mp4", 0, 20 * FPS, "f1", tmp / "cam.mp4")
    clip(v2, "c2", "broll.mp4", 2 * FPS, 4 * FPS, "f2", tmp / "broll.mp4", scale=100)
    tr = ET.SubElement(v2, "transitionitem")
    ET.SubElement(tr, "start").text = str(4 * FPS - 5)
    ET.SubElement(tr, "end").text = str(4 * FPS + 5)
    ET.SubElement(ET.SubElement(tr, "effect"), "name").text = "Push"
    clip(v2, "c3", "map.png", -1, 6 * FPS, "f3", tmp / "map.png", scale=40, w=1920, h=1080)
    clip(v2, "c4", "chart.png", 10 * FPS, 14 * FPS, "f4", tmp / "chart.png", scale=((0, 100), (10, 160)))
    a1, a2 = ET.SubElement(audio, "track"), ET.SubElement(audio, "track")
    clip(a1, "a1", "voice.wav", 0, 20 * FPS, "f5", tmp / "voice.wav", audio=True)
    clip(a2, "a2", "ES_Swish Spin - SFX Producer.wav", 2 * FPS, 2 * FPS + 20, "f6", tmp / "swish.wav", audio=True)
    p = tmp / "edit.xml"
    ET.ElementTree(root).write(p, encoding="utf-8")
    return p


def test_reads_what_happens_on_screen(tmp_path: Path):
    e = read(edit_xml(tmp_path))
    kinds = {(round(x.t, 2), x.kind, x.size) for x in e.events}
    assert (2.0, "appear", "full") in kinds                        # the full-frame video
    assert (4.0, "transition", "") in kinds                        # the push, at its middle
    assert not any(x.kind == "appear" and abs(x.t - 3.8) < 0.1 for x in e.events)   # the transition hits, not the image
    assert (10.0, "appear", "element") not in kinds and any(x.kind == "appear" and x.t == 10.0 for x in e.events)
    assert any(x.kind == "move" and 10.0 < x.t < 10.5 for x in e.events)            # the zoom punch (0.4 s)
    assert any(x.kind == "exit" and x.t == 14.0 for x in e.events)
    assert e.voice_track == 1 and [s.name for s in e.sounds] == ["ES_Swish Spin - SFX Producer.wav"]
    full = next(x for x in e.events if x.t == 2.0)
    assert full.covered.startswith("ES_Swish")                     # already sonorized by the editor


def snd(i, kind="click", peak=-6.0, sync=0.01, dur=0.3):
    return L.Snd(f"t{i}", "folder", kind, f"take {i}", f"/x/{i}.wav", dur, sync, peak, [0.5])


def test_takes_rotate_and_never_repeat_back_to_back():
    bag = Bag([snd(i) for i in range(4)], random.Random(3))
    seq = [bag.draw().id for _ in range(40)]
    assert all(a != b for a, b in zip(seq, seq[1:]))
    for k in range(0, 40, 4):
        assert len(set(seq[k:k + 4])) == 4                          # every take once per round


def test_a_whoosh_peaks_just_after_the_frame_and_a_click_lands_on_it():
    s = Settings()
    c = fit(Cue(1, 10.0, "whoosh", "transition", {"strength": 0.7}, {}), snd(1, "whoosh", sync=0.3, dur=0.8), s)
    assert c.start == pytest.approx(10.04 - 0.3) and c.src_in == 0
    k = fit(Cue(2, 0.005, "click", "appear.element", {"strength": 0.7}, {}), snd(2, sync=0.02), s)
    assert k.start == 0 and k.src_in == pytest.approx(0.015)       # trimmed rather than before the start
    assert k.gain_db == pytest.approx(-17.0 + 6.0)                 # target peak -17 dBFS from a -6 dB file


def test_density_keeps_the_big_moments_and_spaces_sounds():
    events = [Event(t / 10, "appear", 2, strength=0.9 if t % 5 == 0 else 0.3, size="element") for t in range(0, 100, 1)]
    pools = {k: [snd(i, k) for i in range(3)] for k in L.KINDS}
    light = plan(events, pools, Settings(density=1, rules={"appear.element": "pop"}))
    dense = plan(events, pools, Settings(density=3, rules={"appear.element": "pop"}))
    assert 0 < len(light) < len(dense)
    assert all(c.event["strength"] >= 0.7 for c in light)
    assert min(b.t - a.t for a, b in zip(dense, dense[1:])) >= 0.12 - 1e-9


def test_learns_the_editors_habits():
    ev = [Event(i, "motion", 3, 0.8, size="full", covered="ES_Switch Click 2.wav") for i in range(5)]
    ev += [Event(10 + i, "appear", 3, 0.75, size="element", covered="ES_Swish 3.wav") for i in range(4)]
    ev += [Event(20, "appear", 3, 0.85, size="full", covered="ES_Swish 3.wav"),
           Event(21, "appear", 3, 0.85, size="full", covered="click.wav")]
    assert learn(ev) == {"motion.full": "click", "appear.element": "whoosh"}


def test_writes_the_sounds_on_their_own_tracks(tmp_path: Path):
    ensure_ffmpeg()
    wav = tmp_path / "whoosh.wav"
    L.write_wav(wav, (np.random.default_rng(1).standard_normal((24000, 2)) * 0.1).astype(np.float32))
    take = L.Snd("file:w", "folder", "whoosh", "whoosh", str(wav), 0.5, 0.2, -10.0, [])
    cues = [fit(Cue(i, 3.0 + i, "whoosh", "transition", {"strength": 0.7}, {}), take, Settings()) for i in range(3)]
    cues[1].on = False
    out = export(cues, edit_xml(tmp_path), "montage", tmp_path / "x Sons.xml", "x", Fraction(FPS), (1920, 1080), 20.0,
                 log=lambda *a: None)
    root = ET.parse(out).getroot()
    seqs = root.findall("project/children/sequence")
    assert [s.findtext("name") for s in seqs] == ["x Sons", "montage + Sons"]
    alone = seqs[0].findall("media/audio/track")
    assert len(alone) == 2 and all(len(t.findall("clipitem")) == 2 for t in alone)     # stereo pair, the 2 cues on
    first = alone[0].find("clipitem")
    assert first.findtext("start") == str(round(cues[0].start * FPS))
    level = float(first.find(".//parameter/value").text)
    assert level == pytest.approx(10 ** (cues[0].gain_db / 20), rel=1e-4)
    assert len(seqs[1].findall("media/audio/track")) == 4                              # the edit's 2 + 2
    assert sum(1 for f in root.iter("file") if f.get("id") == "sfx-file-1" and len(f)) == 1   # defined once


def test_measures_a_sound_where_it_hits():
    y = np.zeros(16000, dtype=np.float32)
    y[4000:4400] = 0.8                                  # an attack at 0.25 s
    m = L.measure(y, 16000, "click")
    assert m["sync"] == pytest.approx(0.25, abs=0.006) and m["peak_db"] == pytest.approx(-1.94, abs=0.05)
    assert L.kind_of("ES_Swish Spin - SFX Producer") == "whoosh"
    assert L.kind_of("Cymbal, Stick Drag") == ""          # « stick » is not a tick
    assert L.kind_of("ES_Typing On Keyboard") == "typing"


def test_the_page_replans_without_losing_hand_edits(tmp_path: Path):
    from autocut.sfx import page
    events = [Event(float(t), "appear", 2, 0.8, size="full") for t in range(1, 10)]
    pools = {"whoosh": [snd(i, "whoosh") for i in range(3)]}
    cues = plan(events, pools, Settings(density=2, rules={"appear.full": "whoosh"}))
    (tmp_path / "events.json").write_text(json.dumps([e.to_json() for e in events]))
    (tmp_path / "pools.json").write_text(json.dumps({k: [s.to_json() for s in v] for k, v in pools.items()}))
    (tmp_path / "cues.json").write_text(json.dumps({"settings": {"rules": {"appear.full": "whoosh"}},
                                                    "cues": [c.to_json() for c in cues]}))
    moved = page.update(tmp_path, cues[0].id, {"t": 1.08, "gain_db": -3})
    assert moved["edited"] and moved["t"] == pytest.approx(1.08) and moved["gain_db"] == -3
    st = page.replan(tmp_path, {"density": 1})
    kept = next(c for c in st["cues"] if c["id"] == cues[0].id)
    assert kept["t"] == pytest.approx(1.08) and kept["gain_db"] == -3
    assert not any(abs(c["t"] - 1.0) < 1e-6 for c in st["cues"])   # no second sound where it was


def test_levels_stay_in_the_editors_range_whatever_the_mastering():
    """From the user's finished edit: Swish Spin (peak -6.8) at -5/-10, Switch Click 2 (-2.0) at -15, the quiet
    Swish 3 (-16.4) still at -10/-5, Typing (-0.4) at -15. Never louder than -5, never under -20."""
    from autocut.sfx.plan import sfx_gain
    assert -10 <= sfx_gain("whoosh", -6.8) <= -5
    assert -17 <= sfx_gain("click", -2.0) <= -13
    assert sfx_gain("whoosh", -16.4) == -5.0
    assert -17 <= sfx_gain("typing", -0.4) <= -13
    assert sfx_gain("hit", 3.0) >= -20.0
