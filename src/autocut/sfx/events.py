"""What happens on screen in an edit (FCP7 XML exported from Premiere), as moments a sound can hit.

Read from the timeline itself, no pixels:
  appear      a clip starts on V2 and above (an image, a video, a nest): "full" when it fills the frame
              (its Motion scale and size say so), "element" when it is smaller, "layer" for adjustment layers
  title       a text or graphic clip starts (Premiere's Essential Graphics)
  exit        a clip on V2+ ends with nothing taking its place
  transition  a video transition (the sound peaks at its middle)
  move        a fast Motion move: scale, position or rotation keyframes changing quickly (slow Ken Burns
              zooms are left alone)
Pixels are only needed for animations baked inside rendered clips: see motion.py, which gets the
`clips` listed here.

Times are in sequence seconds. A clip whose start or end is -1 sits inside a transition: the
transition gives the time.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path

from ..premiere_xml import AUDIO_EXT, pathurl_to_path

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".psd", ".ai", ".svg", ".tif", ".tiff", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".mxf", ".m4v", ".mts"}
SFX_NAME = re.compile(r"\b(sfx|whoosh|woosh|swoosh|swish|click|pop|typing|keyboard|riser|impact|hit|boom|"
                      r"swipe|tick|ding|glitch|transition)\b|^ES_", re.I)
FAST_MOVE = 1.6          # s: a move longer than this is a slow drift (Ken Burns), not a whoosh


@dataclass
class Event:
    t: float                  # when the sound hits, sequence seconds
    kind: str                 # appear | title | exit | transition | move | motion
    track: int                # video track, 1-based
    strength: float = 1.0     # 0..1: how big and sudden it is on screen
    dur: float = 0.0          # length of the transition / move / motion burst
    size: str = ""            # full | element | layer | text
    clip: str = ""            # clip name
    path: str = ""            # media file shown (thumbnails, motion analysis)
    src: float = 0.0          # time in that file at t
    covered: str = ""         # a sound already in the edit at this moment

    def to_json(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(self).items()}


@dataclass
class VClip:
    """A video clip on V2+: motion.py looks inside it for baked animations."""
    path: str
    start: float              # in the sequence
    end: float
    src_in: float             # in the file
    track: int
    name: str


@dataclass
class Sound:
    """An audio clip already in the edit that looks like a sound effect."""
    t: float
    name: str
    track: int
    dur: float
    gain_db: float | None = None


@dataclass
class Edit:
    name: str
    fps: Fraction
    duration: float
    size: tuple[int, int]
    events: list[Event] = field(default_factory=list)
    clips: list[VClip] = field(default_factory=list)
    sounds: list[Sound] = field(default_factory=list)
    voice_track: int = 1


# --- XML helpers ----------------------------------------------------------------------------------

def _num(el: ET.Element | None, tag: str, default: float = 0) -> float:
    try:
        return float(el.findtext(tag))
    except (TypeError, ValueError, AttributeError):
        return default


def _fps(el: ET.Element) -> Fraction:
    tb = int(_num(el, "rate/timebase", 25)) or 25
    return Fraction(tb * 1000, 1001) if (el.findtext("rate/ntsc") or "").upper() == "TRUE" else Fraction(tb)


def top_sequences(root: ET.Element) -> list[ET.Element]:
    """Sequences that are not nested inside another one, the longest first."""
    nested = {id(s) for ci in root.iter("clipitem") for s in ci.findall("sequence")}
    seqs = [s for s in root.iter("sequence") if id(s) not in nested and s.find("media") is not None]
    return sorted(seqs, key=lambda s: -_num(s, "duration"))


def _defs(root: ET.Element) -> tuple[dict[str, ET.Element], dict[str, ET.Element]]:
    """file id -> full <file>, sequence id -> full <sequence> (an XML defines each once, at first use)."""
    files = {f.get("id"): f for f in root.iter("file") if f.get("id") and len(f)}
    seqs = {s.get("id"): s for s in root.iter("sequence") if s.get("id") and s.find("media") is not None}
    return files, seqs


def _timed(track: ET.Element) -> list[tuple[ET.Element, int, int]]:
    """(item, start, end) in frames, -1 resolved from the neighbouring transition."""
    kids = [k for k in track if k.tag in ("clipitem", "transitionitem", "generatoritem")]
    out = []
    for i, k in enumerate(kids):
        s, e = int(_num(k, "start", -1)), int(_num(k, "end", -1))
        if s < 0 and i and kids[i - 1].tag == "transitionitem":
            s = int(_num(kids[i - 1], "start"))
        if e < 0 and i + 1 < len(kids) and kids[i + 1].tag == "transitionitem":
            e = int(_num(kids[i + 1], "end"))
        out.append((k, s, e))
    return out


def _effects(item: ET.Element) -> dict[str, ET.Element]:
    return {(f.findtext("effect/effectid") or f.findtext("effect/name") or ""): f.find("effect")
            for f in item.findall("filter") if f.find("effect") is not None}


def _param(effect: ET.Element | None, pid: str) -> ET.Element | None:
    if effect is None:
        return None
    return next((p for p in effect.findall("parameter") if p.findtext("parameterid") == pid), None)


def _value(p: ET.Element | None, default: float) -> float:
    """A parameter's static value (center: its distance from the middle)."""
    if p is None:
        return default
    v = p.find("value")
    if v is not None and v.find("horiz") is not None:
        return (_num(v, "horiz") ** 2 + _num(v, "vert") ** 2) ** 0.5
    try:
        return float(p.findtext("value"))
    except (TypeError, ValueError):
        return default


def _keys(p: ET.Element | None) -> list[tuple[int, float, tuple[float, float] | None]]:
    """(frame, value, (x, y) for positions) of each keyframe."""
    out = []
    for k in (p.findall("keyframe") if p is not None else []):
        v = k.find("value")
        if v is not None and v.find("horiz") is not None:
            out.append((int(_num(k, "when")), 0.0, (_num(v, "horiz"), _num(v, "vert"))))
        else:
            out.append((int(_num(k, "when")), _num(k, "value"), None))
    return out


def _media(item: ET.Element, files: dict[str, ET.Element]) -> tuple[Path | None, tuple[int, int] | None]:
    f = item.find("file")
    if f is None:
        return None, None
    full = files.get(f.get("id"), f)
    url = full.findtext("pathurl")
    w, h = _num(full, "media/video/samplecharacteristics/width"), _num(full, "media/video/samplecharacteristics/height")
    return (pathurl_to_path(url) if url else None), ((int(w), int(h)) if w and h else None)


def _kind(item: ET.Element, path: Path | None) -> str:
    fx = _effects(item)
    name = (item.findtext("name") or "").lower()
    if item.tag == "generatoritem" or any(k.startswith("Graphic") for k in fx):
        return "text" if "GraphicAndType" in fx or item.tag == "generatoritem" else "graphic"
    if "adjustment layer" in name or "calque d'effets" in name:
        return "layer"
    if item.find("sequence") is not None:
        return "nest"
    ext = (path.suffix.lower() if path else Path(name).suffix.lower())
    return "image" if ext in IMAGE_EXT else "video" if ext in VIDEO_EXT else "other"


# --- Reading --------------------------------------------------------------------------------------

def read(xml: Path, sequence: str | None = None) -> Edit:
    root = ET.parse(xml).getroot()
    tops = top_sequences(root)
    if not tops:
        raise ValueError(f"no sequence in {xml.name}")
    seq = next((s for s in tops if s.findtext("name") == sequence), tops[0]) if sequence else tops[0]
    fps = _fps(seq)
    f = float(fps)
    files, seqdefs = _defs(root)
    size = (int(_num(seq, "media/video/format/samplecharacteristics/width", 1920)),
            int(_num(seq, "media/video/format/samplecharacteristics/height", 1080)))
    edit = Edit(seq.findtext("name") or xml.stem, fps, _num(seq, "duration") / f, size)
    _video(seq, edit, files, seqdefs, offset=0.0, src_in=0.0, until=float("inf"), depth=0)
    _audio(seq, edit, files)
    for e in edit.events:
        near = [s for s in edit.sounds if -0.15 <= s.t - e.t <= 0.2 or (e.kind == "transition" and abs(s.t - e.t) < 0.4)]
        if near:
            e.covered = near[0].name
    edit.events.sort(key=lambda e: (e.t, -e.strength))
    edit.clips.sort(key=lambda c: c.start)
    return edit


def _video(seq: ET.Element, edit: Edit, files: dict, seqdefs: dict, offset: float, src_in: float,
           until: float, depth: int) -> None:
    """Events of one sequence's video tracks; a nest's own tracks are read once, at their place."""
    f = float(_fps(seq))
    tracks = seq.findall("media/video/track")
    for ti, track in enumerate(tracks, 1):
        timed = _timed(track)
        for n, (item, s, e) in enumerate(timed):
            if s < 0 or e <= s:
                continue
            t0, t1 = offset + s / f - src_in, offset + e / f - src_in
            if t1 <= 0 or t0 >= until:
                continue
            if item.tag == "transitionitem":
                if item.findtext("mediatype", "video") != "audio":
                    edit.events.append(Event((t0 + t1) / 2, "transition", ti, 0.9 if t1 - t0 <= 0.6 else 0.6,
                                             t1 - t0, clip=item.findtext("effect/name") or ""))
                continue
            if (item.findtext("enabled") or "TRUE").upper() == "FALSE":
                continue
            path, dims = _media(item, files)
            kind = _kind(item, path)
            name = item.findtext("name") or (path.name if path else "")
            inner = item.find("sequence")
            if inner is not None and not len(inner) and inner.get("id") in seqdefs:
                inner = seqdefs[inner.get("id")]
            cin = _num(item, "in") / f
            fx = _effects(item)
            motion = fx.get("basic")
            scale = _value(_param(motion, "scale"), 100.0)
            if kind in ("image", "video", "nest") and depth == 0:
                frame = 1.0
                if dims:
                    frame = min(dims[0] / edit.size[0], dims[1] / edit.size[1])
                    if kind == "image":       # Premiere fits stills to the frame by default
                        frame = max(frame, 1.0) if frame >= 0.95 else frame
                cover = frame * scale / 100
                size = "full" if cover >= 0.9 else "element"
            else:
                size = {"text": "text", "graphic": "element", "layer": "layer"}.get(kind, "element")
            if ti >= 2 and t0 >= 0.04:
                prev = timed[n - 1] if n else None
                follows = prev is not None and prev[0].tag == "transitionitem"   # the transition already hits
                if not follows:
                    strength = {"full": 0.85, "element": 0.75, "text": 0.7, "layer": 0.35}.get(size, 0.6)
                    edit.events.append(Event(t0, "title" if kind == "text" else "appear", ti, strength, 0.0, size,
                                             name, str(path or ""), cin))
                nxt = timed[n + 1] if n + 1 < len(timed) else None
                replaced = nxt is not None and nxt[1] >= 0 and abs(offset + nxt[1] / f - src_in - t1) < 0.08
                if not replaced and kind != "layer" and t1 < edit.duration - 0.1:
                    edit.events.append(Event(t1, "exit", ti, 0.4 if size == "full" else 0.3, 0.0, size, name,
                                             str(path or ""), cin + (t1 - t0)))
                if kind == "video" and path:
                    edit.clips.append(VClip(str(path), max(t0, 0.0), min(t1, until), cin, ti, name))
            _moves(item, edit, ti, t0, t1, cin, f, motion, name, path)
            if inner is not None and depth < 2:
                _video(inner, edit, files, seqdefs, offset=t0, src_in=cin, until=t1, depth=depth + 1)


def _moves(item, edit: Edit, ti: int, t0: float, t1: float, cin: float, f: float, motion, name, path) -> None:
    """Fast keyframed moves: a whoosh peaking in the middle of each one."""
    for pid in ("scale", "center", "rotation"):
        keys = _keys(_param(motion, pid))
        for (w0, v0, p0), (w1, v1, p1) in zip(keys, keys[1:]):
            a, b = t0 + w0 / f - cin, t0 + w1 / f - cin
            if not (t0 - 0.05 <= a < b <= t1 + 0.05):
                a, b = t0 + w0 / f, t0 + w1 / f        # some exports count keyframes from the clip's start
            if b - a <= 0 or b - a > FAST_MOVE or not (t0 - 0.05 <= a <= t1):
                continue
            if pid == "center" and p0 and p1:
                amount = ((p1[0] - p0[0]) ** 2 + (p1[1] - p0[1]) ** 2) ** 0.5 / 0.5       # 0.5 = half the frame
            elif pid == "scale":
                amount = abs(v1 - v0) / max(v0, v1, 1)
            else:
                amount = abs(v1 - v0) / 90
            if amount < 0.08:
                continue
            speed = amount / (b - a)
            edit.events.append(Event((a + b) / 2, "move", ti, min(1.0, 0.4 + speed / 2), b - a, pid, name,
                                     str(path or ""), cin + (a + b) / 2 - t0))


def _audio(seq: ET.Element, edit: Edit, files: dict) -> None:
    """Sounds already placed (to leave them alone) and which track holds the voice."""
    f = float(edit.fps)
    tracks = [[(item, s, e) for item, s, e in _timed(t) if item.tag == "clipitem" and s >= 0]
              for t in seq.findall("media/audio/track")]
    longest = {ti: sum(e - s for _, s, e in items) for ti, items in enumerate(tracks, 1)}
    if any(longest.values()):
        edit.voice_track = max(longest, key=longest.get)
    voice_files = {str(_media(item, files)[0]) for item, _, _ in tracks[edit.voice_track - 1]} if tracks else set()
    for ti, items in enumerate(tracks, 1):
        if ti == edit.voice_track:
            continue
        for item, s, e in items:
            name = item.findtext("name") or ""
            path, _ = _media(item, files)
            ext = (path.suffix.lower() if path else Path(name).suffix.lower())
            if (e - s) / f > 8 or str(path) in voice_files:      # music, ambience, the voice itself
                continue
            if SFX_NAME.search(name) or ext in AUDIO_EXT:
                lv = None
                for p in item.iter("parameter"):
                    if p.findtext("parameterid") == "level" and p.findtext("value"):
                        try:
                            import math
                            lv = 20 * math.log10(max(float(p.findtext("value")), 1e-6))
                        except ValueError:
                            pass
                edit.sounds.append(Sound(s / f, name, ti, (e - s) / f, lv))
    # a stereo pair (two tracks with the same clips) counts once
    uniq: dict[tuple[int, str], Sound] = {}
    for snd in edit.sounds:
        uniq.setdefault((round(snd.t * f), snd.name), snd)
    edit.sounds = sorted(uniq.values(), key=lambda s: s.t)
