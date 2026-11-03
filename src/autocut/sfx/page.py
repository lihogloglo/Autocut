"""The sound editor page: the edit's voice and every cue as waveforms on a timeline, each cue with
the picture it lands on. Hear it in context, swap the take, move it, change its level, remove it, add
one; change the density or the rules and the plan is redone at once (from events.json and pools.json,
no new analysis), keeping what was edited by hand. A small local server, like the storyboard's.
"""

from __future__ import annotations

import json
import subprocess
import threading
import traceback
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import library as L
from .events import Event
from .plan import Cue, Settings, fit, plan

PAGE = "sons.html"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_lock = threading.Lock()


def _read(out: Path) -> dict:
    return json.loads((out / "cues.json").read_text(encoding="utf-8"))


def _save(out: Path, data: dict) -> None:
    tmp = out / "cues.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(out / "cues.json")


def _pools(out: Path) -> dict[str, list[L.Snd]]:
    try:
        raw = json.loads((out / "pools.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: [L.Snd(**s) for s in v] for k, v in raw.items()}


def _settings(data: dict) -> Settings:
    s = Settings()
    for k, v in (data.get("settings") or {}).items():
        if hasattr(s, k):
            setattr(s, k, v)
    return s


def state(out: Path) -> dict:
    data = _read(out)
    try:
        voice = json.loads((out / "voice.json").read_text(encoding="utf-8"))
        voice.pop("key", None)
    except (OSError, ValueError):
        voice = None
    return {**data, "pools": {k: [s.to_json() for s in v] for k, v in _pools(out).items()}, "voice": voice,
            "has_voice": (out / "voice.mp3").exists()}


def update(out: Path, cid: int, fields: dict) -> dict:
    """One cue changed on the page: kind, take, time, level, on/off."""
    with _lock:
        data = _read(out)
        s = _settings(data)
        cues = [Cue(**c) for c in data["cues"]]
        cue = next(c for c in cues if c.id == cid)
        pools = _pools(out)
        if "kind" in fields and fields["kind"] != cue.kind:
            cue.kind = fields["kind"]
            snd = (pools.get(cue.kind) or [None])[0]
            if snd:
                fit(cue, snd, s)
        if "sound" in fields:                       # a take of the pool, or one chosen in a search
            snd = L.Snd(**fields["sound"])
            if not snd.path:
                snd = _fetch(out, snd)
            # the level set by hand moves with the cue: same offset from the new take's own level
            offset = 0.0
            if cue.sound:
                offset = cue.gain_db - fit(Cue(**{**cue.to_json(), "sound": {}}), L.Snd(**cue.sound), s).gain_db
            fit(cue, snd, s)
            cue.gain_db = round(max(-40.0, min(6.0, cue.gain_db + offset)), 2)
        if "t" in fields:
            shift = float(fields["t"]) - cue.t
            cue.t, cue.start = round(cue.t + shift, 4), round(max(0.0, cue.start + shift), 4)
        if "gain_db" in fields:
            cue.gain_db = round(max(-40.0, min(6.0, float(fields["gain_db"]))), 2)
        if "on" in fields:
            cue.on = bool(fields["on"])
        cue.edited = True
        data["cues"] = [c.to_json() for c in cues]
        _save(out, data)
        return cue.to_json()


def add(out: Path, t: float, kind: str) -> dict:
    with _lock:
        data = _read(out)
        s = _settings(data)
        cues = [Cue(**c) for c in data["cues"]]
        pool = _pools(out).get(kind) or []
        if not pool:
            raise ValueError(f"pas de son « {kind} »")
        used = [c.sound.get("id") for c in cues if c.kind == kind]
        snd = min(pool, key=lambda x: used.count(x.id))             # the take used least so far
        cue = fit(Cue(max((c.id for c in cues), default=0) + 1, round(t, 4), kind, "hand",
                      {"kind": "hand", "t": t, "strength": 0.8}, {}, edited=True), snd, s)
        cues.append(cue)
        cues.sort(key=lambda c: c.t)
        data["cues"] = [c.to_json() for c in cues]
        _save(out, data)
        return cue.to_json()


def replan(out: Path, settings: dict) -> dict:
    """Density, volume or rules changed: plan again from the saved moments, keeping hand edits."""
    with _lock:
        data = _read(out)
        s = _settings(data)
        for k, v in settings.items():
            if hasattr(s, k):
                setattr(s, k, v)
        events = [Event(**e) for e in json.loads((out / "events.json").read_text(encoding="utf-8"))]
        keep = [Cue(**c) for c in data["cues"] if c.get("edited")]
        cues = plan(events, _pools(out), s, keep)
        data["settings"] = s.__dict__
        data["cues"] = [c.to_json() for c in cues]
        _save(out, data)
    return state(out)


def search(out: Path, kind: str, q: str) -> list[dict]:
    """More takes for a kind: the user's folders (by name), the built-in bank, Epidemic (previews)."""
    q = (q or "").strip().lower()
    found: list[L.Snd] = []
    try:
        cfg = json.loads((out / "sources.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    if cfg.get("folders"):
        found += [x for x in L.scan(cfg["folders"], log=lambda *a: None)
                  if (x.kind == kind or (q and q in x.name.lower())) and (not q or q in x.name.lower())][:40]
    if L.earshot_ok():
        found += [x for x in L.earshot_sounds(kind) if not q or q in x.name.lower()]
    if L.epidemic_key():
        try:
            found += L.Epidemic(L.epidemic_key()).search(q or L.EPIDEMIC_QUERIES.get(kind, kind), kind, n=24)
        except Exception:
            pass
    return [x.to_json() for x in found]


def _fetch(out: Path, snd: L.Snd) -> L.Snd:
    """A sound chosen from a search, made local: rendered (earshot) or downloaded (Epidemic)."""
    if snd.source == "earshot":
        import random
        return L.render_take(snd, seed=random.randint(200, 9999))
    if snd.source == "epidemic":
        return L.Epidemic(L.epidemic_key()).download(snd, out / "médias")
    raise ValueError("son sans fichier")


def thumb(out: Path, cid: int) -> Path | None:
    """The picture where a cue lands: a frame of the clip that appears / moves (cached)."""
    cue = next((c for c in _read(out)["cues"] if c["id"] == cid), None)
    if not cue:
        return None
    ev = cue["event"]
    path = Path(ev.get("path") or "")
    if not path.is_file():
        return None
    src = max(0.0, float(ev.get("src") or 0) - (0.12 if ev.get("kind") == "exit" else -0.12))
    dest = out / ".vignettes" / f"{L.digest(path, round(src, 2))}.jpg"
    if dest.exists():
        return dest
    dest.parent.mkdir(exist_ok=True)
    try:
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
            from PIL import Image
            im = Image.open(path)
            im.thumbnail((360, 360))
            im.convert("RGB").save(dest, quality=82)
        else:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{src:.3f}", "-i", str(path), "-frames:v", "1",
                           "-vf", "scale=360:-2", str(dest)], check=True, creationflags=NO_WINDOW, timeout=30)
    except Exception:
        return None
    return dest if dest.exists() else None


def place(out: Path) -> str:
    from fractions import Fraction

    from .export import export
    data = _read(out)
    xml = out / f"{data.get('title') or 'Autocut'} Sons.xml"
    export([Cue(**c) for c in data["cues"]], Path(data["edit"]), data["sequence"], xml, data.get("title") or "",
           Fraction(data["fps"]), tuple(data["size"]), float(data["duration"]), log=lambda *a: None)
    return str(xml)


def _allowed(out: Path, path: Path) -> bool:
    """Only sounds this page knows about are served (cues, pools, the bank cache, the user's folders)."""
    p = str(path.resolve()).lower()
    if p.startswith(str(out.resolve()).lower()) or p.startswith(str(L.CACHE.resolve()).lower()):
        return True
    data = _read(out)
    known = {str(Path(c["sound"].get("path", "")).resolve()).lower() for c in data["cues"] if c["sound"].get("path")}
    try:
        cfg = json.loads((out / "sources.json").read_text(encoding="utf-8"))
        if any(p.startswith(str(Path(f).resolve()).lower()) for f in cfg.get("folders", [])):
            return True
    except (OSError, ValueError):
        pass
    return p in known or any(p == str(Path(s.path).resolve()).lower() for v in _pools(out).values() for s in v if s.path)


def serve(out: Path, open_browser: bool = False):
    (out / PAGE).write_text((Path(__file__).parent.parent / "web" / PAGE).read_text(encoding="utf-8"), encoding="utf-8")

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _json(self, data, code=200):
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path: Path, ctype: str):
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            from urllib.parse import parse_qs, urlparse
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/i18n.js":
                    from ..i18n import js
                    body = js().encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/javascript; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    return self.wfile.write(body)
                if u.path == "/voice.mp3":          # with Range: the page's player jumps anywhere in it
                    p = out / "voice.mp3"
                    size = p.stat().st_size
                    rng = self.headers.get("Range", "")
                    a, b = 0, size - 1
                    if rng.startswith("bytes="):
                        lo, _, hi = rng[6:].partition("-")
                        a = int(lo) if lo else max(0, size - int(hi))
                        b = int(hi) if hi and lo else size - 1
                    with p.open("rb") as fh:
                        fh.seek(a)
                        body = fh.read(b - a + 1)
                    self.send_response(206 if rng else 200)
                    self.send_header("Content-Type", "audio/mpeg")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", str(len(body)))
                    if rng:
                        self.send_header("Content-Range", f"bytes {a}-{b}/{size}")
                    self.end_headers()
                    return self.wfile.write(body)
                if u.path == "/api/state":
                    return self._json(state(out))
                if u.path == "/api/search":
                    return self._json({"ok": True, "found": search(out, q.get("kind", ""), q.get("q", ""))})
                if u.path == "/snd":
                    p = Path(q.get("path", ""))
                    if p.is_file() and _allowed(out, p):
                        ext = p.suffix.lower()
                        return self._file(p, {".mp3": "audio/mpeg", ".flac": "audio/flac", ".ogg": "audio/ogg",
                                              ".m4a": "audio/mp4"}.get(ext, "audio/wav"))
                    return self.send_error(404)
                if u.path == "/thumb":
                    p = thumb(out, int(q.get("id", 0)))
                    return self._file(p, "image/jpeg") if p else self.send_error(404)
            except Exception as e:
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"})
            return super().do_GET()

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
            try:
                if self.path == "/api/cue":
                    return self._json({"ok": True, "cue": update(out, int(data["id"]), data.get("fields", {}))})
                if self.path == "/api/add":
                    return self._json({"ok": True, "cue": add(out, float(data["t"]), data["kind"])})
                if self.path == "/api/replan":
                    return self._json({"ok": True, "state": replan(out, data.get("settings", {}))})
                if self.path == "/api/place":
                    return self._json({"ok": True, "path": place(out)})
                if self.path == "/api/reveal":
                    p = Path(data.get("path", ""))
                    if p.exists():
                        subprocess.Popen(["explorer", "/select,", str(p)])
                    return self._json({"ok": True})
            except Exception as e:
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}",
                                   "trace": traceback.format_exc(limit=3)})
            self.send_error(404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(out)))
    url = f"http://127.0.0.1:{server.server_address[1]}/{PAGE}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    return server, url
