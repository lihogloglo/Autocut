"""Sound effects: whooshes, clicks, pops and typing placed on what happens on screen.

    python -m fauxraccord.sfx plan  <edit.xml> --out "<video> - sons"   events -> cues (cues.json), voice waveform
    python -m fauxraccord.sfx place "<video> - sons"                    cues -> "<title> Sons.xml"

The plan reads the edit (events.py), looks inside rendered clips for animations (motion.py), gathers
takes from the sources (library.py) and places them (plan.py). The page (page.py) shows it all with
waveforms and lets every cue be heard, swapped, moved, re-levelled or removed; place writes the XML.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

from . import library as L
from .plan import Cue, Settings, plan, pools

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def default_out(stem_from: Path) -> Path:
    return stem_from.parent / f"{stem_from.stem} - sons"


def _write(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def load_cues(out: Path) -> list[Cue]:
    try:
        return [Cue(**c) for c in json.loads((out / "cues.json").read_text(encoding="utf-8"))["cues"]]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def voice_samples(edit_xml: Path, sequence: str):
    """The voice track as it plays in the edit, 16 kHz mono: its clips decoded and laid at their place
    (nests and generated clips, which have no file, are skipped)."""
    import xml.etree.ElementTree as ET

    import numpy as np

    from ..media import SAMPLE_RATE
    from ..premiere_xml import PremiereSequence
    from .events import _defs, _media, _num, _timed, read, top_sequences
    edit = read(edit_xml, sequence)
    root = ET.parse(edit_xml).getroot()
    seq = next((s for s in top_sequences(root) if s.findtext("name") == sequence), top_sequences(root)[0])
    files, _ = _defs(root)
    f = float(edit.fps)
    out = np.zeros(int(edit.duration * SAMPLE_RATE) + SAMPLE_RATE, dtype=np.float32)
    track = seq.findall("media/audio/track")[edit.voice_track - 1]
    for item, s, e in _timed(track):
        if item.tag != "clipitem" or s < 0 or e <= s:
            continue
        path, _ = _media(item, files)
        if not path or not path.exists():
            continue
        ticks = item.findtext("pproTicksIn")
        src = int(ticks) / 254016000000 if ticks else _num(item, "in") / f
        try:
            y = PremiereSequence.decode(path, src, (e - s) / f)
        except Exception:
            continue
        at = int(s / f * SAMPLE_RATE)
        n = min(len(y), len(out) - at)
        if n > 0:
            out[at:at + n] += y[:n]
    return out


def voice(edit_xml: Path, sequence: str, out: Path, log=print) -> None:
    """The edit's voice as it plays (for listening on the page) and its waveform (for drawing)."""
    import numpy as np

    from ..media import SAMPLE_RATE
    key = f"{edit_xml}|{edit_xml.stat().st_mtime}|{sequence}"
    meta = out / "voice.json"
    try:
        if json.loads(meta.read_text(encoding="utf-8")).get("key") == key and (out / "voice.mp3").exists():
            return
    except (OSError, ValueError):
        pass
    log("  voix du montage (pour l'écouter sur la page)")
    y = voice_samples(edit_xml, sequence)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "-",
                    "-b:a", "64k", str(out / "voice.mp3")], input=y.astype(np.float32).tobytes(), check=True,
                   creationflags=NO_WINDOW)
    hop = SAMPLE_RATE // 50                                      # 50 values a second
    n = len(y) // hop
    peaks = np.abs(y[: n * hop]).reshape(n, hop).max(axis=1)
    top = float(np.percentile(peaks, 99.5)) or 1.0
    _write(meta, {"key": key, "rate": 50, "peaks": [round(min(1.0, float(v) / top), 3) for v in peaks]})


def run_plan(args) -> Path:
    from ..media import ensure_ffmpeg
    from .events import read
    ensure_ffmpeg()
    edit_xml = Path(args.edit)
    out = Path(args.out) if args.out else default_out(edit_xml)
    out.mkdir(parents=True, exist_ok=True)
    steps = 5 if args.motion else 4
    print(f"[1/{steps}] reading {edit_xml.name}")
    edit = read(edit_xml, args.sequence or None)
    events = edit.events
    print(f"  « {edit.name} » : {len(events)} moments, {len(edit.sounds)} sons déjà placés")
    n = 2
    if args.motion:
        print(f"[{n}/{steps}] looking inside the rendered clips ({len(edit.clips)})")
        try:
            from .motion import analyse
            cache = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "fauxraccord" / "sfx-motion"
            found = analyse(edit.clips, edit.fps, cache, log=print,
                            progress=lambda i, k: print(f"  {i}/{k}", flush=True))
            from .events import Edit  # noqa: F401
            for e in found:
                near = [s for s in edit.sounds if -0.15 <= s.t - e.t <= 0.2]
                if near:
                    e.covered = near[0].name
            events = sorted(events + found, key=lambda e: e.t)
            print(f"  {len(found)} animations")
        except ImportError:
            print("  (analyse des clips indisponible)")
        n += 1
    settings = Settings(density=args.density, volume=args.volume, keep_existing=not args.redo_existing,
                        rules={**Settings().rules, **(json.loads(args.rules) if args.rules else {})})
    if not args.rules:
        from .plan import learn
        habits = learn(events)
        if habits:
            settings.rules.update(habits)
            print("  vos habitudes : " + ", ".join(f"{k} → {v}" for k, v in sorted(habits.items())))
    kinds = {k for k in settings.rules.values() if k}
    print(f"[{n}/{steps}] gathering the sounds ({', '.join(sorted(kinds))})")
    pool = pools(kinds, args.sources.split(","), args.folder or [], out / "médias", log=print)
    for k, v in sorted(pool.items()):
        print(f"  {k} : {len(v)} prises")
    n += 1
    print(f"[{n}/{steps}] placing")
    keep = [c for c in load_cues(out) if c.edited] if args.keep_edits else []
    cues = plan(events, pool, settings, keep)
    print(f"  {sum(c.on for c in cues)} sons ({', '.join(f'{k} {sum(1 for c in cues if c.kind == k)}' for k in L.KINDS)})")
    _write(out / "sources.json", {"sources": args.sources.split(","), "folders": args.folder or []})
    _write(out / "events.json", [e.to_json() for e in events])
    _write(out / "pools.json", {k: [s.to_json() for s in v] for k, v in pool.items()})
    _write(out / "cues.json", {"edit": str(edit_xml), "sequence": edit.name, "fps": str(edit.fps),
                               "size": list(edit.size), "duration": edit.duration,
                               "title": args.title or edit_xml.stem, "settings": settings.__dict__,
                               "existing": [s.__dict__ for s in edit.sounds],
                               "cues": [c.to_json() for c in cues]})
    n += 1
    print(f"[{n}/{steps}] voice for the page")
    try:
        voice(edit_xml, edit.name, out)
    except Exception as exc:      # the page still works, without the voice
        print(f"  voix indisponible : {exc}")
    return out / "cues.json"


def run_place(args) -> Path:
    from ..media import ensure_ffmpeg
    from .export import export
    ensure_ffmpeg()
    out = Path(args.folder)
    data = json.loads((out / "cues.json").read_text(encoding="utf-8"))
    cues = [Cue(**c) for c in data["cues"]]
    title = data.get("title") or "FauxRaccord"
    xml = out / f"{title} Sons.xml"
    print(f"[1/1] writing {xml.name}")
    export(cues, Path(data["edit"]), data["sequence"], xml, title, Fraction(data["fps"]), tuple(data["size"]),
           float(data["duration"]))
    print(f"  {sum(c.on for c in cues)} sons · {xml}")
    return xml


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="fauxraccord.sfx")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("edit")
    p.add_argument("--out")
    p.add_argument("--sequence", default="")
    p.add_argument("--title", default="")
    p.add_argument("--density", type=int, default=2)
    p.add_argument("--volume", type=float, default=0.0)
    p.add_argument("--rules", default="", help="JSON: {appear.full: whoosh, ...}")
    p.add_argument("--sources", default="folder,epidemic,earshot")
    p.add_argument("--folder", action="append")
    p.add_argument("--no-motion", dest="motion", action="store_false")
    p.add_argument("--redo-existing", action="store_true", help="also where the edit already has a sound")
    p.add_argument("--keep-edits", action="store_true", help="keep the cues edited on the page")
    q = sub.add_parser("place")
    q.add_argument("folder")
    s = sub.add_parser("suggest", help="ambiences and music for the script, searched on Epidemic (sound board)")
    s.add_argument("--layer", action="append", choices=["amb", "music"], help="repeatable (default: both)")
    s.add_argument("--brief", default="")
    s.add_argument("--script", required=True)
    s.add_argument("--derush", default="")
    s.add_argument("--edit", default="")
    s.add_argument("--engine", default="auto")
    s.add_argument("--quality", default="best")
    s.add_argument("--out", required=True, help="the project's « - sons » folder")
    return ap


def run_suggest(args) -> Path:
    from ..i18n import tr
    from . import library as L
    from . import suggest
    if not L.epidemic_key():
        raise SystemExit(tr("les propositions cherchent sur Epidemic : enregistrez votre clé sur la page Sons"))
    ctx = {"script": args.script, "derush": args.derush, "edit": args.edit, "engine": args.engine,
           "quality": args.quality, "out": args.out}
    epi = L.Epidemic(L.epidemic_key())
    layers = args.layer or ["amb", "music"]
    names = {"amb": tr("Ambiances"), "music": tr("Musiques")}
    for i, layer in enumerate(layers, 1):
        print(f"[{i}/{len(layers)}] " + tr("{what} pour le script", what=names[layer]))
        block = suggest.make(ctx, layer, args.brief, epi)
        print("  " + tr("{n} parties", n=len(block["cues"])))
    return Path(args.out) / suggest.FILE


def main(argv=None) -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    args = build_parser().parse_args(argv)
    from .. import write_result
    write_result({"plan": run_plan, "place": run_place, "suggest": run_suggest}[args.cmd](args))
