"""The media folder of an illustrations run: every file downloaded from the planche, one per item.

médias/<type>/S012 youtube - Titre [3f2a9c1e5b7d 80-110].mp4

The download button, « Télécharger la sélection », a drag into Premiere and the placement (XML)
all go through here, so an item is downloaded once whichever way it was asked for: the tag at the
end of the name (item id, plus the excerpt for a video) is how a file is found again, whatever its
folder. Files of the older layout (glissés/, export/) are reused where they are, never moved:
Premiere may already link to them.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..i18n import tr
from .export import credit_line, download_image, download_video, slug
from .fetch import Fetcher
from .model import Asset, Manifest

ROOT = "médias"
TYPES = {"video": "Vidéos", "image": "Images", "screenshot": "Captures d'écran", "page": "Pages PDF"}
LEGACY_DRAG = "glissés"          # earlier drag folder: « … 80-110 [3f2a9c] »
LEGACY_EXPORT = "export"         # earlier export folder: « S012-01 youtube - Titre »
FULL_VIDEO_MAX = 600.0
PARALLEL = 3
SKIP = (".part", ".ytdl", ".tmp")
CREDIT_FILES = ("credits.txt", "credits.csv")

_TAG = re.compile(r"\[([0-9a-f]{12})(?: (\d+)-(\d+))?\]$")
_OLD_TAG = re.compile(r"(?: (\d+)-(\d+))? \[([0-9a-f]{6})\]$")


def _sec(x) -> int:
    """Whole seconds, rounded like the page's Math.round."""
    return math.floor(float(x) + 0.5)


def key(a: Asset, choice: dict | None) -> str:
    """One file per image; per excerpt for a video (the whole video: its id alone)."""
    choice = choice or {}
    if a.kind != "video":
        return a.id
    start, end = choice.get("start", a.start), choice.get("end", a.end)
    if choice.get("full") or start is None or end is None:
        return a.id
    return f"{a.id}@{_sec(start)}-{_sec(end)}"


def _tag(k: str) -> str:
    """« 3f2a9c1e5b7d@80-110 » -> « 3f2a9c1e5b7d 80-110 », the end of the file name."""
    return k.replace("@", " ")


class Library:
    _open: dict[str, Library] = {}
    _open_lock = threading.Lock()

    @classmethod
    def of(cls, out: Path) -> Library:
        """One per output folder in this process: the planche's server and its window share the jobs."""
        k = str(Path(out).resolve()).lower()
        with cls._open_lock:
            lib = cls._open.get(k)
            if lib is None:
                lib = cls._open[k] = cls(Path(out))
            return lib

    def __init__(self, out: Path):
        self.out = out
        self.root = out / ROOT
        self.staging = out / "cache" / "médias"
        self.fetch = Fetcher(out / "cache")
        self.lock = threading.Lock()
        self.jobs: dict[str, dict] = {}     # key -> {state: working|ready|error, keep, progress, path, error}
        self.pool = ThreadPoolExecutor(PARALLEL, thread_name_prefix="media")
        self._manifest_key = None
        self._load()

    def _load(self) -> None:
        man = self.out / "manifest.json"
        mk = man.stat().st_mtime if man.exists() else None
        if mk == self._manifest_key:
            return
        self._manifest_key = mk
        self.manifest = Manifest.load(man)
        self.assets = {a.id: a for a in self.manifest.assets}
        self.sections = {s["idx"]: s for s in self.manifest.sections}
        self.sentences = {s["idx"]: s for s in self.manifest.sentences}

    # --- where files are ---------------------------------------------------------------------

    def final(self, a: Asset, k: str) -> Path:
        """Where a new download goes (without its extension)."""
        folder = self.root / tr(TYPES.get(a.kind, "Images"))
        return folder / f"S{a.sentence + 1:03d} {a.via} - {slug(a.title or tr('Sans titre'), 40)} [{_tag(k)}]"

    def index(self) -> dict[str, Path]:
        """key -> file, for everything already on disk (new layout first, then the older folders)."""
        self._load()
        found: dict[str, Path] = {}
        if self.root.is_dir():
            for p in self.root.rglob("*"):
                if p.is_file() and not p.name.endswith(SKIP) and (m := _TAG.search(p.stem)):
                    found.setdefault(m.group(1) + (f"@{m.group(2)}-{m.group(3)}" if m.group(2) else ""), p)
        old = self.out / LEGACY_DRAG
        if old.is_dir():
            short = {}
            for a in self.manifest.assets:
                short.setdefault(a.id[:6], a.id)
            for p in old.rglob("*"):
                if (p.is_file() and not p.name.endswith(SKIP) and (m := _OLD_TAG.search(p.stem))
                        and (aid := short.get(m.group(3)))):
                    found.setdefault(aid + (f"@{m.group(1)}-{m.group(2)}" if m.group(1) else ""), p)
        exp = self.out / LEGACY_EXPORT
        if exp.is_dir():                 # no id in those names: sentence + source + title (not videos)
            names = {}
            for p in exp.glob("*/S*"):
                if p.is_file() and not p.name.endswith(SKIP) and (m := re.match(r"S(\d{3})-\d{2} (.+)$", p.stem)):
                    names.setdefault((int(m.group(1)) - 1, m.group(2)), p)
            for a in self.manifest.assets:
                if a.kind != "video" and (p := names.get((a.sentence, f"{a.via} - {slug(a.title)}"))):
                    found.setdefault(a.id, p)
        return found

    def find(self, a: Asset, choice: dict | None = None) -> Path | None:
        p = self.index().get(key(a, choice))
        return p if p and p.exists() else None

    # --- downloading -------------------------------------------------------------------------

    def _stage(self, a: Asset, choice: dict, k: str, progress=None) -> Path:
        """The file in the cache, downloaded if need be (a hover may have fetched it already)."""
        self.staging.mkdir(parents=True, exist_ok=True)
        stage = self.staging / k.replace("@", "_")
        ready = [p for p in self.staging.glob(stage.name + ".*") if not p.name.endswith(SKIP)]
        if ready and a.kind != "video":        # videos: a leftover may be a cut-short download, start again
            return ready[0]
        for old in self.staging.glob(stage.name + ".*"):
            old.unlink(missing_ok=True)
        if a.file:
            src = self.out / a.file
            path = stage.with_suffix(src.suffix)
            shutil.copy2(src, path)
            return path
        if a.kind == "video":
            from ..media import ensure_ffmpeg
            ensure_ffmpeg()
            return download_video(a, choice, stage, FULL_VIDEO_MAX, progress=progress)
        return download_image(self.fetch, a, stage)

    def _keep(self, a: Asset, k: str, staged: Path) -> Path:
        dst = self.final(a, k).with_suffix(staged.suffix)
        dst.parent.mkdir(parents=True, exist_ok=True)
        path = Path(shutil.move(str(staged), dst))
        self.write_credits()
        return path

    def get(self, a: Asset, choice: dict | None = None, progress=None) -> Path:
        """The file of this item (and excerpt), downloading it now if it is not there yet."""
        choice = choice or {}
        if done := self.find(a, choice):
            return done
        k = key(a, choice)
        return self._keep(a, k, self._stage(a, choice, k, progress))

    def _run(self, a: Asset, choice: dict, k: str) -> None:
        def progress(frac: float) -> None:
            with self.lock:
                if k in self.jobs:
                    self.jobs[k]["progress"] = round(max(0.0, min(1.0, frac)), 3)
        try:
            staged = self._stage(a, choice, k, progress)
            with self.lock:
                keep = self.jobs[k].get("keep")
            if keep:
                path = self.find(a, choice) or self._keep(a, k, staged)
                job = {"state": "ready", "keep": True, "path": str(path)}
            else:                        # a hover: ready in the cache, not in médias/ unless asked for
                job = {"state": "staged", "keep": False, "path": str(staged)}
        except Exception as e:
            job = {"state": "error", "error": f"{type(e).__name__} : {str(e)[:160]}"}
        with self.lock:
            if not job.get("keep") and self.jobs.get(k, {}).get("keep") and job["state"] == "staged":
                # asked to keep while the hover download was running
                try:
                    job = {"state": "ready", "keep": True, "path": str(self._keep(a, k, Path(job["path"])))}
                except Exception as e:
                    job = {"state": "error", "error": f"{type(e).__name__} : {str(e)[:160]}"}
            self.jobs[k] = job

    def request(self, asset_id: str, choice: dict | None = None, keep: bool = True) -> dict:
        """Start fetching in the background (or say it is there). keep=False is a hover's prefetch: the
        file waits in the cache and only lands in médias/ when it is downloaded or dragged."""
        self._load()
        a = self.assets.get(asset_id)
        if not a:
            return {"state": "error", "error": tr("élément inconnu")}
        choice = choice or {}
        k = key(a, choice)
        with self.lock:
            job = self.jobs.get(k)
            if job and job["state"] == "working":
                job["keep"] = job.get("keep") or keep
                return dict(job)
            if job and job["state"] == "ready" and Path(job["path"]).exists():
                return dict(job)
            if done := self.find(a, choice):
                self.jobs[k] = {"state": "ready", "keep": True, "path": str(done)}
                return dict(self.jobs[k])
            if job and job["state"] == "staged" and Path(job["path"]).exists():
                if not keep:
                    return dict(job)
                self.jobs[k] = {"state": "ready", "keep": True, "path": str(self._keep(a, k, Path(job["path"])))}
                return dict(self.jobs[k])
            self.jobs[k] = {"state": "working", "keep": keep, "progress": None}
        self.pool.submit(self._run, a, choice, k)
        return {"state": "working", "keep": keep, "progress": None}

    def wait(self, asset_id: str, choice: dict | None, timeout: float, keep: bool = True) -> dict:
        import time
        end = time.monotonic() + timeout
        while True:
            job = self.request(asset_id, choice, keep)
            if job["state"] != "working" or time.monotonic() > end:
                return job
            time.sleep(0.1)

    # --- what the planche shows --------------------------------------------------------------

    def status(self) -> dict:
        """Files on disk (key -> path inside the output folder) and the downloads under way."""
        files = {}
        for k, p in self.index().items():
            try:
                files[k] = p.relative_to(self.out).as_posix()
            except ValueError:
                files[k] = str(p)
        with self.lock:
            jobs = {k: {x: j[x] for x in ("state", "progress", "error") if x in j}
                    for k, j in self.jobs.items() if j["state"] in ("working", "error")}
        return {"files": files, "jobs": jobs, "root": str(self.root)}

    def path_of(self, k: str) -> Path | None:
        p = self.index().get(k)
        return p if p and p.exists() else None

    # --- credits -----------------------------------------------------------------------------

    def write_credits(self) -> None:
        """médias/credits.txt (to paste in the video description) and credits.csv, for every file here."""
        self._load()
        have = [(self.assets[k.split("@")[0]], p) for k, p in self.index().items() if k.split("@")[0] in self.assets]
        if not have:
            return
        have.sort(key=lambda x: (x[0].sentence, x[1].name))
        lines, rows, last, seen = [f"Sources — {self.manifest.title}", ""], [], None, set()
        for a, path in have:
            sec = self.sections[self.sentences[a.sentence]["section"]]
            if a.id not in seen:
                if sec["idx"] != last:
                    lines += ["", f"== {sec['title'] or 'Début'} =="]
                    last = sec["idx"]
                lines.append(f"- {credit_line(a)}")
                seen.add(a.id)
            try:
                rel = path.relative_to(self.root).as_posix()
            except ValueError:
                rel = path.relative_to(self.out).as_posix()
            rows.append([rel, a.sentence + 1, a.kind, a.via, a.rights, a.title, a.author, a.licence, a.licence_url,
                         a.source_page, a.url, a.credit, a.note])
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / "credits.tmp"
        tmp.write_text("\n".join(lines).strip() + "\n", encoding="utf-8-sig")
        tmp.replace(self.root / "credits.txt")
        with tmp.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["fichier", "phrase", "type", "source", "droits", "titre", "auteur", "licence", "url licence",
                        "page", "url", "crédit", "note"])
            w.writerows(rows)
        tmp.replace(self.root / "credits.csv")


def selection(out: Path) -> dict[str, dict]:
    try:
        return json.loads((out / "selection.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def dragged_ids(out: Path) -> set[str]:
    """Items dragged into Premiere by hand from the planche (drag.py)."""
    try:
        return set(json.loads((out / "dragged.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def auto_picks(assets: list[Asset], chosen: set[str]) -> dict[str, dict]:
    """« Placer » fills the sentences the user chose nothing for with the AI's best candidate: the
    highest-scored still picture whose rights allow it (cited links first on a tie). Videos are left to
    the user: their excerpt is a choice. {id: choice} for the sentences without a chosen item."""
    taken = {a.sentence for a in assets if a.id in chosen}
    best: dict[int, Asset] = {}
    for a in assets:
        if a.sentence in taken or a.kind == "video" or a.rights == "protégé":
            continue
        cur = best.get(a.sentence)
        if cur is None or (a.score, a.origin == "lien") > (cur.score, cur.origin == "lien"):
            best[a.sentence] = a
    return {a.id: {} for a in best.values()}


def picks(out: Path, auto: bool = False) -> dict[str, dict]:
    """What placing puts in the edit: the ticked items, plus (auto) the AI's pick for the other sentences."""
    sel = selection(out)
    if not auto:
        return sel
    lib = Library.of(out)
    lib._load()
    return {**auto_picks(list(lib.assets.values()), set(sel)), **sel}


def coverage(out: Path) -> dict:
    """Per sentence of the script: 'p' something of it is in Premiere (dragged or placed by the panel),
    'c' chosen, '' nothing. For the window's sentence bar."""
    try:
        man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"states": [], "auto": 0}
    n = len(man.get("sentences", []))
    by_id = {a["id"]: a for a in man.get("assets", [])}
    sel = selection(out)
    dragged = dragged_ids(out)
    try:
        placed_paths = set(json.loads((out / "placé par le panneau.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        placed_paths = set()
    states = [""] * n
    for i in sel:
        a = by_id.get(i)
        if a and 0 <= a["sentence"] < n and not states[a["sentence"]]:
            states[a["sentence"]] = "c"
    for i in dragged:
        a = by_id.get(i)
        if a and 0 <= a["sentence"] < n:
            states[a["sentence"]] = "p"
    if placed_paths:
        lib = Library.of(out)
        lib._load()
        idx = lib.index()
        for i, choice in picks(out, auto=True).items():
            a = lib.assets.get(i)
            p = idx.get(key(a, choice)) if a else None
            if p and str(p.resolve()) in placed_paths and 0 <= a.sentence < n:
                states[a.sentence] = "p"
    assets = [Asset(**{k: v for k, v in a.items() if k in Asset.__dataclass_fields__}) for a in man.get("assets", [])]
    return {"states": states, "auto": len(auto_picks(assets, set(sel)))}


def fetch(out: Path, auto: bool = False, log=print) -> int:
    """Download what placing needs (the choices, and the AI's picks with auto) into médias/. Returns how many
    files are ready."""
    lib = Library(out)
    want = picks(out, auto)
    items = sorted((lib.assets[i] for i in want if i in lib.assets), key=lambda a: (a.sentence, -a.score))
    ok = 0
    for i, a in enumerate(items, 1):
        try:
            if not lib.find(a, want[a.id]):
                log(f"{i}/{len(items)} " + tr("téléchargement : {title}", title=a.title[:60]))
            lib.get(a, want[a.id])
            ok += 1
        except Exception as e:
            log(tr("  [{i}/{n}] ÉCHEC {title} : {error}", i=i, n=len(items), title=a.title[:50],
                   error=f"{type(e).__name__} {str(e)[:120]}"))
    lib.write_credits()
    return ok


def selected_files(out: Path, skip_dragged: bool = False, auto: bool = False) -> tuple[list[tuple[Asset, Path]], int]:
    """(item, file) of the ticked items already downloaded, in script order; and how many are not yet.
    skip_dragged: leave out what was dragged into Premiere by hand (already in the edit).
    auto: also the AI's pick for each sentence nothing was ticked for."""
    lib = Library.of(out)
    lib._load()
    sel = picks(out, auto)
    dragged = dragged_ids(out) if skip_dragged else set()
    idx = lib.index()
    files, missing = [], 0
    for a in sorted((lib.assets[i] for i in sel if i in lib.assets), key=lambda a: (a.sentence, -a.score)):
        if a.id in dragged:
            continue
        p = idx.get(key(a, sel[a.id]))
        if p and p.exists():
            files.append((a, p))
        else:
            missing += 1
    return files, missing


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if hasattr(os, "startfile"):
        os.startfile(path)
