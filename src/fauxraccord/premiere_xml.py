"""A Premiere sequence (FCP7 XML) as the source of the derush.

The sequence is either exported from Premiere or built by the sync step. It is
analysed in *sequence time*: the chosen audio track (by default the one holding
an external .wav) is rendered as it plays in the sequence, so sync and any cuts
already made are respected. Output sequences cut every track of it at the same
points, deep-copying the original clipitems so names, master clips, file
definitions, source channels and effects survive untouched.
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
from .xmeml import PPRO_TICKS, add_marker, write_document

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
    def __init__(self, root: ET.Element, sequence_name: str | None = None, audio_track: int | None = None):
        self.root = root
        sequences = self.root.findall(".//sequence")
        sequences = [s for s in sequences if s.find("media") is not None]
        if not sequences:
            raise ValueError("no sequence in the XML")
        if sequence_name:
            match = [s for s in sequences if s.findtext("name") == sequence_name]
            if not match:
                names = ", ".join(repr(s.findtext("name")) for s in sequences)
                raise ValueError(f"sequence {sequence_name!r} not found; available: {names}")
            self.seq = match[0]
        else:
            self.seq = sequences[0]
        self.name = self.seq.findtext("name", "sequence")
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

    @classmethod
    def from_file(cls, path: Path, sequence_name: str | None = None,
                  audio_track: int | None = None) -> "PremiereSequence":
        return cls(ET.parse(path).getroot(), sequence_name, audio_track)

    def sources(self) -> list[Path]:
        return sorted({pathurl_to_path(f.findtext("pathurl")) for f in self.files.values()})

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

    def source(self, item: Item) -> Path:
        return pathurl_to_path(self.files[item.file_id].findtext("pathurl"))

    def _pick_audio(self, index: int | None) -> Track:
        tracks = self.audio_tracks()
        if not tracks:
            raise ValueError("sequence has no audio track")
        if index is not None:
            return tracks[index - 1]
        for t in tracks:
            if any(self.source(i).suffix.lower() in AUDIO_EXT for i in t.items):
                return t
        return tracks[0]

    def describe(self) -> str:
        lines = [f"sequence {self.name!r}, {float(self.fps):.3f} fps, {self.duration / 60:.1f} min"]
        n = {"video": 0, "audio": 0}
        for t in self.tracks:
            n[t.kind] += 1
            srcs = sorted({self.source(i).name for i in t.items})
            mark = "  <- transcribed" if t is self.analysis_track else ""
            lines.append(f"  {t.kind[0].upper()}{n[t.kind]}: {len(t.items)} clip(s) {', '.join(srcs)}{mark}")
        for name in sorted(set(self.skipped)):
            lines.append(f"  skipped (no media file, e.g. adjustment layer - re-apply it on the derush): {name}")
        return "\n".join(lines)

    def offset(self, item: Item) -> float:
        """Source seconds where the item starts."""
        return item.ticks_in / PPRO_TICKS if item.ticks_in is not None else item.src_in / float(self.fps)

    @staticmethod
    def decode(path: Path, start: float, length: float) -> np.ndarray:
        pcm = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{start:.6f}", "-t", f"{length:.6f}",
             "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", str(SAMPLE_RATE),
             "-f", "f32le", "-"], capture_output=True, check=True).stdout
        return np.frombuffer(pcm, dtype=np.float32)

    def _spans(self, t0: float = 0.0):
        """(item, sequence start s, sequence end s, source start s) of the analysis track from t0 on."""
        fps = float(self.fps)
        for item in self.analysis_track.items:
            a, b = item.start / fps, item.end / fps
            if item.enabled and b > t0:
                yield item, a, b, self.offset(item)

    def analysis_needs(self, t0: float = 0.0) -> dict[Path, list[tuple[float, float]]]:
        """Source ranges heard on the analysis track from sequence time t0 on."""
        needs: dict[Path, list[tuple[float, float]]] = {}
        for item, a, b, off in self._spans(t0):
            needs.setdefault(self.source(item), []).append((off + max(0.0, t0 - a), off + b - a))
        return needs

    def sequence_words(self, transcripts: dict, t0: float = 0.0) -> list:
        """Words as they play in the sequence (from t0 on), from per-source transcripts."""
        from .transcribe import Word
        words = []
        for item, a, b, off in self._spans(t0):
            shift = a - off
            for w in transcripts[self.source(item)].between(off + max(0.0, t0 - a), off + b - a):
                words.append(Word(w.text, round(w.start + shift, 3), round(min(w.end + shift, b), 3), w.prob))
        words.sort(key=lambda w: w.start)
        return words

    def render_audio(self, t0: float = 0.0) -> np.ndarray:
        """The analysis track as it plays in the sequence, 16 kHz mono (silent before t0)."""
        out = np.zeros(int(self.duration * SAMPLE_RATE) + SAMPLE_RATE, dtype=np.float32)
        for item, a, b, off in self._spans(t0):
            samples = self.decode(self.source(item), off, b - a)
            at = int(a * SAMPLE_RATE)
            n = min(len(samples), len(out) - at)
            out[at:at + n] = samples[:n]
        return out

    def islands(self, t1: float) -> list[tuple[float, float]]:
        """Stretches of [0, t1] where the analysis track has sound: a hand derush leaves gaps where
        takes were lifted out, and those are closed when the stretch is kept."""
        fps, f1 = float(self.fps), round(t1 * float(self.fps))
        spans = sorted((i.start, min(i.end, f1)) for i in self.analysis_track.items if i.start < f1)
        out: list[list[int]] = []
        for a, b in spans:
            if out and a <= out[-1][1]:
                out[-1][1] = max(out[-1][1], b)
            else:
                out.append([a, b])
        return [(a / fps, b / fps) for a, b in out]

    def derushed_until(self, long_clip: float = 60.0) -> dict:
        """Where a hand derush stopped. People cut from left to right, so a half-derushed sequence
        is short clips, then the long untouched rushes. "cutoff" (sequence s) is 0 when the whole
        sequence looks raw and None when nothing does."""
        fps = float(self.fps)
        items = sorted((i for i in self.analysis_track.items if i.enabled), key=lambda i: i.start)
        if not items:
            return {"cutoff": None, "duration": 0.0, "clips": 0}
        end = items[-1].end / fps
        is_long = [(i.end - i.start) / fps >= long_clip for i in items]
        cutoff = None
        for k, item in enumerate(items):
            if is_long[k]:
                start = item.start / fps
                raw = sum((i.end - i.start) / fps for i, lg in zip(items[k:], is_long[k:]) if lg)
                if raw >= 0.8 * (end - start):
                    cutoff = start if k else 0.0
                    break
        info = {"cutoff": cutoff, "duration": end, "clips": len(items)}
        if cutoff is not None:
            before = [i for i in items if i.start / fps < cutoff]
            after = [i for i in items if i.start / fps >= cutoff]
            info.update(done_clips=len(before), done=sum((i.end - i.start) / fps for i in before),
                        raw_clips=len(after), raw=sum((i.end - i.start) / fps for i in after),
                        raw_names=sorted({self.source(i).name for i in after}))
        return info

    def export(self, path: Path, project: str, sequences: list[tuple[str, list[Clip] | None]]) -> None:
        """One XML holding several sequences over the same master clips. `None` instead of
        clips writes this sequence unchanged (the sync)."""
        written: set[str] = set()
        out = [self._copy(name, f"sequence-{n}", written) if clips is None
               else self._cut(name, clips, f"sequence-{n}", written)
               for n, (name, clips) in enumerate(sequences, 1)]
        write_document(path, out, project)

    def _fresh(self, uid: str, name: str, keep_markers: bool) -> ET.Element:
        seq = copy.deepcopy(self.seq)
        seq.set("id", uid)
        seq.find("name").text = name
        for tag in ("uuid",) if keep_markers else ("uuid", "marker"):
            for el in seq.findall(tag):
                seq.remove(el)
        return seq

    def _copy(self, name: str, uid: str, written: set[str]) -> ET.Element:
        seq = self._fresh(uid, name, keep_markers=True)
        ids: dict[str, str] = {}
        items = [ci for kind in ("video", "audio") for t in seq.findall(f"media/{kind}/track")
                 for ci in t.findall("clipitem") + t.findall("transitionitem")]
        for n, ci in enumerate(items, 1):
            if ci.get("id"):
                ids[ci.get("id")] = f"{uid}-item-{n}"
                ci.set("id", ids[ci.get("id")])
        for ci in items:
            for ref in ci.findall("link/linkclipref"):
                ref.text = ids.get(ref.text, ref.text)
            f = ci.find("file")
            if f is not None and f.get("id") in self.files:
                self._normalize_file(ci, written)
        return seq

    def _cut(self, name: str, clips: list[Clip], uid: str, written: set[str]) -> ET.Element:
        seq = self._fresh(uid, name, keep_markers=False)

        # Empty every track of the copy, remembering where clips went.
        new_tracks: list[ET.Element] = []
        for kind in ("video", "audio"):
            for t in seq.findall(f"media/{kind}/track"):
                for el in t.findall("clipitem") + t.findall("transitionitem"):
                    t.remove(el)
                new_tracks.append(t)

        tpf = PPRO_TICKS / float(self.fps)
        clip_count = [0] * len(self.tracks)
        pos = 0
        prev: tuple[float, int] | None = None   # (src_out, end frame) of the previous clip
        for k, clip in enumerate(clips):
            if clip.keep:
                pos = self._keep(seq, clip, uid, k, new_tracks, clip_count, pos, written)
                prev = None
                continue
            fa = math.floor(clip.src_in * float(self.fps))
            if prev and abs(prev[0] - clip.src_in) < 1e-9:   # contiguous: no frame shown twice
                fa = prev[1]
            fb = max(fa + 1, math.ceil(clip.src_out * float(self.fps)))
            prev = (clip.src_out, fb)
            group: list[tuple[ET.Element, int, int]] = []   # (clipitem, track index, clip index)
            for ti, (track, dest) in enumerate(zip(self.tracks, new_tracks)):
                for item in track.items:
                    s, e = max(fa, item.start), min(fb, item.end)
                    if e <= s:
                        continue
                    ci = copy.deepcopy(item.el)
                    ci.set("id", f"{uid}-clipitem-{k + 1}-{ti + 1}-{len(group) + 1}")
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
                    for el in ci.findall("link") + ci.findall("labels"):
                        ci.remove(el)
                    ET.SubElement(ET.SubElement(ci, "labels"), "label2").text = clip.color
                    self._normalize_file(ci, written)
                    dest.append(ci)
                    clip_count[ti] += 1
                    group.append((ci, ti, clip_count[ti]))
            self._link(group)
            if group and clip.label:
                add_marker(seq, clip.label, pos, pos + fb - fa)
            pos += fb - fa

        dur = seq.find("duration")
        if dur is not None:
            dur.text = str(pos)
        return seq

    def _keep(self, seq: ET.Element, clip: Clip, uid: str, k: int, new_tracks: list[ET.Element],
              clip_count: list[int], pos: int, written: set[str]) -> int:
        """Copy a stretch of the sequence untouched: clip labels, links and sequence markers kept."""
        fps = float(self.fps)
        fa, fb = round(clip.src_in * fps), round(clip.src_out * fps)
        tpf = PPRO_TICKS / fps
        ids: dict[str, tuple[ET.Element, int, int]] = {}   # old clipitem id -> (copy, track, clip index)
        copies: list[ET.Element] = []
        for ti, (track, dest) in enumerate(zip(self.tracks, new_tracks)):
            for item in track.items:
                s, e = max(fa, item.start), min(fb, item.end)
                if e <= s:
                    continue
                ci = copy.deepcopy(item.el)
                old_id = ci.get("id")
                ci.set("id", f"{uid}-keep-{k + 1}-{ti + 1}-{clip_count[ti] + 1}")
                start, src_in = pos + s - fa, item.src_in + s - item.start
                for tag, value in (("start", start), ("end", start + e - s), ("in", src_in), ("out", src_in + e - s)):
                    ci.find(tag).text = str(value)
                if item.ticks_in is not None:
                    ticks = item.ticks_in + round((s - item.start) * tpf)
                    ci.find("pproTicksIn").text = str(ticks)
                    if ci.find("pproTicksOut") is not None:
                        ci.find("pproTicksOut").text = str(ticks + round((e - s) * tpf))
                self._normalize_file(ci, written)
                dest.append(ci)
                clip_count[ti] += 1
                if old_id:
                    ids[old_id] = (ci, ti, clip_count[ti])
                copies.append(ci)
        kind_index, counters = {}, {"video": 0, "audio": 0}
        for ti, t in enumerate(self.tracks):
            counters[t.kind] += 1
            kind_index[ti] = counters[t.kind]
        for ci in copies:
            for ln in ci.findall("link"):
                target = ids.get(ln.findtext("linkclipref"))
                if target is None:
                    ci.remove(ln)
                    continue
                other, ti, n = target
                for tag, value in (("linkclipref", other.get("id")), ("trackindex", str(kind_index[ti])),
                                   ("clipindex", str(n))):
                    if ln.find(tag) is None:
                        ET.SubElement(ln, tag)
                    ln.find(tag).text = value
        for m in self.seq.findall("marker"):
            m_in = _int(m, "in", -1)
            if fa <= m_in < fb:
                mk = copy.deepcopy(m)
                mk.find("in").text = str(pos + m_in - fa)
                if mk.find("out") is not None and _int(mk, "out", -1) >= 0:
                    mk.find("out").text = str(pos + _int(m, "out") - fa)
                seq.append(mk)
        for label, a, b in clip.markers:
            add_marker(seq, label, pos + round(a * fps) - fa, pos + round(b * fps) - fa)
        return pos + fb - fa

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
