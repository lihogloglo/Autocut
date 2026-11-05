// FauxRaccord panel for Premiere Pro (UXP, 25.6+): the connector between Premiere and the FauxRaccord window.
// Everything is done from the window; this panel only shows a status light, and does in Premiere what the
// window cannot reach:
//
// - Tells FauxRaccord where the playhead is (and reads the open sequence when FauxRaccord asks, or when it
//   changed), so the planche follows the sentence being played. Moves the playhead when a sentence is
//   clicked on the planche.
// - Places what the window asks for: every illustration or storyboard card at its sentence (FauxRaccord,
//   local server on port 47820, computes where), one file at the playhead (« → Premiere »), or removes what
//   it placed before. The edit itself, and what was placed by hand, are never touched.
// - Starts FauxRaccord when it is not running (the fauxraccord:// link, registered by FauxRaccord), and says
//   when the panel and FauxRaccord are not the same version.
// Native Premiere widgets only: a web page inside a docked panel is not drawn by Premiere (measured with 26.5).
// Texts: French in the code; the translations come from FauxRaccord (GET /i18n, the window's catalogue).

const ppro = require("premierepro");
const uxp = require("uxp");

const VERSION = "0.5.0";             // = manifest.json (tests/test_premiere_panel.py checks it)
const BRIDGE = "http://127.0.0.1:47820";
const TICKS_PER_SECOND = 254016000000;
const STILL = 5;                     // seconds a picture is reckoned to last when looking for a free track
const TICK = 400;                    // ms between two asks while FauxRaccord is open (the playhead goes with them)
const RECOUNT = 5000;                // ms between two looks at whether the open sequence was edited

const $ = (id) => document.getElementById(id);
const NAMES = { sources: "illustrations", storyboard: "cartes du storyboard" };
const norm = (p) => (p || "").replace(/\\/g, "/").toLowerCase();

// --- interface language ------------------------------------------------------------------------

const I18N = { lang: "fr", dict: {}, loaded: false };

function t(s, vars) {
  const r = I18N.dict[s] != null ? I18N.dict[s] : s;
  return vars ? r.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m)) : r;
}

/** Asks FauxRaccord for the catalogue of its interface language; silent when FauxRaccord is not running. */
async function loadI18n() {
  try {
    const d = await (await fetch(BRIDGE + "/i18n")).json();
    if (d && d.ok) {
      I18N.lang = d.lang || "fr";
      I18N.dict = d.dict || {};
      I18N.loaded = true;
      $("start").textContent = t("Démarrer");
    }
  } catch (e) { /* FauxRaccord closed: French until the next successful call */ }
}

function setStatus(msg, cls) {
  $("status").textContent = msg || "";
  $("status").className = cls || "";
}

// --- the link with FauxRaccord -----------------------------------------------------------------

const CONN = { ok: false, launched: 0, lastOk: 0, hello: null, note: "" };
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

function light(cls, name, text) {
  $("dot").className = cls;
  $("name").textContent = name || "FauxRaccord";
  $("conn").textContent = text || "";
  $("start").style.display = cls === "bad" ? "" : "none";
}

/** Starts FauxRaccord (in the background), through its fauxraccord:// link. */
function launch() {
  // Answered a moment ago: it is busy, not closed. And one launch is enough while it starts.
  if (Date.now() - CONN.lastOk < RELAUNCH || Date.now() - CONN.launched < RELAUNCH) return;
  CONN.launched = Date.now();
  try {
    const r = uxp.shell.openExternal("fauxraccord://start", t("Démarrer FauxRaccord"));
    if (r && r.catch) r.catch((e) => setStatus(t("FauxRaccord ne démarre pas : {error}", { error: e.message || e }), "err"));
  } catch (e) {
    setStatus(t("FauxRaccord ne démarre pas : {error}", { error: e.message || e }), "err");
  }
  light("wait", "FauxRaccord", t("démarrage…"));
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
    ? t("Nouvelle version installée, active au prochain démarrage de Premiere.")
    : t("Ce panneau ({v}) est plus récent que FauxRaccord : mettez FauxRaccord à jour.", { v: VERSION });
}

async function connect() {
  const h = await hello();
  const was = CONN.ok;
  CONN.ok = !!h;
  CONN.hello = h;
  if (h) {
    CONN.lastOk = Date.now();
    if (!was) await loadI18n();
    CONN.note = versionNote(h);
    if (CONN.note) setStatus(CONN.note, "note");
    return true;
  }
  if (!CONN.launched) { launch(); return false; }
  if (Date.now() - CONN.launched < 45000) { light("wait", "FauxRaccord", t("démarrage…")); return false; }
  light("bad", "FauxRaccord", t("fermé"));
  return false;
}

async function bridge(path, kind, body) {
  let r;
  try {
    r = await fetch(BRIDGE + path + "?kind=" + kind, body ? { method: "POST", body: JSON.stringify(body),
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

const post = (path, body) => fetch(BRIDGE + path, { method: "POST", body: JSON.stringify(body),
                                                    headers: { "Content-Type": "application/json" } }).catch(() => {});

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
    for (let i = 0; i < list.length; i++) {
      const tis = await list[i].getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
      for (const ti of tis) {
        const path = await mediaPath(await ti.getProjectItem());
        const start = (await ti.getStartTime()).seconds, end = (await ti.getEndTime()).seconds;
        if (path && isOurs(path)) { ours.push({ ti, kind, track: i, path, start, end }); continue; }
        top[kind] = Math.max(top[kind], i);
        if (path) items.push({ start, end, in: (await ti.getInPoint()).seconds, path });
      }
    }
  }
  const markers = [];
  try {
    for (const m of (await ppro.Markers.getMarkers(seq)).getMarkers()) {
      markers.push({ name: m.getName(), start: m.getStart().seconds, duration: m.getDuration().seconds });
    }
  } catch (e) { /* no markers: FauxRaccord finds the sentences through the derush */ }
  return { info: { name: seq.name, fps, width, height, items, markers }, ours, top };
}

/** How many clips the sequence holds: a cheap sign that it was edited. */
async function clipCount(seq) {
  let n = 0;
  for (const kind of ["video", "audio"]) {
    for (const tr of await tracks(seq, kind)) n += (await tr.getTrackItems(ppro.Constants.TrackItemType.CLIP, false)).length;
  }
  return n;
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
    setStatus(t("import : {n} fichier(s) dans « {bin} »", { n: paths.size, bin: section }));
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

/** Every illustration (or storyboard card) at its sentence; what the panel placed before is replaced. */
async function place(kind) {
  const what = t(NAMES[kind] || NAMES.sources);
  const st = await bridge("/status", kind);
  const { project, seq } = await openSequence();

  setStatus(t("Lecture de « {name} »…", { name: seq.name }));
  const { info, ours, top } = await readSequence(seq, st.export_dir, st.ours);

  setStatus(t("Calcul des emplacements…"));
  const plan = await bridge("/plan", kind, info);
  if (!plan.items.length) throw new Error(t("rien à placer"));

  setStatus(t("Import des fichiers…"));
  const items = await importAll(project, plan);

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
  for (const k of ["video", "audio"]) {
    const list = await tracks(seq, k);
    const from = k === "video" ? baseV : baseA;
    for (let i = from; i < list.length; i++) {
      for (const ti of await list[i].getTrackItems(ppro.Constants.TrackItemType.CLIP, false)) {
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
  const missing = plan.items.length - todo.length;
  return t("{n} {what} sur {tracks}", { n: todo.length, what, tracks: where })
    + (missing ? " · " + t("{n} non importé(s)", { n: missing }) : "")
    + (plan.timed ? "" : " · " + t("pas de phrases repérées : illustrations à la suite"));
}

async function remove(kind) {
  const what = t(NAMES[kind] || NAMES.sources);
  const st = await bridge("/status", kind);
  const { project, seq } = await openSequence();
  const { ours } = await readSequence(seq, st.export_dir, st.ours);
  removeOurs(project, seq, ours);
  return t("{n} {what} retirée(s)", { n: ours.length, what });
}

// --- one file at the playhead (the planche's « → Premiere ») ------------------------------------

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
  return t("{name} sur {track}", { name: data.name, track: data.audio ? "A" + (a + 1) : "V" + (v + 1) });
}

// --- the playhead, and the sequence it plays ---------------------------------------------------

const PLAY = { seq: null, name: "", t: null, count: -1, counted: 0, sending: false };

/** Where the playhead is in the open sequence (null when no sequence is open). */
async function playhead() {
  try {
    const project = await ppro.Project.getActiveProject();
    const seq = project && await project.getActiveSequence();
    if (!seq) { PLAY.seq = null; return null; }
    if (!PLAY.seq || PLAY.name !== seq.name) { PLAY.count = -1; PLAY.counted = 0; }
    PLAY.seq = seq;
    PLAY.name = seq.name;
    PLAY.t = (await seq.getPlayerPosition()).seconds;
    return PLAY.t;
  } catch (e) {
    return null;
  }
}

/** The open sequence to FauxRaccord (where the sentences are): when it asks, and when the edit changed. */
async function sendSequence(force) {
  const seq = PLAY.seq;
  if (!seq || PLAY.sending) return;
  if (!force && Date.now() - PLAY.counted < RECOUNT) return;
  PLAY.sending = true;
  try {
    PLAY.counted = Date.now();
    const n = await clipCount(seq);
    if (!force && n === PLAY.count) return;
    PLAY.count = n;
    const { info } = await readSequence(seq, "", []);
    await post("/sequence", info);
  } catch (e) {
    /* next time */
  } finally {
    PLAY.sending = false;
  }
}

async function seek(seconds) {
  try {
    const { seq } = await openSequence();
    await seq.setPlayerPosition(ppro.TickTime.createWithSeconds(seconds));
  } catch (e) {
    setStatus(t("La tête de lecture ne bouge pas : {error}", { error: e.message || e }), "err");
  }
}

// --- the loop: ask FauxRaccord what it wants, tell it where the playhead is ----------------------

let working = false;
async function tick() {
  if (!CONN.ok) return connect();
  if (working) return;
  const pos = await playhead();
  let d;
  try {
    const q = "?v=" + VERSION + (pos != null ? "&t=" + pos.toFixed(3) + "&seq=" + encodeURIComponent(PLAY.name) : "");
    d = await (await fetch(BRIDGE + "/pending" + q)).json();
    CONN.lastOk = Date.now();
  } catch (e) {
    CONN.ok = false;
    return connect();
  }
  const st = d.status || {};
  light(CONN.note ? "wait" : "ok", st.project || "FauxRaccord",
        st.sentence ? t("suit {s}", { s: st.sentence }) : PLAY.seq ? PLAY.name : t("connecté"));
  if (d.seek != null) await seek(d.seek);
  sendSequence(d.want === "sequence");        // not awaited: the playhead keeps going while it reads
  const req = d.request;
  if (!req) return;
  working = true;
  await post("/claim", { id: req.id });
  try {
    setStatus(t("FauxRaccord place…"));
    const kind = (req.data && req.data.kind) || req.kind;
    const msg = req.kind === "insert" ? await insertAtPlayhead(req.data || {})
      : req.kind === "remove" ? await remove(kind)
      : await place(req.kind);
    setStatus("✓ " + msg);
    await post("/result", { id: req.id, ok: true, message: msg });
    PLAY.counted = 0;                         // the sequence changed: read it again soon
  } catch (e) {
    setStatus(String(e.message || e), "err");
    await post("/result", { id: req.id, ok: false, message: String(e.message || e) });
  } finally {
    working = false;
  }
}

async function loop() {
  try { await tick(); } catch (e) { /* next round */ }
  setTimeout(loop, CONN.ok ? TICK : 1500);
}

$("start").addEventListener("click", () => { CONN.launched = 0; CONN.lastOk = 0; launch(); });
document.addEventListener("uxpcommand", () => connect());
light("wait", "FauxRaccord", "…");
connect().then(loop);
