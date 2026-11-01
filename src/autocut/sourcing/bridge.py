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


def plan(out: Path, derush: Path | None, sequence: dict) -> dict:
    log: list[str] = []
    files = exported_files(out)
    if not files:
        raise ValueError("rien d'exporté : choisissez les illustrations dans la planche, puis « Exporter »")
    placed, ref, timed = layout(out, files, derush, seq_from_panel(sequence), log.append)
    title = Manifest.load(out / "manifest.json").title
    return {"ok": True, "timed": timed, "log": log, "export_dir": str((out / "export").resolve()),
            "bin": f"Illustrations - {title}"[:80],
            "items": [{"path": str(m.path), "bin": m.path.parent.name, "start": round(start, 4),
                       "length": round(length, 4), "still": still, "lane": lane, "label": label,
                       "image": m.path.suffix.lower() in PREMIERE_IMAGE}
                      for (m, start, _src, length, still, label), lane in zip(placed, lanes(placed))]}


class _Handler(BaseHTTPRequestHandler):
    current = staticmethod(lambda: (None, None))   # -> (output folder, derush .autocut.xml)

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
        if self.path != "/status":
            return self._json({"ok": False}, 404)
        out, derush = self.current()
        if not out or not (out / "manifest.json").exists():
            return self._json({"ok": False, "error": "Dans Autocut, onglet Illustrations : déposez le script "
                                                     "et collectez d'abord."})
        return self._json({"ok": True, "title": Manifest.load(out / "manifest.json").title,
                           "files": len(exported_files(out)), "derush": str(derush or ""),
                           "export_dir": str((out / "export").resolve())})

    def do_POST(self):
        if self.path != "/plan":
            return self._json({"ok": False}, 404)
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            out, derush = self.current()
            if not out:
                raise ValueError("aucun script dans l'onglet Illustrations d'Autocut")
            return self._json(plan(out, derush, data))
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
