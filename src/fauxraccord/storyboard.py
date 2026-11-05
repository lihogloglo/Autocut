"""fauxraccord-storyboard: what to make to illustrate the script, in a chosen style.

1. Style bible: the AI turns the user's style request (and reference images) into shared rules: palette,
   light, materials, camera, typography, techniques and what each is for. Every later request carries it,
   so sixty separate shots still look like one film.
2. Beats: the script is cut into beats (one visual idea, consecutive sentences, ~6 s, from the derush
   timings when there are some). Each beat gets a technique, what we see, the motion, an image prompt, a
   video prompt, a structured scene (for Blender / an MCP agent later), production notes.
3. Output (<script> - storyboard/): storyboard.json, storyboard.md, a card per beat (PNG, named like the
   illustration exports: S014-01 …) and a Premiere XML with the cards over the edit, at their beats.
   The Premiere panel can place the same cards in the open sequence.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from .i18n import tr
from .sourcing import llm
from .sourcing.export import slug
from .sourcing.script import ScriptDoc, parse_script

FACE, ARCHIVE = "face caméra", "archive"
WORDS_PER_SECOND = {"fr": 2.7, "en": 2.5}   # speech rate, to estimate durations without a derush
BATCH_SENTENCES = 45


def default_out(script: Path) -> Path:
    return script.parent / f"{script.stem} - storyboard"


# --- Prompts ---------------------------------------------------------------------------------------

STYLE_INSTRUCTIONS = """Tu es directeur artistique d'une chaîne YouTube documentaire. À partir de la demande de \
style du vidéaste (et des images de référence s'il y en a) et de son script, écris la « bible de style » qui rendra \
toutes les illustrations de la vidéo cohérentes entre elles.

Les références à des créateurs ou à des œuvres (« comme Fern », « comme Lemmino ») sont traduites en caractéristiques \
visuelles concrètes : formes, matières, lumière, couleurs, rythme, mouvements de caméra. Les générateurs d'images ne \
connaissent pas ces noms.

Champs (en français, sauf prompt_style) :
- summary : le style en 2 ou 3 phrases.
- palette : 4 à 7 couleurs (nom, code hex), de la plus sombre à la plus claire, avec leur rôle dans le nom.
- lighting, materials, camera, typography, transitions : une ou deux phrases chacun.
- motifs : 2 à 5 éléments visuels récurrents qui peuvent lier les plans entre eux.
- techniques : 2 à 5 techniques de fabrication tirées de la demande (ex. « 3D lowpoly Blender », « motion design \
After Effects », « carte animée », « typographie cinétique »), chacune avec son rendu (look) et ce qu'elle illustre le \
mieux (use_for). Pas « face caméra » ni « archive » : elles sont ajoutées d'office.
- avoid : ce qu'il faut éviter pour rester dans le style.
- prompt_style : mots-clés en anglais à ajouter à la fin de chaque prompt d'image pour obtenir ce style \
(25 à 45 mots)."""

STYLE_SCHEMA = {"type": "object", "additionalProperties": False,
                "required": ["summary", "palette", "lighting", "materials", "camera", "typography", "transitions",
                             "motifs", "techniques", "avoid", "prompt_style"],
                "properties": {
                    "summary": {"type": "string"},
                    "palette": {"type": "array", "items": {
                        "type": "object", "additionalProperties": False, "required": ["name", "hex"],
                        "properties": {"name": {"type": "string"}, "hex": {"type": "string"}}}},
                    "lighting": {"type": "string"}, "materials": {"type": "string"}, "camera": {"type": "string"},
                    "typography": {"type": "string"}, "transitions": {"type": "string"},
                    "motifs": {"type": "array", "items": {"type": "string"}},
                    "techniques": {"type": "array", "items": {
                        "type": "object", "additionalProperties": False, "required": ["name", "look", "use_for"],
                        "properties": {"name": {"type": "string"}, "look": {"type": "string"},
                                       "use_for": {"type": "string"}}}},
                    "avoid": {"type": "array", "items": {"type": "string"}},
                    "prompt_style": {"type": "string"}}}

BEATS_INSTRUCTIONS = """Tu es réalisateur et storyboardeur d'une vidéo documentaire YouTube. Tu reçois la bible de \
style, le script entier (phrases numérotées, avec leur durée parlée en secondes) et le passage à découper.

Découpe le passage en plans (« beats ») : une idée visuelle par plan, des phrases consécutives, environ {pace} s par \
plan (entre 3 et 15 s : plusieurs phrases courtes peuvent former un plan, une longue phrase peut être seule). Chaque \
phrase du passage appartient à exactement un plan, dans l'ordre, sans trou.

Pour chaque plan :
- first, last : numéros de la première et de la dernière phrase du plan.
- technique : le nom exact d'une technique de la bible, ou « face caméra » (on garde le présentateur : respirations, \
apartés, moments personnels, rien à montrer) ou « archive » (une vraie image ou vidéo d'archive est plus forte qu'une \
création : personne réelle, événement photographié ou filmé, document authentique).
- title : titre court du plan, en français.
- see : ce qu'on voit, concret et précis, 1 à 3 phrases en français. C'est le storyboard que le monteur doit avoir en tête.
- motion : mouvement de caméra et animation, en français, à l'échelle de la durée du plan.
- image_prompt : prompt autonome en anglais pour un générateur d'images : sujet, composition, cadrage, lumière, \
couleurs, puis les mots-clés de style de la bible (prompt_style). 40 à 90 mots. Vide pour « face caméra ».
- video_prompt : prompt en anglais pour un générateur de vidéo (ce qui bouge, la caméra), vide si inutile.
- scene : de quoi reconstruire le plan en 3D (Blender) ou en motion design. objects : les éléments, en anglais, \
précis (forme, matière, échelle) ; environment, lighting, camera : en anglais ; palette : les codes hex utilisés.
- notes : conseils de fabrication en français (assets, effets, astuces Blender ou After Effects), courts.
- reuse : si le plan réutilise ou rappelle un élément d'un autre plan, lequel (« même globe que le plan de la phrase \
12 »), sinon vide.

Varie les plans : alterne techniques, cadrages et échelles ; garde la cohérence avec les plans voisins (motifs \
récurrents, palette, continuité des objets). Utilise les durées : un plan de 3 s doit se lire d'un coup d'œil, un \
plan de 12 s peut évoluer."""

_SCENE = {"type": "object", "additionalProperties": False,
          "required": ["objects", "environment", "lighting", "camera", "palette"],
          "properties": {"objects": {"type": "array", "items": {"type": "string"}},
                         "environment": {"type": "string"}, "lighting": {"type": "string"},
                         "camera": {"type": "string"}, "palette": {"type": "array", "items": {"type": "string"}}}}
BEAT_FIELDS = ["first", "last", "technique", "title", "see", "motion", "image_prompt", "video_prompt", "scene",
               "notes", "reuse"]
BEATS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["beats"], "properties": {
    "beats": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": BEAT_FIELDS,
        "properties": {"first": {"type": "integer"}, "last": {"type": "integer"}, "technique": {"type": "string"},
                       "title": {"type": "string"}, "see": {"type": "string"}, "motion": {"type": "string"},
                       "image_prompt": {"type": "string"}, "video_prompt": {"type": "string"}, "scene": _SCENE,
                       "notes": {"type": "string"}, "reuse": {"type": "string"}}}}}}


# --- Script and timings ----------------------------------------------------------------------------

def sentence_windows(derush: Path | None, edit: Path | None) -> dict[int, tuple[float, float]]:
    """Sentence -> (start, end) in the edit (or the derush), from part 1's Sxxx markers. {} without them."""
    from .sourcing.place import place_sentences, read_sequence
    try:
        d = read_sequence(derush, prefer="derush") if derush else None
        t = read_sequence(edit, prefer="derush") if edit else None
    except Exception:
        return {}
    if d and d.markers:
        return place_sentences(d, t)
    if t and t.markers:
        return place_sentences(t)
    return {}


def script_lines(doc: ScriptDoc, where: dict[int, tuple[float, float]]) -> list[dict]:
    from .text import detect_language
    wps = WORDS_PER_SECOND[detect_language(" ".join(s.text for s in doc.sentences[:200]))]
    out = []
    for s in doc.sentences:
        if doc.sections[s.section].skip:
            continue
        if s.idx in where:
            a, b = where[s.idx]
            d = max(0.5, b - a)
        else:
            d = max(1.0, len(s.text.split()) / wps)
        out.append({"id": s.idx, "section": doc.sections[s.section].title, "text": s.text, "s": round(d, 1)})
    return out


def _script_payload(doc: ScriptDoc, lines: list[dict]) -> str:
    """Compact: one line per sentence, section headings in between."""
    rows, last = [], None
    for x in lines:
        if x["section"] != last:
            rows.append(f"## {x['section'] or 'Début'}")
            last = x["section"]
        rows.append(f"[{x['id']}] ({x['s']} s) {x['text']}")
    return f"# {doc.title}\n" + "\n".join(rows)


# --- Style bible -----------------------------------------------------------------------------------

def make_bible(engine: str, doc: ScriptDoc, lines: list[dict], brief: str, refs: list[Path]) -> dict:
    from PIL import Image
    content = [f"Demande de style du vidéaste :\n{brief.strip() or '(aucune : propose un style sobre et cohérent)'}",
               "Script :\n" + _script_payload(doc, lines)[:60000]]
    if refs and llm.ENGINES[engine]["vision"]:
        content.append("Images de référence du style voulu :")
        for p in refs[:6]:
            try:
                with Image.open(p) as im:
                    content.append(llm.jpeg(im, 768))
            except Exception:
                continue
    from .i18n import localize_prompt
    bible = llm.ask(engine, localize_prompt(STYLE_INSTRUCTIONS), content, STYLE_SCHEMA, effort="high")
    names = {t["name"].lower() for t in bible.get("techniques", [])}
    for name, look, use in ((FACE, tr("le présentateur à l'image, sans illustration"), tr("respirations, apartés")),
                            (ARCHIVE, tr("image ou vidéo d'archive réelle (onglet Illustrations)"),
                             tr("personnes réelles, événements, documents"))):
        if name not in names:
            bible.setdefault("techniques", []).append({"name": name, "look": look, "use_for": use})
    return bible


def _colon() -> str:
    """« : » after a label in the interface language (French puts a space before it)."""
    from .i18n import ui_lang
    return " :" if ui_lang() == "fr" else ":"


def _bible_text(bible: dict, label=None) -> str:
    """The bible as text: French labels for the AI prompts, `label=tr` for storyboard.md."""
    L = label or (lambda s: s)
    c = _colon() if label else " :"
    t = [f"{L('Style')}{c} {bible.get('summary', '')}",
         f"{L('Palette')}{c} " + ", ".join(f"{p['name']} {p['hex']}" for p in bible.get("palette", [])),
         f"{L('Lumière')}{c} {bible.get('lighting', '')}", f"{L('Matières')}{c} {bible.get('materials', '')}",
         f"{L('Caméra')}{c} {bible.get('camera', '')}", f"{L('Typographie')}{c} {bible.get('typography', '')}",
         f"{L('Transitions')}{c} {bible.get('transitions', '')}",
         f"{L('Motifs récurrents')}{c} " + " ; ".join(bible.get("motifs", [])),
         f"{L('Techniques')}{c}"] + [f"- {x['name']}{c} {x['look']} — {L('pour')}{c} {x['use_for']}"
                                     for x in bible.get("techniques", [])]
    t += [f"{L('À éviter')}{c} " + " ; ".join(bible.get("avoid", [])), f"prompt_style{c} {bible.get('prompt_style', '')}"]
    return "\n".join(t)


# --- Beats -----------------------------------------------------------------------------------------

def _batches(lines: list[dict], locked: set[int]) -> list[list[dict]]:
    """Runs of free sentences (not in a locked beat), cut at section changes past BATCH_SENTENCES."""
    out, cur = [], []
    for x in lines:
        if x["id"] in locked:
            if cur:
                out.append(cur)
            cur = []
            continue
        if cur and len(cur) >= BATCH_SENTENCES and x["section"] != cur[-1]["section"]:
            out.append(cur)
            cur = []
        if cur and len(cur) >= BATCH_SENTENCES * 1.6:
            out.append(cur)
            cur = []
        cur.append(x)
    if cur:
        out.append(cur)
    return out


def _clean_beats(raw: list[dict], ids: list[int]) -> list[dict]:
    """Beats that cover exactly `ids`, in order: out-of-range ones dropped, gaps given to the previous beat."""
    pos = {i: k for k, i in enumerate(ids)}
    beats = sorted((b for b in raw if b.get("first") in pos), key=lambda b: pos[b["first"]])
    out, covered = [], -1
    for b in beats:
        a = pos[b["first"]]
        z = pos.get(b.get("last"), a)
        if z < a:
            z = a
        if a <= covered:              # overlaps the previous beat
            if z <= covered:
                continue
            a = covered + 1
        if out and a > covered + 1:   # a gap: the previous beat takes it
            out[-1]["last"] = ids[a - 1]
        elif not out and a > 0:
            a = 0
        b = {**{k: b.get(k) for k in BEAT_FIELDS}, "first": ids[a], "last": ids[z]}
        out.append(b)
        covered = z
    if out and covered < len(ids) - 1:
        out[-1]["last"] = ids[-1]
    if not out and ids:
        out = [{"first": ids[0], "last": ids[-1], "technique": FACE, "title": "", "see": "", "motion": "",
                "image_prompt": "", "video_prompt": "", "scene": {}, "notes": "", "reuse": ""}]
    return out


def _ask_beats(engine: str, bible: dict, doc: ScriptDoc, lines: list[dict], part: list[dict], pace: float,
               extra: str = "") -> list[dict]:
    content = ["Bible de style :\n" + _bible_text(bible),
               "Script entier :\n" + _script_payload(doc, lines),
               f"Passage à découper : phrases {part[0]['id']} à {part[-1]['id']} "
               f"({sum(x['s'] for x in part):.0f} s)." + (f"\n{extra}" if extra else "")]
    from .i18n import localize_prompt
    answer = llm.ask(engine, localize_prompt(BEATS_INSTRUCTIONS.replace("{pace}", f"{pace:g}")), content, BEATS_SCHEMA)
    return _clean_beats(answer.get("beats", []), [x["id"] for x in part])


def _finish(beats: list[dict], lines: list[dict], where: dict[int, tuple[float, float]]) -> list[dict]:
    """Numbers, timings and text of each beat, in script order."""
    by_id = {x["id"]: x for x in lines}
    order = {x["id"]: k for k, x in enumerate(lines)}
    beats.sort(key=lambda b: order.get(b["first"], 0))
    t = 0.0
    for n, b in enumerate(beats, 1):
        span = [x for x in lines if order[b["first"]] <= order[x["id"]] <= order[b["last"]]]
        b["id"] = f"B{n:03d}"
        b["section"] = by_id[b["first"]]["section"]
        b["text"] = " ".join(x["text"] for x in span)
        b["duration"] = round(sum(x["s"] for x in span), 1)
        if b["first"] in where and b["last"] in where:
            b["start"], b["end"] = where[b["first"]][0], where[b["last"]][1]
            b["duration"] = round(max(0.5, b["end"] - b["start"]), 1)
        else:
            b["start"], b["end"] = round(t, 1), round(t + b["duration"], 1)
        t = b["end"]
        b.setdefault("locked", False)
        if not isinstance(b.get("scene"), dict):
            b["scene"] = {}
    return beats


# --- Cards -----------------------------------------------------------------------------------------

_FONTS = Path(r"C:\Windows\Fonts")


def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    for name in (("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")):
        try:
            return ImageFont.truetype(str(_FONTS / name), size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _hex(c: str, default=(40, 44, 52)) -> tuple[int, int, int]:
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", (c or "").strip())
    return tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4)) if m else default


def technique_color(name: str, bible: dict) -> tuple[int, int, int]:
    if name == FACE:
        return (110, 116, 128)
    if name == ARCHIVE:
        return (196, 150, 70)
    hues = [(74, 108, 247), (31, 157, 99), (214, 69, 61), (155, 89, 182), (0, 150, 170), (230, 126, 34)]
    names = [t["name"] for t in bible.get("techniques", []) if t["name"] not in (FACE, ARCHIVE)]
    k = names.index(name) if name in names else zlib.crc32(name.encode()) % len(hues)
    return hues[k % len(hues)]


def _tc(s: float) -> str:
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def render_card(b: dict, bible: dict, path: Path, size=(1920, 1080)) -> None:
    """A storyboard card: what to make, readable in the timeline until the real shot replaces it."""
    from PIL import Image, ImageDraw
    w, h = size
    im = Image.new("RGB", size, (22, 23, 27))
    d = ImageDraw.Draw(im)
    col = technique_color(b.get("technique", ""), bible)
    d.rectangle((0, 0, 24, h), fill=col)
    x0, y = 90, 80
    d.text((x0, y), f"{b['id']}  ·  {_tc(b.get('start', 0))}  ·  {b.get('duration', 0):g} s", font=_font(40), fill=(150, 156, 168))
    tech = (b.get("technique") or "").upper()
    tw = d.textlength(tech, font=_font(38, True))
    d.rounded_rectangle((w - 90 - tw - 40, y - 8, w - 90, y + 52), radius=14, fill=col)
    d.text((w - 90 - tw - 20, y - 2), tech, font=_font(38, True), fill=(255, 255, 255))
    y += 100
    for line in textwrap.wrap(b.get("title") or "", 38)[:2]:
        d.text((x0, y), line, font=_font(84, True), fill=(240, 241, 245))
        y += 104
    y += 20
    for line in textwrap.wrap(b.get("see") or "", 70)[:6]:
        d.text((x0, y), line, font=_font(46), fill=(214, 217, 224))
        y += 62
    if b.get("motion"):
        y += 16
        for line in textwrap.wrap(tr("Mouvement") + _colon() + " " + b["motion"], 84)[:2]:
            d.text((x0, y), line, font=_font(36), fill=(150, 156, 168))
            y += 48
    quote = textwrap.wrap(f"« {b.get('text', '')} »", 110)
    yq = h - 70 - 44 * min(3, len(quote))
    for line in quote[:3]:
        d.text((x0, yq), line, font=_font(32), fill=(120, 126, 138))
        yq += 44
    sw = 44         # palette, under the technique label
    for k, c in enumerate(bible.get("palette", [])[:7]):
        x1 = w - 90 - k * (sw + 8)
        d.rectangle((x1 - sw, 150, x1, 150 + sw), fill=_hex(c.get("hex")))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def card_name(doc_sections: dict[str, int], b: dict) -> str:
    sec = doc_sections.get(b["section"], 0)
    return f"{sec:02d} {slug(b['section'] or 'Début', 40)}/S{b['first'] + 1:03d}-01 {b['id']} - {slug(b.get('title') or '', 40)}.png"


def write_outputs(out: Path, sb: dict, doc: ScriptDoc) -> None:
    """Cards, spans.json, manifest.json (for the placement code), storyboard.md, storyboard.json."""
    from .sourcing.model import Manifest
    export = out / "export"
    for old in export.glob("*/S*.png"):
        old.unlink()
    sections = {s.title: s.idx for s in doc.sections}
    spans = {}
    for b in sb["beats"]:
        if b.get("technique") == FACE:
            b["card"] = ""
            continue
        rel = card_name(sections, b)
        render_card(b, sb["style"]["bible"], export / rel)
        b["card"] = "export/" + rel
        spans[Path(rel).name] = b["last"]
    (out / "spans.json").write_text(json.dumps(spans, ensure_ascii=False, indent=1), encoding="utf-8")
    Manifest(sb["script"], doc.title, [asdict(s) for s in doc.sections],
             [{"idx": s.idx, "text": s.text, "section": s.section, "paragraph": s.paragraph,
               "links": [asdict(link) for link in s.links], "notes": s.notes} for s in doc.sentences],
             [], []).save(out / "manifest.json")
    save(out, sb)
    (out / "storyboard.md").write_text(markdown(sb), encoding="utf-8")


def save(out: Path, sb: dict) -> None:
    tmp = out / "storyboard.tmp"
    tmp.write_text(json.dumps(sb, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(out / "storyboard.json")


def load(out: Path) -> dict:
    return json.loads((out / "storyboard.json").read_text(encoding="utf-8"))


def markdown(sb: dict) -> str:
    bible = sb["style"]["bible"]
    md = [f"# Storyboard — {sb['title']}", "", f"> {sb['style']['brief']}" if sb["style"]["brief"] else "", "",
          "## " + tr("Bible de style"), "", _bible_text(bible, tr), ""]
    last = None
    for b in sb["beats"]:
        if b["section"] != last:
            md += [f"## {b['section'] or tr('Début')}", ""]
            last = b["section"]
        md += [f"### {b['id']} · {_tc(b['start'])} · {b['duration']:g} s · {b['technique']} — {b.get('title', '')}", "",
               f"*« {b['text']} »*", ""]
        for k, name in (("see", "On voit"), ("motion", "Mouvement"), ("notes", "Fabrication"), ("reuse", "Rappel")):
            if b.get(k):
                md.append(f"- **{tr(name)}**{_colon()} {b[k]}")
        for k, name in (("image_prompt", "Prompt image"), ("video_prompt", "Prompt vidéo")):
            if b.get(k):
                md += ["", f"**{tr(name)}**", "", "```", b[k], "```"]
        md.append("")
    return "\n".join(md)


# --- The whole run ---------------------------------------------------------------------------------

def make(script: Path, brief: str = "", refs: list[Path] | None = None, pace: float = 6.0,
         derush: Path | None = None, edit: Path | None = None, engine_pref: str = "auto",
         out: Path | None = None, log=print, keep_style: bool = False) -> Path:
    t0 = time.time()
    doc = parse_script(script)
    out = out or default_out(script)
    out.mkdir(parents=True, exist_ok=True)
    refs = [Path(p) for p in refs or [] if Path(p).is_file()]
    engines = [e for e in llm.candidates(engine_pref) if e != "ollama" or not refs]
    if not engines:
        raise SystemExit(tr("Aucune IA connectée : page IA de la fenêtre (Gemini, Claude, ChatGPT…)."))
    engine = engines[0]
    where = sentence_windows(derush, edit)
    lines = script_lines(doc, where)
    log("[1/4] " + (tr("{title} : {n} phrases, durées du montage ({found} phrases repérées)",
                       title=doc.title, n=len(lines), found=len(where)) if where else
                    tr("{title} : {n} phrases, durées estimées (pas de derush)", title=doc.title, n=len(lines)))
        + f" · {llm.label(engine)}")

    previous = load(out) if (out / "storyboard.json").exists() else None
    same_brief = previous and previous["style"]["brief"] == brief and previous["script"] == str(script)
    if previous and (keep_style or same_brief) and previous["style"].get("bible"):
        bible = previous["style"]["bible"]
        log("[2/4] " + tr("bible de style : celle du storyboard précédent (même demande)"))
    else:
        log("[2/4] " + tr("bible de style…"))
        bible = make_bible(engine, doc, lines, brief, refs)
        log(f"  {bible.get('summary', '')[:200]}")
        log("  " + tr("techniques : {list}", list=", ".join(t["name"] for t in bible.get("techniques", []))))

    valid = {x["id"] for x in lines}
    locked = [b for b in (previous or {}).get("beats", []) if b.get("locked") and b["first"] in valid
              and b["last"] in valid] if same_brief else []
    locked_ids = {x["id"] for b in locked for x in lines if b["first"] <= x["id"] <= b["last"]}
    parts = _batches(lines, locked_ids)
    log("[3/4] " + tr("découpage en plans : {n} passage(s)", n=len(parts))
        + (tr(", {n} plan(s) verrouillé(s) gardé(s)", n=len(locked)) if locked else ""))
    beats = [dict(b) for b in locked]
    errors = []

    def one(part):
        last = None
        for e in engines:
            try:
                return _ask_beats(e, bible, doc, lines, part, pace)
            except Exception as ex:
                last = ex
        raise last

    with ThreadPoolExecutor(2 if llm.ENGINES[engine].get("exe") else 4) as ex:
        futures = [ex.submit(one, p) for p in parts]
        for i, (p, f) in enumerate(zip(parts, futures), 1):
            try:
                got = f.result()
                beats += got
                log(f"  {i}/{len(parts)}  " + tr("phrases {a}–{b} : {n} plans", a=p[0]['id'], b=p[-1]['id'], n=len(got)))
            except Exception as e:
                errors.append(e)
                log(f"  {i}/{len(parts)}  " + tr("ÉCHEC phrases {a}–{b} : {error}", a=p[0]['id'], b=p[-1]['id'],
                                                   error=f"{type(e).__name__} {str(e)[:160]}"))
                beats += _clean_beats([], [x["id"] for x in p])
    if errors and len(errors) == len(parts):
        raise SystemExit(tr("L'IA n'a pas répondu : {error}", error=errors[0]))
    beats = _finish(beats, lines, where)

    sb = {"title": doc.title, "script": str(script), "created": time.strftime("%Y-%m-%d %H:%M"),
          "engine": llm.label(engine), "pace": pace, "timing": "montage" if where else "estimé",
          "derush": str(derush or ""), "edit": str(edit or ""),
          "style": {"brief": brief, "refs": [str(p) for p in refs], "bible": bible}, "beats": beats}
    log("[4/4] " + tr("cartes et XML : {n} plans", n=len(beats)))
    write_outputs(out, sb, doc)
    techniques = {}
    for b in beats:
        techniques[b["technique"]] = techniques.get(b["technique"], 0) + 1
    log("  " + ", ".join(f"{n} {k}" for k, n in sorted(techniques.items(), key=lambda x: -x[1])))
    try:
        xml = place_xml(out, log=log)
        log(f"  Premiere{_colon()} {xml}")
    except Exception as e:
        log("  " + tr("XML non écrit : {error}", error=e))
    usage = llm.usage_summary()
    log("\n" + tr("{n} plans, {s} s", n=len(beats), s=f"{time.time() - t0:.0f}")
        + ("\n" + tr("IA") + _colon() + " " + usage.replace("\n", "\n     ") if usage else "")
        + "\n" + tr("Dossier : {path}", path=out))
    return out


def place_xml(out: Path, derush: Path | None = None, edit: Path | None = None, log=print) -> Path:
    """Premiere XML of the cards at their beats (a cards-only sequence and a copy of the edit with them)."""
    from .sourcing.export import place
    sb = load(out)
    derush = derush or (Path(sb["derush"]) if sb.get("derush") else None)
    edit = edit or (Path(sb["edit"]) if sb.get("edit") else None)
    files = [(b["first"], out / b["card"]) for b in sb["beats"] if b.get("card") and (out / b["card"]).exists()]
    if not files:
        raise ValueError(tr("aucune carte (tous les plans sont « face caméra » ?)"))
    return place(out, files, derush if derush and derush.exists() else None,
                 edit if edit and edit.exists() else None, log=log, kind="Storyboard")


# --- One beat again (from the storyboard page) -----------------------------------------------------

def redo(out: Path, beat_id: str, instruction: str, engine_pref: str = "auto") -> dict:
    sb = load(out)
    doc = parse_script(Path(sb["script"]))
    where = sentence_windows(Path(sb["derush"]) if sb.get("derush") else None,
                             Path(sb["edit"]) if sb.get("edit") else None)
    lines = script_lines(doc, where)
    k = next(i for i, b in enumerate(sb["beats"]) if b["id"] == beat_id)
    b = sb["beats"][k]
    part = [x for x in lines if b["first"] <= x["id"] <= b["last"]]
    near = [f"{x['id']} ({x['technique']}) : {x.get('title', '')} — {x.get('see', '')}"
            for x in sb["beats"][max(0, k - 2):k + 3] if x is not b]
    extra = ("Un seul plan, qui couvre tout le passage. Plans voisins :\n" + "\n".join(near) +
             f"\nVersion actuelle de ce plan : {b.get('technique')} — {b.get('title')} — {b.get('see')}"
             + (f"\nDemande du vidéaste pour ce plan : {instruction.strip()}" if instruction.strip()
                else "\nPropose autre chose que la version actuelle."))
    engine = llm.candidates(engine_pref)[0]
    new = _ask_beats(engine, sb["style"]["bible"], doc, lines, part, 60, extra)[0]
    new.update(first=b["first"], last=b["last"], id=b["id"], section=b["section"], text=b["text"],
               start=b["start"], end=b["end"], duration=b["duration"], locked=b.get("locked", False))
    if not isinstance(new.get("scene"), dict):
        new["scene"] = {}
    sb["beats"][k] = new
    _rewrite_card(out, sb, new, doc)
    save(out, sb)
    (out / "storyboard.md").write_text(markdown(sb), encoding="utf-8")
    return new


def update(out: Path, beat_id: str, fields: dict) -> dict:
    """Edits made on the page (text fields, lock)."""
    sb = load(out)
    b = next(x for x in sb["beats"] if x["id"] == beat_id)
    for k in ("title", "see", "motion", "image_prompt", "video_prompt", "notes", "reuse", "technique", "locked"):
        if k in fields:
            b[k] = fields[k]
    if set(fields) - {"locked"}:
        _rewrite_card(out, sb, b, parse_script(Path(sb["script"])))
    save(out, sb)
    (out / "storyboard.md").write_text(markdown(sb), encoding="utf-8")
    return b


def _rewrite_card(out: Path, sb: dict, b: dict, doc: ScriptDoc) -> None:
    """Same file name when it exists (the clip already in Premiere updates), else a new card."""
    if b.get("technique") == FACE:
        return
    if not b.get("card"):
        rel = card_name({s.title: s.idx for s in doc.sections}, b)
        b["card"] = "export/" + rel
        spans_path = out / "spans.json"
        spans = json.loads(spans_path.read_text(encoding="utf-8")) if spans_path.exists() else {}
        spans[Path(rel).name] = b["last"]
        spans_path.write_text(json.dumps(spans, ensure_ascii=False, indent=1), encoding="utf-8")
    render_card(b, sb["style"]["bible"], out / b["card"])


# --- Page --------------------------------------------------------------------------------------------

PAGE = "storyboard.html"


class StoryboardApi:
    """What the storyboard page may call (window.pywebview.api) in its FauxRaccord window: a card dragged into
    Premiere as a file, and the window's « Tout placer » / XML."""

    def __init__(self, out: Path, place=None, export=None):
        self.out, self._place, self._export = out, place, export
        self.window = None

    def drag(self, beat_id: str) -> dict:
        from .sourcing.drag import drag_files
        try:
            sb = json.loads((self.out / "storyboard.json").read_text(encoding="utf-8"))
            card = next(b["card"] for b in sb["beats"] if b["id"] == beat_id and b.get("card"))
        except (OSError, ValueError, StopIteration, KeyError):
            return {"state": "error", "error": tr("pas de carte pour ce plan")}
        path = self.out / card
        if not path.exists():
            return {"state": "error", "error": tr("carte introuvable : {name}", name=path.name)}
        effect = drag_files(self.window, [str(path)]) if self.window else "none"
        return {"state": "ready", "dropped": effect not in ("none", "None", "released")}

    def insert(self, beat_id: str) -> dict:
        """« → Premiere »: the card at Premiere's playhead, through the panel."""
        from .sourcing.bridge import insert
        try:
            sb = json.loads((self.out / "storyboard.json").read_text(encoding="utf-8"))
            card = next(b["card"] for b in sb["beats"] if b["id"] == beat_id and b.get("card"))
        except (OSError, ValueError, StopIteration, KeyError):
            return {"state": "error", "error": tr("pas de carte pour ce plan")}
        path = self.out / card
        if not path.exists():
            return {"state": "error", "error": tr("carte introuvable : {name}", name=path.name)}
        return insert(path)

    def insert_state(self, rid: int) -> dict:
        from .sourcing.bridge import request_state
        return request_state(int(rid))

    def place_all(self) -> dict:
        return self._place() if self._place else {"ok": False, "message": tr("Ouvrez la planche depuis FauxRaccord.")}

    def export(self) -> dict:
        return self._export() if self._export else {"ok": False, "message": tr("Ouvrez la planche depuis FauxRaccord.")}


def serve(out: Path, engine_pref=lambda: "auto", open_browser: bool = True):
    """The storyboard page with a small API: edit, lock, redo one beat."""
    import threading
    import traceback
    import webbrowser
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    (out / PAGE).write_text((Path(__file__).parent / "web" / PAGE).read_text(encoding="utf-8"), encoding="utf-8")

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

        def do_GET(self):
            if self.path.split("?")[0] == "/i18n.js":
                from .i18n import js
                body = js().encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            return super().do_GET()

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
            try:
                if self.path == "/api/redo":
                    return self._json({"ok": True, "beat": redo(out, data["id"], data.get("instruction", ""),
                                                                engine_pref())})
                if self.path == "/api/update":
                    return self._json({"ok": True, "beat": update(out, data["id"], data.get("fields", {}))})
                if self.path == "/api/xml":
                    return self._json({"ok": True, "path": str(place_xml(out, log=lambda *_: None))})
            except Exception as e:
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}",
                                   "trace": traceback.format_exc(limit=3)})
            self.send_error(404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(out)))
    url = f"http://127.0.0.1:{server.server_address[1]}/{PAGE}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if open_browser:
        webbrowser.open(url)
    return server, url


# --- Command line ------------------------------------------------------------------------------------

def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    ap = argparse.ArgumentParser(prog="fauxraccord-storyboard", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make", help="style bible + beats + cards + Premiere XML")
    m.add_argument("script", type=Path)
    m.add_argument("--style", default="", help="the style wanted, in words")
    m.add_argument("--ref", type=Path, action="append", default=[], help="reference image (repeatable)")
    m.add_argument("--pace", type=float, default=6.0, help="target seconds per beat")
    m.add_argument("--derush", type=Path, help="part 1 .fauxraccord.xml (sentence timings)")
    m.add_argument("--edit", type=Path, help="current edit (FCP7 XML), to place the cards on it")
    m.add_argument("--llm", default="auto", choices=["auto", *llm.ENGINES])
    m.add_argument("--quality", default="best", choices=["best", "fast"])
    m.add_argument("--keep-style", action="store_true", help="reuse the previous style bible")
    m.add_argument("-o", "--out", type=Path)
    p = sub.add_parser("place", help="write the Premiere XML again (e.g. on a newer edit)")
    p.add_argument("folder", type=Path)
    p.add_argument("--derush", type=Path)
    p.add_argument("--edit", type=Path)
    s = sub.add_parser("page", help="open the storyboard page")
    s.add_argument("folder", type=Path)
    args = ap.parse_args()
    from . import write_result
    if args.cmd == "make":
        llm.set_quality(args.quality)
        out = make(args.script, args.style, args.ref, args.pace, args.derush, args.edit, args.llm, args.out,
                   keep_style=args.keep_style)
        write_result(out)
    elif args.cmd == "place":
        write_result(place_xml(args.folder, args.derush, args.edit))
    else:
        serve(args.folder)
        print(tr("Storyboard ouvert (Ctrl+C pour arrêter)"))
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
