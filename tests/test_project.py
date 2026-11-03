"""Projects: a folder is read for what is already there, and each folder keeps its own inputs/outputs."""

import os
import time
from pathlib import Path

import pytest

from autocut import gui, project


def touch(p: Path, text: str = "x", age: float = 0) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    if age:
        t = time.time() - age
        os.utime(p, (t, t))
    return p


def test_detects_a_shoot_folder(tmp_path: Path):
    """Rushes, the script, Premiere's leftovers and an XML exported by hand (the layout people really have)."""
    d = tmp_path / "Révolution"
    script = touch(d / "La révolte.md", "# T\n## A\nUne phrase.")
    touch(d / "FCP Translation Results 2026-11-02 10-12.txt")
    touch(d / "~$brouillon.docx")
    touch(d / "20261030_LEO3300.MP4")
    touch(d / "301026-153347_Tr1.WAV")
    touch(d / "Proxies" / "LEO3300_Proxy.mp4")
    exported = touch(d / "a derush.xml", "<xmeml/>")
    (d / "La révolte - sources").mkdir()
    found = project.detect(d)
    assert found["script"] == str(script)
    assert found["rushes"] == [str(d)]
    assert found["xml"] == str(exported) and found["place_xml"] == str(exported)
    assert "derush_out" not in found and found["step"] == "derush"


def test_autocut_outputs_chain_to_the_next_step(tmp_path: Path):
    sync = touch(tmp_path / "Ep.sync.xml", age=300)
    derush = touch(tmp_path / "Ep.autocut.xml", age=200)
    touch(tmp_path / "Ep.autocut.txt")                     # the derush report is not a script
    found = project.detect(tmp_path)
    assert "script" not in found
    assert found["sync_out"] == str(sync) and found["xml"] == str(sync) and found["mode"] == "all"
    assert found["derush_out"] == str(derush) and found["place_xml"] == str(derush)
    assert found["step"] == "sources"
    edit = touch(tmp_path / "Ep montage.xml")             # an edit exported from Premiere after the derush
    assert project.detect(tmp_path)["place_xml"] == str(edit)


def test_saved_state_wins_and_blanks_are_filled(tmp_path: Path):
    mine = touch(tmp_path / "choisi.xml", age=100)
    touch(tmp_path / "Ep.autocut.xml")
    data = project.merge({"place_xml": str(mine), "step": "storyboard", "derush_out": str(tmp_path / "gone.xml")}, tmp_path)
    assert data["place_xml"] == str(mine) and data["step"] == "storyboard"
    assert data["derush_out"] == str(tmp_path / "Ep.autocut.xml")     # missing file forgotten, then found again


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(gui, "APPDATA", tmp_path / "appdata")
    monkeypatch.setattr(gui, "STATE_FILE", tmp_path / "appdata" / "app.json")
    return gui.Api()


def test_each_project_keeps_its_own_files(api, tmp_path: Path):
    a = touch(tmp_path / "A" / "A.md")
    b = touch(tmp_path / "B" / "B.md")
    a_derush = touch(tmp_path / "A" / "A.autocut.xml")
    api.add("derush", [str(a)])
    assert api._state["project"] == str((tmp_path / "A").resolve())
    assert api._state["derush_out"] == str(a_derush)
    assert api._out_arg() == ["--out", api._state["project"]]
    api.add("sources", [str(b)])                            # another video's script: its own project
    s = api._state
    assert s["project"] == str((tmp_path / "B").resolve()) and s["script"] == str(b)
    assert s["derush_out"] == "" and s["place_xml"] == ""   # nothing leaks from A
    api.open_project(str(tmp_path / "A"))
    assert api._state["script"] == str(a) and api._state["derush_out"] == str(a_derush)
    assert [Path(r).name for r in api._state["recent"]] == ["A", "B"]
    assert gui.Api()._state["project"] == str((tmp_path / "A").resolve())     # remembered


def test_files_dropped_before_the_script_follow_it(api, tmp_path: Path):
    rushes = tmp_path / "Rushs"
    touch(rushes / "cam.mp4")
    api.add("sync", [str(rushes)])
    script = touch(tmp_path / "Projet" / "Ep.md")
    api.add("sync", [str(script)])
    assert api._state["project"] == str((tmp_path / "Projet").resolve())
    assert api._state["rushes"] == [str(rushes)]


def test_a_sequence_dropped_on_the_storyboard_gives_its_timings(api, tmp_path: Path):
    edit = touch(tmp_path / "montage.xml", "<xmeml/>")
    api.add("storyboard", [str(edit)])
    assert api._state["place_xml"] == str(edit) and api._state["xml"] == ""
