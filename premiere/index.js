// Autocut panel for Premiere Pro (UXP, 25.6+).
// Reads the open sequence, asks the Autocut window (local server, port 47820) where each exported
// illustration goes, then imports the files into bins and puts them on the tracks above the edit.
// Placing again first removes what the panel placed before (files from the export folder), so it
// can be re-run after every re-edit. The edit itself is never touched.

const ppro = require("premierepro");

const BRIDGE = "http://127.0.0.1:47820";
const TICKS_PER_SECOND = 254016000000;

const $ = (id) => document.getElementById(id);
const norm = (p) => (p || "").replace(/\\/g, "/").toLowerCase();

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

async function bridge(path, body) {
  let r;
  try {
    r = await fetch(BRIDGE + path, body ? { method: "POST", body: JSON.stringify(body),
                                             headers: { "Content-Type": "application/json" } } : {});
  } catch (e) {
    throw new Error("Autocut n'est pas ouvert (ou pas sur cette machine) : lancez-le, onglet Illustrations.");
  }
  const data = await r.json();
  if (!data.ok) throw new Error(data.error || "erreur d'Autocut");
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

/** Clips of the sequence. Ours (files from the export folder) apart: they are replaced on each run. */
async function readSequence(seq, exportDir) {
  const tb = Number(await seq.getTimebase());           // ticks per frame
  const fps = tb ? TICKS_PER_SECOND / tb : 25;
  let width = 1920, height = 1080;
  try { const r = await seq.getFrameSize(); width = r.width || width; height = r.height || height; } catch (e) {}
  const items = [], ours = [], top = { video: -1, audio: -1 };
  const ourDir = norm(exportDir);
  for (const kind of ["video", "audio"]) {
    const list = await tracks(seq, kind);
    for (let t = 0; t < list.length; t++) {
      const tis = await list[t].getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
      for (const ti of tis) {
        const path = await mediaPath(await ti.getProjectItem());
        const start = (await ti.getStartTime()).seconds, end = (await ti.getEndTime()).seconds;
        if (path && norm(path).startsWith(ourDir)) { ours.push({ ti, kind, track: t, path, start, end }); continue; }
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
  } catch (e) { log("marqueurs illisibles : " + e); }
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
      (ca) => ca.addAction(parent.createBinAction(name, false)), "Autocut : chutier"));
    bin = await find();
  }
  if (!bin) throw new Error("impossible de créer le chutier « " + name + " »");
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
    log(`import : ${paths.size} fichier(s) dans « ${section} »`);
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
    ok = transaction(project, "Autocut : retirer les illustrations", (ca) =>
      ca.addAction(editor.createRemoveItemsAction(sel, false, ppro.Constants.MediaType.VIDEO, false)));
  });
  return ok;
}

const snap = (s, fps) => Math.round(s * fps) / fps;
const at = (s, fps) => ppro.TickTime.createWithSeconds(snap(s, fps));

async function place() {
  $("log").textContent = "";
  const st = await bridge("/status");
  const project = await ppro.Project.getActiveProject();
  const seq = project && await project.getActiveSequence();
  if (!seq) throw new Error("ouvrez la séquence du montage dans la timeline");

  setStatus(`Lecture de « ${seq.name} »…`);
  const { info, ours, top } = await readSequence(seq, st.export_dir);
  log(`${info.items.length} plans lus, ${info.markers.length} marqueurs, ${ours.length} illustrations déjà placées`);

  setStatus("Calcul des emplacements…");
  const plan = await bridge("/plan", info);
  plan.log.forEach((l) => log(l.trim()));
  if (!plan.items.length) throw new Error("aucune illustration à placer");
  if (!plan.timed) log("pas de phrases repérées : illustrations à la suite", "err");

  setStatus("Import des fichiers…");
  const items = await importAll(project, plan);
  const missing = plan.items.filter((it) => !items.has(norm(it.path)));
  missing.forEach((it) => log("non importé : " + it.path, "err"));

  setStatus("Placement…");
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
    transaction(project, "Autocut : piste", (ca) =>
      ca.addAction(editor.createInsertProjectItemAction(it.pi, at(it.start, fps), it.v, it.a, true)));
    it.done = true;
    nV = await seq.getVideoTrackCount();
    nA = await seq.getAudioTrackCount();
  }
  // In time order: each clip overwrites the tail of the previous one on its track; lengths are set after.
  transaction(project, "Autocut : placer les illustrations", (ca) => {
    for (const it of todo) {
      if (!it.done) ca.addAction(editor.createOverwriteItemAction(it.pi, at(it.start, fps), it.v, it.a));
    }
  });

  setStatus("Durées…");
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
    transaction(project, "Autocut : durées des illustrations", (ca) => {
      for (const [ti, end] of trims) ca.addAction(ti.createSetEndAction(ppro.TickTime.createWithSeconds(end)));
    });
  }
  const lanes = Math.max(...todo.map((it) => it.lane)) + 1;
  setStatus(`✓ ${todo.length} illustrations sur V${baseV + 1}${lanes > 1 ? "–V" + (baseV + lanes) : ""}`, "ok");
}

async function remove() {
  $("log").textContent = "";
  const st = await bridge("/status");
  const project = await ppro.Project.getActiveProject();
  const seq = project && await project.getActiveSequence();
  if (!seq) throw new Error("ouvrez la séquence du montage dans la timeline");
  const { ours } = await readSequence(seq, st.export_dir);
  removeOurs(project, seq, ours);
  setStatus(`✓ ${ours.length} illustration(s) retirée(s)`, "ok");
}

function button(id, job) {
  $(id).addEventListener("click", async () => {
    $("place").disabled = $("remove").disabled = true;
    try {
      await job();
    } catch (e) {
      setStatus(String(e.message || e), "err");
      log(String(e.stack || e), "err");
    } finally {
      $("place").disabled = $("remove").disabled = false;
    }
  });
}

async function refresh() {
  try {
    const st = await bridge("/status");
    setStatus(`${st.title} — ${st.files} fichier(s) exporté(s)` + (st.derush ? "" : " · pas de derush indiqué"));
  } catch (e) {
    setStatus(String(e.message || e), "err");
  }
}

button("place", place);
button("remove", remove);
refresh();
document.addEventListener("uxpcommand", refresh);
