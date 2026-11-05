"""Moments: sort very long rushes (gameplay recordings, documentary B-roll) by what happens in them.

    python -m fauxraccord.moments index <rushes or folders…>                  read each rush once (cached, resumable)
    python -m fauxraccord.moments find  <project.moments.json> [--preset rust] [<rushes…>]
                                                                          kinds of moment -> moments
    python -m fauxraccord.moments speech <project.moments.json> [--model large-v3] [--language fr]
                                                                          transcribe what is said (once, cached),
                                                                          then find again ("said" kinds)
    python -m fauxraccord.moments xml   <project.moments.json> [--out x.xml]  string-outs + range markers
    python -m fauxraccord.moments view  <project.moments.json>            see them: video, lanes, curves, cards
    python -m fauxraccord.moments spike <recording> [--minutes 20]            step-0 test: speeds and a report

The index (index.py) is read once per rush: frames every 2 s as image vectors and small JPEGs, and
for each audio track the AudioSet sounds and loudness per second. Kinds of moment (rules.py,
presets/*.json) are rules over it, so changing one is instant. The project file keeps the rushes,
the kinds as the user tuned them, the moments found and the user's ✓ / ✗.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import reader
from .index import ROOT, RushIndex, Settings, build_all
from .rules import Moment, MomentType, find, load_preset

VERSION = 1


class Project:
    """<name>.moments.json: rushes, kinds of moment, moments, ✓ / ✗."""

    def __init__(self, path: Path):
        self.path = Path(path)
        data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.preset: str = data.get("preset", "")
        self.rushes: list[str] = data.get("rushes", [])
        self.types = [MomentType.from_json(t) for t in data.get("types", [])]
        self.moments = [Moment(**m) for m in data.get("moments", [])]
        self.settings: dict = data.get("settings", {})
        if self.preset and self.types:              # kinds the preset gained since (Points forts…)
            try:
                have = {t.id for t in self.types}
                self.types += [t for t in load_preset(self.preset) if t.id not in have]
            except Exception:
                pass

    def use_preset(self, name: str) -> None:
        self.preset, self.types = name, load_preset(name)

    def save(self) -> None:
        data = {"version": VERSION, "preset": self.preset, "rushes": self.rushes, "settings": self.settings,
                "types": [t.to_json() for t in self.types], "moments": [m.to_json() for m in self.moments]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def update(self, found: list[Moment]) -> None:
        """New moments, keeping the ✓ / ✗ of those that overlap a marked one of the same kind."""
        marked = [m for m in self.moments if m.kept is not None]
        for m in found:
            for old in marked:
                if old.type == m.type and old.rush.lower() == m.rush.lower():
                    overlap = min(old.end, m.end) - max(old.start, m.start)
                    if overlap > 0.5 * min(old.end - old.start, m.end - m.start):
                        m.kept = old.kept
                        break
        self.moments = found


def _settings(a) -> Settings:
    return Settings(step=a.step, vision=a.vision, hwaccel=None if a.hwaccel == "none" else a.hwaccel,
                    keyframes={"auto": None, "key": True, "all": False}[a.frames])


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="fauxraccord.moments")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def reading(p):
        p.add_argument("--step", type=float, default=2.0, help="seconds between frames read")
        p.add_argument("--vision", default="clip", choices=["clip", "jina"])
        p.add_argument("--frames", default="auto", choices=["auto", "key", "all"],
                       help="keyframes only (fast), every frame (slow, exact) or chosen from the recording")
        p.add_argument("--hwaccel", default="auto", help="auto (a short trial picks), none, d3d11va, cuda…")
        p.add_argument("--index-dir", type=Path, default=ROOT)

    p = sub.add_parser("index", help="read rushes once (resumable)")
    p.add_argument("rushes", nargs="+", type=Path)
    reading(p)

    p = sub.add_parser("find", help="find the moments")
    p.add_argument("project", type=Path)
    p.add_argument("rushes", nargs="*", type=Path)
    p.add_argument("--preset", default="")
    p.add_argument("--no-index", action="store_true", help="only use what is already read")
    reading(p)

    p = sub.add_parser("speech", help="transcribe what is said in the rushes (once, cached), then find again")
    p.add_argument("project", type=Path)
    p.add_argument("--model", default="large-v3", help="faster-whisper model (large-v3, large-v3-turbo…)")
    p.add_argument("--language", default="auto", help="fr, en… or auto (whisper finds it)")
    p.add_argument("--device", default="auto", help="cuda, cpu or auto")
    p.add_argument("--compute-type", default="auto")
    p.add_argument("--no-find", action="store_true", help="do not look for the moments afterwards")
    p.add_argument("--index-dir", type=Path, default=ROOT)

    p = sub.add_parser("xml", help="write the Premiere XML")
    p.add_argument("project", type=Path)
    p.add_argument("--out", type=Path)

    p = sub.add_parser("view", help="see the moments: video, timeline lanes, curves, cards (opens the browser)")
    p.add_argument("project", type=Path)
    p.add_argument("--index-dir", type=Path, default=ROOT)

    p = sub.add_parser("spike", help="step-0 test on a real recording")
    p.add_argument("recording", type=Path)
    p.add_argument("--minutes", type=float, default=20.0)
    p.add_argument("--start", type=float, default=0.0, help="minute to start at")
    p.add_argument("--out", type=Path)
    return ap


def _result(text: str) -> None:
    if out := os.environ.get("FAUXRACCORD_RESULT"):
        Path(out).write_text(text, encoding="utf-8")


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = build_parser().parse_args(argv)
    from ..media import ensure_ffmpeg
    ensure_ffmpeg()

    if a.cmd == "index":
        files = reader.recordings(a.rushes)
        if not files:
            sys.exit("no video file found")
        build_all(files, _settings(a), root=a.index_dir)
        _result(json.dumps([str(f) for f in files]))

    elif a.cmd == "find":
        proj = Project(a.project)
        if a.preset or not proj.types:
            proj.use_preset(a.preset or "rust")
        if a.rushes:
            proj.rushes = [str(f.resolve()) for f in reader.recordings(a.rushes)]
        if not proj.rushes:
            sys.exit("no rush: give the recordings or a folder")
        files = [Path(r) for r in proj.rushes if Path(r).exists()]
        if a.no_index:
            indexes = [RushIndex(f, a.index_dir) for f in files]
        else:
            indexes = build_all(files, _settings(a), root=a.index_dir)
        print(f"[{len(files) + 1}/{len(files) + 1}] finding the moments")
        found = find([ix for ix in indexes if ix.done()], proj.types, marks=proj.moments)
        proj.update(found)
        proj.save()
        counts = {t.id: sum(m.type == t.id for m in found) for t in proj.types}
        for t in proj.types:
            learned = f"   learned {t.explain}" if t.explain else ""
            print(f"  {t.id:<10} {counts[t.id]:>4}" + ("" if t.ready() else f"   (not ready: {t.hint})") + learned)
        if any("said" in str(t.signals) for t in proj.types if t.enabled):
            from .speech import done
            unread = [f.name for f in files if not done(f, a.index_dir)]
            if unread:
                print(f"  what is said is not read yet in {len(unread)} rush(es): run `speech` first")
        _result(str(proj.path))

    elif a.cmd == "speech":
        from .. import _pick_device
        from ..transcribe import Transcriber
        from . import speech
        proj = Project(a.project)
        files = [Path(r) for r in proj.rushes if Path(r).exists()]
        if not files:
            sys.exit("no rush: run find first, or give the recordings to find")
        finding = not a.no_find and bool(proj.types)
        steps = len(files) + finding
        device, compute_type = _pick_device(a.device, a.compute_type)
        lang = None if a.language in ("", "auto") else a.language
        transcriber = Transcriber(model_name=a.model, language=lang, device=device, compute_type=compute_type)
        for n, f in enumerate(files, 1):
            print(f"[{n}/{steps}] transcribing {f.name} ({a.model} on {device.upper()})")
            speech.transcribe(f, transcriber, root=a.index_dir)
            print(f"  {speech.status(f, a.index_dir)['words']} words")
        if finding:
            indexes = [ix for ix in (RushIndex(f, a.index_dir) for f in files) if ix.done()]
            print(f"[{steps}/{steps}] finding the moments")
            if indexes:
                proj.update(find(indexes, proj.types, marks=proj.moments))
                proj.save()
        _result(str(proj.path))

    elif a.cmd == "xml":
        from .export import write
        proj = Project(a.project)
        out = a.out or proj.path.with_name(proj.path.name.replace(".moments.json", "") + " Moments.xml")
        names = write(out, proj.moments, proj.types, proj.path.stem.replace(".moments", ""))
        print(f"[1/1] wrote {out.name}: " + ", ".join(names))
        _result(str(out))

    elif a.cmd == "view":
        from .view import write as view
        out = view(a.project, a.index_dir)
        print(f"[1/1] {out}")
        _result(str(out))

    elif a.cmd == "spike":
        from .spike import run
        out = a.out or a.recording.with_name(a.recording.stem + " - moments test")
        run(a.recording, out, minutes=a.minutes, start=a.start * 60)
        _result(str(out / "report.html"))
