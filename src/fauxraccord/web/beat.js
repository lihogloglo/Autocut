"use strict";
// Outils › Au rythme: rushes cut on the beats of a music. Python (beat/) computes the grid, the cuts and the
// shots; this page draws them and sends every change back (api.beat_set), so what is shown is what is exported.
// The timeline works like an editor's: click = playhead, drag = select a stretch, double-click or M = add a cut,
// drag a cut = move it, right-click = menu (delete, no cut here…), Delete = delete, Ctrl+Z / Ctrl+Y = undo / redo.
// Shots (under it): click = choose that shot's rush and moment; right-click = the same as a menu.

const BEAT_ON = [["beat", "Temps"], ["off", "Contretemps"], ["half", "Croches"], ["bar", "Mesures"], ["accent", "Accents"]];
const BEAT_EVERY = [1, 2, 4, 8];
const RULER = 24, WAVE_H = 100;     // cuts are grabbed by their handle in the ruler, like an editor's markers

const beatPage = {
  v: null,             // beat_view()
  m: null,             // beat_music(): waveform, hits (once per music)
  pps: 40,             // pixels per second
  sel: null,           // selected shot (its start, ms)
  selCut: null,        // selected cut (its time on the timeline)
  selRange: null,      // selected stretch [a, b] (s)
  hover: null,         // cut under the pointer
  drag: null,
  undo: [], redo: [],
  playing: false,
  sig: "",

  // --- data -----------------------------------------------------------------------------------
  async load() {
    const api = app.api;
    const v = await api.beat_view();
    this.v = v;
    const path = v.music && v.music.path;
    if (path && (!this.m || this.m.path !== path)) {
      this.m = await api.beat_music();
      this.needFit = true;
    }
    if (!path) this.m = null;
    this.render();
    app.renderNav();
  },
  async set(patch, history = true) {
    if (history) {                     // what the patch changes, as it was: Ctrl+Z puts it back
      this.undo.push(this.snapshot(Object.keys(patch)));
      if (this.undo.length > 200) this.undo.shift();
      this.redo = [];
    }
    this.v = await app.api.beat_set(patch);
    if (this.v.state && app.view) app.view.state.beat = this.v.state;     // the window's copy stays in step
    this.render();
    app.renderNav();
  },
  onView(view) {                       // the window's view changed: reload when this tool's inputs did
    const sig = JSON.stringify((view.state && view.state.beat) ? { m: view.state.beat.music, r: view.state.beat.rushes } : {});
    if (sig !== this.sig) { this.sig = sig; if (app.step === "beat" || this.v) this.load(); }
    else { this.renderInputs(); if (this.v) this.renderResult(); }
  },
  show() { this.load(); },
  snapshot(keys) {
    const st = (app.view && app.view.state.beat) || {}, out = {};
    for (const k of keys) out[k] = JSON.parse(JSON.stringify((k === "off" || k === "audio" ? st[k] : this.s[k]) ?? null));
    return out;
  },

  get s() { return (this.v && this.v.settings) || {}; },
  get fps() { return (this.v && this.v.fps) || 25; },
  get dur() { return (this.v && this.v.music && this.v.music.duration) || 0; },
  range() { const r = this.s.range; return r ? r : [0, this.dur]; },
  srcById(id) { return ((this.v && this.v.sources) || []).find((x) => x.id === id); },
  hueOf(id) { const i = ((this.v && this.v.sources) || []).findIndex((x) => x.id === id); return (i * 67 + 210) % 360; },

  // --- rendering ------------------------------------------------------------------------------
  render() {
    if (!this.v) return;
    this.renderInputs();
    this.renderSources();
    this.renderRhythm();
    this.renderBoard();
    this.renderResult();
  },

  renderInputs() {
    const st = (app.view && app.view.state.beat) || {}, v = this.v || {};
    const music = st.music, m = v.music;
    const mus = music
      ? `<div class="islot set" data-zone="beat-music"><span class="fico mus">${BICON.music}</span>
          <span class="fname"><b title="${esc(music)}">${esc(base(music))}</b><small>${m ? esc(`${dur(m.duration)} · ${m.bpm} BPM`) : esc(t("analyse…"))}</small></span>
          <button class="btn small" data-pick="beat-music">${t("Changer…")}</button>
          <button class="icon-btn" title="${esc(t("Retirer"))}" data-act="beat-rm" data-arg="music">✕</button></div>`
      : `<div class="islot" data-zone="beat-music"><span class="fico">${BICON.music}</span>
          <span class="fname"><b>${t("Glissez la musique ici")}</b><small>${t(".mp3, .wav, .m4a… ou depuis la planche sonore")}</small></span>
          <button class="btn small" data-pick="beat-music">${t("Choisir…")}</button></div>`;
    const rushes = st.rushes || [], srcs = v.sources || [], on = srcs.filter((x) => x.on).length;
    const rush = `<div class="islot ${rushes.length ? "set" : ""}" data-zone="beat-rushes"><span class="fico ${rushes.length ? "xml" : ""}">${BICON.film}</span>
        <span class="fname"><b>${rushes.length ? esc(t("{n} rushs", { n: srcs.length })) : t("Glissez les rushs ici")}</b>
        <small>${rushes.length ? esc(t("{n} utilisés", { n: on })) : t("vidéos, dossier, ou séquence Premiere (.xml) de sélections")}</small></span>
        <button class="btn small" data-pick="beat-rushes">${t("Fichiers…")}</button><button class="btn small" data-pick="beat-rushes" data-folder="1">${t("Dossier…")}</button></div>`;
    const set = (id, html) => { const el = $(id); if (el) el.innerHTML = html; };
    set("#in-beat-music", `<span class="flabel">${t("Musique")}</span>${mus}`);
    set("#in-beat-rushes", `<span class="flabel">${t("Rushs")}</span>${rush}`);
  },

  renderSources() {
    const st = (app.view && app.view.state.beat) || {}, srcs = (this.v && this.v.sources) || [];
    // folders and sequences as chips (✕ takes all of their rushes away); a file on its own: ✕ on its card
    const inputs = st.rushes || [], single = new Set(inputs.filter((r) => VIDEO.test(r)).map((r) => r.toLowerCase()));
    const chips = inputs.filter((r) => !single.has(r.toLowerCase())).map((r) => `<span class="fchip" title="${esc(r)}"><span>${esc(base(r) || r)}</span>
        <button class="icon-btn" title="${esc(t("Retirer"))}" data-act="beat-rm" data-arg="rush" data-value="${esc(r)}">✕</button></span>`).join("");
    const cards = srcs.map((x) => `<button class="bsrc ${x.on ? "on" : ""}" data-act="beat-src" data-arg="${esc(x.id)}" style="--h:${this.hueOf(x.id)}"
        title="${esc(x.on ? t("Utilisé — cliquer pour l'écarter") : t("Écarté — cliquer pour l'utiliser"))}">
        <img src="${esc(x.thumb)}" alt="" loading="lazy"><span class="bn"><i></i><b data-noi18n title="${esc(x.name)}">${esc(short(x.name))}</b><small>${esc(dur(x.end - x.start))}</small></span>
        ${single.has(x.path.toLowerCase()) && x.id === x.path ? `<span class="rm" data-act="beat-rm" data-arg="rush" data-value="${esc(inputs.find((r) => r.toLowerCase() === x.path.toLowerCase()))}" title="${esc(t("Retirer"))}">✕</span>` : ""}</button>`).join("");
    const el = $("#beat-srcs");
    if (!el) return;
    el.innerHTML = srcs.length || chips ? `<div class="fchips">${chips}
        ${srcs.length > 1 ? `<span class="r"><button class="link" data-act="beat-all" data-arg="1">${t("Tous")}</button> · <button class="link" data-act="beat-all" data-arg="0">${t("Aucun")}</button></span>` : ""}</div>
        ${srcs.length ? `<div class="bsrcs">${cards}</div>` : `<p class="note">${t("Aucune vidéo dans ces rushs.")}</p>`}` : "";
  },

  renderRhythm() {
    const s = this.s, m = this.v && this.v.music, el = $("#beat-rhythm");
    if (!el) return;
    const seg = (key, items, cur) => `<span class="seg">${items.map(([v, l]) =>
      `<button class="${String(cur) === String(v) ? "on" : ""}" data-act="beat-opt" data-arg="${key}" data-value="${esc(JSON.stringify(v))}">${esc(t(String(l)))}</button>`).join("")}</span>`;
    const hand = (s.add || []).length + (s.del || []).length + Object.keys(s.shots || {}).length + (s.holds || []).length;
    $("#beat-bpm").innerHTML = m ? `<b>${esc(num(m.bpm, 1))} BPM</b> · ${esc(t("{n} temps", { n: m.beats.length }))}` : "";
    el.innerHTML = `
      <div class="brow"><span class="k">${t("Couper sur")}</span>${seg("on", BEAT_ON, s.on)}</div>
      <div class="brow"><span class="k">${t(s.on === "accent" ? "Garder" : "Un sur")}</span>${seg("every", BEAT_EVERY.map((n) => [n, s.on === "accent" ? (n === 1 ? t("tous") : `1/${n}`) : String(n)]), s.every)}
        ${s.every > 1 && s.on !== "accent" ? `<button class="btn small" data-act="beat-opt" data-arg="shift" data-value="${(s.shift + 1) % s.every}" title="${esc(t("Couper sur un autre temps de la série"))}">${t("Décaler")} <span class="muted">${s.shift + 1}/${s.every}</span></button>` : ""}
        ${s.on !== "accent" ? `<button class="sw ${s.follow ? "on" : ""}" data-act="beat-opt" data-arg="follow" data-value="${!s.follow}"><i></i>${t("Plus de coupes quand ça monte")}</button>` : ""}</div>
      <div class="brow"><span class="k">${t("Tempo")}</span>${seg("tempo", [[0.5, "÷ 2"], [1, "× 1"], [2, "× 2"]], s.tempo)}
        <span class="muted">${t("Le 1 de la mesure")}</span><span class="seg"><button data-act="beat-phase" data-arg="-1" title="${esc(t("Un temps plus tôt"))}">◀</button><button data-act="beat-phase" data-arg="1" title="${esc(t("Un temps plus tard"))}">▶</button></span></div>
      <div class="brow"><span class="k">${t("Avance de l'image")}</span>${seg("nudge", [[-2, "−2"], [-1, "−1"], [0, "0"], [1, "+1"], [2, "+2"]], s.nudge)}<span class="muted">${t("images")}</span>
        <span class="muted">${t("Plan le plus court")}</span><input class="numin" type="number" min="0.1" max="10" step="0.1" value="${esc(s.min_len)}" data-beat-num="min_len"><span class="muted">s</span></div>
      <div class="brow"><span class="k">${t("Rushs")}</span>${seg("order", [["order", "Dans l'ordre"], ["shuffle", "Mélangés"]], s.order)}
        ${seg("take", [["start", "Depuis le début"], ["spread", "Répartis"], ["random", "Au hasard"]], s.take)}
        <button class="btn small" data-act="beat-opt" data-arg="seed" data-value="${(s.seed || 0) + 1}">${t("Autre tirage")}</button></div>
      ${hand ? `<div class="brow"><span class="k">${t("À la main")}</span><span class="muted">${esc(t("{a} coupes ajoutées, {d} enlevées, {s} plans changés", { a: (s.add || []).length, d: (s.del || []).length, s: Object.keys(s.shots || {}).length }))}${(s.holds || []).length ? " · " + esc(t("{n} passages sans coupe", { n: s.holds.length })) : ""}</span>
        <button class="link" data-act="beat-clear">${t("Tout effacer")}</button></div>` : ""}`;
    const numIn = $("[data-beat-num]", el);
    if (numIn) numIn.addEventListener("change", () => { const x = Number(numIn.value); if (x > 0) this.set({ [numIn.dataset.beatNum]: x }); });
  },

  renderBoard() {
    const box = $("#beat-board");
    if (!box) return;
    const v = this.v;
    if (v.error) { box.innerHTML = `<div class="empty-prev">${esc(v.error)}</div>`; return; }
    if (!v.music) { box.innerHTML = `<div class="empty-prev">${t("Ajoutez une musique : ses temps s'affichent ici.")}</div>`; return; }
    if (!$(".bt-scroll", box)) {
      box.innerHTML = `
        <div class="bt-top">
          <div class="bt-prev"><img id="bt-prev" alt=""><span id="bt-prev-name" data-noi18n></span></div>
          <div class="bt-side">
            <div class="bt-trans">
              <button class="btn" id="bt-play" title="${esc(t("Espace"))}">▶</button>
              <span class="bt-time" id="bt-time" data-noi18n>0:00</span>
              <span class="seg"><button id="bt-undo" title="${esc(t("Annuler (Ctrl+Z)"))}">↶</button><button id="bt-redo" title="${esc(t("Rétablir (Ctrl+Y)"))}">↷</button></span>
              <span class="r"><button class="btn small" id="bt-out" title="${esc(t("Zoom arrière"))}">−</button><button class="btn small" id="bt-in" title="${esc(t("Zoom avant"))}">+</button>
                <button class="btn small" id="bt-fit">${t("Tout voir")}</button></span>
            </div>
            <div class="bt-trans">
              <button class="btn small" id="bt-a">${t("Début ici")}</button><button class="btn small" id="bt-b">${t("Fin ici")}</button>
              <button class="link" id="bt-ab">${t("toute la musique")}</button>
            </div>
            <div class="bt-sum" id="bt-sum"></div>
            <div class="bt-shot" id="bt-shot"></div>
          </div>
        </div>
        <div class="bt-scroll" id="bt-scroll"><div class="bt-inner" id="bt-inner"><canvas id="bt-canvas" height="${RULER + WAVE_H}"></canvas><div class="bt-strip" id="bt-strip"></div></div></div>
        <p class="note bt-help">${t("Clic : tête de lecture · glisser : choisir un passage · double-clic ou M : couper · tirer la poignée d'une coupe : la déplacer (Alt : sans aimant) · clic droit ou Suppr : enlever · Ctrl+Z : annuler")}</p>
        <audio id="bt-audio" preload="auto"></audio>`;
      this.bindBoard();
    }
    if (this.needFit && $("#bt-scroll").clientWidth > 0) {   // a new music: about 40 s on screen
      const W = $("#bt-scroll").clientWidth;
      this.pps = Math.max(2, Math.min(400, Math.max(W / this.dur, W / 40)));
      $("#bt-scroll").scrollLeft = 0;
      this.needFit = false;
    }
    const au = $("#bt-audio");
    if (au.dataset.src !== v.audio_url) { au.src = v.audio_url; au.dataset.src = v.audio_url; }
    $("#bt-inner").style.width = `${Math.max(1, this.dur * this.pps)}px`;
    this.renderStrip();
    this.draw();
    this.renderShot();
    const shots = v.shots || [], [lo, hi] = this.range();
    $("#bt-sum").innerHTML = v.sources.length
      ? esc(t("{n} plans sur {d} · {m} en moyenne", { n: shots.length, d: dur(hi - lo), m: shots.length ? `${num((hi - lo) / shots.length, 1)} s` : "–" }))
      : esc(t("Ajoutez les rushs pour voir les plans."));
  },

  renderStrip() {
    const shots = this.v.shots || [], pps = this.pps;
    $("#bt-strip").innerHTML = shots.map((sh) => {
      const w = (sh.t1 - sh.t0) * pps, key = Math.round(sh.t0 * 1000);
      return `<button class="bt-sh ${sh.hand ? "hand" : ""} ${sh.short ? "short" : ""} ${this.sel === key ? "sel" : ""}" data-sh="${key}"
          style="left:${sh.t0 * pps}px;width:${Math.max(2, w - 1)}px;--h:${this.hueOf(sh.src)}" title="${esc((this.srcById(sh.src) || {}).name || "")}">
          ${w > 24 && sh.thumb ? `<img src="${esc(sh.thumb)}" alt="" loading="lazy">` : ""}</button>`;
    }).join("");
  },

  // the timeline: drawn for the visible part only (a long music would exceed a canvas' size)
  draw() {
    const cv = $("#bt-canvas"), sc = $("#bt-scroll");
    if (!cv || !this.v || !this.v.music) return;
    const W = sc.clientWidth, H = RULER + WAVE_H, dpr = window.devicePixelRatio || 1, x0 = sc.scrollLeft, pps = this.pps;
    if (cv.width !== Math.round(W * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.width = `${W}px`; cv.style.height = `${H}px`; }
    cv.style.left = `${x0}px`;
    const g = cv.getContext("2d"), css = getComputedStyle(document.documentElement);
    const col = (n) => css.getPropertyValue(n).trim();
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, W, H);
    const t0 = x0 / pps, t1 = (x0 + W) / pps, X = (t) => (t - t0) * pps;
    // waveform
    const m = this.m;
    g.fillStyle = col("--wave") || "#9aa";
    if (m && m.peaks) {
      const mid = RULER + WAVE_H / 2, half = WAVE_H / 2 - 4;
      for (let x = 0; x < W; x++) {
        const a = Math.floor((t0 + x / pps) * m.pps), b = Math.max(a + 1, Math.floor((t0 + (x + 1) / pps) * m.pps));
        let p = 0;
        for (let i = a; i < b && i < m.peaks.length; i++) if (i >= 0 && m.peaks[i] > p) p = m.peaks[i];
        const h = (p / 255) * half;
        if (h > 0.3) g.fillRect(x, mid - h, 1, h * 2);
      }
    }
    // beats: thin; first beat of a bar: strong, with its number in the ruler
    const mu = this.v.music;
    g.font = "10px Segoe UI, sans-serif";
    let bar = 0;
    for (let i = 0; i < mu.beats.length; i++) {
      const b = mu.beats[i];
      if (mu.down[i]) bar++;
      if (b < t0 - 1 || b > t1 + 1) continue;
      const x = Math.round(X(b)) + 0.5;
      g.fillStyle = mu.down[i] ? col("--beat-strong") : col("--beat");
      g.fillRect(x - 0.5, mu.down[i] ? 0 : RULER - 6, 1, mu.down[i] ? H : 6 + WAVE_H * 0.18);
      if (mu.down[i] && pps * mu.beats.length / Math.max(1, this.dur) > 1) {
        const every = pps < 15 ? 8 : pps < 30 ? 4 : 1;
        if ((bar - 1) % every === 0) { g.fillStyle = col("--muted"); g.fillText(String(bar), x + 3, 11); }
      }
    }
    // outside the range: dimmed
    const [lo, hi] = this.range();
    g.fillStyle = col("--dim");
    if (lo > t0) g.fillRect(0, 0, X(lo), H);
    if (hi < t1) g.fillRect(X(hi), 0, W - X(hi), H);
    // stretches with no cut: hatched
    const warn = col("--warn"), n = this.nudge;
    for (const [a, b] of this.s.holds || []) {
      const xa = X(Math.min(a, b) + n), xb = X(Math.max(a, b) + n);
      if (xb < 0 || xa > W) continue;
      g.save(); g.beginPath(); g.rect(xa, RULER, xb - xa, WAVE_H); g.clip();
      g.globalAlpha = 0.16; g.fillStyle = warn; g.fillRect(xa, RULER, xb - xa, WAVE_H);
      g.globalAlpha = 0.5; g.strokeStyle = warn; g.lineWidth = 1;
      for (let x = xa - WAVE_H; x < xb; x += 8) { g.beginPath(); g.moveTo(x, RULER + WAVE_H); g.lineTo(x + WAVE_H, RULER); g.stroke(); }
      g.restore();
      if (xb - xa > 80) { g.fillStyle = warn; g.fillText(t("pas de coupe"), Math.max(xa, 0) + 5, RULER + 12); }
    }
    // the selected stretch
    if (this.selRange) {
      const [a, b] = this.selRange;
      g.globalAlpha = 0.18; g.fillStyle = col("--accent"); g.fillRect(X(a), 0, X(b) - X(a), H); g.globalAlpha = 1;
    }
    // cuts: a line with a handle in the ruler (filled: placed by hand); the hovered or selected one thicker
    const accent = col("--accent"), dragging = this.drag && this.drag.kind === "cut" && this.drag.moved ? this.drag : null;
    for (const c of this.v.cuts || []) {
      if (c < t0 - 1 || c > t1 + 1) continue;
      const x = Math.round(X(c)), sel = c === this.selCut, strong = sel || c === this.hover;
      g.globalAlpha = dragging && dragging.c === c ? 0.3 : 1;
      g.fillStyle = sel ? col("--text") : accent;
      g.fillRect(x - (strong ? 1.5 : 1), RULER, strong ? 3 : 2, WAVE_H);
      g.beginPath(); g.moveTo(x - 6, 3); g.lineTo(x + 6, 3); g.lineTo(x + 6, RULER - 7); g.lineTo(x, RULER); g.lineTo(x - 6, RULER - 7); g.closePath();
      if (this.isHand(c)) g.fill();
      else { g.fillStyle = col("--surface"); g.fill(); g.strokeStyle = sel ? col("--text") : accent; g.lineWidth = 1.5; g.stroke(); }
    }
    g.globalAlpha = 1;
    if (dragging) {                     // where the cut will go
      const x = Math.round(X(dragging.t));
      g.fillStyle = accent; g.fillRect(x - 1.5, 0, 3, H);
      g.fillStyle = col("--text"); g.fillText(fmtS(dragging.t), x + 6, RULER + 12);
    }
    // ruler line and playhead
    g.fillStyle = col("--border");
    g.fillRect(0, RULER - 0.5, W, 1);
    const ph = this.playhead();
    if (ph >= t0 && ph <= t1) { g.fillStyle = col("--danger"); g.fillRect(Math.round(X(ph)) - 1, 0, 2, H); }
  },

  playhead() { const au = $("#bt-audio"); return au ? au.currentTime || 0 : 0; },

  shotAt(time) { return (this.v.shots || []).find((sh) => time >= sh.t0 && time < sh.t1); },

  renderShot() {
    const el = $("#bt-shot");
    if (!el) return;
    const sh = (this.v.shots || []).find((x) => Math.round(x.t0 * 1000) === this.sel);
    this.preview(sh || this.shotAt(this.playhead()));
    if (!sh) { el.innerHTML = ""; return; }
    const src = this.srcById(sh.src) || {}, ons = (this.v.sources || []).filter((x) => x.on);
    el.innerHTML = `<div class="bt-shot-h"><i style="--h:${this.hueOf(sh.src)}"></i><b data-noi18n>${esc(src.name || "")}</b>
        <span class="muted">${esc(t("plan {a} → {b}", { a: fmtS(sh.t0), b: fmtS(sh.t1) }))}</span>${sh.short ? `<span class="why">${t("rush trop court")}</span>` : ""}</div>
      <div class="bt-trans">
        <span class="seg"><button data-act="beat-shot" data-arg="prev" title="${esc(t("Rush précédent"))}">◀</button><button data-act="beat-shot" data-arg="next" title="${esc(t("Rush suivant"))}">▶</button></span>
        <select id="bt-shot-src" data-noi18n>${ons.map((x) => `<option value="${esc(x.id)}" ${x.id === sh.src ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select>
      </div>
      <div class="bt-trans"><span class="muted">${t("Moment")} <b data-noi18n>${esc(fmtS(sh.in))}</b></span>
        <span class="seg"><button data-act="beat-shot" data-arg="-5">−5 s</button><button data-act="beat-shot" data-arg="-1">−1 s</button><button data-act="beat-shot" data-arg="1">+1 s</button><button data-act="beat-shot" data-arg="5">+5 s</button></span>
        <button class="btn small" data-act="beat-shot" data-arg="rand">${t("Au hasard")}</button>
        ${sh.hand ? `<button class="link" data-act="beat-shot" data-arg="reset">${t("Rétablir")}</button>` : ""}</div>`;
    const pick = $("#bt-shot-src");
    if (pick) pick.addEventListener("change", () => this.editShot(sh, { src: pick.value }));
  },

  preview(sh) {
    const img = $("#bt-prev"), name = $("#bt-prev-name");
    if (!img) return;
    const src = sh && sh.thumb ? sh.thumb : "";
    if (img.dataset.src !== src) { img.dataset.src = src; if (src) img.src = src; else img.removeAttribute("src"); }
    img.style.visibility = src ? "visible" : "hidden";
    name.textContent = sh ? ((this.srcById(sh.src) || {}).name || "") : "";
  },

  renderResult() {
    const v = this.v, st = (app.view && app.view.state.beat) || {}, shots = (v.shots || []).length;
    const noMusic = !v.music, noRush = !(v.sources || []).some((x) => x.on);
    const hand = $("#res-beat-hand"), auto = $("#res-beat-auto");
    if (!hand) return;
    const out = (k) => app.saveLine("beat_" + k) +
      (st["out_" + k] ? `<span class="note">✓ <button class="link" data-act="reveal" data-arg="${esc(st["out_" + k])}">${t("Afficher dans l'explorateur")}</button></span>` : "");
    hand.innerHTML = `<div class="body"><h3>${t("À la main")}</h3>
      <p class="note">${t("La musique et un repère sur chaque coupe. Dans Premiere, les plans s'aimantent aux repères.")}</p>
      <div class="go col"><button class="btn big" data-act="beat-export" data-arg="marks" ${noMusic ? "disabled" : ""}>${t("Exporter les repères (.xml)")}</button>
        ${noMusic ? `<span class="why">${t("Ajoutez d'abord la musique.")}</span>` : `<span class="note">${t("Premiere › Fichier › Importer")}</span>`}${out("marks")}</div></div>`;
    auto.innerHTML = `<div class="body"><h3>${ICON.zap}${t("Automatique")}</h3>
      <p class="note">${noMusic || noRush ? t("Les rushs coupés sur la musique, prêts à affiner.") : esc(t("{n} plans, la musique dessous, un repère sur chaque coupe.", { n: shots }))}</p>
      <button class="sw ${st.audio ? "on" : ""}" data-act="beat-audio"><i></i>${t("Garder le son des rushs")}</button>
      <div class="go col"><button class="btn primary big" data-act="beat-export" data-arg="cut" ${noMusic || noRush ? "disabled" : ""}>${ICON.zap}${t("Exporter le montage (.xml)")}</button>
        ${noMusic ? `<span class="why">${t("Ajoutez d'abord la musique.")}</span>` : noRush ? `<span class="why">${t("Ajoutez d'abord les rushs.")}</span>` : `<span class="note">${t("Premiere › Fichier › Importer")}</span>`}${out("cut")}</div></div>`;
  },

  // --- interaction ----------------------------------------------------------------------------
  inRuler(e) { return e.clientY - $("#bt-canvas").getBoundingClientRect().top < RULER + 2; },
  timeAt(e) {
    const sc = $("#bt-scroll"), r = sc.getBoundingClientRect();
    return Math.max(0, Math.min(this.dur, (sc.scrollLeft + e.clientX - r.left) / this.pps));
  },
  cutNear(time, px = 6) {
    let best = null;
    for (const c of this.v.cuts || []) if (Math.abs(c - time) * this.pps <= px && (best == null || Math.abs(c - time) < Math.abs(best - time))) best = c;
    return best;
  },
  holdAt(time) {
    const n = this.nudge;
    return (this.s.holds || []).findIndex(([a, b]) => time - n >= Math.min(a, b) && time - n <= Math.max(a, b));
  },
  get nudge() { return (this.s.nudge || 0) / this.fps; },
  isHand(c) { const raw = c - this.nudge; return (this.s.add || []).some((a) => Math.abs(a - raw) <= 0.03); },
  // the nearest beat, off-beat or hit (music time, before the picture lead), unless free or none is close
  snap(time, free) {
    const at = time - this.nudge;
    if (free) return at;
    const beats = this.v.music.beats, offs = beats.slice(1).map((b, i) => (b + beats[i]) / 2);
    const hits = ((this.m && this.m.onsets) || []).map((o) => o[0]);
    let best = null;
    for (const c of [...beats, ...offs, ...hits]) if (best == null || Math.abs(c - at) < Math.abs(best - at)) best = c;
    return best != null && Math.abs(best - at) <= 12 / this.pps ? best : at;
  },
  seek(time) {
    const au = $("#bt-audio");
    au.currentTime = Math.max(0, Math.min(this.dur, time));
    $("#bt-time").textContent = fmtS(au.currentTime);
    this.preview(this.shotAt(au.currentTime));
    this.draw();
  },

  bindBoard() {
    const sc = $("#bt-scroll"), cv = $("#bt-canvas"), au = $("#bt-audio");
    sc.addEventListener("scroll", () => this.draw());
    sc.addEventListener("wheel", (e) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      const r = sc.getBoundingClientRect(), at = (sc.scrollLeft + e.clientX - r.left) / this.pps;
      this.zoom(e.deltaY < 0 ? 1.25 : 0.8, at, e.clientX - r.left);
    }, { passive: false });
    cv.addEventListener("mousemove", (e) => {
      if (this.drag) return;
      const c = this.inRuler(e) ? this.cutNear(this.timeAt(e), 7) : null;
      cv.style.cursor = c != null ? "ew-resize" : "text";
      cv.title = c != null ? t("Coupe à {t} · glisser pour déplacer, clic droit pour enlever", { t: fmtS(c) }) : "";
      if (c !== this.hover) { this.hover = c; this.draw(); }
    });
    cv.addEventListener("mouseleave", () => { if (this.hover != null && !this.drag) { this.hover = null; this.draw(); } });
    cv.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      this.menu(null);
      const time = this.timeAt(e), c = this.inRuler(e) ? this.cutNear(time, 7) : null;
      this.drag = c != null ? { kind: "cut", c, t: c, x0: e.clientX, moved: false } : { kind: "sel", t0: time, x0: e.clientX, moved: false };
      const move = (ev) => {
        const d = this.drag;
        if (!d) return;
        if (Math.abs(ev.clientX - d.x0) > 3) d.moved = true;
        if (!d.moved) return;
        const tm = this.timeAt(ev);
        if (d.kind === "cut") d.t = this.snap(tm, ev.altKey) + this.nudge;
        else this.selRange = [Math.min(d.t0, tm), Math.max(d.t0, tm)];
        this.draw();
      };
      const up = () => {
        window.removeEventListener("mousemove", move);
        window.removeEventListener("mouseup", up);
        const d = this.drag;
        this.drag = null;
        if (!d) return;
        if (d.kind === "cut") {
          if (d.moved && Math.abs(d.t - d.c) > 0.002) this.moveCut(d.c, d.t);
          else { this.selCut = d.c; this.selRange = null; this.draw(); }
        } else if (!d.moved) {          // a click: the playhead goes there
          this.selCut = null; this.selRange = null;
          this.seek(d.t0);
        } else { this.selCut = null; this.draw(); }
      };
      window.addEventListener("mousemove", move);
      window.addEventListener("mouseup", up);
    });
    cv.addEventListener("dblclick", (e) => {
      const time = this.timeAt(e);
      if (!this.inRuler(e) || this.cutNear(time, 7) == null) { this.selRange = null; this.addCut(this.snap(time, e.altKey)); }
    });
    cv.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      const time = this.timeAt(e), c = this.inRuler(e) ? this.cutNear(time, 7) : null, hold = this.holdAt(time), sr = this.selRange;
      const items = [];
      if (c != null) {
        this.selCut = c; this.draw();
        items.push([t("Enlever cette coupe"), () => this.removeCut(c), t("Suppr")], [t("Écouter d'ici"), () => { this.seek(c - 1); this.play(); }]);
      } else if (sr && time >= sr[0] && time <= sr[1]) {
        items.push([t("Pas de coupe dans ce passage"), () => this.addHold(sr), t("Suppr")],
                   [t("Couper au début et à la fin du passage"), () => this.addCuts([this.snap(sr[0]), this.snap(sr[1])])],
                   [t("Ne monter que ce passage"), () => { this.selRange = null; this.set({ range: [sr[0], sr[1]] }); }],
                   [t("Écouter ce passage"), () => { this.seek(sr[0]); this.play(); }]);
      } else {
        items.push([t("Ajouter une coupe ici"), () => this.addCut(this.snap(time)), t("double-clic")]);
        if (hold >= 0) items.push([t("Autoriser les coupes ici"), () => this.removeHold(hold)]);
        items.push([t("Écouter d'ici"), () => { this.seek(time); this.play(); }]);
      }
      this.menu(items, e.clientX, e.clientY);
    });
    $("#bt-strip").addEventListener("click", (e) => {
      const b = e.target.closest("[data-sh]");
      if (!b) return;
      const k = +b.dataset.sh;
      this.sel = this.sel === k ? null : k;
      $$(".bt-sh", $("#bt-strip")).forEach((x) => x.classList.toggle("sel", +x.dataset.sh === this.sel));
      if (this.sel != null && !this.playing) { const sh = (this.v.shots || []).find((x) => Math.round(x.t0 * 1000) === k); if (sh) this.seek(sh.t0); }
      this.renderShot();
    });
    $("#bt-strip").addEventListener("contextmenu", (e) => {
      const b = e.target.closest("[data-sh]");
      if (!b) return;
      e.preventDefault();
      this.sel = +b.dataset.sh;
      $$(".bt-sh", $("#bt-strip")).forEach((x) => x.classList.toggle("sel", +x.dataset.sh === this.sel));
      this.renderShot();
      const sh = (this.v.shots || []).find((x) => Math.round(x.t0 * 1000) === this.sel);
      this.menu([[t("Rush suivant"), () => this.shotAct("next")], [t("Rush précédent"), () => this.shotAct("prev")],
                 [t("Un autre moment, au hasard"), () => this.shotAct("rand")],
                 ...(sh && sh.hand ? [[t("Rétablir ce plan"), () => this.shotAct("reset")]] : []),
                 [t("Écouter ce plan"), () => { if (sh) { this.seek(sh.t0); this.play(); } }]], e.clientX, e.clientY);
    });
    $("#bt-play").addEventListener("click", () => this.play());
    $("#bt-undo").addEventListener("click", () => this.back(this.undo, this.redo));
    $("#bt-redo").addEventListener("click", () => this.back(this.redo, this.undo));
    $("#bt-in").addEventListener("click", () => this.zoom(1.5));
    $("#bt-out").addEventListener("click", () => this.zoom(1 / 1.5));
    $("#bt-fit").addEventListener("click", () => { this.fit(); this.renderBoard(); });
    $("#bt-a").addEventListener("click", () => this.setRange(0));
    $("#bt-b").addEventListener("click", () => this.setRange(1));
    $("#bt-ab").addEventListener("click", () => this.set({ range: null }));
    au.addEventListener("ended", () => this.stopPlay());
    au.addEventListener("pause", () => this.stopPlay());
    if (this._docBound) return;
    this._docBound = true;
    window.addEventListener("resize", () => this.draw());
    document.addEventListener("mousedown", (e) => { if (!e.target.closest(".ctx-menu")) this.menu(null); });
    document.addEventListener("keydown", (e) => {
      if (app.step !== "beat" || e.target.closest("input,textarea,select")) return;
      const k = e.key.toLowerCase();
      if (e.key === "Escape") { this.menu(null); this.selCut = null; this.selRange = null; this.draw(); return; }
      if (e.target.closest("button") && (e.code === "Space" || e.key === "Enter")) return;
      if (e.code === "Space") { e.preventDefault(); this.play(); }
      else if ((e.ctrlKey || e.metaKey) && k === "z" && !e.shiftKey) { e.preventDefault(); this.back(this.undo, this.redo); }
      else if ((e.ctrlKey || e.metaKey) && (k === "y" || (k === "z" && e.shiftKey))) { e.preventDefault(); this.back(this.redo, this.undo); }
      else if (e.key === "Delete" || e.key === "Backspace") {
        if (this.selCut != null) { e.preventDefault(); this.removeCut(this.selCut); }
        else if (this.selRange) { e.preventDefault(); this.addHold(this.selRange); }
      } else if (k === "m" && !e.ctrlKey && !e.metaKey && this.v && this.v.music) {
        e.preventDefault();
        this.addCut(this.snap(this.playhead(), e.altKey), true);
      }
    });
  },

  // a small menu at the pointer: [[label, action, shortcut]]
  menu(items, x, y) {
    let m = $("#bt-menu");
    if (!items) { if (m) m.hidden = true; return; }
    if (!m) { m = document.createElement("div"); m.id = "bt-menu"; m.className = "ctx-menu"; document.body.appendChild(m); }
    m.innerHTML = items.map(([l, , k], i) => `<button data-i="${i}"><span>${esc(l)}</span>${k ? `<small>${esc(k)}</small>` : ""}</button>`).join("");
    m.hidden = false;
    m.style.left = `${Math.max(4, Math.min(x, window.innerWidth - m.offsetWidth - 8))}px`;
    m.style.top = `${Math.max(4, Math.min(y, window.innerHeight - m.offsetHeight - 8))}px`;
    m.onclick = (e) => { const b = e.target.closest("[data-i]"); if (!b) return; this.menu(null); items[+b.dataset.i][1](); };
  },

  // undo / redo: each entry holds what a change replaced
  async back(from, to) {
    const entry = from.pop();
    if (!entry) return app.toast(t(from === this.undo ? "Rien à annuler." : "Rien à rétablir."));
    to.push(this.snapshot(Object.keys(entry)));
    this.selCut = null;
    await this.set(entry, false);
  },

  // cuts placed by hand (add) and computed ones taken away (del), in music time (before the picture lead)
  async addCut(raw, quiet) {
    const s = this.s, add = [...(s.add || [])], del = [...(s.del || [])];
    const keep = del.filter((d) => Math.abs(d - raw) > 0.03);
    if (keep.length !== del.length) await this.set({ del: keep });          // a computed cut taken away: back
    else { add.push(+raw.toFixed(4)); await this.set({ add, del }); }
    const shown = (this.v.cuts || []).find((c) => Math.abs(c - (raw + this.nudge)) < 0.002);
    this.selCut = shown ?? null;
    this.draw();
    if (shown == null && !quiet) app.toast(t("Trop près d'une autre coupe (plan le plus court : {s} s).", { s: num(this.s.min_len, 1) }));
  },
  addCuts(raws) {
    const add = [...(this.s.add || [])];
    for (const r of raws) if (!add.some((a) => Math.abs(a - r) <= 0.03)) add.push(+r.toFixed(4));
    this.selRange = null;
    return this.set({ add });
  },
  removeCut(c) {
    const raw = c - this.nudge, add = [...(this.s.add || [])], del = [...(this.s.del || [])];
    const i = add.findIndex((a) => Math.abs(a - raw) <= 0.03);
    if (i >= 0) add.splice(i, 1); else del.push(+raw.toFixed(4));
    this.selCut = null; this.hover = null;
    return this.set({ add, del });
  },
  moveCut(c, to) {
    const raw = c - this.nudge, dest = to - this.nudge, add = [...(this.s.add || [])], del = [...(this.s.del || [])];
    const i = add.findIndex((a) => Math.abs(a - raw) <= 0.03);
    if (i >= 0) add.splice(i, 1); else del.push(+raw.toFixed(4));
    add.push(+dest.toFixed(4));
    this.selCut = +to.toFixed(4); this.hover = null;
    return this.set({ add, del });
  },
  // a stretch with no cut: computed cuts go, hand ones inside it too
  addHold([a, b]) {
    const n = this.nudge, lo = a - n, hi = b - n;
    const holds = [...(this.s.holds || []), [+lo.toFixed(3), +hi.toFixed(3)]];
    const add = (this.s.add || []).filter((x) => x < lo || x > hi);
    this.selRange = null;
    return this.set({ holds, add });
  },
  removeHold(i) {
    const holds = [...(this.s.holds || [])];
    holds.splice(i, 1);
    return this.set({ holds });
  },

  setRange(which) {
    const [lo, hi] = this.range(), ph = this.playhead(), mu = this.v.music;
    // on the nearest first beat of a bar, so the cut starts and ends on the music
    let at = ph, best = null;
    mu.beats.forEach((b, i) => { if (mu.down[i] && (best == null || Math.abs(b - ph) < Math.abs(best - ph))) best = b; });
    if (best != null && Math.abs(best - ph) < 2) at = best;
    const r = which === 0 ? [at, hi] : [lo, at];
    if (r[1] - r[0] < 1) return app.toast(t("Le début doit être avant la fin."));
    this.set({ range: r });
  },

  editShot(sh, change) {
    const shots = { ...(this.s.shots || {}) }, key = String(Math.round(sh.t0 * 1000));
    const cur = shots[key] || { src: sh.src, in: sh.in };
    shots[key] = { ...cur, ...change };
    this.set({ shots });
  },
  shotAct(arg) {
    const sh = (this.v.shots || []).find((x) => Math.round(x.t0 * 1000) === this.sel);
    if (!sh) return;
    const ons = (this.v.sources || []).filter((x) => x.on), ln = sh.t1 - sh.t0;
    const mid = (x) => x.start + Math.max(0, (x.end - x.start - ln) / 2);
    if (arg === "reset") { const shots = { ...(this.s.shots || {}) }; delete shots[String(this.sel)]; return this.set({ shots }); }
    if (arg === "prev" || arg === "next") {
      const i = ons.findIndex((x) => x.id === sh.src), x = ons[(i + (arg === "next" ? 1 : -1) + ons.length) % ons.length];
      return x && this.editShot(sh, { src: x.id, in: mid(x) });
    }
    const src = this.srcById(sh.src);
    if (!src) return;
    const room = Math.max(0, src.end - src.start - ln);
    const at = arg === "rand" ? src.start + Math.random() * room : Math.min(src.start + room, Math.max(src.start, sh.in + Number(arg)));
    this.editShot(sh, { src: sh.src, in: +at.toFixed(3) });
  },

  play() {
    const au = $("#bt-audio");
    if (!au || !this.v.music) return;
    if (this.playing) { au.pause(); return; }
    const [lo, hi] = this.range();
    if (au.currentTime < lo || au.currentTime >= hi - 0.05) au.currentTime = lo;
    au.play().catch(() => app.toast(t("Lecture impossible.")));
    this.playing = true;
    $("#bt-play").textContent = "❚❚";
    const tick = () => {
      if (!this.playing) return;
      const ph = au.currentTime, [, end] = this.range();
      if (ph >= end) { au.pause(); return; }
      const sc = $("#bt-scroll"), x = ph * this.pps;
      if (x < sc.scrollLeft || x > sc.scrollLeft + sc.clientWidth - 40) sc.scrollLeft = x - 40;
      $("#bt-time").textContent = fmtS(ph);
      if (this.sel == null) this.preview(this.shotAt(ph));
      this.draw();
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  },
  stopPlay() {
    this.playing = false;
    const b = $("#bt-play");
    if (b) b.textContent = "▶";
    this.draw();
  },

  async act(what, arg, el) {
    const st = (app.view && app.view.state.beat) || {};
    if (what === "beat-opt") return this.set({ [arg]: JSON.parse(el.dataset.value) });
    if (what === "beat-phase") {
      const meter = (this.v.music && this.v.music.meter) || 4;
      return this.set({ phase: (((this.s.phase || 0) + Number(arg)) % meter + meter) % meter });
    }
    if (what === "beat-src" || what === "beat-all") {
      const ids = (this.v.sources || []).map((x) => x.id);
      let off = new Set(st.off || []);
      if (what === "beat-all") off = arg === "1" ? new Set() : new Set(ids);
      else if (off.has(arg)) off.delete(arg); else off.add(arg);
      return this.set({ off: [...off] });
    }
    if (what === "beat-audio") return this.set({ audio: !st.audio });
    if (what === "beat-clear") return this.set({ add: [], del: [], shots: {}, holds: [] });
    if (what === "beat-shot") return this.shotAct(arg);
    if (what === "beat-rm") { this.stopPlay(); return app.render(await app.api.beat_input(arg, el.dataset.value || "")); }
    if (what === "beat-export") {
      el.disabled = true;
      const r = await app.api.beat_export(arg);
      el.disabled = false;
      app.toast(r.message);
      if (r.view) app.render(r.view);
    }
  },
};

const BICON = {
  music: '<svg viewBox="0 0 24 24"><path d="M9 18V5l11-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zm11-2a3 3 0 1 1-6 0 3 3 0 0 1 6 0z"/></svg>',
  film: '<svg viewBox="0 0 24 24"><path d="M4 5h16v14H4zM8 5v14M16 5v14M4 9h4M4 15h4M16 9h4M16 15h4"/></svg>',
};
function short(name, n = 14) {    // the end of a file name tells rushes apart (…LEO3216 · 2)
  name = String(name || "").replace(/\.[a-z0-9]{2,4}( ·|$)/i, "$1");
  return name.length <= n ? name : "…" + name.slice(-(n - 1));
}
function num(x, d) {          // 105,5 in French, 105.5 in English
  const s = Number(x || 0).toFixed(d);
  return (window.I18N && I18N.lang !== "fr") ? s : s.replace(".", ",");
}
function fmtS(s) {
  s = Math.max(0, s || 0);
  const m = Math.floor(s / 60), x = s - m * 60;
  return `${m}:${x.toFixed(1).padStart(4, "0")}`;
}
window.beatPage = beatPage;
