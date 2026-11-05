"""Cut to the beat: rushes cut on the beats of a piece of music (Outils › Au rythme in the window).

    analysis.py   tempo, beats, bars, hits and loudness of the music (cached per file)
    plan.py       where the cuts go (beats, off-beats, bars, hits; one in N; by hand) and what fills each shot
    sources.py    the rushes: files, folders, or the clips of a Premiere sequence
    export.py     the Premiere XML: the cut sequence, and the music alone with a marker on every cut

The window keeps one dict per project (state « beat »): the music, the rushes, the rushes switched off,
the settings of plan.py. Command line, for scripts and tests:

    python -m fauxraccord.beat music.mp3 rushes/ [selects.xml] --on beat --every 2 -o cut.xml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import analysis, plan, sources
from .plan import settings_of

EMPTY = {"music": "", "rushes": [], "off": [], "settings": {}, "audio": False}


def state_of(saved: dict | None) -> dict:
    out = {**EMPTY, **(saved or {})}
    out["settings"] = {k: v for k, v in (out.get("settings") or {}).items() if k in plan.DEFAULTS}
    return out


def clean(saved: dict | None) -> dict:
    """A project's « beat » state with the files gone missing forgotten."""
    s = state_of(saved)
    if s["music"] and not Path(s["music"]).exists():
        s["music"] = ""
    s["rushes"] = [r for r in s["rushes"] if Path(r).exists()]
    return s


def compute(st: dict) -> dict:
    """Everything the page draws, from the saved state: the music's grid, the rushes, the cuts, the shots."""
    st = state_of(st)
    s = settings_of(st["settings"])
    out = {"settings": s, "sources": [], "cuts": [], "shots": [], "music": None, "fps": 25.0}
    srcs = sources.gather(st["rushes"], st["off"])
    out["sources"] = [{"id": x.id, "path": x.path, "name": x.name, "start": x.start, "end": x.end, "on": x.on}
                      for x in srcs]
    first = next((x for x in srcs if x.on), None)
    if first:
        d = sources.info(Path(first.path))
        if d:
            out["fps"] = d["fps"][0] / d["fps"][1]
    if not st["music"]:
        return out
    a = analysis.load(Path(st["music"]))
    if s["phase"] is None:
        s["phase"] = a.phase
    beats, down = plan.grid(a, s["tempo"], s["phase"])
    out["music"] = {"path": a.path, "duration": a.duration, "bpm": round(a.bpm * s["tempo"], 1), "detected": a.bpm,
                    "meter": a.meter, "beats": beats, "down": down}
    if s["range"]:
        lo, hi = s["range"]
        s["range"] = [max(0.0, min(lo, a.duration)), max(0.0, min(hi, a.duration))]
        if s["range"][1] - s["range"][0] < 1:
            s["range"] = None
    out["cuts"] = plan.cuts(a, s, out["fps"])
    out["shots"] = plan.shots(out["cuts"], srcs, s, a.duration)
    return out


def music_payload(path: str) -> dict:
    """The heavy part, sent once per music file: waveform, loudness, hits."""
    a = analysis.load(Path(path))
    return {"path": a.path, "duration": a.duration, "peaks": a.peaks, "pps": analysis.PEAKS_PER_S,
            "onsets": a.onsets, "energy": a.energy, "beats": a.beats}


def write_xml(st: dict, out_xml: Path, only_marks: bool = False) -> dict:
    from .export import export
    st = state_of(st)
    view = compute(st)
    if not view["music"]:
        raise ValueError("no music")
    srcs = sources.gather(st["rushes"], st["off"])
    s = view["settings"]
    rng = tuple(s["range"]) if s["range"] else (0.0, view["music"]["duration"])
    return export(Path(st["music"]), view["shots"], srcs, view["cuts"], out_xml, rng, rush_audio=bool(st["audio"]),
                  only_marks=only_marks)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m fauxraccord.beat", description="Cut rushes on the beats of a music.")
    ap.add_argument("music")
    ap.add_argument("rushes", nargs="+", help="video files, folders, or a Premiere XML of selects")
    ap.add_argument("--on", default="beat", choices=["beat", "off", "half", "bar", "accent"])
    ap.add_argument("--every", type=int, default=2)
    ap.add_argument("--follow", action="store_true", help="more cuts where the music is loud")
    ap.add_argument("--order", default="shuffle", choices=["order", "shuffle"])
    ap.add_argument("--take", default="spread", choices=["start", "spread", "random"])
    ap.add_argument("--audio", action="store_true", help="keep the rushes' own sound")
    ap.add_argument("-o", "--out", type=Path)
    a = ap.parse_args(argv)
    st = {"music": a.music, "rushes": a.rushes, "audio": a.audio,
          "settings": {"on": a.on, "every": a.every, "follow": a.follow, "order": a.order, "take": a.take}}
    view = compute(st)
    m = view["music"]
    print(f"{Path(a.music).name}: {m['bpm']} BPM, {len(m['beats'])} beats, {len(view['cuts'])} cuts, "
          f"{len(view['shots'])} shots from {sum(1 for x in view['sources'] if x['on'])} rushes")
    out = a.out or Path(a.music).with_name(f"{Path(a.music).stem} - au rythme.xml")
    r = write_xml(st, out)
    print(f"-> {out} ({r['shots']} clips)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
