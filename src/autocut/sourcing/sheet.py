"""Contact sheet: a local web page to pick assets, served with a tiny API for the selection and the export."""

from __future__ import annotations

import json
import os
import threading
import traceback
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .export import export

PAGE = "planche.html"


class _State:
    def __init__(self, out: Path, derush: Path | None):
        self.out, self.derush = out, derush
        self.log: list[str] = []
        self.running = False
        self.result = ""
        self.lock = threading.Lock()

    def start_export(self, derush: str | None) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running, self.log, self.result = True, [], ""
        if derush:
            self.derush = Path(derush)

        def work():
            try:
                self.result = str(export(self.out, self.derush, log=self.log.append))
            except Exception as e:
                self.log.append(f"ERREUR : {e}")
                self.log.append(traceback.format_exc(limit=3))
            finally:
                self.running = False

        threading.Thread(target=work, daemon=True).start()
        return True


class _Handler(SimpleHTTPRequestHandler):
    state: _State

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
        if self.path == "/api/status":
            s = self.state
            return self._json({"running": s.running, "log": s.log[-400:], "result": s.result,
                               "derush": str(s.derush or "")})
        return super().do_GET()

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        s = self.state
        if self.path == "/api/selection":
            tmp = s.out / "selection.tmp"
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(s.out / "selection.json")
            return self._json({"ok": True})
        if self.path == "/api/export":
            return self._json({"ok": s.start_export(data.get("derush") or None)})
        if self.path == "/api/open":
            target = Path(s.result) if s.result else s.out
            if hasattr(os, "startfile"):
                os.startfile(target)
            return self._json({"ok": True})
        self.send_error(404)


def write_page(out: Path) -> Path:
    path = out / PAGE
    path.write_text((Path(__file__).with_name("planche.html")).read_text(encoding="utf-8"), encoding="utf-8")
    return path


def serve(out: Path, derush: Path | None = None, open_browser: bool = True) -> tuple[ThreadingHTTPServer, str]:
    write_page(out)
    handler = type("Handler", (_Handler,), {"state": _State(out, derush)})
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(handler, directory=str(out)))
    url = f"http://127.0.0.1:{server.server_address[1]}/{PAGE}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if open_browser:
        webbrowser.open(url)
    return server, url
