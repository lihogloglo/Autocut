"""Link with the Premiere panel (premiere/ folder): a local server the panel asks where the exported
illustrations go in the sequence open in Premiere. No XML goes back and forth: the panel reads the
sequence, this computes the placement (same rules as the XML export), the panel imports and places.
"""

from __future__ import annotations

import json
import re
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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


def plan(out: Path, derush: Path | None, sequence: dict, kind: str = "sources") -> dict:
    log: list[str] = []
    files = exported_files(out)
    if not files:
        raise ValueError("rien d'exporté : choisissez les illustrations dans la planche, puis « Exporter »"
                         if kind == "sources" else "pas de storyboard : générez-le dans Autocut, onglet Storyboard")
    placed, ref, timed = layout(out, files, derush, seq_from_panel(sequence), log.append)
    title = Manifest.load(out / "manifest.json").title
    return {"ok": True, "timed": timed, "log": log, "export_dir": str((out / "export").resolve()),
            "bin": f"{KINDS.get(kind, 'Illustrations')} - {title}"[:80],
            "items": [{"path": str(m.path), "bin": m.path.parent.name, "start": round(start, 4),
                       "length": round(length, 4), "still": still, "lane": lane, "label": label,
                       "image": m.path.suffix.lower() in PREMIERE_IMAGE}
                      for (m, start, _src, length, still, label), lane in zip(placed, lanes(placed))]}


class _Handler(BaseHTTPRequestHandler):
    current = staticmethod(lambda kind="sources": (None, None))   # -> (output folder, derush .autocut.xml)

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
        if not self.path.startswith("/status"):
            return self._json({"ok": False}, 404)
        kind = self._kind()
        out, derush = self.current(kind)
        if not out or not (out / "manifest.json").exists():
            return self._json({"ok": False, "error": "Dans Autocut, onglet Illustrations : déposez le script "
                                                     "et collectez d'abord." if kind == "sources" else
                                                     "Dans Autocut, onglet Storyboard : générez-le d'abord."})
        return self._json({"ok": True, "title": Manifest.load(out / "manifest.json").title,
                           "files": len(exported_files(out)), "derush": str(derush or ""),
                           "export_dir": str((out / "export").resolve())})

    def do_POST(self):
        if not self.path.startswith("/plan"):
            return self._json({"ok": False}, 404)
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            kind = self._kind()
            out, derush = self.current(kind)
            if not out:
                raise ValueError("aucun script dans Autocut")
            return self._json(plan(out, derush, data, kind))
        except Exception as e:
            return self._json({"ok": False, "error": str(e), "trace": traceback.format_exc(limit=4)})


def start(current) -> ThreadingHTTPServer | None:
    """Serve the panel in the background. `current()` gives (output folder, derush xml) at each request,
    so the panel always works on what the window shows. None when the port is taken (another Autocut)."""
    handler = type("Handler", (_Handler,), {"current": staticmethod(current)})
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    except OSError:
        return None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# --- Installing the panel ---------------------------------------------------------------------------
# A UXP plugin is a zip of the premiere/ folder renamed .ccx; Adobe's installer (shipped with the
# Creative Cloud app) installs it without UXP Developer Tools. It needs the Creative Cloud app running.

PANEL = Path(__file__).resolve().parents[3] / "premiere"
UPIA = Path(r"C:\Program Files\Common Files\Adobe\Adobe Desktop Common\RemoteComponents\UPI"
            r"\UnifiedPluginInstallerAgent\UnifiedPluginInstallerAgent.exe")


def _upia(*args: str, timeout: float = 600) -> str:
    import subprocess
    r = subprocess.run([str(UPIA), *args], capture_output=True, text=True, timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.stdout + r.stderr


def install_panel(log=print, force: bool = False) -> bool:
    """Install (or update) the Premiere panel. Does nothing when this exact version is installed."""
    import hashlib
    import os
    import subprocess
    import zipfile
    if not UPIA.exists() or not PANEL.is_dir():
        log("Panneau Premiere : Creative Cloud absent, rien à installer")
        return False
    files = sorted(f for f in PANEL.rglob("*") if f.is_file())
    digest = hashlib.sha1(b"".join(f.relative_to(PANEL).as_posix().encode() + f.read_bytes() for f in files)).hexdigest()
    home = Path(os.environ.get("APPDATA", Path.home())) / "autocut"
    stamp = home / "panel.sha1"
    listed = "Autocut" in _upia("/list", "Premiere Pro", timeout=120)
    if listed and not force and stamp.exists() and stamp.read_text().strip() == digest:
        return True
    home.mkdir(parents=True, exist_ok=True)
    ccx = home / "autocut.ccx"
    with zipfile.ZipFile(ccx, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.relative_to(PANEL).as_posix())
    if "Creative Cloud.exe" not in subprocess.run(
            ["tasklist", "/fi", "imagename eq Creative Cloud.exe"], capture_output=True, text=True).stdout:
        log("Panneau Premiere : ouvrez l'application Creative Cloud, puis relancez (pas installé)")
        return False
    log("Panneau Premiere : installation…")
    if listed:
        _upia("/remove", "Autocut")
    out = _upia("/install", str(ccx))
    if "Successful" not in out:
        log("Panneau Premiere : échec de l'installation\n" + out.strip())
        return False
    stamp.write_text(digest)
    log("Panneau Premiere installé (Premiere : Fenêtre > Extensions UXP > Autocut ; redémarrez Premiere s'il est ouvert)")
    return True
