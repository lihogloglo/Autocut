"""Link with the Premiere panel (premiere/ folder): a local server the panel asks where the exported
illustrations go in the sequence open in Premiere. No XML goes back and forth: the panel reads the
sequence, this computes the placement (same rules as the XML export), the panel imports and places.
"""

from __future__ import annotations

import json
import re
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..i18n import tr
from .export import PREMIERE_IMAGE, layout, lanes
from .model import Manifest
from .place import seq_from_panel

PORT = 47820
_FILE = re.compile(r"S(\d{3})-\d{2} ")


def exported_files(out: Path) -> list[tuple[int, Path]]:
    """(sentence index, file) of everything in export/, from the `S014-01 …` names."""
    files = []
    for p in sorted((out / "export").glob("*/S*")):
        m = _FILE.match(p.name)
        if m and p.is_file() and not p.name.endswith((".part", ".ytdl")):
            files.append((int(m.group(1)) - 1, p))
    return files


KINDS = {"sources": "Illustrations", "storyboard": "Storyboard"}


PANEL_PLACED = "placé par le panneau.json"


def _sources_files(out: Path, log: list[str], auto: bool = False) -> list[tuple[int, Path]]:
    """The ticked illustrations already in médias/ (auto: and the AI's pick for the other sentences),
    minus those dragged into the edit by hand."""
    from .library import selected_files
    files, missing = selected_files(out, skip_dragged=True, auto=auto)
    if missing:
        log.append(tr("{n} élément(s) choisi(s) pas encore téléchargé(s) : « Télécharger la sélection » "
                      "dans la planche", n=missing))
    return [(a.sentence, p) for a, p in files]


def ours(out: Path, kind: str) -> list[str]:
    """Files the panel placed itself: replaced when it places again. Never what was dragged by hand."""
    if kind != "sources":
        return []
    try:
        placed = set(json.loads((out / PANEL_PLACED).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        placed = set()
    try:
        dragged = {str((out / p).resolve()) for p in json.loads((out / "dragged.json").read_text(encoding="utf-8")).values()}
    except (OSError, ValueError):
        dragged = set()
    return sorted(placed - dragged)


def plan(out: Path, derush: Path | None, sequence: dict, kind: str = "sources", auto: bool = False) -> dict:
    log: list[str] = []
    files = _sources_files(out, log, auto) if kind == "sources" else exported_files(out)
    if not files:
        raise ValueError(tr("rien à placer : cochez des illustrations dans la planche, puis « Télécharger la sélection »")
                         if kind == "sources" else tr("pas de storyboard : générez-le dans FauxRaccord, onglet Storyboard"))
    placed, ref, timed = layout(out, files, derush, seq_from_panel(sequence), log.append)
    title = Manifest.load(out / "manifest.json").title
    if kind == "sources":       # remembered so that the next run (or « Retirer ») takes them off again
        mine = set(ours(out, kind)) | {str(m.path.resolve()) for m, *_ in placed}
        (out / PANEL_PLACED).write_text(json.dumps(sorted(mine), ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "timed": timed, "log": log, "export_dir": str((out / "export").resolve()),
            "bin": f"{KINDS.get(kind, 'Illustrations')} - {title}"[:80],
            "items": [{"path": str(m.path), "bin": m.path.parent.name, "start": round(start, 4),
                       "length": round(length, 4), "still": still, "lane": lane, "label": label,
                       "image": m.path.suffix.lower() in PREMIERE_IMAGE}
                      for (m, start, _src, length, still, label), lane in zip(placed, lanes(placed))]}


# --- What the window asks of the panel -------------------------------------------------------------
# The window cannot reach into Premiere: it leaves a request here, and the panel (open in Premiere)
# asks every few seconds whether there is one, does it, and reports back. Kinds: « sources » and
# « storyboard » (place everything), « insert » (one file at the playhead, data = {path, name}).

_REQ = {"id": 0, "kind": "", "data": None, "state": "", "message": "", "at": 0.0}
_SEEN = {"at": 0.0, "version": ""}    # when the panel last asked for a request (it is open in Premiere), its version
_REQ_LOCK = threading.Lock()
WAIT = 90.0          # a request nobody picked up is dropped after this long
# set by the window: focus(view) brings it to the front on that page; playhead(t, seq) where Premiere's playhead
# is; sequence(data) the open sequence as the panel reads it; want(seq) whether it needs that sequence read;
# status() the project and the sentence followed, shown by the panel
_HOOKS = {"focus": None, "playhead": None, "sequence": None, "want": None, "status": None}
_SEEK = {"t": None}                   # where the window wants Premiere's playhead (taken by the panel's next ask)


def panel_live(within: float = 8.0) -> bool:
    return time.time() - _SEEN["at"] < within


def panel_version() -> str:
    """The version of the panel open in Premiere ('' when none is open, or an old one that does not say)."""
    return _SEEN["version"] if panel_live() else ""


def request(kind: str, data: dict | None = None) -> int:
    with _REQ_LOCK:
        _REQ.update(id=_REQ["id"] + 1, kind=kind, data=data, state="waiting", message="", at=time.time())
        return _REQ["id"]


def seek(seconds: float) -> None:
    """Premiere's playhead to there (a sentence clicked on a planche): the panel does it at its next ask."""
    _SEEK["t"] = float(seconds)


def request_state(rid: int) -> dict:
    with _REQ_LOCK:
        if _REQ["id"] != rid:
            return {"state": "gone"}
        if _REQ["state"] == "waiting" and time.time() - _REQ["at"] > WAIT:
            _REQ["state"] = "expired"
        return {"state": _REQ["state"], "message": _REQ["message"], "kind": _REQ["kind"]}


def insert(path, audio: bool = False) -> dict:
    """One file at Premiere's playhead, through the panel (the boards' « → Premiere »). The panel must be
    open: said at once, instead of a request nobody takes."""
    if not panel_live():
        return {"state": "error", "error": tr("Ouvrez le panneau FauxRaccord dans Premiere : Fenêtre › Extensions UXP › FauxRaccord.")}
    p = Path(path)
    image = p.suffix.lower() in PREMIERE_IMAGE
    duration = None                 # the panel looks for a track free for that long (5 s for a picture)
    if not image:
        try:
            from ..media import probe
            duration = round(probe(p).duration, 3)
        except Exception:
            pass
    return {"state": "sent", "id": request("insert", {"path": str(p), "name": p.name, "audio": audio,
                                                      "image": image, "duration": duration})}


def panel_manifest() -> dict:
    try:
        return json.loads((PANEL / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def hello() -> dict:
    """What the panel checks first: is this FauxRaccord, and which panel version comes with it."""
    from ..setup import version
    return {"ok": True, "app": "FauxRaccord", "version": version(), "panel": panel_manifest().get("version", "")}


def running(timeout: float = 0.6) -> dict | None:
    """The FauxRaccord already open on this computer (its hello), or None."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/hello", timeout=timeout) as r:
            d = json.loads(r.read())
        return d if d.get("app") == "FauxRaccord" else None
    except (OSError, ValueError):
        return None


def focus_running(view: str = "main") -> bool:
    """Bring the FauxRaccord already open to the front (on a page). False when none answers."""
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/focus", data=json.dumps({"view": view}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            return bool(json.loads(r.read()).get("ok"))
    except (OSError, ValueError):
        return False


VIEWS = ("main", "sources", "storyboard", "sons", "moments")


class _Handler(BaseHTTPRequestHandler):
    # -> {"out": output folder, "derush": .fauxraccord.xml or None, "auto": fill unchosen sentences}
    current = staticmethod(lambda kind="sources": {"out": None, "derush": None, "auto": False})

    def _kind(self) -> str:
        from urllib.parse import parse_qs, urlparse
        k = parse_qs(urlparse(self.path).query).get("kind", ["sources"])[0]
        return k if k in KINDS else "sources"

    def log_message(self, *args):
        pass

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/hello"):
            return self._json(hello())
        if self.path.startswith("/i18n"):        # the Premiere panel's texts
            from ..i18n import catalog, ui_lang
            return self._json({"ok": True, "lang": ui_lang(), "dict": catalog(ui_lang())})
        if self.path.startswith("/pending"):      # the panel asks whether the window wants something
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            _SEEN["at"] = time.time()
            _SEEN["version"] = q.get("v", [""])[0][:20]
            seq = q.get("seq", [""])[0][:200]
            try:                                  # it also says where Premiere's playhead is
                t = float(q["t"][0]) if "t" in q else None
            except ValueError:
                t = None
            if t is not None and _HOOKS["playhead"]:
                _HOOKS["playhead"](t, seq)
            want = "sequence" if t is not None and _HOOKS["want"] and _HOOKS["want"](seq) else None
            go, _SEEK["t"] = _SEEK["t"], None
            with _REQ_LOCK:
                fresh = _REQ["state"] == "waiting" and time.time() - _REQ["at"] < WAIT
                return self._json({"ok": True, "request": {"id": _REQ["id"], "kind": _REQ["kind"], "data": _REQ["data"]}
                                   if fresh else None, "seek": go, "want": want,
                                   "status": _HOOKS["status"]() if _HOOKS["status"] else None})
        if not self.path.startswith("/status"):
            return self._json({"ok": False}, 404)
        kind = self._kind()
        cur = self.current(kind)
        out, derush = cur["out"], cur["derush"]
        if not out or not (out / "manifest.json").exists():
            return self._json({"ok": False, "error": tr("Dans FauxRaccord, onglet Illustrations : déposez le script "
                                                        "et collectez d'abord.") if kind == "sources" else
                                                     tr("Dans FauxRaccord, onglet Storyboard : générez-le d'abord.")})
        files = _sources_files(out, [], cur.get("auto", False)) if kind == "sources" else exported_files(out)
        return self._json({"ok": True, "title": Manifest.load(out / "manifest.json").title,
                           "files": len(files), "derush": str(derush or ""),
                           "export_dir": str((out / "export").resolve()),
                           "ours": ours(out, kind) if kind == "sources" else None})

    def do_POST(self):
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self._json({"ok": False}, 400)
        if self.path.startswith("/focus"):        # the panel's « Ouvrir » buttons, or a second FauxRaccord starting
            view = data.get("view") if data.get("view") in VIEWS else "main"
            fn = _HOOKS["focus"]
            if not fn:
                return self._json({"ok": False})
            fn(view)                      # queues it (the window does one at a time)
            return self._json({"ok": True})
        if self.path.startswith("/sequence"):     # the open sequence, read by the panel: where the sentences are
            if _HOOKS["sequence"]:
                _HOOKS["sequence"](data)
            return self._json({"ok": True})
        if self.path.startswith(("/claim", "/result")):       # the panel took the window's request / is done
            with _REQ_LOCK:
                if data.get("id") == _REQ["id"]:
                    if self.path.startswith("/claim"):
                        _REQ["state"] = "placing"
                    else:
                        _REQ.update(state="done" if data.get("ok") else "error", message=str(data.get("message", "")))
            return self._json({"ok": True})
        if not self.path.startswith("/plan"):
            return self._json({"ok": False}, 404)
        try:
            kind = self._kind()
            cur = self.current(kind)
            if not cur["out"]:
                raise ValueError(tr("aucun script dans FauxRaccord"))
            return self._json(plan(cur["out"], cur["derush"], data, kind, cur.get("auto", False)))
        except Exception as e:
            return self._json({"ok": False, "error": str(e), "trace": traceback.format_exc(limit=4)})


def start(current, focus=None, playhead=None, sequence=None, want=None,
          status=None) -> ThreadingHTTPServer | None:
    """Serve the panel in the background. `current(kind)` gives {out, derush, auto} at each request,
    so the panel always works on what the window shows; `focus(view)` brings the window to the front;
    playhead / sequence / want / status (what the panel shows): see _HOOKS. None when the port is taken (another FauxRaccord)."""
    handler = type("Handler", (_Handler,), {"current": staticmethod(current)})
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    except OSError:
        return None
    _HOOKS.update(focus=focus, playhead=playhead, sequence=sequence, want=want, status=status)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# --- Installing the panel ---------------------------------------------------------------------------
# Without Creative Cloud: what Adobe's installer does, done here. The premiere/ folder is copied to
# %APPDATA%\Adobe\UXP\Plugins\External\<id>_<version> and gets its entry in PluginsInfo\v1\premierepro.json;
# Premiere loads it at its next start. Measured with Premiere 26.5 (2026-11): an unsigned panel is fine, and
# Premiere keeps the entry when it quits. The other panels in that list are never touched.

PANEL = Path(__file__).resolve().parents[3] / "premiere"
LEGACY = ("com.lihogloglo.autocut",)      # the panel's id before the rename: replaced, not kept beside


def _uxp() -> Path:
    import os
    return Path(os.environ.get("APPDATA", Path.home())) / "Adobe" / "UXP"


def _registry_file() -> Path:
    return _uxp() / "PluginsInfo" / "v1" / "premierepro.json"


def premiere_installed() -> bool:
    import os
    roots = {Path(os.environ.get("ProgramFiles", r"C:\Program Files")), Path(r"C:\Program Files")}
    return any(any((r / "Adobe").glob("Adobe Premiere Pro*/Adobe Premiere Pro.exe")) for r in roots)


def premiere_running() -> bool:
    import subprocess
    try:
        out = subprocess.run(["tasklist", "/fi", "imagename eq Adobe Premiere Pro.exe"], capture_output=True,
                             text=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "Adobe Premiere Pro.exe" in out


def _read_registry() -> dict | None:
    """Premiere's list of panels; empty when there is none yet, None when it cannot be read (left alone)."""
    f = _registry_file()
    if not f.exists():
        return {"plugins": []}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data.get("plugins"), list) else None


def _plugin_dir(entry: dict) -> Path | None:
    """The folder of an entry, only when it is inside Plugins\\External (never anything else)."""
    rel = str(entry.get("path", "")).replace("$localPlugins", "").lstrip("\\/")
    if not rel:
        return None
    d = (_uxp() / "Plugins" / rel).resolve()
    ext = (_uxp() / "Plugins" / "External").resolve()
    return d if ext in d.parents else None


def _same_files(a: Path, b: Path) -> bool:
    if not b.is_dir():
        return False
    fa = sorted(p.relative_to(a).as_posix() for p in a.rglob("*") if p.is_file())
    fb = sorted(p.relative_to(b).as_posix() for p in b.rglob("*") if p.is_file())
    return fa == fb and all((a / f).read_bytes() == (b / f).read_bytes() for f in fa)


def panel_state() -> tuple[bool, bool, bool]:
    """(Premiere Pro on this computer, our panel installed, the installed one is this version)."""
    m = panel_manifest()
    reg = _read_registry() or {"plugins": []}
    mine = [p for p in reg["plugins"] if p.get("pluginId") == m.get("id")]
    dest = _uxp() / "Plugins" / "External" / f"{m.get('id')}_{m.get('version')}"
    current = any(p.get("versionString") == m.get("version") and p.get("status", "enabled") == "enabled"
                  for p in mine) and _same_files(PANEL, dest)
    return premiere_installed(), bool(mine), current


def _write_registry(reg: dict) -> None:
    import os
    f = _registry_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".fauxraccord.tmp")
    tmp.write_text(json.dumps(reg, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, f)


def _drop(reg: dict, ids: tuple[str, ...]) -> dict:
    """The list without these panels; their folders deleted."""
    import shutil
    keep = []
    for p in reg["plugins"]:
        if p.get("pluginId") in ids:
            d = _plugin_dir(p)
            if d:
                shutil.rmtree(d, ignore_errors=True)
        else:
            keep.append(p)
    return {**reg, "plugins": keep}


def install_panel(log=print, force: bool = False) -> bool:
    """Install (or update) the Premiere panel. Does nothing when this exact version is already there."""
    import shutil
    m = panel_manifest()
    if not m.get("id") or not PANEL.is_dir():
        log(tr("Panneau Premiere : dossier premiere/ introuvable"))
        return False
    if not premiere_installed():
        log(tr("Panneau Premiere : Premiere Pro n'est pas installé sur cet ordinateur"))
        return False
    if not force and panel_state()[2]:
        return True
    reg = _read_registry()
    if reg is None:
        log(tr("Panneau Premiere : la liste des panneaux de Premiere est illisible ({path}) ; rien n'a été changé",
               path=_registry_file()))
        return False
    reg = _drop(reg, (m["id"], *LEGACY))
    dest = _uxp() / "Plugins" / "External" / f"{m['id']}_{m['version']}"
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(PANEL, dest)
    reg["plugins"].append({"hostMinVersion": m["host"]["minVersion"], "name": m["name"],
                           "path": f"$localPlugins\\External\\{m['id']}_{m['version']}", "pluginId": m["id"],
                           "status": "enabled", "type": "uxp", "versionString": m["version"]})
    _write_registry(reg)
    log(tr("Panneau Premiere installé : dans Premiere, Fenêtre › Extensions UXP › FauxRaccord")
        + (" " + tr("(redémarrez Premiere, il est ouvert)") if premiere_running() else ""))
    return True


def uninstall_panel(log=print) -> bool:
    reg = _read_registry()
    if reg is None:
        return False
    _write_registry(_drop(reg, (panel_manifest().get("id", ""), *LEGACY)))
    log(tr("Panneau Premiere retiré"))
    return True
