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


def _clip(cid, fid, start, end, src_in, full=True):
    f = (f"<file id='{fid}'><name>{fid}.wav</name><pathurl>file://localhost/D:/rush/{fid}.wav</pathurl></file>"
         if full else f"<file id='{fid}'/>")
    return (f"<clipitem id='{cid}'><name>{fid}.wav</name><start>{start}</start><end>{end}</end>"
            f"<in>{src_in}</in><out>{src_in + end - start}</out>{f}</clipitem>")


def _seq(name, clips, markers=""):
    return (f"<sequence id='{name}'><name>{name}</name><rate><timebase>25</timebase><ntsc>FALSE</ntsc></rate>"
            f"<media><video><format><samplecharacteristics><width>1920</width><height>1080</height>"
            f"</samplecharacteristics></format></video><audio><track>{''.join(clips)}</track></audio></media>"
            f"{markers}</sequence>")


def test_place_sentences_follow_the_edit(tmp_path):
    from autocut.sourcing.place import place_sentences, read_sequence, standalone_copy
    # derush: S001 = rush 10-14 s, S002 = rush 30-33 s (frames at 25 fps); a sync sequence defines the file first
    derush = tmp_path / "x.autocut.xml"
    derush.write_text("<xmeml version='5'><project><children>"
                      + _seq("x 1 sync", [_clip("a", "rec", 0, 2500, 0)])
                      + _seq("x 3 derush", [_clip("b", "rec", 0, 100, 250, False), _clip("c", "rec", 100, 175, 750, False)],
                             "<marker><name>S001 T1/1 · un</name><in>0</in><out>100</out></marker>"
                             "<marker><name>S002 T1/1 · deux</name><in>100</in><out>175</out></marker>")
                      + "</children></project></xmeml>", encoding="utf-8")
    d = read_sequence(derush, prefer="derush")
    assert d.name == "x 3 derush" and len(d.items) == 2
    assert place_sentences(d) == {0: (0.0, 4.0), 1: (4.0, 7.0)}
    # the edit: S002 moved first at 2 s, S001 after a 1 s gap
    edit = tmp_path / "edit.xml"
    edit.write_text("<xmeml version='5'>" + _seq("Montage", [_clip("e1", "rec", 50, 125, 750),
                                                             _clip("e2", "rec", 150, 250, 250)]) + "</xmeml>",
                    encoding="utf-8")
    where = place_sentences(d, read_sequence(edit))
    assert {k: tuple(round(x, 2) for x in v) for k, v in where.items()} == {0: (6.0, 10.0), 1: (2.0, 5.0)}
    # a copy of the derush alone in a new XML defines the rush file itself
    copy = standalone_copy(d, "c", "copie")
    files = copy.findall(".//file")
    assert files[0].find("pathurl") is not None and len(files[1]) == 0


def test_broll_on_top_of_the_edit(tmp_path):
    from autocut.sourcing.place import read_sequence, standalone_copy
    edit = tmp_path / "edit.xml"
    edit.write_text("<xmeml version='5'>" + _seq("Montage", [_clip("e1", "rec", 0, 250, 0)]) + "</xmeml>",
                    encoding="utf-8")
    ref = read_sequence(edit)
    img = MediaInfo(tmp_path / "a.jpg", 3600.0, Fraction(25), 4000, 3000, 0, 48000)
    vid = MediaInfo(tmp_path / "b.mp4", 20.0, Fraction(25), 1920, 1080, 2, 48000)
    placed = [(img, 1.0, 0.0, 3.0, True, "S001"), (vid, 2.0, 0.0, 4.0, False, "S002")]
    shared = {}
    alone = broll_sequence("B-roll", placed, Fraction(25), (1920, 1080), [(1.0, "S001")], files=shared)
    both = broll_sequence("", placed, Fraction(25), (1920, 1080), [],
                          base=standalone_copy(ref, "eb", "Montage + B-roll"), files=shared, prefix="eb")
    out = tmp_path / "b.xml"
    write_document(out, [alone, both], "B-roll")
    root = ET.parse(out).getroot()
    seqs = root.findall(".//sequence")
    assert [s.findtext("name") for s in seqs] == ["B-roll", "Montage + B-roll"]
    v = seqs[1].findall("media/video/track")
    a = seqs[1].findall("media/audio/track")
    assert len(v) == 2 and len(a) == 3           # 2 B-roll lanes (they overlap); edit's A1 + the video's stereo
    link_tracks = sorted(int(ln.findtext("trackindex")) for ln in v[1].find("clipitem").findall("link")
                         if ln.findtext("mediatype") == "audio")
    assert link_tracks == [2, 3]                 # after the edit's own audio track
    defs = [f.get("id") for f in root.iter("file") if len(f)]
    assert len(defs) == len(set(defs)) == 3      # each file defined once in the whole XML


def test_panel_sequence_and_lanes(tmp_path):
    """The Premiere panel sends the open sequence as JSON: same placement as the exported XML."""
    from autocut.sourcing.bridge import exported_files
    from autocut.sourcing.export import lanes
    from autocut.sourcing.place import _key, place_sentences, read_sequence, seq_from_panel
    derush = tmp_path / "x.autocut.xml"
    derush.write_text("<xmeml version='5'><project><children>"
                      + _seq("x 3 derush", [_clip("b", "rec", 0, 100, 250), _clip("c", "rec", 100, 175, 750, False)],
                             "<marker><name>S001 T1/1 · un</name><in>0</in><out>100</out></marker>"
                             "<marker><name>S002 T1/1 · deux</name><in>100</in><out>175</out></marker>")
                      + "</children></project></xmeml>", encoding="utf-8")
    d = read_sequence(derush, prefer="derush")
    rec = d.items[0].file
    # the edit as the panel reads it: S002 first at 2 s, S001 at 6 s (seconds, source in from media start)
    panel = {"name": "Montage", "fps": 25, "items": [{"start": 2, "end": 5, "in": 30, "path": rec},
                                                     {"start": 6, "end": 10, "in": 10, "path": rec.upper()}]}
    edit = seq_from_panel(panel)
    assert edit.items[1].file == _key(Path(rec))         # paths compared like the XML's
    where = place_sentences(d, edit)
    assert {k: tuple(round(x, 2) for x in v) for k, v in where.items()} == {0: (6.0, 10.0), 1: (2.0, 5.0)}

    img = MediaInfo(tmp_path / "a.jpg", 3600.0, Fraction(25), 4000, 3000, 0, 48000)
    placed = [(img, 0.0, 0.0, 4.0, True, ""), (img, 1.0, 0.0, 2.0, True, ""), (img, 3.5, 0.0, 2.0, True, ""),
              (img, 4.0, 0.0, 2.0, True, "")]
    assert lanes(placed) == [0, 1, 1, 0]                 # alternatives stack, the rest goes back down

    sec = tmp_path / "export" / "02 Section"
    sec.mkdir(parents=True)
    for name in ("S014-01 page - a.jpg", "S014-02 web - b.png", "S014-03 x.mp4.part", "credits.txt"):
        (sec / name).write_bytes(b"")
    assert [(s, p.name) for s, p in exported_files(tmp_path)] == [(13, "S014-01 page - a.jpg"),
                                                                    (13, "S014-02 web - b.png")]


# --- dates ---------------------------------------------------------------------------------------

def test_norm_date():
    from autocut.sourcing.model import norm_date
    assert norm_date("2019:03:16 14:02:11") == "2019-03-16"                 # EXIF
    assert norm_date("20190316") == "2019-03-16"                            # YouTube
    assert norm_date('<time class="dtstart" datetime="2019-03-16">16 March 2019</time>') == "2019-03-16"
    assert norm_date("16 mars 2026") == "2026-03-16"
    assert norm_date("March 2026") == "2026-03"
    assert norm_date("ca. 1850–60") == "~1850"
    assert norm_date(["1871", "1871"]) == "1871"
    assert norm_date("2026-05-01T08:00:00+02:00") == "2026-05-01"
    assert norm_date(1552694400) == "2019-03-16"
    assert norm_date("unknown") == "" and norm_date(None) == ""


def test_period_range():
    from autocut.sourcing.model import period_range
    assert period_range("2026") == (2026, 2026)
    assert period_range("mars 2026") == (2026, 2026)
    assert period_range("1789-1794") == (1789, 1794)
    assert period_range("1914-18") == (1914, 1918)
    assert period_range("années 1960") == (1960, 1969)
    assert period_range("XIXe siècle") == (1801, 1900)
    assert period_range("") is None


def test_date_note():
    from autocut.sourcing.model import Asset, date_note
    photo = Asset(id="x", kind="image", via="commons", origin="recherche", sentence=0, paragraph=0, date="2019-03-16")
    assert date_note(photo, "2026") == "image de 2019, le passage parle de 2026"
    assert date_note(photo, "2018-2019") == ""
    assert date_note(photo, "2026", "carte") == ""                          # maps, portraits: older is fine
    vid = Asset(id="y", kind="video", via="youtube", origin="recherche", sentence=0, paragraph=0, date="2020-01-04")
    assert date_note(vid, "mars 2026").startswith("vidéo de 2020")
    vid.date = "2026-03-20"
    assert date_note(vid, "mars 2026") == ""


def test_heuristic_period(tmp_path):
    from autocut.sourcing.script import parse_script
    from autocut.sourcing.search import heuristic_queries
    md = tmp_path / "s.md"
    md.write_text("# A\n\nEn 2019, la grève de la RATP paralyse Paris.\n\nUne idée sans date.\n", encoding="utf-8")
    qs = heuristic_queries(parse_script(md))
    assert [q.period for q in qs] == ["2019", ""]
