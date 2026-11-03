"""The sound board (planche sonore): the manual path for sound, as the planche is for pictures.

Three layers, one tab each: sound effects, ambiences, music. They come from the user's folders (their
Epidemic / Artlist / Envato downloads, packs), the built-in bank (earshot) and Epidemic Sound (search and
preview free, download with the subscription). Anything on the board is dragged straight into Premiere's
timeline: a real file drag, like one from Explorer (sourcing/drag.py).

The sound-effect tiles are the user's own playlists: a name in their language, English search words (Epidemic
names its sounds in English) and the takes starred in it. The board starts with Whoosh, Clic, Pop, Clavier,
Impact, Montée (sorted from file names, plus the bank); any search can become a tile. A tile gives a different
take on every drag: drawn from its starred takes (else its short ones), every take once before any repeats,
never twice in a row. The tile
shows the take that comes next, so what you hear is what you drag. A built-in bank sound is rendered
anew for every drag: never twice the same take.

Files are sorted by their names and lengths: Epidemic names its effects with tags (« ES_Swooshes, Whoosh,
Low… - Epidemic Sound ») and its music « ES_<title> - <artist> »; a music / ambience folder says what is
in it; long sounds are beds, longer ones music.
"""

from __future__ import annotations

import json
import os
import random
import re
import struct
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from ..i18n import tr
from . import library as L
from .plan import sfx_gain

PAGE = Path(__file__).parent.parent / "web" / "board.html"
SETTINGS = Path(os.environ.get("APPDATA", Path.home())) / "autocut" / "board.json"
INDEX = L.CACHE / "board-index.json"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

FAMILIES = (*L.KINDS, "riser", "other")      # how files are sorted (the automatic path does not place risers)
# the tiles a new board starts with: label (French, translated on the page), English search words, the sort it reads
DEFAULT_TILES = [("whoosh", "Whoosh", "whoosh swish"), ("click", "Clic", "click"), ("pop", "Pop", "pop"),
                 ("typing", "Clavier", "typing keyboard"), ("hit", "Impact", "impact hit"), ("riser", "Montée", "riser")]
RISER = re.compile(r"riser|\brise\b|\brising\b|uplifter|build ?up|\bswell|tension|crescendo|\breverse")
LAYERS = ("sfx", "amb", "music")
AMB = re.compile(r"ambien|ambiance|atmos|room ?tone|roomtone|background|\bbg\b|walla|crowd|foule|\brain\b|pluie|"
                 r"\bwind\b|\bvent\b|forest|for[eê]t|\bcity\b|\bville\b|street|traffic|circulation|\bbirds?\b|oiseaux|"
                 r"\bnight\b|\bnuit\b|nature|ocean|oc[eé]an|\bwaves\b|vagues|river|rivi[eè]re|interior|exterior|"
                 r"\bbed\b|soundscape|drone|hum\b|ronron|campagne|countryside|office|bureau|cafe|caf[eé]|restaurant")
MUSIC_DIR = re.compile(r"music|musique|song|track|chanson|\bbgm\b|soundtrack")
AMB_DIR = re.compile(r"ambien|ambiance|atmos|room ?tone|soundscape")
SFX_DIR = re.compile(r"\bsfx\b|bruitage|sound ?effects?|\bfx\b|foley|effets")
MUSIC_NAME = re.compile(r"^(?:es_)?(?P<title>.+?) - (?P<artist>.+)$", re.I)
STEM = re.compile(r"\bstems?\b\s*(?P<part>\w+)?", re.I)
SFX_MAX, AMB_MIN, MUSIC_MIN = 12.0, 20.0, 45.0
# a tile's random takes: no longer than this unless starred (more room than the automatic pools, plan.MAX_DUR:
# here the editor hears what they drag)
RANDOM_MAX = {"whoosh": 6.0, "click": 2.0, "pop": 3.0, "typing": 15.0, "hit": 6.0, "riser": 15.0}


# --- reading the folders -------------------------------------------------------------------------

def wav_duration(path: Path) -> float | None:
    """From the RIFF header (instant, any PCM WAV / BWF, RF64 included); None when it is not one."""
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            head = f.read(12)
            if head[:4] not in (b"RIFF", b"RF64") or head[8:12] != b"WAVE":
                return None
            rate = 0
            while True:
                c = f.read(8)
                if len(c) < 8:
                    return None
                cid, n = c[:4], struct.unpack("<I", c[4:])[0]
                if cid == b"fmt ":
                    fmt = f.read(n)
                    rate = struct.unpack("<I", fmt[8:12])[0]
                    if n & 1:
                        f.seek(1, 1)
                elif cid == b"data":
                    if n in (0, 0xFFFFFFFF):            # RF64 / unfinished header: the rest of the file
                        n = size - f.tell()
                    return n / rate if rate else None
                else:
                    f.seek(n + (n & 1), 1)
    except (OSError, struct.error):
        return None


def duration(path: Path) -> float:
    d = wav_duration(path) if path.suffix.lower() in (".wav", ".bwf") else None
    if d is not None:
        return round(d, 3)
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                              str(path)], capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW).stdout
        return round(float(out.strip() or 0), 3)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def folder_says(dirs: list[str]) -> str:
    """What the nearest telling folder holds: « music », « amb », « sfx » or nothing (dirs: nearest first)."""
    for d in dirs:
        d = d.lower()
        if AMB_DIR.search(d):
            return "amb"
        if SFX_DIR.search(d):
            return "sfx"
        if MUSIC_DIR.search(d):
            return "music"
    return ""


def family_of(stem: str) -> str:
    n = stem.lower().replace("_", " ")
    k = L.kind_of(stem)
    return "riser" if RISER.search(n) and k in ("", "whoosh", "hit") else k


def classify(stem: str, dirs: list[str], dur: float) -> tuple[str, str]:
    """(layer, family) of a file from its name, the folders it sits in (nearest first) and its length."""
    n = stem.lower().replace("_", " ").strip()
    tagged = n.endswith("epidemic sound") or bool(re.match(r"\d{4,} ", n)) or n.count(",") >= 2
    says = folder_says(dirs)
    kind = family_of(stem)
    if dur >= AMB_MIN and (says == "music" or (not tagged and STEM.search(n))
                           or (not tagged and MUSIC_NAME.match(stem) and dur >= MUSIC_MIN)):
        return "music", ""
    if says == "amb" and dur > SFX_MAX:
        return "amb", ""
    if kind and dur <= SFX_MAX:
        return "sfx", kind
    if AMB.search(n) and dur >= 6:
        return "amb", ""
    if dur >= MUSIC_MIN and not tagged and says != "sfx":
        return "music", ""
    if dur >= AMB_MIN:
        return "amb", ""
    return "sfx", kind or "other"


def music_meta(stem: str) -> tuple[str, str, str]:
    """(title, artist, stem part) from « ES_Title - Artist » / « ES_Title STEMS BASS »."""
    name = re.sub(r"\s*\([0-9a-f]{8}\)$", "", stem)            # our own download suffix
    part = ""
    if m := STEM.search(name):
        part = (m["part"] or "").lower()
        name = name[: m.start()].strip()
    if m := MUSIC_NAME.match(name):
        return m["title"].strip(), m["artist"].strip(), part
    return re.sub(r"^ES_", "", name), "", part


class Index:
    """Lengths, waveforms and sync points, measured once per file (by path, size and date)."""

    def __init__(self, path: Path = INDEX):
        self.path, self.lock, self.dirty = path, threading.Lock(), False
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    @staticmethod
    def key(p: Path, st: os.stat_result) -> str:
        return f"{p}|{st.st_size}|{int(st.st_mtime)}"

    def get(self, key: str) -> dict:
        with self.lock:
            return self.data.get(key, {})

    def put(self, key: str, **fields) -> None:
        with self.lock:
            self.data[key] = {**self.data.get(key, {}), **fields}
            self.dirty = True

    def save(self) -> None:
        with self.lock:
            if not self.dirty:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data), encoding="utf-8")
            tmp.replace(self.path)
            self.dirty = False


def scan(roots: list[Path], index: Index, skip: list[Path] = ()) -> list[dict]:
    """Every audio file under the roots, sorted into layers and families."""
    files: dict[str, tuple[Path, Path]] = {}
    skip = [str(s.resolve()).lower() for s in skip]
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.suffix.lower() in L.AUDIO and p.is_file():
                rp = str(p.resolve())
                if not any(rp.lower().startswith(s) for s in skip):
                    files.setdefault(rp.lower(), (p, root))
    rows = []
    for p, root in files.values():
        st = p.stat()
        rows.append((p, root, st, Index.key(p, st)))
    todo = [(p, k) for p, _, _, k in rows if "dur" not in index.get(k)]
    if todo:
        from ..media import ensure_ffmpeg
        ensure_ffmpeg()
        with ThreadPoolExecutor(8) as ex:
            for (p, k), d in zip(todo, ex.map(lambda t: duration(t[0]), todo)):
                index.put(k, dur=d)
        index.save()
    items = []
    for p, root, st, k in rows:
        dur = index.get(k).get("dur", 0.0)
        layer, family = classify(p.stem, [q.name for q in p.parents if q.name], dur)
        it = {"id": f"file:{p}", "layer": layer, "family": family, "name": p.stem, "path": str(p), "dur": dur,
              "source": "folder", "where": str(p.parent), "key": k,
              "licence": "Epidemic Sound" if p.name.startswith("ES_") or "epidemic" in str(p).lower() else ""}
        if layer == "music":
            it["title"], it["artist"], it["stem"] = music_meta(p.stem)
        else:
            it["title"] = tidy(p.stem)
        items.append(it)
    items.sort(key=lambda i: (i["layer"], i["family"], i["title"].lower()))
    return items


def tidy(stem: str) -> str:
    """« ES_Swooshes, Whoosh, Low, Short 02 - Epidemic Sound » -> « Swooshes, Whoosh, Low, Short 02 »."""
    s = re.sub(r"^(ES_|\d{4,}_)", "", stem)
    s = re.sub(r"\s*-\s*Epidemic Sound$", "", s, flags=re.I)
    return re.sub(r"\s*\([0-9a-f]{8}\)$", "", s).strip() or stem


# --- levels ---------------------------------------------------------------------------------------

def _k_weighting(sr: int):
    """ITU-R BS.1770 K-weighting for any sample rate: the head's high shelf, then the low cut."""
    import numpy as np
    G, Q, fc = 4.0, 1 / np.sqrt(2), 1500.0
    A, w0 = 10 ** (G / 40), 2 * np.pi * fc / sr
    al, c = np.sin(w0) / (2 * Q), np.cos(w0)
    shelf = ([A * ((A + 1) + (A - 1) * c + 2 * np.sqrt(A) * al), -2 * A * ((A - 1) + (A + 1) * c),
              A * ((A + 1) + (A - 1) * c - 2 * np.sqrt(A) * al)],
             [(A + 1) - (A - 1) * c + 2 * np.sqrt(A) * al, 2 * ((A - 1) - (A + 1) * c),
              (A + 1) - (A - 1) * c - 2 * np.sqrt(A) * al])
    w0 = 2 * np.pi * 38.0 / sr
    al, c = np.sin(w0) / (2 * 0.5), np.cos(w0)
    cut = ([(1 + c) / 2, -(1 + c), (1 + c) / 2], [1 + al, -2 * c, 1 - al])
    return shelf, cut


def loudness(y, sr: int) -> float:
    """Integrated loudness (LUFS, gated, BS.1770) of samples shaped (n,) or (n, channels). Energies are summed
    per 100 ms, so an hour of audio stays light."""
    import numpy as np
    from scipy.signal import lfilter
    y = np.asarray(y, dtype=np.float32)
    if y.ndim == 1:
        y = y[:, None]
    for b, a in _k_weighting(sr):
        y = lfilter(np.float32(b), np.float32(a), y, axis=0).astype(np.float32)
    hop = int(0.1 * sr)
    n = len(y) // hop
    if n < 4:
        return -70.0
    e = np.square(y[: n * hop]).reshape(n, hop, y.shape[1]).sum(axis=1, dtype=np.float64).sum(axis=1)
    z = (e[:-3] + e[1:-2] + e[2:-1] + e[3:]) / (4 * hop)            # 400 ms blocks, 75 % overlap
    lk = -0.691 + 10 * np.log10(np.maximum(z, 1e-12))
    z = z[lk > -70]
    if not len(z):
        return -70.0
    rel = -0.691 + 10 * np.log10(z.mean()) - 10
    z = z[-0.691 + 10 * np.log10(z) > rel]
    return round(float(-0.691 + 10 * np.log10(z.mean())), 1)


# music sits ~35 LU under its own master in the user's edits (Epidemic tracks at -9..-14 LUFS -> clip -20..-25 dB),
# ambiences ~36 (heavy rain at -29 LUFS -> -7 dB)
BED = {"music": (-35.0, -25.0, -20.0), "amb": (-36.0, -30.0, -3.0)}      # target LUFS, lowest and highest gain
LOUD_SR = 16000


def bed_gain(layer: str, lufs: float | None) -> float | None:
    if lufs is None or lufs <= -69:
        return None
    target, lo, hi = BED[layer]
    return round(max(lo, min(hi, target - lufs)), 1)


def _decode(path: Path, sr: int, channels: int, seconds: float | None = None):
    import numpy as np
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", str(channels), "-ar", str(sr)]
    cmd += ["-t", str(seconds)] if seconds else []
    raw = subprocess.run(cmd + ["-f", "f32le", "-"], capture_output=True, check=True, creationflags=NO_WINDOW).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, channels)


def measure_bed(path: Path, dur: float = 0.0, sr: int = LOUD_SR) -> dict:
    """A long sound: waveform, peak and loudness. Up to 10 min, from one stereo decode; longer (a mix, a
    recording), the waveform from a light decode of the whole and the loudness from its first 10 minutes."""
    import numpy as np
    long = dur > 600
    y = _decode(path, sr, 2, 600 if long else None)
    if len(y) and np.allclose(y[::97, 0], y[::97, 1]):            # a mono file: one channel, as BS.1770 counts it
        y = y[:, :1]
    lufs = loudness(y, sr)
    mono = np.abs((_decode(path, 2000, 1) if long else y).mean(axis=1))
    peak = float(mono.max()) if len(mono) else 0.0
    edges = np.linspace(0, len(mono), 161).astype(int)
    wave = [round(float(mono[edges[i]:max(edges[i] + 1, edges[i + 1])].max()) / (peak or 1), 3) for i in range(160)] \
        if len(mono) else []
    return {"wave": wave, "sync": 0.0, "peak_db": round(20 * np.log10(max(peak, 1e-6)), 2), "lufs": lufs}


# --- the board ------------------------------------------------------------------------------------

class Board:
    """What the page shows and does. roots: the user's sound folders; media: where downloads and
    rendered takes go (the project's « - sons/médias », else the cache)."""

    def __init__(self, roots: Callable[[], list[str]], media: Callable[[], Path],
                 sources: Callable[[], dict] = dict, context: Callable[[], dict] = dict):
        self.roots, self.media, self.sources = roots, media, sources     # sources: the Sons page's switches
        self.context = context      # the project: script, derush / edit for timings, AI engine, « - sons » folder
        self.index = Index()
        self.lock = threading.Lock()
        self.items: dict[str, dict] = {}
        self.found: dict[str, dict] = {}            # Epidemic search results, by id
        self.jobs: dict[str, dict] = {}             # downloads: id -> {state, path, error}
        self.next: dict[str, str] = {}              # family -> the take its tile drags next
        self.bags: dict[str, tuple[tuple, list[str]]] = {}
        self.last: dict[str, str] = {}
        self.rng = random.Random()
        self._epi = None
        self._ear: dict[str, list[L.Snd]] = {}       # the built-in bank, listed once
        self.settings = self._load()
        self.window = None

    # settings: the tiles, stars and the random switch, for every project (a kit is the user's, not the video's)
    def _load(self) -> dict:
        s = {"stars": [], "random": True, "tab": "sfx"}
        try:
            s.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        if "tiles" not in s:
            s["tiles"] = [{"id": k, "label": label, "query": q, "kind": k, "picks": [], "epi": []}
                          for k, label, q in DEFAULT_TILES]
            s["migrate_stars"] = True             # stars given before tiles existed join their tile (catalog)
        return s

    def _store(self) -> None:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.settings, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(SETTINGS)

    def tile(self, tid: str) -> dict | None:
        return next((t for t in self.settings["tiles"] if t["id"] == tid), None)

    def set(self, fields: dict) -> dict:
        with self.lock:
            for k in ("random", "tab"):
                if k in fields:
                    self.settings[k] = fields[k]
            if "star" in fields:                  # ambiences and music: one list of favourites
                stars = [s for s in self.settings["stars"] if s != fields["star"]]
                if fields.get("on"):
                    stars.append(fields["star"])
                self.settings["stars"] = stars
            self._store()
        return self.settings

    # the tiles (sound-effect playlists)
    def pick(self, tid: str, item_id: str, on: bool) -> dict:
        """★ in a tile: the take joins (or leaves) the tile's playlist."""
        with self.lock:
            t = self.tile(tid)
            t["picks"] = [i for i in t["picks"] if i != item_id] + ([item_id] if on else [])
            self.next.pop(tid, None)
            self._store()
        return t

    def create_tile(self, label: str, query: str) -> dict:
        import re as _re
        label = (label or query or "").strip()[:40] or "?"
        base = _re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "tuile"
        tid, n = f"u-{base}", 2
        while self.tile(tid):
            tid, n = f"u-{base}-{n}", n + 1
        t = {"id": tid, "label": label, "query": (query or label).strip()[:80], "kind": "", "picks": [], "epi": []}
        with self.lock:
            self.settings["tiles"].append(t)
            self._store()
        return t

    def update_tile(self, tid: str, fields: dict) -> dict:
        with self.lock:
            t = self.tile(tid)
            if "label" in fields and fields["label"].strip():
                t["label"] = fields["label"].strip()[:40]
            if "query" in fields:
                t["query"] = fields["query"].strip()[:80]
            self.next.pop(tid, None)
            self._store()
        return t

    def delete_tile(self, tid: str) -> None:
        with self.lock:
            self.settings["tiles"] = [t for t in self.settings["tiles"] if t["id"] != tid]
            self.next.pop(tid, None)
            self._store()

    def search_tile(self, tid: str) -> dict:
        """The tile's English words on Epidemic: its results stay in the tile, to hear and star."""
        from .suggest import sfx_item
        t = self.tile(tid)
        kind = t.get("kind") or "other"
        found = [sfx_item(x, "sfx", kind) for x in self.epidemic().search(t["query"] or t["label"], kind, n=30,
                                                                        max_ms=12000)]
        self._found(found)
        with self.lock:
            t["epi"] = found
            self._store()
        return t

    def members(self, t: dict) -> list[str]:
        """What a tile holds: its starred takes, then the files of its sort (a starting tile) or whose names
        have its words, then its Epidemic results."""
        if t.get("kind"):
            mine = [i for i, it in self.items.items() if it["layer"] == "sfx" and it["family"] == t["kind"]]
        else:
            words = [w for w in (t.get("query") or t["label"]).lower().split() if w]
            mine = [i for i, it in self.items.items() if it["layer"] == "sfx" and words
                    and all(w in f"{it['title']} {it['name']}".lower() for w in words)]
        out = list(dict.fromkeys([*t["picks"], *sorted(mine), *(e["id"] for e in t.get("epi", []))]))
        return [i for i in out if i in self.items or i in self.found]

    def _migrate_stars(self) -> None:
        if not self.settings.pop("migrate_stars", False):
            return
        for sid in list(self.settings["stars"]):
            it = self.items.get(sid)
            t = it and it["layer"] == "sfx" and self.tile(it["family"])
            if t:
                t["picks"].append(sid)
                self.settings["stars"].remove(sid)
        self._store()

    def _warm(self) -> None:
        """The bank's first render takes seconds (imports): done while the page draws the user's own sounds."""
        try:
            first = next(s for v in self._ear.values() for s in v)
            L.render_take(first, seed=1)
        except Exception:
            pass

    # the catalogue
    def media_dir(self) -> Path:
        return Path(self.media())

    def catalog(self) -> dict:
        media = self.media_dir()
        on = lambda k: (self.sources() or {}).get(k, True) is not False      # noqa: E731
        roots = [Path(r) for r in (self.roots() or []) if on("folder")] + ([media] if media.is_dir() else [])
        rows = scan(roots, self.index, skip=[media / "earshot"])
        if on("earshot") and L.earshot_ok():
            if not self._ear:
                self._ear = {kind: L.earshot_sounds(kind) for kind in L.KINDS}
                threading.Thread(target=self._warm, daemon=True).start()
            for kind in L.KINDS:
                for s in self._ear[kind]:
                    rows.append({"id": s.id, "layer": "sfx", "family": kind, "name": s.name, "title": s.name,
                                 "path": "", "dur": s.dur, "sync": s.sync, "source": "earshot",
                                 "licence": s.licence, "where": ""})
        with self.lock:
            self.items = {r["id"]: r for r in rows}
            for t in self.settings["tiles"]:
                self._found(t.get("epi", []), lock=False)
            self._migrate_stars()
            for tid in list(self.next):
                if self.next[tid] not in self.items and self.next[tid] not in self.found:
                    self.next.pop(tid, None)
        ctx = self.context() or {}
        tiles = self.settings["tiles"]
        return {"items": rows, "settings": self.settings, "next": {t["id"]: self.peek(t["id"]) for t in tiles},
                "members": {t["id"]: self.members(t) for t in tiles},
                "epidemic": on("epidemic") and bool(L.epidemic_key()), "media": str(media), "roots": [str(r) for r in roots],
                "script": Path(ctx["script"]).name if ctx.get("script") else "", "suggestions": self.suggestions()}

    # random takes
    def _pool(self, family: str) -> list[str]:
        """The takes a tile draws from: its starred ones, else its short files and bank sounds (a long take
        is dragged by its own row, or starred on purpose), else its Epidemic results."""
        t = self.tile(family)
        if not t:
            return []
        known = lambda i: i in self.items or i in self.found         # noqa: E731
        picks = [i for i in t["picks"] if known(i)]
        if picks:
            return sorted(picks)
        ids = self.members(t)
        local = [i for i in ids if i in self.items]
        cap = RANDOM_MAX.get(t.get("kind") or "", 1e9)
        short = [i for i in local if (self.items[i].get("dur") or 0) <= cap]
        return sorted(short or local or ids)

    def _draw(self, family: str) -> str | None:
        pool = self._pool(family)
        if not pool:
            return None
        key, left = self.bags.get(family, ((), []))
        if key != tuple(pool) or not left:
            left = pool[:]
            self.rng.shuffle(left)
            if len(left) > 1 and left[-1] == self.last.get(family):
                left[0], left[-1] = left[-1], left[0]
        pick = left.pop()
        self.bags[family] = (tuple(pool), left)
        self.last[family] = pick
        return pick

    def peek(self, family: str) -> str | None:
        """The take the family's tile drags next (drawn now if there is none yet)."""
        cur = self.next.get(family)
        if cur not in self._pool(family):
            cur = self._draw(family)
            if cur:
                self.next[family] = cur
        return cur

    def skip(self, family: str) -> str | None:
        with self.lock:
            self.next.pop(family, None)
            return self.peek(family)

    def choose(self, family: str, item_id: str) -> str:
        """Random off: the tile drags this take until another is chosen."""
        with self.lock:
            self.next[family] = item_id
        return item_id

    # making a sound local
    def epidemic(self) -> L.Epidemic:
        if self._epi is None:
            self._epi = L.Epidemic(L.epidemic_key())
        return self._epi

    def local(self, item_id: str, fresh: bool = False) -> dict:
        """{state: ready, path} | {state: working} | {state: error, error}. fresh: a built-in bank sound
        rendered with a new seed (a drag); otherwise its preview take."""
        it = self.items.get(item_id) or self.found.get(item_id)
        if not it:
            return {"state": "error", "error": "son inconnu"}
        if it["source"] == "folder":
            return {"state": "ready", "path": it["path"]}
        if it["source"] == "earshot":
            snd = next((s for s in self._ear.get(it["family"], []) if s.id == item_id), None)
            if not snd:
                return {"state": "error", "error": "son inconnu"}
            if fresh:
                take = L.render_take(snd, seed=self.rng.randint(200, 99999), folder=self.media_dir() / "earshot")
            else:
                take = L.render_take(snd, seed=1)
            return {"state": "ready", "path": take.path, "sync": take.sync, "wave": take.wave, "peak_db": take.peak_db}
        return self._download(it)

    def _download(self, it: dict) -> dict:
        with self.lock:
            job = self.jobs.get(it["id"])
            if job and job["state"] != "error":
                return dict(job)
            self.jobs[it["id"]] = job = {"state": "working"}

        def run():
            try:
                folder = self.media_dir()
                if it["layer"] == "music":
                    path = self.epidemic().download_music(it["uid"], it["title"], it.get("artist", ""), folder)
                else:
                    snd = L.Snd(it["id"], "epidemic", it["family"] or "other", it["title"], preview=it.get("preview", ""))
                    path = Path(self.epidemic().download(snd, folder).path)
                job.update(state="ready", path=str(path))
            except Exception as e:  # shown on the row
                self._epi = None
                job.update(state="error", error=f"{type(e).__name__}: {e}")
        threading.Thread(target=run, daemon=True).start()
        return dict(job)

    def wait(self, item_id: str, seconds: float, fresh: bool = False) -> dict:
        import time
        t0 = time.time()
        r = self.local(item_id, fresh)
        while r["state"] == "working" and time.time() - t0 < seconds:
            time.sleep(0.25)
            r = self.local(item_id, fresh)
        return r

    # the drag
    def drag(self, target: str) -> dict:
        """target: an item id, or « family:<name> » (the tile: its next take, then the one after).
        The OS drag starts only if the mouse button is still held."""
        family = target.split(":", 1)[1] if target.startswith("family:") else ""
        with self.lock:
            item_id = self.peek(family) if family else target
        if not item_id:
            return {"state": "error", "error": "aucun son dans cette famille"}
        it = self.items.get(item_id) or self.found.get(item_id) or {}
        quick = it.get("source") != "epidemic" or it.get("layer") != "music"
        r = self.wait(item_id, 12 if quick else 0, fresh=True)
        if r["state"] != "ready":
            return {**r, "id": item_id}
        from ..sourcing.drag import drag_files
        effect = drag_files(self.window, [r["path"]]) if self.window else "none"
        dropped = effect not in ("released", "none", "None")
        out = {"state": "ready", "dropped": dropped, "id": item_id, "path": r["path"]}
        if dropped:
            try:
                out["level"] = (sfx_gain(it.get("family") or "other", r["peak_db"]) if "peak_db" in r
                                else self.level_of(r["path"], it.get("layer", "sfx"), it.get("family", "")))
            except Exception:
                pass
        if family and dropped and self.settings.get("random", True):
            out["next"] = self.skip(family)
        if dropped and it.get("source") == "epidemic":
            out["rescan"] = True                    # the file is in médias now: a folder item
        return out

    # Epidemic search
    def _found(self, rows: list[dict], lock: bool = True) -> list[dict]:
        if not lock:
            self.found.update({r["id"]: r for r in rows})
            return rows
        with self.lock:
            self.found.update({r["id"]: r for r in rows})
        return rows

    def search(self, layer: str, term: str, family: str = "") -> list[dict]:
        from .suggest import music_item, sfx_item
        t = self.tile(family) if family else None
        term = (term or "").strip() or {"sfx": (t and (t["query"] or t["label"])) or "whoosh", "amb": "ambience",
                                        "music": "documentary"}[layer]
        family = (t and t.get("kind")) or ("other" if t else family)
        if layer == "music":
            return self._found([music_item(r) for r in self.epidemic().search_music(term)])
        amb = layer == "amb"
        return self._found([sfx_item(s, layer, family or "other") for s in self.epidemic().search(
            term, family or "other", n=30, max_ms=None if amb else 12000, min_ms=15000 if amb else None)])

    def similar(self, item_id: str) -> list[dict]:
        """« More like this one »: Epidemic's own neighbours of a track or a sound."""
        from .suggest import music_item, sfx_item
        it = self.found.get(item_id) or self.items.get(item_id) or {}
        if it.get("source") != "epidemic":
            raise ValueError(tr("seulement pour un son d'Epidemic"))
        if it["layer"] == "music":
            return self._found([music_item(r) for r in self.epidemic().similar_music(it["uid"])])
        return self._found([sfx_item(x, it["layer"], it.get("family") or "other")
                            for x in self.epidemic().similar_sfx(it["uid"], it.get("family") or "other")])

    # music and ambiences for the script, on request
    def _ctx(self) -> dict:
        ctx = dict(self.context() or {})
        if not ctx.get("script") or not ctx.get("out"):
            raise ValueError(tr("ouvrez d'abord le projet et son script dans la fenêtre Autocut"))
        if not L.epidemic_key():
            raise ValueError(tr("les propositions cherchent sur Epidemic : enregistrez votre clé sur la page Sons"))
        return ctx

    def suggestions(self) -> dict:
        from . import suggest
        ctx = self.context() or {}
        data = suggest.load(Path(ctx["out"])) if ctx.get("out") else {}
        for block in data.values():
            for c in block.get("cues", []):
                self._found(c.get("results", []))
        return data

    def suggest(self, layer: str, brief: str) -> dict:
        from . import suggest
        block = suggest.make(self._ctx(), layer, brief, self.epidemic())
        for c in block["cues"]:
            self._found(c["results"])
        return block

    def redo(self, layer: str, cue_id: str, instruction: str) -> dict:
        from . import suggest
        c = suggest.redo(self._ctx(), layer, cue_id, instruction, self.epidemic())
        self._found(c["results"])
        return c

    def research(self, layer: str, cue_id: str, queries: list[str], bpm=None) -> dict:
        from . import suggest
        c = suggest.research(self._ctx(), layer, cue_id, queries, self.epidemic(), bpm)
        self._found(c["results"])
        return c

    # waveforms (asked for the rows on screen)
    def waves(self, ids: list[str]) -> dict:
        def one(item_id: str):
            it = self.items.get(item_id)
            if not it:
                return item_id, None
            if it["source"] == "earshot":
                r = self.local(item_id)
                if r["state"] != "ready":
                    return item_id, None
                return item_id, {"wave": r.get("wave", []), "sync": r.get("sync", 0),
                                 "level": sfx_gain(it["family"], r.get("peak_db", -6.0))}
            return item_id, self.measured(it)
        from ..media import ensure_ffmpeg
        ensure_ffmpeg()
        with ThreadPoolExecutor(6) as ex:
            res = dict(ex.map(one, ids[:60]))
        self.index.save()
        return {k: v for k, v in res.items() if v}

    def measured(self, it: dict) -> dict:
        """Waveform, hit point and the clip level to set in Premiere: sound effects from their peak (in the
        editor's -20..-5 dB), beds and music from their loudness. Measured once per file."""
        got = self.index.get(it["key"])
        bed = it["layer"] in BED
        if "wave" not in got or (bed and "lufs" not in got):
            p = Path(it["path"])
            try:
                if bed:
                    m = measure_bed(p, it.get("dur") or 0.0)
                else:
                    m = L.measure(L.decode(p, 16000), 16000, it["family"])
            except (subprocess.CalledProcessError, OSError, ValueError):
                m = {"wave": [], "sync": 0.0, "peak_db": -120.0, "lufs": None}
            self.index.put(it["key"], **m)
            got = self.index.get(it["key"])
        if bed:
            level = bed_gain(it["layer"], got.get("lufs"))
        else:
            level = sfx_gain(it["family"], got["peak_db"]) if got.get("peak_db", -120) > -100 else None
        return {"wave": got.get("wave", []), "sync": got.get("sync", 0.0), "level": level}

    def level_of(self, path: str, layer: str, family: str = "") -> float | None:
        """For a file just downloaded and dragged: the level to give it."""
        p = Path(path)
        try:
            st = p.stat()
        except OSError:
            return None
        it = {"key": Index.key(p, st), "path": str(p), "layer": layer, "family": family or "other"}
        r = self.measured(it)
        self.index.save()
        return r["level"]

    def allowed(self, path: Path) -> bool:
        """Only sounds on the board are played to the page."""
        p = str(path.resolve()).lower()
        roots = [Path(r) for r in self.roots() or []] + [self.media_dir(), L.CACHE]
        return any(p.startswith(str(r.resolve()).lower()) for r in roots)


# --- the page ---------------------------------------------------------------------------------------

def serve(board: Board):
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _send(self, body: bytes, ctype: str, code: int = 200, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data):
            self._send(json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def do_GET(self):
            from urllib.parse import parse_qs, urlparse
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path in ("/", "/board.html"):
                    return self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
                if u.path == "/i18n.js":
                    from ..i18n import js
                    return self._send(js().encode(), "text/javascript; charset=utf-8")
                if u.path == "/api/catalog":
                    return self._json({"ok": True, **board.catalog()})
                if u.path == "/snd":                # with Range: long music seeks without loading it all
                    p = Path(q.get("path", ""))
                    if not (p.is_file() and board.allowed(p)):
                        return self.send_error(404)
                    size = p.stat().st_size
                    rng = self.headers.get("Range", "")
                    a, b = 0, size - 1
                    if rng.startswith("bytes="):
                        lo, _, hi = rng[6:].partition("-")
                        a = int(lo) if lo else max(0, size - int(hi))
                        b = min(size - 1, int(hi)) if hi and lo else size - 1
                    with p.open("rb") as fh:
                        fh.seek(a)
                        body = fh.read(b - a + 1)
                    ctype = {".mp3": "audio/mpeg", ".flac": "audio/flac", ".ogg": "audio/ogg",
                             ".m4a": "audio/mp4"}.get(p.suffix.lower(), "audio/wav")
                    extra = {"Accept-Ranges": "bytes", **({"Content-Range": f"bytes {a}-{b}/{size}"} if rng else {})}
                    return self._send(body, ctype, 206 if rng else 200, extra)
            except Exception as e:
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"})
            self.send_error(404)

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
            try:
                if self.path == "/api/waves":
                    return self._json({"ok": True, "waves": board.waves(list(data.get("ids", [])))})
                if self.path == "/api/settings":
                    return self._json({"ok": True, "settings": board.set(data)})
                if self.path == "/api/skip":
                    return self._json({"ok": True, "next": board.skip(data["family"])})
                if self.path == "/api/choose":
                    return self._json({"ok": True, "next": board.choose(data["family"], data["id"])})
                if self.path == "/api/local":          # a preview: the file to play
                    return self._json({"ok": True, **board.local(data["id"])})
                if self.path == "/api/search":
                    return self._json({"ok": True, "found": board.search(data.get("layer", "sfx"), data.get("q", ""),
                                                                         data.get("family", ""))})
                if self.path == "/api/tile":             # create, update, delete, star in, search Epidemic
                    act = data.get("action")
                    if act == "create":
                        t = board.create_tile(data.get("label", ""), data.get("query", ""))
                        if data.get("search") and L.epidemic_key():
                            t = board.search_tile(t["id"])
                    elif act == "update":
                        t = board.update_tile(data["id"], data)
                    elif act == "delete":
                        board.delete_tile(data["id"])
                        t = None
                    elif act == "pick":
                        t = board.pick(data["id"], data["item"], bool(data.get("on")))
                    elif act == "search":
                        t = board.search_tile(data["id"])
                    else:
                        return self.send_error(400)
                    return self._json({"ok": True, "tile": t})
                if self.path == "/api/similar":
                    return self._json({"ok": True, "found": board.similar(data["id"])})
                if self.path == "/api/suggest":           # the AI reads the script: up to a minute or two
                    return self._json({"ok": True, "block": board.suggest(data["layer"], data.get("brief", ""))})
                if self.path == "/api/redo":
                    return self._json({"ok": True, "cue": board.redo(data["layer"], data["cue"],
                                                                     data.get("instruction", ""))})
                if self.path == "/api/research":
                    bpm = (data.get("bpm_min") or 0, data.get("bpm_max") or 0) if "bpm_min" in data else None
                    return self._json({"ok": True, "cue": board.research(data["layer"], data["cue"],
                                                                         list(data.get("queries", [])), bpm)})
                if self.path == "/api/reveal":
                    p = Path(data.get("path", ""))
                    if p.exists() and board.allowed(p):
                        subprocess.Popen(["explorer", "/select,", str(p)])
                    return self._json({"ok": True})
            except Exception as e:
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"})
            self.send_error(404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(PAGE.parent)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/board.html"


class BoardApi:
    """What the board page may call (window.pywebview.api) in the Autocut window: the native drag."""

    def __init__(self, board: Board):
        self._b = board

    def drag(self, target: str) -> dict:
        return self._b.drag(target)

    def prepare(self, item_id: str) -> dict:
        r = self._b.local(item_id)
        return {k: v for k, v in r.items() if k != "wave"}
