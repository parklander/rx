// rx mobile review: read-only map and plan in the field. Keeps the last plan for offline use.
const M = { plans: [], bundle: null, layers: [], map: null, planLayer: null, overlayLayer: null, land: {}, me: null, watch: null, tab: "summary" };
const esc = RX.esc;
const store = {
  get: (k) => { try { return JSON.parse(localStorage.getItem(k)); } catch (_) { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) {} },
};

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

M.map = L.map("mmap", { zoomControl: false });
const bm = RX.basemaps(); bm["Imagery"].addTo(M.map);
M.map.setView([49.75, -99.5], 11);

async function boot() {
  try {
    await RX.api("/api/me");
    [M.plans, M.layers] = await Promise.all([RX.api("/api/plans"), RX.api("/api/layers")]);
    store.set("rx.plans", M.plans); store.set("rx.layers", M.layers);
  } catch (e) {
    if (e.status === 401) return showLogin();
    M.plans = store.get("rx.plans") || []; M.layers = store.get("rx.layers") || [];
    document.getElementById("net").hidden = false;
  }
  const pick = document.getElementById("plan-pick");
  pick.innerHTML = `<option value="all">Burn program: all blocks</option>` + M.plans.map((p) => `<option value="${p.id}">${esc(p.name)} · v${p.version_no} · ${p.status}</option>`).join("");
  const want = location.hash.slice(1) || store.get("rx.lastPlan") || "all";
  pick.value = String(want); if (!pick.value) pick.value = "all";
  pick.onchange = () => (pick.value === "all" ? loadProgram() : loadPlan(+pick.value));
  buildLayerPanel();
  await Visit.init();
  pick.value === "all" ? loadProgram() : loadPlan(+pick.value);
}

function showLogin() {
  const d = document.getElementById("mlogin"); d.hidden = false;
  Object.assign(d.style, { position: "fixed", inset: 0, background: "var(--bg)", zIndex: 2000 });
  d.innerHTML = `<form class="login" id="lf"><h2>Sign in</h2><p>rx plan review</p>
    <div class="field"><label for="u">Username</label><input id="u" autocomplete="username" required></div>
    <div class="field"><label for="p">Password</label><input id="p" type="password" autocomplete="current-password" required></div>
    <div class="err" id="le" role="alert"></div><button class="btn primary" style="width:100%;min-height:44px">Sign in</button></form>`;
  document.getElementById("lf").onsubmit = async (e) => {
    e.preventDefault();
    try { await RX.api("/api/login", { method: "POST", body: { username: u.value, password: p.value } }); d.hidden = true; boot(); }
    catch (err) { document.getElementById("le").textContent = err.message; }
  };
}

// The whole program: every burn block, tap one to open its plan.
async function loadProgram() {
  store.set("rx.lastPlan", "all"); history.replaceState(null, "", "/m#all");
  let fc;
  try { fc = await RX.api("/api/blocks"); store.set("rx.blocks", fc); document.getElementById("net").hidden = true; }
  catch (e) { if (e.status === 401) return showLogin(); fc = store.get("rx.blocks"); document.getElementById("net").hidden = false; if (!fc) return; }
  M.bundle = null;
  if (M.planLayer) M.map.removeLayer(M.planLayer);
  if (M.prepLayer) { M.map.removeLayer(M.prepLayer); M.prepLayer = null; }
  const COL = { draft: "#9e9e9e", review: "#e0a100", approved: "#2e7d32", implemented: "#1565c0", closed: "#6d4c41" };
  M.planLayer = L.geoJSON(fc, { style: (f) => ({ color: "#111", weight: 2, fillColor: COL[f.properties.status] || "#999", fillOpacity: 0.45 }),
    onEachFeature: (f, l) => { l.bindTooltip(esc(f.properties.name), { permanent: true, direction: "center", className: "block-label" });
      l.on("click", () => { document.getElementById("plan-pick").value = f.properties.id; loadPlan(f.properties.id); }); } }).addTo(M.map);
  fitToSheet(M.planLayer.getBounds());
  document.getElementById("mtabs").innerHTML = `<button role="tab" aria-selected="true">Burn blocks</button>`;
  const el = document.getElementById("mpanel");
  el.innerHTML = `<p class="hint">Tap a block on the map or below to open its plan.</p>` + fc.features.map((f) => { const p = f.properties; return `<div class="block-row" data-id="${p.id}" role="button" tabindex="0">
    <div class="br-top"><span class="sw" style="background:${COL[p.status]}"></span><b>${esc(p.name)}</b><span class="spacer"></span><span class="badge ${p.status}">${p.status}</span></div>
    <div class="br-meta">${p.area_ha} ha · ${esc(p.planned_window || "")} · last fire ${p.last_fire || "none on record"}</div></div>`; }).join("");
  el.querySelectorAll(".block-row").forEach((r) => (r.onclick = () => { document.getElementById("plan-pick").value = r.dataset.id; loadPlan(+r.dataset.id); }));
}

async function loadPlan(id) {
  store.set("rx.lastPlan", id); history.replaceState(null, "", `/m#${id}`);
  try {
    M.bundle = await RX.api(`/api/plans/${id}/bundle`);
    store.set(`rx.bundle.${id}`, M.bundle); document.getElementById("net").hidden = true;
  } catch (e) {
    if (e.status === 401) return showLogin();
    M.bundle = store.get(`rx.bundle.${id}`);
    document.getElementById("net").hidden = false;
    document.getElementById("net").textContent = M.bundle ? `Offline copy · ${M.bundle.fetched_at.slice(0, 16).replace("T", " ")}` : "Offline: plan not saved on this device";
    if (!M.bundle) return;
  }
  if (M.planLayer) M.map.removeLayer(M.planLayer);
  M.planLayer = RX.featureLayer(M.bundle.features).addTo(M.map);
  if (M.prepLayer) M.map.removeLayer(M.prepLayer);
  M.prepLayer = M.bundle.prep ? Visit.prepLayer(M.bundle.prep).addTo(M.map) : null;
  fitToSheet(M.planLayer.getBounds());
  renderTabs(); renderPanel(); Visit.planChanged();
}

function fitToSheet(b, maxZoom) {
  if (!b.isValid()) return;
  const sh = document.getElementById("sheet").offsetHeight;
  M.map.fitBounds(b, { paddingTopLeft: [16, 16], paddingBottomRight: [72, sh + 16], maxZoom });
}

// --- layers ---------------------------------------------------------------------
function buildLayerPanel() {
  const d = document.getElementById("layers");
  d.innerHTML = `<div class="sec">Basemap</div>${Object.keys(bm).map((k, i) => `<label><input type="radio" name="bm" value="${k}" ${i === 0 ? "checked" : ""}> ${k}</label>`).join("")}
    <div class="sec">Plan</div><label><input type="checkbox" id="ov" > Values in unit + contingency</label>
    ${M.layers.some((l) => l.kind === "raster") ? `<div class="sec">Terrain</div>${M.layers.filter((l) => l.kind === "raster").map((l) => `<label><input type="checkbox" data-layer="${l.name}"> ${esc(l.title)}</label>`).join("")}` : ""}
    <div class="sec">Landscape</div>${M.layers.filter((l) => l.visible && l.kind === "state").map((l) => `<label><input type="checkbox" data-layer="${l.name}"> ${esc(l.title)}${RX.layerNote(l)}</label>`).join("")}`;
  d.querySelectorAll('input[name="bm"]').forEach((r) => (r.onchange = () => { Object.values(bm).forEach((x) => M.map.removeLayer(x)); bm[r.value].addTo(M.map).bringToBack(); }));
  d.querySelector("#ov").onchange = (e) => {
    if (M.overlayLayer) { M.map.removeLayer(M.overlayLayer); M.overlayLayer = null; }
    if (e.target.checked && M.bundle) {
      M.overlayLayer = L.geoJSON(M.bundle.overlay.features.filter((f) => f.properties.layer !== "fuels.fuel_class"), {
        style: { color: "#00bcd4", weight: 2, fillOpacity: 0.08 },
        pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 7, color: "#00838f", fillColor: "#00e5ff", fillOpacity: 0.9, weight: 2 }),
        onEachFeature: (f, l) => { const p = f.properties; l.bindPopup(`<b>${esc(p.name || p.species || p.kind || p.layer)}</b><br>${esc(p.layer)} · ${p.zone}`); },
      }).addTo(M.map);
    }
  };
  d.querySelectorAll("input[data-layer]").forEach((c) => (c.onchange = async () => {
    const n = c.dataset.layer;
    if (M.land[n]) { M.map.removeLayer(M.land[n]); delete M.land[n]; }
    if (!c.checked) return;
    const meta = M.layers.find((l) => l.name === n);
    if (meta.kind === "raster") { M.land[n] = RX.rasterLayer(meta).addTo(M.map); return; }
    const b = M.map.getBounds().pad(0.5);
    try {
      const fc = await RX.api(`/api/layers/${n}?bbox=${[b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((v) => v.toFixed(4)).join(",")}`);
      M.land[n] = RX.landscapeLayer(meta, fc).addTo(M.map); if (M.planLayer) M.planLayer.bringToFront();
    } catch (e) { c.checked = false; alert("This layer needs a connection."); }
  }));
  const btn = document.getElementById("layers-btn");
  btn.onclick = () => { d.hidden = !d.hidden; btn.setAttribute("aria-expanded", String(!d.hidden)); btn.classList.toggle("on", !d.hidden); };
}

// --- location ---------------------------------------------------------------------
document.getElementById("locate").onclick = (e) => {
  const b = e.currentTarget;
  if (M.watch !== null) { navigator.geolocation.clearWatch(M.watch); M.watch = null; b.classList.remove("on"); if (M.me) { M.map.removeLayer(M.me); M.me = null; } return; }
  if (!navigator.geolocation) return alert("Location is not available on this device.");
  b.classList.add("on"); let first = true;
  M.watch = navigator.geolocation.watchPosition((pos) => {
    const ll = [pos.coords.latitude, pos.coords.longitude];
    if (!M.me) M.me = L.layerGroup([L.circle(ll, { radius: pos.coords.accuracy, weight: 1, fillOpacity: 0.1 }), L.marker(ll, { icon: L.divIcon({ className: "", html: '<div class="me-dot"></div>', iconSize: [16, 16] }) })]).addTo(M.map);
    else M.me.eachLayer((l) => { l.setLatLng(ll); if (l.setRadius) l.setRadius(pos.coords.accuracy); });
    if (first) { M.map.setView(ll, Math.max(M.map.getZoom(), 15)); first = false; }
  }, (err) => { alert("Location: " + err.message); b.classList.remove("on"); M.watch = null; }, { enableHighAccuracy: true, maximumAge: 5000 });
};

// --- bottom sheet -------------------------------------------------------------------
const sheet = document.getElementById("sheet");
document.getElementById("grip").onclick = () => {
  sheet.classList.contains("full") ? (sheet.classList.remove("full"), sheet.classList.add("min"))
    : sheet.classList.contains("min") ? sheet.classList.remove("min") : sheet.classList.add("full");
};
const MTABS = [["summary", "Summary"], ["visit", "Site visit"], ["prep", "Prep work"], ["ignition", "Ignition"], ["values", "Values"], ["elements", "Plan elements"], ["burn", "Burn days"]];
function renderTabs() {
  const n = document.getElementById("mtabs");
  n.innerHTML = MTABS.map(([k, l]) => `<button role="tab" aria-selected="${M.tab === k}" data-t="${k}">${l}</button>`).join("");
  n.querySelectorAll("button").forEach((b) => (b.onclick = () => { M.tab = b.dataset.t; renderTabs(); renderPanel(); }));
}
function renderPanel() {
  if (M.tab === "visit") return Visit.render();
  if (M.tab === "prep") return Visit.renderPrep();
  const p = M.bundle.plan, el = document.getElementById("mpanel");
  const rng = (r) => r.low != null && r.high != null ? `${r.low}–${r.high}` : r.low != null ? `≥ ${r.low}` : r.high != null ? `≤ ${r.high}` : "—";
  if (M.tab === "summary") {
    const unit = M.bundle.features.features.filter((f) => f.properties.kind === "burn_unit").reduce((a, f) => a + (f.properties.area_ha || 0), 0);
    el.innerHTML = `<h3 style="margin:4px 0">${esc(p.name)} ${p.demo ? '<span class="badge demo">DEMO</span>' : ""}</h3>
      <div class="kv"><b>Status</b><span><span class="badge ${p.status}">${p.status}</span> · v${p.version_no}</span>
      <b>Units</b><span>${esc(p.unit_name || "—")}</span><b>Area</b><span>${unit.toFixed(1)} ha</span>
      <b>Complexity</b><span>${esc(p.complexity || "—")} · ${esc(p.min_burn_boss || "")}</span><b>Window</b><span>${esc(p.planned_window || "—")}</span>
      <b>Data as of</b><span>${p.as_of ? p.as_of.slice(0, 16).replace("T", " ") : "live (draft)"}</span></div>
      <h4>Prescription</h4><table class="grid">${p.prescription.map((r) => `<tr><td>${esc(RX.PARAMS[r.param] || r.param)}</td><td class="num">${rng(r)}</td></tr>`).join("")}</table>
      <h4>Map key</h4>${Object.entries(RX.KINDS).filter(([k]) => M.bundle.features.features.some((f) => f.properties.kind === k)).map(([k, v]) => `<div class="feat"><span class="sw" style="background:${v.color}"></span><span class="lbl">${v.label}</span></div>`).join("")}`;
  } else if (M.tab === "ignition") {
    el.innerHTML = p.variants.map((v) => `<h4>${esc(v.name)} <span class="hint">wind from ${v.wind_dir_min}–${v.wind_dir_max}°</span></h4><p class="hint">${esc(v.description || "")}</p>
      ${(v.firing_sequence || []).map((s, i) => `<div class="step"><b>${i + 1}</b><span>${esc(s.step)}</span></div>`).join("")}`).join("") || '<p class="hint">No ignition variants.</p>';
    const e15 = p.elements["15"]; if (e15) el.innerHTML += `<h4>Element 15 notes</h4><p style="white-space:pre-wrap;font-size:14px">${esc(Object.values(e15.content).join("\n\n"))}</p>`;
  } else if (M.tab === "values") {
    const fs = M.bundle.overlay.features.filter((f) => f.properties.layer !== "fuels.fuel_class");
    el.innerHTML = `<h4>Fuels (ha)</h4><table class="grid"><tr><th>Class</th><th class="num">Unit</th><th class="num">Contingency</th></tr>
      ${M.bundle.overlay.fuels.map((f) => `<tr><td>${esc(f.fuel_class)}</td><td class="num">${f.unit_ha ?? 0}</td><td class="num">${f.contingency_ha ?? 0}</td></tr>`).join("")}</table>
      <h4>Values</h4>${fs.map((f, i) => { const q = f.properties; return `<div class="feat"><span class="lbl">${esc(q.name || q.species || q.kind)}<br><span class="hint">${esc(q.layer)}</span></span>
        <span class="badge ${q.zone === "unit" ? "review" : "draft"}">${q.zone}</span><button class="btn small" data-i="${i}">Map</button></div>`; }).join("") || '<p class="hint">Nothing recorded.</p>'}`;
    el.querySelectorAll("button[data-i]").forEach((b) => (b.onclick = () => {
      const l = L.geoJSON(fs[+b.dataset.i], { style: { color: "#00e5ff", weight: 4 }, pointToLayer: (_, ll) => L.circleMarker(ll, { radius: 12, color: "#00e5ff", weight: 4 }) }).addTo(M.map);
      sheet.classList.add("min"); sheet.classList.remove("full"); setTimeout(() => fitToSheet(l.getBounds(), 16), 220); setTimeout(() => M.map.removeLayer(l), 5000);
    }));
  } else if (M.tab === "elements") {
    el.innerHTML = M.bundle.defs.map((d) => {
      const e = p.elements[d.code];
      return `<details class="el"><summary><span class="code">${d.code}</span><span style="flex:1">${esc(d.title)}</span><span class="dot ${e ? e.status : "empty"}"></span></summary>
        <div class="body">${Forms.view(d.fields, e && e.content)}</div></details>`;
    }).join("");
  } else if (M.tab === "burn") {
    el.innerHTML = p.burn_days.map((b) => `<div class="feat"><span class="lbl"><b>${b.burn_date}</b></span><span class="badge ${b.decision === "go" ? "approved" : b.decision === "no_go" ? "cancelled" : "draft"}">${b.decision.replace("_", "-")}</span></div>`).join("")
      || '<p class="hint">No burn days yet.</p>';
  }
}

boot();
