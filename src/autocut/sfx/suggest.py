"""Music and ambiences for a script, on request (a click on the sound board), steered by the editor's brief.

The AI reads the whole script and the brief, and says where the music should change (only at real turns,
not at every heading) and what each part needs: its feel in words, a tempo range, and precise Epidemic
searches (instruments, texture, genre, era) instead of the generic words every library answers with.
Ambiences only where the script puts us somewhere that can be heard, true to the period. Each part's
searches run on Epidemic; the results are suggestions on the board, to listen to and drag. Nothing is
placed by itself. One part can be redone with an instruction, or searched again with edited queries.

Saved per project in « <video> - sons/suggestions.json ».
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..i18n import tr
from . import library as L

FILE = "suggestions.json"

MUSIC_INSTRUCTIONS = """Tu es superviseur musical d'une chaîne YouTube de documentaires et d'essais vidéo. Tu \
reçois le script entier (une ligne par phrase : [numéro] (durée) texte, sous ses titres de section) et la demande du \
vidéaste. Découpe la vidéo en parties musicales et dis, pour chacune, ce que la musique doit faire sous la voix et \
comment la trouver dans le catalogue Epidemic Sound.

Règles :
- La demande du vidéaste prime sur tout : le genre, les instruments, les références, ce qu'il refuse.
- La musique change seulement à un vrai tournant du récit (changement de ton, de période, de tension, une révélation), \
pas à chaque titre : une partie dure en général de 40 s à 3 min. Les parties se suivent sans trou, de la première \
phrase à la dernière ; first et last sont des numéros de phrase.
- Deux parties voisines doivent sonner différemment : c'est le contraste qui fait sentir le tournant.
- feel : ce que la musique fait, en français, concret : instruments, tempo, texture, énergie, la place qu'elle laisse \
à la voix. Une ou deux phrases.
- queries : 3 ou 4 recherches en anglais pour le catalogue, de 2 à 5 mots, chacune sous un autre angle (instruments et \
texture ; genre précis ; humeur précise ; époque ou lieu quand le passage en a un). Les mots que portent les vrais \
titres et tags : « solo cello, sparse », « analog synth pulse », « baroque harpsichord », « dusty lo-fi drums », \
« dark ambient drone », « pizzicato strings, playful ». Une recherche dit ce qu'on entend, jamais le sujet du \
passage : pas de political, economic, historical, investigative, analytical, intellectual, academic, realism. \
Interdits aussi sauf si le vidéaste les emploie : cinematic, epic, documentary, inspiring, corporate, background, \
emotional, uplifting, trailer, motivational, thriller.
- bpm_min et bpm_max : la fourchette de tempo voulue ; 0 et 0 quand elle importe peu (nappes, ambient).
- title : un nom court pour la partie, en français."""

AMB_INSTRUCTIONS = """Tu es designer sonore d'une chaîne YouTube de documentaires et d'essais vidéo. Tu reçois le \
script entier (une ligne par phrase : [numéro] (durée) texte, sous ses titres de section) et la demande du vidéaste. \
Dis où une ambiance (un fond sonore : un lieu, une époque, une situation) rendrait le récit concret, et comment la \
trouver dans les bruitages d'Epidemic Sound.

Règles :
- La demande du vidéaste prime sur tout.
- Seulement les passages qui nous mettent quelque part qu'on peut entendre : une rue de Paris en 1789, une tranchée, \
un marché, une salle des machines, un orage, une salle de classe. Rien sur les passages abstraits : les parties \
peuvent laisser des trous. first et last sont des numéros de phrase.
- Des sons qui durent (une foule, la pluie, des machines, la campagne la nuit), pas des événements ponctuels (un coup, \
une porte, une épée, une explosion) : ceux-là sont des bruitages, posés à la main.
- Fidèle à l'époque et au lieu : pas de circulation ni de bourdonnement électrique avant leur temps, les bons oiseaux, \
la bonne langue des foules.
- feel : ce qu'on entend, en français, couche par couche (le fond, puis les détails). Une ou deux phrases.
- queries : 3 ou 4 recherches en anglais, de 2 à 5 mots, avec les mots des bruitages : le lieu ou la matière puis un \
détail (« crowd, market, distant », « rain on canvas tent », « horse carriage, cobblestone », « crickets, night, \
rural », « factory, steam machinery »). Jamais ambience, background ou atmosphere seuls.
- title : le lieu, court, en français."""


def _schema(music: bool) -> dict:
    fields = {"first": {"type": "integer"}, "last": {"type": "integer"}, "title": {"type": "string"},
              "feel": {"type": "string"}, "queries": {"type": "array", "items": {"type": "string"}}}
    if music:
        fields.update(bpm_min={"type": "integer"}, bpm_max={"type": "integer"})
    return {"type": "object", "additionalProperties": False, "required": ["cues"], "properties": {"cues": {
        "type": "array", "items": {"type": "object", "additionalProperties": False, "required": list(fields),
                                   "properties": fields}}}}


# --- items the board shows (also used by its own searches) -------------------------------------------

def music_item(r: dict) -> dict:
    return {"id": f"epidemic:{r['uid']}", "uid": r["uid"], "layer": "music", "family": "", "name": r["title"],
            "title": r["title"], "artist": r["artist"], "dur": r["dur"], "bpm": r["bpm"], "tags": r["tags"],
            "stems": r["stems"], "preview": r["preview"], "source": "epidemic", "licence": "Epidemic Sound"}


def sfx_item(s: L.Snd, layer: str, family: str = "other") -> dict:
    return {"id": s.id, "uid": s.id.split(":", 1)[1], "layer": layer, "family": family, "name": s.name,
            "title": s.name, "dur": s.dur, "preview": s.preview, "source": "epidemic", "licence": "Epidemic Sound"}


# --- the script ---------------------------------------------------------------------------------------

def _script(ctx: dict):
    from ..sourcing.script import parse_script
    from ..storyboard import script_lines, sentence_windows
    if not ctx.get("script") or not Path(ctx["script"]).is_file():
        raise ValueError(tr("pas de script"))
    doc = parse_script(Path(ctx["script"]))
    derush = Path(ctx["derush"]) if ctx.get("derush") and Path(ctx["derush"]).is_file() else None
    edit = Path(ctx["edit"]) if ctx.get("edit") and Path(ctx["edit"]).is_file() else None
    where = sentence_windows(derush, edit)
    return doc, script_lines(doc, where), where


def _engine(ctx: dict) -> str:
    from ..sourcing import llm
    llm.set_quality(ctx.get("quality") or "best")
    engines = llm.candidates(ctx.get("engine") or "auto")
    if not engines:
        raise ValueError(tr("aucune IA connectée : page IA de la fenêtre Autocut"))
    return engines[0]


def _clean(raw: list[dict], ids: list[int], music: bool, lo: int | None = None, hi: int | None = None) -> list[dict]:
    """Parts inside the script (or inside one part, for a redo), in order, with usable searches."""
    lo = ids[0] if lo is None else lo
    hi = ids[-1] if hi is None else hi
    out = []
    for c in sorted(raw, key=lambda c: c.get("first", 0)):
        a, b = max(lo, int(c.get("first", lo))), min(hi, int(c.get("last", hi)))
        if b < a:
            continue
        qs = [q.strip() for q in c.get("queries", []) if isinstance(q, str) and q.strip()][:4]
        title = (c.get("title") or "").strip()
        if not qs:
            qs = [title] if title else []
        if not qs:
            continue
        cue = {"first": a, "last": b, "title": title, "feel": (c.get("feel") or "").strip(), "queries": qs}
        if music:
            bmin, bmax = int(c.get("bpm_min") or 0), int(c.get("bpm_max") or 0)
            if bmin and bmax and bmin > bmax:
                bmin, bmax = bmax, bmin
            cue.update(bpm_min=max(0, bmin), bpm_max=max(0, bmax))
        out.append(cue)
    return out


def _timing(cue: dict, lines: list[dict], where: dict) -> dict:
    part = [x for x in lines if cue["first"] <= x["id"] <= cue["last"]]
    cue["duration"] = round(sum(x["s"] for x in part), 1)
    cue["start"] = round(where[cue["first"]][0], 2) if cue["first"] in where else None
    cue["end"] = round(where[cue["last"]][1], 2) if cue["last"] in where else None
    cue["text"] = " ".join(x["text"] for x in part)[:240]
    return cue


def _ask(engine: str, layer: str, doc, lines: list[dict], brief: str, extra: str = "") -> list[dict]:
    from ..i18n import localize_prompt
    from ..sourcing import llm
    from ..storyboard import _script_payload
    music = layer == "music"
    content = [f"Demande du vidéaste :\n{brief.strip() or '(aucune : choisis ce qui sert le mieux ce récit)'}",
               "Script :\n" + _script_payload(doc, lines)[:60000]] + ([extra] if extra else [])
    answer = llm.ask(engine, localize_prompt(MUSIC_INSTRUCTIONS if music else AMB_INSTRUCTIONS), content,
                     _schema(music), effort="high")
    return answer.get("cues", [])


# --- searching Epidemic for one part --------------------------------------------------------------------

def search_cue(epi: L.Epidemic, layer: str, cue: dict, n: int = 12) -> list[dict]:
    """Each query's best results, taken in turns, so every angle of the part is heard."""
    per: list[list[dict]] = []
    for q in cue["queries"]:
        try:
            if layer == "music":
                bpm = (cue.get("bpm_min") or 0, cue.get("bpm_max") or 0)
                per.append([music_item(r) for r in epi.search_music(q, n=8, bpm=bpm)])
            else:
                per.append([sfx_item(s, "amb") for s in epi.search(q, "other", n=8, max_ms=None, min_ms=15000)])
        except Exception:
            per.append([])
    out, seen = [], set()
    for i in range(max((len(p) for p in per), default=0)):
        for qi, p in enumerate(per):
            if i < len(p) and p[i]["id"] not in seen:
                seen.add(p[i]["id"])
                p[i]["query"] = cue["queries"][qi]
                out.append(p[i])
    return out[:n]


# --- saved per project ----------------------------------------------------------------------------------

def load(out: Path) -> dict:
    try:
        return json.loads((out / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(out: Path, data: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / (FILE + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(out / FILE)


def make(ctx: dict, layer: str, brief: str, epi: L.Epidemic) -> dict:
    """The whole script: parts, then their searches."""
    out = Path(ctx["out"])
    doc, lines, where = _script(ctx)
    if not lines:
        raise ValueError(tr("script vide"))
    engine = _engine(ctx)
    music = layer == "music"
    cues = _clean(_ask(engine, layer, doc, lines, brief), [x["id"] for x in lines], music)
    for i, c in enumerate(cues, 1):
        c["id"] = f"{layer[0]}{i:02d}"
        _timing(c, lines, where)
        c["results"] = search_cue(epi, layer, c)
    data = load(out)
    data[layer] = {"brief": brief, "engine": engine, "created": time.strftime("%Y-%m-%d %H:%M"),
                   "timed": bool(where), "cues": cues}
    _save(out, data)
    return data[layer]


def redo(ctx: dict, layer: str, cue_id: str, instruction: str, epi: L.Epidemic) -> dict:
    """One part again, with the editor's instruction (« plus sombre », « sans percussions »…)."""
    out = Path(ctx["out"])
    data = load(out)
    block = data[layer]
    k = next(i for i, c in enumerate(block["cues"]) if c["id"] == cue_id)
    cur = block["cues"][k]
    doc, lines, where = _script(ctx)
    near = [f"phrases {c['first']}-{c['last']} : {c['title']} — {c['feel']}"
            for c in block["cues"][max(0, k - 1):k + 2] if c is not cur]
    extra = (f"Une seule partie, phrases {cur['first']} à {cur['last']}, gardées telles quelles. "
             + ("Parties voisines :\n" + "\n".join(near) + "\n" if near else "")
             + f"Version actuelle : {cur['title']} — {cur['feel']} — recherches : {'; '.join(cur['queries'])}\n"
             + (f"Demande du vidéaste pour cette partie : {instruction.strip()}" if instruction.strip()
                else "Propose une autre direction que la version actuelle, avec d'autres recherches."))
    raw = _ask(_engine(ctx), layer, doc, lines, block.get("brief", ""), extra)
    new = _clean(raw, [x["id"] for x in lines], layer == "music", cur["first"], cur["last"])
    if not new:
        raise ValueError(tr("l'IA n'a rien proposé"))
    c = {**new[0], "first": cur["first"], "last": cur["last"], "id": cur["id"]}
    if instruction.strip():
        c["instruction"] = instruction.strip()
    _timing(c, lines, where)
    c["results"] = search_cue(epi, layer, c)
    block["cues"][k] = c
    _save(out, data)
    return c


def research(ctx: dict, layer: str, cue_id: str, queries: list[str], epi: L.Epidemic,
             bpm: tuple[int, int] | None = None) -> dict:
    """The editor's own searches for a part (no AI)."""
    out = Path(ctx["out"])
    data = load(out)
    c = next(c for c in data[layer]["cues"] if c["id"] == cue_id)
    c["queries"] = [q.strip() for q in queries if q.strip()][:6] or c["queries"]
    if bpm is not None and layer == "music":
        c["bpm_min"], c["bpm_max"] = int(bpm[0] or 0), int(bpm[1] or 0)
    c["results"] = search_cue(epi, layer, c)
    _save(out, data)
    return c
