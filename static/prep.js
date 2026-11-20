// rx desktop: pre-burn work. Jobs that lower a burn's complexity, drawn where they go, with width and
// standard, and followed through planned → assigned → done → verified.
const PREP_STATUS = { planned: ["#b3261e", "Planned"], assigned: ["#e08a00", "Assigned"], done: ["#1565c0", "Done"], verified: ["#2e7d32", "Verified"], not_needed: ["#9e9e9e", "Not needed"] };
const PREP_DRAW = { mulch: "Line", mow: "Line", disc: "Line", grade: "Line", wet_line: "Line", black_line: "Line", brush_removal: "Polygon",
  snag_felling: "Polygon", protect_asset: "Marker", water: "Marker", signage: "Marker", other: "Line" };
const PREP_DEFAULT_WIDTH = { mulch: 6, mow: 10, disc: 3, grade: 4, wet_line: 1, black_line: 30 };
const COMPLEXITY = ["Off-site values", "On-site values", "Public and political interest", "Safety", "Fire behavior", "Resistance to containment",
  "Ignition procedures / methods", "Prescribed fire duration", "Smoke management", "Number and dependence of activities", "Management organization",
  "Treatment / resource objectives", "Constraints", "Project logistics"];

function prepLayer(fc, onClick) {
  const g = L.featureGroup();
  for (const f of fc.features) {
    const p = f.properties, [col] = PREP_STATUS[p.status] || ["#555"];
    if (p.band) L.geoJSON(p.band, { style: { color: col, weight: 1, fillColor: col, fillOpacity: 0.3, dashArray: p.status === "planned" ? "4 3" : null }, interactive: false }).addTo(g);
    const l = L.geoJSON(f, {
      style: { color: col, weight: p.band ? 2 : 4, fillColor: col, fillOpacity: 0.25, dashArray: p.status === "planned" ? "8 5" : null },
      pointToLayer: (_, ll) => L.marker(ll, { icon: L.divIcon({ className: "rx-pt", html: `<span style="background:${col}">W</span>`, iconSize: null }) }),
    }).bindTooltip(`<b>${RX.esc(p.title)}</b><br>${RX.esc(p.kind_label)}${p.width_m ? ` · ${p.width_m} m wide` : ""}<br>${PREP_STATUS[p.status][1]}`, { sticky: true });
    l.taskId = f.id; if (onClick) l.on("click", () => onClick(f.id));
    l.addTo(g);
  }
  return g;
}

async function panelPrep(root) {
  const p = S.plan, ro = locked() || !can("planner");
  const [fc, sum, kinds] = await call(() => Promise.all([RX.api(`/api/plans/${p.id}/prep`), RX.api(`/api/plans/${p.id}/prep/summary`), S.prepKinds || RX.api("/api/prep/kinds")]));
  S.prepKinds = kinds;
  if (S.prepLayer) S.map.removeLayer(S.prepLayer);
  S.prepLayer = prepLayer(fc, (id) => { const el = document.querySelector(`.ptask[data-id="${id}"]`); if (el) { el.scrollIntoView({ block: "center" }); el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1200); } }).addTo(S.map);
  const open = sum.outstanding_for_ignition;
  root.insertAdjacentHTML("beforeend", `
    <div class="prep-sum">${Object.entries(PREP_STATUS).map(([k, [c, l]]) => `<span class="pill"><span class="sw" style="background:${c}"></span>${l} <b>${sum.by_status[k] || 0}</b></span>`).join("")}</div>
    ${open.length ? `<div class="locked">Not yet verified, needed before ignition: ${open.map((w) => esc(w.title)).join(", ")}. A GO decision on a burn day is blocked until these are verified.</div>` : sum.total ? '<div class="ok-note">All work needed before ignition is verified.</div>' : ""}
    ${Object.keys(sum.by_kind).length ? `<table class="grid"><thead><tr><th>Work</th><th class="num">Jobs</th><th class="num">Length</th><th class="num">Area</th></tr></thead><tbody>
      ${Object.entries(sum.by_kind).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${v.n}</td><td class="num">${v.length_m ? (v.length_m / 1000).toFixed(2) + " km" : "—"}</td><td class="num">${v.area_ha ? v.area_ha.toFixed(2) + " ha" : "—"}</td></tr>`).join("")}</tbody></table>` : ""}
    <div class="row-actions">${ro ? "" : '<button class="btn primary" id="padd">Add work</button>'}
      <a class="btn small" href="/api/plans/${p.id}/prep.csv">Work order (.csv)</a><a class="btn small" href="/api/plans/${p.id}/prep.geojson">GeoJSON for GPS</a></div>
    <div id="pform"></div>
    <div id="plist">${fc.features.map((f) => prepRow(f.properties)).join("") || '<p class="hint">No pre-burn work yet. Add the jobs that make this burn safer and easier to hold, e.g. mulching along control lines.</p>'}</div>`);
  const add = document.getElementById("padd"); if (add) add.onclick = () => prepForm(null);
  root.querySelectorAll(".ptask").forEach((el) => {
    const id = el.dataset.id, t = fc.features.find((f) => f.id === id).properties;
    el.querySelector("[data-a=zoom]").onclick = () => { const l = S.prepLayer.getLayers().find((x) => x.taskId === id); if (l) { const b = l.getBounds ? l.getBounds() : null; b && b.isValid() ? S.map.fitBounds(b.pad(0.3), { maxZoom: 17 }) : S.map.setView(l.getLayers()[0].getLatLng(), 17); } };
    const st = el.querySelector("[data-a=status]"); if (st) st.onclick = () => prepStatusForm(el, t);
    const ed = el.querySelector("[data-a=edit]"); if (ed) ed.onclick = () => prepForm(t);
    const dl = el.querySelector("[data-a=del]"); if (dl) dl.onclick = async () => { if (confirm(`Delete "${t.title}"?`)) { await call(() => RX.api(`/api/prep/${id}`, { method: "DELETE" })); showPlan(S.plan.id); } };
    el.querySelector("[data-a=hist]").onclick = () => {
      const h = el.querySelector(".phist"); h.hidden = !h.hidden;
      h.innerHTML = (t.events || []).map((e) => `<div><b>${PREP_STATUS[e.status] ? PREP_STATUS[e.status][1] : e.status}</b> · ${e.at.slice(0, 16).replace("T", " ")} · ${esc(e.by || "")}
        ${e.measured && e.measured.width_m ? ` · measured ${e.measured.width_m} m wide` : ""}${e.note ? `<br>${esc(e.note)}` : ""}${e.record_id ? ' <span class="hint">(site visit)</span>' : ""}
        ${(e.media || []).map((m) => `<a href="/api/media/${m}" target="_blank"><img src="/api/media/${m}?size=thumb" alt="Photo" class="pthumb"></a>`).join("")}</div>`).join("");
    };
  });
}

function prepRow(t) {
  const [col, lab] = PREP_STATUS[t.status], ro = !can("planner");
  const qty = t.width_m ? `${t.width_m} m wide × ${Math.round(t.length_m)} m` : t.area_ha ? `${t.area_ha} ha` : "point";
  return `<div class="ptask" data-id="${t.id}"><div class="pt-top"><span class="sw" style="background:${col}"></span><b>${esc(t.title)}</b><span class="spacer"></span><span class="pstatus" style="border-color:${col};color:${col}">${lab}</span></div>
    <div class="br-meta">${esc(t.kind_label)} · ${qty}${t.depth_cm ? ` · ${t.depth_cm} cm deep` : ""}${t.dac_required ? " · DAC clearance needed" : ""}</div>
    ${t.spec ? `<div class="br-meta">Standard: ${esc(t.spec)}</div>` : ""}
    <div class="br-meta">Needed before ${t.required_for}${t.required_by ? ` · by ${t.required_by}` : ""}${t.assigned_to ? ` · ${esc(t.assigned_to)}` : ""}${t.mitigates && t.mitigates.length ? ` · lowers: ${t.mitigates.map(esc).join(", ")}` : ""}</div>
    <div class="row-actions"><button class="btn small" data-a="zoom">Map</button>${ro ? "" : '<button class="btn small" data-a="status">Update status</button>'}
      ${ro || locked() ? "" : '<button class="btn small" data-a="edit">Edit</button><button class="btn small danger" data-a="del" aria-label="Delete">✕</button>'}
      <button class="btn small" data-a="hist">History (${(t.events || []).length})</button></div><div class="phist" hidden></div><div class="pstat"></div></div>`;
}

function prepStatusForm(el, t) {
  const box = el.querySelector(".pstat");
  box.innerHTML = `<div class="inline-form"><div class="field"><label>New status</label><select name="st">${Object.entries(PREP_STATUS).map(([k, [, l]]) => `<option value="${k}" ${k === t.status ? "selected" : ""}>${l}</option>`).join("")}</select></div>
    ${t.width_m ? '<div class="field"><label>Measured width (m)</label><input name="w" type="number" step="0.1"></div>' : ""}
    <div class="field" style="grid-column:1/-1"><label>Note</label><input name="note" placeholder="Who did it, what was found"></div>
    <div class="row-actions"><button class="btn primary small" data-s>Save status</button><button class="btn small" data-c>Cancel</button></div>
    <p class="hint" style="grid-column:1/-1">Verification is best done on site with the mobile view (Site visit → Prep work), which adds GPS position and photos.</p></div>`;
  box.querySelector("[data-c]").onclick = () => (box.innerHTML = "");
  box.querySelector("[data-s]").onclick = async () => {
    const w = box.querySelector("[name=w]");
    await call(() => RX.api(`/api/prep/${t.id}/events`, { method: "POST", body: { status: box.querySelector("[name=st]").value, note: box.querySelector("[name=note]").value, measured: w && w.value ? { width_m: +w.value } : {} } }));
    toast("Status saved"); showPlan(S.plan.id);
  };
}

function prepForm(t) {
  const k = (S.prepKinds || []), v = t || { kind: "mulch", width_m: 6, required_for: "ignition", mitigates: [], dac_required: false };
  const box = document.getElementById("pform");
  box.innerHTML = `<form class="inline-form" id="pf"><h4 style="grid-column:1/-1;margin:0">${t ? "Edit work" : "New pre-burn work"}</h4>
    <div class="field"><label for="pk">Work</label><select id="pk" name="kind">${k.map((x) => `<option value="${x.key}" ${x.key === v.kind ? "selected" : ""}>${esc(x.label)}</option>`).join("")}</select></div>
    <div class="field"><label for="pt">Title</label><input id="pt" name="title" required value="${esc(v.title || "")}" placeholder="e.g. Mulch along N control line"></div>
    <div class="field"><label for="pw">Width (m)</label><input id="pw" name="width_m" type="number" step="0.5" value="${v.width_m ?? ""}"></div>
    <div class="field"><label for="pd">Depth (cm)</label><input id="pd" name="depth_cm" type="number" step="1" value="${v.depth_cm ?? ""}"></div>
    <div class="field" style="grid-column:1/-1"><label for="ps">Standard to meet</label><input id="ps" name="spec" value="${esc(v.spec || "")}" placeholder="e.g. vegetation mulched to < 10 cm, juniper removed, no gaps"></div>
    <div class="field"><label for="prf">Needed before</label><select id="prf" name="required_for"><option value="ignition">ignition</option><option value="approval">approval</option><option value="none">not required</option></select></div>
    <div class="field"><label for="prb">Needed by (date)</label><input id="prb" name="required_by" type="date" value="${v.required_by || ""}"></div>
    <div class="field"><label for="pa">Assigned to</label><input id="pa" name="assigned_to" value="${esc(v.assigned_to || "")}" placeholder="crew / contractor"></div>
    <div class="field"><label class="chipbox" style="margin-top:22px"><input type="checkbox" name="dac_required" ${v.dac_required ? "checked" : ""}><span>DAC clearance needed</span></label></div>
    <div class="field" style="grid-column:1/-1"><span class="flabel">Lowers these complexity elements</span><div class="chips">${COMPLEXITY.map((c) => `<label class="chipbox"><input type="checkbox" name="mit" value="${esc(c)}" ${(v.mitigates || []).includes(c) ? "checked" : ""}><span>${esc(c)}</span></label>`).join("")}</div></div>
    <div class="row-actions" style="grid-column:1/-1"><button class="btn primary">${t ? "Save" : "Draw it on the map"}</button>${t ? '<button type="button" class="btn small" id="pgeom">Redraw on map</button>' : ""}<button type="button" class="btn small" id="pcancel">Cancel</button>
      <span class="hint" id="pdrawhint"></span></div></form>`;
  const f = document.getElementById("pf");
  f.required_for.value = v.required_for || "ignition";
  f.kind.onchange = () => { if (PREP_DEFAULT_WIDTH[f.kind.value] && !f.width_m.value) f.width_m.value = PREP_DEFAULT_WIDTH[f.kind.value]; };
  document.getElementById("pcancel").onclick = () => (box.innerHTML = "");
  const data = () => ({ kind: f.kind.value, title: f.title.value, width_m: f.width_m.value === "" ? null : +f.width_m.value, depth_cm: f.depth_cm.value === "" ? null : +f.depth_cm.value,
    spec: f.spec.value, required_for: f.required_for.value, required_by: f.required_by.value || null, assigned_to: f.assigned_to.value, dac_required: f.dac_required.checked,
    mitigates: [...f.querySelectorAll("[name=mit]:checked")].map((x) => x.value) });
  const startDraw = (onDone) => {
    const shape = PREP_DRAW[f.kind.value] || "Line";
    S.mode = "prep"; S.prepPending = onDone;
    S.map.pm.enableDraw(shape, { continueDrawing: false });
    document.getElementById("pdrawhint").textContent = shape === "Line" ? "Click along the line; click the last point again to finish." : shape === "Polygon" ? "Click around the area; click the first point to finish." : "Click the spot.";
  };
  f.onsubmit = (e) => {
    e.preventDefault();
    if (!f.title.value) return;
    if (!t) return startDraw(async (geom) => { await call(() => RX.api(`/api/plans/${S.plan.id}/prep`, { method: "POST", body: { ...data(), geom } })); toast("Work added"); showPlan(S.plan.id); });
    call(() => RX.api(`/api/prep/${t.id}`, { method: "PUT", body: data() })).then(() => { toast("Saved"); showPlan(S.plan.id); });
  };
  const rg = document.getElementById("pgeom");
  if (rg) rg.onclick = () => startDraw(async (geom) => { await call(() => RX.api(`/api/prep/${t.id}`, { method: "PUT", body: { ...data(), geom } })); toast("Location saved"); showPlan(S.plan.id); });
  f.title.focus();
}

// Element 9 component: the work list in brief.
async function panelPrepComponent(root) {
  const fc = await call(() => RX.api(`/api/plans/${S.plan.id}/prep`));
  root.innerHTML = fc.features.length ? `<table class="grid"><thead><tr><th>Work</th><th>Size</th><th>Needed before</th><th>Status</th></tr></thead><tbody>
    ${fc.features.map((f) => { const t = f.properties; return `<tr><td>${esc(t.title)}<div class="hint">${esc(t.kind_label)}${t.spec ? " · " + esc(t.spec) : ""}</div></td>
      <td>${t.width_m ? `${t.width_m} m × ${Math.round(t.length_m)} m` : t.area_ha ? t.area_ha + " ha" : "point"}</td><td>${t.required_for}</td>
      <td><span class="pstatus" style="border-color:${PREP_STATUS[t.status][0]};color:${PREP_STATUS[t.status][0]}">${PREP_STATUS[t.status][1]}</span></td></tr>`; }).join("")}</tbody></table>
    <a class="btn small" href="#plan/${S.plan.id}/prep">Open pre-burn work on the map ›</a>`
    : `<p class="hint">No pre-burn work yet.</p><a class="btn small" href="#plan/${S.plan.id}/prep">Add pre-burn work on the map ›</a>`;
}
