"""Step 0: test Moments on a real recording before anything else is decided.

    python -m fauxraccord.moments spike "<recording>" --minutes 20 [--start 0]

Writes "<recording> - moments test/" with report.html and the pictures it shows:
  - what the file is: codec, size, frame rate, audio tracks, keyframe spacing;
  - decoding speed of each way of reading frames, and what 10 h would take;
  - image and sound model speed;
  - per audio track, the sounds heard most and a timeline of gunfire, explosions and loudness;
  - for words people would type, the frames that match best;
  - the moments the Rust preset finds in the sample, with pictures;
  - a contact sheet (one frame every 30 s) and one full-resolution frame, to place the health box.
The sample's chunks go in the normal index, so the full reading later starts from them.
"""

from __future__ import annotations

import html
import json
import subprocess
import time
from pathlib import Path

import numpy as np

from . import reader
from .index import RushIndex, Settings
from .models import Sounds, Vision
from .rules import Signals, find, load_preset

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PROBES = [
    "a video game death screen with a respawn button",
    "building a wooden base in a survival video game",
    "a blue holographic blueprint of a wall in a video game",
    "an inventory screen with many item slots",
    "a map screen of an island",
    "a dark night scene in a video game",
    "shooting a rifle at another player",
    "a player in a boat on the sea",
    "chopping a tree with a hatchet",
    "a loading screen",
]
WATCH = {"gunfire": ["Gunshot, gunfire", "Machine gun", "Fusillade", "Artillery fire", "Cap gun"],
         "explosion": ["Explosion", "Boom"], "hammer": ["Hammer", "Wood", "Sawing", "Chop"],
         "voice": ["Speech"], "reaction": ["Laughter", "Shout", "Yell", "Screaming", "Whoop", "Bellow"]}


def _tc(s: float) -> str:
    h, rem = divmod(int(s), 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}"


def _speed(rec: reader.Recording, start: float, seconds: float, **kw) -> dict:
    t0 = time.time()
    n = 0
    try:
        for _ in reader.frames(rec, start, seconds, 2.0, 512, **kw):
            n += 1
        err = ""
    except Exception as exc:
        err = str(exc)[:200]
    dt = time.time() - t0
    x = seconds / dt if dt else 0
    return {"frames": n, "seconds": round(dt, 2), "x_realtime": round(x, 1),
            "ten_hours_min": round(36000 / x / 60, 1) if x else None, "error": err}


def _svg(series: dict[str, np.ndarray], colours: dict[str, str], height: int = 80, top: float | None = None) -> str:
    w = 1000
    vals = [v for v in series.values() if len(v)]
    if not vals:
        return ""
    hi = top if top is not None else max(float(np.nanmax(v)) for v in vals) or 1.0
    lines = []
    for name, v in series.items():
        if not len(v):
            continue
        xs = np.linspace(0, w, len(v))
        ys = height - np.clip(np.nan_to_num(v) / hi, 0, 1) * (height - 4) - 2
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
        lines.append(f'<polyline fill="none" stroke="{colours.get(name, "#888")}" stroke-width="1.2" points="{pts}">'
                     f"<title>{html.escape(name)}</title></polyline>")
    legend = " ".join(f'<span style="color:{colours.get(k, "#888")}">■ {html.escape(k)}</span>' for k in series)
    return f'<div class="legend">{legend}</div><svg viewBox="0 0 {w} {height}" class="plot">{"".join(lines)}</svg>'


def run(path: Path, out: Path, minutes: float = 20.0, start: float = 0.0) -> Path:
    from ..media import ensure_ffmpeg
    ensure_ffmpeg()
    out.mkdir(parents=True, exist_ok=True)
    pics = out / "img"
    pics.mkdir(exist_ok=True)
    rec = reader.probe(path)
    end = min(rec.duration, start + minutes * 60)
    facts = {"file": str(path), "duration": _tc(rec.duration), "codec": rec.vcodec,
             "size": f"{rec.width}×{rec.height}", "fps": f"{float(rec.fps):.2f}",
             "audio": [{"track": a.index, "channels": a.channels, "title": a.title} for a in rec.audio]}
    kf = reader.keyframe_times(path, 120, start)
    facts["keyframe_spacing"] = round(float(np.median(np.diff(kf))), 2) if len(kf) > 2 else None
    facts["keyframe_spacing_max"] = round(float(np.max(np.diff(kf))), 2) if len(kf) > 2 else None
    print(f"[1/5] {path.name}: {facts['codec']} {facts['size']} {facts['fps']} fps, "
          f"{len(rec.audio)} audio track(s), keyframes every {facts['keyframe_spacing']} s")

    print("[2/5] decoding speed (60 s each)")
    speeds = {}
    for name, kw in [("keyframes only", {"keyframes": True}),
                     ("keyframes + d3d11va", {"keyframes": True, "hwaccel": "d3d11va"}),
                     ("every frame", {"keyframes": False}),
                     ("every frame + d3d11va", {"keyframes": False, "hwaccel": "d3d11va"}),
                     ("every frame + cuda", {"keyframes": False, "hwaccel": "cuda"})]:
        speeds[name] = _speed(rec, start + 60, 60, **kw)
        print(f"  {name:<24} {speeds[name]['x_realtime']:>6}× real time, 10 h ≈ {speeds[name]['ten_hours_min']} min "
              f"{speeds[name]['error']}")

    print("[3/5] model speed")
    vision, sounds = Vision("clip"), Sounds()
    sample = [rgb for _, rgb in reader.frames(rec, start, 128, 2.0, 512, keyframes=False)][:64]
    vision.images(sample[:4])
    t0 = time.time()
    vision.images(sample)
    img_rate = len(sample) / (time.time() - t0) if sample else 0
    wave = reader.audio(rec, 0, start, 300) if rec.audio else np.zeros(0, np.float32)
    sounds.per_second(wave[:16000 * 10], 10)
    t0 = time.time()
    sounds.per_second(wave, 300)
    snd_rate = 300 / (time.time() - t0) if len(wave) else 0
    models = {"image frames per s": round(img_rate, 1), "10 h of frames (1 per 2 s), min": round(18000 / img_rate / 60, 1) if img_rate else None,
              "sound: seconds of audio per s": round(snd_rate), "10 h of one track, min": round(36000 / snd_rate / 60, 1) if snd_rate else None}
    print("  " + json.dumps(models))

    print(f"[4/5] reading {_tc(start)}–{_tc(end)} into the index")
    ix = RushIndex(path)
    t0 = time.time()
    ix.build(Settings(), vision, sounds, only=(start, end),
             on_chunk=lambda d, n: print(f"  {d}/{n} chunks ({d / n:.0%})"))
    read_time = time.time() - t0
    print(f"  {read_time:.0f} s for {(end - start) / 60:.0f} min ({(end - start) / max(read_time, 1e-3):.1f}× real time)")

    print("[5/5] report")
    times, emb = ix.frames()
    keep = (times >= start) & (times < end)
    idx = np.flatnonzero(keep)
    lo, hi = int(start), int(end)

    def thumb(k: int, name: str | None = None) -> str:
        f = pics / (name or f"f{k}.jpg")
        if not f.exists():
            f.write_bytes(ix.jpeg(k))
        return f"img/{f.name}"

    # sounds per track
    names = sounds.names()
    track_html = []
    colours = {"gunfire": "#e05252", "explosion": "#c9a227", "hammer": "#4fa36b", "voice": "#3c8fe0",
               "reaction": "#b04ad0", "loudness": "#888"}
    sounds_json = {}
    for k in range(ix.audio_tracks):
        tags = ix.tags(k)[lo:hi]
        mean = tags.mean(axis=0)
        top = [(names[j], round(float(mean[j]), 3)) for j in np.argsort(-mean)[:15]]
        series = {w: np.convolve(np.minimum(1, tags[:, [names.index(c) for c in cls]].sum(axis=1)),
                                 np.ones(5) / 5, "same") for w, cls in WATCH.items()}
        loud = ix.loud(k)[lo:hi]
        series["loudness"] = (loud + 60) / 60
        sounds_json[k] = {"top": top}
        title = html.escape(rec.audio[k].title or f"track {k + 1}")
        track_html.append(f"<h3>Audio {k + 1} · {title}</h3><p class='muted'>"
                          + ", ".join(f"{html.escape(n)} {v:.2f}" for n, v in top) + "</p>"
                          + _svg(series, colours, 90, 1.0))

    # words
    probe_html = []
    sig = Signals(ix, vision)
    for words in PROBES:
        sim = emb[idx] @ vision.words([words])[0] if len(idx) else np.zeros(0)
        z = (sim - np.median(sim)) / max(np.median(np.abs(sim - np.median(sim))) * 1.4826, 1e-4) if len(sim) else sim
        best = idx[np.argsort(-z)[:8]] if len(z) else []
        cells = "".join(f"<figure><img src='{thumb(int(k))}' loading='lazy'><figcaption>{_tc(times[k])} · "
                        f"z {z[np.flatnonzero(idx == k)[0]]:.1f}</figcaption></figure>" for k in best)
        probe_html.append(f"<h3>{html.escape(words)}</h3><div class='row'>{cells}</div>")

    # Rust preset
    types = load_preset("rust")
    found = [m for m in find([ix], types, vision) if start <= m.anchor < end]
    moment_html = []
    for t in types:
        mine = [m for m in found if m.type == t.id]
        if not t.ready():
            moment_html.append(f"<h3 style='color:{t.color}'>{t.name}</h3><p class='muted'>pas prêt : {html.escape(t.hint)}</p>")
            continue
        margin = sig.combined(t)[lo:hi]
        rows = []
        for m in mine[:30]:
            ks = [ix.frame_at(x) for x in (m.anchor - 2, m.anchor, m.anchor + 4)]
            rows.append(f"<div class='mom'><b>{_tc(m.start)}–{_tc(m.end)}</b> <span class='muted'>score {m.score:.2f}</span>"
                        f"<div class='row'>{''.join(f'<img src={chr(39)}{thumb(k)}{chr(39)}>' for k in ks)}</div></div>")
        moment_html.append(f"<h3 style='color:{t.color}'>{t.name} · {len(mine)}</h3>"
                           + _svg({"marge": np.clip(np.nan_to_num(margin, nan=-3) + 3, 0, 6)}, {"marge": t.color}, 50, 6.0)
                           + "".join(rows))

    # contact sheet + full-resolution frame
    sheet = []
    for s in range(lo, hi, 30):
        k = ix.frame_at(s)
        sheet.append(f"<figure><img src='{thumb(k)}' loading='lazy'><figcaption>{_tc(times[k])}</figcaption></figure>")
    full = out / "full-frame.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start + (end - start) / 2:.2f}", "-i", str(path),
                    "-frames:v", "1", str(full)], creationflags=NO_WINDOW)

    report = {"facts": facts, "decoding": speeds, "models": models,
              "read": {"seconds": round(read_time), "minutes_read": round((end - start) / 60, 1)},
              "sounds": sounds_json, "moments": [m.to_json() for m in found]}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{v['x_realtime']}×</td><td>{v['ten_hours_min']} min</td>"
                   f"<td>{v['frames']}</td><td class='muted'>{html.escape(v['error'])}</td></tr>" for k, v in speeds.items())
    page = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Moments · test</title>
<style>
body{{font:14px/1.45 system-ui,sans-serif;background:#16171a;color:#e6e6e6;margin:24px;max-width:1200px}}
h1{{font-size:20px}} h2{{font-size:16px;margin-top:32px;border-bottom:1px solid #333;padding-bottom:4px}} h3{{font-size:14px;margin:18px 0 6px}}
.muted{{color:#999}} table{{border-collapse:collapse}} td,th{{padding:3px 10px;border-bottom:1px solid #2a2a2e;text-align:left}}
.row{{display:flex;gap:6px;flex-wrap:wrap}} figure{{margin:0}} img{{width:192px;border-radius:4px;display:block}}
figcaption{{font-size:11px;color:#aaa}} .plot{{width:100%;height:auto;background:#1e1f23;border-radius:4px}}
.legend{{font-size:12px;display:flex;gap:12px}} .mom{{margin:6px 0 12px}} pre{{background:#1e1f23;padding:8px}}
</style></head><body>
<h1>Moments · test · {html.escape(path.name)}</h1>
<pre>{html.escape(json.dumps(facts, ensure_ascii=False, indent=1))}</pre>
<h2>Lecture des images</h2><table><tr><th>Méthode</th><th>Vitesse</th><th>10 h</th><th>images</th><th></th></tr>{rows}</table>
<h2>Modèles</h2><pre>{html.escape(json.dumps(models, indent=1))}</pre>
<p>Lecture de l'extrait ({_tc(start)}–{_tc(end)}) : {read_time:.0f} s.</p>
<h2>Sons par piste</h2>{''.join(track_html)}
<h2>Moments trouvés (préréglage Rust)</h2>{''.join(moment_html)}
<h2>Mots</h2>{''.join(probe_html)}
<h2>Planche (une image toutes les 30 s)</h2><div class="row">{''.join(sheet)}</div>
<h2>Image pleine résolution</h2><p class="muted">full-frame.png, pour placer la barre de vie.</p><img src="full-frame.png" style="width:100%">
</body></html>"""
    (out / "report.html").write_text(page, encoding="utf-8")
    print(f"  {out / 'report.html'}")
    return out / "report.html"
