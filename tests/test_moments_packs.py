"""Game packs: kinds taught on one player's rush, shared as a file, finding the same moments on another's."""

import json
import shutil
import subprocess

import numpy as np
import pytest

from fauxraccord.moments import Project, learn, packs, rules
from fauxraccord.moments.index import RushIndex, Settings
from fauxraccord.moments.rules import Moment, MomentType, find

from test_moments import NAMES, FakeSounds, FakeVision, sound_names, video  # noqa: F401  (fixtures)


@pytest.fixture()
def other_video(video, tmp_path):
    """The same picture and sound, in another file: re-encoded, another name, another folder."""
    out = tmp_path / "friend" / "Ma partie.mp4"
    out.parent.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-map", "0", "-c:v", "libx264", "-crf", "28", "-g", "30",
                    "-preset", "ultrafast", "-c:a", "aac", str(out)], check=True)
    return out


@pytest.fixture()
def pack_dir(tmp_path, monkeypatch):
    folder = tmp_path / "packs"
    monkeypatch.setattr(packs, "PACKS", folder)
    return folder


def _index(path, root):
    ix = RushIndex(path, root)
    ix.build(Settings(chunk=30, width=160), FakeVision(), FakeSounds())
    return ix


def _kinds(video):
    taught = MomentType("u-blue", "Bleu", signals=[{"learn": True}], before=0, after=0, gap=3, min_len=2, user=True,
                        examples={"pos": [{"rush": str(video), "start": 22, "end": 28}],
                                  "neg": [{"rush": str(video), "start": 2, "end": 8}]})
    like = MomentType("u-like", "Comme", signals=[{"like": [{"rush": str(video), "t": 30}], "min": 0.99}],
                      before=0, after=0, gap=3, min_len=1, user=True)
    look = MomentType("u-look", "Zone", signals=[{"zone": [0.1, 0.1, 0.3, 0.3], "look": {"rush": str(video), "t": 30}, "z": 3}],
                      before=0, after=0, gap=3, min_len=2, user=True)
    loud = MomentType("fight", "Combat", signals=[{"sound": ["Gunshot, gunfire"], "window": 1, "min": 0.5}],
                      before=0, after=0, gap=0)
    return [taught, like, look, loud]


def _spans(found, kind):
    return [(m.start, m.end) for m in found if m.type == kind]


def test_a_pack_finds_the_same_moments_on_someone_elses_rush(video, other_video, tmp_path, pack_dir):
    root_a, root_b = tmp_path / "index-a", tmp_path / "index-b"
    ix_a = _index(video, root_a)
    proj = Project(tmp_path / "a.moments.json")
    proj.rushes, proj.types = [str(video)], _kinds(video)
    proj.moments = [Moment("fight", str(video), 20, 23, 20, 0.9, kept=True), Moment("fight", str(video), 27, 30, 27, 0.9, kept=False)]
    before = find([ix_a], proj.types, FakeVision(), marks=proj.moments)
    for k in ("u-blue", "u-like", "u-look", "fight"):
        assert _spans(before, k), k

    out = packs.export(proj, proj.types, tmp_path / "out" / "Rouge et bleu", name="Rouge et bleu", game="Test", root=root_a)
    assert out["path"].endswith("Rouge et bleu.fauxpack.json") and not out["skipped"]
    text = (tmp_path / "out" / "Rouge et bleu.fauxpack.json").read_text(encoding="utf-8")
    assert str(video.parent).replace("\\", "\\\\") not in text and '"rush"' not in text and '"moments"' not in text
    data = json.loads(text)
    assert data["format"] == "fauxraccord-moments-pack" and data["version"] == 1 and data["game"] == "Test"
    blue = next(t for t in data["types"] if t["id"] == "u-blue")
    assert set(blue["examples"]) == {"pos", "neg", "pos_vectors", "neg_vectors"} and not blue["examples"]["pos"]
    fight = next(t for t in data["types"] if t["id"] == "fight")
    assert "pos_vectors" in fight["examples"] and "neg_vectors" in fight["examples"]       # its ✓ and ✗

    shutil.rmtree(root_a)                              # the author's index is gone: only the pack remains
    pid = packs.import_pack(tmp_path / "out" / "Rouge et bleu.fauxpack.json")
    assert pid == "pack:rouge-et-bleu" and (pack_dir / "rouge-et-bleu.fauxpack.json").exists()
    assert any(p["id"] == pid and p["pack"] and p["types"] == 4 for p in rules.presets())

    friend = Project(tmp_path / "friend" / "friend.moments.json")
    friend.rushes, friend.types = [str(other_video)], []
    res = packs.add_to(friend, pid)
    assert res["added"] == ["Bleu", "Comme", "Zone", "Combat"] and not res["renamed"]
    ix_b = _index(other_video, root_b)
    after = find([ix_b], friend.types, FakeVision())
    for k in ("u-blue", "u-like", "u-look"):
        assert np.allclose(_spans(after, k), _spans(before, k), atol=1.05), k
    assert friend.types[0].explain["examples"] == 6 and friend.types[0].explain["counter"] == 6
    assert _spans(after, "fight")
    # chosen as a preset, the pack gives the same kinds
    assert [t.id for t in rules.load_preset(pid)] == ["u-blue", "u-like", "u-look", "fight"]


def test_adding_a_pack_renames_what_clashes(tmp_path, pack_dir, video):
    f = tmp_path / "p.fauxpack.json"
    f.write_text(json.dumps({"format": packs.FORMAT, "version": 1, "name": "Mon pack", "types": [
        {"id": "fight", "name": "Combat", "signals": [{"sound": ["Explosion"]}]}]}), encoding="utf-8")
    pid = packs.import_pack(f)
    proj = Project(tmp_path / "x.moments.json")
    proj.types = [MomentType("fight", "Combat", signals=[{"sound": ["Gunshot, gunfire"]}])]
    res = packs.add_to(proj, pid)
    assert [t.id for t in proj.types] == ["fight", "fight-mon-pack"] and proj.types[1].name == "Combat (Mon pack)"
    assert res["renamed"] == ["Combat (Mon pack)"] and proj.types[1].user
    proj.types[1].signals = [{"sound": ["Speech"]}]               # changed here: added again, under a new name
    again = packs.add_to(proj, pid)
    assert again["added"] == ["Combat (Mon pack) 2"] and [t.id for t in proj.types][-1] == "fight-mon-pack-2"
    assert packs.add_to(proj, pid) == {"added": [], "renamed": [], "same": ["Combat"], "name": "Mon pack"}


def test_a_pack_never_points_at_files(tmp_path, pack_dir):
    f = tmp_path / "bad.fauxpack.json"
    f.write_text(json.dumps({"format": packs.FORMAT, "version": 1, "name": "x", "types": [
        {"id": "a", "name": "A", "signals": [{"like": [{"rush": "C:/secret.mp4", "t": 3}]}]},
        {"id": "b", "name": "B", "signals": [{"zone": [0, 0, 1, 1], "look": {"rush": "C:/x.mp4", "t": 1}}]},
        {"id": "c", "name": "C", "signals": [{"learn": True}],
         "examples": {"pos": [{"rush": "C:/x.mp4", "start": 0, "end": 9}], "pos_vectors": {"sound": [[1.0] * 1024]}}}]}),
        encoding="utf-8")
    data = packs.read(f)
    assert [t["id"] for t in data["types"]] == ["c"] and data["types"][0]["examples"]["pos"] == []
    for bad in ({"format": "other", "types": []}, {"format": packs.FORMAT, "version": 9, "types": [{}]}, "not json"):
        f.write_text(bad if isinstance(bad, str) else json.dumps(bad), encoding="utf-8")
        with pytest.raises(packs.PackError):
            packs.import_pack(f)


def test_stored_rows_round_trip_and_other_models_are_skipped():
    rng = np.random.default_rng(1)
    rows = rng.normal(size=(5, 512)).astype(np.float32)
    rows = np.vstack([rows[:2], rows[1:2], rows[2:]])            # a repeated second (same stored frame)
    rows /= np.linalg.norm(rows, axis=1, keepdims=True)
    block = learn.pack_rows(rows)
    assert block["repeat"] == [1, 2, 1, 1, 1]
    back = learn.unpack_rows(json.loads(json.dumps(block)))
    assert back.shape == rows.shape and (back * rows).sum(axis=1).min() > 0.999
    assert np.allclose(learn.unpack_rows(rows.tolist()), rows, atol=1e-6)
    vec = {"model": "clip", "image": block, "sound": [[1.0] * 1024]}
    assert set(learn.stored(vec, "clip", {"image": 512, "sound": 1024})) == {"image", "sound"}
    assert set(learn.stored(vec, "jina", {"image": 768, "sound": 1024})) == {"sound"}


def test_a_stored_look_fits_frames_of_another_size():
    from fauxraccord.moments.zones import LOOK_W, fit_look
    v = np.arange(9 * LOOK_W * 3, dtype=np.float32)
    out = fit_look(v, [9, LOOK_W], 10 * LOOK_W * 3)
    assert out.shape == (10 * LOOK_W * 3,) and abs(np.linalg.norm(out) - 1) < 1e-5
    assert fit_look(v, [9, LOOK_W], 7) is None
