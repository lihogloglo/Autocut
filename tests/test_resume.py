"""Half-derushed sequences and the per-rush transcript cache."""

import xml.etree.ElementTree as ET
from pathlib import Path

from autocut import _after
from autocut.premiere_xml import PremiereSequence
from autocut.timeline import Clip
from autocut import transcribe
from autocut.transcribe import SourceTranscript, Word, _merge, _subtract, transcribe_ranges

FPS = 25


def _items(spans, kind, fid, path, prefix):
    """spans: (start, end, src_in) in frames; linked to the other track by index."""
    out = []
    for n, (start, end, src) in enumerate(spans, 1):
        other = "a" if prefix == "v" else "v"
        out.append(f"""<clipitem id="{prefix}{n}"><name>{Path(path).name}</name><enabled>TRUE</enabled>
          <start>{start}</start><end>{end}</end><in>{src}</in><out>{src + end - start}</out>
          <file id="{fid}"><name>{Path(path).name}</name><pathurl>file://localhost/{path}</pathurl></file>
          <labels><label2>Mango</label2></labels>
          <link><linkclipref>{prefix}{n}</linkclipref><mediatype>{kind}</mediatype></link>
          <link><linkclipref>{other}{n}</linkclipref></link></clipitem>""")
    return "".join(out)


# 3 hand-cut clips (4 s each, with a gap), then a 2-minute raw take, then 3 minutes raw.
SPANS = [(0, 100, 500), (100, 200, 900), (250, 350, 1500), (350, 3350, 3000), (3350, 7850, 0)]


def _xml(tmp_path: Path) -> Path:
    doc = f"""<?xml version="1.0" encoding="UTF-8"?><xmeml version="4"><sequence id="s1"><name>a derush</name>
      <rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate><media>
      <video><track>{_items(SPANS, "video", "f1", "D:/R/CAM.MP4", "v")}</track></video>
      <audio><track>{_items(SPANS, "audio", "f2", "D:/R/REC.WAV", "a")}</track></audio></media>
      <marker><name>S001 hand</name><in>20</in><out>40</out></marker>
      <marker><name>late</name><in>5000</in><out>5010</out></marker></sequence></xmeml>"""
    path = tmp_path / "a derush.xml"
    path.write_text(doc, encoding="utf-8")
    return path


def test_finds_where_the_hand_derush_stopped(tmp_path: Path):
    info = PremiereSequence.from_file(_xml(tmp_path)).derushed_until()
    assert info["cutoff"] == 350 / FPS
    assert (info["done_clips"], info["raw_clips"]) == (3, 2)
    assert info["raw_names"] == ["REC.WAV"]


def test_raw_and_fully_cut_sequences(tmp_path: Path):
    seq = PremiereSequence.from_file(_xml(tmp_path))
    seq.analysis_track.items = seq.analysis_track.items[3:]
    assert seq.derushed_until()["cutoff"] == 0.0
    seq.analysis_track.items = PremiereSequence.from_file(_xml(tmp_path)).analysis_track.items[:3]
    assert seq.derushed_until()["cutoff"] is None


def test_kept_part_is_copied_untouched(tmp_path: Path):
    seq = PremiereSequence.from_file(_xml(tmp_path))
    keep = 350 / FPS
    clips = _after([Clip(0.5, 1.5, "S001 T1/1 · a", "Iris", 0, 1),            # inside the kept part
                    Clip(13.9, 20.0, "S002 T1/1 · b", "Iris", 2, 3)], keep)   # straddles the cut-off
    out = tmp_path / "out.xml"
    seq.export(out, "a", [("a derush", None), ("3 derush", clips)])
    s = [x for x in ET.parse(out).getroot().iter("sequence") if x.findtext("name") == "3 derush"][0]
    video = s.findall("media/video/track/clipitem")
    assert [(int(c.findtext("start")), int(c.findtext("end")), int(c.findtext("in"))) for c in video[:3]] == \
        [(0, 100, 500), (100, 200, 900), (250, 350, 1500)]          # gap and sources kept
    assert video[0].findtext("labels/label2") == "Mango"
    links = [ln.findtext("linkclipref") for ln in video[1].findall("link")]
    ids = {c.get("id") for c in s.iter("clipitem")}
    assert len(links) == 2 and set(links) <= ids                     # links point at the copies
    # the derushed clip starts right after: 350 + (20 - 14) s of the raw take
    assert (int(video[3].findtext("start")), int(video[3].findtext("end"))) == (350, 350 + 150)
    names = [m.findtext("name") for m in s.findall("marker")]
    assert "S001 hand" in names and "late" not in names and "S001 T1/1 · a" in names


def test_kept_part_closes_gaps(tmp_path: Path):
    seq = PremiereSequence.from_file(_xml(tmp_path))
    keep = 350 / FPS
    assert seq.islands(keep) == [(0.0, 8.0), (10.0, 14.0)]
    out = tmp_path / "out.xml"
    seq.export(out, "a", [("3 derush", _after([Clip(15.0, 16.0, "S002", "Iris", 0, 1)], keep, seq.islands(keep)))])
    video = [x for x in ET.parse(out).getroot().iter("sequence")][0].findall("media/video/track/clipitem")
    spans = [(int(c.findtext("start")), int(c.findtext("end"))) for c in video]
    assert spans == [(0, 100), (100, 200), (200, 300), (300, 325)]


def test_ranges():
    assert _merge([(5, 6), (0, 2), (1, 3)]) == [(0, 3), (5, 6)]
    assert _merge([(0, 1), (20, 21)], gap=30) == [(0, 21)]
    assert _subtract([(0, 10)], [(2, 4), (6, 7)]) == [(0, 2), (4, 6), (7, 10)]
    assert _subtract([(0, 10)], [(0, 9.8)]) == []


class FakeWhisper:
    model_name, language = "m", "fr"

    def __init__(self):
        self.calls = []

    def __call__(self, audio, progress=None):
        self.calls.append(len(audio) / 16000)
        return [Word("mot", 1.0, 1.4, 0.9), Word("fin", len(audio) / 16000 - 0.5, len(audio) / 16000 - 0.1, 0.9)]


def test_transcripts_are_reused_and_extended(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(transcribe, "CACHE_DIR", tmp_path / "cache")
    wav = tmp_path / "REC.WAV"
    wav.write_bytes(b"x" * 100)
    import numpy as np

    def decode(path, start, length):
        return np.zeros(int(length * 16000), dtype=np.float32)
    whisper = FakeWhisper()
    transcribe_ranges({wav: [(100, 200)]}, decode, whisper)
    transcribe_ranges({wav: [(100, 200)]}, decode, whisper)        # cached: nothing new
    assert len(whisper.calls) == 1
    st = transcribe_ranges({wav: [(150, 300)]}, decode, whisper)[wav]   # only 201..300 (+ overlap)
    assert len(whisper.calls) == 2 and 95 < whisper.calls[1] < 105
    assert st.covered == [(99.0, 301.0)]
    assert SourceTranscript(wav, "m", "fr").covered == [(99.0, 301.0)]   # saved


def test_sequence_words_follow_the_cuts(tmp_path: Path):
    seq = PremiereSequence.from_file(_xml(tmp_path))
    src = seq.source(seq.analysis_track.items[0])

    class T:
        def between(self, a, b):
            return [w for w in [Word("x", 21.0, 21.2, 1), Word("y", 37.0, 37.2, 1), Word("z", 1.0, 1.2, 1)]
                    if a <= (w.start + w.end) / 2 < b]
    words = seq.sequence_words({src: T()})
    # clip 1 plays source 20-24 s at 0 s, clip 2 source 36-40 s at 4 s; the last take replays source 0-180 s
    # from 134 s, so every word is heard there again
    assert [(w.text, w.start) for w in words] == [("x", 1.0), ("y", 5.0), ("z", 135.0), ("x", 155.0),
                                                  ("y", 171.0)]
