// rx mobile: site visits (pre-burn recce etc). Everything is saved on the phone first (IndexedDB)
// and sent to the server when there is a connection. Ids are made here, so resending is safe.
const V = { db: null, active: null, recce: [], fix: null, watch: null, layer: null, syncing: false, pending: 0, serverRecords: null };

const FUEL_CLASSES = [["mixed_grass", "Mixed-grass"], ["grass_juniper", "Grass + juniper"], ["juniper", "Juniper-dominant"], ["aspen", "Aspen"], ["shrub", "Shrub"], ["other", "Other"]];
const VISIT_KINDS = [["pre_burn_recce", "Pre-burn recce"], ["burn_day", "Burn day"], ["post_burn", "Post-burn"], ["monitoring", "Monitoring"], ["fuel_survey", "Fuel survey"], ["other", "Other"]];
const HAZARDS = ["UXO / suspected UXO", "Snag / dead trees", "Structure", "Power line", "Fence / wire", "Washout / soft ground", "Steep slope", "Other"];
const KIND_STYLE = { note: ["#1f6fb2", "N"], photo: ["#455a64", "P"], fuel_plot: ["#7a8b3a", "F"], check: ["#2e7d32", "✓"], hazard: ["#b3261e", "!"], water: ["#1f6fb2", "W"], access: ["#6d4c41", "A"] };

// --- storage ------------------------------------------------------------------------
function idb() {
  if (V.db) return Promise.resolve(V.db);
  return new Promise((res, rej) => {
    const r = indexedDB.open("rx-field", 1);
    r.onupgradeneeded = () => {
      const d = r.result;
      d.createObjectStore("visits", { keyPath: "id" });
      d.createObjectStore("records", { keyPath: "id" }).createIndex("visit", "visit_id");
      d.createObjectStore("photos", { keyPath: "id" }).createIndex("record", "record_id");
    };
    r.onsuccess = () => res((V.db = r.result));
    r.onerror = () => rej(r.error);
  });
}
async function put(store, obj) { const d = await idb(); return new Promise((res, rej) => { const t = d.transaction(store, "readwrite"); t.objectStore(store).put(obj); t.oncomplete = res; t.onerror = () => rej(t.error); }); }
async function getAll(store, index, key) {
  const d = await idb();
  return new Promise((res, rej) => { const os = d.transaction(store).objectStore(store); const q = index ? os.index(index).getAll(key) : os.getAll(); q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); });
}
async function del(store, key) { const d = await idb(); return new Promise((res) => { const t = d.transaction(store, "readwrite"); t.objectStore(store).delete(key); t.oncomplete = res; }); }
const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => { const r = (Math.random() * 16) | 0; return (c === "x" ? r : (r & 3) | 8).toString(16); }));

// --- GPS ---------------------------------------------------------------------------------
function startGps() {
  if (V.watch !== null || !navigator.geolocation) return;
  V.watch = navigator.geolocation.watchPosition((p) => {
    V.fix = { lat: p.coords.latitude, lon: p.coords.longitude, acc: Math.round(p.coords.accuracy), heading: p.coords.heading, t: Date.now() };
    document.querySelectorAll(".gps-line").forEach(gpsLine);
  }, (e) => { V.fix = null; document.querySelectorAll(".gps-line").forEach((el) => (el.textContent = "No GPS: " + e.message)); },
  { enableHighAccuracy: true, maximumAge: 3000, timeout: 20000 });
}
function stopGps() { if (V.watch !== null) navigator.geolocation.clearWatch(V.watch); V.watch = null; }
function gpsLine(el) {
  if (!V.fix) { el.textContent = "Waiting for GPS…"; el.className = "gps-line wait"; return; }
  const age = Math.round((Date.now() - V.fix.t) / 1000);
  el.textContent = `GPS ±${V.fix.acc} m${age > 15 ? ` (${age}s old)` : ""} · ${V.fix.lat.toFixed(5)}, ${V.fix.lon.toFixed(5)}`;
  el.className = "gps-line " + (V.fix.acc <= 10 ? "good" : V.fix.acc <= 30 ? "ok" : "poor");
}

// --- photos: shrink on the phone before storing ----------------------------------------
async function shrink(file) {
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
    const s = Math.min(1, 2560 / Math.max(bmp.width, bmp.height));
    const cv = document.createElement("canvas"); cv.width = Math.round(bmp.width * s); cv.height = Math.round(bmp.height * s);
    cv.getContext("2d").drawImage(bmp, 0, 0, cv.width, cv.height);
    return await new Promise((res) => cv.toBlob(res, "image/jpeg", 0.85));
  } catch (_) { return file; }
}

// --- sync -----------------------------------------------------------------------------------
async function sync() {
  if (V.syncing || !navigator.onLine) return countPending();
  V.syncing = true;
  try {
    for (const v of (await getAll("visits")).filter((x) => !x.synced)) {
      await RX.api("/api/visits", { method: "POST", body: v }); v.synced = true; await put("visits", v);
    }
    for (const r of (await getAll("records")).filter((x) => !x.synced)) {
      const out = await RX.api(`/api/visits/${r.visit_id}/records`, { method: "POST", body: r });
      r.synced = true; r.data = out.data || r.data; await put("records", r);
    }
    for (const p of (await getAll("photos")).filter((x) => !x.synced)) {
      const fd = new FormData(); fd.append("file", p.blob, "photo.jpg"); fd.append("media_id", p.id); fd.append("taken_at", p.taken_at);
      const r = await fetch(`/api/records/${p.record_id}/media`, { method: "POST", body: fd, credentials: "same-origin" });
      if (!r.ok) throw new Error("photo upload " + r.status);
      p.synced = true; await put("photos", p);
    }
  } catch (e) { console.warn("sync paused:", e.message); }
  finally { V.syncing = false; }
  return countPending();
}
async function countPending() {
  const n = (await getAll("visits")).filter((x) => !x.synced).length + (await getAll("records")).filter((x) => !x.synced).length + (await getAll("photos")).filter((x) => !x.synced).length;
  V.pending = n;
  document.querySelectorAll(".sync-state").forEach((el) => { el.textContent = n ? `${n} waiting to send` : "All sent"; el.className = "sync-state " + (n ? "wait" : "done"); });
  return n;
}
window.addEventListener("online", sync);
setInterval(sync, 30000);

// --- visits -------------------------------------------------------------------------------
async function loadActive() {
  const id = localStorage.getItem("rx.activeVisit");
  V.active = id ? (await getAll("visits")).find((v) => v.id === id) || null : null;
  if (V.active) startGps();
}
async function startVisit(form) {
  const v = { id: uuid(), plan_id: M.bundle ? M.bundle.plan.id : null, kind: form.kind.value, title: form.title.value || null,
    crew: form.crew.value || null, weather: form.weather.value || null, notes: null, started_at: new Date().toISOString(), ended_at: null, synced: false };
  await put("visits", v); localStorage.setItem("rx.activeVisit", v.id); V.active = v; startGps(); sync(); Visit.render();
}
async function endVisit() {
  if (!confirm("End this site visit? You can still see it in the plan's visit list.")) return;
  V.active.ended_at = new Date().toISOString(); V.active.notes = document.getElementById("vnotes")?.value || V.active.notes; V.active.synced = false;
  await put("visits", V.active); localStorage.removeItem("rx.activeVisit"); V.active = null; stopGps(); sync(); Visit.render();
}

// --- records ----------------------------------------------------------------------------------
async function saveRecord(rec, files) {
  const f = V.fix;
  const r = { id: uuid(), visit_id: V.active.id, observed_at: new Date().toISOString(), lat: f ? f.lat : null, lon: f ? f.lon : null,
    accuracy_m: f ? f.acc : null, heading_deg: f && f.heading != null ? Math.round(f.heading) : null, synced: false, data: {}, ...rec };
  await put("records", r);
  for (const file of files || []) {
    await put("photos", { id: uuid(), record_id: r.id, blob: await shrink(file), taken_at: new Date(file.lastModified || Date.now()).toISOString(), synced: false });
  }
  sync().then(() => Visit.render()); Visit.render(); drawRecords();
  return r;
}

async function drawRecords() {
  if (V.layer) M.map.removeLayer(V.layer);
  V.layer = L.layerGroup().addTo(M.map);
  const local = V.active ? await getAll("records", "visit", V.active.id) : [];
  const seen = new Set(local.map((r) => r.id));
  const server = (V.serverRecords?.features || []).filter((f) => !seen.has(f.id) && f.geometry).map((f) => ({ ...f.properties, lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1] }));
  for (const r of [...local, ...server]) {
    if (r.lat == null) continue;
    const [col, sym] = KIND_STYLE[r.kind] || ["#555", "•"];
    const color = r.kind === "check" && r.status === "issue" ? "#b3261e" : col;
    L.marker([r.lat, r.lon], { icon: L.divIcon({ className: "rx-pt", html: `<span style="background:${color}">${sym}</span>`, iconSize: null }) })
      .bindPopup(`<b>${RX.esc(recTitle(r))}</b><br>${RX.esc(r.text || "")}<br><span style="color:#666">${(r.observed_at || "").slice(0, 16).replace("T", " ")}</span>`).addTo(V.layer);
  }
}
const recTitle = (r) => r.kind === "check" ? (V.recce.find((i) => i.key === r.item)?.label.split(":")[0] || r.item) + (r.status ? ` · ${r.status}` : "")
  : r.kind === "fuel_plot" ? `Fuel plot ${r.data?.plot_code || ""} · ${r.data?.load_kg_m2 ?? "?"} kg/m²` : r.kind === "hazard" ? `Hazard: ${r.item || ""}` : r.kind[0].toUpperCase() + r.kind.slice(1).replace("_", " ");

// --- capture sheet ------------------------------------------------------------------------------
function openCapture(kind, opts = {}) {
  const wrap = document.getElementById("capture");
  const photoField = `<div class="field"><label for="cph">Photos</label><input id="cph" type="file" accept="image/*" capture="environment" multiple>
    <span class="hint">Opens the camera. Add more from the gallery by tapping again.</span><div id="cpprev" class="thumbs"></div></div>`;
  let body = "";
  if (kind === "note" || kind === "photo") body = `<div class="field"><label for="ctx">${kind === "photo" ? "Caption" : "Note"}</label><textarea id="ctx"></textarea></div>`;
  if (kind === "check") body = `<p style="margin:0 0 8px"><b>${RX.esc(opts.label)}</b></p>
    <div class="seg" role="radiogroup" aria-label="Result">${["ok", "issue", "n/a"].map((s) => `<label><input type="radio" name="cst" value="${s}" ${s === (opts.status || "ok") ? "checked" : ""}><span>${s === "ok" ? "OK" : s === "issue" ? "Issue" : "N/A"}</span></label>`).join("")}</div>
    <div class="field"><label for="ctx">Notes</label><textarea id="ctx" placeholder="What did you find? What needs doing?"></textarea></div>`;
  if (kind === "hazard") body = `<div class="field"><label for="chz">Hazard</label><select id="chz">${HAZARDS.map((h) => `<option>${h}</option>`).join("")}</select></div>
    <div class="field"><label for="ctx">Description</label><textarea id="ctx"></textarea></div>`;
  if (kind === "fuel_plot") {
    const n = (Number(localStorage.getItem("rx.plotN") || 0) + 1);
    body = `<div class="grid2"><div class="field"><label for="fpc">Plot code</label><input id="fpc" value="R${n}"></div>
      <div class="field"><label for="ffc">Fuel class</label><select id="ffc">${FUEL_CLASSES.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select></div></div>
      <div class="seg" role="radiogroup" aria-label="Method"><label><input type="radio" name="fm" value="clip" checked><span>Clip &amp; weigh</span></label><label><input type="radio" name="fm" value="visual"><span>Visual estimate</span></label></div>
      <div id="fclip"><div class="grid2"><div class="field"><label for="ffr">Frame area m²</label><input id="ffr" type="number" step="0.01" inputmode="decimal" value="0.25"></div>
        <div class="field"><label for="fwg">Wet weight g</label><input id="fwg" type="number" step="0.1" inputmode="decimal"></div>
        <div class="field"><label for="fmc">Moisture % (dry basis)</label><input id="fmc" type="number" step="1" inputmode="decimal" placeholder="if known"></div>
        <div class="field"><label for="fdg">Oven-dry weight g</label><input id="fdg" type="number" step="0.1" inputmode="decimal" placeholder="later, if dried"></div></div></div>
      <div id="fvis" hidden><div class="field"><label for="fld">Estimated load kg/m²</label><input id="fld" type="number" step="0.05" inputmode="decimal"></div></div>
      <div class="loadout" id="fout">Load: —</div>
      <div class="grid2"><div class="field"><label for="fcu">Curing %</label><input id="fcu" type="number" min="0" max="100" inputmode="numeric"></div>
        <div class="field"><label for="fht">Height cm</label><input id="fht" type="number" inputmode="numeric"></div>
        <div class="field"><label for="fcv">Cover %</label><input id="fcv" type="number" min="0" max="100" inputmode="numeric"></div>
        <div class="field"><label for="fjp">Juniper %</label><input id="fjp" type="number" min="0" max="100" inputmode="numeric"></div>
        <div class="field"><label for="flt">Litter depth cm</label><input id="flt" type="number" step="0.5" inputmode="decimal"></div>
        <div class="field"><label for="fco">Continuity</label><select id="fco"><option value="">—</option><option>continuous</option><option>patchy</option><option>sparse</option></select></div></div>
      <div class="field"><label for="ctx">Notes</label><textarea id="ctx"></textarea></div>`;
  }
  const titles = { note: "Note", photo: "Photo point", check: "Recce check", hazard: "Hazard", fuel_plot: "Fuel plot" };
  wrap.innerHTML = `<div class="cap-card" role="dialog" aria-modal="true" aria-labelledby="capt"><div class="cap-head"><h3 id="capt">${titles[kind]}</h3>
    <button type="button" class="btn small" id="capx">Cancel</button></div><div class="gps-line"></div>${body}${photoField}
    <button type="button" class="btn primary" id="caps" style="width:100%;min-height:48px;justify-content:center">Save</button></div>`;
  wrap.hidden = false;
  wrap.querySelectorAll(".gps-line").forEach(gpsLine);
  const files = [];
  document.getElementById("cph").onchange = (e) => {
    for (const f of e.target.files) { files.push(f); const u = URL.createObjectURL(f); document.getElementById("cpprev").insertAdjacentHTML("beforeend", `<img src="${u}" alt="">`); }
    e.target.value = "";
  };
  const $ = (id) => document.getElementById(id);
  if (kind === "fuel_plot") {
    const calc = () => {
      const vis = document.querySelector('input[name="fm"]:checked').value === "visual";
      $("fclip").hidden = vis; $("fvis").hidden = !vis;
      let load = null; const fr = +$("ffr").value;
      if (vis) load = $("fld").value === "" ? null : +$("fld").value;
      else if ($("fdg").value !== "" && fr > 0) load = +$("fdg").value / 1000 / fr;
      else if ($("fwg").value !== "" && $("fmc").value !== "" && fr > 0) load = +$("fwg").value / (1 + +$("fmc").value / 100) / 1000 / fr;
      $("fout").textContent = load == null ? (vis ? "Load: enter an estimate" : "Load: needs dry weight, or wet weight + moisture (wet weight alone is kept)") : `Load: ${load.toFixed(2)} kg/m²`;
      return load;
    };
    wrap.querySelectorAll("input,select").forEach((i) => i.addEventListener("input", calc)); calc();
  }
  $("capx").onclick = () => (wrap.hidden = true);
  $("caps").onclick = async () => {
    if (!V.fix && !confirm("No GPS position yet. Save without a location?")) return;
    const txt = $("ctx") ? $("ctx").value : null;
    let rec = { kind, text: txt };
    if (kind === "check") rec = { ...rec, item: opts.key, status: document.querySelector('input[name="cst"]:checked').value };
    if (kind === "hazard") rec = { ...rec, item: $("chz").value, status: "issue" };
    if (kind === "fuel_plot") {
      const num = (id) => ($(id).value === "" ? null : +$(id).value);
      const vis = document.querySelector('input[name="fm"]:checked').value === "visual";
      rec.data = { plot_code: $("fpc").value, fuel_class: $("ffc").value, method: vis ? "visual" : "clip", frame_m2: vis ? null : num("ffr"),
        wet_g: vis ? null : num("fwg"), moisture_pct: vis ? null : num("fmc"), dry_g: vis ? null : num("fdg"), load_kg_m2: vis ? num("fld") : null,
        curing_pct: num("fcu"), height_cm: num("fht"), cover_pct: num("fcv"), juniper_pct: num("fjp"), litter_cm: num("flt"), continuity: $("fco").value || null };
      localStorage.setItem("rx.plotN", String(Number(localStorage.getItem("rx.plotN") || 0) + 1));
    }
    $("caps").disabled = true;
    await saveRecord(rec, files); wrap.hidden = true;
  };
}

// --- the Visit tab ------------------------------------------------------------------------------
const Visit = {
  async init() {
    try { V.recce = await RX.api("/api/field/recce-items"); localStorage.setItem("rx.recce", JSON.stringify(V.recce)); }
    catch (_) { V.recce = JSON.parse(localStorage.getItem("rx.recce") || "[]"); }
    await loadActive(); sync();
  },
  async planChanged() {
    V.serverRecords = null;
    if (M.bundle) { try { V.serverRecords = await RX.api(`/api/plans/${M.bundle.plan.id}/visit-records`); } catch (_) {} }
    drawRecords();
  },
  async render() {
    const el = document.getElementById("mpanel");
    if (!el || M.tab !== "visit") return;
    if (!V.active) {
      el.innerHTML = `<p class="hint">Record what you find on the ground before a burn (or after it): checks against the plan, photos, hazards and fuel plots.
        Everything saves on the phone first and is sent when you have a signal.</p>
        <form id="vstart"><div class="field"><label for="vk">Visit type</label><select id="vk" name="kind">${VISIT_KINDS.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select></div>
        <div class="field"><label for="vt">Title (optional)</label><input id="vt" name="title" placeholder="${M.bundle ? RX.esc(M.bundle.plan.name) + " recce" : ""}"></div>
        <div class="field"><label for="vc">Crew</label><input id="vc" name="crew" placeholder="Names"></div>
        <div class="field"><label for="vw">Weather</label><input id="vw" name="weather" placeholder="Sky, wind, temperature"></div>
        <button class="btn primary" style="width:100%;min-height:48px;justify-content:center">Start site visit${M.bundle ? " for " + RX.esc(M.bundle.plan.name) : ""}</button></form>
        <p class="sync-state"></p>${await pastVisits()}`;
      document.getElementById("vstart").onsubmit = (e) => { e.preventDefault(); startVisit(e.target); };
      countPending(); return;
    }
    const recs = (await getAll("records", "visit", V.active.id)).sort((a, b) => b.observed_at.localeCompare(a.observed_at));
    const photos = await getAll("photos");
    const checks = {}; recs.filter((r) => r.kind === "check").forEach((r) => { if (!checks[r.item] || checks[r.item].observed_at < r.observed_at) checks[r.item] = r; });
    const kindLabel = (VISIT_KINDS.find(([k]) => k === V.active.kind) || [, ""])[1];
    el.innerHTML = `<div class="visit-head"><div><b>${RX.esc(kindLabel)}</b> · started ${V.active.started_at.slice(11, 16)}<div class="gps-line"></div></div>
        <button class="btn small" id="vend">End visit</button></div>
      <p class="sync-state"></p>
      <div class="quick">${[["photo", "Photo"], ["note", "Note"], ["fuel_plot", "Fuel plot"], ["hazard", "Hazard"]].map(([k, l]) => `<button class="btn" data-cap="${k}">${l}</button>`).join("")}</div>
      ${V.active.kind === "pre_burn_recce" || V.active.kind === "burn_day" ? `<h4>Recce checklist <span class="hint">${Object.keys(checks).length} of ${V.recce.length} done</span></h4>
      ${V.recce.map((i) => { const c = checks[i.key]; return `<div class="chk"><span class="lbl">${RX.esc(i.label)}${c && c.text ? `<br><span class="hint">${RX.esc(c.text)}</span>` : ""}</span>
        <span class="chk-btns"><button class="btn small ${c?.status === "ok" ? "is-ok" : ""}" data-chk="${i.key}" data-st="ok" aria-label="${RX.esc(i.label)}: OK">OK</button>
        <button class="btn small ${c?.status === "issue" ? "is-issue" : ""}" data-chk="${i.key}" data-st="issue" aria-label="${RX.esc(i.label)}: issue">Issue</button></span></div>`; }).join("")}` : ""}
      <h4>Records (${recs.length})</h4>
      ${recs.map((r) => { const ph = photos.filter((p) => p.record_id === r.id); return `<div class="rec"><span class="dot ${r.synced && ph.every((p) => p.synced) ? "complete" : "draft"}" title="${r.synced ? "sent" : "waiting to send"}"></span>
        <div class="lbl"><b>${RX.esc(recTitle(r))}</b> <span class="hint">${r.observed_at.slice(11, 16)}${r.accuracy_m ? ` · ±${r.accuracy_m} m` : " · no GPS"}</span>
        ${r.text ? `<div>${RX.esc(r.text)}</div>` : ""}<div class="thumbs">${ph.map((p) => `<img data-ph="${p.id}" alt="">`).join("")}</div></div></div>`; }).join("") || '<p class="hint">Nothing recorded yet.</p>'}
      <div class="field" style="margin-top:12px"><label for="vnotes">Visit notes</label><textarea id="vnotes">${RX.esc(V.active.notes || "")}</textarea></div>`;
    el.querySelectorAll(".gps-line").forEach(gpsLine); countPending();
    for (const img of el.querySelectorAll("img[data-ph]")) { const p = photos.find((x) => x.id === img.dataset.ph); if (p) img.src = URL.createObjectURL(p.blob); }
    document.getElementById("vend").onclick = endVisit;
    el.querySelectorAll("[data-cap]").forEach((b) => (b.onclick = () => openCapture(b.dataset.cap)));
    el.querySelectorAll("[data-chk]").forEach((b) => (b.onclick = () => {
      const item = V.recce.find((i) => i.key === b.dataset.chk);
      if (b.dataset.st === "ok") saveRecord({ kind: "check", item: item.key, status: "ok", text: null });
      else openCapture("check", { key: item.key, label: item.label, status: "issue" });
    }));
    document.getElementById("vnotes").onchange = async (e) => { V.active.notes = e.target.value; V.active.synced = false; await put("visits", V.active); sync(); };
  },
};

async function pastVisits() {
  if (!M.bundle) return "";
  let vs = [];
  try { vs = await RX.api(`/api/visits?plan_id=${M.bundle.plan.id}`); } catch (_) { return ""; }
  if (!vs.length) return "";
  return `<h4>Earlier visits for this plan</h4>` + vs.map((v) => `<div class="feat"><span class="lbl">${RX.esc((VISIT_KINDS.find(([k]) => k === v.kind) || [, v.kind])[1])} · ${v.started_at.slice(0, 10)}<br>
    <span class="hint">${RX.esc(v.crew || "")} · ${v.n_records} records, ${v.n_photos} photos${v.n_issues ? `, <b style="color:var(--bad)">${v.n_issues} issue${v.n_issues > 1 ? "s" : ""}</b>` : ""}</span></span></div>`).join("");
}
