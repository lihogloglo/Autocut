"""Sourcing helpers that need no network: rights, timestamps, captions, queries, Premiere export."""

import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

from autocut.media import MediaInfo
from autocut.sourcing.collect import _bigger, _start_param, _vtt_cues
from autocut.sourcing.export import broll_sequence, sentence_times
from autocut.sourcing.model import CHECK, FREE, PROTECTED, rights_for
from autocut.sourcing.script import parse_script
from autocut.sourcing.search import heuristic_queries
from autocut.xmeml import write_document


def test_rights():
    assert rights_for("CC BY-SA 4.0") == FREE
    assert rights_for("Public domain") == FREE
    assert rights_for("CC BY-NC 2.0") == CHECK
    assert rights_for(None) == CHECK
    assert rights_for("CC BY 4.0", "Photo : AFP / Jean Dupont") == PROTECTED


def test_video_start_and_captions():
    assert _start_param("https://youtu.be/V2EOgyICFEw?si=x&t=232") == 232
    assert _start_param("https://www.youtube.com/watch?v=x&t=1m30s") == 90
    assert _start_param("https://www.youtube.com/watch?v=x") is None
    vtt = ("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nbonjour à tous\n\n"
           "00:00:03.000 --> 00:00:05.000\nbonjour à tous\nla révolte gronde\n")
    assert _vtt_cues(vtt) == [(1.0, "bonjour à tous"), (3.0, "la révolte gronde")]


def test_bigger_variants():
    assert _bigger("https://x.fr/wp-content/uploads/a-1024x683.jpg")[0] == "https://x.fr/wp-content/uploads/a.jpg"
    assert _bigger("https://cdn.x.com/a.jpg?w=600&q=80")[0] == "https://cdn.x.com/a.jpg"


def test_queries_pick_names_and_years(tmp_path):
    path = tmp_path / "s.md"
    path.write_text("## Un\n\nEn 1789, Robespierre et Danton étaient avocats à Paris.\n\n"
                    "Bref, les gens ont tendance à faire des choses aléatoires. (*extrait Bigard*)\n", encoding="utf-8")
    qs = heuristic_queries(parse_script(path))
    assert "Robespierre" in qs[0].fr[0] and "1789" in qs[0].fr[0]
    assert qs[1].video and qs[1].video.startswith("Bigard")
    assert not any("Bref" in q for q in qs[1].fr)


def test_broll_xml_roundtrip(tmp_path):
    img = MediaInfo(tmp_path / "a.jpg", 3600.0, Fraction(25), 4000, 3000, 0, 48000)
    vid = MediaInfo(tmp_path / "b.mp4", 20.0, Fraction(25), 1920, 1080, 2, 48000)
    seq = broll_sequence("Test B-roll", [(img, 0.0, 0.0, 5.0, True, "S001"), (vid, 2.0, 0.0, 10.0, False, "S002")],
                         Fraction(25), (1920, 1080), [(0.0, "S001 · phrase"), (2.0, "S002 · autre")])
    out = tmp_path / "b.xml"
    write_document(out, [seq], "Test")
    root = ET.parse(out).getroot()
    tracks = root.findall(".//sequence/media/video/track")
    assert len(tracks) == 2                     # overlapping clips go on separate tracks
    assert len(root.findall(".//sequence/media/audio/track")) == 2   # stereo, exploded
    assert [m.findtext("name") for m in root.findall(".//sequence/marker")] == ["S001 · phrase", "S002 · autre"]

    # markers written by part 1 give the sentence times back
    times, fps, size, _ = sentence_times(out)
    assert times == {0: 0.0, 1: 2.0} and fps == 25 and size == (1920, 1080)


def test_sentence_times_spans(tmp_path):
    xml = """<xmeml version="5"><sequence><name>x 3 derush</name><rate><timebase>25</timebase><ntsc>FALSE</ntsc>
    </rate><marker><name>S003–S004 T1/1 · abc</name><in>100</in><out>200</out></marker>
    <marker><name>S003 T2/2 · abc</name><in>300</in><out>350</out></marker></sequence></xmeml>"""
    p = Path(tmp_path / "d.xml")
    p.write_text(xml, encoding="utf-8")
    times, *_ = sentence_times(p)
    assert times == {2: 4.0, 3: 6.0}
