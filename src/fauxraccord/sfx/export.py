"""The sound cues as a Premiere XML: one stereo track pair per kind (whooshes, clicks, pops, typing,
hits), so a kind can be muted or rebalanced in one move. Two sequences: the sounds alone (to paste
onto the edit) and a copy of the edit with the sounds on tracks under its own. Each clip carries its
level as Premiere's own Audio Levels; nothing is re-encoded and the user's files keep their names.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote

from ..media import probe
from ..sourcing.place import read_sequence, standalone_copy
from ..xmeml import PPRO_TICKS, el, rate, write_document
from .plan import Cue

ORDER = ("whoosh", "click", "pop", "typing", "hit")
NAMES = {"whoosh": "Whoosh", "click": "Clics", "pop": "Pops", "typing": "Clavier", "hit": "Impacts"}


def _file(path: Path, fid: str, fps: Fraction, info) -> ET.Element:
    f = ET.Element("file", id=fid)
    el(f, "name", path.name)
    el(f, "pathurl", "file://localhost/" + quote(path.as_posix(), safe="/"))
    rate(f, fps)
    el(f, "duration", max(1, round(info.duration * float(fps))))
    a = el(el(f, "media"), "audio")
    sc = el(a, "samplecharacteristics")
    el(sc, "depth", 16)
    el(sc, "samplerate", info.audio_rate)
    el(a, "channelcount", max(1, info.audio_channels))
    return f


def _tracks(seq: ET.Element | None, cues: list[Cue], fps: Fraction, files: dict, infos: dict,
            prefix: str, name: str, size: tuple[int, int], duration: float) -> ET.Element:
    """The cues on new audio tracks of `seq` (a copy of the edit), or of a new sequence."""
    f = float(fps)
    tpf = PPRO_TICKS / f
    fr = lambda s: round(s * f)   # noqa: E731
    if seq is None:
        seq = ET.Element("sequence", id=f"{prefix}-sequence")
        el(seq, "name", name)
        el(seq, "duration", fr(duration))
        rate(seq, fps)
        media = el(seq, "media")
        video = el(media, "video")
        vsc = el(el(video, "format"), "samplecharacteristics")
        el(vsc, "width", size[0])
        el(vsc, "height", size[1])
        el(vsc, "pixelaspectratio", "square")
        rate(vsc, fps)
        el(video, "track")
        audio = el(media, "audio")
        el(audio, "numOutputChannels", 2)
        asc = el(el(audio, "format"), "samplecharacteristics")
        el(asc, "depth", 16)
        el(asc, "samplerate", 48000)
    audio = seq.find("media/audio")
    before = len(audio.findall("track"))
    ids = iter(range(1, 10 ** 9))
    added = 0
    for kind in ORDER:
        mine = [c for c in cues if c.on and c.kind == kind and c.sound.get("path")]
        if not mine:
            continue
        pair = []
        for ch in range(2):
            t = ET.Element("track", currentExplodedTrackIndex=str(ch), totalExplodedTrackCount="2",
                           premiereTrackType="Stereo")
            kids = list(audio)
            last = max((i for i, c in enumerate(kids) if c.tag == "track"), default=len(kids) - 1)
            audio.insert(last + 1, t)
            pair.append(t)
        index = (before + added + 1, before + added + 2)
        added += 2
        for n, c in enumerate(sorted(mine, key=lambda c: c.start), 1):
            path = Path(c.sound["path"])
            info = infos[path]
            if path not in files:
                files[path] = f"sfx-file-{len(files) + 1}"
                file_el = _file(path, files[path], fps, info)
            else:
                file_el = ET.Element("file", id=files[path])
            s0, s1 = fr(c.start), max(fr(c.start) + 1, fr(c.start + c.length))
            i0 = fr(c.src_in)
            group = []
            for ch, track in enumerate(pair):
                ci = el(track, "clipitem", id=f"{prefix}-clip-{next(ids)}",
                        premiereChannelType="stereo" if info.audio_channels >= 2 else "mono")
                el(ci, "name", path.name)
                el(ci, "enabled", "TRUE")
                el(ci, "duration", max(1, fr(info.duration)))
                rate(ci, fps)
                el(ci, "start", s0)
                el(ci, "end", s1)
                el(ci, "in", i0)
                el(ci, "out", i0 + s1 - s0)
                el(ci, "pproTicksIn", round(i0 * tpf))
                el(ci, "pproTicksOut", round((i0 + s1 - s0) * tpf))
                ci.append(file_el if ch == 0 else ET.Element("file", id=files[path]))
                st = el(ci, "sourcetrack")
                el(st, "mediatype", "audio")
                el(st, "trackindex", min(ch, max(1, info.audio_channels) - 1) + 1)   # mono: the same channel twice
                fx = el(el(ci, "filter"), "effect")
                el(fx, "name", "Audio Levels")
                el(fx, "effectid", "audiolevels")
                el(fx, "effectcategory", "audiolevels")
                el(fx, "effecttype", "audiolevels")
                el(fx, "mediatype", "audio")
                p = el(fx, "parameter", authoringApp="PremierePro")
                el(p, "parameterid", "level")
                el(p, "name", "Level")
                el(p, "valuemin", 0)
                el(p, "valuemax", 3.98109)
                el(p, "value", round(10 ** (c.gain_db / 20), 6))
                group.append((ci, index[ch]))
            for ci, _ in group:
                for other, tindex in group:
                    ln = el(ci, "link")
                    el(ln, "linkclipref", other.get("id"))
                    el(ln, "mediatype", "audio")
                    el(ln, "trackindex", tindex)
                    el(ln, "clipindex", n)
                    el(ln, "groupindex", 1)
    return seq


def export(cues: list[Cue], edit_xml: Path, sequence: str, out_xml: Path, title: str, fps: Fraction,
           size: tuple[int, int], duration: float, log=print) -> Path:
    used = sorted({Path(c.sound["path"]) for c in cues if c.on and c.sound.get("path")})
    infos = {}
    for p in used:
        if p.exists():
            infos[p] = probe(p)
        else:
            log(f"  introuvable : {p}")
    cues = [c for c in cues if c.on and c.sound.get("path") and Path(c.sound["path"]) in infos]
    files: dict[Path, str] = {}
    alone = _tracks(None, cues, fps, files, infos, "sfx", f"{title} Sons", size, duration)
    seqs = [alone]
    try:
        ref = read_sequence(edit_xml, sequence)
        base = standalone_copy(ref, "sfx-edit-sequence", f"{ref.name} + Sons")
        seqs.append(_tracks(base, cues, fps, files, infos, "sfx-edit", "", size, duration))
    except Exception as exc:          # the sounds alone still go out
        log(f"  copie du montage impossible ({exc}) : seulement la séquence des sons")
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    write_document(out_xml, seqs, f"{title} Sons")
    return out_xml
