"""The rushes to cut: video files, their folders, or the clips of a Premiere sequence (selects).

A sequence's clips each become one source with the in and out the user gave them, so a selection
made in Premiere is respected. Files are probed once (duration, frame rate, size) and remembered.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from ..media import MediaInfo, ensure_ffmpeg, probe
from .analysis import CACHE
from .plan import Source

VIDEO_EXT = {".mp4", ".mov", ".mxf", ".mkv", ".avi", ".mts", ".m2ts", ".webm"}
_lock = threading.Lock()
_mem: dict[str, dict] = {}
PROBES = CACHE / "probes.json"


def _sig(p: Path) -> str:
    st = p.stat()
    return f"{str(p.resolve()).lower()}|{st.st_size}|{int(st.st_mtime)}"


def info(path: Path) -> dict | None:
    """{duration, fps (num, den), width, height, channels, rate} of a media file, cached on disk."""
    try:
        sig = _sig(path)
    except OSError:
        return None
    with _lock:
        if not _mem and PROBES.exists():
            try:
                _mem.update(json.loads(PROBES.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        if sig in _mem:
            return _mem[sig]
    try:
        ensure_ffmpeg()
        m = probe(path)
    except Exception:
        return None
    d = {"duration": m.duration, "fps": [m.fps.numerator, m.fps.denominator], "width": m.width, "height": m.height,
         "channels": m.audio_channels, "rate": m.audio_rate, "video": m.has_video}
    with _lock:
        _mem[sig] = d
        try:
            CACHE.mkdir(parents=True, exist_ok=True)
            PROBES.write_text(json.dumps(_mem), encoding="utf-8")
        except OSError:
            pass
    return d


def media_info(path: Path) -> MediaInfo:
    from fractions import Fraction
    d = info(path)
    if d is None:
        raise ValueError(f"cannot read {path}")
    return MediaInfo(path=Path(path).resolve(), duration=d["duration"], fps=Fraction(*d["fps"]), width=d["width"],
                     height=d["height"], audio_channels=d["channels"], audio_rate=d["rate"], has_video=d["video"])


def files_in(inputs: list[str]) -> list[Path]:
    """The video files behind the inputs (a folder: its videos, one level down too)."""
    out: list[Path] = []
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            found = sorted(f for f in p.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXT)
            for sub in sorted(d for d in p.iterdir() if d.is_dir() and not d.name.lower().startswith(("proxy", "proxies"))):
                try:
                    found += sorted(f for f in sub.iterdir() if f.is_file() and f.suffix.lower() in VIDEO_EXT)
                except OSError:
                    pass
            out += found
        elif p.is_file() and p.suffix.lower() in VIDEO_EXT:
            out.append(p)
    seen, uniq = set(), []
    for f in out:
        k = str(f).lower()
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq


def from_sequence(xml: Path) -> list[Source]:
    """The clips of a Premiere sequence's video tracks, in timeline order, with their in and out.
    Titles, colour mattes, stills and nested sequences are not rushes: left out."""
    import xml.etree.ElementTree as ET

    from ..premiere_xml import pathurl_to_path
    root = ET.parse(xml).getroot()
    seq = next((s for s in root.iter("sequence") if s.find("media") is not None), None)
    if seq is None:
        raise ValueError("no sequence in the XML")
    tb = int(seq.findtext("rate/timebase") or 25)
    fps = tb * 1000 / 1001 if (seq.findtext("rate/ntsc") or "").upper() == "TRUE" else float(tb)
    paths = {f.get("id"): pathurl_to_path(f.findtext("pathurl")) for f in root.iter("file")
             if f.get("id") and f.findtext("pathurl")}
    clips = []
    for track in seq.findall("media/video/track"):
        for ci in track.findall("clipitem"):
            f = ci.find("file")
            path = paths.get(f.get("id")) if f is not None else None
            if path is None or path.suffix.lower() not in VIDEO_EXT or (ci.findtext("enabled") or "TRUE").upper() != "TRUE":
                continue
            start, end = int(ci.findtext("start") or -1), int(ci.findtext("end") or -1)
            src_in, src_out = int(ci.findtext("in") or 0), int(ci.findtext("out") or 0)
            if start < 0 or end < 0:                 # a transition at a head or tail: the source length
                end = start + (src_out - src_in) if start >= 0 else end
                start = end - (src_out - src_in) if start < 0 else start
            ticks = ci.findtext("pproTicksIn")
            a = int(ticks) / 254016000000 if ticks else src_in / fps
            clips.append((start, path, a, a + (src_out - src_in) / fps))
    clips.sort(key=lambda c: c[0])
    return [Source(id=f"{p}|{a:.3f}", path=str(p), name=f"{p.name} · {n + 1}", start=a, end=b)
            for n, (_, p, a, b) in enumerate(clips) if b > a]


def gather(inputs: list[str], off: list[str] = ()) -> list[Source]:
    """Every source of the inputs; those listed in `off` are kept but switched off."""
    out: list[Source] = []
    for raw in inputs:
        p = Path(raw)
        if p.is_file() and p.suffix.lower() == ".xml":
            try:
                out += from_sequence(p)
            except Exception:
                pass
            continue
        for f in files_in([raw]):
            d = info(f)
            if d and d.get("video") and d["duration"] > 0.2:
                out.append(Source(id=str(f), path=str(f), name=f.name, start=0.0, end=float(d["duration"])))
    off = set(off)
    for s in out:
        s.on = s.id not in off
    return out
