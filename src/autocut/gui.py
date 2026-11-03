"""The Autocut window: one page per step, each also usable on its own.

1. Synchro       rushes (videos + .wav, or their folder)      -> <title>.sync.xml
2. Derush        a Premiere sequence (raw or half derushed)   -> <title>.autocut.xml
3. Illustrations script links -> contact sheet -> files, credits and B-roll placed on the derush/edit
4. Storyboard     a style in words -> a beat-by-beat storyboard (what to make), cards placed on the edit
5. Sons           automatic: sounds on what moves in the finished edit (editor page, XML); by hand: the sound board
                  (sound effects, ambiences, music dragged into Premiere)
   IA             which AI engine every step uses (API keys, or the user's subscriptions through their CLIs)

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

APPDATA = Path(os.environ.get("APPDATA", Path.home())) / "autocut"
STATE_FILE = APPDATA / "app.json"
WEB = Path(__file__).parent / "web"

SCRIPT_EXT, MEDIA_EXT = project.SCRIPT_EXT, project.MEDIA_EXT
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

DEFAULTS = {
    **project.EMPTY, "project": "", "projects": {}, "recent": [], "chain": True, "ui_lang": "",
    "opts": {"model": "large-v3", "max_pause": 0.6, "pad_in": 0.12, "pad_out": 0.25,
             "shots": True, "search": True, "web": True, "videos": True, "llm": "auto", "judge": True, "brief": "", "quality": "best",
             "sb_style": "", "sb_pace": 6, "lang": "auto",
             "shot_height": 4000, "segment": 30, "full_max": 10,
             "sfx_folders": [], "sfx_density": 2, "sfx_sources": {"folder": True, "epidemic": True, "earshot": True}},
}


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
        fd, result = tempfile.mkstemp(prefix="autocut-", suffix=".txt")
        os.close(fd)
        from .i18n import ui_lang
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "AUTOCUT_RESULT": result,
               "AUTOCUT_LANG": ui_lang()}
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
                "sources": self._sources(),
                "job": {"running": self._job.running, "step": self._job.step}, "checks": self._checks,
                "keys": self._keys(), "ai": self._ai, "storyboard": self._storyboard(), "sfx": self._sfx()}

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
                self._window.set_title(f"Autocut — {name}" if name else "Autocut")
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
        mask = lambda k: f"{k[:4]}…{k[-4:]}" if len(k) > 12 else (tr("enregistrée") if k else "")   # noqa: E731
        return {"gemini": mask(gemini_key()), "epidemic": mask(epidemic_key())}

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
        return info

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
        return info

    # sound effects
    def _sfx_edit(self) -> str:
        """The edit the sounds go on: the one chosen here, else the sequence the illustrations use."""
        s = self._state
        return s["sfx_xml"] or (s["place_xml"] if s["place_xml"] and not s["place_xml"].lower().endswith(".autocut.xml")
                                 else "") or s["place_xml"] or s["derush_out"]

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
                xml = out / f"{data.get('title') or ''} Sons.xml"
                info["xml"] = str(xml) if xml.exists() else ""
            except (OSError, ValueError, KeyError):
                pass
        return info

    def open_sfx(self) -> dict:
        out = self._sfx_out()
        if not out or not (out / "cues.json").exists():
            return {"ok": False, "message": tr("Analysez d'abord le montage.")}
        import webview

        from .sfx.page import serve
        if getattr(self, "_sfx_server", None):
            self._sfx_server.shutdown()
        self._sfx_server, url = serve(out)
        win = getattr(self, "_sfx_window", None)
        if win is not None:
            try:
                win.load_url(url)
                win.restore()
                win.show()
                return {"ok": True}
            except Exception:
                self._sfx_window = None
        self._sfx_window = webview.create_window(tr("Sons"), url, width=1500, height=900, min_size=(800, 500))

        def closed():
            self._sfx_window = None
        self._sfx_window.events.closed += closed
        return {"ok": True}

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
        derush = s["derush_out"] or (edit if edit.lower().endswith(".autocut.xml") else "")
        if edit.lower().endswith(".autocut.xml"):
            edit = ""
        return {"script": s["script"], "derush": derush, "edit": edit, "engine": o.get("llm", "auto"),
                "quality": o.get("quality", "best"), "out": str(out) if out else ""}

    def open_board(self) -> dict:
        """The sound board in its own Autocut window: sound effects, ambiences and music to drag into
        Premiere. Needs no analysis: only the sound folders (and Epidemic, the bank)."""
        import webview

        from .sfx.board import Board, BoardApi, serve
        win = getattr(self, "_board_window", None)
        if win is not None:
            try:
                win.restore()
                win.show()
                win.evaluate_js("load(true)")
                return {"ok": True}
            except Exception:
                self._board_window = None
        opts = lambda: self._state["opts"]      # noqa: E731  (read at each use: settings change while it is open)
        board = Board(lambda: opts().get("sfx_folders") or [], self._board_media, lambda: opts().get("sfx_sources") or {},
                      self._board_context)
        if getattr(self, "_board_server", None):
            self._board_server.shutdown()
        self._board_server, url = serve(board)
        win = webview.create_window(tr("Planche sonore"), url, js_api=BoardApi(board), width=1180, height=860,
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
        for win in (self._window, self._sheet_window[0] if self._sheet_window else None):
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
        return {"sources": self._sources(), "storyboard": self._storyboard(), "sfx": self._sfx()}

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
        self._job.start("setup", ["autocut.setup", "install", "ai", engine],
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
            if p.is_file() and ext in SCRIPT_EXT:
                # the script decides the project: its folder is where every step writes
                folder = p.parent
                if (not s["project"] or not project.inside(folder, Path(s["project"]))) and not self._job.running:
                    self._switch(folder, carry=not s["script"])
                    notes.append(tr("Projet : {name}", name=folder.name))
                s["script"] = str(p)
                notes.append(tr("Script : {name}", name=p.name))
                continue
            if p.is_file() and ext == ".xml" and zone in ("sfx", "sfx-src"):
                s["sfx_xml"] = str(p)
                notes.append(tr("Montage pour les sons : {name}", name=p.name))
            elif p.is_file() and ext == ".xml":
                if zone in ("sources", "storyboard"):
                    s["place_xml"] = str(p)
                    notes.append(tr("Séquence pour les timecodes : {name}", name=p.name))
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
                 "script": (tr("Script") + " (*.md;*.txt;*.docx)",),
                 "storyboard": (tr("Images de référence") + " (*.jpg;*.jpeg;*.png;*.webp)",),
                 "sfx": (tr("Montage Premiere") + " (*.xml)",)}.get(zone, ())
        if folder:
            paths = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        else:
            paths = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=zone in ("sync", "storyboard"),
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
            args = ["autocut", *s["rushes"], "--model", o["model"], *self._out_arg()]
            self._job.start("sync", args, self._sync_done)
        elif step == "derush":
            if not s["xml"]:
                return {"ok": False, "message": tr("Déposez d'abord une séquence (.xml).")}
            if not s["script"]:
                return {"ok": False, "message": tr("Le derush a besoin du script.")}
            keep = "0"
            if s["mode"] == "continue":
                keep = str(s["keep"]) if s["keep"] is not None else "auto"
            args = ["autocut", s["xml"], s["script"], "--model", o["model"], "--max-pause", str(o["max_pause"]),
                    "--pad-in", str(o["pad_in"]), "--pad-out", str(o["pad_out"]), "--keep-until", keep,
                    "--language", o.get("lang", "auto"), *self._out_arg()]
            if s["sequence"]:
                args += ["--sequence", s["sequence"]]
            self._job.start("derush", args, self._derush_done)
        elif step == "collect":
            if not s["script"]:
                return {"ok": False, "message": tr("Déposez d'abord le script.")}
            args = ["autocut.sourcing", "collect", s["script"], "--llm", o["llm"], "--quality", o.get("quality", "best"),
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
            args = ["autocut.sourcing", "export", str(out), "--model", o["model"]]
            if derush:
                args += ["--derush", str(derush)]
            if edit:
                args += ["--edit", str(edit)]
            self._job.start("place", args, self._place_done)
        elif step == "sfx":
            edit, out = self._sfx_edit(), self._sfx_out()
            if not edit:
                return {"ok": False, "message": tr("Déposez d'abord le montage (.xml).")}
            src = o.get("sfx_sources") or {}
            order = [k for k in ("folder", "epidemic", "earshot") if src.get(k, True)] or ["earshot"]
            args = ["autocut.sfx", "plan", edit, "--out", str(out), "--title", Path(s["script"] or edit).stem,
                    "--density", str(o.get("sfx_density") or 2), "--sources", ",".join(order), "--keep-edits"]
            for f in o.get("sfx_folders") or []:
                args += ["--folder", f]
            self._job.start("sfx", args, self._sfx_done)
        elif step == "storyboard":
            if not s["script"]:
                return {"ok": False, "message": tr("Déposez d'abord le script.")}
            args = ["autocut.storyboard", "make", s["script"], "--llm", o["llm"], "--quality", o.get("quality", "best"),
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
        """(derush, edit) for the placement. One sequence is given; when it is not Autocut's own derush,
        that derush (if any) still helps: its Sxxx markers find the sentences without listening."""
        s = self._state
        target = Path(s["place_xml"]) if s["place_xml"] else None
        if not target:
            return None, None
        if target.name.lower().endswith(".autocut.xml"):
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

    def install(self, item: str) -> dict:
        if self._job.running:
            return {"ok": False, "message": tr("Une étape tourne déjà.")}
        what, _, arg = item.partition(":")
        if what == "update":      # the new installer waits for this window to close, then opens it again
            done = lambda r: (threading.Timer(1.0, self._window.destroy).start(),       # noqa: E731
                              tr("Mise à jour : Autocut se rouvre dans un instant."))[1]
        else:
            done = lambda r: (self.check(), tr("Installé."))[1]                      # noqa: E731
        self._job.start("setup", ["autocut.setup", "install", what, *([arg] if arg else [])], done)
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
        report = Path(result).with_suffix("").with_suffix(".autocut.txt") if result else None
        summary = ""
        if report and report.exists():
            lines = [ln for ln in report.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
            summary = next((ln for ln in lines if ln.startswith("Source ")), "")
        return tr("{name} écrit. {summary}", name=Path(result).name, summary=summary).strip()

    def _sfx_done(self, result: str) -> str:
        self._push()
        self.open_sfx()
        info = self._sfx()
        return tr("{n} sons placés : l'éditeur s'ouvre.", n=info["cues"])

    def _storyboard_done(self, result: str) -> str:
        self._push()
        self.open_storyboard()
        return tr("Storyboard prêt : il s'ouvre dans le navigateur. Premiere : panneau Autocut › Storyboard, ou le .xml.")

    def open_storyboard(self) -> dict:
        out = self._sb_out()
        if not out or not (out / "storyboard.json").exists():
            return {"ok": False, "message": tr("Générez d'abord le storyboard.")}
        from .storyboard import serve
        if self._sb_server:
            self._sb_server.shutdown()
        self._sb_server, _ = serve(out, lambda: self._state["opts"].get("llm", "auto"))
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
        """The planche in its own Autocut window (not the browser): cards can be dragged into Premiere."""
        import webview

        from .sourcing.drag import Dragger, SheetApi
        dragger = Dragger(out)
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
        api = SheetApi(dragger)
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
            txt = Path(r[: -len(".autocut.xml")] + ".autocut.txt") if r.endswith(".autocut.xml") else None
            if txt and txt.exists():
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


def main(tab: int = 0) -> None:
    import webview
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
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("lihogloglo.autocut")
        global _MUTEX           # the installer waits while this is held (Autocut-Setup.exe, installer/Autocut.iss)
        _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "lihogloglo.autocut")
    except (AttributeError, OSError):
        pass
    window = webview.create_window("Autocut", str(WEB / "index.html"), js_api=api, width=1120, height=780,
                                   min_size=(420, 520), background_color="#16171a" if dark else "#f6f7f9",
                                   text_select=True)
    api._window = window
    window.events.loaded += lambda: _on_loaded(window, api)
    window.events.loaded += lambda: threading.Thread(target=api.check, daemon=True).start()
    window.events.loaded += lambda: threading.Thread(target=api.ai_check, daemon=True).start()
    window.events.closing += lambda: api._job.stop()
    window.events.closed += lambda: api._sheet_window and api._sheet_window[0].destroy()
    window.events.closed += lambda: getattr(api, "_sfx_window", None) and api._sfx_window.destroy()
    window.events.closed += lambda: getattr(api, "_board_window", None) and api._board_window.destroy()
    from .sourcing import bridge
    bridge.start(lambda kind="sources": (api._sb_out() if kind == "storyboard" else api._sources_out(),
                                         Path(api._state["derush_out"]) if api._state["derush_out"] else None))
    fresh_page_cache(APPDATA / "webview")
    webview.start(private_mode=False, storage_path=str(APPDATA / "webview"), icon=str(WEB / "autocut.ico"))


def main_sources() -> None:
    main(tab=2)


if __name__ == "__main__":
    main()
