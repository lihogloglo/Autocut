"""Final Cut Pro 7 XML (xmeml) export as Premiere Pro imports it.

Structure follows auto-editor's Premiere exporter (exploded stereo audio
tracks, plain absolute pathurl, label2 colour labels), which is known to
round-trip through Premiere.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

from .media import MediaInfo
from .timeline import Clip

PPRO_TICKS = 254016000000


def _el(parent: ET.Element, tag: str, text: str | int | None = None, **attrs) -> ET.Element:
    e = ET.SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})
    if text is not None:
        e.text = str(text)
    return e


class _Writer:
    def __init__(self, media: MediaInfo):
        self.media = media
        self.file_written = False
        self.stereo = media.audio_channels >= 2

    def rate(self, parent: ET.Element) -> None:
        r = _el(parent, "rate")
        _el(r, "timebase", self.media.timebase)
        _el(r, "ntsc", "TRUE" if self.media.ntsc else "FALSE")

    def file(self, parent: ET.Element) -> None:
        f = _el(parent, "file", id="file-1")
        if self.file_written:
            return
        self.file_written = True
        m = self.media
        _el(f, "name", m.path.name)
        _el(f, "pathurl", m.path.as_posix())
        tc = _el(f, "timecode")
        _el(tc, "string", "00:00:00:00")
        _el(tc, "displayformat", "NDF")
        self.rate(tc)
        self.rate(f)
        _el(f, "duration", "")
        md = _el(f, "media")
        sc = _el(_el(md, "video"), "samplecharacteristics")
        self.rate(sc)
        _el(sc, "width", m.width)
        _el(sc, "height", m.height)
        _el(sc, "pixelaspectratio", "square")
        au = _el(md, "audio")
        asc = _el(au, "samplecharacteristics")
        _el(asc, "depth", 16)
        _el(asc, "samplerate", m.audio_rate)
        _el(au, "channelcount", m.audio_channels)

    def clipitem(self, track: ET.Element, cid: str, clip: Clip, start: int, src_in: int, src_out: int,
                 audio_index: int | None, links: list[tuple[str, str, int]], clip_index: int) -> None:
        attrs = {"id": cid}
        if audio_index is not None:
            attrs["premiereChannelType"] = "stereo" if self.stereo else "mono"
        ci = _el(track, "clipitem", **attrs)
        _el(ci, "name", clip.name)
        _el(ci, "enabled", "TRUE")
        _el(ci, "start", start)
        _el(ci, "end", start + src_out - src_in)
        _el(ci, "in", src_in)
        _el(ci, "out", src_out)
        per_frame = PPRO_TICKS / float(self.media.fps)
        _el(ci, "pproTicksIn", round(src_in * per_frame))
        _el(ci, "pproTicksOut", round(src_out * per_frame))
        self.file(ci)
        if audio_index is None:
            _el(ci, "compositemode", "normal")
        else:
            st = _el(ci, "sourcetrack")
            _el(st, "mediatype", "audio")
            _el(st, "trackindex", audio_index)
        for ref, mtype, tindex in links:
            ln = _el(ci, "link")
            _el(ln, "linkclipref", ref)
            _el(ln, "mediatype", mtype)
            _el(ln, "trackindex", tindex)
            _el(ln, "clipindex", clip_index)
        _el(_el(ci, "labels"), "label2", clip.color)

    def sequence(self, parent: ET.Element, name: str, clips: list[Clip], uid: str) -> None:
        m = self.media
        frames = [(math.floor(c.src_in * float(m.fps)), math.ceil(c.src_out * float(m.fps))) for c in clips]
        total = sum(b - a for a, b in frames)
        seq = _el(parent, "sequence", id=uid, explodedTracks="true")
        _el(seq, "name", name)
        _el(seq, "duration", total)
        self.rate(seq)
        media = _el(seq, "media")

        video = _el(media, "video")
        vsc = _el(_el(video, "format"), "samplecharacteristics")
        _el(vsc, "width", m.width)
        _el(vsc, "height", m.height)
        _el(vsc, "pixelaspectratio", "square")
        self.rate(vsc)
        vtrack = _el(video, "track")

        audio = _el(media, "audio")
        _el(audio, "numOutputChannels", 2)
        asc = _el(_el(audio, "format"), "samplecharacteristics")
        _el(asc, "depth", 16)
        _el(asc, "samplerate", m.audio_rate)
        n_audio = 2 if self.stereo else 1
        atracks = []
        for k in range(n_audio):
            t = _el(audio, "track", currentExplodedTrackIndex=k, totalExplodedTrackCount=n_audio,
                    premiereTrackType="Stereo" if self.stereo else "Mono")
            if self.stereo:
                _el(t, "outputchannelindex", k + 1)
            atracks.append(t)

        vid =lambda j: f"{uid}-v{j + 1}"
        aid = lambda k, j: f"{uid}-a{k + 1}-{j + 1}"
        pos = 0
        for j, (clip, (fin, fout)) in enumerate(zip(clips, frames)):
            links = [(vid(j), "video", 1)] + [(aid(k, j), "audio", k + 1) for k in range(n_audio)]
            self.clipitem(vtrack, vid(j), clip, pos, fin, fout, None, links, j + 1)
            for k in range(n_audio):
                self.clipitem(atracks[k], aid(k, j), clip, pos, fin, fout, k + 1, links, j + 1)
            pos += fout - fin


def write_xml(path: Path, media: MediaInfo, name: str, clips: list[Clip]) -> None:
    root = ET.Element("xmeml", version="5")
    _Writer(media).sequence(root, name, clips, "sequence-1")
    ET.indent(root)
    with path.open("wb") as fh:
        fh.write(b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n')
        ET.ElementTree(root).write(fh, encoding="utf-8", xml_declaration=False)
