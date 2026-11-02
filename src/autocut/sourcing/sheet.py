"""Contact sheet: a local web page to pick assets, served with a tiny API for the selection and the
downloads (médias/, see library.py). Placing them at their sentences is the window's « Placer » step."""

from __future__ import annotations

import json
import subprocess
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .library import Library, open_folder

PAGE = "planche.html"


class _Handler(SimpleHTTPRequestHandler):
    out: Path

    def log_message(self, *args):
        pass

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/i18n.js":
            from ..i18n import js
            body = js().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if self.path == "/api/files":
            return self._json(Library.of(self.out).status())
        return super().do_GET()

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        lib = Library.of(self.out)
        if self.path == "/api/selection":
            tmp = self.out / "selection.tmp"
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.out / "selection.json")
            return self._json({"ok": True})
        if self.path == "/api/download":         # [{id, choice}]: into médias/, in the background
            return self._json({"ok": True, "jobs": [lib.request(it["id"], it.get("choice") or {}, keep=True)
                                                    for it in data.get("items", [])]})
        if self.path == "/api/reveal":           # show one downloaded file in Explorer
            p = lib.path_of(str(data.get("key", "")))
            if p:
                subprocess.Popen(["explorer", "/select,", str(p)])
            return self._json({"ok": bool(p)})
        if self.path == "/api/open":
            open_folder(lib.root)
            return self._json({"ok": True})
        self.send_error(404)


def write_page(out: Path) -> Path:
    path = out / PAGE
    path.write_text((Path(__file__).with_name("planche.html")).read_text(encoding="utf-8"), encoding="utf-8")
    return path


def serve(out: Path, open_browser: bool = True) -> tuple[ThreadingHTTPServer, str]:
    write_page(out)
    handler = type("Handler", (_Handler,), {"out": out})
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(handler, directory=str(out)))
    url = f"http://127.0.0.1:{server.server_address[1]}/{PAGE}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if open_browser:
        webbrowser.open(url)
    return server, url
