"use strict";
// Autocut window. Python (gui.py, class Api) owns the state; this page renders it and forwards clicks.

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
const STEP_OF_JOB = { sync: "sync", derush: "derush", collect: "sources", place: "sources", storyboard: "storyboard", sfx: "sfx", setup: "setup" };
const JOB_TITLE = { sync: "Synchro", derush: "Derush", collect: "Collecte des illustrations", place: "Placement sur le montage", storyboard: "Storyboard", sfx: "Sons", setup: "Installation" };
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
    setInterval(() => this.poll(), 3000);
  },

  // --- events from Python ---------------------------------------------------------------------
  event(ev) {
    if (ev.type === "view") this.render(ev.view);
    else if (ev.type === "added") { this.render(ev.view); this.toast(ev.notes); this.show(this.view.state.step); }
    else if (ev.type === "log") this.onLog(ev);
    else if (ev.type === "job") this.onJob(ev);
    else if (ev.type === "ai") { if (this.view) { this.view.ai = ev.ai; this.renderAI(); this.renderNav(); } }
    else if (ev.type === "checks") { if (this.view) this.view.checks = ev.checks; this.renderChecks(); this.renderNav(); if (this.view) this.renderDerush(); }
  },
  dropZone() {
    // scripts are recognised by their extension, so the script card stands for its page
    const page = { sync: "sync", derush: "derush", sources: "sources", storyboard: "storyboard", sfx: "sfx" }[this.step] || "sync";
    return this.hoverZone && this.hoverZone !== "script" ? this.hoverZone : page;
  },

  // --- navigation -----------------------------------------------------------------------------
  show(step, save = true) {
    this.step = step;
    $$(".step").forEach((b) => b.classList.toggle("active", b.dataset.step === step));
    $$(".page").forEach((p) => p.classList.toggle("active", p.id === `page-${step}`));
    this.placeJob();
    if (save && this.view && this.view.state.step !== step) this.api.set("step", step);
    $("#main").scrollTop = 0;
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
      else if (t.dataset.act) this.act(t.dataset.act, t.dataset.arg);
    });
    $("#go-sync").addEventListener("click", () => this.run("sync"));
    $("#go-derush").addEventListener("click", () => this.run("derush"));
    $("#stop").addEventListener("click", () => this.api.stop());
    $("#recheck").addEventListener("click", () => { $("#checks").innerHTML = `<li class="muted">${esc(t("Vérification…"))}</li>`; this.api.check(); });
    $("#open-sheet").addEventListener("click", async () => {
      const r = await this.api.open_sheet();
      this.toast(r.ok ? t("Planche ouverte : cochez et téléchargez, ou glissez les vignettes dans Premiere.") : r.message);
    });
    $("#chain").addEventListener("change", (e) => this.set("chain", e.target.checked));
    $("#open-sb").addEventListener("click", async () => {
      const r = await this.api.open_storyboard();
      this.toast(r.ok ? t("Storyboard ouvert dans le navigateur.") : r.message);
    });
    $("#open-sfx").addEventListener("click", async () => { const r = await this.api.open_sfx(); if (!r.ok) this.toast(r.message); });
    $("#open-board").addEventListener("click", async () => { const r = await this.api.open_board(); if (!r.ok) this.toast(r.message); });
    $$("#sfx-density button").forEach((b) => b.addEventListener("click", () => this.set("opts.sfx_density", +b.dataset.d)));
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
    $$("[data-opt]").forEach((el) => el.addEventListener("change", () => {
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
    $("#proj-btn").title = pr.path || t("Le dossier de la vidéo : script, rushs, et tout ce qu'Autocut écrit");
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
      sources: src.exported ? t("{n} fichiers téléchargés", { n: src.exported }) : src.chosen ? t("{n} choisis", { n: src.chosen }) :
        src.collected ? t("{n} candidats", { n: src.collected }) : t("liens du script → images"),
    };
    const checks = this.view.checks;
    const missing = checks ? checks.filter((c) => c.required && !c.ok).length : 0;
    info.setup = !checks ? t("vérification…") : missing ? t("{n} élément(s) à installer", { n: missing }) : t("tout est prêt");
    const sb = this.view.storyboard || {};
    info.storyboard = sb.beats ? t("{n} plans", { n: sb.beats }) : t("un style → les plans à créer");
    const cur = this.currentEngine();
    // the subscription engines are the ones reached through their app (cli); "how" may be translated
    info.ai = !this.view.ai ? t("vérification…") : cur ? (cur.cli ? t("{engine} (abonnement)", { engine: cur.label }) : cur.label) : t("aucune connectée");
    const fx = this.view.sfx || {};
    info.sfx = fx.cues ? t("{n} sons", { n: fx.cues }) : t("le montage → les sons");
    const done = { sync: !!s.sync_out, derush: !!s.derush_out, sources: !!src.exported, storyboard: !!sb.beats, sfx: !!fx.xml, ai: !!cur };
    $$(".step").forEach((b) => {
      const k = b.dataset.step;
      $("small", b).textContent = info[k];
      b.classList.toggle("done", !!done[k]);
      b.classList.toggle("needs", (k === "setup" && missing > 0) || (k === "ai" && !!this.view.ai && !cur));
      b.classList.toggle("busy", this.job.running && STEP_OF_JOB[this.job.step] === k);
    });
  },

  renderScript() {
    const s = this.view.state;
    const slot = (id, big, hint) => {
      const el = $(id);
      el.classList.toggle("big", big);
      el.innerHTML = s.script
        ? `<div class="row"><span class="kind script">Script</span>
             <span class="fname"><b title="${esc(s.script)}">${esc(base(s.script))}</b><small>${esc(where(s.script))}</small></span>
             <button class="btn small" data-act="open" data-arg="${esc(s.script)}">${t("Ouvrir")}</button>
             <button class="btn small" data-pick="script">${t("Changer…")}</button>
             <button class="icon-btn" title="${esc(t("Retirer"))}" data-remove="script">✕</button></div>`
        : `<div class="drop missing ${big ? "" : "compact"}"><div class="drop-icon"><svg viewBox="0 0 24 24"><path d="M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6"/></svg></div>
             <div class="drop-text"><b>${t("Glissez le script (.md)")}</b><span>${hint}</span></div>
             <div class="drop-btns"><button class="btn" data-pick="script">${t("Choisir…")}</button></div></div>`;
    };
    slot("#derush-script", false, t("Le derush garde les prises qui correspondent au script."));
    slot("#src-script", true, t("C'est lui qui compte ici : ses liens donnent les images, ses phrases les timecodes."));
    slot("#sb-script", false, t("Le storyboard découpe le script en plans."));
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
    $("#chain").nextElementSibling.textContent = s.script
      ? t("Enchaîner avec le derush (script : {name})", { name: base(s.script) })
      : t("Enchaîner avec le derush (il faudra le script, page Derush)");
    $("#res-sync").innerHTML = s.sync_out ? this.resultCard(s.sync_out, t("Fichier › Importer dans Premiere : séquence « 1 sync »."),
      `<button class="btn primary" data-act="use-sync">${t("Derush avec cette séquence →")}</button>`) : "";
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
    go.textContent = cont ? t("Continuer le derush") : t("Derusher");
    go.disabled = !s.xml || !s.script || !!scan.error || this.job.running;
    $("#res-derush").innerHTML = s.derush_out ? this.resultCard(s.derush_out,
      t("Fichier › Importer dans Premiere : séquences « 2 triage » (tout, coloré par prise) et « 3 derush »."),
      `<button class="btn" data-act="report">${t("Rapport par phrase")}</button>
       <button class="btn primary" data-act="go" data-arg="sources">${t("Illustrations →")}</button>`) : "";
  },

  renderSources() {
    const s = this.view.state, src = this.view.sources || {};
    $("#outdir").innerHTML = src.out && src.exists ? `<button class="link" data-act="open" data-arg="${esc(src.out)}" title="${esc(src.out)}">📁 <span data-noi18n>${esc(where(src.out) ? src.out : base(src.out))}</span></button>` : "";
    $("#res-place").innerHTML = s.broll_out ? this.resultCard(s.broll_out, t("Fichier › Importer dans Premiere.")) : "";
    $("#pipeline").style.opacity = s.script ? "" : ".5";

    const fromDerush = s.place_xml && s.place_xml === s.derush_out;
    $("#place-slot").className = `pslot ${s.place_xml ? "set" : ""}`;
    $("#place-slot").innerHTML = s.place_xml
      ? `<span class="fname"><b title="${esc(s.place_xml)}">${esc(base(s.place_xml))}</b><small>${fromDerush ? t("résultat du derush") : t("votre séquence")}</small></span>
         <button class="btn small" data-pick="sources">${t("Changer…")}</button><button class="icon-btn" title="${esc(t("Retirer"))}" data-remove="place_xml">✕</button>`
      : `<span class="muted" style="flex:1">${t("Glissez ici la séquence (.xml) : le derush ou votre montage")}</span>
         <button class="btn small" data-pick="sources">${t("Choisir…")}</button>`;

    const collected = src.collected > 0, chosen = src.chosen > 0, placeable = chosen && !!s.place_xml;
    const next = !s.script ? null : !collected ? "collect" : !chosen ? "choose" : "place";
    const set = (id, text, isDone, enabled) => {
      const el = $(id);
      $("p", el).innerHTML = text;
      el.classList.toggle("done", isDone);
      el.classList.toggle("next", next === id.slice(3));
      $(":scope > button", el).disabled = !enabled || (this.job.running && id !== "#p-choose");
    };
    set("#p-collect", collected ? `<span class="stat">${t("{n} candidats", { n: src.collected })}</span> ${t("— relancer ne retélécharge que le nouveau.")}` :
      t("Images des liens du script, captures des pages, recherches libres de droits. Quelques minutes."), collected, !!s.script);
    $("#p-collect > button").textContent = collected ? t("Recollecter") : t("Collecter");
    set("#p-choose", chosen ? `<span class="stat">${t("{n} choisis", { n: src.chosen })}</span>${src.exported ? " · " + t("{n} téléchargés", { n: src.exported }) : ""}` :
      t("Cochez les vignettes à garder dans la planche et téléchargez-les — ou glissez-les directement dans Premiere."), chosen, collected);
    set("#p-place", src.exported ? `<span class="stat">${t("{n} fichiers", { n: src.exported })}</span> ${t("dans « médias ». Placer écrit le .xml des illustrations aux timecodes (ce qui manque est téléchargé). Après un nouveau montage : exportez-le en XML, déposez-le ici, replacez.")}` :
      t("Chaque image va au timecode de sa phrase. Les phrases sont retrouvées par les marqueurs du derush, ou à l'écoute."), src.exported > 0, placeable);
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
    $$(".ai-current").forEach((el) => { el.textContent = cur ? `${cur.label} (${cur.how})` : t("aucune connectée"); });
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
    $("#sb-refs").innerHTML = s.sb_refs.map((r) => `<div class="ref" title="${esc(r)}"><img src="file:///${esc(r.replace(/\\/g, "/"))}" alt="">
        <button class="icon-btn" title="${esc(t("Retirer"))}" data-remove="sb_refs" data-value="${esc(r)}">✕</button></div>`).join("") +
      `<span class="muted" style="flex:1;min-width:200px">${s.sb_refs.length ? "" : t("Images de référence du style (facultatif) : glissez-les ici.") + " "}</span>
       <button class="btn small" data-pick="storyboard">${t("Ajouter…")}</button>`;
    const seq = s.place_xml || s.derush_out;
    $("#sb-seq").className = `pslot sb-seq ${seq ? "set" : ""}`;
    $("#sb-seq").innerHTML = seq
      ? `<span class="fname"><b title="${esc(seq)}">${esc(base(seq))}</b><small>${seq === s.derush_out ? t("résultat du derush") : t("votre séquence")} · ${t("donne les durées")}</small></span>
         <button class="btn small" data-pick="sources">${t("Changer…")}</button>${s.place_xml ? `<button class="icon-btn" title="${esc(t("Retirer"))}" data-remove="place_xml">✕</button>` : ""}`
      : `<span class="muted" style="flex:1">${t("Sans séquence (.xml), les durées sont estimées d'après le texte")}</span>
         <button class="btn small" data-pick="sources">${t("Choisir…")}</button>`;
    $("#sb-info").innerHTML = !s.script ? "" : sb.beats
      ? `<b>${t("{n} plans", { n: sb.beats })}</b>, ${t("{n} cartes", { n: sb.cards })} · ${esc(sb.created)} · ${esc(sb.engine)} · ${sb.timing === "montage" ? t("durées du montage") : t("durées estimées")}
         ${sb.xml ? "<br>" + t("Premiere : panneau Autocut › Storyboard › Placer, ou importez {file}.",
           { file: `<button class="link" data-act="reveal" data-arg="${esc(sb.xml)}" data-noi18n>${esc(base(sb.xml))}</button>` }) : ""}
         ${sb.brief !== (s.opts.sb_style || "").trim() ? "<br>" + t("Le style a changé depuis : recréez pour une nouvelle bible de style.") : "<br>" + t("Recréer garde la bible de style et les plans verrouillés sur la page.")}`
      : "";
    $("#go-sb").disabled = !s.script || this.job.running;
    $("#go-sb").textContent = sb.beats ? t("Recréer le storyboard") : t("Créer le storyboard");
    $("#open-sb").disabled = !sb.beats;
  },

  renderSfx() {
    if (!this.view) return;
    const s = this.view.state, o = s.opts, fx = this.view.sfx || {}, keys = this.view.keys || {};
    const edit = fx.edit, own = !!s.sfx_xml;
    $("#sfx-edit").className = `pslot sfx-edit ${edit ? "set" : ""}`;
    $("#sfx-edit").innerHTML = edit
      ? `<span class="kind video">XML</span><span class="fname"><b title="${esc(edit)}">${esc(base(edit))}</b><small>${own ? t("votre montage") : t("le même que les illustrations")}</small></span>
         <button class="btn small" data-pick="sfx">${t("Changer…")}</button>${own ? `<button class="icon-btn" title="${esc(t("Retirer"))}" data-remove="sfx_xml">✕</button>` : ""}`
      : `<span class="muted" style="flex:1">${t("Glissez le montage fini (.xml) : Premiere › Fichier › Exporter › Final Cut Pro XML")}</span>
         <button class="btn small" data-pick="sfx">${t("Choisir…")}</button>`;
    const on = (k) => (o.sfx_sources || {})[k] !== false;
    const row = (k, title, detail, extra = "") => `<li class="item"><button class="dot ${on(k) ? "ok" : "opt"}" data-act="sfx-src" data-arg="${k}"
        title="${esc(on(k) ? t("Utilisée — cliquer pour l'ignorer") : t("Ignorée — cliquer pour l'utiliser"))}" style="border:0;cursor:pointer">${on(k) ? "✓" : "–"}</button>
      <span class="ctext"><b>${title}</b><span>${detail}</span>${extra}</span></li>`;
    const folders = o.sfx_folders || [];
    $("#sfx-srcs").innerHTML =
      row("folder", t("Vos dossiers"), folders.length ? t("Les sons sont triés par leur nom (whoosh, click, pop, typing…).") : t("Vos téléchargements Epidemic, Artlist, Envato, vos packs : glissez un dossier ici."),
        `<div class="srcfold">${folders.map((f) => `<span class="chip" title="${esc(f)}"><span>${esc(f)}</span><button class="icon-btn" data-act="sfx-folder-rm" data-arg="${esc(f)}">✕</button></span>`).join("")}
           <button class="btn small" data-act="sfx-folder">${t("Ajouter un dossier…")}</button></div>`) +
      row("epidemic", "Epidemic Sound", keys.epidemic ? t("Connecté avec votre clé ({key}). Les sons choisis sont téléchargés dans le dossier du projet.", { key: keys.epidemic })
          + (keys.epidemic_src === "env" ? " " + t("(clé lue dans le fichier .env ou l'environnement)") : "")
        : t("Votre abonnement, avec une clé API : epidemicsound.com › Compte › API keys."),
        keys.epidemic && !this.epEdit
          ? `<div class="keyrow inline"><button class="btn small" data-act="sfx-key-edit">${t("Changer la clé")}</button></div>`
          : `<div class="keyrow inline"><input type="password" id="ep-key" placeholder="${esc(keys.epidemic ? t("Nouvelle clé (vide : oublier la clé enregistrée)") : t("Collez la clé"))}" autocomplete="off" spellcheck="false">
          <button class="btn small" data-act="sfx-key">${t("Enregistrer")}</button>${keys.epidemic ? `<button class="btn small" data-act="sfx-key-cancel">${t("Annuler")}</button>` : ""}</div>`) +
      row("earshot", t("Banque intégrée"), t("Sons fabriqués par code (earshot, libres de droits) : jamais deux fois la même prise."));
    $$("#sfx-density button").forEach((b) => b.classList.toggle("on", +b.dataset.d === (o.sfx_density || 2)));
    $("#go-sfx").disabled = !edit || this.job.running;
    $("#go-sfx").textContent = fx.exists ? t("Analyser à nouveau") : t("Analyser le montage");
    $("#open-sfx").disabled = !fx.exists;
    const sum = fx.exists ? `<div class="kinds-sum">${SFX_KINDS.filter(([k]) => fx.kinds[k]).map(([k, n, c]) => `<span><i style="background:${c}"></i>${t(n)} <b>${fx.kinds[k]}</b></span>`).join("")}</div>` : "";
    $("#res-sfx").innerHTML = fx.xml ? this.resultCard(fx.xml, t("Fichier › Importer dans Premiere : les sons seuls, et votre montage avec les sons."), sum)
      : fx.exists ? `<div class="r-head">${t("{n} sons prêts", { n: fx.cues })}${fx.edited ? " · " + t("{n} retouchés", { n: fx.edited }) : ""}</div>${sum}
          <p class="r-sum">${t("Écoutez et ajustez dans l'éditeur, puis « Placer dans Premiere ». Analyser à nouveau garde vos retouches.")}</p>` : "";
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
    const mine = this.job.step && STEP_OF_JOB[this.job.step] === this.step;
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
      this.show(STEP_OF_JOB[ev.step]);
    } else {
      this.job.running = false;
      box.className = `job ${ev.ok ? "ok" : "err"}`;
      $(".bar").classList.remove("indeterminate");
      $("#job-msg").textContent = ev.message || "";
      $("#job-label").textContent = ev.ok ? t("terminé") : "";
      $("#job-eta").textContent = "";
      if (!ev.ok && ev.message !== t("Arrêté.") && ev.message !== "Arrêté.") $("#log-wrap").open = true;
      this.notify(ev);
    }
    this.placeJob();
    if (this.view) this.render(this.view);
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
    try { new Notification("Autocut", { body: ev.message }); } catch (e) { /* not available */ }
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
