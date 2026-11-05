// FauxRaccord panel for Premiere Pro (UXP, 25.6+). Native Premiere widgets only: a web page inside a docked
// panel is not drawn by Premiere (measured with 26.5), and the big boards live in the FauxRaccord window.
//
// - Starts FauxRaccord when it is not running (the fauxraccord:// link, registered by FauxRaccord), and says
//   when the panel and FauxRaccord are not the same version.
// - « Placer » reads the open sequence, asks FauxRaccord (local server, port 47820) where each illustration
//   or storyboard card goes, imports the files into bins and puts them on the tracks above the edit. Placing
//   again first removes what the panel placed before, so it can be re-run after every re-edit. The edit
//   itself, and what you placed by hand, are never touched.
// - « Ouvrir » brings the FauxRaccord window (or one of its boards) to the front.
// - The boards' « → Premiere » (and the sound board's I key): one file at the playhead, on the first track
//   that is free for its length (V2 and up, A2 and up; a new track when none is).
// Texts: French in the code; the translations come from FauxRaccord (GET /i18n, the window's catalogue).

const ppro = require("premierepro");
const uxp = require("uxp");

const VERSION = "0.4.1";             // = manifest.json (tests/test_premiere_panel.py checks it)
const BRIDGE = "http://127.0.0.1:47820";
const TICKS_PER_SECOND = 254016000000;
const STILL = 5;                     // seconds a picture is reckoned to last when looking for a free track

const $ = (id) => document.getElementById(id);
let forcedKind = "";         // set while placing what the FauxRaccord window asked for
const kind = () => { if (forcedKind) return forcedKind; const p = $("kind"); if (!p) return "sources"; if (p.value === "storyboard" || p.value === "sources") return p.value; return p.selectedIndex === 1 ? "storyboard" : "sources"; };
const NAMES = { sources: "illustrations", storyboard: "cartes du storyboard" };
const what = () => t(NAMES[kind()]);
const norm = (p) => (p || "").replace(/\\/g, "/").toLowerCase();

// --- interface language ------------------------------------------------------------------------

const I18N = { lang: "fr", dict: {}, loaded: false };

function t(s, vars) {
  const r = I18N.dict[s] != null ? I18N.dict[s] : s;
  return vars ? r.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m)) : r;
}

const placeLabel = () => t(kind() === "storyboard" ? "Placer le storyboard" : "Placer les illustrations");

/** Static labels, from their French text (kept in data-fr so the language can change again). */
function applyStatic() {
  $("place").textContent = placeLabel();
  $("kind").setAttribute("label", t("Quoi"));
  for (const el of document.querySelectorAll("sp-menu-item, sp-action-button, #remove, #start, .sec")) {
    if (!el.getAttribute("data-fr")) el.setAttribute("data-fr", el.textContent.trim());
    el.textContent = t(el.getAttribute("data-fr"));
  }
}

/** Asks FauxRaccord for the catalogue of its interface language; silent when FauxRaccord is not running. */
async function loadI18n() {
  try {
    const d = await (await fetch(BRIDGE + "/i18n")).json();
    if (d && d.ok) {
      I18N.lang = d.lang || "fr";
      I18N.dict = d.dict || {};
      I18N.loaded = true;
      applyStatic();
    }
  } catch (e) { /* FauxRaccord closed: French until the next successful call */ }
}

function log(msg, cls) {
  const d = document.createElement("div");
  d.textContent = msg;
  if (cls) d.className = cls;
  $("log").appendChild(d);
  $("log").scrollTop = 1e9;
}

function setStatus(msg, cls) {
  $("status").textContent = msg;
  $("status").className = cls || "";
}

// --- the link with FauxRaccord -----------------------------------------------------------------

const CONN = { ok: false, launched: 0, lastOk: 0, hello: null, warned: "" };
const RELAUNCH = 30000;     // never two launches closer than this: FauxRaccord may just be busy

/** a.b.c compared as numbers: < 0, 0, > 0 */
function cmp(a, b) {
  const x = String(a).split("."), y = String(b).split(".");
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    const d = (parseInt(x[i], 10) || 0) - (parseInt(y[i], 10) || 0);
    if (d) return d;
  }
  return 0;
}

function connState(cls, text) {
  $("dot").className = cls;
  $("conn").textContent = text;
}

/** Starts FauxRaccord (in the background) or brings it forward on a page, through its fauxraccord:// link. */
function launch(view) {
  // Answered a moment ago: it is busy, not closed. And one launch is enough while it starts.
  if (Date.now() - CONN.lastOk < RELAUNCH || Date.now() - CONN.launched < RELAUNCH) {
    setStatus(t("FauxRaccord est occupé : un instant…"));
    return;
  }
  CONN.launched = Date.now();
  const url = view ? "fauxraccord://open/" + view : "fauxraccord://start";
  try {
    const r = uxp.shell.openExternal(url, t("Démarrer FauxRaccord"));
    if (r && r.catch) r.catch((e) => log(t("FauxRaccord ne démarre pas : {error}", { error: e.message || e }), "err"));
  } catch (e) {
    log(t("FauxRaccord ne démarre pas : {error}", { error: e.message || e }), "err");
  }
  connState("wait", t("démarrage…"));
}

async function hello() {
  try {
    const d = await (await fetch(BRIDGE + "/hello")).json();
    return d && d.app === "FauxRaccord" ? d : null;
  } catch (e) {
    return null;
  }
}

/** The versions: FauxRaccord installs the panel that goes with it; Premiere loads it at its next start. */
function versionNote(h) {
  if (!h.panel || h.panel === VERSION) return "";
  return cmp(h.panel, VERSION) > 0
    ? t("FauxRaccord a installé le panneau {v} : redémarrez Premiere pour l'utiliser.", { v: h.panel })
    : t("Ce panneau ({v}) est plus récent que FauxRaccord : mettez FauxRaccord à jour.", { v: VERSION });
}

async function connect() {
  const h = await hello();
  const was = CONN.ok;
  CONN.ok = !!h;
  CONN.hello = h;
  $("start").style.display = "none";
  if (h) {
    CONN.lastOk = Date.now();
    if (!was) { await loadI18n(); refresh(); }
    const note = versionNote(h);
    connState(note ? "wait" : "ok", "v" + VERSION + (h.version ? " · FauxRaccord " + h.version : ""));
    if (note && CONN.warned !== note) { CONN.warned = note; setStatus(note, "err"); }
    return true;
  }
  if (!CONN.launched) { launch(); return false; }
  if (Date.now() - CONN.launched < 45000) { connState("wait", t("démarrage…")); return false; }
  connState("bad", t("FauxRaccord n'est pas ouvert"));
  $("start").style.display = "";
  $("project").textContent = "";
  return false;
}

async function bridge(path, body) {
  let r;
  try {
    r = await fetch(BRIDGE + path + "?kind=" + kind(), body ? { method: "POST", body: JSON.stringify(body),
                                             headers: { "Content-Type": "application/json" } } : {});
  } catch (e) {
    CONN.ok = false;
    throw new Error(t("FauxRaccord n'est pas ouvert : il démarre, réessayez dans un instant."));
  }
  const data = await r.json();
  if (!I18N.loaded) await loadI18n();      // FauxRaccord was started after the panel
  if (!data.ok) throw new Error(data.error || t("erreur de FauxRaccord"));
  return data;
}

// --- reading Premiere ---------------------------------------------------------------------------

async function mediaPath(projectItem) {
  const clip = projectItem && ppro.ClipProjectItem.cast(projectItem);
  if (!clip) return "";
  try { return (await clip.getMediaFilePath()) || ""; } catch (e) { return ""; }
}

async function tracks(seq, kind) {
  const n = kind === "video" ? await seq.getVideoTrackCount() : await seq.getAudioTrackCount();
  const out = [];
  for (let i = 0; i < n; i++) out.push(kind === "video" ? await seq.getVideoTrack(i) : await seq.getAudioTrack(i));
  return out;
}

async function fpsOf(seq) {
  const tb = Number(await seq.getTimebase());           // ticks per frame
  return tb ? TICKS_PER_SECOND / tb : 25;
}

/** Clips of the sequence. Ours (files the panel placed, or from the export folder) apart: they are
 *  replaced on each run. */
async function readSequence(seq, exportDir, oursList) {
  const fps = await fpsOf(seq);
  let width = 1920, height = 1080;
  try { const r = await seq.getFrameSize(); width = r.width || width; height = r.height || height; } catch (e) {}
  const items = [], ours = [], top = { video: -1, audio: -1 };
  const ourDir = norm(exportDir);
  const mine = Array.isArray(oursList) ? new Set(oursList.map(norm)) : null;
  const isOurs = (path) => mine ? mine.has(norm(path)) : norm(path).startsWith(ourDir);
  for (const kind of ["video", "audio"]) {
    const list = await tracks(seq, kind);
    for (let t = 0; t < list.length; t++) {
      const tis = await list[t].getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
      for (const ti of tis) {
        const path = await mediaPath(await ti.getProjectItem());
        const start = (await ti.getStartTime()).seconds, end = (await ti.getEndTime()).seconds;
        if (path && isOurs(path)) { ours.push({ ti, kind, track: t, path, start, end }); continue; }
        top[kind] = Math.max(top[kind], t);
        if (path) items.push({ start, end, in: (await ti.getInPoint()).seconds, path });
      }
    }
  }
  const markers = [];
  try {
    for (const m of (await ppro.Markers.getMarkers(seq)).getMarkers()) {
      markers.push({ name: m.getName(), start: m.getStart().seconds, duration: m.getDuration().seconds });
    }
  } catch (e) { log(t("marqueurs illisibles : {error}", { error: e })); }
  return { info: { name: seq.name, fps, width, height, items, markers }, ours, top };
}

// --- project bins -----------------------------------------------------------------------------

async function childBin(project, parent, name) {
  const find = async () => {
    for (const it of await parent.getItems()) {
      const f = ppro.FolderItem.cast(it);
      if (f && it.name === name) return f;
    }
    return null;
  };
  let bin = await find();
  if (!bin) {
    project.lockedAccess(() => project.executeTransaction(
      (ca) => ca.addAction(parent.createBinAction(name, false)), t("FauxRaccord : chutier")));
    bin = await find();
  }
  if (!bin) throw new Error(t("impossible de créer le chutier « {name} »", { name }));
  return bin;
}

async function clipsIn(folder, out = new Map()) {
  for (const it of await folder.getItems()) {
    const f = ppro.FolderItem.cast(it);
    if (f) { await clipsIn(f, out); continue; }
    const p = await mediaPath(it);
    if (p) out.set(norm(p), it);
  }
  return out;
}

/** Imports what is not in the project yet, one bin per section under the main bin. path -> ProjectItem. */
async function importAll(project, plan) {
  const root = await project.getRootItem();
  const main = await childBin(project, root, plan.bin);
  let have = await clipsIn(main);
  const bySection = new Map();
  for (const it of plan.items) {
    if (have.has(norm(it.path))) continue;
    if (!bySection.has(it.bin)) bySection.set(it.bin, new Set());
    bySection.get(it.bin).add(it.path);
  }
  for (const [section, paths] of bySection) {
    const bin = await childBin(project, main, section);
    log(t("import : {n} fichier(s) dans « {bin} »", { n: paths.size, bin: section }));
    await project.importFiles([...paths], true, bin, false);
  }
  if (bySection.size) have = await clipsIn(main);
  return have;
}

// --- editing -----------------------------------------------------------------------------------

function transaction(project, name, build) {
  let ok = false;
  project.lockedAccess(() => { ok = project.executeTransaction((ca) => build(ca), name); });
  return ok;
}

function removeOurs(project, seq, ours) {
  if (!ours.length) return true;
  const editor = ppro.SequenceEditor.getEditor(seq);
  let ok = false;
  ppro.TrackItemSelection.createEmptySelection((sel) => {
    for (const o of ours) sel.addItem(o.ti, true);
    ok = transaction(project, t("FauxRaccord : retirer les illustrations"), (ca) =>
      ca.addAction(editor.createRemoveItemsAction(sel, false, ppro.Constants.MediaType.VIDEO, false)));
  });
  return ok;
}

const snap = (s, fps) => Math.round(s * fps) / fps;
const at = (s, fps) => ppro.TickTime.createWithSeconds(snap(s, fps));

async function openSequence() {
  const project = await ppro.Project.getActiveProject();
  const seq = project && await project.getActiveSequence();
  if (!seq) throw new Error(t("ouvrez la séquence du montage dans la timeline"));
  return { project, seq };
}

async function place() {
  $("log").textContent = "";
  const st = await bridge("/status");
  const { project, seq } = await openSequence();

  setStatus(t("Lecture de « {name} »…", { name: seq.name }));
  const { info, ours, top } = await readSequence(seq, st.export_dir, st.ours);
  log(t("{n} plans lus, {m} marqueurs, {k} {what} déjà placées",
        { n: info.items.length, m: info.markers.length, k: ours.length, what: what() }));

  setStatus(t("Calcul des emplacements…"));
  const plan = await bridge("/plan", info);
  plan.log.forEach((l) => log(l.trim()));
  if (!plan.items.length) throw new Error(t("rien à placer"));
  if (!plan.timed) log(t("pas de phrases repérées : illustrations à la suite"), "err");

  setStatus(t("Import des fichiers…"));
  const items = await importAll(project, plan);
  const missing = plan.items.filter((it) => !items.has(norm(it.path)));
  missing.forEach((it) => log(t("non importé : {path}", { path: it.path }), "err"));

  setStatus(t("Placement…"));
  removeOurs(project, seq, ours);
  const fps = info.fps;
  const editor = ppro.SequenceEditor.getEditor(seq);
  const baseV = top.video + 1, baseA = top.audio + 1;
  const todo = plan.items.filter((it) => items.has(norm(it.path)))
    .map((it) => ({ ...it, v: baseV + it.lane, a: baseA + it.lane, pi: items.get(norm(it.path)) }));

  // Tracks that do not exist yet are created by inserting the first clip that needs them.
  let nV = await seq.getVideoTrackCount(), nA = await seq.getAudioTrackCount();
  for (const it of todo) {
    if (it.v < nV && (it.image || it.a < nA)) continue;
    transaction(project, t("FauxRaccord : piste"), (ca) =>
      ca.addAction(editor.createInsertProjectItemAction(it.pi, at(it.start, fps), it.v, it.a, true)));
    it.done = true;
    nV = await seq.getVideoTrackCount();
    nA = await seq.getAudioTrackCount();
  }
  // In time order: each clip overwrites the tail of the previous one on its track; lengths are set after.
  transaction(project, t("FauxRaccord : placer les illustrations"), (ca) => {
    for (const it of todo) {
      if (!it.done) ca.addAction(editor.createOverwriteItemAction(it.pi, at(it.start, fps), it.v, it.a));
    }
  });

  setStatus(t("Durées…"));
  const want = new Map(todo.map((it) => [norm(it.path) + "@" + snap(it.start, fps).toFixed(2), it]));
  const trims = [];
  for (const kind of ["video", "audio"]) {
    const list = await tracks(seq, kind);
    const from = kind === "video" ? baseV : baseA;
    for (let t = from; t < list.length; t++) {
      for (const ti of await list[t].getTrackItems(ppro.Constants.TrackItemType.CLIP, false)) {
        const path = await mediaPath(await ti.getProjectItem());
        const start = (await ti.getStartTime()).seconds;
        const it = want.get(norm(path) + "@" + snap(start, fps).toFixed(2));
        if (!it) continue;
        const end = snap(it.start + it.length, fps);
        if (Math.abs((await ti.getEndTime()).seconds - end) > 0.5 / fps) trims.push([ti, end]);
      }
    }
  }
  if (trims.length) {
    transaction(project, t("FauxRaccord : durées des illustrations"), (ca) => {
      for (const [ti, end] of trims) ca.addAction(ti.createSetEndAction(ppro.TickTime.createWithSeconds(end)));
    });
  }
  const lanes = Math.max(...todo.map((it) => it.lane)) + 1;
  const where = `V${baseV + 1}${lanes > 1 ? "–V" + (baseV + lanes) : ""}`;
  const done = t("{n} {what} sur {tracks}", { n: todo.length, what: what(), tracks: where });
  setStatus("✓ " + done, "ok");
  return done;
}

async function remove() {
  $("log").textContent = "";
  const st = await bridge("/status");
  const { project, seq } = await openSequence();
  const { ours } = await readSequence(seq, st.export_dir, st.ours);
  removeOurs(project, seq, ours);
  setStatus("✓ " + t("{n} {what} retirée(s)", { n: ours.length, what: what() }), "ok");
}

// --- one file at the playhead (the boards' « → Premiere ») --------------------------------------

/** The first track from `from` with nothing between start and end; the track count when none is free. */
async function freeTrack(seq, kind, from, start, end) {
  const list = await tracks(seq, kind);
  for (let i = from; i < list.length; i++) {
    let busy = false;
    for (const ti of await list[i].getTrackItems(ppro.Constants.TrackItemType.CLIP, false)) {
      const s = (await ti.getStartTime()).seconds, e = (await ti.getEndTime()).seconds;
      if (s < end - 0.001 && e > start + 0.001) { busy = true; break; }
    }
    if (!busy) return i;
  }
  return list.length;
}

async function insertAtPlayhead(data) {
  const { project, seq } = await openSequence();
  const fps = await fpsOf(seq);
  const start = snap((await seq.getPlayerPosition()).seconds, fps);
  const end = start + (data.duration || STILL);

  const root = await project.getRootItem();
  const bin = await childBin(project, await childBin(project, root, "FauxRaccord"), t("Insérés"));
  let have = await clipsIn(bin);
  if (!have.has(norm(data.path))) {
    await project.importFiles([data.path], true, bin, false);
    have = await clipsIn(bin);
  }
  const pi = have.get(norm(data.path));
  if (!pi) throw new Error(t("non importé : {path}", { path: data.path }));

  const v = data.audio ? 0 : await freeTrack(seq, "video", 1, start, end);
  const a = data.image ? 0 : await freeTrack(seq, "audio", 1, start, end);
  const editor = ppro.SequenceEditor.getEditor(seq);
  const nV = await seq.getVideoTrackCount(), nA = await seq.getAudioTrackCount();
  const newTrack = data.audio ? a >= nA : v >= nV || (!data.image && a >= nA);
  transaction(project, t("FauxRaccord : insérer {name}", { name: data.name }), (ca) => ca.addAction(newTrack
    ? editor.createInsertProjectItemAction(pi, at(start, fps), v, a, true)        // a new track: nothing shifts
    : editor.createOverwriteItemAction(pi, at(start, fps), v, a)));
  const where = data.audio ? "A" + (a + 1) : "V" + (v + 1);
  const done = t("{name} sur {track}", { name: data.name, track: where });
  setStatus("✓ " + done, "ok");
  return done;
}

// --- buttons -----------------------------------------------------------------------------------

function busy(on) {
  $("place").disabled = $("remove").disabled = on;
}

function button(id, job) {
  $(id).addEventListener("click", async () => {
    busy(true);
    try {
      await job();
    } catch (e) {
      setStatus(String(e.message || e), "err");
      log(String(e.stack || e), "err");
    } finally {
      busy(false);
    }
  });
}

async function refresh() {
  if (!CONN.ok) return;
  try {
    const st = await bridge("/status");
    $("project").textContent = t("{title} — {n} fichier(s) exporté(s)", { title: st.title, n: st.files })
      + (st.derush ? "" : " · " + t("pas de derush indiqué"));
  } catch (e) {
    $("project").textContent = String(e.message || e);
  }
}

button("place", place);
button("remove", remove);
$("start").addEventListener("click", () => launch());
for (const b of document.querySelectorAll("[data-open]")) {
  b.addEventListener("click", async () => {
    const view = b.getAttribute("data-open");
    if (!CONN.ok) return launch(view);
    try {        // FauxRaccord does one « Ouvrir » at a time and merges a burst of clicks
      await fetch(BRIDGE + "/focus", { method: "POST", body: JSON.stringify({ view }),
                                       headers: { "Content-Type": "application/json" } });
      CONN.lastOk = Date.now();
    } catch (e) {
      launch(view);          // only when it has not answered for a while (see launch)
    }
  });
}
$("kind").addEventListener("change", () => {
  $("place").textContent = placeLabel();
  refresh();
});
document.addEventListener("uxpcommand", () => { connect(); refresh(); });

// What the FauxRaccord window asks for: it leaves a request on the bridge; the panel takes it.
let working = false;
async function pending() {
  if (!CONN.ok) return connect();
  if (working) return;
  let req = null;
  try {
    req = (await (await fetch(BRIDGE + "/pending?v=" + VERSION)).json()).request;
    CONN.lastOk = Date.now();
  } catch (e) {
    CONN.ok = false;
    return connect();
  }
  if (!req) return;
  working = true;
  busy(true);
  const post = (path, body) => fetch(BRIDGE + path, { method: "POST", body: JSON.stringify(body),
                                                      headers: { "Content-Type": "application/json" } }).catch(() => {});
  await post("/claim", { id: req.id });
  try {
    let msg;
    if (req.kind === "insert") msg = await insertAtPlayhead(req.data || {});
    else { forcedKind = req.kind; msg = await place(); }
    await post("/result", { id: req.id, ok: true, message: msg });
  } catch (e) {
    setStatus(String(e.message || e), "err");
    await post("/result", { id: req.id, ok: false, message: String(e.message || e) });
  } finally {
    forcedKind = "";
    working = false;
    busy(false);
  }
}

async function loop() {
  try { await pending(); } catch (e) { /* next round */ }
  setTimeout(loop, CONN.ok ? 2500 : 1500);
}

connect().then(loop);
