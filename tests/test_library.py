"""The planche's media folder: one file per item whichever way it was asked for (button, drag, placement)."""

import json
from pathlib import Path

from fauxraccord.sourcing.library import Library, key, selected_files
from fauxraccord.sourcing.model import Asset, Manifest

IMG = "a1b2c3d4e5f6"
VID = "0f9e8d7c6b5a"
SHOT = "123456abcdef"


def _project(tmp_path: Path) -> Path:
    """An output folder: a local screenshot, a local image and a video, all on sentence 12."""
    out = tmp_path / "run"
    (out / "captures").mkdir(parents=True)
    (out / "captures" / "page.png").write_bytes(b"png")
    (out / "captures" / "photo.jpg").write_bytes(b"jpg")
    assets = [Asset(SHOT, "screenshot", "capture", "lien", 11, 3, url="https://ex.org/p", file="captures/page.png",
                    title="La page"),
              Asset(IMG, "image", "commons", "recherche", 11, 3, url="https://ex.org/a.jpg", file="captures/photo.jpg",
                    title="Une photo", author="X", licence="CC BY 4.0"),
              Asset(VID, "video", "youtube", "recherche", 11, 3, url="https://youtu.be/x", title="Un film",
                    duration=900, start=80.4, end=110.0)]
    Manifest("script.md", "Épisode", [{"idx": 0, "title": "Intro"}],
             [{"idx": 11, "section": 0, "paragraph": 3, "text": "Une phrase."}], assets).save(out / "manifest.json")
    return out


def test_key_one_file_per_excerpt():
    v = Asset(VID, "video", "youtube", "recherche", 0, 0, start=80.4, end=110.0)
    assert key(v, {}) == f"{VID}@80-110"
    assert key(v, {"start": 12.5, "end": 40}) == f"{VID}@13-40"        # rounded like the page's Math.round
    assert key(v, {"full": True}) == VID
    assert key(Asset(IMG, "image", "web", "lien", 0, 0), {"start": 3}) == IMG


def test_download_once_into_type_folders(tmp_path):
    out = _project(tmp_path)
    lib = Library(out)
    a = lib.assets[IMG]
    first = lib.get(a)
    assert first.parent == out / "médias" / "Images"
    assert first.name == f"S012 commons - Une photo [{IMG}].jpg"
    assert lib.get(a) == first                                         # again: the same file, not a copy
    assert lib.get(lib.assets[SHOT]).parent.name == "Captures d'écran"
    assert sorted(p.name for p in (out / "médias").rglob("*.jpg")) == [first.name]
    credits = (out / "médias" / "credits.txt").read_text(encoding="utf-8-sig")
    assert "Une photo — X — CC BY 4.0" in credits and "== Intro ==" in credits
    st = lib.status()
    assert st["files"][IMG] == f"médias/Images/{first.name}" and st["jobs"] == {}


def test_hover_prefetch_stays_in_cache_until_asked(tmp_path):
    out = _project(tmp_path)
    lib = Library(out)
    job = lib.wait(IMG, {}, 5, keep=False)                              # a hover
    assert job["state"] == "staged" and not (out / "médias").exists()
    job = lib.wait(IMG, {}, 5, keep=True)                               # then a drag or the button
    assert job["state"] == "ready" and Path(job["path"]).parent == out / "médias" / "Images"


def test_older_folders_are_reused_where_they_are(tmp_path):
    out = _project(tmp_path)
    dragged = out / "glissés" / "01 Intro" / f"S012 youtube - Un film 80-110 [{VID[:6]}].mp4"
    dragged.parent.mkdir(parents=True)
    dragged.write_bytes(b"mp4")
    exported = out / "export" / "01 Intro" / "S012-01 commons - Une photo.jpg"
    exported.parent.mkdir(parents=True)
    exported.write_bytes(b"jpg")
    lib = Library(out)
    assert lib.find(lib.assets[VID], {}) == dragged                     # the default excerpt, 80-110
    assert lib.find(lib.assets[VID], {"full": True}) is None            # the whole video is another file
    assert lib.get(lib.assets[IMG]) == exported                         # not downloaded again


def test_placement_skips_what_was_dragged(tmp_path):
    out = _project(tmp_path)
    lib = Library.of(out)
    lib.get(lib.assets[IMG])
    shot = lib.get(lib.assets[SHOT])
    (out / "selection.json").write_text(json.dumps({IMG: {}, SHOT: {}, VID: {}}), encoding="utf-8")
    files, missing = selected_files(out)
    assert [a.id for a, _ in files] == [IMG, SHOT] and missing == 1     # the video is not downloaded yet
    (out / "dragged.json").write_text(json.dumps({SHOT: shot.relative_to(out).as_posix()}), encoding="utf-8")
    files, _ = selected_files(out, skip_dragged=True)
    assert [a.id for a, _ in files] == [IMG]

    from fauxraccord.sourcing.bridge import PANEL_PLACED, ours
    (out / PANEL_PLACED).write_text(json.dumps([str(p.resolve()) for _, p in selected_files(out)[0]]), encoding="utf-8")
    assert ours(out, "sources") == [str(lib.find(lib.assets[IMG]).resolve())]   # never the dragged one
