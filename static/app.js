// rx desktop editor.
const S = { user: null, defs: [], layers: [], plan: null, featuresFC: null, overlay: null, map: null,
            planLayer: null, landscape: {}, asOf: "", tab: "elements", el: "4", drawKind: null };
const view = document.getElementById("view");
const ROLE_RANK = { viewer: 0, planner: 1, burn_boss: 2, admin: 3 };
const can = (role) => S.user && ROLE_RANK[S.user.role] >= ROLE_RANK[role];
const locked = () => S.plan && ["approved", "implemented", "closed", "cancelled"].includes(S.plan.status);
const esc = RX.esc;

function toast(msg, bad) {
  let t = document.getElementById("toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; document.body.appendChild(t);
    Object.assign(t.style, { position: "fixed", bottom: "18px", left: "50%", transform: "translateX(-50%)", padding: "9px 14px", borderRadius: "6px", color: "#fff", zIndex: 9999, fontSize: "14px", maxWidth: "90vw" }); }
  t.textContent = msg; t.style.background = bad ? "#b3261e" : "#1d2329"; t.hidden = false;
  clearTimeout(t._h); t._h = setTimeout(() => (t.hidden = true), 3500);
}
async function call(fn) { try { return await fn(); } catch (e) { if (e.status === 401) return showLogin(); toast(e.message, true); throw e; } }

// --- routing -----------------------------------------------------------------------
async function route() {
  const m = location.hash.match(/^#plan\/(\d+)(?:\/([\w-]+))?/);
  if (!S.user) {
    try { S.user = await RX.api("/api/me"); } catch (e) { return showLogin(); }
    document.getElementById("who").textContent = `${S.user.display_name} · ${S.user.role.replace("_", " ")}`;
    document.getElementById("logout").hidden = false;
    [S.defs, S.layers] = await Promise.all([RX.api("/api/element-defs"), RX.api("/api/layers")]);
  }
  if (m) return showPlan(+m[1], m[2]);
  return showList();
}
window.addEventListener("hashchange", route);
document.getElementById("logout").onclick = async () => { await RX.api("/api/logout", { method: "POST" }); location.hash = ""; location.reload(); };

// --- login ---------------------------------------------------------------------------
function showLogin() {
  S.user = null;
  view.innerHTML = `<div class="login-wrap"><form class="login" id="lf">
    <h2>Sign in</h2><p>Prescribed fire plans and the landscape database.</p>
    <div class="field"><label for="u">Username</label><input id="u" autocomplete="username" required></div>
    <div class="field"><label for="p">Password</label><input id="p" type="password" autocomplete="current-password" required></div>
    <div class="err" id="le" role="alert"></div>
    <button class="btn primary" style="width:100%">Sign in</button></form></div>`;
  document.getElementById("lf").onsubmit = async (e) => {
    e.preventDefault();
    try { await RX.api("/api/login", { method: "POST", body: { username: u.value, password: p.value } }); route(); }
    catch (err) { document.getElementById("le").textContent = err.message; }
  };
  document.getElementById("u").focus();
}

// --- program view: every burn block on one map ---------------------------------------
const STATUS_COLOR = { draft: "#9e9e9e", review: "#e0a100", approved: "#2e7d32", implemented: "#1565c0", closed: "#6d4c41" };
const STATUS_ORDER = ["draft", "review", "approved", "implemented", "closed"];
async function showList() {
  S.view = "program"; S.mode = "program"; S.plan = null;
  const fc = await call(() => RX.api("/api/blocks"));
  const plans = await call(() => RX.api("/api/plans"));
  const noBlock = plans.filter((p) => p.area_ha == null && p.status !== "cancelled");
  view.innerHTML = `<div class="ws-bar"><h2>Burn program</h2><span class="meta" id="pstats"></span><span class="spacer"></span>
      ${can("planner") ? '<button class="btn primary small" id="addblock">Add burn block</button>' : ""}</div>
    <div class="ws"><div id="map"></div><div class="side"><div class="tabpanel" id="panel"></div></div></div>`;
  buildMap();
  const filt = new Set(STATUS_ORDER);
  const ha = (st) => fc.features.filter((f) => f.properties.status === st).reduce((a, f) => a + (f.properties.area_ha || 0), 0);
  document.getElementById("pstats").textContent = `${fc.features.length} blocks · ${Math.round(fc.features.reduce((a, f) => a + (f.properties.area_ha || 0), 0))} ha`;
  S.blockLayer = L.geoJSON(fc, {
    style: (f) => ({ color: "#111", weight: 2, fillColor: STATUS_COLOR[f.properties.status] || "#999", fillOpacity: 0.45 }),
    onEachFeature: (f, l) => {
      l.bindTooltip(esc(f.properties.name), { permanent: true, direction: "center", className: "block-label" });
      l.on("click", () => selectBlock(f.properties.id, false));
    },
  }).addTo(S.map);
  const b = S.blockLayer.getBounds(); if (b.isValid()) S.map.fitBounds(b, { padding: [40, 40], maxZoom: 14 }); else S.map.setView([49.72, -99.55], 11);
  const panel = document.getElementById("panel");
  const render = () => {
    const rows = fc.features.map((f) => f.properties).filter((p) => filt.has(p.status));
    panel.innerHTML = `<div class="legend-chips">${STATUS_ORDER.map((st) => `<button class="chip-f ${filt.has(st) ? "on" : ""}" data-st="${st}" aria-pressed="${filt.has(st)}">
        <span class="sw" style="background:${STATUS_COLOR[st]}"></span>${st[0].toUpperCase() + st.slice(1)} <span class="hint">${Math.round(ha(st))} ha</span></button>`).join("")}</div>
      <p class="hint">Click a block on the map or in the list. ${can("planner") ? "Add burn block draws a new one and starts its fire plan." : ""}</p>
      ${rows.map((p) => `<div class="block-row" data-id="${p.id}" tabindex="0" role="button" aria-label="Select ${esc(p.name)}">
        <div class="br-top"><span class="sw" style="background:${STATUS_COLOR[p.status]}"></span><b>${esc(p.name)}</b> ${p.demo ? '<span class="badge demo">DEMO</span>' : ""}
          <span class="spacer"></span><span class="badge ${p.status}">${p.status}</span></div>
        <div class="br-meta">${p.area_ha} ha · v${p.version_no} · ${esc(p.planned_window || "window not set")}</div>
        <div class="br-meta">Last fire: ${p.last_fire || "none on record"}${p.burned_on ? ` · burned ${p.burned_on}` : ""} · ${p.visits} site visit${p.visits === 1 ? "" : "s"}</div>
        <div class="br-meta"><span class="bar"><i style="width:${Math.round(100 * p.complete / p.total)}%"></i></span> ${p.complete} / ${p.total} elements</div>
        <div class="br-actions" hidden><a class="btn primary small" href="#plan/${p.id}">Open fire plan ›</a></div></div>`).join("") || '<p class="hint">No burn blocks shown.</p>'}
      ${noBlock.length ? `<h4>Plans without a burn block drawn</h4>${noBlock.map((p) => `<div class="feat"><span class="lbl">${esc(p.name)}</span><a class="btn small" href="#plan/${p.id}">Open</a></div>`).join("")}` : ""}`;
    panel.querySelectorAll(".chip-f").forEach((c) => (c.onclick = () => { filt.has(c.dataset.st) ? filt.delete(c.dataset.st) : filt.add(c.dataset.st); applyFilter(); render(); }));
    panel.querySelectorAll(".block-row").forEach((r) => { r.onclick = (e) => { if (e.target.closest("a")) return; selectBlock(+r.dataset.id, true); }; r.onkeydown = (e) => e.key === "Enter" && selectBlock(+r.dataset.id, true); });
    if (S.selBlock) selectBlock(S.selBlock, false);
  };
  const applyFilter = () => S.blockLayer.eachLayer((l) => {
    const on = filt.has(l.feature.properties.status);
    l.setStyle({ opacity: on ? 1 : 0, fillOpacity: on ? 0.45 : 0 }); on ? l.openTooltip() : l.closeTooltip();
  });
  render();
  const add = document.getElementById("addblock");
  if (add) add.onclick = () => { S.map.pm.enableDraw("Polygon", { continueDrawing: false }); toast("Draw the burn block on the map. Click the first point to finish; Esc cancels."); };
}
function selectBlock(id, zoom) {
  S.selBlock = id;
  document.querySelectorAll(".block-row").forEach((r) => { const on = +r.dataset.id === id; r.classList.toggle("sel", on); r.querySelector(".br-actions").hidden = !on; if (on && !zoom) r.scrollIntoView({ block: "nearest" }); });
  S.blockLayer.eachLayer((l) => l.setStyle({ weight: l.feature.properties.id === id ? 5 : 2, color: l.feature.properties.id === id ? "#c2410c" : "#111" }));
  const l = S.blockLayer.getLayers().find((x) => x.feature.properties.id === id);
  if (l && zoom) S.map.fitBounds(l.getBounds(), { padding: [60, 60], maxZoom: 15 });
}
async function createBlock(gj) {
  const name = prompt("Name for the new burn block (e.g. Burn Unit 12)");
  if (!name) return showList();
  const win = prompt("Planned burn window (optional, e.g. Apr 15 – May 14, 2027)", "") || null;
  const r = await call(() => RX.api("/api/plans", { method: "POST", body: { name, planned_window: win, geom: gj } }));
  toast("Burn block created: now build its fire plan"); location.hash = `#plan/${r.id}/map`;
}

// --- fire plan view: elements on the left, the selected element on the right -------------
const NAV_GROUPS = [["Map and data", [["map", "Plan map"], ["values", "Values and fuels"], ["visits", "Site visits"]]],
                    ["Implementation", [["burn", "Burn days"], ["versions", "Versions and signatures"]]]];
const MAP_VIEWS = new Set(["map", "values", "visits"]);
async function showPlan(id, sel) {
  S.sel = sel || (S.planId === id && S.sel) || "e-4";
  const [plan, fc, ov] = await call(() => Promise.all([RX.api(`/api/plans/${id}`), RX.api(`/api/plans/${id}/features`), RX.api(`/api/plans/${id}/overlay`)]));
  S.plan = plan; S.featuresFC = fc; S.overlay = ov;
  const fresh = S.view !== "plan" || S.planId !== id || !document.getElementById("pv");
  S.view = "plan"; S.mode = "plan"; S.planId = id; S.dirty = false;
  if (fresh) {
    view.innerHTML = `<div class="ws-bar" id="bar"></div><div class="pv" id="pv"><nav class="pv-nav" id="nav" aria-label="Plan sections"></nav><section class="pv-main" id="main"></section></div>`;
    S.mapEl = document.createElement("div"); S.mapEl.id = "map";
    document.getElementById("main").appendChild(S.mapEl); buildMap();
  }
  renderBar(); drawPlanFeatures(); renderNav(); renderMain();
}
function go(key) {
  if (S.dirty && !confirm("This element has unsaved changes. Leave without saving?")) return;
  S.dirty = false; location.hash = `#plan/${S.plan.id}/${key}`;
}
window.addEventListener("beforeunload", (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ""; } });

function renderNav() {
  const els = S.plan.elements;
  const done = S.defs.filter((d) => (els[d.code] || {}).status === "complete").length;
  const item = (key, inner) => `<button type="button" class="nav-item" data-k="${key}" aria-current="${S.sel === key ? "page" : "false"}">${inner}</button>`;
  const nav = document.getElementById("nav");
  nav.innerHTML = `<div class="nav-sec">Plan elements <span class="hint">${done} of ${S.defs.length} complete</span></div>
    ${S.defs.map((d) => { const st = (els[d.code] || {}).status || "empty";
      return item("e-" + d.code, `<span class="dot ${st}" title="${st}"><span class="sr">${st}</span></span><span class="nc">${d.code}</span><span class="nt">${esc(d.title.replace(/^Appendix [A-F]: /, ""))}</span>`); }).join("")}
    ${NAV_GROUPS.map(([g, items]) => `<div class="nav-sec">${g}</div>` + items.map(([k, l]) => item(k, `<span class="dot tool"></span><span class="nt">${l}</span>`)).join("")).join("")}`;
  nav.querySelectorAll(".nav-item").forEach((b) => (b.onclick = () => go(b.dataset.k)));
  const cur = nav.querySelector('[aria-current="page"]'); if (cur) cur.scrollIntoView({ block: "nearest" });
}

function placeMap(slotId) {
  document.getElementById(slotId).appendChild(S.mapEl);
  setTimeout(() => { S.map.invalidateSize(); fitPlan(); }, 0);
}
function renderMain() {
  const main = document.getElementById("main");
  S.mapEl.remove(); main.innerHTML = "";
  if (S.visitLayer) { S.map.removeLayer(S.visitLayer); S.visitLayer = null; }
  const lock = locked() ? `<div class="locked">This plan is ${S.plan.status} and locked. Use <b>Amend</b> to make a new version.</div>` : "";
  if (S.sel.startsWith("e-")) return renderElement(main, S.sel.slice(2), lock);
  if (MAP_VIEWS.has(S.sel)) {
    main.innerHTML = `<div class="split"><div class="map-slot" id="mslot"></div><div class="split-side" id="side">${lock}</div></div>`;
    placeMap("mslot");
    return ({ map: panelFeatures, values: panelValues, visits: panelVisits })[S.sel](document.getElementById("side"));
  }
  main.innerHTML = `<div class="doc">${lock}<h2 class="doc-title">${S.sel === "burn" ? "Burn days" : "Versions and signatures"}</h2><div id="docbody"></div></div>`;
  ({ burn: panelBurn, versions: panelVersions })[S.sel](document.getElementById("docbody"));
}

// The plan's own data, shown read-only inside elements.
function autoHtml(src, live) {
  const p = S.plan, feats = S.featuresFC.features.map((f) => f.properties);
  const list = (kind, unit) => feats.filter((f) => f.kind === kind).map((f) => `<li>${esc(f.label || RX.KINDS[kind].label)}${unit === "ha" && f.area_ha ? ` · ${f.area_ha} ha` : ""}${unit === "m" && f.length_m ? ` · ${Math.round(f.length_m)} m` : ""}</li>`).join("");
  const none = (what) => `<span class="hint">None drawn yet. Add ${what} on the <a href="#plan/${p.id}/map">plan map</a>.</span>`;
  const sum = (kind) => feats.filter((f) => f.kind === kind).reduce((a, f) => a + (f.area_ha || 0), 0);
  switch (src) {
    case "plan_name": return esc(p.name);
    case "ignition_units": { const l = list("ignition_unit", "ha"); return l ? `<ul>${l}</ul>` : none("ignition units"); }
    case "location": return p.centroid ? `Centre ${p.centroid.lat}, ${p.centroid.lon} · ${esc(p.centroid.utm)}` : none("the burn unit");
    case "size": return sum("burn_unit") ? `Burn unit ${sum("burn_unit").toFixed(1)} ha${sum("contingency_area") ? ` · contingency area ${(sum("contingency_area") - sum("burn_unit")).toFixed(1)} ha outside the unit` : ""}` : none("the burn unit");
    case "fuels": return S.overlay.fuels.length ? `<table class="grid"><thead><tr><th>Fuel class</th><th class="num">Burn unit ha</th><th class="num">Contingency ha</th></tr></thead><tbody>${S.overlay.fuels.map((f) => `<tr><td>${esc(f.fuel_class)}</td><td class="num">${f.unit_ha ?? 0}</td><td class="num">${f.contingency_ha ?? 0}</td></tr>`).join("")}</tbody></table>` : '<span class="hint">No fuel classes under the unit.</span>';
    case "values": {
      const v = S.overlay.features.map((f) => f.properties).filter((x) => !["fuels.fuel_class", "ops.road", "ops.fireguard"].includes(x.layer));
      const title = (n) => (S.layers.find((l) => l.name === n) || {}).title || n;
      return v.length ? `<table class="grid"><thead><tr><th>Value</th><th>Layer</th><th>Detail</th><th>Where</th></tr></thead><tbody>${v.map((x) => `<tr><td>${esc(x.name || x.species || x.kind || "")}${x.grid_id ? " · " + esc(x.grid_id) : ""}</td><td>${esc(title(x.layer))}</td><td>${esc(x.vulnerability || x.measure || x.status || "")}</td><td>${x.zone}</td></tr>`).join("")}</tbody></table>` : '<span class="hint">Nothing recorded in the unit or contingency area.</span>';
    }
    case "receptors": return p.receptors.length ? `<table class="grid"><thead><tr><th>Receptor</th><th>Type</th><th>Sensitivity</th><th class="num">km</th><th class="num">Bearing</th></tr></thead><tbody>${p.receptors.map((r) => `<tr><td>${esc(r.name)}</td><td>${esc(r.kind || "")}</td><td>${esc(r.sensitivity || "")}</td><td class="num">${r.km}</td><td class="num">${r.bearing}°</td></tr>`).join("")}</tbody></table>` : '<span class="hint">No receptors within 40 km in the database.</span>';
    case "test_fire_site": { const l = list("test_fire_site"); return l ? `<ul>${l}</ul>` : none("a test fire site"); }
    case "holding_lines": { const h = list("holding_line", "m"), c = list("contingency_line", "m"); return h || c ? `<b>Holding</b><ul>${h || "<li>none</li>"}</ul><b>Contingency</b><ul>${c || "<li>none</li>"}</ul>` : none("holding lines"); }
    case "trigger_points": { const l = list("trigger_point"); return l ? `<ul>${l}</ul>` : none("trigger points"); }
    case "cost_total": { const t = (live.costs || []).reduce((a, r) => a + (+r.amount || 0), 0); return `$${t.toLocaleString()}`; }
    case "mbca": {
      const w = (live.windows || []).filter((r) => r.from && r.to);
      if (!w.length) return '<span class="hint">Add burn windows to check them.</span>';
      const bad = w.filter((r) => { const md = (d) => d.slice(5); return !(md(r.to) < "05-15" || md(r.from) > "08-15") || r.from.slice(0, 4) !== r.to.slice(0, 4); });
      return bad.length ? `<span class="warn">${bad.length} window${bad.length > 1 ? "s overlap" : " overlaps"} May 15 – Aug 15 (no prescribed ignition at Shilo during the MBCA period).</span>` : '<span class="ok">No window overlaps May 15 – Aug 15.</span>';
    }
    case "complexity_summary": {
      const rows = live.elements || []; const c = (k) => ({ low: 0, moderate: 0, high: 0, ...rows.reduce((a, r) => (r[k] ? { ...a, [r[k]]: (a[r[k]] || 0) + 1 } : a), {}) });
      const r = c("post_risk"), d = c("difficulty"), rated = rows.filter((x) => x.post_risk && x.difficulty).length;
      return `${rated} of ${rows.length} elements rated. Post-plan risk: ${r.high} high, ${r.moderate} moderate, ${r.low} low. Technical difficulty: ${d.high} high, ${d.moderate} moderate, ${d.low} low.
        <div class="hint">Use the PMS 424-1 worksheet to calculate the summary rating; the agency administrator sets the final rating below.</div>`;
    }
  }
  return "";
}

function renderElement(main, code, lock) {
  const d = S.defs.find((x) => x.code === code) || S.defs[0];
  const e = S.plan.elements[d.code] || { content: {}, status: "empty" };
  const ro = locked() || !can("planner");
  const known = new Set(d.fields.map((f) => f.key));
  const legacy = Object.entries(e.content || {}).filter(([k, v]) => !known.has(k) && v);
  main.innerHTML = `<div class="doc">${lock}
    <div class="el-headbar"><div><div class="owner">${/^\d/.test(d.code) ? "Element " + d.code : "Appendix " + d.code} · drafted by ${d.owner_role.replace("_", " ")}</div><h2 class="doc-title">${esc(d.title)}</h2></div>
      <div class="el-actions">${ro ? `<span class="badge ${e.status === "complete" ? "approved" : "draft"}">${e.status}</span>` : `<label class="hint" for="est">Status</label><select id="est"><option value="draft">Draft</option><option value="complete">Complete</option></select>
        <button class="btn primary" id="esave">Save</button>`}</div></div>
    ${d.guidance ? `<p class="hint">${esc(d.guidance)}</p>` : ""}
    ${d.map ? '<div class="map-slot small" id="mslot"></div>' : ""}
    <form id="ef" class="ef" onsubmit="return false"></form>
    ${legacy.length ? `<div class="legacy"><b>Text from the earlier version of this element</b> <span class="hint">(kept with the plan; copy it into the fields above)</span>${legacy.map(([k, v]) => `<p><b>${esc(k)}</b>: ${esc(typeof v === "string" ? v : JSON.stringify(v))}</p>`).join("")}</div>` : ""}
    <div class="row-actions"><button type="button" class="btn small" id="ehist">History</button><span class="hint">${e.updated_at ? "Last saved " + e.updated_at.slice(0, 16).replace("T", " ") + " by " + esc(e.updated_by) : "Not saved yet"}</span></div><div id="hist"></div></div>`;
  if (d.map) placeMap("mslot");
  const form = document.getElementById("ef");
  const refreshAuto = () => { const live = read(); form.querySelectorAll(".auto[data-src]").forEach((a) => (a.innerHTML = autoHtml(a.dataset.src, live))); };
  const read = Forms.render(form, d.fields, e.content, ro, { onChange: () => { S.dirty = true; const b = document.getElementById("esave"); if (b) b.textContent = "Save*"; refreshAuto(); } });
  refreshAuto();
  form.querySelectorAll(".component").forEach((c) => {
    const box = document.createElement("div"); c.appendChild(box);
    ({ prescription: panelRx, variants: panelVariants, signatures: panelSignatures })[c.dataset.component](box);
  });
  const st = document.getElementById("est"); if (st) st.value = e.status === "complete" ? "complete" : "draft";
  if (st) st.onchange = () => { S.dirty = true; };
  const save = async () => {
    const content = { ...Object.fromEntries(legacy), ...read() };
    await call(() => RX.api(`/api/plans/${S.plan.id}/elements/${d.code}`, { method: "PUT", body: { content, status: st.value } }));
    S.plan.elements[d.code] = { content, status: st.value, updated_at: new Date().toISOString(), updated_by: S.user.username };
    S.dirty = false; toast(`${d.code}. ${d.title}: saved`); renderNav(); renderMain();
  };
  const sv = document.getElementById("esave"); if (sv) sv.onclick = save;
  main.onkeydown = (ev) => { if ((ev.ctrlKey || ev.metaKey) && ev.key === "s" && sv) { ev.preventDefault(); save(); } };
  document.getElementById("ehist").onclick = async () => {
    const h = await call(() => RX.api(`/api/plans/${S.plan.id}/elements/${d.code}/history`));
    document.getElementById("hist").innerHTML = `<h4>Saved versions</h4>` + (h.map((r) => `<details><summary class="hint">${r.saved_at.slice(0, 16).replace("T", " ")} · ${esc(r.saved_by)} · ${r.status}</summary><pre class="hist">${esc(JSON.stringify(r.content, null, 1))}</pre></details>`).join("") || '<p class="hint">No saves yet.</p>');
  };
}

function renderBar() {
  const p = S.plan;
  const btn = (id, label, cls = "") => `<button class="btn small ${cls}" id="${id}">${label}</button>`;
  let actions = "";
  if (p.status === "draft" && can("planner")) actions += btn("to-review", "Submit for review");
  if (p.status === "review" && can("planner")) actions += btn("to-draft", "Back to draft");
  if (p.status === "review" && can("burn_boss")) actions += btn("approve", "Approve", "primary");
  if (["approved", "implemented", "closed"].includes(p.status) && can("planner") && !p.successor) actions += btn("amend", "Amend");
  if (p.successor) actions += `<a class="btn small" href="#plan/${p.successor.id}">Go to the amendment ›</a>`;
  document.getElementById("bar").innerHTML = `<a class="btn small" href="#">‹ Burn program</a>
    <h2>${esc(p.name)}</h2> ${p.demo ? '<span class="badge demo">DEMO</span>' : ""}<span class="badge ${p.status}">${p.status}</span>
    <span class="meta">v${p.version_no} · ${esc(p.complexity || "complexity —")} · ${esc(p.min_burn_boss || "")}${p.as_of ? " · data frozen " + p.as_of.slice(0, 16).replace("T", " ") : ""}</span>
    <span class="spacer"></span>${actions}
    <a class="btn small" href="/api/plans/${p.id}/export.docx">Export .docx</a>
    <a class="btn small" href="/m#${p.id}" target="_blank" rel="noopener">Mobile ↗</a>`;
  const on = (id, fn) => { const b = document.getElementById(id); if (b) b.onclick = fn; };
  const status = (s) => async () => { await call(() => RX.api(`/api/plans/${p.id}/status`, { method: "POST", body: { status: s } })); showPlan(p.id); };
  on("to-review", status("review")); on("to-draft", status("draft"));
  on("approve", async () => { if (confirm("Approve this plan? It will be locked and the data it uses frozen as of now.")) status("approved")(); });
  on("amend", async () => {
    const note = prompt("What does the amendment change?"); if (!note) return;
    const r = await call(() => RX.api(`/api/plans/${p.id}/amend`, { method: "POST", body: { note } })); location.hash = `#plan/${r.id}`;
  });
}

// --- map ---------------------------------------------------------------------------------
function buildMap() {
  S.map = L.map("map", { zoomControl: true });
  const bm = RX.basemaps(); bm["Imagery"].addTo(S.map);
  S.landscape = {};
  const panel = L.control({ position: "topright" });
  panel.onAdd = () => {
    const wrap = L.DomUtil.create("div");
    const tb = L.DomUtil.create("button", "layer-toggle", wrap); tb.type = "button"; tb.textContent = "Layers ▾"; tb.setAttribute("aria-expanded", "false");
    const d = L.DomUtil.create("div", "layer-panel", wrap); d.hidden = true;
    tb.onclick = () => { d.hidden = !d.hidden; tb.setAttribute("aria-expanded", String(!d.hidden)); tb.textContent = d.hidden ? "Layers ▾" : "Layers ▴"; };
    L.DomEvent.disableClickPropagation(wrap); L.DomEvent.disableScrollPropagation(wrap);
    d.innerHTML = `<div class="sec">Basemap</div>${Object.keys(bm).map((k, i) => `<label><input type="radio" name="bm" value="${k}" ${i === 0 ? "checked" : ""}> ${k}</label>`).join("")}
      <div class="sec">Landscape layers</div>
      ${S.layers.filter((l) => l.visible).map((l) => `<label><input type="checkbox" data-layer="${l.name}"> ${esc(l.title)}${l.kind === "event" ? ' <span class="hint">(records)</span>' : ""}</label>`).join("")}
      <div class="sec">Show layers as on</div><input type="date" id="asof" aria-label="Show landscape layers as they were on this date">
      <div class="hint" style="margin-top:4px">Blank = current.</div>`;
    d.querySelectorAll('input[name="bm"]').forEach((r) => (r.onchange = () => { Object.values(bm).forEach((b) => S.map.removeLayer(b)); bm[r.value].addTo(S.map).bringToBack(); }));
    d.querySelectorAll("input[data-layer]").forEach((c) => (c.onchange = () => toggleLandscape(c.dataset.layer, c.checked)));
    d.querySelector("#asof").onchange = (e) => { S.asOf = e.target.value; Object.keys(S.landscape).forEach((n) => toggleLandscape(n, true)); };
    return wrap;
  };
  panel.addTo(S.map);
  S.map.pm.setGlobalOptions({ snappable: true, snapDistance: 15 });
  S.map.on("pm:create", onDrawn);
}

async function toggleLandscape(name, on) {
  if (S.landscape[name]) { S.map.removeLayer(S.landscape[name]); delete S.landscape[name]; }
  if (!on) return;
  const meta = S.layers.find((l) => l.name === name);
  const q = S.asOf ? `?on_ground=${S.asOf}T12:00:00Z` : "";
  const fc = await call(() => RX.api(`/api/layers/${name}${q}`));
  S.landscape[name] = RX.landscapeLayer(meta, fc).addTo(S.map);
  if (S.planLayer) S.planLayer.bringToFront();
}

function drawPlanFeatures() {
  if (S.planLayer) S.map.removeLayer(S.planLayer);
  S.planLayer = RX.featureLayer(S.featuresFC, (f, l) => { l.featureId = f.id; }).addTo(S.map);
}
function fitPlan() {
  const b = S.planLayer.getBounds();
  if (b.isValid()) S.map.fitBounds(b, { padding: [20, 20] }); else S.map.setView([49.75, -99.5], 11);
}

async function onDrawn(e) {
  const gj = e.layer.toGeoJSON().geometry; S.map.removeLayer(e.layer);
  if (S.mode === "program") return createBlock(gj);
  const kind = S.drawKind; S.drawKind = null;
  if (!kind) return;
  const label = prompt(`Label for this ${RX.KINDS[kind].label.toLowerCase()}`, "") ?? "";
  await call(() => RX.api(`/api/plans/${S.plan.id}/features`, { method: "POST", body: { kind, label, geom: gj } }));
  toast("Saved"); showPlan(S.plan.id);
}

// Map features
function panelFeatures(root) {
  const ro = locked() || !can("planner");
  const feats = S.featuresFC.features;
  root.insertAdjacentHTML("beforeend", `${ro ? "" : `<div class="row-actions"><select id="nk" aria-label="Feature type">${Object.entries(RX.KINDS).map(([k, v]) => `<option value="${k}">${v.label}</option>`).join("")}</select>
      <button class="btn primary" id="draw">Draw on map</button></div><p class="hint">Pick a type, then click on the map to draw it. Lines and polygons finish on the first or last point.</p>`}
    ${Object.keys(RX.KINDS).map((k) => {
      const fs = feats.filter((f) => f.properties.kind === k); if (!fs.length) return "";
      return `<h4>${RX.KINDS[k].label}</h4>` + fs.map((f) => `<div class="feat" data-id="${f.id}"><span class="sw" style="background:${RX.KINDS[k].color}"></span>
        <span class="lbl">${esc(f.properties.label || "—")}</span><span class="m">${f.properties.area_ha ? f.properties.area_ha + " ha" : f.properties.length_m ? Math.round(f.properties.length_m) + " m" : ""}</span>
        <button class="btn small" data-act="zoom">Zoom</button>${ro ? "" : `<button class="btn small" data-act="edit">Edit shape</button><button class="btn small danger" data-act="del" aria-label="Delete">✕</button>`}</div>`).join("");
    }).join("")}`);
  const draw = document.getElementById("draw");
  if (draw) draw.onclick = () => {
    S.drawKind = document.getElementById("nk").value;
    const shape = RX.KINDS[S.drawKind].draw;
    S.map.pm.enableDraw(shape, { continueDrawing: false });
    toast(`Drawing a ${RX.KINDS[S.drawKind].label.toLowerCase()}. Esc cancels.`);
  };
  root.querySelectorAll(".feat button").forEach((b) => (b.onclick = async () => {
    const id = b.closest(".feat").dataset.id;
    const layer = S.planLayer.getLayers().find((l) => l.featureId === id);
    if (b.dataset.act === "zoom") { layer.getBounds ? S.map.fitBounds(layer.getBounds(), { maxZoom: 16 }) : S.map.setView(layer.getLatLng(), 16); layer.openTooltip(); }
    if (b.dataset.act === "del" && confirm("Delete this feature?")) {
      await call(() => RX.api(`/api/plans/${S.plan.id}/features/${id}`, { method: "DELETE" })); showPlan(S.plan.id);
    }
    if (b.dataset.act === "edit") {
      if (layer.pm.enabled()) {
        layer.pm.disable();
        await call(() => RX.api(`/api/plans/${S.plan.id}/features/${id}`, { method: "PUT", body: { geom: layer.toGeoJSON().geometry } }));
        toast("Shape saved"); showPlan(S.plan.id);
      } else { layer.pm.enable({ snappable: true }); b.textContent = "Save shape"; b.classList.add("primary"); }
    }
  }));
}

// Values & fuels (overlay)
function panelValues(root) {
  const ov = S.overlay;
  const by = {};
  ov.features.forEach((f) => { const k = f.properties.layer; (by[k] = by[k] || []).push(f); });
  const title = (n) => (S.layers.find((l) => l.name === n) || {}).title || n;
  root.insertAdjacentHTML("beforeend", `<p class="hint">What the database holds inside the burn unit and the contingency area
    ${ov.as_of ? `as known when the plan was approved (${ov.as_of.slice(0, 16).replace("T", " ")})` : "right now (draft plans follow the live layers)"}.</p>
    <h4>Fuel classes</h4><table class="grid"><thead><tr><th>Class</th><th class="num">Burn unit ha</th><th class="num">Contingency ha</th></tr></thead>
    <tbody>${ov.fuels.map((f) => `<tr><td>${esc(f.fuel_class)}</td><td class="num">${f.unit_ha ?? 0}</td><td class="num">${f.contingency_ha ?? 0}</td></tr>`).join("") || '<tr><td colspan="3" class="hint">No fuel data under the unit.</td></tr>'}</tbody></table>
    ${Object.entries(by).filter(([k]) => k !== "fuels.fuel_class").map(([k, fs]) => `<h4>${esc(title(k))}</h4>` + fs.map((f, i) => {
      const p = f.properties; const name = p.name || p.species || p.grid_id || p.kind || "—";
      const extra = p.vulnerability || p.sensitivity || p.condition || p.status || p.guard_type || "";
      return `<div class="feat"><span class="lbl">${esc(name)}${p.grid_id && p.species ? " · " + esc(p.grid_id) : ""}</span><span class="m">${esc(extra)}</span>
        <span class="badge ${p.zone === "unit" ? "review" : "draft"}">${p.zone}</span><button class="btn small" data-k="${k}" data-i="${i}">Show</button></div>`;
    }).join("")).join("")}`);
  root.querySelectorAll("button[data-k]").forEach((b) => (b.onclick = () => {
    const f = by[b.dataset.k][+b.dataset.i];
    const l = L.geoJSON(f, { style: { color: "#00e5ff", weight: 4, fillOpacity: 0.1 }, pointToLayer: (_, ll) => L.circleMarker(ll, { radius: 10, color: "#00e5ff", weight: 4 }) }).addTo(S.map);
    S.map.fitBounds(l.getBounds(), { maxZoom: 15 }); setTimeout(() => S.map.removeLayer(l), 4000);
  }));
}

// Prescription
function panelRx(root) {
  const ro = locked() || !can("planner");
  const rows = S.plan.prescription.length ? S.plan.prescription : [];
  root.insertAdjacentHTML("beforeend", `<p class="hint">Limits checked against burn-day forecasts. Leave a side blank for a one-sided limit.</p>
    <table class="grid" id="rxt"><thead><tr><th>Parameter</th><th>Low</th><th>High</th><th>Note</th>${ro ? "" : "<th></th>"}</tr></thead><tbody>
    ${rows.map((r) => rxRow(r, ro)).join("")}</tbody></table>
    ${ro ? "" : `<div class="row-actions"><button class="btn small" id="rxadd">Add parameter</button><button class="btn primary" id="rxsave">Save prescription</button></div>`}`);
  if (ro) return;
  document.getElementById("rxadd").onclick = () => document.querySelector("#rxt tbody").insertAdjacentHTML("beforeend", rxRow({}, false));
  root.addEventListener("click", (e) => { if (e.target.dataset.del) e.target.closest("tr").remove(); });
  document.getElementById("rxsave").onclick = async () => {
    const body = [...document.querySelectorAll("#rxt tbody tr")].map((tr) => {
      const v = (n) => tr.querySelector(`[name=${n}]`).value; const num = (n) => (v(n) === "" ? null : +v(n));
      return { param: v("param"), low: num("low"), high: num("high"), note: v("note") };
    });
    await call(() => RX.api(`/api/plans/${S.plan.id}/prescription`, { method: "PUT", body })); toast("Prescription saved"); showPlan(S.plan.id);
  };
}
function rxRow(r, ro) {
  const dis = ro ? "disabled" : "";
  return `<tr><td><select name="param" ${dis}>${Object.entries(RX.PARAMS).map(([k, l]) => `<option value="${k}" ${r.param === k ? "selected" : ""}>${l}</option>`).join("")}</select></td>
    <td><input name="low" type="number" step="any" value="${r.low ?? ""}" ${dis}></td><td><input name="high" type="number" step="any" value="${r.high ?? ""}" ${dis}></td>
    <td><input name="note" value="${esc(r.note || "")}" ${dis}></td>${ro ? "" : '<td><button class="btn small danger" data-del="1" aria-label="Remove">✕</button></td>'}</tr>`;
}

// Ignition variants
function panelVariants(root) {
  const ro = locked() || !can("planner");
  root.insertAdjacentHTML("beforeend", `<p class="hint">Pre-approved ignition plans by wind direction (the direction the wind comes from).
    On a burn day the forecast picks the variant; a wind outside every variant is a NO-GO until the plan is amended.</p>
    ${S.plan.variants.map((v) => variantForm(v, ro)).join("")}${ro ? "" : variantForm({ name: "", wind_dir_min: "", wind_dir_max: "", description: "", firing_sequence: [] }, false, true)}`);
  root.querySelectorAll("form.variant").forEach((f) => (f.onsubmit = async (e) => {
    e.preventDefault();
    const body = { name: f.vname.value, wind_dir_min: +f.dmin.value, wind_dir_max: +f.dmax.value, description: f.desc.value,
      firing_sequence: f.steps.value.split("\n").map((s) => s.trim()).filter(Boolean).map((step) => ({ step })) };
    const id = f.dataset.id;
    await call(() => RX.api(id ? `/api/plans/${S.plan.id}/variants/${id}` : `/api/plans/${S.plan.id}/variants`, { method: id ? "PUT" : "POST", body }));
    toast("Variant saved"); showPlan(S.plan.id);
  }));
  root.querySelectorAll("button[data-vdel]").forEach((b) => (b.onclick = async () => {
    if (!confirm("Delete this variant?")) return;
    await call(() => RX.api(`/api/plans/${S.plan.id}/variants/${b.dataset.vdel}`, { method: "DELETE" })); showPlan(S.plan.id);
  }));
}
function variantForm(v, ro, isNew) {
  const dis = ro ? "disabled" : "";
  return `<form class="variant" data-id="${v.id || ""}" style="border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin-bottom:12px">
    <h4 style="margin-top:0">${isNew ? "Add a variant" : esc(v.name)}</h4>
    <div class="field"><label>Name</label><input name="vname" value="${esc(v.name)}" required ${dis}></div>
    <div style="display:flex;gap:10px"><div class="field" style="flex:1"><label>Wind from (°)</label><input name="dmin" type="number" min="0" max="360" value="${v.wind_dir_min}" required ${dis}></div>
    <div class="field" style="flex:1"><label>to (°)</label><input name="dmax" type="number" min="0" max="360" value="${v.wind_dir_max}" required ${dis}></div></div>
    <div class="field"><label>Description</label><input name="desc" value="${esc(v.description || "")}" ${dis}></div>
    <div class="field"><label>Firing sequence (one step per line)</label><textarea name="steps" ${dis}>${esc((v.firing_sequence || []).map((s) => s.step).join("\n"))}</textarea></div>
    ${ro ? "" : `<div class="row-actions"><button class="btn primary">${isNew ? "Add variant" : "Save"}</button>${isNew ? "" : `<button type="button" class="btn small danger" data-vdel="${v.id}">Delete</button>`}</div>`}</form>`;
}

// Site visits (recorded on the mobile view)
const VKIND = { pre_burn_recce: "Pre-burn recce", burn_day: "Burn day", post_burn: "Post-burn", monitoring: "Monitoring", fuel_survey: "Fuel survey", other: "Other" };
const RSTYLE = { note: ["#1f6fb2", "N"], photo: ["#455a64", "P"], fuel_plot: ["#7a8b3a", "F"], check: ["#2e7d32", "✓"], hazard: ["#b3261e", "!"] };
async function panelVisits(root) {
  if (!S.recce) S.recce = await call(() => RX.api("/api/field/recce-items"));
  const vs = await call(() => RX.api(`/api/visits?plan_id=${S.plan.id}`));
  root.insertAdjacentHTML("beforeend", `<p class="hint">Site visits are recorded in the field on the mobile view (Site visit tab): recce checks, photos, hazards and fuel plots.
    Fuel plots with a position are also added to the fuels database.</p>
    ${vs.map((v) => `<div class="feat"><span class="lbl"><b>${VKIND[v.kind] || v.kind}</b> · ${v.started_at.slice(0, 16).replace("T", " ")}<br>
      <span class="hint">${esc(v.crew || "")} · ${v.n_records} records · ${v.n_photos} photos${v.n_issues ? ` · <b style="color:var(--bad)">${v.n_issues} issue${v.n_issues > 1 ? "s" : ""}</b>` : ""}</span></span>
      <button class="btn small" data-v="${v.id}">Open</button></div>`).join("") || '<p class="hint">No visits yet.</p>'}<div id="vview"></div>`);
  root.querySelectorAll("button[data-v]").forEach((b) => (b.onclick = () => openVisit(b.dataset.v)));
}
async function openVisit(id) {
  const { visit: v, records } = await call(() => RX.api(`/api/visits/${id}`));
  if (S.visitLayer) S.map.removeLayer(S.visitLayer);
  S.visitLayer = L.geoJSON(records, { pointToLayer: (f, ll) => {
    const p = f.properties, [c, sym] = RSTYLE[p.kind] || ["#555", "•"];
    return L.marker(ll, { icon: L.divIcon({ className: "rx-pt", html: `<span style="background:${p.status === "issue" ? "#b3261e" : c}">${sym}</span>`, iconSize: null }) });
  }, onEachFeature: (f, l) => { const p = f.properties; l.bindPopup(`<b>${esc(recLabel(p))}</b><br>${esc(p.text || "")}${p.media.map((m) => `<br><a href="/api/media/${m}" target="_blank"><img src="/api/media/${m}?size=thumb" style="width:160px;margin-top:4px" alt=""></a>`).join("")}`); } }).addTo(S.map);
  const recs = records.features.map((f) => f.properties);
  const plots = recs.filter((r) => r.kind === "fuel_plot");
  document.getElementById("vview").innerHTML = `<h4>${VKIND[v.kind] || v.kind} · ${v.started_at.slice(0, 10)}</h4>
    <div class="hint">${esc(v.crew || "")}${v.weather ? " · " + esc(v.weather) : ""}${v.ended_at ? " · ended " + v.ended_at.slice(11, 16) : " · in progress"}</div>
    ${v.notes ? `<p>${esc(v.notes)}</p>` : ""}
    ${recs.some((r) => r.status === "issue") ? `<h4 style="color:var(--bad)">Issues</h4>` + recs.filter((r) => r.status === "issue").map(recRow).join("") : ""}
    ${plots.length ? `<h4>Fuel plots</h4><table class="grid"><thead><tr><th>Plot</th><th>Class</th><th class="num">kg/m²</th><th class="num">Curing</th><th class="num">Height</th><th>Method</th></tr></thead><tbody>
      ${plots.map((r) => `<tr><td>${esc(r.data.plot_code || "")}</td><td>${esc(r.data.fuel_class || "")}</td><td class="num">${r.data.load_kg_m2 ?? "—"}</td><td class="num">${r.data.curing_pct ?? "—"}</td><td class="num">${r.data.height_cm ?? "—"}</td><td>${esc(r.data.method || "")}</td></tr>`).join("")}</tbody></table>` : ""}
    <h4>All records</h4>${recs.map(recRow).join("")}
    ${can("planner") && !locked() ? `<div class="row-actions"><button class="btn small" id="v2e9">Copy issues into Element 9 (pre-burn considerations)</button></div>` : ""}`;
  document.querySelectorAll("#vview [data-zoom]").forEach((b) => (b.onclick = () => { const l = S.visitLayer.getLayers().find((x) => x.feature.id === b.dataset.zoom); if (l) { S.map.setView(l.getLatLng(), 17); l.openPopup(); } }));
  const e9 = document.getElementById("v2e9");
  if (e9) e9.onclick = async () => {
    const cur = (S.plan.elements["9"] || { content: {} }).content;
    const lines = recs.filter((r) => r.status === "issue").map((r) => `- ${recLabel(r)}: ${r.text || ""}`).join("\n");
    if (!lines) return toast("No issues to copy");
    const content = { ...cur, onsite: ((cur.onsite || "") + `\n\nFrom the ${VKIND[v.kind] || v.kind} on ${v.started_at.slice(0, 10)}:\n` + lines).trim() };
    await call(() => RX.api(`/api/plans/${S.plan.id}/elements/9`, { method: "PUT", body: { content, status: "draft" } }));
    S.plan.elements["9"] = { content, status: "draft" }; toast("Added to Element 9");
  };
  const b = S.visitLayer.getBounds(); if (b.isValid()) S.map.fitBounds(b.pad(0.3), { maxZoom: 16 });
}
const recLabel = (p) => p.kind === "check" ? `${((S.recce || []).find((i) => i.key === p.item)?.label || p.item).split(":")[0]} · ${p.status}` : p.kind === "fuel_plot" ? `Fuel plot ${p.data.plot_code || ""}` : p.kind === "hazard" ? `Hazard: ${p.item}` : p.kind;
const recRow = (r) => `<div class="feat"><span class="lbl"><b>${esc(recLabel(r))}</b> <span class="m">${r.observed_at.slice(11, 16)} · ${esc(r.created_by || "")}</span>${r.text ? `<br>${esc(r.text)}` : ""}
  ${r.media.length ? `<div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:4px">${r.media.map((m) => `<a href="/api/media/${m}" target="_blank"><img src="/api/media/${m}?size=thumb" style="width:64px;height:64px;object-fit:cover;border-radius:4px" alt="Photo"></a>`).join("")}</div>` : ""}</span>
  <button class="btn small" data-zoom="${r.id}">Map</button></div>`;

// Burn days
const CHECKLIST = [["permits", "Permits and notifications complete"], ["prep", "Pre-burn preparation (lines, wet lines, mowing) complete"],
  ["weather", "Spot / burn-morning forecast obtained and within prescription"], ["prescription", "On-site weather within prescription"],
  ["smoke", "Smoke specifications can be met"], ["personnel", "Required personnel and equipment on site"],
  ["contingency", "Contingency resources available and staged"], ["briefing", "Briefing completed"], ["range", "Range Control clearance received"]];
function panelBurn(root) {
  const p = S.plan;
  const canAdd = ["approved", "implemented"].includes(p.status) && can("planner");
  root.insertAdjacentHTML("beforeend", `<p class="hint">Burn days are added to approved plans. Each one freezes the forecast it was decided on and records the go / no-go.</p>
    ${canAdd ? `<div class="row-actions"><input type="date" id="bdd" aria-label="Burn date"><button class="btn primary" id="bdadd">Add burn day</button></div>` : ""}
    <div id="bdl">${p.burn_days.map((b) => `<div class="feat"><span class="lbl"><b>${b.burn_date}</b></span><span class="badge ${b.decision === "go" ? "approved" : b.decision === "no_go" ? "cancelled" : "draft"}">${b.decision.replace("_", "-")}</span>
      <button class="btn small" data-bd="${b.id}">Open</button></div>`).join("") || '<p class="hint">None yet.</p>'}</div><div id="bdv"></div>`);
  const add = document.getElementById("bdadd");
  if (add) add.onclick = async () => {
    const d = document.getElementById("bdd").value; if (!d) return toast("Pick a date", true);
    await call(() => RX.api(`/api/plans/${p.id}/burn-days`, { method: "POST", body: { burn_date: d } })); showPlan(p.id);
  };
  root.querySelectorAll("button[data-bd]").forEach((b) => (b.onclick = () => openBurnDay(+b.dataset.bd)));
}
async function openBurnDay(id) {
  const bd = await call(() => RX.api(`/api/burn-days/${id}`));
  const fc = bd.forecast;
  const cls = !fc ? "" : fc.verdict.startsWith("GO") ? "go" : fc.verdict.startsWith("PARTIAL") ? "part" : "no";
  const v = S.plan.variants;
  document.getElementById("bdv").innerHTML = `<h4>Burn day ${bd.burn_date}</h4>
    <div class="row-actions">${can("planner") ? '<button class="btn" id="fx">Get burn-day forecast</button>' : ""}<span class="hint">${fc ? `${esc(fc.source)} · ${esc(fc.stage)} · issued ${fc.issued_at.slice(0, 16).replace("T", " ")}` : "No forecast frozen yet."}</span></div>
    ${fc ? `<div class="verdict ${cls}" style="margin-top:8px">${esc(fc.verdict)}</div>
      <div class="hours" aria-label="Hourly check 06:00 to 21:00">${fc.hours.map((h) => `<div class="${h.ok_for_variant ? "go" : "no"} ${h.ignition_period ? "ign" : ""}" title="${h.hour}:00 · ${h.temp_c}°C ${h.rh_pct}% ${h.wind_kmh} km/h from ${h.wind_dir_deg}°${h.fails.length ? " · " + h.fails.join("; ") : ""}">${h.hour}</div>`).join("")}</div>
      <p class="hint">Outlined hours are the ignition period. GO windows: ${fc.go_windows.join(", ") || "none"}. Suggested variant: <b>${esc(fc.suggested_variant || "none")}</b>.
      ${fc.unchecked_params.length ? `Not in the forecast, check separately: ${fc.unchecked_params.map((k) => RX.PARAMS[k] || k).join(", ")}.` : ""}</p>` : ""}
    <h4>Go / no-go checklist (Element 2B)</h4>
    ${CHECKLIST.map(([k, l]) => `<label style="display:flex;gap:8px;padding:3px 0;font-size:14px"><input type="checkbox" data-ck="${k}" ${bd.checklist?.[k]?.ok ? "checked" : ""}> ${l}</label>`).join("")}
    <div class="field" style="margin-top:8px"><label for="bdvar">Ignition variant</label><select id="bdvar"><option value="">—</option>${v.map((x) => `<option value="${x.id}" ${bd.variant_id === x.id ? "selected" : ""}>${esc(x.name)} (${x.wind_dir_min}–${x.wind_dir_max}°)</option>`).join("")}</select></div>
    <div class="field"><label for="bdtf">Test fire result</label><input id="bdtf" value="${esc(bd.test_fire_result || "")}"></div>
    <div class="field"><label for="bdn">Notes</label><textarea id="bdn">${esc(bd.notes || "")}</textarea></div>
    <div class="row-actions"><button class="btn" id="bdsave">Save</button>
      ${can("burn_boss") ? '<button class="btn primary" id="bdgo">Decision: GO</button><button class="btn danger" id="bdno">Decision: NO-GO</button>' : ""}
      <span class="hint">${bd.decided_at ? `Decided ${bd.decision} by ${esc(bd.decided_by)} at ${bd.decided_at.slice(0, 16).replace("T", " ")}` : ""}</span></div>`;
  const body = (decision) => {
    const checklist = {}; document.querySelectorAll("[data-ck]").forEach((c) => (checklist[c.dataset.ck] = { ok: c.checked }));
    const vv = document.getElementById("bdvar").value;
    return { checklist, variant_id: vv ? +vv : null, test_fire_result: document.getElementById("bdtf").value, notes: document.getElementById("bdn").value, ...(decision ? { decision } : {}) };
  };
  const save = (decision) => async () => {
    if (decision === "go" && !confirm("Record a GO decision for this burn day?")) return;
    await call(() => RX.api(`/api/burn-days/${id}`, { method: "PUT", body: body(decision) })); toast("Burn day saved");
    if (decision) { await showPlan(S.plan.id, "burn"); } openBurnDay(id);
  };
  document.getElementById("bdsave").onclick = save();
  const g = document.getElementById("bdgo"); if (g) g.onclick = save("go");
  const n = document.getElementById("bdno"); if (n) n.onclick = save("no_go");
  const fx = document.getElementById("fx");
  if (fx) fx.onclick = async () => { fx.disabled = true; fx.textContent = "Fetching…"; await call(() => RX.api(`/api/burn-days/${id}/forecast`, { method: "POST", body: {} })).finally(() => (fx.disabled = false)); openBurnDay(id); };
}

// Versions
function panelVersions(root) {
  const p = S.plan;
  root.insertAdjacentHTML("beforeend", `<p class="hint">Approved plans are locked. An amendment copies the plan into a new draft version; the approved version keeps the data it was approved on.</p>
    <table class="grid"><thead><tr><th>Version</th><th>Status</th><th>Amendment</th><th></th></tr></thead><tbody>
    ${p.versions.map((v) => `<tr><td>v${v.version_no}</td><td><span class="badge ${v.status}">${v.status}</span></td><td>${esc(v.amendment_note || "")}</td>
      <td>${v.id === p.id ? "<b>this</b>" : `<a href="#plan/${v.id}">open</a>`}</td></tr>`).join("")}
    ${p.successor ? `<tr><td colspan="3">A newer version exists.</td><td><a href="#plan/${p.successor.id}">open</a></td></tr>` : ""}</tbody></table>
    <h4>Signatures (Element 1)</h4><div id="sigbox"></div>`);
  panelSignatures(document.getElementById("sigbox"));
}
function panelSignatures(root) {
  const p = S.plan;
  root.insertAdjacentHTML("beforeend", `${p.signatures.map((s) => `<div class="feat"><span class="lbl">${esc(s.role.replace(/_/g, " "))}: <b>${esc(s.name)}</b> ${esc(s.qualification || "")}</span><span class="m">${s.signed_at.slice(0, 10)}</span></div>`).join("") || '<p class="hint">None recorded.</p>'}
    ${can("planner") ? `<form id="sig" class="row-actions"><select name="role"><option value="preparer">Preparer</option><option value="technical_reviewer">Technical reviewer</option><option value="agency_administrator">Agency administrator</option><option value="burn_boss">Burn boss</option></select>
      <input name="sname" placeholder="Name" required style="flex:1;border:1px solid #b9b4a8;border-radius:6px;padding:6px"><input name="qual" placeholder="Qualification" style="width:110px;border:1px solid #b9b4a8;border-radius:6px;padding:6px"><button class="btn small">Record</button></form>` : ""}`);
  const f = root.querySelector("#sig");
  if (f) f.onsubmit = async (e) => { e.preventDefault(); await call(() => RX.api(`/api/plans/${p.id}/signatures`, { method: "POST", body: { role: f.role.value, name: f.sname.value, qualification: f.qual.value } })); showPlan(p.id); };
}

route();
