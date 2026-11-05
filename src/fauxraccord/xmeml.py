"""Final Cut Pro 7 XML (xmeml) as Premiere Pro imports it.

Structure follows auto-editor's Premiere exporter (exploded stereo audio
tracks, plain absolute pathurl, label2 colour labels), which is known to
round-trip through Premiere. Clipitems are always named after their source
file, so Premiere keeps the link to the rush (and its proxy).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote

from .media import MediaInfo
from .sync import SyncResult

PPRO_TICKS = 254016000000


def el(parent: ET.Element, tag: str, text: str | int | None = None, **attrs) -> ET.Element:
    e = ET.SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})
    if text is not None:
        e.text = str(text)
    return e


def add_marker(seq: ET.Element, name: str, start: int, end: int) -> None:
    """Sequence marker spanning [start, end) frames. Take info lives here rather than in
    clip names, so every clip keeps its original name and its link to the rush/proxy."""
    m = el(seq, "marker")
    el(m, "comment", "")
    el(m, "name", name)
    el(m, "in", start)
    el(m, "out", end)


def rate(parent: ET.Element, fps: Fraction) -> None:
    r = el(parent, "rate")
    el(r, "timebase", round(float(fps)))
    el(r, "ntsc", "TRUE" if fps.denominator == 1001 else "FALSE")


def file_element(m: MediaInfo, fid: str, fps: Fraction) -> ET.Element:
    f = ET.Element("file", id=fid)
    el(f, "name", m.path.name)
    el(f, "pathurl", "file://localhost/" + quote(m.path.as_posix(), safe="/"))   # as Premiere writes it
    rate(f, m.fps if m.has_video else fps)
    el(f, "duration", int(m.duration * float(m.fps if m.has_video else fps)))
    tc = el(f, "timecode")
    el(tc, "string", "00:00:00:00")
    el(tc, "displayformat", "NDF")
    rate(tc, m.fps if m.has_video else fps)
    md = el(f, "media")
    if m.has_video:
        sc = el(el(md, "video"), "samplecharacteristics")
        rate(sc, m.fps)
        el(sc, "width", m.width)
        el(sc, "height", m.height)
        el(sc, "pixelaspectratio", "square")
    if m.audio_channels:
        au = el(md, "audio")
        asc = el(au, "samplecharacteristics")
        el(asc, "depth", 16)
        el(asc, "samplerate", m.audio_rate)
        el(au, "channelcount", m.audio_channels)
    return f


def sync_document(infos: list[MediaInfo], result: SyncResult, name: str, uid: str = "sync") -> ET.Element:
    """An xmeml root holding the sync sequence: videos on V1.., their own audio, then the
    recorder files, every channel on its own (exploded) track. `uid` prefixes the ids, so several
    sequences built this way can live in one file."""
    fps = Fraction(result.fps_num, result.fps_den)
    tpf = PPRO_TICKS / float(fps)
    first_video = next((m for m in infos if m.has_video), None)
    width, height = (first_video.width, first_video.height) if first_video else (1920, 1080)

    root = ET.Element("xmeml", version="5")
    seq = el(root, "sequence", id=f"{uid}-sequence", explodedTracks="true")
    el(seq, "name", name)
    el(seq, "duration", max((p.start + p.length for p in result.placed), default=0))
    rate(seq, fps)
    media = el(seq, "media")
    video = el(media, "video")
    vsc = el(el(video, "format"), "samplecharacteristics")
    el(vsc, "width", width)
    el(vsc, "height", height)
    el(vsc, "pixelaspectratio", "square")
    rate(vsc, fps)
    audio = el(media, "audio")
    el(audio, "numOutputChannels", 2)
    asc = el(el(audio, "format"), "samplecharacteristics")
    el(asc, "depth", 16)
    el(asc, "samplerate", 48000)

    vplaced = [p for p in result.placed if infos[p.file].has_video]
    aplaced = [p for p in result.placed if not infos[p.file].has_video]
    v_lanes = sorted({p.lane for p in vplaced})
    a_lanes = sorted({p.lane for p in aplaced})
    vtracks = {lane: el(video, "track") for lane in v_lanes}

    def channels(placed, lane):
        return max(infos[p.file].audio_channels for p in placed if p.lane == lane)

    atracks: dict[tuple[str, int, int], ET.Element] = {}
    for kind, placed, lanes in (("cam", vplaced, v_lanes), ("rec", aplaced, a_lanes)):
        for lane in lanes:
            n = channels(placed, lane)
            for ch in range(n):
                t = el(audio, "track", currentExplodedTrackIndex=ch, totalExplodedTrackCount=n,
                       premiereTrackType="Stereo" if n == 2 else "Mono")
                if n == 2:
                    el(t, "outputchannelindex", ch + 1)
                atracks[(kind, lane, ch)] = t
    track_no = {id(t): k + 1 for k, t in enumerate(atracks.values())}
    vtrack_no = {id(t): k + 1 for k, t in enumerate(vtracks.values())}

    count: dict[int, int] = {}
    ids = iter(range(1, 10 ** 9))

    def clipitem(track: ET.Element, p, channel: int | None) -> tuple[ET.Element, int]:
        m = infos[p.file]
        attrs = {"id": f"{uid}-clipitem-{next(ids)}"}
        if channel is not None:
            attrs["premiereChannelType"] = "stereo" if m.audio_channels == 2 else "mono"
        ci = el(track, "clipitem", **attrs)
        el(ci, "name", m.path.name)
        el(ci, "enabled", "TRUE")
        el(ci, "start", p.start)
        el(ci, "end", p.start + p.length)
        src_in = round(p.src * float(fps))
        el(ci, "in", src_in)
        el(ci, "out", src_in + p.length)
        ticks = round(p.src * PPRO_TICKS)
        el(ci, "pproTicksIn", ticks)
        el(ci, "pproTicksOut", ticks + round(p.length * tpf))
        ci.append(file_element(m, f"file-{p.file + 1}", fps))
        if channel is None:
            el(ci, "compositemode", "normal")
        else:
            st = el(ci, "sourcetrack")
            el(st, "mediatype", "audio")
            el(st, "trackindex", channel + 1)
        count[id(track)] = count.get(id(track), 0) + 1
        return ci, count[id(track)]

    for p in result.placed:
        m = infos[p.file]
        group: list[tuple[ET.Element, str, int, int]] = []
        if m.has_video:
            ci, n = clipitem(vtracks[p.lane], p, None)
            group.append((ci, "video", vtrack_no[id(vtracks[p.lane])], n))
        kind = "cam" if m.has_video else "rec"
        for ch in range(m.audio_channels):
            t = atracks[(kind, p.lane, ch)]
            ci, n = clipitem(t, p, ch)
            group.append((ci, "audio", track_no[id(t)], n))
        if m.has_video and len(group) > 1:
            for ci, *_ in group:
                for other, mtype, tindex, cindex in group:
                    ln = el(ci, "link")
                    el(ln, "linkclipref", other.get("id"))
                    el(ln, "mediatype", mtype)
                    el(ln, "trackindex", tindex)
                    el(ln, "clipindex", cindex)
    if not vtracks:   # Premiere wants a video track even in an audio-only sequence
        el(video, "track")
    return root


def write_document(path: Path, sequences: list[ET.Element], project: str) -> None:
    """One xmeml file holding several sequences (inside a project = a bin in Premiere)."""
    root = ET.Element("xmeml", version="5")
    proj = el(root, "project")
    el(proj, "name", project)
    children = el(proj, "children")
    for s in sequences:
        children.append(s)
    ET.indent(root)
    with path.open("wb") as fh:
        fh.write(b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n')
        ET.ElementTree(root).write(fh, encoding="utf-8", xml_declaration=False)
