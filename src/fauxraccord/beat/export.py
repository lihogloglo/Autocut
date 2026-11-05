"""The cut as a Premiere XML (FCP7 xmeml), two sequences in one bin:

  « <music> · au rythme »   the shots on V1 (the rushes' own audio under them, if asked), the music
                            below, a marker on every cut
  « <music> · repères »     the music alone with the same markers: to cut by hand, snapping on them

Clips keep their file's name and point at the original rushes (nothing is rendered or renamed).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

from ..xmeml import PPRO_TICKS, add_marker, el, file_element, rate, write_document
from .plan import Source
from .sources import media_info


def _sequence(sid: str, name: str, fps: Fraction, size: tuple[int, int], frames: int) -> tuple[ET.Element, ET.Element, ET.Element]:
    seq = ET.Element("sequence", id=sid, explodedTracks="true")
    el(seq, "name", name)
    el(seq, "duration", frames)
    rate(seq, fps)
    media = el(seq, "media")
    video = el(media, "video")
    vsc = el(el(video, "format"), "samplecharacteristics")
    el(vsc, "width", size[0])
    el(vsc, "height", size[1])
    el(vsc, "pixelaspectratio", "square")
    rate(vsc, fps)
    audio = el(media, "audio")
    el(audio, "numOutputChannels", 2)
    asc = el(el(audio, "format"), "samplecharacteristics")
    el(asc, "depth", 16)
    el(asc, "samplerate", 48000)
    return seq, video, audio


def _stereo_pair(audio: ET.Element) -> list[ET.Element]:
    out = []
    for ch in range(2):
        t = el(audio, "track", currentExplodedTrackIndex=ch, totalExplodedTrackCount=2, premiereTrackType="Stereo")
        el(t, "outputchannelindex", ch + 1)
        out.append(t)
    return out


def _clip(track: ET.Element, cid: str, info, file_el: ET.Element, fps: Fraction, start: int, end: int, src_s: float,
          channel: int | None) -> ET.Element:
    tpf = PPRO_TICKS / float(fps)
    attrs = {"id": cid}
    if channel is not None:
        attrs["premiereChannelType"] = "stereo" if info.audio_channels >= 2 else "mono"
    ci = el(track, "clipitem", **attrs)
    el(ci, "name", info.path.name)
    el(ci, "enabled", "TRUE")
    el(ci, "start", start)
    el(ci, "end", end)
    i0 = round(src_s * float(fps))
    el(ci, "in", i0)
    el(ci, "out", i0 + end - start)
    ticks = round(src_s * PPRO_TICKS)
    el(ci, "pproTicksIn", ticks)
    el(ci, "pproTicksOut", ticks + round((end - start) * tpf))
    ci.append(file_el)
    if channel is None:
        el(ci, "compositemode", "normal")
    else:
        st = el(ci, "sourcetrack")
        el(st, "mediatype", "audio")
        el(st, "trackindex", min(channel, max(1, info.audio_channels) - 1) + 1)   # mono: the same channel twice
    return ci


def _link(group: list[tuple[ET.Element, str, int, int]]) -> None:
    for ci, *_ in group:
        for other, mtype, tindex, cindex in group:
            ln = el(ci, "link")
            el(ln, "linkclipref", other.get("id"))
            el(ln, "mediatype", mtype)
            el(ln, "trackindex", tindex)
            el(ln, "clipindex", cindex)


def export(music: Path, shots: list[dict], sources: list[Source], cuts: list[float], out_xml: Path,
           music_range: tuple[float, float], rush_audio: bool = False, only_marks: bool = False) -> dict:
    """Writes the XML (only_marks: the music and its markers alone); returns {"shots", "duration", "fps"}."""
    by_id = {s.id: s for s in sources}
    used = [] if only_marks else [sh for sh in shots if sh.get("src") in by_id]
    infos: dict[str, object] = {}
    for sh in used:
        p = by_id[sh["src"]].path
        if p not in infos:
            infos[p] = media_info(Path(p))
    first = next(iter(infos.values()), None)
    if first is None and sources:                  # markers only: still at the rushes' frame rate
        try:
            first = media_info(Path(next((x for x in sources if x.on), sources[0]).path))
        except ValueError:
            first = None
    fps = first.fps if first else Fraction(25)
    size = (first.width, first.height) if first else (1920, 1080)
    f = float(fps)
    fr = lambda s: round(s * f)                      # noqa: E731
    lo, hi = music_range
    total = max(1, fr(hi - lo))
    m_info = media_info(music)
    title = music.stem
    ids = iter(range(1, 10 ** 9))
    files: dict[str, str] = {}

    def file_of(info) -> ET.Element:
        k = str(info.path)
        if k in files:
            return ET.Element("file", id=files[k])
        files[k] = f"beat-file-{len(files) + 1}"
        return file_element(info, files[k], fps)

    def music_on(audio: ET.Element, prefix: str, index0: int) -> None:
        pair = _stereo_pair(audio)
        group = []
        for ch, t in enumerate(pair):
            fe = file_of(m_info) if ch == 0 else ET.Element("file", id=files.get(str(m_info.path)) or "")
            ci = _clip(t, f"{prefix}-clip-{next(ids)}", m_info, fe, fps, 0, total, lo, ch)
            group.append((ci, "audio", index0 + ch, 1))
        for ci, *_ in group:
            for other, mtype, tindex, cindex in group:
                ln = el(ci, "link")
                el(ln, "linkclipref", other.get("id"))
                el(ln, "mediatype", mtype)
                el(ln, "trackindex", tindex)
                el(ln, "clipindex", cindex)
                el(ln, "groupindex", 1)

    def markers(seq: ET.Element) -> None:
        for n, c in enumerate(cuts, 1):
            at = fr(c - lo)
            if 0 < at < total:
                add_marker(seq, str(n), at, -1)   # a point marker, as Premiere writes them

    # 1. the cut
    seq, video, audio = _sequence("beat-cut", f"{title} · au rythme", fps, size, total)
    v1 = el(video, "track")
    rush_pair = _stereo_pair(audio) if rush_audio else []
    index_music = 3 if rush_audio else 1
    count = {"v": 0, "a": 0}
    for sh in used:
        src = by_id[sh["src"]]
        info = infos[src.path]
        s0, s1 = fr(sh["t0"] - lo), fr(sh["t1"] - lo)
        if s1 <= s0:
            continue
        if sh.get("short"):                          # the rush ends before the shot does
            s1 = min(s1, s0 + max(1, fr(src.end - sh["in"])))
        count["v"] += 1
        group = [(_clip(v1, f"beat-clip-{next(ids)}", info, file_of(info), fps, s0, s1, sh["in"], None), "video", 1, count["v"])]
        if rush_audio and info.audio_channels:
            count["a"] += 1
            for ch, t in enumerate(rush_pair):
                ci = _clip(t, f"beat-clip-{next(ids)}", info, ET.Element("file", id=files[str(info.path)]), fps, s0, s1,
                           sh["in"], ch)
                group.append((ci, "audio", ch + 1, count["a"]))
        _link(group)
    music_on(audio, "beat", index_music)
    markers(seq)

    # 2. the music alone, with the markers
    seq2, video2, audio2 = _sequence("beat-marks", f"{title} · repères", fps, size, total)
    el(video2, "track")
    music_on(audio2, "marks", 1)
    markers(seq2)

    write_document(out_xml, [seq2] if only_marks else [seq, seq2], f"{title} · au rythme")
    return {"shots": count["v"], "duration": (hi - lo), "fps": f}
