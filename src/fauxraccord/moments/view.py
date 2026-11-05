"""A look at what Moments found: one HTML page next to the project file, opened in the browser.

    python -m fauxraccord.moments view "<project>.moments.json"

The rush plays at the top. Below it, the whole rush as a timeline: a lane per kind of moment
(coloured blocks), the curves the rules read (health bar, gunfire, explosions, voice, loudness),
and the frames read. Clicking anywhere jumps the video there; hovering shows the frame. The cards
list every moment: click to play it from its start. A first draft of the board, before the window.
"""

from __future__ import annotations

import html
import json
import os
import webbrowser
from pathlib import Path

import numpy as np

from ..i18n import tr
from .index import ROOT, RushIndex
from .rules import Signals, sound_names

CURVES = {
    "gunfire": (["Gunshot, gunfire", "Machine gun", "Fusillade", "Artillery fire", "Cap gun"], "#e08a3c", "Tirs"),
    "explosion": (["Explosion", "Boom"], "#c9a227", "Explosions"),
    "voice": (["Speech"], "#3c8fe0", "Voix"),
    "reaction": (["Laughter", "Shout", "Yell", "Screaming", "Whoop", "Bellow"], "#b04ad0", "Cris, rires"),
}


def _curves(ix: RushIndex, types) -> list[dict]:
    names = sound_names()
    out = []
    for key, (classes, colour, label) in CURVES.items():
        cols = [names.index(c) for c in classes if c in names]
        per = [np.minimum(1, ix.tags(k)[:, cols].sum(axis=1)) for k in range(ix.audio_tracks)]
        if per:
            v = np.convolve(np.max(per, axis=0), np.ones(3) / 3, "same")
            out.append({"id": key, "label": label, "color": colour, "values": [round(float(x), 2) for x in v]})
    if ix.audio_tracks:
        loud = np.max([ix.loud(k) for k in range(ix.audio_tracks)], axis=0)
        out.append({"id": "loud", "label": "Volume", "color": "#8a8f99",
                    "values": [round(float(np.clip((x + 60) / 60, 0, 1)), 2) for x in loud]})
    if any(t.enabled and any("intensity" in s for s in t.signals) for t in types):
        from .intensity import curve
        c, _ = curve(ix)
        out.insert(0, {"id": "intensity", "label": "Intensité", "color": "#ff7043", "line": True,
                       "values": [None if not np.isfinite(x) else round(float(x), 3) for x in c]})
    zone = next((s for t in types for s in t.signals if s.get("zone")), None)
    if zone:
        sig = Signals(ix)
        fill, _, _ = sig.value({"zone": zone["zone"], "side": zone.get("side", "left"), "below": 0})
        out.insert(0, {"id": "health", "label": "Barre de vie", "color": "#7cc95a", "line": True,
                       "values": [None if not np.isfinite(x) else round(float(x), 3) for x in fill]})
    return out


def write(project_path: Path, root: Path = ROOT, open_it: bool = True) -> Path:
    from . import Project
    proj = Project(project_path)
    out_dir = project_path.with_name(project_path.name.replace(".moments.json", "") + " - vue")
    (out_dir / "img").mkdir(parents=True, exist_ok=True)
    rushes = []
    for r in proj.rushes:
        ix = RushIndex(Path(r), root)
        if not ix.done():
            continue
        times, _ = ix.frames()
        tag = f"r{len(rushes)}"
        for k in range(len(times)):
            f = out_dir / "img" / f"{tag}-{k}.jpg"
            if not f.exists():
                f.write_bytes(ix.jpeg(k))
        rushes.append({
            "name": Path(r).name, "src": Path(r).resolve().as_uri(), "duration": ix.duration,
            "frames": [round(float(t), 2) for t in times], "img": f"img/{tag}-",
            "curves": _curves(ix, proj.types),
            "moments": [m.to_json() for m in proj.moments if m.rush.lower() == str(Path(r).resolve()).lower()],
        })
    data = {"types": [{"id": t.id, "name": tr(t.name), "color": t.color, "ready": t.ready(), "remove": t.remove, "mode": t.mode,
                       "hint": tr(t.hint) if t.hint else ""} for t in proj.types], "rushes": rushes}
    page = PAGE.replace("/*DATA*/", json.dumps(data, ensure_ascii=False)).replace(
        "{{title}}", html.escape(project_path.name.replace(".moments.json", "")))
    out = out_dir / "index.html"
    out.write_text(page, encoding="utf-8")
    if open_it and not os.environ.get("FAUXRACCORD_RESULT"):
        webbrowser.open(out.resolve().as_uri())
    return out


PAGE = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Moments · {{title}}</title>
<style>
:root{--bg:#15161a;--panel:#1d1f24;--line:#2b2e35;--text:#e8e9ec;--muted:#8d929c;--accent:#e0a040}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);font:13px/1.4 system-ui,"Segoe UI",sans-serif}
header{display:flex;align-items:center;gap:12px;padding:10px 16px;border-bottom:1px solid var(--line)}
header h1{font-size:15px;margin:0} header select{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:4px 8px}
.muted{color:var(--muted)}
main{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:16px;padding:16px;height:calc(100vh - 49px)}
.left{display:flex;flex-direction:column;gap:12px;min-height:0;overflow:auto;padding-right:4px}
video{width:100%;max-height:52vh;background:#000;border-radius:8px}
.now{display:flex;gap:12px;align-items:center;font-variant-numeric:tabular-nums}
.now b{font-size:15px}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{display:inline-flex;align-items:center;gap:6px;padding:3px 9px;border-radius:99px;background:var(--panel);border:1px solid var(--line);cursor:pointer;user-select:none}
.chip i{width:9px;height:9px;border-radius:3px;display:inline-block}
.chip.off{opacity:.4} .chip small{color:var(--muted)}
.tl{position:relative;background:var(--panel);border-radius:8px;padding:8px 0 8px 112px;cursor:crosshair;user-select:none}
.row{position:relative;height:22px;margin:3px 10px 3px 0}
.row.curve{height:34px} .row.strip{height:44px}
.row .lab{position:absolute;left:-104px;width:96px;top:50%;transform:translateY(-50%);font-size:12px;color:var(--muted);text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.lane{position:absolute;inset:0;background:#24272d;border-radius:4px;overflow:hidden}
.blk{position:absolute;top:2px;bottom:2px;border-radius:3px;opacity:.9}
.blk:hover{outline:2px solid #fff}
svg{position:absolute;inset:0;width:100%;height:100%}
.strip .lane{display:flex}
.strip img{height:100%;flex:1 1 0;min-width:0;object-fit:cover;opacity:.85}
.head{position:absolute;top:0;bottom:0;width:2px;background:var(--accent);pointer-events:none}
.hover{position:absolute;top:0;bottom:0;width:1px;background:#fff8;pointer-events:none;display:none}
.tip{position:fixed;pointer-events:none;display:none;background:#000;border:1px solid var(--line);border-radius:6px;padding:4px;z-index:9}
.tip img{width:256px;display:block;border-radius:4px} .tip span{font-size:12px;font-variant-numeric:tabular-nums}
.ticks{position:relative;height:16px;margin-right:10px;font-size:11px;color:var(--muted)}
.ticks span{position:absolute;transform:translateX(-50%)}
aside{display:flex;flex-direction:column;min-height:0}
aside h2{font-size:13px;margin:0 0 8px;color:var(--muted);font-weight:600}
.cards{overflow:auto;display:flex;flex-direction:column;gap:8px;padding-right:4px}
.card{display:grid;grid-template-columns:120px 1fr;gap:10px;background:var(--panel);border:1px solid var(--line);border-left:4px solid;border-radius:8px;padding:6px;cursor:pointer}
.card:hover{border-color:#555} .card.on{outline:2px solid var(--accent)}
.card img{width:120px;aspect-ratio:16/9;object-fit:cover;border-radius:4px}
.card b{display:block} .card .sc{height:4px;border-radius:2px;background:#333;margin-top:6px} .card .sc i{display:block;height:100%;border-radius:2px}
.empty{color:var(--muted);padding:12px}
</style></head><body>
<header><h1>Moments</h1><span class="muted">{{title}}</span><select id="rush" aria-label="Rush"></select></header>
<main>
  <div class="left">
    <video id="v" controls preload="metadata"></video>
    <div class="now"><b id="tc">0:00:00</b><span class="muted" id="here"></span></div>
    <div class="chips" id="chips"></div>
    <div class="tl" id="tl"></div>
  </div>
  <aside><h2 id="count"></h2><div class="cards" id="cards"></div></aside>
</main>
<div class="tip" id="tip"><img alt=""><span></span></div>
<script>
const DATA = /*DATA*/;
const $ = id => document.getElementById(id);
const v = $("v"), tl = $("tl"), tip = $("tip");
const types = Object.fromEntries(DATA.types.map(t => [t.id, t]));
const hidden = new Set();
let R = null, head, hov;
const tc = s => { s = Math.max(0, Math.floor(s)); return `${Math.floor(s/3600)}:${String(Math.floor(s%3600/60)).padStart(2,"0")}:${String(s%60).padStart(2,"0")}`; };
const frameAt = t => { const f = R.frames; let lo = 0, hi = f.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (f[m] < t) lo = m; else hi = m; }
  return Math.abs(f[lo] - t) <= Math.abs(f[hi] - t) ? lo : hi; };
const pct = t => (100 * t / R.duration) + "%";

function row(label, cls, inner) {
  const r = document.createElement("div"); r.className = "row " + cls;
  r.innerHTML = `<div class="lab" title="${label}">${label}</div><div class="lane">${inner}</div>`;
  tl.appendChild(r); return r;
}
function curveSvg(c) {
  const n = c.values.length, h = 34, pts = [];
  c.values.forEach((y, i) => { if (y !== null) pts.push(`${(i / n * 1000).toFixed(1)},${(h - 2 - y * (h - 4)).toFixed(1)}`); });
  const path = c.line ? `<polyline fill="none" stroke="${c.color}" stroke-width="1.6" points="${pts.join(" ")}"/>`
    : `<polygon fill="${c.color}" fill-opacity=".75" points="0,${h} ${pts.join(" ")} 1000,${h}"/>`;
  return `<svg viewBox="0 0 1000 ${h}" preserveAspectRatio="none">${path}</svg>`;
}
function draw() {
  tl.innerHTML = "";
  const ticks = document.createElement("div"); ticks.className = "ticks";
  const step = [60, 120, 300, 600, 1800, 3600].find(s => R.duration / s <= 12) || 7200;
  for (let s = 0; s <= R.duration; s += step) ticks.innerHTML += `<span style="left:${pct(s)}">${tc(s)}</span>`;
  tl.appendChild(ticks);
  const n = Math.min(R.frames.length, 60);
  let imgs = ""; for (let i = 0; i < n; i++) imgs += `<img src="${R.img}${Math.round(i * (R.frames.length - 1) / Math.max(1, n - 1))}.jpg" alt="" loading="lazy">`;
  row("Images", "strip", imgs);
  for (const t of DATA.types) {
    if (hidden.has(t.id)) continue;
    const ms = R.moments.filter(m => m.type === t.id);
    const blocks = ms.map((m, i) => `<div class="blk" data-m="${R.moments.indexOf(m)}" title="${t.name} · ${tc(m.start)}–${tc(m.end)} · ${Math.round(m.score*100)} %"
      style="left:${pct(m.start)};width:max(3px,${pct(m.end - m.start)});background:${t.color}"></div>`).join("");
    const r = row(t.name + (t.ready ? "" : " ⚠"), "", blocks || (t.ready ? "" : `<span class="muted" style="padding:3px 8px;font-size:11px">${t.hint}</span>`));
    r.title = t.hint || "";
  }
  for (const c of R.curves) row(c.label, "curve", curveSvg(c));
  head = document.createElement("div"); head.className = "head"; tl.appendChild(head);
  hov = document.createElement("div"); hov.className = "hover"; tl.appendChild(hov);
  place();
}
function cards() {
  const list = R.moments.filter(m => !hidden.has(m.type)).sort((a, b) => a.start - b.start);
  $("count").textContent = `${list.length} moment${list.length > 1 ? "s" : ""}`;
  $("cards").innerHTML = list.length ? list.map(m => { const t = types[m.type] || {name: m.type, color: "#888"};
    return `<div class="card" data-m="${R.moments.indexOf(m)}" style="border-left-color:${t.color}">
      <img src="${R.img}${frameAt(t.mode === "state" ? (m.anchor + m.end) / 2 : m.anchor)}.jpg" alt="" loading="lazy">
      <div><b>${t.name}</b><span class="muted">${tc(m.start)} · ${Math.round(m.end - m.start)} s</span>
      <div class="sc"><i style="width:${Math.round(m.score*100)}%;background:${t.color}"></i></div></div></div>`; }).join("")
    : `<div class="empty">Aucun moment.</div>`;
}
function chips() {
  $("chips").innerHTML = DATA.types.map(t => { const n = R.moments.filter(m => m.type === t.id).length;
    return `<span class="chip ${hidden.has(t.id) ? "off" : ""}" data-t="${t.id}"><i style="background:${t.color}"></i>${t.name} <small>${n}</small></span>`; }).join("");
}
function x2t(e) { const lane = tl.querySelector(".lane").getBoundingClientRect();
  return Math.min(R.duration, Math.max(0, (e.clientX - lane.left) / lane.width * R.duration)); }
function place() {
  if (!head) return;
  const lane = tl.querySelector(".lane"), off = lane.offsetLeft + lane.parentElement.offsetLeft;
  head.style.left = (off + v.currentTime / R.duration * lane.offsetWidth) + "px";
  $("tc").textContent = tc(v.currentTime);
  const inside = R.moments.filter(m => m.start <= v.currentTime && v.currentTime < m.end).map(m => types[m.type]?.name || m.type);
  $("here").textContent = [...new Set(inside)].join(" · ");
  document.querySelectorAll(".card").forEach(c => { const m = R.moments[c.dataset.m]; c.classList.toggle("on", m.start <= v.currentTime && v.currentTime < m.end); });
}
function play(m) { v.currentTime = m.start; v.play(); }
function load(i) { R = DATA.rushes[i]; v.src = R.src; chips(); draw(); cards(); }

tl.addEventListener("click", e => { const b = e.target.closest(".blk"); if (b) return play(R.moments[b.dataset.m]); v.currentTime = x2t(e); });
tl.addEventListener("mousemove", e => { const t = x2t(e), lane = tl.querySelector(".lane");
  hov.style.display = "block"; hov.style.left = (lane.offsetLeft + lane.parentElement.offsetLeft + t / R.duration * lane.offsetWidth) + "px";
  tip.style.display = "block"; tip.querySelector("img").src = `${R.img}${frameAt(t)}.jpg`; tip.querySelector("span").textContent = tc(t);
  tip.style.left = Math.min(innerWidth - 270, e.clientX + 14) + "px"; tip.style.top = (e.clientY - 170) + "px"; });
tl.addEventListener("mouseleave", () => { hov.style.display = "none"; tip.style.display = "none"; });
$("cards").addEventListener("click", e => { const c = e.target.closest(".card"); if (c) play(R.moments[c.dataset.m]); });
$("chips").addEventListener("click", e => { const c = e.target.closest(".chip"); if (!c) return;
  hidden.has(c.dataset.t) ? hidden.delete(c.dataset.t) : hidden.add(c.dataset.t); chips(); draw(); cards(); });
v.addEventListener("timeupdate", place); addEventListener("resize", place);
$("rush").innerHTML = DATA.rushes.map((r, i) => `<option value="${i}">${r.name}</option>`).join("");
$("rush").addEventListener("change", e => load(+e.target.value));
if (DATA.rushes.length) load(0); else $("cards").innerHTML = `<div class="empty">Aucun rush lu.</div>`;
</script></body></html>
"""
