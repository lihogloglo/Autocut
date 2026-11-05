"""Game packs: what one player taught Moments about a game, in a file friends use on their own rushes.

A pack (<name>.fauxpack.json) holds kinds of moment that work without the author's rushes: every place
a kind pointed at a stretch or a frame of a rush now holds what it stood for.

  {"format": "fauxraccord-moments-pack", "version": 1, "name": "Rust – raids", "game": "Rust",
   "about": "…", "made_with": {"vision": "clip"},
   "types": [{"id": "u-menus", "name": "Menus", "signals": [{"learn": true}], …,
              "examples": {"pos": [], "neg": [],
                           "pos_vectors": {"model": "clip", "spans": 1, "image": rows, "sound": rows}}},
             {"id": "u-kill", "signals": [{"zone": [x, y, w, h], "look": {"vector": [...], "shape": [9, 24]}}]},
             {"id": "u-boss", "signals": [{"like": [{"vector": [...], "model": "clip"}], "min": 0.85}]}]}

  examples (stretches) and the ✓ / ✗ of that kind -> example seconds: image (CLIP of the nearest stored
                                       frame) and sound (YAMNet) fingerprints, at most SAMPLE seconds
                                       per kind and side (learn.pack_rows: int8, ~1 kB a second)
  "like" {"rush", "t"}              -> {"vector", "model"}: the frame's image fingerprint
  "look" {"rush", "t"}              -> {"vector", "shape"}: the zone as it looked then
Zones are fractions of the picture: they stay. Moments, file paths and what the last search learned
are left out. Fingerprints made by another image model are skipped by whoever reads them (learn.stored).

An imported pack is copied to %APPDATA%/fauxraccord/packs/ and listed with the presets ("pack:<id>").
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import numpy as np

from .index import ROOT, RushIndex
from .rules import Moment, MomentType

FORMAT, VERSION = "fauxraccord-moments-pack", 1
SUFFIX = ".fauxpack.json"
PACKS = Path(os.environ.get("APPDATA", Path.home())) / "fauxraccord" / "packs"
SAMPLE = 60                 # example seconds kept per kind and per side
MAX_BYTES = 20_000_000


class PackError(ValueError):
    """Not a pack, or one this version cannot read (the message is French, for tr())."""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "pack"


# --- export ------------------------------------------------------------------------------------

def _seconds(ix: RushIndex, spans: list[dict]):
    from .learn import features, seconds_of
    X = features(ix)
    return X[seconds_of(spans, ix)[: len(X)] & ix.known()[: len(X)]]


def _vectors(indexes: list[RushIndex], spans: list[dict]) -> dict | None:
    """Example seconds of the spans as stored fingerprints (None: none of those rushes is read)."""
    from .learn import SOUND_DIM, _present, pack_rows
    if not spans:
        return None
    rows = [r for ix in indexes if ix.done() for r in [_seconds(ix, spans)] if len(r)]
    if not rows:
        return None
    X = np.vstack(rows)
    if len(X) > SAMPLE:                               # evenly spread: neighbours stay neighbours
        X = X[np.linspace(0, len(X) - 1, SAMPLE).round().astype(int)]
    d = X.shape[1] - SOUND_DIM
    out = {"model": indexes[0].meta.get("vision", "clip"), "spans": len(spans)}
    for name, block in (("image", X[:, :d]), ("sound", X[:, d:])):
        block = _present(block)
        if len(block):
            out[name] = pack_rows(block)
    return out if "image" in out or "sound" in out else None


def _index_of(rush: str, indexes: list[RushIndex], root: Path) -> RushIndex:
    me = str(Path(rush).resolve()).lower()
    return next((ix for ix in indexes if str(ix.path).lower() == me), None) or RushIndex(Path(rush), root)


def _signal(sig: dict, indexes: list[RushIndex], root: Path):
    """The signal with every rush reference replaced by what it stood for (None: it cannot be)."""
    if "opposite" in sig:
        inner = _signal(sig["opposite"], indexes, root)
        return {**sig, "opposite": inner} if inner else None
    if "any" in sig:
        inner = [x for x in (_signal(s, indexes, root) for s in sig["any"]) if x]
        return {**sig, "any": inner} if inner else None
    out = dict(sig)
    for key in ("like", "unlike"):
        if key in sig:
            items = []
            for e in sig[key]:
                if "vector" in e:
                    items.append(e)
                    continue
                ix = _index_of(e["rush"], indexes, root)
                times, emb = ix.frames()
                if len(times):
                    v = emb[int(np.abs(times - float(e["t"])).argmin())]
                    items.append({"vector": [round(float(x), 4) for x in v], "model": ix.meta.get("vision", "clip")})
            if key == "like" and not items:
                return None
            out[key] = items
    if "look" in sig and "rush" in sig["look"]:
        from .zones import look_shape, looks
        ix = _index_of(sig["look"]["rush"], indexes, root)
        if not ix.frames()[0].size:
            return None
        v = looks(ix, sig["zone"])[ix.frame_at(float(sig["look"]["t"]))]
        out["look"] = {"vector": [round(float(x), 4) for x in v], "shape": look_shape(ix, sig["zone"])}
    return out


def changed(kind: MomentType, preset: str, marks: list[Moment]) -> bool:
    """A kind worth sharing: made by the user, tuned, or taught by ✓ and ✗ (one side alone teaches nothing)."""
    kept = {m.kept for m in marks if m.type == kind.id and m.kept is not None}
    if kind.user or kept == {True, False}:
        return True
    from .rules import load_preset
    try:
        base = next((t for t in load_preset(preset) if t.id == kind.id), None) if preset else None
    except (OSError, ValueError, KeyError):
        base = None
    if base is None:
        return True
    mine, theirs = kind.to_json(), base.to_json()
    for d in (mine, theirs):
        d.pop("explain", None)
        d.pop("enabled", None)
    return mine != theirs


def kind_json(kind: MomentType, marks: list[Moment], indexes: list[RushIndex], root: Path = ROOT) -> dict | None:
    """One kind as a pack holds it; None when what it was taught is not read (no fingerprint to keep)."""
    mine = [m for m in marks if m.type == kind.id and m.kept is not None]
    pos = list(kind.examples.get("pos", [])) + [kind.core(m) for m in mine if m.kept]
    neg = list(kind.examples.get("neg", [])) + [kind.core(m) for m in mine if not m.kept]
    d = kind.to_json()
    d["explain"] = {}
    signals = []
    for s in kind.signals:
        x = _signal(s, indexes, root)
        if x is None:
            return None
        signals.append(x)
    d["signals"] = signals
    ex = {"pos": [], "neg": []}
    for side, spans in (("pos", pos), ("neg", neg)):
        old = kind.examples.get(f"{side}_vectors")        # a kind that came from a pack keeps its fingerprints
        v = _vectors(indexes, spans) or old
        if v:
            ex[f"{side}_vectors"] = v
    if any("learn" in s for s in kind.signals) and "pos_vectors" not in ex:
        return None
    d["examples"] = ex
    return d


def export(project, kinds: list[MomentType], path: Path, name: str = "", game: str = "", about: str = "",
           root: Path = ROOT) -> dict:
    """Write the pack. {"path", "kinds": names written, "skipped": names left out, "bytes"}."""
    path = Path(path)
    if not path.name.lower().endswith(SUFFIX):
        path = path.with_name(path.name.removesuffix(".json") + SUFFIX)
    indexes = [RushIndex(Path(r), root) for r in project.rushes if Path(r).exists()]
    types, skipped = [], []
    for k in kinds:
        d = kind_json(k, project.moments, indexes, root)
        (types.append(d) if d else skipped.append(k.name))
    vision = next((ix.meta.get("vision", "clip") for ix in indexes if ix.meta), "clip")
    name = name or path.name[: -len(SUFFIX)]
    data = {"format": FORMAT, "version": VERSION, "name": name, "game": game, "about": about,
            "made_with": {"vision": vision}, "types": types}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)
    return {"path": str(path), "kinds": [t["name"] for t in types], "skipped": skipped, "bytes": path.stat().st_size}


# --- import ------------------------------------------------------------------------------------

def _clean(sig):
    """A signal from a pack, without anything pointing at a file (a pack never reads anyone's disk)."""
    if not isinstance(sig, dict):
        return None
    if "opposite" in sig:
        inner = _clean(sig["opposite"])
        return {**sig, "opposite": inner} if inner else None
    if "any" in sig:
        inner = [x for x in (_clean(s) for s in sig.get("any") or []) if x]
        return {**sig, "any": inner} if inner else None
    out = dict(sig)
    for key in ("like", "unlike"):
        if key in out:
            out[key] = [e for e in out[key] or [] if isinstance(e, dict) and "vector" in e]
            if key == "like" and not out[key]:
                return None
    if "look" in out and not (isinstance(out["look"], dict) and "vector" in out["look"]):
        return None
    return out


def read(path: Path) -> dict:
    """A pack file, checked and cleaned: raises PackError."""
    path = Path(path)
    try:
        if path.stat().st_size > MAX_BYTES:
            raise PackError("Ce fichier est trop gros pour un pack.")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        if isinstance(e, PackError):
            raise
        raise PackError("Ce fichier n'est pas un pack de moments.") from e
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("types"), list):
        raise PackError("Ce fichier n'est pas un pack de moments.")
    if int(data.get("version", 0) or 0) > VERSION:
        raise PackError("Ce pack vient d'une version plus récente de FauxRaccord : mettez-la à jour.")
    types = []
    for t in data["types"]:
        if not isinstance(t, dict) or not t.get("id") or not isinstance(t.get("signals"), list):
            continue
        sigs = [x for x in (_clean(s) for s in t["signals"]) if x]
        if len(sigs) < len(t["signals"]):
            continue                     # a condition it cannot keep would change what the kind finds
        ex = t.get("examples") if isinstance(t.get("examples"), dict) else {}
        ex = {"pos": [], "neg": [], **{k: v for k, v in ex.items() if k in ("pos_vectors", "neg_vectors")}}
        types.append({**{k: v for k, v in t.items() if k in MomentType.__dataclass_fields__},
                      "signals": sigs, "examples": ex, "explain": {}})
    if not types:
        raise PackError("Ce pack ne contient aucun type de moment utilisable.")
    return {**data, "name": str(data.get("name") or path.name.removesuffix(SUFFIX)), "types": types}


def import_pack(path: Path, folder: Path | None = None) -> str:
    """Copy a pack into the packs folder (a pack of the same name is replaced): its preset id."""
    data = read(path)
    folder = Path(folder or PACKS)
    folder.mkdir(parents=True, exist_ok=True)
    pid = slug(data["name"])
    out = folder / f"{pid}{SUFFIX}"
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, out)
    return f"pack:{pid}"


def load(pid: str, folder: Path | None = None) -> dict:
    return read(Path(folder or PACKS) / f"{pid.removeprefix('pack:')}{SUFFIX}")


def imported(folder: Path | None = None) -> list[dict]:
    """The imported packs, as the preset list shows them."""
    out = []
    for f in sorted(Path(folder or PACKS).glob(f"*{SUFFIX}")):
        try:
            d = read(f)
        except PackError:
            continue
        out.append({"id": f"pack:{f.name[: -len(SUFFIX)]}", "name": d["name"], "game": d.get("game", ""),
                    "about": d.get("about", ""), "types": len(d["types"]), "pack": True})
    return out


_SAME = ("mode", "combine", "signals", "before", "after", "gap", "min_len", "sensitivity", "remove", "examples")


def add_to(project, pid: str, folder: Path | None = None) -> dict:
    """The pack's kinds added to the project's: ids and names that clash get the pack's name, a kind
    already there (the same pack added twice) is skipped. {"added", "renamed", "same": [names], "name"}."""
    data = load(pid, folder)
    ids = {t.id for t in project.types}
    names = {t.name.lower() for t in project.types}
    have = [{f: t.to_json()[f] for f in _SAME} for t in project.types]
    added, renamed, same = [], [], []
    for d in data["types"]:
        k = MomentType.from_json(d)
        if {f: k.to_json()[f] for f in _SAME} in have:
            same.append(k.name)
            continue
        k.user, k.enabled = True, True
        if k.id in ids or k.name.lower() in names:
            base, n = f"{k.id}-{slug(data['name'])}", 2
            k.id = base
            while k.id in ids:
                k.id, n = f"{base}-{n}", n + 1
            if k.name.lower() in names:
                base, n = f"{k.name} ({data['name']})", 2
                k.name = base
                while k.name.lower() in names:
                    k.name, n = f"{base} {n}", n + 1
            renamed.append(k.name)
        ids.add(k.id)
        names.add(k.name.lower())
        project.types.append(k)
        added.append(k.name)
    return {"added": added, "renamed": renamed, "same": same, "name": data["name"]}
