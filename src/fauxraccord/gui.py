"""The FauxRaccord window: one page per step, each also usable on its own.

1. Synchro       rushes (videos + .wav, or their folder)      -> <title>.sync.xml
2. Derush        a Premiere sequence (raw or half derushed)   -> <title>.fauxraccord.xml
3. Illustrations script links -> contact sheet -> files, credits and B-roll placed on the derush/edit
4. Storyboard     a style in words -> a beat-by-beat storyboard (what to make), cards placed on the edit
5. Sons           automatic: sounds on what moves in the finished edit (editor page, XML); by hand: the sound board
                  (sound effects, ambiences, music dragged into Premiere)
   IA             which AI engine every step uses (API keys, or the user's subscriptions through their CLIs)
   Outils › Au rythme  rushes cut on the beats of a music (beat/): markers or a cut sequence as XML

The page is HTML (web/) in a native window (pywebview on WebView2). Steps run as subprocesses of
the command-line tools, so the window never freezes and a job can be stopped at any time.
"""

from __future__ import annotations

import codecs
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from . import project
from .i18n import tr

APPDATA = Path(os.environ.get("APPDATA", Path.home())) / "fauxraccord"
STATE_FILE = APPDATA / "app.json"
WEB = Path(__file__).parent / "web"

SCRIPT_EXT, MEDIA_EXT = project.SCRIPT_EXT, project.MEDIA_EXT
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
BEAT_AUDIO = {".wav", ".bwf", ".aif", ".aiff", ".flac", ".mp3", ".m4a", ".ogg", ".opus"}
BEAT_VIDEO = {".mp4", ".mov", ".mxf", ".mkv", ".avi", ".mts", ".m2ts", ".webm"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

DEFAULTS = {
    **project.EMPTY, "project": "", "projects": {}, "recent": [], "chain": True, "ui_lang": "",
    "opts": {"model": "large-v3", "max_pause": 0.6, "pad_in": 0.12, "pad_out": 0.25,
             "shots": True, "search": True, "web": True, "videos": True, "llm": "auto", "judge": True, "brief": "", "quality": "best",
             "sb_style": "", "sb_pace": 6, "lang": "auto",
             "shot_height": 4000, "segment": 30, "full_max": 10,
             "sfx_folders": [], "sfx_density": 2, "sfx_sources": {"folder": True, "epidemic": True, "earshot": True},
             "sfx_brief": "", "auto_fill": True},
}


def _unify_montage(s: dict) -> None:
    """One edit per project (« Montage »): Illustrations, Storyboard and Sons all use it. A sound edit chosen
    before that (sfx_xml) becomes the project's edit when it is the newer one."""
    sfx = s.get("sfx_xml") or ""
    if sfx and Path(sfx).exists():
        cur = s.get("place_xml") or ""
        if not cur or not Path(cur).exists() or Path(sfx).stat().st_mtime >= Path(cur).stat().st_mtime:
            s["place_xml"] = sfx
    s["sfx_xml"] = ""


def _python() -> str:
    """python.exe next to the running interpreter (the window itself runs under pythonw.exe)."""
    exe = Path(sys.executable)
    console = exe.with_name("python.exe")
    return str(console if console.exists() else exe)


def _load_state() -> dict:
    state = json.loads(json.dumps(DEFAULTS))
    try:
        saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        state.update({k: v for k, v in saved.items() if k in DEFAULTS and k != "opts"})
        state["opts"].update(saved.get("opts", {}))
        if state["opts"].get("shot_height") in (1080, 2400, 3600):   # old choices: captures are taller now
            state["opts"]["shot_height"] = DEFAULTS["opts"]["shot_height"]
    except (OSError, ValueError):
        pass
    state.update(project.clean(state))
    _unify_montage(state)
    if not state["project"] and state["script"]:      # state saved before projects existed
        state["project"] = str(Path(state["script"]).parent.resolve())
    if state["project"] and not Path(state["project"]).is_dir():
        state["project"] = ""
    state["recent"] = [r for r in state["recent"] if Path(r).is_dir()]
    if state["project"] and state["project"] not in state["recent"]:
        state["recent"].insert(0, state["project"])
    return state


# --- Jobs ---------------------------------------------------------------------------------------------

STEP_RE = re.compile(r"^\[(\d+)/(\d+)\]\s*(.*)")
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
COUNT_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\b")


class Job:
    """One subprocess at a time; its output is parsed into progress and streamed to the page."""

    def __init__(self, emit):
        self.emit = emit
        self.proc: subprocess.Popen | None = None
        self.stopped = False
        self.step = ""

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, step: str, module_args: list[str], on_done) -> None:
        fd, result = tempfile.mkstemp(prefix="fauxraccord-", suffix=".txt")
        os.close(fd)
        from .i18n import ui_lang
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "FAUXRACCORD_RESULT": result,
               "FAUXRACCORD_LANG": ui_lang()}
        self.stopped, self.step = False, step
        self.proc = subprocess.Popen([_python(), "-u", "-m", *module_args], stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                                     creationflags=NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        self.emit({"type": "job", "step": step, "running": True})
        threading.Thread(target=self._read, args=(self.proc, result, on_done), daemon=True).start()

    def stop(self) -> None:
        if self.running:
            self.stopped = True
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True,
                           creationflags=NO_WINDOW)

    def _read(self, proc: subprocess.Popen, result: str, on_done) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        lines: list[str] = []          # finished lines not sent yet
        current = ""                   # line being written (\r rewrites it)
        tail: list[str] = []           # last lines, for the error message
        progress = {"step": 0, "steps": 0, "label": "", "sub": 0.0, "t_step": time.time()}
        t0 = last_send = time.time()

        def parse(line: str) -> None:
            m = STEP_RE.match(line.strip())
            if m:
                progress.update(step=int(m[1]), steps=int(m[2]), label=m[3], sub=0.0, t_step=time.time())
                return
            m = PCT_RE.search(line) if progress["steps"] else None
            c = COUNT_RE.match(line) if progress["steps"] and not m else None
            if m:
                progress["sub"] = min(1.0, float(m[1]) / 100)
            elif c and int(c[2]) > 0:
                progress["sub"] = min(1.0, int(c[1]) / int(c[2]))

        def send(force: bool = False) -> None:
            nonlocal lines, last_send
            if not force and time.time() - last_send < 0.15:
                return
            p = progress
            overall = (p["step"] - 1 + p["sub"]) / p["steps"] if p["steps"] else None
            eta = None
            elapsed_step = time.time() - p["t_step"]
            if p["sub"] > 0.03 and elapsed_step > 20:
                eta = elapsed_step / p["sub"] * (1 - p["sub"])
            self.emit({"type": "log", "lines": lines, "current": current, "progress": overall,
                       "label": p["label"], "stepNo": p["step"], "steps": p["steps"], "eta": eta,
                       "elapsed": time.time() - t0})
            lines, last_send = [], time.time()

        fd = proc.stdout.fileno()
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            for ch in re.split(r"(\r\n|\r|\n)", decoder.decode(chunk)):
                if ch in ("\n", "\r\n"):
                    lines.append(current)
                    tail = (tail + [current])[-30:] if current.strip() else tail
                    current = ""
                elif ch == "\r":
                    current = ""
                elif ch:
                    current += ch
                    parse(current)
            send()
        rc = proc.wait()
        if current:
            lines.append(current)
            tail.append(current)
        send(force=True)
        out = Path(result).read_text(encoding="utf-8").strip() if Path(result).exists() else ""
        Path(result).unlink(missing_ok=True)
        if self.stopped:
            ev = {"ok": False, "message": tr("Arrêté.")}
        elif rc == 0:
            ev = {"ok": True, "message": on_done(out) or tr("Terminé.")}
        else:
            last = next((t.strip() for t in reversed(tail) if re.match(r"^\w*(Error|Exception)\b", t.strip())),
                        tail[-1].strip() if tail else f"code {rc}")
            ev = {"ok": False, "message": last}
        self.emit({"type": "job", "step": self.step, "running": False, **ev})


# --- What the page calls -----------------------------------------------------------------------------

def _tc(s: float) -> str:
    h, rem = divmod(int(round(s)), 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}"


_FRAMES = threading.Semaphore(3)


def _frame(path: Path, t: float, width: int = 320) -> bytes:
    """One frame of a video as a small JPEG, cached on disk (the shots of « Au rythme »)."""
    import hashlib
    from .beat.analysis import CACHE
    st = path.stat()
    width = max(64, min(960, width))
    key = hashlib.sha1(f"{str(path).lower()}|{st.st_size}|{int(st.st_mtime)}|{t:.2f}|{width}".encode()).hexdigest()[:24]
    f = CACHE / "frames" / f"{key}.jpg"
    if f.exists():
        return f.read_bytes()
    from .media import ensure_ffmpeg
    ensure_ffmpeg()
    with _FRAMES:
        proc = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(path), "-frames:v", "1",
                               "-vf", f"scale={width}:-2", "-q:v", "5", "-f", "image2", "-c:v", "mjpeg", "pipe:1"],
                              capture_output=True, timeout=60, creationflags=NO_WINDOW)
    body = proc.stdout
    if body:
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(body)
        except OSError:
            pass
    return body


_MO_INDEX: dict = {}


def _moments_index(path: str):
    """The Moments index of a rush (kept: it caches the chunks it has loaded)."""
    from .moments.index import RushIndex
    if path not in _MO_INDEX:
        _MO_INDEX[path] = RushIndex(Path(path))
    return _MO_INDEX[path]


def _thumb_server(allowed):
    """Small JPEG previews of local pictures, for the window's page. allowed(): the folders and files
    it may read (the project's)."""
    import io
    from functools import lru_cache
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, urlparse

    @lru_cache(maxsize=256)
    def small(path: str, mtime: float) -> bytes:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((480, 480))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=82)
            return buf.getvalue()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            p = Path(q.get("p", [""])[0])
            ok = p.is_file() and any(a and (str(p).lower() == str(a).lower() or project.inside(p, Path(a)))
                                     for a in allowed())
            if ok and url.path == "/a":                 # a music file, for the page's <audio> (seekable)
                return self._file(p)
            try:
                if not ok:
                    body = b""
                elif url.path == "/f":                  # a frame of a video (Au rythme: the shots)
                    body = _frame(p, float(q.get("t", ["0"])[0]), int(q.get("w", ["320"])[0]))
                elif url.path == "/m":                  # a frame read by Moments (its index, no decoding)
                    body = _moments_index(str(p)).jpeg(int(q.get("k", ["0"])[0]))
                else:
                    body = small(str(p), p.stat().st_mtime)
            except Exception:
                body = b""
            self.send_response(200 if body else 404)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "max-age=3600" if url.path == "/f" else "max-age=60")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (ConnectionError, OSError):          # the page dropped the picture (redrawn meanwhile)
                pass

        def _file(self, p: Path):
            import mimetypes
            size = p.stat().st_size
            a, b = 0, size - 1
            rng = self.headers.get("Range", "")
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    a = int(m.group(1))
                    b = min(size - 1, int(m.group(2))) if m.group(2) else size - 1
                else:
                    a = max(0, size - int(m.group(2)))
            self.send_response(206 if m else 200)
            self.send_header("Content-Type", mimetypes.guess_type(p.name)[0] or "application/octet-stream")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(b - a + 1))
            if m:
                self.send_header("Content-Range", f"bytes {a}-{b}/{size}")
            self.end_headers()
            try:
                with p.open("rb") as fh:
                    fh.seek(a)
                    left = b - a + 1
                    while left > 0:
                        chunk = fh.read(min(1 << 16, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except (ConnectionError, OSError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class Api:
    def __init__(self):
        self._window = None
        self._state = _load_state()
        self._job = Job(self._emit)
        self._scan_key = None
        self._scan: dict = {}
        self._sheet = None
        self._sheet_window = None
        self._manifest_cache: tuple = (None, 0)
        self._lock = threading.Lock()
        self._checks: list[dict] | None = None
        self._ai: list[dict] | None = None
        self._sb_server = None

    # plumbing
    def _emit(self, ev: dict) -> None:
        if self._window:
            try:
                self._window.evaluate_js(f"window.app && app.event({json.dumps(ev, ensure_ascii=False)})")
            except Exception:  # window closing
                pass

    def _save(self) -> None:
        s = self._state
        if s["project"]:
            s["projects"][s["project"]] = {k: s[k] for k in project.KEYS}
        try:
            APPDATA.mkdir(parents=True, exist_ok=True)
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(STATE_FILE)
        except OSError:
            pass

    def _push(self) -> None:
        self._emit({"type": "view", "view": self.view()})

    # state for the page
    def view(self) -> dict:
        s = self._state
        return {"state": s, "project": self._project(), "sequences": self._sequences(), "scan": self.scan(),
                "sources": self._sources(), "montage": self._montage(), "refs": [self._thumb(r) for r in s["sb_refs"]],
                "job": {"running": self._job.running, "step": self._job.step}, "checks": self._checks,
                "keys": self._keys(), "ai": self._ai, "storyboard": self._storyboard(), "sfx": self._sfx(),
                "panel": self._panel(), "beat": self._beat_summary(), "moments": self._mo_summary(), "exports": self._exports()}

    def _panel(self) -> dict:
        """The Premiere panel: Premiere on this computer, panel installed, this version, open now (and which)."""
        from .sourcing import bridge
        cached = getattr(self, "_panel_cache", None)
        if not cached or time.time() - cached[0] > 5:
            from .setup import panel_state
            try:
                premiere, installed, current = panel_state()
            except OSError:
                premiere = installed = current = False
            cached = self._panel_cache = (time.time(), {"premiere": premiere, "installed": installed, "current": current,
                                                        "expected": bridge.panel_manifest().get("version", "")})
        seen = bridge.panel_version()
        live = bridge.panel_live()
        # an older panel still open in Premiere (installed again since, Premiere not restarted)
        return {**cached[1], "live": live, "open_version": seen,
                "stale": bool(live and cached[1]["expected"] and seen != cached[1]["expected"])}

    def _project(self) -> dict:
        s = self._state
        rows = [{"path": r, "name": Path(r).name or r, "where": str(Path(r).parent)} for r in s["recent"]]
        return {"path": s["project"], "name": Path(s["project"]).name if s["project"] else "", "recent": rows}

    # projects
    def _switch(self, folder: Path, carry: bool = False) -> None:
        """Make `folder` the current project: its saved inputs and outputs, or what is found in it.
        carry: the current inputs come along (they were dropped before a script said which project)."""
        s = self._state
        self._save()
        key = str(folder.resolve())
        prev, prev_key = {k: s[k] for k in project.KEYS}, s["project"]
        data = project.merge(s["projects"].get(key), folder)
        if carry:
            for k in project.KEYS:
                if k not in ("script", "step") and prev[k] and not data[k]:
                    data[k] = prev[k]
            if prev_key and prev_key != key:      # it only held these files until the script came
                s["projects"].pop(prev_key, None)
                s["recent"] = [r for r in s["recent"] if r != prev_key]
        s.update(data)
        _unify_montage(s)
        s["project"] = key
        s["recent"] = [key, *[r for r in s["recent"] if r != key]][:12]
        self._scan_key = None
        self._title()
        if self._sheet_window:       # the contact sheet belongs to the project it was opened from
            try:
                self._sheet_window[0].destroy()
            except Exception:
                pass
            self._sheet_window = None

    def _title(self) -> None:
        name = Path(self._state["project"]).name if self._state["project"] else ""
        if self._window:
            try:
                self._window.set_title(f"FauxRaccord — {name}" if name else "FauxRaccord")
            except Exception:
                pass

    def open_project(self, folder: str = "") -> dict | None:
        """A folder from the menu or dropped on it (none: ask for one)."""
        if self._job.running:
            return {"ok": False, "message": tr("Une étape tourne : attendez la fin ou arrêtez-la.")}
        if not folder:
            import webview
            start = str(Path(self._state["project"]).parent) if self._state["project"] else ""
            picked = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=start)
            if not picked:
                return None
            folder = picked if isinstance(picked, str) else picked[0]
        p = Path(folder)
        if not p.is_dir():
            self._state["recent"] = [r for r in self._state["recent"] if r != folder]
            self._save()
            return {"ok": False, "message": tr("Dossier introuvable : {name}", name=folder), "view": self.view()}
        self._switch(p)
        self._save()
        return {"ok": True, "view": self.view()}

    def forget_project(self, folder: str) -> dict:
        """Off the list (nothing is deleted on disk: reopening the folder finds its files again)."""
        s = self._state
        if folder != s["project"]:
            s["recent"] = [r for r in s["recent"] if r != folder]
            s["projects"].pop(folder, None)
            self._save()
        return self.view()

    @staticmethod
    def _keys() -> dict:
        """Which API keys are saved, shown masked: the key itself never goes to the page."""
        from .sourcing.llm import gemini_key
        from .sfx.library import epidemic_key
        from .sourcing.llm import _keys as saved
        mask = lambda k: f"{k[:4]}…{k[-4:]}" if len(k) > 12 else (tr("enregistrée") if k else "")   # noqa: E731
        ep = epidemic_key()
        # where the Epidemic key comes from: saved from the window, or the environment / .env (developers)
        src = "" if not ep else "saved" if saved().get("epidemic") else "env"
        return {"gemini": mask(gemini_key()), "epidemic": mask(ep), "epidemic_src": src}

    def _sequences(self) -> list[str]:
        if not self._state["xml"]:
            return []
        try:
            root = ET.parse(self._state["xml"]).getroot()
            return [q.findtext("name") for q in root.iter("sequence") if q.find("media") is not None]
        except (OSError, ET.ParseError):
            return []

    def scan(self) -> dict:
        """What the derush input looks like: raw, half derushed (and where it stops), already done;
        and how much of it still needs transcribing."""
        s = self._state
        if not s["xml"]:
            return {}
        p = Path(s["xml"])
        key = (str(p), p.stat().st_mtime if p.exists() else 0, s["sequence"], s["opts"]["model"])
        with self._lock:
            if key == self._scan_key:
                return self._scan
            try:
                from .premiere_xml import PremiereSequence
                from .transcribe import SourceTranscript, _merge
                from .text import script_language
                seq = PremiereSequence.from_file(p, s["sequence"] or None)
                lang = script_language(s["script"] or None, s["opts"].get("lang", "auto"))
                info = seq.derushed_until()
                todo = known = 0.0
                for src, ranges in seq.analysis_needs().items():
                    total = sum(b - a for a, b in _merge(ranges))
                    miss = sum(b - a for a, b in SourceTranscript(src, s["opts"]["model"], lang).missing(ranges))
                    todo, known = todo + min(miss, total), known + total
                info.update(name=seq.name, to_transcribe=todo, heard=known, skipped=sorted(set(seq.skipped)))
            except Exception as exc:  # shown in the page
                info = {"error": str(exc)}
            self._scan_key, self._scan = key, info
            return info

    def _sources_out(self) -> Path | None:
        if not self._state["script"]:
            return None
        from .sourcing import default_out
        return default_out(Path(self._state["script"]))

    def _sources(self) -> dict:
        out = self._sources_out()
        if not out:
            return {}
        info = {"out": str(out), "exists": out.exists(), "collected": 0, "chosen": 0, "exported": 0}
        man = out / "manifest.json"
        if man.exists():
            mtime = man.stat().st_mtime
            if self._manifest_cache[0] != (str(man), mtime):
                try:
                    n = len(json.loads(man.read_text(encoding="utf-8")).get("assets", []))
                except (OSError, ValueError):
                    n = 0
                self._manifest_cache = ((str(man), mtime), n)
            info["collected"] = self._manifest_cache[1] or 1
        try:
            info["chosen"] = len(json.loads((out / "selection.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        media = out / "médias"          # downloaded from the planche (sourcing/library.py)
        if media.is_dir():
            info["exported"] = sum(1 for f in media.rglob("*") if f.is_file() and f.suffix.lower() not in
                                   (".xml", ".csv", ".txt", ".part", ".ytdl", ".tmp"))
        if man.exists():
            info.update(self._sources_detail(out))
        return info

    def _sources_detail(self, out: Path) -> dict:
        """The sentence bar (what is in Premiere, chosen, empty) and a few thumbnails for the planche card.
        Cached on the files it reads."""
        files = [out / f for f in ("manifest.json", "selection.json", "dragged.json", "placé par le panneau.json")]
        stamp = tuple(f.stat().st_mtime if f.exists() else 0 for f in files)
        cached = getattr(self, "_detail_cache", None)
        if cached and cached[0] == (str(out), stamp):
            return cached[1]
        from .sourcing.library import coverage, selection
        cov = coverage(out)
        try:
            assets = json.loads(files[0].read_text(encoding="utf-8")).get("assets", [])
        except (OSError, ValueError):
            assets = []
        sel = selection(out)
        states = cov["states"]
        ranked = sorted(assets, key=lambda a: (a["id"] not in sel, -a.get("score", 0)))
        thumbs = []
        for a in ranked:
            t = a.get("thumb") or (a.get("url") if a.get("kind") != "video" else "")
            if not t:
                continue
            src = t if t.startswith("http") else self._thumb(str(out / t))
            placed = 0 <= a.get("sentence", -1) < len(states) and states[a["sentence"]] == "p" and a["id"] in sel
            thumbs.append({"src": src, "placed": placed})
            if len(thumbs) == 12:
                break
        detail = {"states": states, "sentences": len(states), "auto": cov["auto"], "thumbs": thumbs,
                  "placed": states.count("p"), "picked": states.count("c")}
        self._detail_cache = ((str(out), stamp), detail)
        return detail

    # the project's edit and small pictures for the page
    def _montage(self) -> str:
        """The edit every step places on: the one given (or found), else FauxRaccord's derush."""
        s = self._state
        return s["place_xml"] or s["derush_out"]

    def _thumb(self, path: str) -> str:
        """A local picture as a small JPEG served to the page (the window's page cannot read file:// paths)."""
        from urllib.parse import quote
        srv = getattr(self, "_thumbs", None)
        if srv is None:
            srv = self._thumbs = _thumb_server(lambda: [self._state["project"], self._state["script"] and
                                                        str(Path(self._state["script"]).parent),
                                                        *self._state["sb_refs"], *self._beat_allowed(),
                                                        *self._mo_allowed()])
        return f"http://127.0.0.1:{srv.server_address[1]}/t?p={quote(path)}"

    def _sb_out(self) -> Path | None:
        if not self._state["script"]:
            return None
        from .storyboard import default_out
        return default_out(Path(self._state["script"]))

    def _storyboard(self) -> dict:
        out = self._sb_out()
        if not out:
            return {}
        info = {"out": str(out), "exists": (out / "storyboard.json").exists(), "beats": 0}
        if info["exists"]:
            try:
                sb = json.loads((out / "storyboard.json").read_text(encoding="utf-8"))
                info.update(beats=len(sb["beats"]), cards=sum(1 for b in sb["beats"] if b.get("card")),
                            created=sb.get("created", ""), engine=sb.get("engine", ""), timing=sb.get("timing", ""),
                            brief=sb["style"].get("brief", ""))
            except (OSError, ValueError, KeyError):
                pass
            xml = next(iter(sorted((out / "export").glob("*Storyboard.xml"))), None)
            info["xml"] = str(xml) if xml else ""
            try:
                cards = [b["card"] for b in sb["beats"] if b.get("card")][:12]
                info["thumbs"] = [self._thumb(str(out / c)) for c in cards]
                info["locked"] = sum(1 for b in sb["beats"] if b.get("locked"))
            except (NameError, KeyError, TypeError):
                info["thumbs"] = []
        return info

    # sound effects
    def _sfx_edit(self) -> str:
        """The edit the sounds go on: the project's edit (« Montage »)."""
        return self._montage()

    def _sfx_out(self) -> Path | None:
        edit = self._sfx_edit()
        if not edit and not self._state["script"]:
            return None
        stem = Path(self._state["script"] or edit).stem
        folder = Path(self._state["project"]) if self._state["project"] else Path(self._state["script"] or edit).parent
        return folder / f"{stem} - sons"

    def _sfx(self) -> dict:
        out = self._sfx_out()
        info = {"edit": self._sfx_edit(), "out": str(out or ""), "exists": False, "cues": 0, "kinds": {}, "xml": "",
                "earshot": True}
        if out and (out / "cues.json").exists():
            try:
                data = json.loads((out / "cues.json").read_text(encoding="utf-8"))
                on = [c for c in data["cues"] if c.get("on")]
                info.update(exists=True, cues=len(on), edited=sum(1 for c in data["cues"] if c.get("edited")))
                for c in on:
                    info["kinds"][c["kind"]] = info["kinds"].get(c["kind"], 0) + 1
                # the sounds along the edit: 120 slices, each the kind it holds most of ('' when silent)
                dur, bins = float(data.get("duration") or 0), [dict() for _ in range(120)]
                for c in on:
                    if dur > 0:
                        b = bins[min(119, int(c.get("t", 0) / dur * 120))]
                        b[c["kind"]] = b.get(c["kind"], 0) + 1
                info["bins"] = [max(b, key=b.get) if b else "" for b in bins]
                xml = out / f"{data.get('title') or ''} Sons.xml"
                info["xml"] = str(xml) if xml.exists() else ""
            except (OSError, ValueError, KeyError):
                pass
        return info

    def _editor_url(self) -> str:
        """The page of the sounds placed on the edit (sfx/page.py), shown in the sound board's « Sur le montage »
        tab. Served once per analysis folder."""
        out = self._sfx_out()
        if not out or not (out / "cues.json").exists():
            return ""
        from .sfx.page import serve
        cur = getattr(self, "_sfx_server", None)
        if cur and cur[0] == str(out):
            return cur[2]
        if cur:
            cur[1].shutdown()
        server, url = serve(out)
        self._sfx_server = (str(out), server, url)
        return url

    def open_sfx(self) -> dict:
        """The sounds placed on the edit: the sound board, on its « Sur le montage » tab."""
        return self.open_board("montage")

    def _board_media(self) -> Path:
        """Where the sound board puts Epidemic downloads and bank takes: the project's sounds, else the cache."""
        out = self._sfx_out()
        if out:
            return out / "médias"
        from .sfx.library import CACHE
        return CACHE / "planche"

    def _board_context(self) -> dict:
        """What the board's « for the script » suggestions need: the script, the sequences that time its
        sentences (the edit the sounds go on, else the illustrations' one, and the derush), the AI engine."""
        s, o = self._state, self._state["opts"]
        out = self._sfx_out()
        edit = self._sfx_edit()
        derush = s["derush_out"] or (edit if edit.lower().endswith(".fauxraccord.xml") else "")
        if edit.lower().endswith(".fauxraccord.xml"):
            edit = ""
        return {"script": s["script"], "derush": derush, "edit": edit, "engine": o.get("llm", "auto"),
                "quality": o.get("quality", "best"), "out": str(out) if out else "", "brief": o.get("sfx_brief", ""),
                "editor": self._editor_url(), "analysed": bool(out and (out / "cues.json").exists()),
                "montage": self._montage()}

    def open_board(self, tab: str = "") -> dict:
        """The sound board in its own FauxRaccord window: sound effects, ambiences and music to drag into
        Premiere, and (tab « montage ») the sounds placed on the edit. Needs no analysis for the rest."""
        import webview

        from .sfx.board import Board, BoardApi, serve
        win = getattr(self, "_board_window", None)
        if win is not None:
            try:
                win.restore()
                win.show()
                win.evaluate_js(f"openTab({json.dumps(tab)})" if tab else "load(true)")
                return {"ok": True}
            except Exception:
                self._board_window = None
        opts = lambda: self._state["opts"]      # noqa: E731  (read at each use: settings change while it is open)
        board = Board(lambda: opts().get("sfx_folders") or [], self._board_media, lambda: opts().get("sfx_sources") or {},
                      self._board_context)
        if getattr(self, "_board_server", None):
            self._board_server.shutdown()
        self._board_server, url = serve(board)
        if tab:
            url += f"?tab={tab}"
        api = BoardApi(board, place=lambda: self.premiere("sons"), export=lambda: self.run("sfx_place"),
                       analyse=lambda: self.run("sfx"), beat=self.beat_from_board)
        win = webview.create_window(tr("Planche sonore"), url, js_api=api, width=1320, height=900,
                                    min_size=(640, 420))
        board.window = win
        self._board_window = win

        def closed():
            self._board_window = None
        win.events.closed += closed
        return {"ok": True}

    def sfx_folder(self, folder: str = "", remove: bool = False) -> dict:
        """A folder of sounds (the user's downloads, packs): added once, used by every project."""
        o = self._state["opts"]
        folders = list(o.get("sfx_folders") or [])
        if remove:
            folders = [f for f in folders if f != folder]
        else:
            if not folder:
                import webview
                picked = self._window.create_file_dialog(webview.FileDialog.FOLDER)
                if not picked:
                    return self.view()
                folder = picked if isinstance(picked, str) else picked[0]
            if folder not in folders and Path(folder).is_dir():
                folders.append(folder)
        o["sfx_folders"] = folders
        self._save()
        return self.view()

    # where exports are saved: by default where each step writes; « Changer… » picks a file, remembered per project
    EXPORT_KINDS = ("sync", "derush", "sources", "storyboard", "sfx", "beat_cut", "beat_marks", "moments")

    def _export_default(self, kind: str) -> Path | None:
        """Where an export goes when the user has not chosen: the file it was last written to, else its usual place."""
        s = self._state
        proj = Path(s["project"]) if s["project"] else None
        last = {"sync": s["sync_out"], "derush": s["derush_out"], "sources": s["broll_out"]}.get(kind)
        if last:
            return Path(last)
        if kind.startswith("beat_"):
            m = self._beat().get("music")
            if not m:
                return None
            name = f"{Path(m).stem} - au rythme.xml" if kind == "beat_cut" else f"{Path(m).stem} - repères.xml"
            return (proj or Path(m).parent) / name
        if kind == "moments":                   # what `moments xml` writes: next to the .moments.json
            pf = self._mo_file()
            return pf.with_name(pf.name.replace(".moments.json", "") + " Moments.xml") if pf else None
        if kind == "sfx":
            out = self._sfx_out()
            return out / f"{Path(s['script'] or self._sfx_edit() or 'sons').stem} Sons.xml" if out else None
        if kind == "storyboard":
            out = self._sb_out()
            return out / "storyboard.xml" if out else None
        if kind == "sources":
            out = self._sources_out()
            return out / "illustrations.xml" if out else None
        if kind == "sync":
            return proj / "synchro.sync.xml" if proj else None
        if kind == "derush":
            return proj / f"{Path(s['xml'] or 'derush').stem}.fauxraccord.xml" if proj else None
        return None

    def _export_target(self, kind: str) -> str:
        return (self._state.get("exports") or {}).get(kind) or str(self._export_default(kind) or "")

    def _exports(self) -> dict:
        """For the page: each export's file, and whether the user chose it."""
        mine, s = self._state.get("exports") or {}, self._state
        known = {"sync": bool(s["sync_out"]), "derush": bool(s["derush_out"]), "sources": bool(s["broll_out"]),
                 "storyboard": False, "sfx": True, "beat_cut": True, "beat_marks": True, "moments": True}
        # exact: the file is known (chosen, written before, or always the same name); else only its folder is
        return {k: {"path": self._export_target(k), "chosen": bool(mine.get(k)), "exact": bool(mine.get(k)) or known[k]}
                for k in self.EXPORT_KINDS}

    def _save_dialog(self, suggested: Path | None, types: tuple[str, ...] = ()) -> str | None:
        """The one « Save as » of the app (every export goes through it; in the Premiere panel, its own picker)."""
        import webview
        kw = {"file_types": types or (tr("Séquence Premiere") + " (*.xml)",)}
        if suggested:
            kw.update(directory=str(suggested.parent if suggested.parent.is_dir() else Path.home()), save_filename=suggested.name)
        picked = self._window.create_file_dialog(webview.FileDialog.SAVE, **kw)
        if not picked:
            return None
        picked = picked if isinstance(picked, str) else picked[0]
        ext = ".xml"
        if types and (m := re.search(r"\(\*(\.[^;)]+)", types[0])):     # the first type's extension
            ext = m.group(1)
        return picked if picked.lower().endswith(ext.lower()) else picked + ext

    def export_dest(self, kind: str, reset: bool = False) -> dict:
        """« Changer… » next to an export: where that file is saved from now on (reset: back to the default)."""
        if kind not in self.EXPORT_KINDS:
            return self.view()
        ex = dict(self._state.get("exports") or {})
        if reset:
            ex.pop(kind, None)
        else:
            cur = self._export_target(kind)
            picked = self._save_dialog(Path(cur) if cur else None)
            if not picked:
                return self.view()
            ex[kind] = picked
        self._state["exports"] = ex
        self._save()
        return self.view()

    def _deliver(self, kind: str, produced: str) -> str:
        """A finished export moved to the file the user chose (its .txt report along), else left where it is."""
        dest = (self._state.get("exports") or {}).get(kind)
        if not produced or not dest:
            return produced
        src, dst = Path(produced), Path(dest)
        if not src.exists() or str(src.resolve()).lower() == str(dst.resolve()).lower():
            return produced
        import shutil
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            txt = src.with_suffix(".txt")
            if txt.exists():
                shutil.move(str(txt), str(dst.with_suffix(".txt")))
        except OSError:
            return produced
        return str(dst)

    # Outils › Au rythme: rushes cut on the beats of a music
    def _beat(self) -> dict:
        b = self._state.get("beat")
        if not isinstance(b, dict):
            b = self._state["beat"] = {}
        return b

    def _beat_allowed(self) -> list[str]:
        """What the page may read for this tool: the music, the rushes (and the files behind a sequence)."""
        b = self._beat()
        return [b.get("music") or "", *(b.get("rushes") or []), *getattr(self, "_beat_paths", [])]

    def _beat_summary(self) -> dict:
        b, last = self._beat(), getattr(self, "_beat_last", None) or {}
        return {"music": b.get("music") or "", "rushes": len(b.get("rushes") or []), "shots": last.get("shots", 0)}

    def _src_url(self, kind: str, path: str, t: float = 0.0, w: int = 320) -> str:
        from urllib.parse import quote
        self._thumb(path)                                # starts the server
        port = self._thumbs.server_address[1]
        return f"http://127.0.0.1:{port}/a?p={quote(path)}" if kind == "a" else \
            f"http://127.0.0.1:{port}/f?p={quote(path)}&t={t:.2f}&w={w}"

    def beat_view(self) -> dict:
        """The cut as it stands: the rushes (on/off, a frame of each), the grid, the cuts, the shots."""
        from . import beat
        try:
            v = beat.compute(self._beat())
        except Exception as e:  # unreadable music or sequence
            return {"error": str(e), "state": beat.state_of(self._beat())}
        self._beat_paths = sorted({x["path"] for x in v["sources"]})
        for x in v["sources"]:
            x["thumb"] = self._src_url("f", x["path"], x["start"] + min(5.0, (x["end"] - x["start"]) * 0.2), 240)
        for sh in v["shots"]:
            src = next((x for x in v["sources"] if x["id"] == sh["src"]), None)
            sh["thumb"] = self._src_url("f", src["path"], round(sh["in"] * 10) / 10, 240) if src else ""
        self._beat_last = {"shots": len(v["shots"]) if v["music"] and v["sources"] else 0}
        v["state"] = beat.state_of(self._beat())
        v["audio_url"] = self._src_url("a", v["music"]["path"]) if v["music"] else ""
        return v

    def beat_music(self) -> dict:
        """The waveform and hits of the music, sent once per file (heavy)."""
        from . import beat
        m = self._beat().get("music")
        if not m:
            return {}
        try:
            return beat.music_payload(m)
        except Exception as e:
            return {"error": str(e)}

    def beat_set(self, patch: dict) -> dict:
        """Settings of the cut (plan.DEFAULTS keys), the rushes switched off (off), the rushes' sound (audio)."""
        from .beat.plan import DEFAULTS as KEYS
        b = self._beat()
        st = dict(b.get("settings") or {})
        for k, v in (patch or {}).items():
            if k in ("off", "audio"):
                b[k] = v
            elif k in KEYS:
                if v is None and k != "phase" and k != "range":
                    st.pop(k, None)
                else:
                    st[k] = v
        b["settings"] = st
        self._save()
        return self.beat_view()

    def beat_input(self, kind: str, path: str = "") -> dict:
        """Remove the music (kind music) or one rush input (kind rush, its path; none: all of them)."""
        b = self._beat()
        if kind == "music":
            b["music"] = ""
            st = dict(b.get("settings") or {})
            for k in ("phase", "tempo", "range", "add", "del", "shots"):    # they belonged to that music
                st.pop(k, None)
            b["settings"] = st
        else:
            b["rushes"] = [r for r in b.get("rushes") or [] if path and r != path]
        self._save()
        return self.view()

    def _beat_music(self, p: Path) -> None:
        b = self._beat()
        if b.get("music") != str(p):
            b["music"] = str(p)
            st = dict(b.get("settings") or {})
            for k in ("phase", "tempo", "range", "add", "del", "shots"):
                st.pop(k, None)
            b["settings"] = st

    def beat_from_board(self, path: str) -> dict:
        """A music of the sound board (« Couper au rythme »): it becomes the tool's music, the page opens."""
        p = Path(path)
        if not p.is_file():
            return {"ok": False, "message": tr("Fichier introuvable.")}
        self._beat_music(p)
        self._state["step"] = "beat"
        self._save()
        self._emit({"type": "added", "view": self.view(), "notes": [tr("Musique : {name}", name=p.name)]})
        if self._window:
            try:
                self._window.restore()
                self._window.show()
            except Exception:
                pass
        return {"ok": True}

    def beat_export(self, kind: str = "cut") -> dict:
        """The XML: kind « cut » (the cut sequence + the markers) or « marks » (the music and its markers)."""
        from . import beat
        b = self._beat()
        if not b.get("music"):
            return {"ok": False, "message": tr("Ajoutez d'abord la musique.")}
        if kind == "cut" and not b.get("rushes"):
            return {"ok": False, "message": tr("Ajoutez d'abord les rushs.")}
        out = Path(self._export_target("beat_" + kind))
        try:
            r = beat.write_xml(b, out, only_marks=kind != "cut")
        except Exception as e:
            return {"ok": False, "message": tr("Export impossible : {error}", error=e)}
        b["out_" + kind] = str(out)
        self._save()
        msg = tr("{n} plans exportés : {name}", n=r["shots"], name=out.name) if kind == "cut" else \
            tr("Repères exportés : {name}", name=out.name)
        return {"ok": True, "path": str(out), "message": msg, "view": self.view()}

    # Outils › Moments: long rushes (gameplay, B-roll) sorted by what happens in them
    def _mo(self) -> dict:
        m = self._state.get("moments")
        if not isinstance(m, dict):
            m = self._state["moments"] = {}
        return m

    def _mo_files(self) -> list[Path]:
        from .moments import reader
        return reader.recordings([Path(r) for r in self._mo().get("rushes") or [] if Path(r).exists()])

    def _mo_allowed(self) -> list[str]:
        return [str(f) for f in self._mo_files()]

    def _mo_file(self) -> Path | None:
        """<folder>/<folder>.moments.json: the kinds as tuned, the moments, the ✓ / ✗."""
        files = self._mo_files()
        if not files:
            return None
        if self._state.get("project") and any(project.inside(f, Path(self._state["project"])) for f in files):
            folder = Path(self._state["project"])
        else:
            folder = files[0].parent
        return folder / f"{folder.name}.moments.json"

    def _mo_project(self):
        from .moments import Project
        pf = self._mo_file()
        if not pf:
            return None
        proj = Project(pf)
        if not proj.types:
            proj.use_preset(self._mo().get("preset") or "rust")
        return proj

    def _mo_summary(self) -> dict:
        m, pf = self._mo(), self._mo_file()
        found = 0
        if pf and pf.exists():
            try:
                found = len(json.loads(pf.read_text(encoding="utf-8")).get("moments", []))
            except (OSError, ValueError):
                pass
        return {"rushes": len(m.get("rushes") or []), "found": found, "runs": m.get("runs", 0)}

    def moments_view(self) -> dict:
        """Everything the Moments page shows: the rushes (read or not), the kinds, the moments, the curves."""
        from urllib.parse import quote
        from .moments import reader
        from .moments.rules import describe, presets
        from .moments.view import _curves
        m, proj, files = self._mo(), self._mo_project(), self._mo_files()
        self._thumb("")                                          # starts the server (frames, video)
        port = self._thumbs.server_address[1]
        types = proj.types if proj else []
        out = {"preset": (proj.preset if proj and proj.preset else m.get("preset") or "rust"), "presets": presets(),
               "file": str(self._mo_file() or ""), "xml": m.get("xml", ""),
               "types": [{"id": t.id, "name": tr(t.name), "color": t.color, "mode": t.mode, "ready": t.ready(),
                          "enabled": t.enabled, "sensitivity": t.sensitivity, "remove": t.remove,
                          "hint": tr(t.hint) if t.hint else "", "user": t.user, "explain": t.explain,
                          "learned": any("learn" in sg for sg in t.signals),
                          "zones": [d for sg in t.signals if (d := describe(sg))],
                          "examples": len(t.examples.get("pos", [])) + (t.examples.get("pos_vectors") or {}).get("spans", 0),
                          "counter": len(t.examples.get("neg", [])) + (t.examples.get("neg_vectors") or {}).get("spans", 0)}
                         for t in types],
               "rushes": []}
        probes = self.__dict__.setdefault("_mo_probes", {})
        for f in files:
            ix = _moments_index(str(f))
            ix._meta, ix._cache = None, {}                      # a job may have read more since
            read = ix.progress() if ix.meta else 0.0
            if ix.meta:
                duration = ix.duration
            else:
                if str(f) not in probes:
                    try:
                        probes[str(f)] = reader.probe(f).duration
                    except Exception:
                        probes[str(f)] = 0.0
                duration = probes[str(f)]
            r = {"path": str(f), "name": f.name, "duration": duration, "read": read, "frames": [], "curves": [],
                 "video": self._src_url("a", str(f)), "img": f"http://127.0.0.1:{port}/m?p={quote(str(f))}&k=",
                 "moments": []}
            try:
                from .moments.speech import status as _speech
                r["speech"] = _speech(ix, duration=duration)
            except Exception:
                r["speech"] = {"done": False, "words": 0}
            if read > 0:
                r["frames"] = [round(float(x), 2) for x in ix.frames()[0]]
                try:
                    r["curves"] = _curves(ix, types)
                except Exception:
                    r["curves"] = []
            if proj:
                r["moments"] = [{**mo.to_json(), "i": i} for i, mo in enumerate(proj.moments)
                                if mo.rush.lower() == str(f).lower()]
            out["rushes"].append(r)
        return out

    def moments_set(self, patch: dict) -> dict:
        """preset (its kinds replace the project's), or one kind's enabled / sensitivity ({"type": id, …})."""
        m, proj = self._mo(), self._mo_project()
        if "preset" in patch:
            m["preset"] = patch["preset"]
            if proj:
                proj.use_preset(patch["preset"])
                proj.moments = []
        elif proj and patch.get("type") and patch.get("delete"):
            proj.types = [t for t in proj.types if not (t.id == patch["type"] and t.user)]
            proj.moments = [m for m in proj.moments if m.type != patch["type"]]
        elif proj and patch.get("type"):
            for t in proj.types:
                if t.id == patch["type"]:
                    for k in ("enabled", "sensitivity"):
                        if k in patch:
                            setattr(t, k, patch[k])
        if proj:
            proj.save()
        self._save()
        return self.moments_view()

    MO_COLOURS = ("#2fb5b5", "#e0a040", "#9a6ee0", "#5aa0e0", "#e06e9a", "#7cc95a", "#c9a227", "#e07a52")

    def moments_teach(self, ex: dict) -> dict:
        """A stretch picked on the timeline ({rush, start, end}): an example (or, with neg, a counter-example)
        of the kind `kind`, or of a new kind named `name`. The search runs again at once."""
        import re as _re
        from .moments.rules import MomentType
        proj = self._mo_project()
        if not proj:
            return {"ok": False, "message": tr("Déposez d'abord les rushs.")}
        span = {"rush": ex["rush"], "start": round(float(ex["start"]), 2), "end": round(float(ex["end"]), 2)}
        if span["end"] - span["start"] < 1:
            return {"ok": False, "message": tr("Choisissez au moins une seconde.")}
        kind = next((t for t in proj.types if t.id == ex.get("kind")), None)
        if kind is None:
            name = (ex.get("name") or "").strip()
            if not name:
                return {"ok": False, "message": tr("Donnez un nom à ce type de moment.")}
            slug = _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "moment"
            ids = {t.id for t in proj.types}
            kid, n = f"u-{slug}", 2
            while kid in ids:
                kid, n = f"u-{slug}-{n}", n + 1
            used = {t.color for t in proj.types}
            colour = next((c for c in self.MO_COLOURS if c not in used), self.MO_COLOURS[len(proj.types) % len(self.MO_COLOURS)])
            kind = MomentType(kid, name, color=colour, mode="state", combine="all", signals=[{"learn": True}],
                              before=1, after=1, gap=6, min_len=2, user=True)
            proj.types.append(kind)
        kind.examples.setdefault("pos", [])
        kind.examples.setdefault("neg", [])
        kind.examples["neg" if ex.get("neg") else "pos"].append(span)
        kind.enabled = True
        proj.save()
        self._save()
        if not self._job.running:
            self.run("moments")
        return {"ok": True, "kind": kind.id, "message": tr("{name} : exemple ajouté, recherche relancée.", name=tr(kind.name))}

    def moments_zone_preview(self, z: dict) -> dict:
        """What a box drawn on the video reads at the frame shown: its words (text), or its fill (gauge)."""
        from .moments import zones
        ix = _moments_index(z["rush"])
        box = [max(0.0, min(1.0, float(v))) for v in z["box"]]
        if z.get("read") == "text":
            try:
                words = zones.text_at(ix, [round(float(z["t"]), 1)], box)[round(float(z["t"]), 1)]
            except Exception as e:
                return {"ok": False, "message": tr("Lecture impossible : {error}", error=e)}
            return {"ok": True, "text": words}
        if z.get("read") == "gauge":
            times, _ = ix.frames()
            if not len(times):
                return {"ok": False, "message": tr("Le rush n'est pas encore lu.")}
            side = z.get("side") or "left"
            sample = [ix.picture(k) for k in range(0, len(times), max(1, len(times) // 60))]
            tight = zones.snap(sample, box, side)
            now = ix.picture(ix.frame_at(float(z["t"])))
            n = None
            profiles = [zones._profile(zones._crop(pic, tight), side) for pic in sample + [now]]
            n = min(len(q) for q in profiles)
            raw = zones.read(__import__("numpy").stack([q[:n] for q in profiles]))
            full = max(float(__import__("numpy").percentile(raw[:-1], 95)), 0.5)
            return {"ok": True, "fill": round(min(1.0, float(raw[-1]) / full), 3), "box": tight}
        return {"ok": True}

    def moments_zone(self, z: dict) -> dict:
        """A box drawn on the video becomes a condition of a kind (existing `kind`, or a new one named
        `name`): read gauge (below / drop), text (words) or look (as it is at t); negate: the opposite."""
        import re as _re
        from .moments.rules import MomentType
        proj = self._mo_project()
        if not proj:
            return {"ok": False, "message": tr("Déposez d'abord les rushs.")}
        box = [round(max(0.0, min(1.0, float(v))), 4) for v in z["box"]]
        if box[2] < 0.003 or box[3] < 0.003:
            return {"ok": False, "message": tr("Tracez une zone un peu plus grande.")}
        read = z.get("read")
        if read == "text":
            words = [w.strip().upper() for w in _re.split(r"[,;\n]", z.get("words") or "") if w.strip()]
            if not words:
                return {"ok": False, "message": tr("Écrivez au moins un mot à chercher.")}
            sig = {"text": words, "zone": box, "window": 10 if z.get("negate") else 4}
        elif read == "gauge":
            side = z.get("side") or "left"
            sig = {"zone": box, "side": side, "drop": 0.1, "within": 2} if z.get("drop") else \
                {"zone": box, "side": side, "below": round(float(z.get("below", 0.3)), 2)}
        elif read == "look":
            sig = {"zone": box, "look": {"rush": z["rush"], "t": round(float(z["t"]), 2)}, "z": 3.0}
        else:
            return {"ok": False, "message": tr("Choisissez ce que contient la zone.")}
        if z.get("negate"):
            sig = {"opposite": sig}
        kind = next((t for t in proj.types if t.id == z.get("kind")), None)
        if kind is None:
            name = (z.get("name") or "").strip()
            if not name:
                return {"ok": False, "message": tr("Donnez un nom à ce type de moment.")}
            slug = _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "moment"
            ids = {t.id for t in proj.types}
            kid, n = f"u-{slug}", 2
            while kid in ids:
                kid, n = f"u-{slug}-{n}", n + 1
            used = {t.color for t in proj.types}
            colour = next((c for c in self.MO_COLOURS if c not in used), self.MO_COLOURS[len(proj.types) % len(self.MO_COLOURS)])
            event = read == "gauge" and z.get("drop")
            kind = MomentType(kid, name, color=colour, mode="event" if event else "state", combine="all",
                              signals=[sig], before=8 if event else 1, after=4 if event else 1, gap=6, min_len=1, user=True)
            proj.types.append(kind)
        elif kind.combine == "any" and len(kind.signals) > 1:
            kind.signals, kind.combine = [{"any": kind.signals}, sig], "all"     # the new box is a condition: and
        else:
            if kind.combine == "any":
                kind.combine = "all"
            kind.signals.append(sig)
        kind.enabled = True
        proj.save()
        self._save()
        if not self._job.running:
            self.run("moments")
        return {"ok": True, "kind": kind.id, "message": tr("{name} : zone ajoutée, recherche relancée.", name=tr(kind.name))}

    def moments_unzone(self, kind_id: str, index: int) -> dict:
        """Remove the index-th zone condition of a kind (as listed in moments_view's zones)."""
        from .moments.rules import describe
        proj = self._mo_project()
        kind = next((t for t in proj.types if t.id == kind_id), None) if proj else None
        if kind:
            zoned = [k for k, sg in enumerate(kind.signals) if describe(sg)]
            if 0 <= index < len(zoned):
                del kind.signals[zoned[index]]
                proj.save()
        return self.moments_view()

    @staticmethod
    def _mo_phrases(query: str) -> list[str]:
        import re as _re
        return [p.strip() for p in _re.split(r"[,;\n]", query or "") if p.strip()]

    def moments_said(self, query: str) -> dict:
        """Where the words are said in each rush: {total, unread, rushes: [{path, name, done, hits}]};
        several phrases separated by commas are searched together."""
        from .moments import speech
        phrases = self._mo_phrases(query)
        out = {"ok": True, "query": query, "total": 0, "unread": 0, "rushes": []}
        for f in self._mo_files():
            ix = _moments_index(str(f))
            done = speech.done(ix)
            hits = sorted((h for p in phrases for h in speech.search(ix, p)), key=lambda h: h["start"]) if done else []
            out["rushes"].append({"path": str(f), "name": f.name, "done": done, "hits": hits[:300]})
            out["total"] += len(hits)
            out["unread"] += not done
        return out

    def moments_said_kind(self, query: str, name: str = "") -> dict:
        """A kind of moment made of words said ({"said": [...]}), named `name` (or after the words);
        the search runs again at once."""
        import re as _re
        from .moments.rules import MomentType
        proj = self._mo_project()
        if not proj:
            return {"ok": False, "message": tr("Déposez d'abord les rushs.")}
        phrases = self._mo_phrases(query)
        if not phrases:
            return {"ok": False, "message": tr("Écrivez ce qui est dit.")}
        name = (name or "").strip() or phrases[0][:1].upper() + phrases[0][1:] + ("…" if len(phrases) > 1 else "")
        kind = next((t for t in proj.types if t.signals == [{"said": phrases, "window": 3}]), None)
        if kind is None:
            slug = _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "dit"
            ids = {t.id for t in proj.types}
            kid, n = f"u-{slug}", 2
            while kid in ids:
                kid, n = f"u-{slug}-{n}", n + 1
            used = {t.color for t in proj.types}
            colour = next((c for c in self.MO_COLOURS if c not in used), self.MO_COLOURS[len(proj.types) % len(self.MO_COLOURS)])
            kind = MomentType(kid, name, color=colour, mode="event", combine="all",
                              signals=[{"said": phrases, "window": 3}], before=8, after=6, gap=3, min_len=1, user=True)
            # gap 3: each time the words are said is its own event (a wider gap would fold a second
            # mention into the first, whose margins end before it); events that overlap still make one
            proj.types.append(kind)
        kind.enabled = True
        proj.save()
        self._save()
        if not self._job.running:
            self.run("moments")
        return {"ok": True, "kind": kind.id, **{k: v for k, v in self.moments_said(query).items() if k != "ok"},
                "message": tr("{name} : nouveau type de moment, recherche relancée.", name=kind.name)}

    def moments_mark(self, i: int, kept) -> dict:
        """✓ (True), ✗ (False) or neither (None) on moment number i."""
        proj = self._mo_project()
        if proj and 0 <= i < len(proj.moments):
            proj.moments[i].kept = kept
            proj.save()
        return {"ok": True}

    # game packs (moments/packs.py): what was taught here, in a file friends use on their own rushes
    PACK_TYPES = ("Pack de moments (*.fauxpack.json)",)

    def _mo_game(self, proj) -> str:
        """The game the kinds are for: the preset's name (or the imported pack's game)."""
        from .moments.rules import presets
        p = next((p for p in presets() if p["id"] == (proj.preset or self._mo().get("preset"))), None)
        return (p.get("game") or p["name"]) if p else ""

    def moments_pack_export(self, name: str = "", kinds=None, path: str = "") -> dict:
        """« Partager… »: kinds (ids; default: the enabled ones made, tuned or ✓ / ✗-taught here) saved as a
        .fauxpack.json (path, or the app's « Save as » in the project folder)."""
        from .moments import packs
        proj = self._mo_project()
        if not proj:
            return {"ok": False, "message": tr("Déposez d'abord les rushs.")}
        chosen = [t for t in proj.types if t.id in kinds] if kinds else \
            [t for t in proj.types if t.enabled and packs.changed(t, proj.preset, proj.moments)]
        if not chosen:
            return {"ok": False, "message": tr("Rien à partager : apprenez d'abord un type de moment (exemple, ✓ / ✗ ou zone).")}
        game = self._mo_game(proj)
        suggested = (name or "").strip() or " – ".join(x for x in (tr(game), proj.path.parent.name) if x)
        if not path:
            fname = re.sub(r'[\\/:*?"<>|]+', " ", suggested).strip() or "moments"
            path = self._save_dialog(proj.path.parent / f"{fname}{packs.SUFFIX}",
                                     tuple(tr(x) for x in self.PACK_TYPES))
            if not path:
                return {"ok": False, "cancel": True}
        out = Path(path)
        pack_name = (name or "").strip() or out.name.removesuffix(packs.SUFFIX).removesuffix(".json")
        try:
            r = packs.export(proj, chosen, out, name=pack_name, game=game,
                             about=", ".join(tr(t.name) for t in chosen))
        except OSError as e:
            return {"ok": False, "message": tr("Écriture impossible : {error}", error=e)}
        msg = tr("Pack enregistré : {name} ({n} types, {size} ko). Vos amis l'importent sur leurs propres rushs.",
                 name=Path(r["path"]).name, n=len(r["kinds"]), size=max(1, round(r["bytes"] / 1000)))
        if r["skipped"]:
            msg += " " + tr("Laissés de côté (rushs pas encore lus) : {names}.", names=", ".join(tr(n) for n in r["skipped"]))
        return {"ok": bool(r["kinds"]), "path": r["path"], "message": msg}

    def _mo_pack_add(self, path: Path) -> tuple[bool, str]:
        """Import a pack: its kinds are added to the project's (renamed when they clash), or, with no rush
        yet, it becomes the preset."""
        from .moments import packs
        try:
            pid = packs.import_pack(path)
        except packs.PackError as e:
            return False, tr(str(e))
        m, proj = self._mo(), self._mo_project()
        if not proj:
            m["preset"] = pid
            self._save()
            return True, tr("Pack ajouté aux préréglages et choisi : déposez vos rushs.")
        res = packs.add_to(proj, pid)
        if not res["added"]:
            return True, tr("« {name} » est déjà là : rien à ajouter.", name=res["name"])
        new = proj.types[-len(res["added"]):]
        used = {t.color for t in proj.types[: -len(new)]}
        for k in new:                                          # its own colour on the board
            if k.color in used:
                k.color = next((c for c in self.MO_COLOURS if c not in used), k.color)
            used.add(k.color)
        proj.save()
        m["kinds"] = m.get("kinds", 0) + 1                    # the page reloads its kinds
        self._save()
        msg = tr("1 type ajouté depuis « {name} »", name=res["name"]) if len(res["added"]) == 1 else \
            tr("{n} types ajoutés depuis « {name} »", n=len(res["added"]), name=res["name"])
        if res["renamed"]:
            msg += " " + tr("(renommés : {names})", names=", ".join(res["renamed"]))
        return True, msg + ". " + tr("Lancez la recherche.")

    def moments_pack_import(self, path: str = "") -> dict:
        """« Importer… »: a .fauxpack.json (path, or an open dialog); its kinds are added to the current ones."""
        if not path:
            import webview
            picked = self._window.create_file_dialog(
                webview.FileDialog.OPEN, file_types=tuple(tr(x) for x in self.PACK_TYPES) + (tr("Tous les fichiers") + " (*.*)",))
            if not picked:
                return {"ok": False, "cancel": True}
            path = picked if isinstance(picked, str) else picked[0]
        ok, msg = self._mo_pack_add(Path(path))
        return {"ok": ok, "message": msg, "view": self.moments_view()}

    def moments_input(self, path: str = "") -> dict:
        m = self._mo()
        m["rushes"] = [r for r in m.get("rushes") or [] if path and r != path]
        self._save()
        return self.view()

    def _mo_done(self, result: str) -> str:
        m = self._mo()
        m["runs"] = m.get("runs", 0) + 1                        # the page reloads when this changes
        self._save()
        return tr("{n} moments trouvés.", n=self._mo_summary()["found"])

    def _mo_xml_done(self, result: str) -> str:
        m = self._mo()
        m["xml"] = result.strip()
        m["runs"] = m.get("runs", 0) + 1
        self._save()
        return tr("XML : {name}", name=Path(result.strip()).name)

    def _mo_speech_done(self, result: str) -> str:
        from .moments import speech
        m = self._mo()
        m["runs"] = m.get("runs", 0) + 1
        self._save()
        n = sum(speech.status(_moments_index(str(f)))["words"] for f in self._mo_files())
        return tr("Ce qui est dit est lu : {n} mots.", n=n)

    # interface language
    def i18n(self) -> dict:
        from .i18n import NAMES, catalog, ui_lang
        lang = ui_lang()
        return {"lang": lang, "dict": catalog(lang), "names": NAMES}

    def set_ui_lang(self, lang: str) -> None:
        """Saved in app.json (read by every page and job), then the open pages reload in that language."""
        from .i18n import NAMES
        if lang not in NAMES:
            return
        self._state["ui_lang"] = lang
        self._save()
        self._checks = self._ai = None          # their texts come from Python: checked again in the new language
        threading.Thread(target=self.check, daemon=True).start()
        threading.Thread(target=self.ai_check, daemon=True).start()
        for win in (self._window, self._sheet_window[0] if self._sheet_window else None,
                    getattr(self, "_sb_window", None), getattr(self, "_board_window", None)):
            if win:
                try:
                    win.evaluate_js("location.reload()")
                except Exception:
                    pass

    def init(self) -> dict:
        self._title()
        return self.view()

    def poll(self) -> dict:
        """Cheap refresh while the contact sheet or the storyboard is open in the browser."""
        return {"sources": self._sources(), "storyboard": self._storyboard(), "sfx": self._sfx(), "panel": self._panel()}

    # AI engines
    def ai_check(self) -> list[dict]:
        """Which engines are installed and signed in (a few seconds: the CLIs are asked)."""
        from concurrent.futures import ThreadPoolExecutor

        from .sourcing import llm
        with ThreadPoolExecutor(len(llm.ENGINES)) as ex:
            self._ai = list(ex.map(llm.status, llm.ENGINES))
        self._emit({"type": "ai", "ai": self._ai})
        return self._ai

    def ai_connect(self, engine: str) -> dict:
        from .sourcing import llm
        try:
            msg = llm.connect(engine)
        except Exception as e:
            return {"ok": False, "message": tr("{engine} : {error}", engine=llm.label(engine), error=e)}
        return {"ok": True, "message": msg}

    def ai_test(self, engine: str) -> dict:
        from .sourcing import llm
        llm.set_quality("fast")
        try:
            answer = llm.test(engine)
            ok, msg = True, tr("{engine} répond et voit les images (« {answer} »).", engine=llm.label(engine), answer=answer)
        except Exception as e:
            ok, msg = False, tr("{engine} : {error}", engine=llm.label(engine), error=f"{type(e).__name__} : {str(e)[:200]}")
        finally:
            llm.set_quality(self._state["opts"].get("quality", "best"))
        self.ai_check()
        return {"ok": ok, "message": msg}

    def ai_install(self, engine: str) -> dict:
        if self._job.running:
            return {"ok": False, "message": tr("Une étape tourne déjà.")}
        self._job.start("setup", ["fauxraccord.setup", "install", "ai", engine],
                        lambda r: (self.ai_check(), tr("Installé : cliquez « Connecter »."))[1])
        return {"ok": True}

    # inputs
    def add(self, zone: str, paths: list[str]) -> dict:
        s = self._state
        notes = []
        if zone == "project":            # dropped on the project button: open that folder
            if self._job.running:
                return {"view": self.view(), "notes": [tr("Une étape tourne : attendez la fin ou arrêtez-la.")]}
            p = Path(paths[0]) if paths else None
            if p and p.exists():
                self._switch(p if p.is_dir() else p.parent)
                self._save()
                notes.append(tr("Projet : {name}", name=Path(s["project"]).name))
            return {"view": self.view(), "notes": notes}
        for raw in paths:
            p = Path(raw)
            ext = p.suffix.lower()
            if zone in ("beat", "beat-music", "beat-rushes"):       # Outils › Au rythme
                b = self._beat()
                if p.is_file() and ext in BEAT_AUDIO:
                    self._beat_music(p)
                    notes.append(tr("Musique : {name}", name=p.name))
                elif p.is_dir() or (p.is_file() and (ext in BEAT_VIDEO or ext == ".xml")):
                    if str(p) not in (b.get("rushes") or []):
                        b["rushes"] = [*(b.get("rushes") or []), str(p)]
                    notes.append(tr("Rushs : {name}", name=p.name))
                else:
                    notes.append(tr("Ignoré : {name}", name=p.name))
                continue
            if zone in ("moments", "moments-rushes"):                # Outils › Moments
                m = self._mo()
                if p.is_file() and p.name.lower().endswith(".fauxpack.json"):      # a friend's game pack
                    notes.append(self._mo_pack_add(p)[1])
                elif p.is_dir() or (p.is_file() and ext in BEAT_VIDEO):
                    if str(p) not in (m.get("rushes") or []):
                        m["rushes"] = [*(m.get("rushes") or []), str(p)]
                    notes.append(tr("Rushs : {name}", name=p.name))
                else:
                    notes.append(tr("Ignoré : {name}", name=p.name))
                continue
            if p.is_file() and ext in SCRIPT_EXT:
                # the script decides the project: its folder is where every step writes
                folder = p.parent
                if (not s["project"] or not project.inside(folder, Path(s["project"]))) and not self._job.running:
                    self._switch(folder, carry=not s["script"])
                    notes.append(tr("Projet : {name}", name=folder.name))
                s["script"] = str(p)
                notes.append(tr("Script : {name}", name=p.name))
                continue
            if p.is_file() and ext == ".xml":
                if zone in ("sources", "storyboard", "sfx", "sfx-src", "montage"):
                    s["place_xml"] = str(p)
                    notes.append(tr("Montage : {name}", name=p.name))
                else:
                    s["xml"], s["sequence"], s["keep"], s["mode"] = str(p), "", None, "continue"
                    notes.append(tr("Séquence pour le derush : {name}", name=p.name))
                    if zone != "derush":
                        s["step"] = "derush"
            elif p.is_dir() and zone == "sfx-src":
                self.sfx_folder(str(p))
                notes.append(tr("Dossier de sons : {name}", name=p.name))
            elif p.is_file() and ext in IMAGE_EXT and zone == "storyboard":
                if str(p) not in s["sb_refs"]:
                    s["sb_refs"].append(str(p))
                notes.append(tr("Référence de style : {name}", name=p.name))
            elif p.is_dir() or (p.is_file() and ext in MEDIA_EXT):
                if str(p) not in s["rushes"]:
                    s["rushes"].append(str(p))
                if zone != "sync":
                    s["step"] = "sync"
                notes.append(tr("Rush : {name}", name=p.name))
            else:
                notes.append(tr("Ignoré : {name}", name=p.name))
        if s["xml"] and s["sequence"] and s["sequence"] not in self._sequences():
            s["sequence"] = ""
        self._save()
        return {"view": self.view(), "notes": notes}

    def pick(self, zone: str, folder: bool = False) -> dict | None:
        import webview
        types = {"sync": (tr("Rushs") + " (*.mp4;*.mov;*.mxf;*.mkv;*.wav;*.bwf;*.aif;*.aiff;*.flac;*.mp3;*.m4a)",),
                 "derush": (tr("Séquence Premiere") + " (*.xml)",),
                 "sources": (tr("Derush ou montage") + " (*.xml)",),
                 "montage": (tr("Derush ou montage") + " (*.xml)",),
                 "script": (tr("Script") + " (*.md;*.txt;*.docx)",),
                 "storyboard": (tr("Images de référence") + " (*.jpg;*.jpeg;*.png;*.webp)",),
                 "sfx": (tr("Montage Premiere") + " (*.xml)",),
                 "beat-music": (tr("Musique") + " (*.mp3;*.wav;*.m4a;*.flac;*.aif;*.aiff;*.ogg)",),
                 "beat-rushes": (tr("Rushs ou séquence Premiere") + " (*.mp4;*.mov;*.mxf;*.mkv;*.avi;*.mts;*.xml)",),
                 "moments-rushes": (tr("Rushs") + " (*.mp4;*.mov;*.mxf;*.mkv;*.avi;*.mts;*.webm)",)}.get(zone, ())
        if folder:
            paths = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        else:
            paths = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=zone in ("sync", "storyboard", "beat-rushes", "moments-rushes"),
                                                   file_types=types + (tr("Tous les fichiers") + " (*.*)",))
        if not paths:
            return None
        return self.add(zone, list(paths) if not isinstance(paths, str) else [paths])

    def remove(self, key: str, value: str = "") -> dict:
        s = self._state
        if key in ("rushes", "sb_refs"):
            s[key] = [r for r in s[key] if r != value] if value else []
        else:
            s[key] = ""
            if key == "xml":
                s["sequence"], s["keep"] = "", None
        self._save()
        return self.view()

    def set(self, key: str, value) -> dict:
        if key.startswith("opts."):
            self._state["opts"][key[5:]] = value
        else:
            self._state[key] = value
        if key == "xml":   # a new sequence: its own scan decides
            self._state.update(sequence="", keep=None, mode="continue")
        self._save()
        return self.view()

    def set_key(self, name: str, value: str) -> dict:
        """Check an API key with its service, then save it (empty: forget it)."""
        from .sourcing import llm
        value = (value or "").strip()
        if name == "epidemic":
            if value:
                try:
                    from .sfx.library import Epidemic
                    Epidemic(value).search("whoosh", "whoosh", n=1)
                except Exception as e:
                    return {"ok": False, "message": tr("{engine} : {error}", engine="Epidemic Sound", error=e),
                            "view": self.view()}
            llm.save_key(name, value)
            return {"ok": True, "message": tr("Clé Epidemic enregistrée.") if value else tr("Clé Epidemic oubliée."),
                    "view": self.view()}
        if name != "gemini":
            return {"ok": False, "message": tr("Clé inconnue.")}
        if value:
            err = llm.check_gemini(value)
            if err:
                return {"ok": False, "message": tr("{engine} : {error}", engine="Gemini", error=err), "view": self.view()}
        llm.save_key(name, value)
        threading.Thread(target=self.ai_check, daemon=True).start()
        return {"ok": True, "message": tr("Clé Gemini enregistrée.") if value else tr("Clé Gemini oubliée."),
                "view": self.view()}

    # jobs
    def run(self, step: str) -> dict:
        s, o = self._state, self._state["opts"]
        if self._job.running:
            return {"ok": False, "message": tr("Une étape tourne déjà.")}
        if step == "sync":
            if not s["rushes"]:
                return {"ok": False, "message": tr("Déposez d'abord les rushs.")}
            args = ["fauxraccord", *s["rushes"], "--model", o["model"], *self._out_arg()]
            self._job.start("sync", args, lambda r: self._sync_done(self._deliver("sync", r)))
        elif step == "derush":
            if not s["xml"]:
                return {"ok": False, "message": tr("Déposez d'abord une séquence (.xml).")}
            if not s["script"]:
                return {"ok": False, "message": tr("Le derush a besoin du script.")}
            keep = "0"
            if s["mode"] == "continue":
                keep = str(s["keep"]) if s["keep"] is not None else "auto"
            args = ["fauxraccord", s["xml"], s["script"], "--model", o["model"], "--max-pause", str(o["max_pause"]),
                    "--pad-in", str(o["pad_in"]), "--pad-out", str(o["pad_out"]), "--keep-until", keep,
                    "--language", o.get("lang", "auto"), *self._out_arg()]
            if s["sequence"]:
                args += ["--sequence", s["sequence"]]
            self._job.start("derush", args, lambda r: self._derush_done(self._deliver("derush", r)))
        elif step == "collect":
            if not s["script"]:
                return {"ok": False, "message": tr("Déposez d'abord le script.")}
            args = ["fauxraccord.sourcing", "collect", s["script"], "--llm", o["llm"], "--quality", o.get("quality", "best"),
                    "--segment", str(o["segment"]),
                    "--full-video-max", str(float(o["full_max"]) * 60), "--shot-height", str(o["shot_height"])]
            args += [flag for flag, on in (("--no-shots", o["shots"]), ("--no-search", o["search"]),
                                           ("--no-web", o["web"]), ("--no-videos", o["videos"]),
                                           ("--no-judge", o.get("judge", True))) if not on]
            if (o.get("brief") or "").strip():
                args += ["--brief", o["brief"].strip()]
            self._job.start("collect", args, self._collect_done)
        elif step == "place":
            out = self._sources_out()
            if not out or not (out / "selection.json").exists():
                return {"ok": False, "message": tr("Choisissez d'abord des images dans la planche.")}
            if not s["place_xml"]:
                return {"ok": False, "message": tr("Déposez la séquence où placer les images (.xml).")}
            derush, edit = self._place_inputs()
            args = ["fauxraccord.sourcing", "export", str(out), "--model", o["model"]]
            if derush:
                args += ["--derush", str(derush)]
            if edit:
                args += ["--edit", str(edit)]
            if o.get("auto_fill", True):
                args += ["--auto"]
            self._job.start("place", args, lambda r: self._place_done(self._deliver("sources", r)))
        elif step == "fetch":           # before the panel places: the files it will import
            out = self._sources_out()
            if not out or not (out / "manifest.json").exists():
                return {"ok": False, "message": tr("Collectez d'abord.")}
            args = ["fauxraccord.sourcing", "fetch", str(out)] + (["--auto"] if o.get("auto_fill", True) else [])
            self._job.start("fetch", args, lambda r: self._ask_panel("sources"))
        elif step == "sb_place":        # the storyboard's XML again, on the current edit
            out = self._sb_out()
            if not out or not (out / "storyboard.json").exists():
                return {"ok": False, "message": tr("Créez d'abord les plans.")}
            derush, edit = self._place_inputs()
            derush = derush or (Path(s["derush_out"]) if s["derush_out"] else None)
            args = ["fauxraccord.storyboard", "place", str(out)]
            if derush:
                args += ["--derush", str(derush)]
            if edit:
                args += ["--edit", str(edit)]
            self._job.start("sb_place", args, lambda r: self._xml_done(self._deliver("storyboard", r)))
        elif step == "sfx_place":
            out = self._sfx_out()
            if not out or not (out / "cues.json").exists():
                return {"ok": False, "message": tr("Analysez d'abord le montage.")}
            self._job.start("sfx_place", ["fauxraccord.sfx", "place", str(out)],
                            lambda r: self._xml_done(self._deliver("sfx", r)))
        elif step == "sfx_suggest":
            ctx, out = self._board_context(), self._sfx_out()
            if not s["script"] or not out:
                return {"ok": False, "message": tr("Les propositions ont besoin du script.")}
            args = ["fauxraccord.sfx", "suggest", "--script", s["script"], "--out", str(out), "--brief",
                    (o.get("sfx_brief") or "").strip(), "--engine", ctx["engine"], "--quality", ctx["quality"]]
            if ctx["derush"]:
                args += ["--derush", ctx["derush"]]
            if ctx["edit"]:
                args += ["--edit", ctx["edit"]]
            self._job.start("sfx_suggest", args, self._suggest_done)
        elif step == "sfx":
            edit, out = self._sfx_edit(), self._sfx_out()
            if not edit:
                return {"ok": False, "message": tr("Déposez d'abord le montage (.xml).")}
            src = o.get("sfx_sources") or {}
            order = [k for k in ("folder", "epidemic", "earshot") if src.get(k, True)] or ["earshot"]
            args = ["fauxraccord.sfx", "plan", edit, "--out", str(out), "--title", Path(s["script"] or edit).stem,
                    "--density", str(o.get("sfx_density") or 2), "--sources", ",".join(order), "--keep-edits"]
            for f in o.get("sfx_folders") or []:
                args += ["--folder", f]
            self._job.start("sfx", args, self._sfx_done)
        elif step == "moments":
            pf, files = self._mo_file(), self._mo_files()
            if not files:
                return {"ok": False, "message": tr("Déposez d'abord les rushs.")}
            from .moments import Project
            proj = Project(pf)
            if not proj.types:
                proj.use_preset(self._mo().get("preset") or "rust")
            proj.rushes = [str(f) for f in files]
            proj.save()
            self._mo()["file"] = str(pf)
            self._save()
            self._job.start("moments", ["fauxraccord.moments", "find", str(pf)], self._mo_done)
        elif step == "moments_speech":                         # what is said in the rushes (whisper, once)
            pf, files = self._mo_file(), self._mo_files()
            if not files:
                return {"ok": False, "message": tr("Déposez d'abord les rushs.")}
            from .moments import Project
            proj = Project(pf)
            if not proj.types:
                proj.use_preset(self._mo().get("preset") or "rust")
            proj.rushes = [str(f) for f in files]
            proj.save()
            self._mo()["file"] = str(pf)
            self._save()
            self._job.start("moments_speech", ["fauxraccord.moments", "speech", str(pf), "--model", o["model"],
                                               "--language", o.get("lang", "auto")], self._mo_speech_done)
        elif step == "moments_xml":
            pf = self._mo_file()
            if not pf or not pf.exists():
                return {"ok": False, "message": tr("Cherchez d'abord les moments.")}
            self._job.start("moments_xml", ["fauxraccord.moments", "xml", str(pf)],
                            lambda r: self._mo_xml_done(self._deliver("moments", r)))
        elif step == "storyboard":
            if not s["script"]:
                return {"ok": False, "message": tr("Déposez d'abord le script.")}
            args = ["fauxraccord.storyboard", "make", s["script"], "--llm", o["llm"], "--quality", o.get("quality", "best"),
                    "--pace", str(o.get("sb_pace") or 6), "--style", (o.get("sb_style") or "").strip()]
            for r in s["sb_refs"]:
                args += ["--ref", r]
            derush, edit = self._place_inputs()
            derush = derush or (Path(s["derush_out"]) if s["derush_out"] else None)
            if derush:
                args += ["--derush", str(derush)]
            if edit:
                args += ["--edit", str(edit)]
            self._job.start("storyboard", args, self._storyboard_done)
        return {"ok": True}

    # « Placer dans Premiere »: the panel, open in Premiere, picks the request up (sourcing/bridge.py)
    def premiere(self, kind: str) -> dict:
        """Illustrations: their files are downloaded first (a job), then the panel is asked. Storyboard: at once.
        Without the panel (or with an old one, which cannot take requests) the page shows how to install it."""
        pan = self._panel()
        if kind in ("sources", "storyboard") and not pan["live"] and not (pan["installed"] and pan["current"]):
            self._emit({"type": "panel-guide", "kind": kind})
            return {"ok": False, "guide": True,
                    "message": tr("Il faut le panneau FauxRaccord dans Premiere : la fenêtre FauxRaccord montre comment l'installer.")}
        if kind == "sources":
            r = self.run("fetch")
            return {**r, "waiting": "job"} if r.get("ok") else r
        if kind == "storyboard":
            out = self._sb_out()
            if not out or not (out / "storyboard.json").exists():
                return {"ok": False, "message": tr("Créez d'abord les plans.")}
            rid = self._ask_panel("storyboard", announce=False)
            self._emit({"type": "premiere", "id": rid, "kind": "storyboard"})
            return {"ok": True, "id": rid}
        return {"ok": False, "message": tr("Le panneau Premiere ne place pas encore les sons : exportez le XML.")}

    def _ask_panel(self, kind: str, announce: bool = True):
        from .sourcing import bridge
        rid = bridge.request(kind)
        if announce:         # after a job: the page starts following the request
            self._emit({"type": "premiere", "id": rid, "kind": kind})
            return tr("Fichiers prêts : le panneau FauxRaccord de Premiere les place.")
        return rid

    def premiere_state(self, rid: int) -> dict:
        from .sourcing import bridge
        return bridge.request_state(int(rid))

    def _xml_done(self, result: str) -> str:
        if result:
            self.reveal(result)
        return tr("{name} écrit : Premiere › Fichier › Importer.", name=Path(result).name) if result else ""

    def _suggest_done(self, result: str) -> str:
        self.open_board("amb")
        return tr("Propositions prêtes : la planche sonore s'ouvre.")

    def _out_arg(self) -> list[str]:
        """Sync and derush write into the project folder (without one: next to their input)."""
        return ["--out", self._state["project"]] if self._state["project"] else []

    def _place_done(self, result: str) -> str:
        if result:
            self._state["broll_out"] = result
            self._save()
            self._push()
        return tr("Placé : importez « {name} » dans Premiere (Fichier > Importer).", name=Path(result).name) if result else ""

    def _place_inputs(self) -> tuple[Path | None, Path | None]:
        """(derush, edit) for the placement. One sequence is given; when it is not FauxRaccord's own derush,
        that derush (if any) still helps: its Sxxx markers find the sentences without listening."""
        s = self._state
        target = Path(s["place_xml"]) if s["place_xml"] else None
        if not target:
            return None, None
        if target.name.lower().endswith(".fauxraccord.xml"):
            return target, None
        return (Path(s["derush_out"]) if s["derush_out"] else None), target

    def stop(self) -> None:
        self._job.stop()

    # installation page
    def check(self) -> list[dict]:
        """What this computer has and lacks (a few seconds: run off the page's thread by pywebview)."""
        from .setup import check_all
        self._checks = check_all()
        self._emit({"type": "checks", "checks": self._checks})
        return self._checks

    def install(self, item: str, here: bool = False) -> dict:
        """here: started from a step page (the panel's guide): the progress stays on that page."""
        if self._job.running:
            return {"ok": False, "message": tr("Une étape tourne déjà.")}
        what, _, arg = item.partition(":")
        if what == "update":      # the new installer waits for this window to close, then opens it again
            done = lambda r: (threading.Timer(1.0, self._window.destroy).start(),       # noqa: E731
                              tr("Mise à jour : FauxRaccord se rouvre dans un instant."))[1]
        elif what == "panel":
            def done(r):
                self._panel_cache = None
                self.check()
                self._push()
                return tr("Panneau installé. Dans Premiere : Fenêtre › Extensions UXP › FauxRaccord "
                          "(redémarrez Premiere s'il était ouvert).")
        else:
            done = lambda r: (self.check(), tr("Installé."))[1]                      # noqa: E731
        self._job.start("panel" if what == "panel" and here else "setup",
                        ["fauxraccord.setup", "install", what, *([arg] if arg else [])], done)
        return {"ok": True}

    def open_url(self, url: str) -> None:
        import webbrowser
        if url.startswith("https://"):
            webbrowser.open(url)

    def _sync_done(self, result: str) -> str:
        s = self._state
        if result:
            s["sync_out"] = result
            s["xml"], s["sequence"], s["keep"], s["mode"] = result, "", None, "all"
        self._save()
        self._push()
        if s["chain"] and s["script"] and result:
            threading.Timer(0.3, lambda: (self.set("step", "derush"), self._push(), self.run("derush"),
                                          self._push())).start()
            return tr("{name} écrit. Le derush enchaîne…", name=Path(result).name)
        return tr("{name} écrit : à importer dans Premiere (Fichier > Importer).", name=Path(result).name)

    def _derush_done(self, result: str) -> str:
        if result:
            if self._state["place_xml"] in ("", self._state["derush_out"]):
                self._state["place_xml"] = result
            self._state["derush_out"] = result
        self._save()
        self._push()
        report = Path(result).with_suffix(".txt") if result else None
        summary = ""
        if report and report.exists():
            lines = [ln for ln in report.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
            summary = next((ln for ln in lines if ln.startswith("Source ")), "")
        return tr("{name} écrit. {summary}", name=Path(result).name, summary=summary).strip()

    def _sfx_done(self, result: str) -> str:
        self._push()
        self.open_sfx()
        info = self._sfx()
        return tr("{n} sons proposés : la planche sonore s'ouvre sur « Sur le montage ».", n=info["cues"])

    def _storyboard_done(self, result: str) -> str:
        self._push()
        self.open_storyboard()
        return tr("Plans prêts : la planche du storyboard s'ouvre.")

    def open_storyboard(self) -> dict:
        """The storyboard's planche in its own FauxRaccord window: cards can be dragged into Premiere."""
        out = self._sb_out()
        if not out or not (out / "storyboard.json").exists():
            return {"ok": False, "message": tr("Créez d'abord les plans.")}
        import webview

        from .storyboard import StoryboardApi, serve
        if self._sb_server:
            self._sb_server.shutdown()
        self._sb_server, url = serve(out, lambda: self._state["opts"].get("llm", "auto"), open_browser=False)
        win = getattr(self, "_sb_window", None)
        if win is not None:
            try:
                self._sb_api.out = out
                win.load_url(url)
                win.restore()
                win.show()
                return {"ok": True}
            except Exception:
                self._sb_window = None
        api = StoryboardApi(out, place=lambda: self.premiere("storyboard"), export=lambda: self.run("sb_place"))
        win = webview.create_window(tr("Planche · Storyboard"), url, js_api=api, width=1400, height=950,
                                    min_size=(640, 420), text_select=True)
        api.window = win
        self._sb_api, self._sb_window = api, win

        def closed():
            self._sb_window = None
        win.events.closed += closed
        return {"ok": True}

    def _collect_done(self, result: str) -> str:
        self._push()
        self.open_sheet()
        return tr("Collecte terminée : la planche s'ouvre dans sa fenêtre.")

    # files
    def open_path(self, path: str) -> None:
        if path and Path(path).exists():
            os.startfile(path)

    def reveal(self, path: str) -> None:
        if path and Path(path).exists():
            subprocess.Popen(["explorer", "/select,", str(Path(path))])

    def open_sheet(self) -> dict:
        out = self._sources_out()
        if not out or not (out / "manifest.json").exists():
            return {"ok": False, "message": tr("Collectez d'abord.")}
        from .sourcing.sheet import serve
        if self._sheet:
            self._sheet.shutdown()
        self._sheet, url = serve(out, open_browser=False)
        self._sheet_window_open(out, url)
        return {"ok": True}

    def _sheet_window_open(self, out: Path, url: str) -> None:
        """The planche in its own FauxRaccord window (not the browser): cards can be dragged into Premiere."""
        import webview

        from .sourcing.drag import Dragger, SheetApi
        dragger = Dragger(out)
        place = lambda: self.premiere("sources")      # noqa: E731
        if self._sheet_window is not None:
            win, api = self._sheet_window
            try:      # same window, new server / collection
                dragger.window = win
                api._d = dragger
                win.load_url(url)
                win.restore()
                win.show()
                return
            except Exception:
                self._sheet_window = None
        api = SheetApi(dragger, place=place)
        win = webview.create_window(tr("Planche"), url, js_api=api, width=1500, height=950, min_size=(600, 400),
                                    text_select=True)
        dragger.window = win
        self._sheet_window = (win, api)

        def closed():
            self._sheet_window = None
        win.events.closed += closed

    def report(self) -> None:
        r = self._state["derush_out"]
        if r:
            txt = Path(r).with_suffix(".txt")       # X.fauxraccord.xml -> X.fauxraccord.txt, or the name the user gave
            if txt.exists():
                os.startfile(txt)

    def tc(self, seconds: float) -> str:
        return _tc(seconds)


_MUTEX = None


def fresh_page_cache(storage: Path, web: Path = WEB) -> bool:
    """pywebview serves web/ from a local server on a fixed port, without cache headers: after an update the
    window would keep showing the old page and scripts from WebView2's cache. When web/ changed since the last
    start, that cache is emptied (only the cached files: settings and storage stay). True when it was."""
    import hashlib
    import shutil
    h = hashlib.sha1()
    for f in sorted(web.rglob("*")):
        if f.is_file():
            st = f.stat()
            h.update(f"{f.relative_to(web)}|{st.st_size}|{int(st.st_mtime)}".encode())
    stamp, now = storage / "web-stamp.txt", h.hexdigest()
    try:
        if stamp.read_text(encoding="utf-8").strip() == now:
            return False
    except OSError:
        pass
    for sub in ("Cache", "Code Cache"):
        shutil.rmtree(storage / "EBWebView" / "Default" / sub, ignore_errors=True)
    try:
        storage.mkdir(parents=True, exist_ok=True)
        stamp.write_text(now, encoding="utf-8")
    except OSError:
        pass
    return True


def _on_loaded(window, api: Api) -> None:
    """Dropped files: WebView2 only gives full paths to a Python-side drop handler."""
    from webview.dom import DOMEventHandler

    def on_drop(event):
        files = event.get("dataTransfer", {}).get("files", [])
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if not paths:
            return
        zone = window.evaluate_js("window.app ? app.dropZone() : 'sync'") or "sync"
        res = api.add(zone, paths)
        api._emit({"type": "added", **res})

    window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)


def _link_view(url: str) -> str:
    """fauxraccord://start (the Premiere panel starting FauxRaccord: in the background) -> 'start';
    fauxraccord://open/<view> -> that view; anything else -> 'main'."""
    from .sourcing.bridge import VIEWS
    rest = url.split("://", 1)[-1].strip("/").lower()
    if rest.startswith("start"):
        return "start"
    view = rest.split("/", 1)[1].split("?", 1)[0] if rest.startswith("open/") else ""
    return view if view in VIEWS else "main"


def _register_link() -> None:
    """fauxraccord:// opens this FauxRaccord (the Premiere panel uses it to start it). The installer writes
    the same key; done again here so a copy run from the sources, or moved, still answers."""
    exe = Path(sys.executable).parent / "fauxraccord-gui.exe"
    if not exe.exists():
        return
    command = f'"{exe}" "%1"'
    try:
        import winreg
        base = r"Software\Classes\fauxraccord"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command") as k:
                if winreg.QueryValueEx(k, "")[0] == command:
                    return
        except OSError:
            pass
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:FauxRaccord")
            winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, command)
    except OSError:
        pass


def _hwnd_of(win) -> int:
    """The Windows handle of a pywebview window of this process, found by its title (0 when not there yet)."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    title = getattr(win, "title", "") or ""
    pid, found, prefix = os.getpid(), [], []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(h, _l):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(h, buf, 512)
            if buf.value == title:
                found.append(h)
            elif title and buf.value.startswith(title):      # the main window: « FauxRaccord — <project> »
                prefix.append(h)
        return True
    user32.EnumWindows(each, 0)
    return (found or prefix or [0])[0]


def _front(win) -> None:
    """Bring a window to the front, even from behind Premiere. Plain Windows calls through ctypes, which let
    go of Python's lock while they wait: going through pywebview (.on_top, .restore) from this thread held
    the lock while the window thread needed it, and the whole window froze (2026-11-05)."""
    import ctypes
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_uint]
    for name in ("ShowWindow", "IsIconic", "BringWindowToTop", "SetForegroundWindow"):
        getattr(user32, name).argtypes = [wintypes.HWND] + ([ctypes.c_int] if name == "ShowWindow" else [])
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
    h = 0
    for _ in range(20):                  # a window just asked for takes a moment to exist
        h = _hwnd_of(win)
        if h:
            break
        time.sleep(0.15)
    if not h:
        return
    user32.ShowWindow(h, 9 if user32.IsIconic(h) else 5)          # SW_RESTORE / SW_SHOW
    # Windows gives the foreground only to the active app's input queue: borrow it for a moment
    fg = user32.GetForegroundWindow()
    them = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    me = kernel32.GetCurrentThreadId()
    joined = bool(them and them != me and user32.AttachThreadInput(me, them, True))
    try:
        user32.BringWindowToTop(h)
        user32.SetForegroundWindow(h)
        flags = 0x0001 | 0x0002 | 0x0040                               # NOSIZE | NOMOVE | SHOWWINDOW
        user32.SetWindowPos(h, wintypes.HWND(-1), 0, 0, 0, 0, flags)   # topmost, then back: on top of Premiere
        user32.SetWindowPos(h, wintypes.HWND(-2), 0, 0, 0, 0, flags)
    finally:
        if joined:
            user32.AttachThreadInput(me, them, False)


def _focus(api: "Api", window, view: str) -> None:
    """The Premiere panel's « Ouvrir » buttons, or FauxRaccord launched again: the window, on that page.
    A board already open only comes forward (not reloaded)."""
    log_event(f"focus {view}")
    current = {"sources": lambda: (api._sheet_window or (None,))[0],
               "storyboard": lambda: getattr(api, "_sb_window", None),
               "sons": lambda: getattr(api, "_board_window", None)}.get(view)
    if current:
        win = current()
        if win is None:
            r = {"sources": api.open_sheet, "storyboard": api.open_storyboard, "sons": api.open_board}[view]() or {}
            if not r.get("ok", True):
                api._emit({"type": "toast", "text": r.get("message") or r.get("error") or ""})
                return _front(window)
            win = current()
        if win is not None:
            return _front(win)
    elif view == "moments":
        api._emit({"type": "show", "step": "moments"})
    _front(window)


_FOCUS = {"lock": threading.Lock(), "next": None, "busy": False}


def _focus_soon(api: "Api", window, view: str) -> None:
    """One « Ouvrir » at a time: clicks that come while one is being done are merged (the last one wins),
    so a burst of clicks never opens windows in parallel."""
    with _FOCUS["lock"]:
        _FOCUS["next"] = view
        if _FOCUS["busy"]:
            return
        _FOCUS["busy"] = True

    def work():
        while True:
            with _FOCUS["lock"]:
                v, _FOCUS["next"] = _FOCUS["next"], None
                if v is None:
                    _FOCUS["busy"] = False
                    return
            try:
                _focus(api, window, v)
            except Exception:
                log_event("focus failed", exc=True)
    threading.Thread(target=work, daemon=True).start()


# --- one FauxRaccord at a time, and a log of what went wrong -----------------------------------------
LOG_FILE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "fauxraccord" / "gui.log"


def log_event(msg: str, exc: bool = False) -> None:
    """gui.log: start, focus requests, uncaught errors (the window runs without a console)."""
    import traceback
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
            if exc:
                f.write(traceback.format_exc() + "\n")
    except OSError:
        pass


def _start_log() -> None:
    """Uncaught errors (any thread) and hard crashes (faulthandler) go to gui.log; the log is kept small."""
    import faulthandler
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 1_000_000:
            LOG_FILE.replace(LOG_FILE.with_suffix(".old.log"))
        global _LOG_FH
        _LOG_FH = LOG_FILE.open("a", encoding="utf-8")
        faulthandler.enable(_LOG_FH)
    except OSError:
        pass

    def hook(args):
        import traceback
        log_event("error in thread " + getattr(args.thread, "name", "?") + ":\n"
                  + "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
    threading.excepthook = hook


_LOG_FH = None


def _first_instance() -> bool:
    """True for the first FauxRaccord on this session. Windows says so (a named mutex), whether or not the
    first one answers: a busy FauxRaccord must never get a second window beside it."""
    global _MUTEX
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        _MUTEX = k32.CreateMutexW(None, False, "lihogloglo.fauxraccord")
        return k32.GetLastError() != 183            # ERROR_ALREADY_EXISTS
    except (AttributeError, OSError):
        return True


def _panel_at_start(api: "Api") -> None:
    """The Premiere panel follows FauxRaccord: installed, or updated, whenever this version differs."""
    from .sourcing import bridge
    try:
        premiere, _installed, current = bridge.panel_state()
        if not premiere or current:
            return
        notes: list[str] = []
        if bridge.install_panel(log=notes.append):
            api._panel_cache = None
            if bridge.premiere_running():
                api._emit({"type": "toast", "text": tr("Panneau Premiere mis à jour : redémarrez Premiere pour l'utiliser.")})
    except Exception:
        pass


def main(tab: int = 0) -> None:
    import webview

    from .sourcing import bridge
    link = next((a for a in sys.argv[1:] if a.lower().startswith("fauxraccord:")), "")
    view = _link_view(link) if link else "main"
    if not _first_instance():      # already open: bring it forward (unless the panel only wanted it running)
        if view != "start":
            for _ in range(3):
                if bridge.focus_running(view):
                    break
                time.sleep(1)
        return
    _start_log()
    log_event(f"start {link or ''}".strip())
    api = Api()
    if tab:
        api._state["step"] = ["sync", "derush", "sources"][tab]
    dark = False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            dark = winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        pass
    try:   # own taskbar button and icon instead of Python's (the installer's shortcuts carry the same id)
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("lihogloglo.fauxraccord")
        # the mutex taken by _first_instance(): the installer also waits while it is held (installer/FauxRaccord.iss)
    except (AttributeError, OSError):
        pass
    window = webview.create_window("FauxRaccord", str(WEB / "index.html"), js_api=api, width=1120, height=780,
                                   min_size=(420, 520), background_color="#16171a" if dark else "#f6f7f9",
                                   text_select=True, minimized=view == "start")
    api._window = window
    window.events.loaded += lambda: _on_loaded(window, api)
    window.events.loaded += lambda: threading.Thread(target=api.check, daemon=True).start()
    window.events.loaded += lambda: threading.Thread(target=api.ai_check, daemon=True).start()
    window.events.loaded += lambda: threading.Thread(target=_panel_at_start, args=(api,), daemon=True).start()
    if view not in ("main", "start"):
        window.events.loaded += lambda: _focus_soon(api, window, view)
    window.events.closing += lambda: api._job.stop()
    window.events.closed += lambda: api._sheet_window and api._sheet_window[0].destroy()
    window.events.closed += lambda: getattr(api, "_sb_window", None) and api._sb_window.destroy()
    window.events.closed += lambda: getattr(api, "_board_window", None) and api._board_window.destroy()
    bridge.start(lambda kind="sources": {"out": api._sb_out() if kind == "storyboard" else api._sources_out(),
                                         "derush": Path(api._state["derush_out"]) if api._state["derush_out"] else None,
                                         "auto": bool(api._state["opts"].get("auto_fill", True))},
                 focus=lambda v: _focus_soon(api, window, v))
    threading.Thread(target=_register_link, daemon=True).start()
    fresh_page_cache(APPDATA / "webview")
    webview.start(private_mode=False, storage_path=str(APPDATA / "webview"), icon=str(WEB / "fauxraccord.ico"))


def main_sources() -> None:
    main(tab=2)


if __name__ == "__main__":
    main()
