"use strict";
// FauxRaccord window. Python (gui.py, class Api) owns the state; this page renders it and forwards clicks.

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const base = (p) => String(p || "").split(/[\\/]/).pop();
const dir = (p) => String(p || "").replace(/[\\/][^\\/]*$/, "");
// a file's folder as shown under its name: nothing when it is in the project, the sub-folder when below it
function where(p) {
  const root = ((app.view && app.view.project && app.view.project.path) || "").toLowerCase(), d = dir(p);
  if (!root) return d;
  if (d.toLowerCase() === root) return "";
  if (d.toLowerCase().startsWith(root + "\\")) return d.slice(root.length + 1);
  return d;
}
// each project its own colour, so two folders are told apart at a glance
function hue(path) {
  let h = 0;
  for (const c of String(path).toLowerCase()) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return h % 360;
}
const AUDIO = /\.(wav|bwf|aif|aiff|flac|mp3|m4a)$/i;
const VIDEO = /\.(mp4|mov|mxf|mkv|avi|mts|m2ts)$/i;
const STEP_OF_JOB = { sync: "sync", derush: "derush", collect: "sources", place: "sources", fetch: "sources", storyboard: "storyboard",
  sb_place: "storyboard", sfx: "sfx", sfx_place: "sfx", sfx_suggest: "sfx", setup: "setup",
  moments: "moments", moments_xml: "moments" };
const JOB_TITLE = { sync: "Synchro", derush: "Derush", collect: "Collecte des illustrations", place: "Export du XML des illustrations",
  fetch: "Téléchargement des images à placer", storyboard: "Storyboard", sb_place: "Export du XML du storyboard", sfx: "Analyse du montage",
  sfx_place: "Export du XML des sons", sfx_suggest: "Ambiances et musiques", setup: "Installation",
  moments: "Recherche des moments", moments_xml: "Export du XML des moments" };
const PREMIERE_LINE = { sources: "#prem-sources", storyboard: "#prem-storyboard" };
JOB_TITLE.panel = "Installation du panneau Premiere";
const EXPORT_OF_RUN = { sync: "sync", derush: "derush", place: "sources", sb_place: "storyboard", sfx_place: "sfx", moments_xml: "moments" };
const ICON = {
  folder: '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
  md: '<svg viewBox="0 0 24 24"><path d="M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6"/></svg>',
  xml: '<svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h10M4 18h7"/></svg>',
  zap: '<svg viewBox="0 0 24 24"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>',
};
const SFX_KINDS = [["whoosh", "Whoosh", "#4a6cf7"], ["click", "Clic", "#1f9d63"], ["pop", "Pop", "#e8833a"], ["typing", "Clavier", "#9b59b6"], ["hit", "Impact", "#d6453d"]];
const AUTO_ORDER = ["gemini", "claude", "claude-code", "codex", "antigravity", "ollama"];
const ENGINE_CHOICES = [["auto", "Auto : la première IA connectée"], ["gemini", "Gemini (clé API)"],
  ["claude-code", "Claude (abonnement Pro / Max)"], ["codex", "ChatGPT (abonnement, via Codex)"],
  ["antigravity", "Gemini (abonnement Google AI)"], ["claude", "Claude (clé API)"], ["ollama", "Ollama (local)"],
  ["off", "Aucune (recherche par noms propres et dates)"]];
const LABELS_FR = [
  [/^syncing/, "Synchronisation par le son"], [/^reading/, "Lecture de la séquence"],
  [/^transcribing/, "Transcription"], [/^aligning/, "Alignement sur le script"],
  [/^cutting/, "Découpe"], [/^writing Premiere XML/, "Écriture du XML Premiere"],
  [/^looking inside the rendered clips/, "Animations dans les clips"], [/^gathering the sounds/, "Préparation des sons"],
  [/^placing/, "Placement des sons"], [/^voice for the page/, "Voix pour l'éditeur"],
];

function view_beat(view) { return (view && view.state && view.state.beat) || {}; }
function tc(s) {
  s = Math.max(0, Math.round(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}`;
}
function dur(s) {
  s = Math.round(s || 0);
  if (s < 90) return t("{s} s", { s });
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h ? t("{h} h {m}", { h, m: String(m).padStart(2, "0") }) : t("{m} min", { m });
}
function parseTc(t) {
  const parts = String(t).trim().split(":").map(Number);
  if (parts.some(isNaN)) return null;
  return parts.reduce((a, v) => a * 60 + v, 0);
}

const app = {
  view: null,
  step: "sync",
  hoverZone: null,
  job: { step: null, running: false },
  logLines: [],
  prem: {},              // last news of « Placer dans Premiere », per page
  guide: {},             // the panel's install guide, opened on a page
  panelPage: "sources",  // where the panel's install was started (its progress shows there)
  stepOf(job) { return job === "panel" ? this.panelPage : STEP_OF_JOB[job]; },

  async start() {
    this.api = window.pywebview.api;
    try {
      const l = await this.api.i18n();
      I18N.set(l.lang, l.dict);
      const pick = $("#ui-lang");
      pick.innerHTML = Object.entries(l.names).map(([k, n]) => `<option value="${k}"${k === l.lang ? " selected" : ""}>${esc(n)}</option>`).join("");
      pick.addEventListener("change", () => this.api.set_ui_lang(pick.value));
    } catch (e) { /* stays in French */ }
    this.bind();
    this.render(await this.api.init());
    this.show(this.view.state.step || "sync", false);
    await this.plancheInit();
    setInterval(() => this.poll(), 3000);
  },

  // --- events from Python ---------------------------------------------------------------------
  event(ev) {
    if (ev.type === "view") this.render(ev.view);
    else if (ev.type === "added") { this.render(ev.view); this.toast(ev.notes); this.show(this.view.state.step); }
    else if (ev.type === "log") this.onLog(ev);
    else if (ev.type === "job") this.onJob(ev);
    else if (ev.type === "ai") { if (this.view) { this.view.ai = ev.ai; this.renderAI(); this.renderNav(); } }
    else if (ev.type === "premiere") this.followPremiere(ev.id, ev.kind);
    else if (ev.type === "toast") { if (ev.text) this.toast(ev.text); }
    else if (ev.type === "show") { this.plancheMode(false); this.show(ev.step); }
    else if (ev.type === "planche") this.plancheShow(ev.tab, ev.url, ev.sub);
    else if (ev.type === "planche-drop") this.plancheDrop(ev.tabs || []);
    else if (ev.type === "playhead") this.onPlayhead(ev);
    else if (ev.type === "panel-guide") { this.guide[ev.kind] = true; this.show(ev.kind); this.render(this.view); }
    else if (ev.type === "checks") { if (this.view) this.view.checks = ev.checks; this.renderChecks(); this.renderNav(); if (this.view) this.renderDerush(); }
  },
  dropZone() {
    // scripts are recognised by their extension, so the script card stands for its page
    const page = { sync: "sync", derush: "derush", sources: "sources", storyboard: "storyboard", sfx: "sfx", beat: "beat", moments: "moments" }[this.step] || "sync";
    return this.hoverZone && this.hoverZone !== "script" ? this.hoverZone : page;
  },

  // --- navigation -----------------------------------------------------------------------------
  show(step, save = true) {
    if (step === "planche") return this.plancheMode(true);
    this.step = step;
    $$(".step").forEach((b) => b.classList.toggle("active", b.dataset.step === step));
    $$(".page").forEach((p) => p.classList.toggle("active", p.id === `page-${step}`));
    this.placeJob();
    if (save && this.view && this.view.state.step !== step) this.api.set("step", step);
    $("#main").scrollTop = 0;
    if (step === "beat" && window.beatPage) beatPage.show();
    if (step === "moments" && window.momentsPage) momentsPage.show();
  },

  bind() {
    $$(".step").forEach((b) => b.addEventListener("click", () => this.show(b.dataset.step)));
    $("#proj-btn").addEventListener("click", (e) => {
      e.stopPropagation();
      if (!this.view.project.recent.length) return this.act("proj-open");
      this.menu(!!$("#proj-menu").hidden);
    });
    document.addEventListener("click", (e) => { if (!e.target.closest("#project")) this.menu(false); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") this.menu(false); });
    document.addEventListener("click", async (e) => {
      const t = e.target.closest("[data-pick],[data-run],[data-remove],[data-act]");
      if (!t || t.disabled) return;
      if (t.dataset.pick) {
        const r = await this.api.pick(t.dataset.pick, !!t.dataset.folder);
        if (r) { this.render(r.view); this.toast(r.notes); this.show(this.view.state.step); }
      } else if (t.dataset.run) this.run(t.dataset.run);
      else if (t.dataset.remove) this.render(await this.api.remove(t.dataset.remove, t.dataset.value || ""));
      else if (t.dataset.act) { this._actEl = t; this.act(t.dataset.act, t.dataset.arg); }
    });
    $("#go-sync").addEventListener("click", () => this.run("sync"));
    $("#go-derush").addEventListener("click", () => this.run("derush"));
    $("#stop").addEventListener("click", () => this.api.stop());
    $("#recheck").addEventListener("click", () => { $("#checks").innerHTML = `<li class="muted">${esc(t("Vérification…"))}</li>`; this.api.check(); });
    $("#chain").addEventListener("change", (e) => this.set("chain", e.target.checked));
    // on/off options shown as switches (data-toggle="shots" → opts.shots)
    document.addEventListener("click", (e) => {
      const sw = e.target.closest("[data-toggle]");
      if (sw && this.view) this.set(`opts.${sw.dataset.toggle}`, !this.view.state.opts[sw.dataset.toggle]);
    });
    $("#ai-recheck").addEventListener("click", () => { $("#ai-list").innerHTML = `<li class="muted">${esc(t("Vérification…"))}</li>`; this.api.ai_check(); });
    $("#ai-engine").innerHTML = ENGINE_CHOICES.map(([v, l]) => `<option value="${v}">${esc(t(l))}</option>`).join("");
    const saveKey = async () => {
      const input = $("#gemini-key"), btn = $("#save-gemini");
      btn.disabled = true;
      $("#gemini-status").className = "muted";
      $("#gemini-status").textContent = input.value.trim() ? t("Vérification auprès de Google…") : "";
      const r = await this.api.set_key("gemini", input.value);
      btn.disabled = false;
      if (r.ok) input.value = "";
      if (r.view) this.render(r.view);
      if (!r.ok) { $("#gemini-status").className = "bad"; $("#gemini-status").textContent = r.message; }
      this.toast(r.message);
    };
    $("#save-gemini").addEventListener("click", saveKey);
    $("#gemini-key").addEventListener("keydown", (e) => { if (e.key === "Enter") saveKey(); });
    $("#copy-log").addEventListener("click", (e) => {
      e.preventDefault();
      navigator.clipboard.writeText($("#log").innerText);
      this.toast(t("Journal copié"));
    });
    $$("[data-opt]").forEach((el) => el.addEventListener(el.tagName === "TEXTAREA" ? "input" : "change", () => {
      if (el.tagName === "TEXTAREA") { clearTimeout(el._t); el._t = setTimeout(() => this.set(`opts.${el.dataset.opt}`, el.value), 400); return; }
      let v = el.type === "checkbox" ? el.checked : el.value;
      if (el.type === "number" || el.dataset.num) v = Number(v);
      this.set(`opts.${el.dataset.opt}`, v);
    }));

    // drag and drop: Python receives the files; the page shows where they will land
    let depth = 0;
    document.addEventListener("dragenter", (e) => { depth++; document.body.classList.add("dragging"); });
    document.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; this.endDrag(); } });
    document.addEventListener("dragover", (e) => {
      e.preventDefault();
      const z = e.target.closest("[data-zone]");
      this.hoverZone = z ? z.dataset.zone : null;
      $$("[data-zone]").forEach((el) => el.classList.toggle("over", el === z));
      if (!z) { const def = $(`.page.active [data-zone]`); if (def) def.classList.add("over"); }
    });
    document.addEventListener("drop", (e) => { e.preventDefault(); depth = 0; setTimeout(() => this.endDrag(), 50); });
  },
  endDrag() {
    document.body.classList.remove("dragging");
    $$("[data-zone]").forEach((el) => el.classList.remove("over"));
    setTimeout(() => { this.hoverZone = null; }, 500);
  },

  async set(key, value) { this.render(await this.api.set(key, value)); },
  async run(step) {
    const r = await this.api.run(step);
    if (!r.ok) this.toast(r.message);
  },
  async act(what, arg) {
    if (what === "reveal") this.api.reveal(arg);
    else if (what === "open") this.api.open_path(arg);
    else if (what === "go") this.show(arg);
    else if (what === "report") this.api.report();
    else if (what === "install") { const r = await this.api.install(arg); if (!r.ok) this.toast(r.message); }
    else if (what === "url") this.api.open_url(arg);
    else if (what === "ai-connect" || what === "ai-test") {
      const btn = document.activeElement;
      if (what === "ai-test" && btn) { btn.disabled = true; btn.textContent = t("Test…"); }
      const r = await (what === "ai-connect" ? this.api.ai_connect(arg) : this.api.ai_test(arg));
      this.toast(r.message);
      if (what === "ai-connect") setTimeout(() => this.api.ai_check(), 20000);
    }
    else if (what === "ai-install") { const r = await this.api.ai_install(arg); if (!r.ok) this.toast(r.message); }
    else if (what === "ai-use") await this.set("opts.llm", arg);
    else if (what === "use-sync") { await this.set("xml", this.view.state.sync_out); this.show("derush"); }
    else if (what === "proj-open") {
      this.menu(false);
      const r = await this.api.open_project(arg || "");
      if (!r) return;
      if (r.view) this.render(r.view);
      if (r.ok) this.show(this.view.state.step, false); else this.toast(r.message);
    }
    else if (what === "open-sheet") { const r = await this.api.open_sheet(); if (!r.ok) this.toast(r.message); }
    else if (what === "open-sb") { const r = await this.api.open_storyboard(); if (!r.ok) this.toast(r.message); }
    else if (what === "open-board") { const r = await this.api.open_board(arg || ""); if (!r.ok) this.toast(r.message); }
    else if (what === "guide") { this.guide[arg] = !this.guide[arg]; this.render(this.view); }
    else if (what === "panel-install") {
      this.panelPage = this.step;
      const r = await this.api.install("panel", true);
      if (!r.ok) this.toast(r.message);
    }
    else if (what === "premiere-remove") {
      const r = await this.api.premiere_remove(arg);
      if (!r.ok) this.toast(r.message);
      else if (r.id) this.followPremiere(r.id, arg);
    }
    else if (what === "premiere") {
      const r = await this.api.premiere(arg);
      if (r.guide) { this.guide[arg] = true; this.render(this.view); }
      else if (!r.ok) this.toast(r.message);
      else if (r.id) this.followPremiere(r.id, arg);
    }
    else if (what === "density") await this.set("opts.sfx_density", +arg);
    else if (what === "sfx-folder") this.render(await this.api.sfx_folder(arg || "", false));
    else if (what === "sfx-folder-rm") this.render(await this.api.sfx_folder(arg, true));
    else if (what === "sfx-src") { const src = { ...(this.view.state.opts.sfx_sources || {}) }; src[arg] = src[arg] === false; await this.set("opts.sfx_sources", src); }
    else if (what === "sfx-key") {
      const input = $("#ep-key"), r = await this.api.set_key("epidemic", input ? input.value : "");
      if (r.ok) this.epEdit = false;
      if (r.view) this.render(r.view);
      this.toast(r.message);
    }
    else if (what === "sfx-key-edit" || what === "sfx-key-cancel") {
      this.epEdit = what === "sfx-key-edit";
      this.renderSfx();
      if (this.epEdit && $("#ep-key")) $("#ep-key").focus();
    }
    else if (what.startsWith("beat-") && window.beatPage) await beatPage.act(what, arg, this._actEl);
    else if (what.startsWith("mo-") && window.momentsPage) await momentsPage.act(what, arg, this._actEl);
    else if (what === "dest" || what === "dest-reset") this.render(await this.api.export_dest(arg, what === "dest-reset"));
    else if (what === "proj-forget") { this.render(await this.api.forget_project(arg)); this.menu(true); }
    else if (what === "proj-reveal") { this.menu(false); this.api.open_path(this.view.project.path); }
  },
  async poll() {
    if (!["sources", "storyboard", "sfx"].includes(this.step) || !this.view) return;
    const r = await this.api.poll();
    if (JSON.stringify(r.sources) !== JSON.stringify(this.view.sources) ||
        JSON.stringify(r.storyboard) !== JSON.stringify(this.view.storyboard) ||
        JSON.stringify(r.sfx) !== JSON.stringify(this.view.sfx)) {
      this.view.sources = r.sources;
      this.view.storyboard = r.storyboard;
      this.view.sfx = r.sfx;
      this.renderSfx();
      this.renderSources();
      this.renderStoryboard();
      this.renderNav();
    }
    if (r.panel && JSON.stringify(r.panel) !== JSON.stringify(this.view.panel)) {      // the panel was opened or closed in Premiere
      this.view.panel = r.panel;
      this.renderSources();
      this.renderStoryboard();
    }
  },

  // --- rendering ------------------------------------------------------------------------------
  render(view) {
    if (!view) return;
    this.view = view;
    const s = view.state;
    if (view.job) { this.job.running = view.job.running; if (view.job.running) this.job.step = view.job.step; }
    this.renderProject();
    this.renderScript();
    this.renderSync();
    this.renderDerush();
    this.renderSources();
    this.renderStoryboard();
    this.renderSfx();
    this.renderChecks();
    this.renderAI();
    this.renderNav();
    if (window.beatPage) beatPage.onView(view);
    if (window.momentsPage) momentsPage.onView(view);
    $$("[data-opt]").forEach((el) => {
      const v = s.opts[el.dataset.opt];
      if (el.type === "checkbox") el.checked = !!v; else if (document.activeElement !== el) el.value = v;
    });
    $("#chain").checked = !!s.chain;
    const gk = (view.keys || {}).gemini;
    if (!$("#save-gemini").disabled) {
      $("#gemini-status").className = gk ? "ok" : "muted";
      $("#gemini-status").innerHTML = gk
        ? esc(t("Clé enregistrée ({key}). Pour la changer, collez-en une autre ; pour l'oublier, enregistrez un champ vide.", { key: gk }))
        : t("Gratuite sur {link}. Elle reste sur cet ordinateur.",
            { link: `<button class="link" data-act="url" data-arg="https://aistudio.google.com/apikey">aistudio.google.com/apikey</button>` });
    }
  },

  renderProject() {
    const pr = this.view.project || { recent: [] }, box = $("#project");
    box.classList.toggle("none", !pr.path);
    box.style.setProperty("--proj", pr.path ? `hsl(${hue(pr.path)} 62% 52%)` : "var(--muted)");
    $("#proj-name").textContent = pr.path ? pr.name : t("Ouvrir un projet…");
    $("#proj-where").textContent = pr.path ? dir(pr.path) : "";
    $("#proj-btn").title = pr.path || t("Le dossier de la vidéo : script, rushs, et tout ce que FauxRaccord écrit");
    if (!$("#proj-menu").hidden) this.menu(true);
  },
  menu(open) {
    const m = $("#proj-menu"), pr = (this.view && this.view.project) || { recent: [] };
    $("#proj-btn").setAttribute("aria-expanded", String(open));
    if (!open) { m.hidden = true; return; }
    const cur = (pr.path || "").toLowerCase();
    m.innerHTML = pr.recent.map((r) => {
      const on = r.path.toLowerCase() === cur;
      return `<div class="proj-row ${on ? "on" : ""}" style="--proj:hsl(${hue(r.path)} 62% 52%)">
        <button class="proj-item" role="menuitem" data-act="${on ? "proj-reveal" : "proj-open"}" data-arg="${esc(r.path)}" title="${esc(r.path)}">
          <i class="pdot"></i><span class="txt"><b data-noi18n>${esc(r.name)}</b><small data-noi18n>${esc(r.where)}</small></span>${on ? `<span class="tick">✓</span>` : ""}</button>
        ${on ? "" : `<button class="icon-btn" title="${esc(t("Retirer de la liste"))}" data-act="proj-forget" data-arg="${esc(r.path)}">✕</button>`}</div>`;
    }).join("") + `<div class="proj-sep"></div>
      <button class="proj-item cmd" role="menuitem" data-act="proj-open"><span class="plus">+</span><span class="txt"><b>${t("Ouvrir un dossier…")}</b></span></button>
      ${pr.path ? `<button class="proj-item cmd" role="menuitem" data-act="proj-reveal"><span class="plus">↗</span><span class="txt"><b>${t("Afficher dans l'explorateur")}</b></span></button>` : ""}`;
    m.hidden = false;
  },

  renderNav() {
    const s = this.view.state, src = this.view.sources || {};
    const info = {
      sync: s.sync_out ? base(s.sync_out) : s.rushes.length ? t("{n} rush(s)", { n: s.rushes.length }) : t("rushs → séquence calée"),
      derush: s.derush_out ? base(s.derush_out) : s.xml ? base(s.xml) : t("séquence → bonnes prises"),
      sources: src.placed ? t("{n} dans Premiere", { n: src.placed }) : src.chosen ? t("{n} choisies", { n: src.chosen }) :
        src.collected ? t("{n} images", { n: src.collected }) : t("pas commencé"),
    };
    const checks = this.view.checks;
    const missing = checks ? checks.filter((c) => c.required && !c.ok).length : 0;
    info.setup = !checks ? t("vérification…") : missing ? t("{n} élément(s) à installer", { n: missing }) : t("tout est prêt");
    const sb = this.view.storyboard || {};
    info.storyboard = sb.beats ? t("{n} plans", { n: sb.beats }) : t("pas commencé");
    const cur = this.currentEngine();
    // the subscription engines are the ones reached through their app (cli); "how" may be translated
    info.ai = !this.view.ai ? t("vérification…") : cur ? (cur.cli ? t("{engine} (abonnement)", { engine: cur.label }) : cur.label) : t("aucune connectée");
    const fx = this.view.sfx || {};
    info.sfx = fx.cues ? t("{n} sons", { n: fx.cues }) : t("après le montage");
    const bt = view_beat(this.view), bs = (window.beatPage && beatPage.v && beatPage.v.shots) ? beatPage.v : null;
    info.beat = bs && bs.music && bs.sources.some((x) => x.on) ? t("{n} plans", { n: bs.shots.length })
      : bt.music ? base(bt.music) : t("musique → coupes");
    info.planche = t("à glisser dans Premiere");
    const mo = this.view.moments || {};
    info.moments = mo.found ? t("{n} moments", { n: mo.found }) : mo.rushes ? t("{n} rushs", { n: mo.rushes }) : t("rushs → moments");
    const done = { sync: !!s.sync_out, derush: !!s.derush_out, sources: !!(src.placed || s.broll_out), storyboard: !!sb.beats, sfx: !!fx.exists, ai: !!cur };
    $$(".step").forEach((b) => {
      const k = b.dataset.step;
      $("small", b).textContent = info[k];
      b.classList.toggle("done", !!done[k]);
      b.classList.toggle("needs", (k === "setup" && missing > 0) || (k === "ai" && !!this.view.ai && !cur));
      b.classList.toggle("busy", this.job.running && this.stepOf(this.job.step) === k);
    });
  },

  renderScript() {
    const s = this.view.state;
    const el = $("#derush-script");
    el.innerHTML = s.script
      ? `<div class="row"><span class="kind script">Script</span>
           <span class="fname"><b title="${esc(s.script)}">${esc(base(s.script))}</b><small>${esc(where(s.script))}</small></span>
           <button class="btn small" data-act="open" data-arg="${esc(s.script)}">${t("Ouvrir")}</button>
           <button class="btn small" data-pick="script">${t("Changer…")}</button>
           <button class="icon-btn" title="${esc(t("Retirer"))}" data-remove="script">✕</button></div>`
      : `<div class="drop missing compact"><div class="drop-icon">${ICON.md}</div>
           <div class="drop-text"><b>${t("Glissez le script (.md)")}</b><span>${t("Le derush garde les prises qui correspondent au script.")}</span></div>
           <div class="drop-btns"><button class="btn" data-pick="script">${t("Choisir…")}</button></div></div>`;
    this.renderInputs();
  },

  // Entrées: the script and the edit, the same two fields on every page that uses them
  inputField(kind, label, opt, detail) {
    const s = this.view.state;
    const path = kind === "script" ? s.script : this.view.montage;
    const optTag = opt ? ` <span class="opt">${t("facultatif")}</span>` : "";
    const head = `<span class="flabel">${t(label)}${optTag}</span>`;
    if (!path) {
      const what = kind === "script" ? t("Glissez le script ici") : t("Glissez le montage ici");
      const hint = kind === "script" ? t(".md, .txt ou .docx") : t("Premiere › Fichier › Exporter › Final Cut Pro XML");
      return `${head}<div class="islot" data-zone="${kind}"><span class="fico">${ICON[kind === "script" ? "md" : "xml"]}</span>
        <span class="fname"><b>${what}</b><small>${hint}</small>${detail ? `<small>${esc(detail)}</small>` : ""}</span>
        <button class="btn small" data-pick="${kind === "script" ? "script" : "montage"}">${t("Choisir…")}</button></div>`;
    }
    const isDerush = kind === "montage" && path === s.derush_out;
    const small = [kind === "montage" ? (isDerush ? t("le derush") : t("votre montage")) : where(path), detail].filter(Boolean).join(" · ");
    return `${head}<div class="islot set" data-zone="${kind}"><span class="fico ${kind === "script" ? "md" : "xml"}">${ICON[kind === "script" ? "md" : "xml"]}</span>
      <span class="fname"><b title="${esc(path)}">${esc(base(path))}</b><small>${esc(small)}</small></span>
      ${kind === "script" ? `<button class="btn small" data-act="open" data-arg="${esc(path)}">${t("Ouvrir")}</button>` : ""}
      <button class="btn small" data-pick="${kind === "script" ? "script" : "montage"}">${t("Changer…")}</button>
      ${kind === "script" || s.place_xml ? `<button class="icon-btn" title="${esc(t("Retirer"))}" data-remove="${kind === "script" ? "script" : "place_xml"}">✕</button>` : ""}</div>`;
  },

  renderInputs() {
    const s = this.view.state, src = this.view.sources || {};
    const derushOnly = this.view.montage && this.view.montage === s.derush_out;
    const fill = (id, html) => { const el = $(id); if (el) el.innerHTML = html; };
    fill("#in-sources-script", this.inputField("script", "Script", false, src.sentences ? t("{n} phrases", { n: src.sentences }) : ""));
    fill("#in-sources-montage", this.inputField("montage", "Montage", false, t("pour placer au timecode")));
    fill("#in-storyboard-script", this.inputField("script", "Script", false, ""));
    fill("#in-storyboard-montage", this.inputField("montage", "Montage", true, t("donne les durées")));
    fill("#in-sfx-montage", this.inputField("montage", "Montage fini", false, derushOnly ? t("c'est le derush : exportez plutôt le montage fini") : ""));
    fill("#in-sfx-script", this.inputField("script", "Script", true, t("pour les ambiances et musiques")));
    $$(".ai-line").forEach((el) => {
      const cur = this.currentEngine();
      el.innerHTML = `${t("IA :")} <b>${esc(cur ? cur.label : t("aucune connectée"))}</b> · <button class="link" data-act="go" data-arg="ai">${t("changer")}</button>`;
    });
    $$("[data-toggle]").forEach((b) => b.classList.toggle("on", !!s.opts[b.dataset.toggle]));
  },

  // the automatic card, the same on the three pages
  autoCard({ text, extra = "", place = null, placeOff = "", exportRun, exportOff = "", exportLabel = "" }) {
    const placeBtn = place
      ? `<button class="btn big" data-act="premiere" data-arg="${place}" ${placeOff || this.job.running ? "disabled" : ""}>${ICON.zap}${t("Placer dans Premiere")}</button>`
      : `<button class="btn big" data-run="${exportRun}" ${exportOff || this.job.running ? "disabled" : ""}>${ICON.zap}${t(exportLabel)}</button>`;
    const why = place ? placeOff : exportOff;
    const help = place ? this.panelHelp(place) : "";
    return `<div class="body"><h3>${ICON.zap}${t("Automatique")}</h3><p class="note">${text}</p>${extra}
      <div class="go col">${placeBtn}
        ${place ? `<button class="link" data-run="${exportRun}" ${exportOff || this.job.running ? "disabled" : ""}>${t("ou exporter le XML")}</button>
          <button class="link" data-act="premiere-remove" data-arg="${place}" ${this.job.running ? "disabled" : ""}>${t("Retirer de Premiere")}</button>` : `<span class="note">${t("Premiere › Fichier › Importer")}</span>`}
        ${this.saveLine(EXPORT_OF_RUN[exportRun])}
        ${why ? `<span class="why">${esc(why)}</span>` : ""}${help}
        ${place ? `<span class="prem ${(this.prem[place] || {}).cls || ""}" id="prem-${place}">${esc((this.prem[place] || {}).txt || "")}</span>` : ""}</div></div>`;
  },

  renderSync() {
    const s = this.view.state;
    const kind = (p) => /\.[^\\/]+$/.test(p) ? (AUDIO.test(p) ? ["audio", t("Son")] : VIDEO.test(p) ? ["video", t("Vidéo")] : ["", t("Fichier")]) : ["folder", t("Dossier")];
    $("#rushes").innerHTML = s.rushes.map((r) => {
      const [k, label] = kind(r);
      return `<li><span class="kind ${k}">${label}</span><span class="fname"><b title="${esc(r)}">${esc(base(r))}</b><small>${esc(r.toLowerCase() === (this.view.project.path || "").toLowerCase() ? t("dossier du projet") : where(r))}</small></span>
              <button class="icon-btn" title="${esc(t("Retirer"))}" data-remove="rushes" data-value="${esc(r)}">✕</button></li>`;
    }).join("") + (s.rushes.length > 1 ? `<li class="clear" style="border:0;background:none;padding:0"><button class="link" data-remove="rushes">${t("Tout retirer")}</button></li>` : "");
    $(".drop[data-zone=sync]").classList.toggle("compact", s.rushes.length > 0);
    $("#go-sync").disabled = !s.rushes.length || this.job.running;
    $("#go-sync").textContent = s.chain && s.script ? t("Synchroniser puis derusher") : t("Synchroniser");
    this.destUnder("#go-sync", "sync");
    $("#chain").nextElementSibling.textContent = s.script
      ? t("Enchaîner avec le derush (script : {name})", { name: base(s.script) })
      : t("Enchaîner avec le derush (il faudra le script, page Derush)");
    $("#res-sync").innerHTML = s.sync_out ? this.resultCard(s.sync_out, t("Fichier › Importer dans Premiere : séquence « 1 sync »."),
      `<button class="btn primary" data-act="use-sync">${t("Derush avec cette séquence →")}</button>`) : "";
  },

  // where an export is saved, with « Changer… » (a Save as, remembered per project) — under every export button
  saveLine(kind) {
    const ex = ((this.view && this.view.exports) || {})[kind];
    if (!ex) return "";
    const folder = ex.path ? base(dir(ex.path)) : "";
    return `<span class="dest" title="${esc(ex.path || "")}"><span class="dico">${ICON.folder}</span><span class="dtxt">${ex.path
        ? `${t("Enregistré dans")} <b data-noi18n>${esc(folder)}</b>${ex.exact ? ` › <span data-noi18n>${esc(base(ex.path))}</span>` : ""}`
        : t("Enregistré dans le dossier du projet")}</span>
      <button class="link" data-act="dest" data-arg="${kind}">${t("Changer…")}</button>${ex.chosen
        ? `<button class="link muted" data-act="dest-reset" data-arg="${kind}" title="${esc(t("Revenir à l'emplacement habituel"))}">${t("par défaut")}</button>` : ""}</span>`;
  },

  destUnder(button, kind) {
    const b = $(button);
    if (!b) return;
    let el = b.parentElement.querySelector(".dest-slot");
    if (!el) { el = document.createElement("div"); el.className = "dest-slot"; b.parentElement.appendChild(el); }
    el.innerHTML = this.saveLine(kind);
  },

  resultCard(path, sum, extra = "") {
    return `<div class="r-head">✓ <span>${esc(base(path))}</span></div>${sum ? `<p class="r-sum">${esc(sum)}</p>` : ""}
      <div class="r-btns"><button class="btn" data-act="reveal" data-arg="${esc(path)}">${t("Afficher dans l'explorateur")}</button>${extra}</div>`;
  },

  renderDerush() {
    const s = this.view.state, scan = this.view.scan || {}, seqs = this.view.sequences || [];
    $("#drop-derush").hidden = !!s.xml;
    $("#xml-card").innerHTML = s.xml ? `<div class="row"><span class="kind video">XML</span>
        <span class="fname"><b title="${esc(s.xml)}">${esc(base(s.xml))}</b><small>${esc(where(s.xml))}</small></span>
        ${seqs.length > 1 ? `<select id="seq-pick" title="${esc(t("Séquence à derusher"))}" data-noi18n>${seqs.map((n) =>
          `<option ${n === (s.sequence || seqs[0]) ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>` : ""}
        <button class="btn small" data-pick="derush">${t("Changer…")}</button>
        <button class="icon-btn" title="${esc(t("Retirer"))}" data-remove="xml">✕</button></div>` : "";
    const pick = $("#seq-pick");
    if (pick) pick.addEventListener("change", () => this.set("sequence", pick.value));

    let html = "";
    if (s.xml && scan.error) html = `<h3>${t("Lecture impossible")}</h3><p>${esc(scan.error)}</p>`;
    else if (s.xml && scan.duration !== undefined) {
      const total = scan.duration || 1;
      if (scan.cutoff > 0) {
        const keep = s.keep ?? scan.cutoff;
        html = `<h3>${t("On dirait que vous avez déjà derushé le début")}</h3>
          <div class="timeline"><div class="done" style="width:${(keep / total) * 100}%"></div><div class="raw" style="flex:1"></div></div>
          <div class="legend"><span><i style="background:var(--ok)"></i>${t("{n} clips coupés, jusqu'à {tc}", { n: scan.done_clips, tc: tc(scan.cutoff) })}</span>
            <span><i style="background:var(--warn)"></i>${t("{d} encore brutes ({names})", { d: dur(scan.raw), names: esc((scan.raw_names || []).join(", ")) })}</span></div>
          <div class="choices">
            <label class="choice ${s.mode === "continue" ? "on" : ""}"><input type="radio" name="mode" value="continue" ${s.mode === "continue" ? "checked" : ""}>
              <span class="ct"><b>${t("Continuer là où vous vous êtes arrêté")}</b>
              <span>${t("Garder tel quel jusqu'à")} <input class="tc" id="keep-tc" value="${tc(keep)}" title="${esc(t("Modifiable (h:mm:ss)"))}"> ${t("puis derusher la suite.")}
              ${s.keep != null && Math.abs(s.keep - scan.cutoff) > 0.5 ? `<button class="link" id="keep-reset">${t("revenir à {tc}", { tc: tc(scan.cutoff) })}</button>` : ""}</span></span></label>
            <label class="choice ${s.mode === "all" ? "on" : ""}"><input type="radio" name="mode" value="all" ${s.mode === "all" ? "checked" : ""}>
              <span class="ct"><b>${t("Tout refaire")}</b><span>${t("Derusher toute la séquence à nouveau (vos coupes ne sont pas gardées).")}</span></span></label>
          </div>`;
      } else if (scan.cutoff === 0) {
        html = `<h3>${t("Séquence brute")}</h3><p>${t("{d}, {n} clip(s) : tout sera derushé.", { d: dur(scan.duration), n: scan.clips })}</p>`;
      } else {
        html = `<h3>${t("Cette séquence a l'air déjà derushée")}</h3><p>${t("{n} clips, aucun long passage brut. Le derush la refera entièrement.", { n: scan.clips })}</p>`;
      }
      const todo = scan.to_transcribe || 0;
      html += todo < 1
        ? `<div class="pill ok">${t("✓ Transcription déjà faite (en cache) : le derush prend une minute ou deux")}</div>`
        : `<div class="pill info">${t("≈ {d} d'audio à transcrire", { d: dur(todo) })}${scan.heard - todo > 60 ? ` · ${t("{d} déjà en cache", { d: dur(scan.heard - todo) })}` : ""}</div>`;
      if ((scan.skipped || []).length) html += `<p style="margin-top:10px">${t("Non copiés (sans fichier média, à réappliquer sur le derush) : {names}", { names: esc(scan.skipped.join(", ")) })}</p>`;
    }
    $("#scan").innerHTML = html;
    $$("input[name=mode]").forEach((r) => r.addEventListener("change", () => this.set("mode", r.value)));
    const ktc = $("#keep-tc");
    if (ktc) {
      ktc.addEventListener("change", () => {
        const v = parseTc(ktc.value);
        if (v == null || v < 0 || v > scan.duration) { this.toast(t("Timecode invalide (h:mm:ss)")); ktc.value = tc(s.keep ?? scan.cutoff); return; }
        this.api.set("mode", "continue");
        this.set("keep", v);
      });
    }
    const kr = $("#keep-reset");
    if (kr) kr.addEventListener("click", (e) => { e.preventDefault(); this.set("keep", null); });

    const model = (this.view.checks || []).find((c) => c.id === `model:${s.opts.model}`);
    if (s.xml && model && !model.ok && (scan.to_transcribe || 0) >= 1) {
      $("#scan").insertAdjacentHTML("beforeend", `<p style="margin-top:10px">${t("Le modèle de transcription n'est pas encore là : il sera téléchargé au lancement, ou dès maintenant depuis {link}.",
        { link: `<button class="link" data-act="go" data-arg="setup">${t("Installation")}</button>` })}</p>`);
    }
    const cont = scan.cutoff > 0 && s.mode === "continue";
    const go = $("#go-derush");
    this.destUnder("#go-derush", "derush");
    go.textContent = cont ? t("Continuer le derush") : t("Derusher");
    go.disabled = !s.xml || !s.script || !!scan.error || this.job.running;
    $("#res-derush").innerHTML = s.derush_out ? this.resultCard(s.derush_out,
      t("Fichier › Importer dans Premiere : séquences « 2 triage » (tout, coloré par prise) et « 3 derush »."),
      `<button class="btn" data-act="report">${t("Rapport par phrase")}</button>
       <button class="btn" data-act="go" data-arg="sources">${t("Illustrations →")}</button>`) : "";
  },

  renderSources() {
    const s = this.view.state, src = this.view.sources || {}, o = s.opts;
    const collected = src.collected > 0;
    const go = $("#go-collect");
    go.textContent = collected ? t("Relancer la collecte") : t("Collecter");
    go.classList.toggle("primary", !collected);
    go.disabled = !s.script || this.job.running;
    $("#collect-note").innerHTML = !s.script ? `<span class="why">${t("Ajoutez d'abord le script.")}</span>`
      : collected ? esc(t("{n} images trouvées. Relancer garde vos choix.", { n: src.collected }))
      : esc(t("Les liens du script, puis les sources cochées. Quelques minutes."));

    const states = src.states || [];
    const n = states.length, placed = states.filter((x) => x === "p").length, picked = states.filter((x) => x === "c").length;
    const strip = (src.thumbs || []).map((th) => `<span class="${th.placed ? "p" : ""}"><img src="${esc(th.src)}" alt="" loading="lazy" referrerpolicy="no-referrer"></span>`).join("");
    $("#res-src-board").innerHTML = collected
      ? `${strip ? `<div class="strip">${strip}</div>` : ""}
         <div class="body"><h3>${t("Planche")}</h3>
           ${n ? `<div class="cover" title="${esc(t("Les {n} phrases du script", { n }))}">${states.map((x) => `<i class="${x}"></i>`).join("")}</div>
           <div class="legend2"><span><i class="p"></i>${t("dans Premiere")} <b>${placed}</b></span><span><i class="c"></i>${t("choisies")} <b>${picked}</b></span>
             <span><i></i>${t("sans image")} <b>${n - placed - picked}</b></span><span>${t("sur {n} phrases", { n })}</span></div>` : ""}
           <div class="go"><button class="btn primary big" data-act="open-sheet">${t("Ouvrir la planche")}</button>
             ${src.out && src.exists ? `<button class="link" data-act="open" data-arg="${esc(src.out)}">${t("Dossier des images")}</button>` : ""}</div></div>`
      : `<div class="empty-prev">${t("Aucune image pour l'instant.")}</div>
         <div class="body"><h3>${t("Planche")}</h3><p class="note">${t("Les images trouvées, rangées par phrase : à regarder et à glisser dans la timeline de Premiere.")}</p>
           <div class="go"><button class="btn big" disabled>${t("Ouvrir la planche")}</button></div></div>`;

    const chosen = src.chosen || 0, auto = o.auto_fill !== false ? (src.auto || 0) : 0;
    const text = !collected ? t("Une image sur chaque phrase, à son timecode.")
      : auto ? t("Vos {n} choix, puis la meilleure image selon l'IA pour {m} autres phrases, chacune à son timecode.", { n: chosen, m: auto })
      : t("Les {n} images choisies, chacune au timecode de sa phrase.", { n: chosen });
    $("#res-src-auto").innerHTML = this.autoCard({
      text: esc(text),
      extra: `<button class="sw ${o.auto_fill !== false ? "on" : ""}" data-toggle="auto_fill"><i></i>${t("Compléter avec le choix de l'IA")}</button>`,
      place: "sources", placeOff: !collected ? t("Collectez d'abord.") : !chosen && !auto ? t("Choisissez des images sur la planche.") : "",
      exportRun: "place", exportOff: !collected ? t("Collectez d'abord.") : !this.view.montage ? t("Ajoutez le montage pour exporter le XML.") : "",
    });
    $("#res-place").innerHTML = s.broll_out ? this.resultCard(s.broll_out, t("Premiere › Fichier › Importer.")) : "";
  },

  currentEngine() {
    const ai = (this.view && this.view.ai) || [], pref = this.view ? this.view.state.opts.llm : "auto";
    if (pref === "off") return null;
    if (pref !== "auto") return ai.find((e) => e.id === pref && e.connected) || null;
    for (const id of AUTO_ORDER) { const e = ai.find((x) => x.id === id && x.connected); if (e) return e; }
    return null;
  },

  renderAI() {
    if (!this.view) return;
    const ai = this.view.ai, cur = this.currentEngine();
    if (this.view.state) this.renderInputs();
    if (!ai) return;
    const HELP = { codex: "https://developers.openai.com/codex/cli", "claude-code": "https://code.claude.com/docs/en/setup",
                   antigravity: "https://antigravity.google", ollama: "https://ollama.com/download",
                   claude: "https://console.anthropic.com/settings/keys", gemini: "https://aistudio.google.com/apikey" };
    $("#ai-list").innerHTML = ai.map((e) => {
      const btns = [];
      if (e.cli && !e.installed) btns.push(`<button class="btn" data-act="ai-install" data-arg="${e.id}" ${this.job.running ? "disabled" : ""}>${t("Installer")}</button>`);
      if (e.cli && e.installed && !e.connected) btns.push(`<button class="btn primary" data-act="ai-connect" data-arg="${e.id}">${t("Connecter")}</button>`);
      if (e.connected) btns.push(`<button class="btn" data-act="ai-test" data-arg="${e.id}">${t("Tester")}</button>`);
      if (e.connected && this.view.state.opts.llm !== e.id) btns.push(`<button class="btn" data-act="ai-use" data-arg="${e.id}">${t("Utiliser")}</button>`);
      if (!e.cli && !e.connected && e.id !== "gemini") btns.push(`<button class="btn" data-act="url" data-arg="${HELP[e.id]}">${t("Aide…")}</button>`);
      const note = e.vision ? "" : " · " + t("ne regarde pas les images");
      return `<li class="item ${cur && cur.id === e.id ? "current" : ""}"><span class="dot ${e.connected ? "ok" : "opt"}">${e.connected ? "✓" : "–"}</span>
        <span class="ctext"><b>${esc(e.label)} <span class="muted">— ${esc(e.how)}${note}</span></b><span>${esc(e.detail)}</span></span>
        <span class="cbtns">${btns.join("")}</span></li>`;
    }).join("");
  },

  renderStoryboard() {
    if (!this.view) return;
    const s = this.view.state, sb = this.view.storyboard || {};
    const refs = this.view.refs || [];
    $("#sb-refs").innerHTML = s.sb_refs.map((r, i) => `<span class="ref" title="${esc(r)}"><img src="${esc(refs[i] || "")}" alt="">
        <button class="icon-btn" title="${esc(t("Retirer"))}" data-remove="sb_refs" data-value="${esc(r)}">✕</button></span>`).join("") +
      `<button class="btn small" data-pick="storyboard">${t("Ajouter des images…")}</button>${s.sb_refs.length ? "" : ` <span class="opt">${t("facultatif")}</span>`}`;
    const go = $("#go-sb");
    go.textContent = sb.beats ? t("Relancer") : t("Créer les plans");
    go.classList.toggle("primary", !sb.beats);
    go.disabled = !s.script || this.job.running;
    const changed = sb.beats && sb.brief !== (s.opts.sb_style || "").trim();
    $("#sb-note").innerHTML = !s.script ? `<span class="why">${t("Ajoutez d'abord le script.")}</span>`
      : changed ? `<span class="warnline">${esc(t("Le style a changé : relancez pour le prendre en compte."))}</span>`
      : sb.beats ? esc(t("Relancer garde les plans marqués ✓ Gardé."))
      : esc(t("Une à deux minutes."));

    const thumbs = (sb.thumbs || []).map((u) => `<span><img src="${esc(u)}" alt="" loading="lazy"></span>`).join("");
    $("#res-sb-board").innerHTML = sb.beats
      ? `${thumbs ? `<div class="strip">${thumbs}</div>` : ""}
         <div class="body"><h3>${t("Planche")}</h3>
           <p class="note">${esc([t("{n} plans", { n: sb.beats }), t("{n} cartes", { n: sb.cards }), sb.locked ? t("{n} gardés", { n: sb.locked }) : "",
              sb.timing === "montage" ? t("durées du montage") : t("durées estimées"), sb.engine].filter(Boolean).join(" · "))}</p>
           <div class="go"><button class="btn primary big" data-act="open-sb">${t("Ouvrir la planche")}</button></div></div>`
      : `<div class="empty-prev">${t("Aucun plan pour l'instant.")}</div>
         <div class="body"><h3>${t("Planche")}</h3><p class="note">${t("Chaque plan : ce qu'on voit, le mouvement, les prompts image et vidéo, la scène Blender. À relire, refaire, glisser.")}</p>
           <div class="go"><button class="btn big" disabled>${t("Ouvrir la planche")}</button></div></div>`;
    $("#res-sb-auto").innerHTML = this.autoCard({
      text: esc(t("Une carte par plan, à sa place dans la timeline, au-dessus de votre montage.")),
      place: "storyboard", placeOff: sb.beats ? "" : t("Créez d'abord les plans."),
      exportRun: "sb_place", exportOff: sb.beats ? "" : t("Créez d'abord les plans."),
    });
  },

  renderSfx() {
    if (!this.view) return;
    const s = this.view.state, o = s.opts, fx = this.view.sfx || {}, keys = this.view.keys || {};
    const on = (k) => (o.sfx_sources || {})[k] !== false;
    const row = (k, title, body) => `<div class="srcrow"><button class="sw ${on(k) ? "on" : ""}" data-act="sfx-src" data-arg="${k}"
        title="${esc(on(k) ? t("Utilisée — cliquer pour l'ignorer") : t("Ignorée — cliquer pour l'utiliser"))}"><i></i>${title}</button><div class="srcbody">${body}</div></div>`;
    const folders = o.sfx_folders || [];
    $("#sfx-srcs").innerHTML =
      row("folder", t("Vos dossiers"), `<div class="fchips">${folders.map((f) => `<span class="fchip" title="${esc(f)}"><span>${esc(f)}</span>
          <button class="icon-btn" title="${esc(t("Retirer"))}" data-act="sfx-folder-rm" data-arg="${esc(f)}">✕</button></span>`).join("")}
          <button class="btn small" data-act="sfx-folder">${t("Ajouter un dossier…")}</button></div>
          ${folders.length ? "" : `<span class="note">${t("Vos téléchargements Epidemic, Artlist, Envato, vos packs : glissez un dossier ici.")}</span>`}`) +
      row("epidemic", "Epidemic Sound", keys.epidemic && !this.epEdit
        ? `<div class="keyrow inline"><span class="note">${esc(t("Clé enregistrée ({key})", { key: keys.epidemic }))}${keys.epidemic_src === "env" ? " · " + esc(t("lue dans .env")) : ""}</span>
            <button class="btn small" data-act="sfx-key-edit">${t("Changer la clé")}</button></div>`
        : `<div class="keyrow inline"><input type="password" id="ep-key" placeholder="${esc(keys.epidemic ? t("Nouvelle clé (vide : oublier la clé enregistrée)") : t("Collez la clé"))}" autocomplete="off" spellcheck="false">
            <button class="btn small" data-act="sfx-key">${t("Enregistrer")}</button>${keys.epidemic ? `<button class="btn small" data-act="sfx-key-cancel">${t("Annuler")}</button>` : ""}</div>
            <span class="note">${t("Votre abonnement : epidemicsound.com › Compte › API keys.")}</span>`) +
      row("earshot", t("Banque intégrée"), `<span class="note">${t("Libre de droits. Une prise neuve à chaque fois.")}</span>`);

    const sg = $("#go-suggest");
    sg.disabled = !s.script || !keys.epidemic || this.job.running;
    $("#suggest-note").innerHTML = !s.script ? `<span class="why">${t("Ajoutez le script pour des propositions.")}</span>`
      : !keys.epidemic ? `<span class="why">${t("Les propositions cherchent sur Epidemic : enregistrez la clé ci-dessus.")}</span>`
      : esc(t("Proposées sur la planche, jamais posées sans vous."));

    $("#res-sfx-board").innerHTML = `<div class="strip tiles">
        <span style="--c:var(--k-whoosh)">Whoosh</span><span style="--c:var(--k-click)">${t("Clic")}</span><span style="--c:var(--k-pop)">Pop</span>
        <span style="--c:var(--k-typing)">${t("Clavier")}</span><span style="--c:var(--k-amb)">${t("Ambiances")}</span><span style="--c:var(--k-music)">${t("Musiques")}</span></div>
      <div class="body"><h3>${t("Planche sonore")}</h3><p class="note">${t("Vos sons, Epidemic et la banque : écoutez, glissez dans la timeline.")}</p>
        <div class="go"><button class="btn primary big" data-act="open-board">${t("Ouvrir la planche")}</button></div></div>`;

    const dens = `<div class="brow"><span class="k">${t("Densité")}</span><span class="seg">${[[1, "Léger"], [2, "Normal"], [3, "Dense"]].map(([d, l]) =>
      `<button class="${(o.sfx_density || 2) === d ? "on" : ""}" data-act="density" data-arg="${d}">${t(l)}</button>`).join("")}</span></div>`;
    const bins = fx.exists && fx.bins ? `<div class="cover k" title="${esc(t("Les sons le long du montage"))}">${fx.bins.map((k) => `<i class="${k ? "k-" + k : ""}"></i>`).join("")}</div>
      <div class="legend2">${SFX_KINDS.filter(([k]) => fx.kinds[k]).map(([k, n]) => `<span><i class="k-${k}"></i>${t(n)} <b>${fx.kinds[k]}</b></span>`).join("")}</div>` : "";
    const sum = fx.exists ? `<p class="note">${esc(t("{n} sons", { n: fx.cues }))}${fx.edited ? " · " + esc(t("{n} retouchés", { n: fx.edited })) : ""} ·
        <button class="link" data-act="open-board" data-arg="montage">${t("écouter et ajuster")}</button></p>` : "";
    $("#res-sfx-auto").innerHTML = this.autoCard({
      text: esc(t("Des bruitages sur tout ce qui bouge dans le montage.")),
      extra: dens + bins + sum + `<button class="btn small" data-run="sfx" ${!fx.edit || this.job.running ? "disabled" : ""}>${fx.exists ? t("Analyser à nouveau") : t("Analyser le montage")}</button>`,
      exportRun: "sfx_place", exportLabel: "Exporter pour Premiere (.xml)",
      exportOff: !fx.edit ? t("Ajoutez le montage.") : !fx.exists ? t("Analysez d'abord le montage.") : "",
    });
  },

  // The Premiere panel, under « Placer dans Premiere »: open (ready), to open, or to install (a short guide)
  panelHelp(kind) {
    const p = this.view && this.view.panel;
    if (!p) return "";
    if (p.live && p.stale) return `<span class="pstat"><i></i>${t("Premiere utilise encore l'ancien panneau FauxRaccord : redémarrez Premiere.")}</span>`;
    if (p.live) return `<span class="pstat ok"><i></i>${t("Panneau FauxRaccord ouvert dans Premiere")}</span>`;
    if (p.installed && p.current) return `<span class="pstat"><i></i>${t("Utilise le panneau FauxRaccord : dans Premiere, Fenêtre › Extensions UXP › FauxRaccord.")}</span>`;
    if (!p.premiere) return `<span class="pstat">${t("Premiere Pro n'est pas sur cet ordinateur : exportez le XML.")}</span>`;
    const update = p.installed;
    if (!this.guide[kind])
      return `<span class="pstat">${update ? t("Le panneau FauxRaccord de Premiere a une nouvelle version.") : t("Passe par le panneau FauxRaccord de Premiere, à installer une fois.")}
        <button class="link" data-act="guide" data-arg="${kind}">${t("Comment ?")}</button></span>`;
    const busy = this.job.running && this.job.step === "panel";
    return `<div class="pguide">
      <b>${update ? t("Mettre à jour le panneau FauxRaccord") : t("Une fois : le panneau FauxRaccord dans Premiere")}</b>
      <ol><li><button class="btn small primary" data-act="panel-install" ${this.job.running ? "disabled" : ""}>${busy ? t("Installation…") : update ? t("Mettre à jour le panneau") : t("Installer le panneau")}</button></li>
        <li>${update ? t("Redémarrez Premiere, puis Fenêtre › Extensions UXP › FauxRaccord.") : t("Dans Premiere : Fenêtre › Extensions UXP › FauxRaccord. Gardez-le ouvert : FauxRaccord place par lui.")}</li></ol>
      <span class="note">${t("Sans le panneau : « ou exporter le XML », puis Premiere › Fichier › Importer.")}</span>
      <button class="link" data-act="guide" data-arg="${kind}">${t("Fermer")}</button></div>`;
  },

  // « Placer dans Premiere »: follow the request until the panel has done it (or nobody answered)
  followPremiere(id, kind) {
    const line = () => $(PREMIERE_LINE[kind] || "#none");
    const say = (txt, cls = "") => {           // kept: the card is drawn again at each refresh
      this.prem[kind] = { txt, cls };
      const el = line(); if (el) { el.textContent = txt; el.className = `prem ${cls}`; }
    };
    clearInterval(this._prem);
    const t0 = Date.now();
    say(t("Envoyé au panneau FauxRaccord de Premiere…"));
    this._prem = setInterval(async () => {
      const r = await this.api.premiere_state(id);
      if (r.state === "waiting" && Date.now() - t0 > 5000)
        say(t("En attente du panneau : dans Premiere, Fenêtre › Extensions UXP › FauxRaccord. Il place dès qu'il est ouvert."), "wait");
      else if (r.state === "placing") say(t("Le panneau place…"));
      else if (r.state === "done") { clearInterval(this._prem); say("✓ " + (r.message || t("Placé dans Premiere.")), "ok"); this.toast(r.message || t("Placé dans Premiere.")); }
      else if (r.state === "error") { clearInterval(this._prem); say(r.message, "bad"); this.toast(r.message); }
      else if (r.state === "expired" || r.state === "gone") {
        clearInterval(this._prem);
        if (r.state === "expired") say(t("Le panneau n'a pas répondu. Ouvrez-le dans Premiere, ou exportez le XML."), "bad");
      }
    }, 1000);
  },

  renderChecks() {
    const checks = this.view && this.view.checks;
    if (!checks) return;
    $("#checks").innerHTML = checks.map((c) => {
      const cls = c.ok ? "ok" : c.required ? "miss" : "opt";
      const btn = c.action ? `<button class="btn ${c.required ? "primary" : ""}" data-act="install" data-arg="${esc(c.id)}" ${this.job.running ? "disabled" : ""}>${esc(c.action)}</button>`
        : c.link ? `<button class="btn" data-act="url" data-arg="${esc(c.link)}">${t("Télécharger…")}</button>` : "";
      return `<li class="item"><span class="dot ${cls}">${c.ok ? "✓" : c.required ? "!" : "–"}</span>
        <span class="ctext"><b>${esc(c.name)}</b><span>${esc(c.detail)}</span>${c.note && c.action ? `<em>${esc(c.note)}</em>` : ""}</span>${btn}</li>`;
    }).join("");
  },

  // --- jobs -----------------------------------------------------------------------------------
  placeJob() {
    const box = $("#job");
    const mine = this.job.step && this.stepOf(this.job.step) === this.step;
    box.hidden = !mine;
    if (mine) $(`#page-${this.step}`).after(box);
  },
  onJob(ev) {
    const box = $("#job");
    if (ev.running) {
      this.job = { step: ev.step, running: true };
      this.logLines = [];
      $("#log").innerHTML = "";
      box.className = "job running";
      $("#job-title").textContent = JOB_TITLE[ev.step] ? t(JOB_TITLE[ev.step]) : ev.step;
      $("#job-label").textContent = t("démarrage…");
      $("#job-msg").textContent = "";
      $("#job-pct").textContent = "";
      $("#job-eta").textContent = "";
      $(".bar").classList.add("indeterminate");
      this.show(this.stepOf(ev.step));
    } else {
      this.job.running = false;
      box.className = `job ${ev.ok ? "ok" : "err"}`;
      $(".bar").classList.remove("indeterminate");
      $("#job-msg").textContent = ev.message || "";
      $("#job-label").textContent = ev.ok ? t("terminé") : "";
      $("#job-eta").textContent = "";
      if (!ev.ok && ev.message !== t("Arrêté.") && ev.message !== "Arrêté.") $("#log-wrap").open = true;
      this.notify(ev);
      if (window.momentsPage) momentsPage.onJobEnd(ev);
    }
    this.placeJob();
    this.plancheJob(ev);
    if (this.view) this.render(this.view);
  },

  // --- the planche: this window's other mode (Illustrations · Storyboard · Sons · Moments) ----
  // Each tab is a planche page with its own little server, in an iframe kept alive while you switch.
  // Its calls to Python come here as messages (the iframe has no window.pywebview of its own).
  pl: { on: false, tab: "sources", urls: {}, frames: {}, follow: true, sentence: null },

  async plancheInit() {
    try { this.pl.follow = localStorage.getItem("fauxraccord.follow") !== "0"; } catch (e) { /* no storage */ }
    $("#pl-menu").addEventListener("click", () => this.plancheMode(false));
    $$(".pl-tab").forEach((b) => b.addEventListener("click", () => this.plancheTab(b.dataset.tab)));
    $("#pl-follow").addEventListener("click", () => {
      this.pl.follow = !this.pl.follow;
      try { localStorage.setItem("fauxraccord.follow", this.pl.follow ? "1" : "0"); } catch (e) { /* no storage */ }
      this.plancheHead();
      if (this.pl.follow) this.plancheFollow();
    });
    $("#pl-empty").addEventListener("click", (e) => {
      const go = e.target.closest("[data-plgo]");
      if (go) { this.plancheMode(false); this.show(go.dataset.plgo); }
    });
    $("#pl-job").addEventListener("click", () => { this.plancheMode(false); this.show(this.stepOf(this.job.step)); });
    window.addEventListener("message", (e) => this.plancheMessage(e));
    try {          // the page was reloaded: the planches already open come back as they were
      for (const [tab, url] of Object.entries((await this.api.planche_state()) || {})) this.plancheFrame(tab, url);
    } catch (e) { /* none */ }
  },
  plancheShow(tab, url, sub) {           // Python opened (or brought forward) a planche
    if (url) this.plancheFrame(tab, url);
    this.pl.tab = tab;
    this.plancheMode(true);
    if (sub) this.plancheSend(tab, sub === "reload" ? { fr: "reload" } : { fr: "tab", tab: sub });
  },
  plancheMode(on) {
    if (on && !this.pl.on) this.pl.from = this.step;      // « Menu » comes back to that page
    if (!on && this.pl.on && this.pl.from && this.step !== this.pl.from) this.show(this.pl.from, false);
    this.pl.on = on;
    $(".app").classList.toggle("planche-on", on);
    $("#planche").hidden = !on;
    if (on) this.plancheRender();
    else $(".app").classList.remove("pl-moments");
  },
  async plancheTab(tab) {                // a tab clicked
    this.pl.tab = tab;
    this.plancheRender();
    if (tab === "moments" || this.pl.urls[tab]) return;
    const r = await this.api.planche_open(tab);     // opens it when there is something to show
    if (r && !r.ok) this.plancheRender(r.message);
  },
  plancheFrame(tab, url) {
    this.pl.urls[tab] = url;
    let f = this.pl.frames[tab];
    if (!f) {
      f = document.createElement("iframe");
      f.title = tab;
      f.addEventListener("load", () => { if (this.pl.follow && this.pl.tab === tab) this.plancheFollow(); });
      $("#pl-body").appendChild(f);
      this.pl.frames[tab] = f;
    }
    if (f.dataset.src !== url) { f.dataset.src = url; f.src = url; }
  },
  plancheRender(msg) {
    const tab = this.pl.tab;
    $$(".pl-tab").forEach((b) => { const on = b.dataset.tab === tab; b.classList.toggle("on", on); b.setAttribute("aria-selected", String(on)); });
    for (const [k, f] of Object.entries(this.pl.frames)) f.hidden = k !== tab;
    $(".app").classList.toggle("pl-moments", tab === "moments");
    if (tab === "moments" && this.step !== "moments") this.show("moments", false);
    const empty = tab !== "moments" && !this.pl.urls[tab];
    $("#pl-empty").hidden = !empty;
    if (empty) {
      const [why, step] = { sources: ["Pas encore d'images : collectez-les dans Illustrations.", "sources"],
                            storyboard: ["Pas encore de plans : créez-les dans Storyboard.", "storyboard"],
                            sons: ["La planche sonore s'ouvre…", "sfx"] }[tab];
      $("#pl-empty").innerHTML = `<p>${esc(msg || t(why))}</p><button class="btn" data-plgo="${step}">${t("Aller à l'étape")}</button>`;
    }
    this.plancheHead();
    if (this.pl.follow) this.plancheFollow();
  },
  plancheHead() {
    $("#pl-proj").textContent = (this.view && this.view.project && this.view.project.name) || "";
    const f = $("#pl-follow"), s = this.pl.sentence;
    f.hidden = !["sources", "storyboard"].includes(this.pl.tab);    // the planches that are by sentence
    f.classList.toggle("on", this.pl.follow);
    f.setAttribute("aria-pressed", String(this.pl.follow));
    f.textContent = !this.pl.follow ? t("Ne suit pas Premiere")
      : s != null ? t("Suit Premiere · S{n}", { n: String(s + 1).padStart(3, "0") }) : t("Suit Premiere");
  },
  plancheJob(ev) {
    const pill = $("#pl-job");
    if (ev.running) { pill.hidden = false; pill.className = "pl-job run"; pill.textContent = (JOB_TITLE[ev.step] ? t(JOB_TITLE[ev.step]) : ev.step) + "…"; }
    else { pill.className = `pl-job ${ev.ok ? "ok" : "err"}`; pill.textContent = (ev.ok ? "✓ " : "") + (ev.message || "").slice(0, 80); }
  },
  plancheDrop(tabs) {                    // another project: its planches go
    for (const k of tabs) {
      delete this.pl.urls[k];
      if (this.pl.frames[k]) { this.pl.frames[k].remove(); delete this.pl.frames[k]; }
    }
    if (this.pl.on) this.plancheRender();
  },
  plancheSend(tab, msg) {
    const f = this.pl.frames[tab];
    if (f && f.contentWindow) f.contentWindow.postMessage(msg, "*");
  },
  onPlayhead(ev) {                       // the panel says Premiere's playhead is on another sentence
    this.pl.sentence = ev.sentence;
    this.plancheHead();
    if (this.pl.follow) this.plancheFollow();
  },
  plancheFollow() {
    if (this.pl.on && this.pl.sentence != null) this.plancheSend(this.pl.tab, { fr: "follow", sentence: this.pl.sentence });
  },
  async plancheMessage(e) {
    const d = e.data || {};
    const tab = Object.keys(this.pl.frames).find((k) => this.pl.frames[k].contentWindow === e.source);
    if (!tab || !d.fr) return;
    if (d.fr === "call") {
      let reply;
      try { reply = { fr: "reply", id: d.id, ok: true, r: await this.api.planche_call(tab, d.method, d.args || []) }; }
      catch (err) { reply = { fr: "reply", id: d.id, ok: false, error: String((err && err.message) || err) }; }
      e.source.postMessage(reply, "*");
    } else if (d.fr === "seek") {        // a sentence clicked: Premiere's playhead goes there
      const r = await this.api.planche_seek(d.sentence);
      if (!r.ok) this.toast(r.message);
    }
  },
  onLog(ev) {
    const log = $("#log");
    const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 30;
    if (ev.lines.length) {
      this.logLines.push(...ev.lines);
      if (this.logLines.length > 3000) this.logLines = this.logLines.slice(-2000);
    }
    log.innerHTML = esc(this.logLines.join("\n")) + (ev.current ? `\n<span class="cur">${esc(ev.current)}</span>` : "");
    if (atBottom) log.scrollTop = log.scrollHeight;
    let label = ev.label || "";
    for (const [re, fr] of LABELS_FR) if (re.test(label)) { label = t(fr); break; }
    if (ev.steps) $("#job-label").textContent = t("étape {n}/{total} · {label}", { n: ev.stepNo, total: ev.steps, label });
    const bar = $(".bar");
    if (ev.progress != null) {
      bar.classList.remove("indeterminate");
      $("#bar-fill").style.width = `${Math.round(ev.progress * 1000) / 10}%`;
      $("#job-pct").textContent = t("{p} %", { p: Math.round(ev.progress * 100) });
    }
    $("#job-eta").textContent = [ev.eta ? t("≈ {d} restantes pour cette étape", { d: dur(ev.eta) }) : "",
                                 t("{d} écoulées", { d: dur(ev.elapsed) })].filter(Boolean).join(" · ");
  },
  notify(ev) {
    if (document.hasFocus()) return;
    try { new Notification("FauxRaccord", { body: ev.message }); } catch (e) { /* not available */ }
  },
  toast(msg) {
    const list = Array.isArray(msg) ? msg : [msg];
    for (const m of list.filter(Boolean)) {
      const t = document.createElement("div");
      t.className = "toast";
      t.textContent = m;
      $("#toasts").appendChild(t);
      setTimeout(() => t.remove(), 3500);
    }
  },
};
window.app = app;
// pywebview announces its API with an event that may fire before or after this script runs
let started = false;
const boot = () => { if (!started && window.pywebview && window.pywebview.api && window.pywebview.api.init) { started = true; app.start(); } };
window.addEventListener("pywebviewready", boot);
boot();
if (!started) { const t = setInterval(() => { boot(); if (started) clearInterval(t); }, 50); }
