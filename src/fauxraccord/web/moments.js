"use strict";
// Outils › Moments: long rushes (10 h of gameplay, documentary B-roll) sorted by what happens in them.
// Python (moments/) reads each rush once and finds the moments; this page shows them and sends back the
// user's choices (api.moments_set / moments_mark). Only window.pywebview.api is called (app.api).
//   Timeline: hover = see the frame, click = play from there, click a block = play that moment.
//   Cards: click = play, ✓ = keep, ✗ = wrong (the XML leaves it out).

const MO_CURVE_H = 30;
// « Ce qui est dit »: whisper large-v3 on the RTX 4060 laptop read the 8.8 min test rush in 27 s (+ 8 s to
// load the model): about 3.1 min per hour of rush, more when people talk a lot (only speech is read).
const MO_SPEECH_MIN_PER_H = { "large-v3": 3.1 };
STEP_OF_JOB.moments_speech = "moments";
JOB_TITLE.moments_speech = "Lecture de ce qui est dit";

const momentsPage = {
  v: null,              // moments_view()
  rush: 0,              // index of the rush shown on the board
  hidden: new Set(),    // kinds hidden on the board
  dirty: false,         // kinds changed since the last search
  sig: "",

  // --- data -----------------------------------------------------------------------------------
  async load() {
    this.v = await app.api.moments_view();
    if (this.rush >= (this.v.rushes || []).length) this.rush = 0;
    this.render();
    app.renderNav();
  },
  async set(patch) {
    this.v = await app.api.moments_set(patch);
    this.dirty = true;
    this.render();
  },
  onJobEnd(ev) {                      // a search or an export of this page finished: show what it found
    if (!["moments", "moments_xml", "moments_speech"].includes(ev.step)) return;
    if (ev.ok && ["moments", "moments_speech"].includes(ev.step)) this.dirty = false;
    this.load().then(() => { if (ev.step === "moments_speech" && this.saidQ) this.saidSearch(); });
  },
  onView(view) {                      // the window's view changed: reload when this tool's inputs or results did
    const m = (view.state && view.state.moments) || {};
    const sig = JSON.stringify({ r: m.rushes || [], n: m.runs || 0, p: m.preset || "", k: m.kinds || 0 });
    if (sig !== this.sig) {
      const runs = this.sig && JSON.parse(this.sig).n !== (m.runs || 0);
      const added = this.sig && JSON.parse(this.sig).k !== (m.kinds || 0);    // a game pack dropped here
      this.sig = sig;
      if (runs) this.dirty = false;
      else if (added) this.dirty = true;
      if (app.step === "moments" || this.v) this.load();
    } else this.renderInputs();
  },
  show() { this.load(); },

  get R() { return (this.v && this.v.rushes && this.v.rushes[this.rush]) || null; },
  type(id) { return ((this.v && this.v.types) || []).find((x) => x.id === id) || { id, name: id, color: "#888" }; },
  frameAt(t) {
    const f = this.R.frames;
    let lo = 0, hi = f.length - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (f[m] < t) lo = m; else hi = m; }
    return Math.abs(f[lo] - t) <= Math.abs(f[hi] - t) ? lo : hi;
  },
  img(t) { return this.R && this.R.frames.length ? `${this.R.img}${this.frameAt(t)}` : ""; },

  // --- rendering ------------------------------------------------------------------------------
  render() {
    if (!this.v) return;
    this.renderInputs();
    this.renderKinds();
    this.renderBoard();
    this.renderResult();
  },

  renderInputs() {
    const st = (app.view && app.view.state.moments) || {}, rushes = st.rushes || [], v = this.v || {};
    const files = v.rushes || [];
    const total = files.reduce((a, r) => a + (r.duration || 0), 0);
    const el = $("#in-moments-rushes");
    if (el) el.innerHTML = `<span class="flabel">${t("Rushs")}</span>
      <div class="islot ${rushes.length ? "set" : ""}" data-zone="moments-rushes"><span class="fico ${rushes.length ? "xml" : ""}">${BICON.film}</span>
        <span class="fname"><b>${rushes.length ? esc(t("{n} rushs", { n: files.length })) : t("Glissez les rushs ici")}</b>
        <small>${rushes.length ? esc(dur(total)) : t("enregistrements OBS, rushs de tournage, ou le dossier qui les contient")}</small></span>
        <button class="btn small" data-pick="moments-rushes">${t("Fichiers…")}</button><button class="btn small" data-pick="moments-rushes" data-folder="1">${t("Dossier…")}</button></div>`;
    const list = $("#mo-files");
    if (list) list.innerHTML = files.map((r) => `<li><span class="fname"><b title="${esc(r.path)}">${esc(r.name)}</b>
        <small>${esc(dur(r.duration))} · ${r.read >= 1 ? t("lu") : r.read > 0 ? t("lu à {p} %", { p: Math.round(r.read * 100) }) : t("pas encore lu")}</small></span>
        <button class="icon-btn" title="${esc(t("Retirer"))}" data-act="mo-rm" data-arg="${esc(r.path)}">✕</button></li>`).join("");
  },

  renderKinds() {
    const v = this.v, el = $("#mo-kinds");
    if (!el) return;
    const counts = {};
    for (const r of v.rushes || []) for (const m of r.moments) counts[m.type] = (counts[m.type] || 0) + 1;
    const read = (v.rushes || []).length && v.rushes.every((r) => r.read >= 1);
    const opt = (p) => `<option value="${esc(p.id)}" ${p.id === v.preset ? "selected" : ""}>${esc(p.pack ? p.name : t(p.name))}</option>`;
    const packs = (v.presets || []).filter((p) => p.pack);      // game packs imported from friends
    const presets = (v.presets || []).filter((p) => !p.pack).map(opt).join("")
      + (packs.length ? `<optgroup label="${esc(t("Packs importés"))}">${packs.map(opt).join("")}</optgroup>` : "");
    $("#mo-preset-line").innerHTML = `${t("Préréglage")} <select id="mo-preset" aria-label="${esc(t("Préréglage"))}">${presets}</select>
      <button class="btn small" data-act="mo-pack-share" ${(v.rushes || []).length ? "" : "disabled"}
        title="${esc(t("Enregistrer les types que vous avez appris dans un fichier, pour vos amis qui jouent au même jeu"))}">${t("Partager…")}</button>
      <button class="btn small" data-act="mo-pack-import" title="${esc(t("Ajouter les types d'un pack reçu (.fauxpack.json)"))}">${t("Importer…")}</button>`;
    const rows = (v.types || []).map((k) => `<div class="mo-kind ${k.enabled ? "" : "off"}">
        <button class="sw ${k.enabled ? "on" : ""}" data-act="mo-kind" data-arg="${esc(k.id)}" title="${esc(t("Chercher ce type de moment"))}"><i></i></button>
        <span class="mo-dot" style="background:${k.color}"></span>
        <span class="mo-name"><b>${esc(k.name)}</b>${k.remove ? `<small>${t("temps mort")}</small>` : k.learned ? `<small>${t("appris")}</small>` : ""}</span>
        <span class="mo-n">${counts[k.id] || 0}</span>
        <label class="mo-sens" title="${esc(t("Sensibilité : plus à droite, plus de moments (et plus d'erreurs)"))}">
          <input type="range" min="0" max="1" step="0.05" value="${k.sensitivity}" data-kind="${esc(k.id)}" ${k.enabled ? "" : "disabled"}></label>
        <span class="mo-hint">${this.why(k)}</span>
        ${k.user ? `<button class="icon-btn" title="${esc(t("Supprimer ce type"))}" data-act="mo-del" data-arg="${esc(k.id)}">✕</button>` : "<span></span>"}</div>`).join("");
    const busy = app.job.running;
    const label = !read ? t("Lire les rushs et chercher") : this.dirty === "marks" ? t("Apprendre de vos ✓ / ✗")
      : this.dirty ? t("Appliquer les réglages") : t("Chercher à nouveau");
    el.innerHTML = `<div class="mo-kinds">${rows}</div>
      <div class="acts"><button class="btn ${!read || this.dirty ? "primary" : ""}" data-run="moments" ${!(v.rushes || []).length || busy ? "disabled" : ""}>${label}</button>
      <span class="note">${!read ? esc(t("Lu une seule fois (environ 4 min par heure de rush), puis chaque recherche prend quelques secondes."))
        : this.dirty ? esc(t("Les réglages ont changé.")) : esc(t("Tout est sur cet ordinateur : rien n'est envoyé."))}</span></div>`;
    $("#mo-preset").addEventListener("change", (e) => this.set({ preset: e.target.value }));
    $$(".mo-sens input", el).forEach((inp) => inp.addEventListener("change", (e) =>
      this.set({ type: e.target.dataset.kind, sensitivity: +e.target.value })));
    $$(".mo-zchip", el).forEach((c) => {
      c.addEventListener("mouseenter", () => this.showBox(JSON.parse(c.dataset.box)));
      c.addEventListener("mouseleave", () => this.showBox(null));
    });
  },

  // what a kind is recognised by, in words (taught kinds: what the last search learned)
  why(k) {
    const zones = (k.zones || []).map((z, i) => {
      if (z.read === "said") {            // words said (no box): « 🗣 dit « je suis mort » », ⚠ while not transcribed
        const unread = (this.v.rushes || []).some((r) => !(r.speech || {}).done);
        return `<span class="mo-zchip said ${z.negate ? "neg" : ""}" data-box="null" title="${esc(unread ? t("Lisez d'abord ce qui est dit (bouton au-dessus de la frise).") : t("Trouvé dans ce qui est dit"))}">🗣 ${z.negate ? esc(t("pas de")) + " " : ""}${esc(t("dit « {w} »", { w: z.words.join(", ") }))}${unread ? ` <span class="mo-warn">⚠ ${esc(t("pas encore lu"))}</span>` : ""}
        <button class="icon-btn" data-act="mo-unzone" data-arg="${esc(k.id)}" data-value="${i}" title="${esc(t("Retirer"))}">✕</button></span>`;
      }
      const what = z.read === "text" ? t("texte « {w} »", { w: z.words.join(", ") })
        : z.read === "look" ? t("apparition")
        : z.drop ? t("jauge qui chute") : t("jauge sous {p} %", { p: Math.round(z.below * 100) });
      return `<span class="mo-zchip ${z.negate ? "neg" : ""}" data-box="${esc(JSON.stringify(z.box))}" title="${esc(t("Survolez pour voir la zone sur la vidéo"))}">▭ ${z.negate ? esc(t("pas de")) + " " : ""}${esc(what)}
        <button class="icon-btn" data-act="mo-unzone" data-arg="${esc(k.id)}" data-value="${i}" title="${esc(t("Retirer cette zone"))}">✕</button></span>`;
    }).join("");
    const text = this.whyText(k, !!(k.zones || []).length);
    return text + (zones ? `<span class="mo-zchips">${zones}</span>` : "");
  },
  whyText(k, zoned) {
    const e = k.explain || {}, lv = (z) => (z >= 4 ? t("forte") : z >= 2 ? t("moyenne") : t("faible"));
    if (!k.ready) return `⚠ ${esc(k.learned ? t("Glissez sur la frise pour lui donner un exemple.") : k.hint || "")}`;
    if (!e.examples) return zoned && k.user ? "" : esc(k.hint || (k.learned ? t("Lancez la recherche pour apprendre.") : ""));
    const parts = [];
    if (e.image != null) parts.push(t("image {lv}", { lv: lv(e.image) }));
    if (e.sound != null) parts.push(t("son {lv}", { lv: lv(e.sound) }));
    const n = k.examples || 0;
    const ex = k.learned ? (n === 1 ? t("1 exemple") : t("{n} exemples", { n })) + (k.counter ? ` · ${k.counter} ✗` : "") : "";
    let warn = "";
    if (e.confused && !zoned) warn = t("Vos ✓ et ✗ se ressemblent à l'image et au son : tracez une zone sur ce qui les distingue (bouton Zone).");
    else if (k.learned && !zoned && Math.max(e.image || 0, e.sound || 0) < 2) warn = t("Ces exemples ressemblent au reste : ajoutez-en d'autres, des ✗, ou une zone de l'écran qui les distingue.");
    const head = k.learned ? t("Reconnu par") : t("Affiné par vos ✓ / ✗ :");
    return `${esc(head)} ${esc(parts.join(" · "))}${ex ? ` <span class="muted">(${esc(ex)})</span>` : ""}${warn ? `<br><span class="mo-warn">⚠ ${esc(warn)}</span>` : ""}`;
  },

  renderBoard() {
    const el = $("#mo-board"), R = this.R;
    if (!el) return;
    const all = (this.v.rushes || []).reduce((a, r) => a + r.moments.length, 0);
    $("#mo-count").textContent = all ? t("{n} moments", { n: all }) : "";
    if (!R) { el.innerHTML = `<div class="empty">${t("Ajoutez les rushs, puis lancez la recherche.")}</div>`; return; }
    if (!R.frames.length) { el.innerHTML = `<div class="empty">${t("Lancez la recherche : la planche se remplit quand les rushs sont lus.")}</div>`; return; }
    const pick = this.v.rushes.length > 1 ? `<select id="mo-rush">${this.v.rushes.map((r, i) =>
      `<option value="${i}" ${i === this.rush ? "selected" : ""}>${esc(r.name)}</option>`).join("")}</select>` : "";
    const keep = el.querySelector("video");
    const sameVideo = keep && keep.dataset.src === R.video;
    if (!sameVideo) {
      el.innerHTML = `<div class="mo-top"><div class="mo-player"><video controls preload="metadata" data-src="${esc(R.video)}" src="${esc(R.video)}"></video>
          <div class="mo-zlayer" hidden></div><div class="mo-zshow" hidden></div>
          <div class="mo-now"><b id="mo-tc">0:00:00</b><span class="muted" id="mo-here"></span>${pick}
            <button class="btn small mo-zonebtn" data-act="mo-zone" title="${esc(t("Tracez un rectangle sur la vidéo : une jauge, un texte, une icône du jeu"))}">▭ ${t("Zone")}</button>
            <button class="btn small mo-fullbtn" data-act="mo-full">${t("Plein écran")}</button></div></div>
          <div class="mo-cards" id="mo-cards"></div></div>
        <div class="mo-chips" id="mo-chips"></div>
        <div class="mo-said" id="mo-said"></div>
        <p class="note mo-howto">${esc(t("Glissez sur la frise pour montrer un moment : il devient un nouveau type, ou un exemple d'un type existant."))}</p>
        <div class="mo-tl" id="mo-tl"></div>
        <div class="mo-tip" id="mo-tip"><img alt=""><span></span></div>
        <div class="mo-teach" id="mo-teach" hidden></div>
        <div class="mo-teach mo-zonep" id="mo-zone" hidden></div>`;
      const video = $("video", el), tl = $("#mo-tl");
      video.addEventListener("timeupdate", () => this.place());
      tl.addEventListener("mousedown", (e) => {
        if (e.button !== 0 || e.target.closest(".mo-blk")) return;
        e.preventDefault();                 // no native drag of the thumbnails (it would also open the drop veil)
        this.drag = { t0: this.x2t(e), x0: e.clientX, moved: false };
      });
      addEventListener("mouseup", (e) => {
        const d = this.drag;
        this.drag = null;
        if (!d || !d.moved) return;
        this.justDragged = true;
        const t1 = this.x2t(e), a = Math.min(d.t0, t1), b = Math.max(d.t0, t1);
        if (b - a >= 1) this.teachAsk(a, b, e);
        else this.clearSel();
      });
      tl.addEventListener("click", (e) => {
        if (this.justDragged) { this.justDragged = false; return; }
        const said = e.target.closest(".mo-stick");
        if (said) return this.saidPlay(+said.dataset.t);
        const b = e.target.closest(".mo-blk");
        if (b) return this.play(+b.dataset.i);
        video.currentTime = this.x2t(e);
      });
      tl.addEventListener("mousemove", (e) => {
        this.hover(e);
        const d = this.drag;
        if (d && (d.moved || Math.abs(e.clientX - d.x0) > 4)) { d.moved = true; this.showSel(d.t0, this.x2t(e)); }
      });
      $("#mo-tl").addEventListener("mouseleave", () => { $("#mo-tip").style.display = "none"; const h = $(".mo-hov"); if (h) h.style.display = "none"; });
      $("#mo-cards").addEventListener("click", (e) => {
        const mark = e.target.closest("[data-mark]");
        if (mark) { e.stopPropagation(); return this.mark(+mark.dataset.i, mark.dataset.mark); }
        const c = e.target.closest(".mo-card");
        if (c) this.play(+c.dataset.i);
      });
      $("#mo-chips").addEventListener("click", (e) => {
        const c = e.target.closest(".mo-chip");
        if (!c) return;
        if (this.hidden.has(c.dataset.t)) this.hidden.delete(c.dataset.t); else this.hidden.add(c.dataset.t);
        this.renderBoard();
      });
      if ($("#mo-rush")) $("#mo-rush").addEventListener("change", (e) => { this.rush = +e.target.value; this.renderBoard(); });
    }
    this.renderChips();
    this.renderSaid();
    this.renderTimeline();
    this.renderCards();
    this.place();
  },

  // --- « Ce qui est dit »: search the words said (speech.py), make them a kind of moment ---------------
  saidHits() {                        // hits of the current search in the rush shown (null: no search)
    if (!this.said || !this.saidQ || !this.R) return null;
    const r = (this.said.rushes || []).find((x) => x.path === this.R.path);
    return r ? r.hits : [];
  },
  renderSaid() {
    const el = $("#mo-said"), R = this.R;
    if (!el || !R) return;
    const rushes = this.v.rushes || [], read = rushes.every((r) => (r.speech || {}).done);
    const mode = read ? "read" : "unread";
    if (el.dataset.mode !== mode) {
      el.dataset.mode = mode;
      const left = rushes.filter((r) => !(r.speech || {}).done).reduce((a, r) => a + (r.duration || 0), 0);
      const model = ((app.view && app.view.state.opts) || {}).model || "large-v3", rate = MO_SPEECH_MIN_PER_H[model];
      const cost = rate ? t("≈ {d}, une seule fois, sur cet ordinateur", { d: dur(left / 3600 * rate * 60 + 10) })
        : t("une seule fois, sur cet ordinateur");
      el.innerHTML = `<label class="mo-said-q"><span class="flabel">🗣 ${t("Ce qui est dit")}</span>
          <input id="mo-said-q" type="search" autocomplete="off" spellcheck="false" value="${esc(this.saidQ || "")}"
            placeholder="${esc(t("Ex. : je suis mort, on raid"))}" ${read ? "" : "disabled"}></label>
        ${read ? `<button class="btn small" data-said="kind" title="${esc(t("Chaque fois que ces mots sont dits devient un moment"))}">${t("En faire un type de moment")}</button>`
          : `<button class="btn small primary" data-run="moments_speech" ${app.job.running ? "disabled" : ""}
              title="${esc(t("Transcrit la voix des rushs avec Whisper ({model}).", { model }))}">${t("Lire ce qui est dit")}</button>
            <span class="note">${esc(cost)}</span>`}
        <div class="mo-said-hits" id="mo-said-hits"></div>`;
      const q = $("#mo-said-q");
      q.addEventListener("input", () => { clearTimeout(this.saidTimer); this.saidTimer = setTimeout(() => this.saidSearch(), 250); });
      q.addEventListener("keydown", (e) => { if (e.key === "Enter") { clearTimeout(this.saidTimer); this.saidSearch(); } });
      el.onclick = (e) => {
        const b = e.target.closest("[data-said]");
        if (!b) return;
        if (b.dataset.said === "kind") return this.saidKind();
        if (b.dataset.said === "go") return this.saidPlay(+b.dataset.t);
      };
    }
    this.renderSaidHits();
  },
  renderSaidHits() {
    const el = $("#mo-said-hits"), hits = this.saidHits();
    if (!el) return;
    const kind = $('#mo-said [data-said="kind"]');
    if (kind) kind.disabled = !(this.saidQ || "").trim();
    if (!hits) { el.innerHTML = ""; return; }
    const others = (this.said.rushes || []).filter((r) => r.path !== this.R.path).reduce((a, r) => a + r.hits.length, 0);
    const head = hits.length ? (hits.length === 1 ? t("1 fois") : t("{n} fois", { n: hits.length })) : t("Jamais dit dans ce rush.");
    el.innerHTML = `<p class="note">${esc(head)}${others ? " · " + esc(t("{n} dans les autres rushs", { n: others })) : ""}</p>` +
      (hits.length ? `<ol>${hits.map((h) => `<li><button class="link" data-said="go" data-t="${h.start}"><b>${tc(h.start)}</b> ${esc(h.text)}</button></li>`).join("")}</ol>` : "");
  },
  async saidSearch() {
    const q = (($("#mo-said-q") || {}).value || "").trim();
    this.saidQ = q;
    this.said = q ? await app.api.moments_said(q) : null;
    if (q !== this.saidQ) return;                 // typed on meanwhile
    this.renderSaidHits();
    this.renderTimeline();
    this.place();
  },
  async saidKind() {
    const q = (this.saidQ || "").trim();
    if (!q) return;
    const r = await app.api.moments_said_kind(q);
    app.toast(r.message);
    if (r.ok) { this.said = r; this.dirty = false; }
  },
  saidPlay(t0) {
    const video = $("#mo-board video");
    if (!video) return;
    video.currentTime = Math.max(0, t0 - 1);      // a second before: the phrase is heard from its start
    video.play();
  },

  renderChips() {
    const R = this.R;
    $("#mo-chips").innerHTML = (this.v.types || []).filter((k) => k.enabled).map((k) => {
      const n = R.moments.filter((m) => m.type === k.id).length;
      return `<span class="mo-chip ${this.hidden.has(k.id) ? "off" : ""}" data-t="${esc(k.id)}"><i style="background:${k.color}"></i>${esc(k.name)} <small>${n}</small></span>`;
    }).join("");
  },

  renderTimeline() {
    const R = this.R, tl = $("#mo-tl"), d = R.duration || 1;
    const pct = (x) => `${(100 * x / d).toFixed(3)}%`;
    const row = (label, cls, inner, title = "") =>
      `<div class="mo-row ${cls}"><div class="mo-lab" title="${esc(title || label)}">${esc(label)}</div><div class="mo-lane">${inner}</div></div>`;
    const step = [60, 120, 300, 600, 1800, 3600].find((s) => d / s <= 12) || 7200;
    let ticks = "";
    for (let s = 0; s <= d; s += step) ticks += `<span style="left:${pct(s)}">${tc(s)}</span>`;
    const n = Math.min(R.frames.length, 60);
    let strip = "";
    for (let i = 0; i < n; i++) strip += `<img src="${R.img}${Math.round(i * (R.frames.length - 1) / Math.max(1, n - 1))}" alt="" loading="lazy">`;
    let html = `<div class="mo-ticks">${ticks}</div>` + row(t("Images"), "strip", strip);
    for (const k of this.v.types || []) {
      if (!k.enabled || this.hidden.has(k.id)) continue;
      const blocks = R.moments.filter((m) => m.type === k.id).map((m) =>
        `<div class="mo-blk ${m.kept === false ? "no" : m.kept ? "yes" : ""}" data-i="${m.i}" title="${esc(`${k.name} · ${tc(m.start)}–${tc(m.end)} · ${Math.round(m.score * 100)} %`)}"
          style="left:${pct(m.start)};width:max(3px,${pct(m.end - m.start)});background:${k.color}"></div>`).join("");
      html += row(k.name + (k.ready ? "" : " ⚠"), "", blocks, k.hint);
    }
    const said = this.saidHits();             // « Ce qui est dit »: where the words searched are said
    if (said) html += row(t("Dit"), "said", said.map((h) => `<i class="mo-stick" data-t="${h.start}" style="left:${pct(h.start)}"
        title="${esc(`${tc(h.start)} · ${h.text}`)}"></i>`).join(""), t("Où « {q} » est dit", { q: this.saidQ }));
    for (const c of R.curves || []) {
      const pts = [];
      c.values.forEach((y, i) => { if (y !== null) pts.push(`${(i / c.values.length * 1000).toFixed(1)},${(MO_CURVE_H - 2 - y * (MO_CURVE_H - 4)).toFixed(1)}`); });
      const shape = c.line ? `<polyline fill="none" stroke="${c.color}" stroke-width="1.6" points="${pts.join(" ")}"/>`
        : `<polygon fill="${c.color}" fill-opacity=".7" points="0,${MO_CURVE_H} ${pts.join(" ")} 1000,${MO_CURVE_H}"/>`;
      html += row(t(c.label), "curve", `<svg viewBox="0 0 1000 ${MO_CURVE_H}" preserveAspectRatio="none">${shape}</svg>`);
    }
    tl.innerHTML = html + `<div class="mo-head"></div><div class="mo-hov"></div><div class="mo-sel" hidden></div>`;
  },

  // --- teaching: a stretch shown on the timeline ----------------------------------------------
  showSel(a, b) {
    const sel = $("#mo-tl .mo-sel");
    if (!sel) return;
    const x0 = this.xOf(Math.min(a, b)), x1 = this.xOf(Math.max(a, b));
    sel.hidden = false;
    sel.style.left = x0 + "px";
    sel.style.width = Math.max(2, x1 - x0) + "px";
  },
  clearSel() {
    const sel = $("#mo-tl .mo-sel"), pop = $("#mo-teach");
    if (sel) sel.hidden = true;
    if (pop) pop.hidden = true;
    this.sel = null;
  },
  teachAsk(a, b, e) {
    this.sel = { a, b };
    this.showSel(a, b);
    const kinds = (this.v.types || []).filter((k) => k.enabled);
    const pop = $("#mo-teach");
    pop.innerHTML = `<div class="mo-teach-h"><b>${tc(a)} – ${tc(b)}</b> <span class="muted">${Math.round(b - a)} s</span>
        <button class="link" data-teach="play">${t("voir")}</button><button class="icon-btn" data-teach="close" title="${esc(t("Fermer"))}">✕</button></div>
      <label class="lbl">${t("Nouveau type de moment")}
        <span class="mo-row2"><input id="mo-teach-name" type="text" placeholder="${esc(t("Ex. : En bateau, Raid, Coucher de soleil"))}">
        <button class="btn primary small" data-teach="new">${t("Créer")}</button></span></label>
      <label class="lbl">${t("ou un exemple de")}
        <span class="mo-row2"><select id="mo-teach-kind">${kinds.map((k) => `<option value="${esc(k.id)}">${esc(k.name)}</option>`).join("")}</select>
        <button class="btn small" data-teach="pos" title="${esc(t("C'est ce type de moment"))}">✓ ${t("C'est ça")}</button>
        <button class="btn small" data-teach="neg" title="${esc(t("Ça ressemble à ce type, mais ce n'en est pas un"))}">✗ ${t("Pas ça")}</button></span></label>`;
    pop.hidden = false;
    const box = $("#mo-board").getBoundingClientRect();
    pop.style.left = Math.max(8, Math.min(box.width - 380, e.clientX - box.left - 180)) + "px";
    pop.style.top = (e.clientY - box.top + 14) + "px";
    pop.onclick = async (ev) => {
      const btn = ev.target.closest("[data-teach]");
      if (!btn) return;
      const what = btn.dataset.teach, video = $("#mo-board video");
      if (what === "close") return this.clearSel();
      if (what === "play") { video.currentTime = a; video.play(); return; }
      const ex = { rush: this.R.path, start: a, end: b };
      if (what === "new") ex.name = $("#mo-teach-name").value;
      else { ex.kind = $("#mo-teach-kind").value; ex.neg = what === "neg"; }
      const r = await app.api.moments_teach(ex);
      app.toast(r.message);
      if (r.ok) { this.clearSel(); this.dirty = false; }
    };
    $("#mo-teach-name").addEventListener("keydown", (ev) => { if (ev.key === "Enter") pop.querySelector('[data-teach="new"]').click(); });
    setTimeout(() => $("#mo-teach-name").focus(), 0);
  },
  // --- screen zones: a box drawn on the video (a gauge, a text, an icon) ------------------------
  // where the picture is inside the <video> (letterboxed), in the player's coordinates
  pictureRect() {
    const video = $("#mo-board video"), player = $("#mo-board .mo-player");
    const r = video.getBoundingClientRect(), pr = player.getBoundingClientRect();
    const vw = video.videoWidth || 16, vh = video.videoHeight || 9, s = Math.min(r.width / vw, r.height / vh);
    const w = vw * s, h = vh * s;
    return { left: r.left - pr.left + (r.width - w) / 2, top: r.top - pr.top + (r.height - h) / 2, width: w, height: h };
  },
  placeBox(el, box) {
    const p = this.pictureRect();
    Object.assign(el.style, { left: `${p.left + box[0] * p.width}px`, top: `${p.top + box[1] * p.height}px`,
      width: `${box[2] * p.width}px`, height: `${box[3] * p.height}px` });
  },
  showBox(box) {
    const el = $("#mo-board .mo-zshow");
    if (!el) return;
    if (!box) { el.hidden = true; return; }
    el.hidden = false;
    this.placeBox(el, box);
  },
  zoneMode(on) {
    const layer = $("#mo-board .mo-zlayer"), video = $("#mo-board video");
    if (!layer) return;
    $("#mo-zone").hidden = true;
    if (!on) { layer.hidden = true; layer.innerHTML = ""; $(".mo-zonebtn").classList.remove("on"); return; }
    video.pause();
    $(".mo-zonebtn").classList.add("on");
    const p = this.pictureRect();
    layer.hidden = false;
    Object.assign(layer.style, { left: `${p.left}px`, top: `${p.top}px`, width: `${p.width}px`, height: `${p.height}px` });
    layer.innerHTML = `<span class="mo-zhelp">${esc(t("Tracez un rectangle autour de la jauge, du texte ou de l'icône"))}</span>`;
    let start = null, rect = null;
    const at = (e) => { const r = layer.getBoundingClientRect();
      return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))]; };
    layer.onmousedown = (e) => {
      e.preventDefault();
      start = at(e);
      layer.innerHTML = `<div class="mo-zbox"></div>`;
      rect = $(".mo-zbox", layer);
    };
    layer.onmousemove = (e) => {
      if (!start) return;
      const [x, y] = at(e);
      Object.assign(rect.style, { left: `${Math.min(x, start[0]) * 100}%`, top: `${Math.min(y, start[1]) * 100}%`,
        width: `${Math.abs(x - start[0]) * 100}%`, height: `${Math.abs(y - start[1]) * 100}%` });
    };
    layer.onmouseup = (e) => {
      if (!start) return;
      const [x, y] = at(e), box = [Math.min(x, start[0]), Math.min(y, start[1]), Math.abs(x - start[0]), Math.abs(y - start[1])];
      start = null;
      if (box[2] < 0.005 || box[3] < 0.005) { layer.innerHTML = ""; return; }
      this.zoneAsk(box.map((v) => Math.round(v * 10000) / 10000), e);
    };
  },
  zoneAsk(box, e) {
    const video = $("#mo-board video"), t0 = video.currentTime, pop = $("#mo-zone");
    this.zone = { box, t: t0, read: "", side: "left", negate: false, below: 0.3, drop: false };
    const kinds = (this.v.types || []).filter((k) => k.enabled);
    pop.innerHTML = `<div class="mo-teach-h"><b>${t("Zone")}</b> <span class="muted">${t("à {tc}", { tc: tc(t0) })}</span>
        <button class="icon-btn" data-z="close" title="${esc(t("Fermer"))}">✕</button></div>
      <div class="lbl">${t("Que contient cette zone ?")}
        <span class="mo-seg"><button class="btn small" data-z="read" data-v="gauge">${t("Une jauge")}</button>
        <button class="btn small" data-z="read" data-v="text">${t("Du texte")}</button>
        <button class="btn small" data-z="read" data-v="look">${t("Une icône, un bandeau")}</button></span></div>
      <div id="mo-zopts"></div>
      <div id="mo-ztarget" hidden>
        <label class="lbl">${t("Ajouter à")}
          <span class="mo-row2"><select id="mo-zkind">${kinds.map((k) => `<option value="${esc(k.id)}">${esc(k.name)}</option>`).join("")}</select>
          <button class="btn small" data-z="add">${t("Ajouter")}</button></span></label>
        <label class="lbl">${t("ou un nouveau type")}
          <span class="mo-row2"><input id="mo-zname" type="text" placeholder="${esc(t("Ex. : Vie basse, Kill, Récolte"))}">
          <button class="btn primary small" data-z="new">${t("Créer")}</button></span></label></div>`;
    pop.hidden = false;
    const board = $("#mo-board").getBoundingClientRect();
    pop.style.left = Math.max(8, Math.min(board.width - 390, e.clientX - board.left - 190)) + "px";
    pop.style.top = Math.min(e.clientY - board.top + 14, board.height - 40) + "px";
    pop.onclick = (ev) => this.zoneClick(ev);
    pop.oninput = (ev) => {
      if (ev.target.id === "mo-zbelow") { this.zone.below = +ev.target.value / 100; $("#mo-zbelow-v").textContent = `${ev.target.value} %`; }
    };
    pop.onchange = (ev) => { if (ev.target.id === "mo-zside") { this.zone.side = ev.target.value; this.zonePreview(); } };
  },
  zoneOpts() {
    const z = this.zone, el = $("#mo-zopts");
    $$("#mo-zone [data-z=read]").forEach((b) => b.classList.toggle("primary", b.dataset.v === z.read));
    $("#mo-ztarget").hidden = !z.read;
    const two = (a, b) => `<span class="mo-seg"><button class="btn small ${!z.negate ? "primary" : ""}" data-z="neg" data-v="0">${a}</button>
      <button class="btn small ${z.negate ? "primary" : ""}" data-z="neg" data-v="1">${b}</button></span>`;
    if (z.read === "gauge") el.innerHTML = `<div class="lbl">${t("Elle se remplit depuis")}
        <select id="mo-zside">${[["left", t("la gauche")], ["right", t("la droite")], ["bottom", t("le bas")], ["top", t("le haut")]]
          .map(([v, n]) => `<option value="${v}" ${z.side === v ? "selected" : ""}>${n}</option>`).join("")}</select>
        <span class="note" id="mo-zprev">${t("lecture…")}</span></div>
      <div class="lbl">${t("Le moment, c'est quand elle est")}
        <span class="mo-seg"><button class="btn small ${!z.drop ? "primary" : ""}" data-z="drop" data-v="0">${t("basse")}</button>
        <button class="btn small ${z.drop ? "primary" : ""}" data-z="drop" data-v="1">${t("en chute rapide")}</button></span>
        ${!z.drop ? `<span class="mo-row2">${t("sous")} <input id="mo-zbelow" type="range" min="5" max="90" step="5" value="${Math.round(z.below * 100)}"><b id="mo-zbelow-v">${Math.round(z.below * 100)} %</b></span>` : ""}</div>`;
    else if (z.read === "text") el.innerHTML = `<div class="lbl">${t("Lu ici")} <span class="note mo-read" id="mo-zprev">${t("lecture…")}</span></div>
      <label class="lbl">${t("Mots à chercher")} <input id="mo-zwords" type="text" placeholder="${esc(t("Ex. : ORE, WOOD, KILLED"))}" value="${esc(z.words || "")}"></label>
      <div class="lbl">${t("Le moment, c'est quand la zone")} ${two(t("contient un de ces mots"), t("n'en contient aucun"))}</div>`;
    else if (z.read === "look") el.innerHTML = `<div class="lbl">${t("Le moment, c'est quand la zone")}
      ${two(t("ressemble à maintenant"), t("ne ressemble pas à maintenant"))}
      <span class="note">${esc(t("Mettez la vidéo sur une image où l'icône ou le bandeau est visible avant de tracer."))}</span></div>`;
    else el.innerHTML = "";
  },
  async zonePreview() {
    const z = this.zone;
    if (!z || !["gauge", "text"].includes(z.read)) return;
    const r = await app.api.moments_zone_preview({ rush: this.R.path, t: z.t, box: z.box, read: z.read, side: z.side });
    const el = $("#mo-zprev");
    if (!el) return;
    if (!r.ok) { el.textContent = r.message || ""; return; }
    if (z.read === "text") {
      el.textContent = r.text ? r.text : t("aucun texte lu ici");
      const words = $("#mo-zwords");
      if (words && !words.value && r.text) words.placeholder = t("Ex. : {w}", { w: r.text.split(/\s+/).slice(0, 2).join(", ") });
    } else el.textContent = t("remplie à {p} % ici", { p: Math.round(r.fill * 100) });
  },
  async zoneClick(ev) {
    const b = ev.target.closest("[data-z]");
    if (!b) return;
    const z = this.zone, what = b.dataset.z;
    if (what === "close") return this.zoneMode(false);
    if (what === "read") { z.read = b.dataset.v; this.zoneOpts(); return this.zonePreview(); }
    if (what === "neg") { z.negate = b.dataset.v === "1"; z.words = ($("#mo-zwords") || {}).value || z.words; return this.zoneOpts(); }
    if (what === "drop") { z.drop = b.dataset.v === "1"; return this.zoneOpts(); }
    if (what === "add" || what === "new") {
      const req = { ...z, rush: this.R.path, words: ($("#mo-zwords") || {}).value || z.words || "" };
      if (what === "add") req.kind = $("#mo-zkind").value; else req.name = $("#mo-zname").value;
      const r = await app.api.moments_zone(req);
      app.toast(r.message);
      if (r.ok) this.zoneMode(false);
    }
  },

  full(on) {
    const el = $("#mo-board");
    if (!el) return;
    el.classList.toggle("full", on);
    const b = $(".mo-fullbtn", el);
    if (b) b.textContent = on ? t("Quitter le plein écran") : t("Plein écran");
    setTimeout(() => this.place(), 50);
  },

  renderCards() {
    const R = this.R;
    const list = R.moments.filter((m) => !this.hidden.has(m.type) && this.type(m.type).enabled !== false).sort((a, b) => a.start - b.start);
    $("#mo-cards").innerHTML = list.length ? list.map((m) => {
      const k = this.type(m.type), mid = k.mode === "state" ? (m.anchor + m.end) / 2 : m.anchor;
      return `<div class="mo-card ${m.kept === false ? "no" : m.kept ? "yes" : ""}" data-i="${m.i}" style="border-left-color:${k.color}">
        <img src="${this.img(mid)}" alt="" loading="lazy">
        <div class="mo-cb"><b>${esc(k.name)}</b><span class="muted">${tc(m.start)} · ${Math.round(m.end - m.start)} s</span>
          <div class="mo-sc"><i style="width:${Math.round(m.score * 100)}%;background:${k.color}"></i></div></div>
        <div class="mo-marks"><button class="mo-mk ${m.kept === true ? "on" : ""}" data-mark="yes" data-i="${m.i}" title="${esc(t("Garder"))}">✓</button>
          <button class="mo-mk ${m.kept === false ? "on" : ""}" data-mark="no" data-i="${m.i}" title="${esc(t("Ce n'est pas ça"))}">✗</button></div></div>`;
    }).join("") : `<div class="empty">${t("Aucun moment.")}</div>`;
  },

  renderResult() {
    const all = (this.v.rushes || []).flatMap((r) => r.moments);
    const yes = all.filter((m) => m.kept === true).length, no = all.filter((m) => m.kept === false).length;
    const hand = $("#res-mo-hand"), auto = $("#res-mo-auto");
    if (hand) hand.innerHTML = `<div class="body"><h3>${t("Sur la planche")}</h3>
      <p class="note">${esc(t("Cliquez un moment pour le voir. ✓ garde, ✗ écarte : la séquence « Moments · ✓ » ne prend que les ✓."))}</p>
      <p class="note"><b>${esc(t("{n} gardés", { n: yes }))}</b> · ${esc(t("{n} écartés", { n: no }))} · ${esc(t("{n} moments", { n: all.length }))}</p></div>`;
    const dead = (this.v.types || []).filter((k) => k.remove && k.enabled).map((k) => k.name.toLowerCase());
    if (auto) auto.innerHTML = app.autoCard({
      text: esc(t("Une séquence par type de moment, les rushs avec un repère sur chaque moment")) +
        (dead.length ? esc(t(", et chaque rush sans {what}", { what: dead.join(", ") })) : "") + ". " + esc(t("Les clips restent liés aux rushs.")),
      exportRun: "moments_xml", exportLabel: "Exporter pour Premiere (.xml)",
      exportOff: all.length ? "" : t("Cherchez d'abord les moments."),
      extra: this.v.xml ? `<p class="note">${esc(base(this.v.xml))} · <button class="link" data-act="mo-reveal">${t("afficher")}</button></p>` : "",
    });
  },

  // --- the timeline ---------------------------------------------------------------------------
  lane() { return $("#mo-tl .mo-lane"); },
  x2t(e) {
    const r = this.lane().getBoundingClientRect();
    return Math.min(this.R.duration, Math.max(0, (e.clientX - r.left) / r.width * this.R.duration));
  },
  xOf(t) { const l = this.lane(); return l.offsetLeft + l.parentElement.offsetLeft + t / this.R.duration * l.offsetWidth; },
  hover(e) {
    const t0 = this.x2t(e), tip = $("#mo-tip"), h = $(".mo-hov");
    h.style.display = "block";
    h.style.left = this.xOf(t0) + "px";
    tip.style.display = "block";
    $("img", tip).src = this.img(t0);
    $("span", tip).textContent = tc(t0);
    tip.style.left = Math.min(innerWidth - 270, e.clientX + 14) + "px";
    tip.style.top = Math.max(8, e.clientY - 170) + "px";
  },
  place() {
    const video = $("#mo-board video"), head = $(".mo-head");
    if (!video || !head || !this.R) return;
    const now = video.currentTime;
    head.style.left = this.xOf(now) + "px";
    $("#mo-tc").textContent = tc(now);
    const inside = this.R.moments.filter((m) => m.start <= now && now < m.end).map((m) => this.type(m.type).name);
    $("#mo-here").textContent = [...new Set(inside)].join(" · ");
    $$("#mo-cards .mo-card").forEach((c) => {
      const m = this.R.moments.find((x) => x.i === +c.dataset.i);
      c.classList.toggle("on", !!m && m.start <= now && now < m.end);
    });
  },
  play(i) {
    const m = this.R.moments.find((x) => x.i === i), video = $("#mo-board video");
    if (!m || !video) return;
    video.currentTime = m.start;
    video.play();
  },
  async mark(i, which) {
    const m = this.R.moments.find((x) => x.i === i);
    if (!m) return;
    const want = which === "yes" ? true : false;
    m.kept = m.kept === want ? null : want;
    await app.api.moments_mark(i, m.kept);
    this.dirty = "marks";
    this.renderKinds();
    this.renderCards();
    this.renderTimeline();
    this.renderResult();
    this.place();
  },

  async act(what, arg) {
    if (what === "mo-rm") return app.render(await app.api.moments_input(arg || ""));
    if (what === "mo-kind") {
      const k = this.type(arg);
      return this.set({ type: arg, enabled: !k.enabled });
    }
    if (what === "mo-reveal" && this.v.xml) return app.api.reveal(this.v.xml);
    if (what === "mo-del") return this.set({ type: arg, delete: true });
    if (what === "mo-pack-share") {                // game pack: what was taught here, for friends' rushes
      const r = await app.api.moments_pack_export();
      if (r && !r.cancel) app.toast(r.message);
      return;
    }
    if (what === "mo-pack-import") {
      const r = await app.api.moments_pack_import();
      if (!r || r.cancel) return;
      app.toast(r.message);
      if (r.ok && r.view) { this.v = r.view; this.dirty = true; this.render(); }
      return;
    }
    if (what === "mo-full") return this.full(!$("#mo-board").classList.contains("full"));
    if (what === "mo-zone") return this.zoneMode($("#mo-board .mo-zlayer").hidden);
    if (what === "mo-unzone") {
      this.v = await app.api.moments_unzone(arg, +((app._actEl && app._actEl.dataset.value) || 0));
      this.dirty = true;
      return this.render();
    }
  },
};
window.momentsPage = momentsPage;
addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if ($("#mo-board .mo-zlayer") && !$("#mo-board .mo-zlayer").hidden) momentsPage.zoneMode(false);
  else if ($("#mo-teach") && !$("#mo-teach").hidden) momentsPage.clearSel();
  else if ($("#mo-board.full")) momentsPage.full(false);
});
addEventListener("resize", () => momentsPage.place());
