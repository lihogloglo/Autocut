"""Where the sounds come from. Every source gives the same thing: sounds of a kind (whoosh, click,
pop, typing, hit), each a local file with the moment it hits (its sync point), its level and its
waveform, so the plan can aim it at a frame and the page can draw it.

  earshot   built in: sounds made in code (MIT), rendered on this computer, never twice the same take
  folder    the user's folders: their Epidemic / Artlist / Envato downloads, packs, anything. Sorted by
            file name (swish, click, pop, typing…), measured once and remembered
  epidemic  the user's Epidemic Sound subscription, through Epidemic's official MCP server with their
            own API key (search and preview are free; downloading needs the subscription)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

KINDS = ("whoosh", "click", "pop", "typing", "hit")
AUDIO = {".wav", ".mp3", ".flac", ".aif", ".aiff", ".ogg", ".m4a"}
CACHE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "autocut" / "sfx"
SR = 48000

NAMES = [   # file name -> kind (English and French words, as packs and Epidemic name them)
    ("typing", r"typing|keyboard|keystroke|key ?press|typewriter|clavier|frappe|dactylo"),
    ("whoosh", r"whoosh|woosh|swoosh|swish|swipe|swoop|whip|pass ?by|fly ?by|transition|swing|souffle"),
    ("hit", r"impact|\bhit\b|boom|thud|punch|slam|sub ?drop|bass ?drop|braam|stomp"),
    ("pop", r"\bpop|bubble|blip|plop|bloop|boop|notif|ding|chime|bell|appear|cartoon"),
    ("click", r"click|clic|switch|\btick|\btap\b|button|mouse|toggle|select|interface|\bui\b|keypad|shutter"),
]

EARSHOT = {   # kind -> bank categories, in the order a kit takes them
    "whoosh": ["swish", "whoosh_fast", "swipe"],
    "click": ["pro_click", "click", "toggle"],
    "pop": ["pro_pop", "ui_pop", "pro_pop_in"],
    "typing": ["pro_typing_run"],
    "hit": ["pro_impact", "cut_hit"],
}


@dataclass
class Snd:
    id: str                   # earshot:<bank id>  ·  file:<path>  ·  epidemic:<uuid>
    source: str               # earshot | folder | epidemic
    kind: str
    name: str
    path: str = ""            # local file ("" until rendered / downloaded)
    dur: float = 0.0
    sync: float = 0.0         # seconds into the file where it hits
    peak_db: float = 0.0
    wave: list = field(default_factory=list)   # 0..1 peaks, for drawing
    licence: str = ""
    preview: str = ""         # a URL to hear it before it is downloaded (Epidemic)
    extra: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return asdict(self)


def kind_of(name: str) -> str:
    n = name.lower().replace("_", " ").replace("-", " ")
    return next((k for k, rx in NAMES if re.search(rx, n)), "")


# --- measuring a file -----------------------------------------------------------------------------

def decode(path: Path, sr: int = 16000) -> np.ndarray:
    """Mono float32 samples (ffmpeg reads every format the packs use)."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", str(sr),
                          "-f", "f32le", "-"], capture_output=True, check=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    return np.frombuffer(out, dtype=np.float32)


def measure(y: np.ndarray, sr: int, kind: str) -> dict:
    """Duration, sync point, peak level and a waveform. The sync point is where the ear locks the
    sound to the picture: the attack for clicks, pops, keys and hits, the loudest moment for a whoosh."""
    if not len(y):
        return {"dur": 0.0, "sync": 0.0, "peak_db": -120.0, "wave": []}
    a = np.abs(y.astype(np.float32))
    hop = max(1, sr // 200)                     # 5 ms
    n = len(a) // hop
    env = np.sqrt((a[: n * hop].reshape(n, hop) ** 2).mean(axis=1)) if n else a
    peak = float(a.max())
    top = float(env.max()) or 1e-9
    if kind == "whoosh":
        sm = np.convolve(env, np.ones(6) / 6, mode="same")          # 30 ms: the body, not a click in it
        sync = float(np.argmax(sm)) * hop / sr
    else:
        on = np.nonzero(env >= top * 0.25)[0]
        sync = float(on[0]) * hop / sr if len(on) else 0.0
    bins = 160
    edges = np.linspace(0, len(a), bins + 1).astype(int)
    w = [float(a[edges[i]:max(edges[i] + 1, edges[i + 1])].max()) for i in range(bins)]
    return {"dur": len(y) / sr, "sync": round(sync, 4), "peak_db": round(20 * np.log10(max(peak, 1e-6)), 2),
            "wave": [round(v / (peak or 1), 3) for v in w]}


def write_wav(path: Path, y: np.ndarray, sr: int = SR) -> None:
    y = np.asarray(y, dtype=np.float32)
    ch = 1 if y.ndim == 1 else y.shape[1]
    pcm = (np.clip(y, -1, 1) * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    tmp.replace(path)


# --- earshot ---------------------------------------------------------------------------------------

def earshot_ok() -> bool:
    try:
        from earshot.forge import bank  # noqa: F401
        return True
    except Exception:
        return False


def earshot_sounds(kind: str) -> list[Snd]:
    """The bank's members for a kind (not rendered yet: takes are made per cue, see render_take)."""
    from earshot.forge import bank
    rows = []
    for cat in EARSHOT.get(kind, []):
        rows += bank.list_sounds(category=cat)
    return [Snd(f"earshot:{r['id']}", "earshot", kind, r["id"].replace("/", " · "), dur=float(r["dur_s"]),
                sync=float(r["peak_s"] if kind == "whoosh" else r.get("onset_s") or 0.0), licence="earshot (MIT)",
                extra={"bank": r["id"], "knobs": r.get("knobs", {})}) for r in rows]


def render_take(snd: Snd, seed: int, dur: float | None = None, apex: float | None = None,
                folder: Path | None = None) -> Snd:
    """One take of an earshot sound, written once (same sound, seed and knobs: same file)."""
    from earshot.forge import bank
    knobs = snd.extra.get("knobs", {})
    kw = {}
    if dur and knobs.get("dur") in ("param", "shape"):
        kw["dur"] = round(dur, 3)
    if apex is not None and knobs.get("apex"):
        kw["apex"] = round(apex, 3)
    tag = "-".join(f"{k}{v}" for k, v in sorted(kw.items()))
    folder = folder or CACHE / "earshot"
    path = folder / f"{snd.extra['bank'].replace('/', '_')}-s{seed}{'-' + tag if tag else ''}.wav"
    meta_path = path.with_suffix(".json")
    if path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        y, m = bank.render(snd.extra["bank"], seed=seed, checks=False, **kw)
        write_wav(path, y, int(m.get("sr", SR)))
        meta = measure(y.mean(axis=1) if y.ndim > 1 else y, int(m.get("sr", SR)), snd.kind)
        meta["sync"] = float(m["peak_s"] if snd.kind == "whoosh" else m.get("onset_s") or meta["sync"])
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return Snd(f"{snd.id}#{seed}{'-' + tag if tag else ''}", "earshot", snd.kind, snd.name, str(path),
               meta["dur"], meta["sync"], meta["peak_db"], meta["wave"], snd.licence, extra=snd.extra)


# --- folders ---------------------------------------------------------------------------------------

def _index_file() -> Path:
    return CACHE / "folders.json"


def scan(folders: list[str], log=print) -> list[Snd]:
    """Every sound file in the folders whose name says its kind, measured once (cached by size+date)."""
    from ..media import ensure_ffmpeg
    ensure_ffmpeg()
    try:
        cache = json.loads(_index_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    out, fresh = [], {}
    files = []
    for folder in folders:
        root = Path(folder)
        if root.is_dir():
            files += [p for p in root.rglob("*") if p.suffix.lower() in AUDIO and p.is_file()]
    todo = [p for p in files if kind_of(p.stem)]
    for i, p in enumerate(todo, 1):
        st = p.stat()
        key = f"{p}|{st.st_size}|{int(st.st_mtime)}"
        kind = kind_of(p.stem)
        info = cache.get(key)
        if not info or info.get("kind") != kind:
            if st.st_size > 40_000_000:      # a long ambience or a music track, not an effect
                continue
            try:
                info = {"kind": kind, **measure(decode(p), 16000, kind)}
            except (subprocess.CalledProcessError, OSError):
                continue
            if i % 20 == 0:
                log(f"  {i}/{len(todo)} sons mesurés")
        fresh[key] = info
        if info["dur"] > 12:                 # beds and ambiences: not placed on an event
            continue
        lic = "Epidemic Sound" if p.name.startswith("ES_") else ""
        out.append(Snd(f"file:{p}", "folder", kind, p.stem, str(p), info["dur"], info["sync"], info["peak_db"],
                       info["wave"], lic))
    _index_file().parent.mkdir(parents=True, exist_ok=True)
    _index_file().write_text(json.dumps(fresh), encoding="utf-8")
    return out


# --- Epidemic Sound (MCP) --------------------------------------------------------------------------

EPIDEMIC_MCP = "https://www.epidemicsound.com/a/mcp-service/mcp"
EPIDEMIC_QUERIES = {"whoosh": "swish", "click": "click", "pop": "pop", "typing": "typing keyboard",
                    "hit": "impact hit"}


def epidemic_key() -> str:
    """The user's Epidemic API key: saved from the window, or EPIDEMIC_KEY (environment or .env)."""
    from ..sourcing.llm import _keys
    k = _keys().get("epidemic") or os.environ.get("EPIDEMIC_KEY", "")
    if not k:
        env = Path(__file__).resolve().parents[3] / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("EPIDEMIC_KEY="):
                    k = line.split("=", 1)[1].strip().strip("'\"")
    return k


class Epidemic:
    """A minimal MCP client (streamable HTTP, JSON-RPC) for Epidemic's server: search and download."""

    def __init__(self, key: str):
        import httpx
        self.http = httpx.Client(timeout=60, headers={"Authorization": f"Bearer {key}",
                                                      "Accept": "application/json, text/event-stream"})
        self.sid = None
        self.n = 0
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "autocut", "version": "1"}})
        self._rpc("notifications/initialized", notify=True)

    def _rpc(self, method: str, params: dict | None = None, notify: bool = False):
        self.n += 1
        body = {"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})}
        if not notify:
            body["id"] = self.n
        r = self.http.post(EPIDEMIC_MCP, json=body, headers={"Mcp-Session-Id": self.sid} if self.sid else {})
        self.sid = r.headers.get("Mcp-Session-Id", self.sid)
        if notify:
            return None
        if r.status_code == 401:
            raise PermissionError("Epidemic : clé refusée")
        r.raise_for_status()
        if "text/event-stream" in r.headers.get("Content-Type", ""):
            data = [ln[5:].strip() for ln in r.text.splitlines() if ln.startswith("data:")]
            msg = json.loads(data[-1]) if data else {}
        else:
            msg = r.json()
        if "error" in msg:
            raise RuntimeError(f"Epidemic : {msg['error'].get('message')}")
        return msg.get("result", {})

    def tool(self, name: str, args: dict) -> dict:
        res = self._rpc("tools/call", {"name": name, "arguments": args})
        text = "".join(c.get("text", "") for c in res.get("content", []))
        data = json.loads(text) if text.strip().startswith("{") else {"text": text}
        if res.get("isError") or data.get("errors"):
            raise RuntimeError(f"Epidemic : {(data.get('errors') or [{}])[0].get('message', text[:200])}")
        return data.get("data", data)

    def search(self, term: str, kind: str, n: int = 12, max_ms: int = 6000) -> list[Snd]:
        data = self.tool("SearchSoundEffects", {"query": {"term": term}, "first": n,
                                                "filter": {"duration": {"max": max_ms}}})
        out = []
        for node in data.get("soundEffects", {}).get("nodes", []):
            s = node.get("soundEffect", node)
            af = s.get("audioFile") or {}
            out.append(Snd(f"epidemic:{s['id']}", "epidemic", kind, s.get("title", ""), dur=af.get(
                "durationInMilliseconds", 0) / 1000, licence="Epidemic Sound", preview=af.get("lqmp3Url", ""),
                extra={"waveform": af.get("waveformUrl", "")}))
        return out

    def download(self, snd: Snd, folder: Path) -> Snd:
        """The WAV into the project's sounds folder (once), then measured like any file."""
        uid = snd.id.split(":", 1)[1]
        path = folder / f"ES_{re.sub(r'[^\w ,.-]', ' ', snd.name).strip()[:80]} ({uid[:8]}).wav"
        if not path.exists():
            data = self.tool("DownloadSoundEffect", {"id": uid, "options": {"fileType": "WAV"}})
            url = _find_url(data)
            if not url:
                raise RuntimeError("Epidemic : pas de lien de téléchargement")
            folder.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            with self.http.stream("GET", url, headers={"Authorization": ""}) as r:
                r.raise_for_status()
                with tmp.open("wb") as fh:
                    for chunk in r.iter_bytes():
                        fh.write(chunk)
            tmp.replace(path)
        info = measure(decode(path), 16000, snd.kind)
        return Snd(snd.id, "epidemic", snd.kind, snd.name, str(path), info["dur"], info["sync"], info["peak_db"],
                   info["wave"], "Epidemic Sound", snd.preview, snd.extra)


def _find_url(data) -> str:
    if isinstance(data, str):
        return data if data.startswith("http") else ""
    if isinstance(data, dict):
        for v in data.values():
            if u := _find_url(v):
                return u
    if isinstance(data, list):
        for v in data:
            if u := _find_url(v):
                return u
    return ""


def digest(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]
