"""Where each script sentence is in a Premiere sequence, even after the derush was re-edited.

Part 1 writes a sequence marker `Sxxx …` over every take in `3 derush`. Under the marker, the
clipitems say which rush (file + source time) holds that sentence. Any later sequence that still
uses those rushes (the edit, exported from Premiere as FCP7 XML) is searched for the same rush
times, so the sentence is found wherever it ended up, whichever take was kept.
"""

from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from ..premiere_xml import AUDIO_EXT, _rate, pathurl_to_path
from ..xmeml import PPRO_TICKS

_SPAN = re.compile(r"S(\d{3})(?:[–-]S(\d{3}))?\b")


@dataclass
class Item:
    start: float    # seconds in the sequence
    end: float
    src: float      # seconds in the source file at `start`
    file: str       # normalised path of the source file
    audio_file: bool


@dataclass
class Seq:
    name: str
    el: ET.Element
    root: ET.Element
    fps: Fraction
    size: tuple[int, int]
    items: list[Item]
    markers: list[tuple[str, float, float]]   # (name, in, out) in seconds

    @property
    def duration(self) -> float:
        return max((i.end for i in self.items), default=0.0)


def _key(path: Path) -> str:
    return str(path).replace("\\", "/").lower()


def sequences(root: ET.Element) -> list[ET.Element]:
    """Top-level sequences (not the nested ones inside clipitems)."""
    nested = {id(s) for ci in root.iter("clipitem") for s in ci.iter("sequence")}
    return [s for s in root.iter("sequence") if s.find("media") is not None and id(s) not in nested]


def read_sequence(path: Path, name: str | None = None, prefer: str = "") -> Seq:
    root = ET.parse(path).getroot()
    seqs = sequences(root)
    if not seqs:
        raise ValueError(f"aucune séquence dans {path.name}")
    if name:
        seq = next((s for s in seqs if s.findtext("name") == name), None)
        if seq is None:
            raise ValueError(f"séquence « {name} » introuvable dans {path.name} : "
                             + ", ".join(s.findtext("name") or "?" for s in seqs))
    else:
        seq = next((s for s in reversed(seqs) if (s.findtext("name") or "").lower().endswith(prefer)), seqs[-1]) \
            if prefer else seqs[0]
    fps = _rate(seq)
    files = {f.get("id"): f for f in root.iter("file") if f.get("id") and f.find("pathurl") is not None}
    items = []
    for track in seq.findall("media/video/track") + seq.findall("media/audio/track"):
        for ci in track.findall("clipitem"):
            f = ci.find("file")
            fdef = files.get(f.get("id")) if f is not None else None
            start, end = ci.findtext("start"), ci.findtext("end")
            if fdef is None or start in (None, "-1") or end in (None, "-1"):
                continue
            ticks = ci.findtext("pproTicksIn")
            src = int(ticks) / PPRO_TICKS if ticks else int(ci.findtext("in") or 0) / float(fps)
            p = pathurl_to_path(fdef.findtext("pathurl"))
            items.append(Item(int(start) / float(fps), int(end) / float(fps), src, _key(p),
                              p.suffix.lower() in AUDIO_EXT))
    markers = [(m.findtext("name") or "", int(m.findtext("in") or 0) / float(fps),
                int(m.findtext("out") or m.findtext("in") or 0) / float(fps)) for m in seq.findall("marker")]
    w = int(seq.findtext("media/video/format/samplecharacteristics/width") or 1920)
    h = int(seq.findtext("media/video/format/samplecharacteristics/height") or 1080)
    return Seq(seq.findtext("name") or path.stem, seq, root, fps, (w, h), items, markers)


def _to_source(seq: Seq, t: float) -> list[tuple[str, float]]:
    """(file, source time) of every clip playing at sequence time t, the recorder's .wav first."""
    hits = [i for i in seq.items if i.start - 1e-6 <= t < i.end]
    hits.sort(key=lambda i: not i.audio_file)
    return list(dict.fromkeys((i.file, round(i.src + t - i.start, 4)) for i in hits))


def _to_sequence(seq: Seq, anchors: list[tuple[str, float]]) -> list[float]:
    """Every sequence time where one of the source points plays."""
    out = []
    for file, s in anchors:
        for i in seq.items:
            if i.file == file and i.src - 1e-3 <= s < i.src + (i.end - i.start):
                out.append(i.start + s - i.src)
        if out:
            return sorted(set(round(t, 4) for t in out))
    return out


def sentence_spans(derush: Seq) -> dict[int, list[tuple[float, float]]]:
    """Sentence index -> (start, end) of each of its takes in the derush, from the Sxxx markers.
    A marker over several sentences (S002–S003) is shared out evenly."""
    spans: dict[int, list[tuple[float, float]]] = {}
    for name, t0, t1 in derush.markers:
        m = _SPAN.match(name)
        if not m or name.startswith("FAILED"):
            continue
        a = int(m.group(1)) - 1
        b = int(m.group(2)) - 1 if m.group(2) else a
        n = b - a + 1
        for k, idx in enumerate(range(a, b + 1)):
            spans.setdefault(idx, []).append((t0 + (t1 - t0) * k / n, t0 + (t1 - t0) * (k + 1) / n))
    return spans


def place_sentences(derush: Seq, target: Seq | None = None) -> dict[int, tuple[float, float]]:
    """Sentence index -> (start, end) in `target` (default: the derush itself). The first take that
    still appears in the target wins; the end is where the sentence stops playing contiguously."""
    spans = sentence_spans(derush)
    if target is None:
        return {idx: min(v) for idx, v in spans.items()}
    out: dict[int, tuple[float, float]] = {}
    for idx, takes in spans.items():
        best = None
        for t0, t1 in takes:
            # anchors a little inside the take: its padded edges may also play at the end of the previous clip
            lead = min(0.4, (t1 - t0) / 3)
            starts = _to_sequence(target, _to_source(derush, t0 + lead))
            if not starts:
                continue
            start = starts[0] - lead
            ends = [e for e in _to_sequence(target, _to_source(derush, t1 - lead)) if e > start]
            end = ends[0] + lead if ends and ends[0] - start < 3 * (t1 - t0) + 1 else start + (t1 - t0)
            if best is None or start < best[0]:
                best = (start, end)
        if best:
            out[idx] = best
    return out


def standalone_copy(seq: Seq, uid: str, name: str) -> ET.Element:
    """Copy of a sequence that can live alone in a new XML: every file it uses is fully defined at
    its first use (an XML with several sequences defines each file once, in the first sequence)."""
    full = {f.get("id"): f for f in seq.root.iter("file") if f.get("id") and len(f)}
    out = copy.deepcopy(seq.el)
    out.set("id", uid)
    if out.find("name") is not None:
        out.find("name").text = name
    for u in out.findall("uuid"):
        out.remove(u)
    seen: set[str] = set()
    refs = [(parent, i, f) for parent in out.iter() for i, f in enumerate(parent)
            if f.tag == "file" and f.get("id")]          # document order, collected before editing
    for parent, i, f in refs:
        fid = f.get("id")
        if fid in seen:
            if len(f):
                parent[i] = ET.Element("file", id=fid)
        else:
            seen.add(fid)
            if not len(f) and fid in full:
                parent[i] = copy.deepcopy(full[fid])
    return out
