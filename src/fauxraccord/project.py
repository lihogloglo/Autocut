"""A project is a folder: the script, the rushes and what every step writes live in it.

The window remembers each project's inputs and outputs (app.json, "projects"), so switching folders
never mixes one video's derush with another's illustrations. A folder opened for the first time is
read for what is already there, so work can start at any step: a script and its rushes, a .sync.xml,
a .fauxraccord.xml, or a sequence exported from Premiere each wire up the step that uses them.
"""

from __future__ import annotations

from pathlib import Path

SCRIPT_EXT = {".md", ".txt", ".docx"}
MEDIA_EXT = {".mp4", ".mov", ".mxf", ".mkv", ".avi", ".mts", ".m2ts", ".wav", ".bwf", ".aif", ".aiff",
             ".flac", ".mp3", ".m4a"}

# What belongs to one project (the rest of app.json is the user's settings, shared by all projects).
KEYS = ("script", "rushes", "sync_out", "xml", "sequence", "mode", "keep", "derush_out", "place_xml",
        "broll_out", "sb_refs", "sfx_xml", "step", "beat", "exports")
EMPTY = {"script": "", "rushes": [], "sync_out": "", "xml": "", "sequence": "", "mode": "continue", "keep": None,
         "derush_out": "", "place_xml": "", "broll_out": "", "sb_refs": [], "sfx_xml": "", "step": "sync",
         "beat": {}, "exports": {}}
PATHS = ("script", "sync_out", "xml", "derush_out", "place_xml", "broll_out", "sfx_xml")


def _is_script(f: Path) -> bool:
    n = f.name.lower()
    return (f.suffix.lower() in SCRIPT_EXT and not n.startswith(("~$", "fcp translation results"))
            and not n.endswith((".fauxraccord.txt", ".sync.txt")) and n not in ("credits.txt", "crédits.txt"))


def _newest(files: list[Path]) -> Path | None:
    return max(files, key=lambda f: f.stat().st_mtime, default=None)


def detect(folder: Path) -> dict:
    """The inputs and outputs already in a folder (its top level only: sub-folders are proxies,
    auto-saves, FauxRaccord's own « - sources » folders…)."""
    try:
        files = [f for f in folder.iterdir() if f.is_file()]
    except OSError:
        return {}
    found: dict = {}
    scripts = [f for f in files if _is_script(f)]
    if scripts:
        def rank(f: Path):
            has_out = any((folder / f"{f.stem} - {k}").is_dir() for k in ("sources", "storyboard"))
            return (not has_out, {".md": 0, ".docx": 1}.get(f.suffix.lower(), 2), -f.stat().st_mtime)
        found["script"] = str(min(scripts, key=rank))
    if any(f.suffix.lower() in MEDIA_EXT for f in files):
        found["rushes"] = [str(folder)]
    xmls = [f for f in files if f.suffix.lower() == ".xml"]
    sync = _newest([f for f in xmls if f.name.lower().endswith(".sync.xml")])
    derush = _newest([f for f in xmls if f.name.lower().endswith(".fauxraccord.xml")])
    other = _newest([f for f in xmls if not f.name.lower().endswith((".sync.xml", ".fauxraccord.xml"))])
    if sync:
        found["sync_out"] = str(sync)
    if derush:
        found["derush_out"] = str(derush)
    # the derush input: the latest sequence that is not FauxRaccord's derush (a sync, or an export from Premiere)
    if src := _newest([f for f in (sync, other) if f]):
        found["xml"] = str(src)
        found["mode"] = "all" if src == sync else "continue"
    # where illustrations and cards go: the latest of the derush and an edit exported after it
    if target := _newest([f for f in (derush, other) if f]):
        found["place_xml"] = str(target)
    found["step"] = ("sources" if derush else "derush" if found.get("xml") else
                     "sync" if found.get("rushes") else "sources" if scripts else "sync")
    return found


def clean(data: dict) -> dict:
    """A project's saved state with the files that have gone missing forgotten."""
    out = {**EMPTY, **{k: v for k, v in data.items() if k in KEYS}}
    for k in PATHS:
        if out[k] and not Path(out[k]).exists():
            out[k] = ""
    out["rushes"] = [r for r in out["rushes"] if Path(r).exists()]
    out["sb_refs"] = [r for r in out["sb_refs"] if Path(r).exists()]
    beat = dict(out.get("beat") or {})            # Outils › Au rythme: its music and rushes
    if beat.get("music") and not Path(beat["music"]).exists():
        beat["music"] = ""
    beat["rushes"] = [r for r in beat.get("rushes") or [] if Path(r).exists()]
    out["beat"] = beat
    # where each export is saved, chosen by the user ({kind: path}); a folder gone missing: back to the default
    out["exports"] = {k: v for k, v in (out.get("exports") or {}).items() if v and Path(v).parent.is_dir()}
    if not out["xml"]:
        out.update(sequence="", keep=None)
    return out


def merge(saved: dict | None, folder: Path) -> dict:
    """What was saved for the folder, with blanks filled by what is in it now (e.g. an XML exported
    from Premiere since, or a derush made from the command line)."""
    data = clean(saved or {})
    fresh = detect(folder)
    for k, v in fresh.items():
        if k in ("mode", "step"):
            if saved is None:
                data[k] = v
        elif not data[k]:
            data[k] = v
            if k == "xml" and "mode" in fresh:
                data["mode"] = fresh["mode"]
    return data


def inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False
