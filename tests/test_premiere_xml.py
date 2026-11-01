import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

from autocut.media import MediaInfo
from autocut.premiere_xml import PremiereSequence, pathurl_to_path
from autocut.timeline import Clip
from autocut.sync import Placed, SyncResult
from autocut.xmeml import sync_document


def test_pathurl_forms():
    expected = Path("D:/Rushes/A7S3/C0001.MP4")
    assert pathurl_to_path("file://localhost/D%3a/Rushes/A7S3/C0001.MP4") == expected
    assert pathurl_to_path("file:///D:/Rushes/A7S3/C0001.MP4") == expected
    assert pathurl_to_path("D:/Rushes/A7S3/C0001.MP4") == expected
    assert pathurl_to_path("file://localhost/D:/Mes%20rushes/prise%201.wav") == Path("D:/Mes rushes/prise 1.wav")


def _clipitem(cid: str, name: str, fid: str, pathurl: str, master: str) -> str:
    return f"""
      <clipitem id="{cid}">
        <masterclipid>{master}</masterclipid>
        <name>{name}</name>
        <enabled>TRUE</enabled>
        <start>0</start><end>2500</end><in>0</in><out>2500</out>
        <file id="{fid}"><name>{name}</name><pathurl>{pathurl}</pathurl></file>
      </clipitem>"""


SEQUENCE = f"""<?xml version="1.0" encoding="UTF-8"?>
<xmeml version="4">
  <sequence id="sequence-7">
    <name>Episode 12</name>
    <rate><timebase>25</timebase><ntsc>FALSE</ntsc></rate>
    <media>
      <video><track>{_clipitem("v1", "C0001.MP4", "file-1", "file://localhost/D%3a/Rushes/C0001.MP4", "masterclip-1")}</track></video>
      <audio><track>{_clipitem("a1", "ZOOM0001.WAV", "file-2", "file://localhost/D%3a/Rushes/ZOOM0001.WAV", "masterclip-2")}</track></audio>
    </media>
    <marker><name>old</name><in>10</in><out>-1</out></marker>
  </sequence>
</xmeml>"""

CLIPS = [Clip(1.0, 3.0, "S001 T1/2 · Bonjour", "Iris", 0, 3),
         Clip(5.0, 6.0, "S001 T2/2 · Bonjour", "Forest", 4, 6)]


def _sequences(path: Path) -> dict[str, ET.Element]:
    root = ET.parse(path).getroot()
    return {s.findtext("name"): s for s in root.iter("sequence")}


def test_premiere_export_keeps_clip_names(tmp_path: Path):
    src = tmp_path / "in.xml"
    src.write_text(SEQUENCE, encoding="utf-8")
    out = tmp_path / "out.xml"
    PremiereSequence.from_file(src).export(out, "Episode 12", [("1 sync", None), ("3 derush", CLIPS)])

    seqs = _sequences(out)
    assert list(seqs) == ["1 sync", "3 derush"]
    seq = seqs["3 derush"]
    items = seq.findall(".//clipitem")
    assert len(items) == 4
    by_file = {}
    for ci in items:
        by_file.setdefault(ci.find("file").get("id"), set()).add(
            (ci.findtext("name"), ci.findtext("masterclipid")))
    assert by_file == {"file-1": {("C0001.MP4", "masterclip-1")},
                       "file-2": {("ZOOM0001.WAV", "masterclip-2")}}
    assert [ci.findtext("labels/label2") for ci in seq.findall("media/video/track/clipitem")] == ["Iris", "Forest"]

    markers = [(m.findtext("name"), int(m.findtext("in")), int(m.findtext("out"))) for m in seq.findall("marker")]
    assert markers == [("S001 T1/2 · Bonjour", 0, 50), ("S001 T2/2 · Bonjour", 50, 75)]

    sync = seqs["1 sync"]
    assert [m.findtext("name") for m in sync.findall("marker")] == ["old"]   # the sync is left as it was
    assert [ci.findtext("in") for ci in sync.iter("clipitem")] == ["0", "0"]


def test_export_defines_each_file_once_and_ids_are_unique(tmp_path: Path):
    src = tmp_path / "in.xml"
    src.write_text(SEQUENCE, encoding="utf-8")
    out = tmp_path / "out.xml"
    PremiereSequence.from_file(src).export(out, "Episode 12", [("1", None), ("2", CLIPS), ("3", CLIPS[:1])])
    root = ET.parse(out).getroot()
    full = [f.get("id") for f in root.iter("file") if f.find("pathurl") is not None]
    assert sorted(full) == ["file-1", "file-2"]
    ids = [e.get("id") for e in root.iter() if e.get("id")]
    file_ids = [e.get("id") for e in root.iter("file")]
    others = [i for i in ids if i not in file_ids]
    assert len(others) == len(set(others))
    refs = {r.text for r in root.iter("linkclipref")}
    assert refs <= set(others)


def test_contiguous_clips_do_not_repeat_a_frame(tmp_path: Path):
    src = tmp_path / "in.xml"
    src.write_text(SEQUENCE, encoding="utf-8")
    out = tmp_path / "out.xml"
    clips = [Clip(0.0, 1.01, "a", "Iris", 0, 0), Clip(1.01, 2.5, "", "Blue", -1, -1)]
    PremiereSequence.from_file(src).export(out, "x", [("2 triage", clips)])
    v = _sequences(out)["2 triage"].findall("media/video/track/clipitem")
    assert [(ci.findtext("in"), ci.findtext("out")) for ci in v] == [("0", "26"), ("26", "63")]
    assert len(_sequences(out)["2 triage"].findall("marker")) == 1   # silence has no marker


def test_sync_document_names_tracks_and_subframe_ticks(tmp_path: Path):
    infos = [MediaInfo(Path("D:/Rushes/C0001.MP4"), 10.0, Fraction(25), 1920, 1080, 2, 48000, True),
             MediaInfo(Path("D:/Rushes/ZOOM0001.WAV"), 12.0, Fraction(25), 1920, 1080, 1, 48000, False)]
    result = SyncResult(25, 1, [Placed(0, 0, 0, 250, 0.0), Placed(1, 0, 0, 120, 2.0123),
                                Placed(1, 0, 120, 100, 6.8125)], [], [True, True])
    seq = PremiereSequence(sync_document(infos, result, "Ep 1 sync"))
    kinds = [(t.kind, len(t.items)) for t in seq.tracks]
    assert kinds == [("video", 1), ("audio", 1), ("audio", 1), ("audio", 2)]   # V1, cam L/R, recorder
    assert seq.source(seq.analysis_track.items[0]).name == "ZOOM0001.WAV"
    assert {ci.findtext("name") for ci in seq.seq.iter("clipitem")} == {"C0001.MP4", "ZOOM0001.WAV"}
    wav = seq.analysis_track.items
    assert wav[0].ticks_in == round(2.0123 * 254016000000) and wav[0].src_in == 50
    out = tmp_path / "out.xml"
    seq.export(out, "Ep 1", [("Ep 1 sync", None), ("Ep 1 derush", [Clip(1.0, 3.0, "S001", "Iris", 0, 0)])])
    d = _sequences(out)["Ep 1 derush"]
    wav_out = [ci for ci in d.iter("clipitem") if ci.findtext("name") == "ZOOM0001.WAV"]
    assert int(wav_out[0].findtext("pproTicksIn")) == round(2.0123 * 254016000000) + 25 * 10160640000
    video = [ci for ci in d.iter("clipitem") if ci.find("compositemode") is not None]
    assert len(video[0].findall("link")) == 4   # video + 2 camera channels + recorder, linked
