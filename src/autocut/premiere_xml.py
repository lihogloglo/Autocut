"""Use an existing Premiere sequence (FCP7 XML export) as the source.

The sequence is analysed in *sequence time*: the chosen audio track (by
default the one holding an external .wav) is rendered as it plays in the
sequence, so sync and any cuts already made are respected. The derush is
then written back by cutting every track of the original sequence at the
same points, deep-copying the original clipitems so file definitions,
source channels and effects survive untouched.
"""

from __future__ import annotations

import copy
import math
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote

import numpy as np

from .media import SAMPLE_RATE
from .timeline import Clip
from .xmeml import PPRO_TICKS

AUDIO_EXT = {".wav", ".aif", ".aiff", ".flac", ".mp3", ".m4a", ".bwf"}


@dataclass
class Item:
    el: ET.Element
    start: int   # sequence frames
    end: int
    src_in: int  # source frames (sequence timebase)
    ticks_in: int | None
    file_id: str | None
    enabled: bool


@dataclass
class Track:
    el: ET.Element
    kind: str    # "video" | "audio"
    items: list[Item]


def _int(el: ET.Element, tag: str, default: int = 0) -> int:
    v = el.findtext(tag)
    return int(v) if v not in (None, "") else default


def _rate(el: ET.Element) -> Fraction:
    tb = _int(el, "rate/timebase", 25)
    return Fraction(tb * 1000, 1001) if el.findtext("rate/ntsc", "FALSE").upper() == "TRUE" else Fraction(tb)


def pathurl_to_path(url: str) -> Path:
    url = unquote(url)
    for prefix in ("file://localhost/", "file:///", "file://"):
        if url.startswith(prefix):
            url = url[len(prefix):]
            break
    if len(url) > 2 and url[1] != ":" and url[2] == ":":   # "/D:/..." form
        url = url[1:]
    return Path(url)


class PremiereSequence:
    def __init__(self, path: Path, sequence_name: str | None = None, audio_track: int | None = None):
        self.path = path
        self.root = ET.parse(path).getroot()
        sequences = self.root.findall(".//sequence")
        sequences = [s for s in sequences if s.find("media") is not None]
        if not sequences:
            raise ValueError(f"no sequence in {path}")
        if sequence_name:
            match = [s for s in sequences if s.findtext("name") == sequence_name]
            if not match:
                names = ", ".join(repr(s.findtext("name")) for s in sequences)
                raise ValueError(f"sequence {sequence_name!r} not found; available: {names}")
            self.seq = match[0]
        else:
            self.seq = sequences[0]
        self.name = self.seq.findtext("name", path.stem)
        self.fps = _rate(self.seq)

        self.files: dict[str, ET.Element] = {}
        generated: set[str] = set()
        for f in self.root.iter("file"):
            if not f.get("id") or len(f) == 0:
                continue
            if f.find("pathurl") is not None:
                self.files.setdefault(f.get("id"), f)
            else:   # slug / adjustment layer / title: no media file behind it
                generated.add(f.get("id"))

        self.tracks: list[Track] = []
        self.skipped: list[str] = []
        for kind in ("video", "audio"):
            for t in self.seq.findall(f"media/{kind}/track"):
                items = self._items(t)
                for i in items:
                    if i.file_id not in self.files:
                        self.skipped.append(f"{kind[0].upper()}: {i.el.findtext('name')}")
                self.tracks.append(Track(t, kind, [i for i in items if i.file_id in self.files]))
        self.duration_frames = max((i.end for t in self.tracks for i in t.items), default=0)
        self.duration = self.duration_frames / float(self.fps)
        self.analysis_track = self._pick_audio(audio_track)

    def _items(self, track: ET.Element) -> list[Item]:
        items: list[Item] = []
        for ci in track.findall("clipitem"):
            f = ci.find("file")
            if f is None:
                raise ValueError(f"clip {ci.findtext('name')!r} has no source file (nested sequence?) "
                                 "- unnest or render it first")
            src_in, src_out = _int(ci, "in"), _int(ci, "out")
            start, end = _int(ci, "start", -1), _int(ci, "end", -1)
            if start < 0:  # transition at head: starts where the previous clip ended
                start = items[-1].end if items else 0
            if end < 0:
                end = start + (src_out - src_in)
            ticks = ci.findtext("pproTicksIn")
            items.append(Item(ci, start, end, src_in, int(ticks) if ticks else None, f.get("id"),
                              ci.findtext("enabled", "TRUE").upper() == "TRUE"))
        return items

    def audio_tracks(self) -> list[Track]:
        return [t for t in self.tracks if t.kind == "audio"]

    def _source(self, item: Item) -> Path:
        return pathurl_to_path(self.files[item.file_id].findtext("pathurl"))

    def _pick_audio(self, index: int | None) -> Track:
        tracks = self.audio_tracks()
        if not tracks:
            raise ValueError("sequence has no audio track")
        if index is not None:
            return tracks[index - 1]
        for t in tracks:
            if any(self._source(i).suffix.lower() in AUDIO_EXT for i in t.items):
                return t
        return tracks[0]

    def describe(self) -> str:
        lines = [f"sequence {self.name!r}, {float(self.fps):.3f} fps, {self.duration / 60:.1f} min"]
        n = {"video": 0, "audio": 0}
        for t in self.tracks:
            n[t.kind] += 1
            srcs = sorted({self._source(i).name for i in t.items})
            mark = "  <- transcribed" if t is self.analysis_track else ""
            lines.append(f"  {t.kind[0].upper()}{n[t.kind]}: {len(t.items)} clip(s) {', '.join(srcs)}{mark}")
        for name in sorted(set(self.skipped)):
            lines.append(f"  skipped (no media file, e.g. adjustment layer - re-apply it on the derush): {name}")
        return "\n".join(lines)

    def render_audio(self) -> np.ndarray:
        """The analysis track as it plays in the sequence, 16 kHz mono."""
        out = np.zeros(int(self.duration * SAMPLE_RATE) + SAMPLE_RATE, dtype=np.float32)
        fps = float(self.fps)
        for item in self.analysis_track.items:
            if not item.enabled:
                continue
            offset = item.ticks_in / PPRO_TICKS if item.ticks_in is not None else item.src_in / fps
            length = (item.end - item.start) / fps
            pcm = subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", f"{offset:.6f}", "-t", f"{length:.6f}",
                 "-i", str(self._source(item)), "-map", "0:a:0", "-ac", "1", "-ar", str(SAMPLE_RATE),
                 "-f", "f32le", "-"], capture_output=True, check=True).stdout
            samples = np.frombuffer(pcm, dtype=np.float32)
            at = int(item.start / fps * SAMPLE_RATE)
            n = min(len(samples), len(out) - at)
            out[at:at + n] = samples[:n]
        return out

    def write(self, path: Path, name: str, clips: list[Clip]) -> None:
        seq = copy.deepcopy(self.seq)
        seq.set("id", "sequence-1")
        seq.find("name").text = name
        for tag in ("uuid", "marker"):
            for el in seq.findall(tag):
                seq.remove(el)

        # Empty every track of the copy, remembering where clips went.
        new_tracks: list[ET.Element] = []
        for kind in ("video", "audio"):
            for t in seq.findall(f"media/{kind}/track"):
                for el in t.findall("clipitem") + t.findall("transitionitem"):
                    t.remove(el)
                new_tracks.append(t)

        tpf = PPRO_TICKS / float(self.fps)
        written: set[str] = set()
        clip_count = [0] * len(self.tracks)
        pos = 0
        for k, clip in enumerate(clips):
            fa = math.floor(clip.src_in * float(self.fps))
            fb = math.ceil(clip.src_out * float(self.fps))
            group: list[tuple[ET.Element, int, int]] = []   # (clipitem, track index, clip index)
            for ti, (track, dest) in enumerate(zip(self.tracks, new_tracks)):
                for item in track.items:
                    s, e = max(fa, item.start), min(fb, item.end)
                    if e <= s:
                        continue
                    ci = copy.deepcopy(item.el)
                    ci.set("id", f"clipitem-{k + 1}-{ti + 1}-{len(group) + 1}")
                    start = pos + s - fa
                    src_in = item.src_in + s - item.start
                    for tag, value in (("start", start), ("end", start + e - s),
                                       ("in", src_in), ("out", src_in + e - s)):
                        ci.find(tag).text = str(value)
                    if item.ticks_in is not None:
                        ticks = item.ticks_in + round((s - item.start) * tpf)
                        ci.find("pproTicksIn").text = str(ticks)
                        if ci.find("pproTicksOut") is not None:
                            ci.find("pproTicksOut").text = str(ticks + round((e - s) * tpf))
                    if ci.find("name") is not None:
                        ci.find("name").text = clip.name
                    for el in ci.findall("link") + ci.findall("labels"):
                        ci.remove(el)
                    ET.SubElement(ET.SubElement(ci, "labels"), "label2").text = clip.color
                    self._normalize_file(ci, written)
                    dest.append(ci)
                    clip_count[ti] += 1
                    group.append((ci, ti, clip_count[ti]))
            self._link(group)
            pos += fb - fa

        dur = seq.find("duration")
        if dur is not None:
            dur.text = str(pos)
        root = ET.Element("xmeml", version=self.root.get("version", "5"))
        root.append(seq)
        ET.indent(root)
        with path.open("wb") as fh:
            fh.write(b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n')
            ET.ElementTree(root).write(fh, encoding="utf-8", xml_declaration=False)

    def _normalize_file(self, ci: ET.Element, written: set[str]) -> None:
        """Full <file> definition on first use in the output, a bare reference after."""
        f = ci.find("file")
        fid = f.get("id")
        idx = list(ci).index(f)
        ci.remove(f)
        if fid in written:
            ci.insert(idx, ET.Element("file", id=fid))
        else:
            ci.insert(idx, copy.deepcopy(self.files[fid]))
            written.add(fid)

    def _link(self, group: list[tuple[ET.Element, int, int]]) -> None:
        if len(group) < 2:
            return
        kind_index: dict[int, int] = {}
        counters = {"video": 0, "audio": 0}
        for ti, t in enumerate(self.tracks):
            counters[t.kind] += 1
            kind_index[ti] = counters[t.kind]
        for ci, _, _ in group:
            for other, ti, clip_index in group:
                ln = ET.SubElement(ci, "link")
                ET.SubElement(ln, "linkclipref").text = other.get("id")
                ET.SubElement(ln, "mediatype").text = self.tracks[ti].kind
                ET.SubElement(ln, "trackindex").text = str(kind_index[ti])
                ET.SubElement(ln, "clipindex").text = str(clip_index)
