// Shared by the desktop editor and the mobile review view.
const RX = {};

RX.api = async (path, opts = {}) => {
  const o = { credentials: "same-origin", headers: {}, ...opts };
  if (o.body && typeof o.body !== "string") { o.body = JSON.stringify(o.body); o.headers["Content-Type"] = "application/json"; }
  const r = await fetch(path, o);
  if (r.status === 401) { const e = new Error("login required"); e.status = 401; throw e; }
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    const e = new Error(msg); e.status = r.status; throw e;
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r;
};

RX.esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Plan feature kinds: label, geometry to draw, style.
RX.KINDS = {
  burn_unit:        { label: "Burn unit",        draw: "Polygon", color: "#111111", weight: 3, fill: "#fbe7c6", fillOpacity: 0.25 },
  ignition_unit:    { label: "Ignition unit",    draw: "Polygon", color: "#c62828", weight: 2, dash: "8 5", fillOpacity: 0 },
  contingency_area: { label: "Contingency area", draw: "Polygon", color: "#e08a00", weight: 3, dash: "12 6", fill: "#e08a00", fillOpacity: 0.05 },
  holding_line:     { label: "Holding line",     draw: "Line",    color: "#8b5a2b", weight: 6 },
  contingency_line: { label: "Contingency line", draw: "Line",    color: "#e08a00", weight: 4, dash: "12 6" },
  firing_line:      { label: "Firing line",      draw: "Line",    color: "#c62828", weight: 3 },
  escape_route:     { label: "Escape route",     draw: "Line",    color: "#2e7d32", weight: 3, dash: "8 5" },
  trigger_point:    { label: "Trigger point",    draw: "Marker",  color: "#e08a00", symbol: "◆" },
  safety_zone:      { label: "Safety zone",      draw: "Marker",  color: "#2e7d32", symbol: "SZ" },
  anchor_point:     { label: "Anchor point",     draw: "Marker",  color: "#111111", symbol: "▲" },
  test_fire_site:   { label: "Test fire site",   draw: "Marker",  color: "#c62828", symbol: "★" },
  drop_point:       { label: "Drop point / ICP", draw: "Marker",  color: "#111111", symbol: "DP" },
  lookout:          { label: "Lookout",          draw: "Marker",  color: "#111111", symbol: "L" },
  other:            { label: "Other",            draw: "Marker",  color: "#555555", symbol: "•" },
};

RX.PARAMS = {
  temp_c: "Temperature °C", rh_pct: "RH %", wind_kmh: "10-m wind km/h", gust_kmh: "Gusts km/h", wind_dir_deg: "Wind dir °",
  ffmc: "FFMC", isi: "ISI", bui: "BUI", fwi: "FWI", dmc: "DMC", dc: "DC", curing_pct: "Curing %",
  mixing_height_m: "Mixing height m", vent_index: "Ventilation index", precip_mm: "Rain mm/h",
};

RX.featureLayer = (fc, onEach) => L.geoJSON(fc, {
  style: (f) => {
    const k = RX.KINDS[f.properties.kind] || RX.KINDS.other;
    return { color: k.color, weight: k.weight || 2, dashArray: k.dash, fillColor: k.fill || k.color, fillOpacity: k.fillOpacity ?? 0.1 };
  },
  pointToLayer: (f, ll) => {
    const k = RX.KINDS[f.properties.kind] || RX.KINDS.other;
    return L.marker(ll, { icon: L.divIcon({ className: "rx-pt", html: `<span style="background:${k.color}">${RX.esc(k.symbol)}</span><b>${RX.esc(f.properties.label || "")}</b>`, iconSize: null }) });
  },
  onEachFeature: (f, l) => {
    const p = f.properties, k = RX.KINDS[p.kind] || RX.KINDS.other;
    const m = p.area_ha ? `${p.area_ha} ha` : (p.length_m ? `${Math.round(p.length_m)} m` : "");
    l.bindTooltip(`<b>${RX.esc(p.label || k.label)}</b><br>${RX.esc(k.label)}${m ? " · " + m : ""}`, { sticky: true });
    if (onEach) onEach(f, l);
  },
});

RX.layerStyle = (meta) => (f) => {
  const s = meta.style || {}, p = f.properties || {};
  let color = s.color || "#555";
  if (meta.name === "infra.asset") color = { high: "#d84315", moderate: "#f2a900", low: "#888" }[p.vulnerability] || color;
  if (meta.name === "fuels.fuel_class") color = { mixed_grass: "#c9b458", grass_juniper: "#8fa83a", juniper: "#3f6b3a", aspen: "#5f9f8a", shrub: "#a87a50" }[p.fuel_class] || color;
  if (meta.name === "smoke.receptor") color = { high: "#b3261e", moderate: "#b26a00", low: "#666" }[p.sensitivity] || color;
  const proposed = meta.name === "habitat.critical_habitat" && p.status === "proposed";
  return { color, weight: s.weight || 2, dashArray: proposed ? "6 4" : s.dash, fillColor: color,
           fillOpacity: s.fill ? (meta.name === "fuels.fuel_class" ? 0.45 : proposed ? 0.08 : 0.18) : 0.05 };
};

// Readable popup lines for layers whose raw attributes are noisy.
RX.popupLines = (meta, p) => {
  if (meta.name !== "habitat.critical_habitat") return null;
  const v = p.valid && p.valid.from ? p.valid.from.slice(0, 10) : "";
  return [p.population && p.population !== p.species ? RX.esc(p.population) : "", p.sci_name ? `<i>${RX.esc(p.sci_name)}</i>` : "",
    `${p.status === "proposed" ? "Proposed" : "Final"} critical habitat${p.site_name ? " · " + RX.esc(p.site_name) : ""}${p.grid_id ? " · " + RX.esc(p.grid_id) : ""}`,
    p.source_doc ? RX.esc(p.source_doc) : "", p.sensitivity ? `Sensitivity: ${RX.esc(p.sensitivity)}` : "",
    p.source === "eccc_national" ? `ECCC national dataset${v ? ", in force from " + v : ""}` : (p.source_doc ? "" : "Loaded by hand")]
    .filter(Boolean).join("<br>");
};

// "ECCC 2026-06-15 · checked 2026-11-23" for synced layers.
RX.layerNote = (l) => l.note ? ` <span class="hint">(${RX.esc(l.note)})</span>` : l.sync ? ` <span class="hint">(ECCC ${RX.esc((l.sync.remote_modified || "").slice(0, 10) || "?")}, checked ${l.sync.checked_at.slice(0, 10)}${l.sync.status === "failed" ? ", last check failed" : ""})</span>` : "";

RX.landscapeLayer = (meta, fc) => L.geoJSON(fc, {
  style: RX.layerStyle(meta),
  pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 6, ...RX.layerStyle(meta)(f), fillOpacity: 0.85, weight: 1.5, color: "#222" }),
  onEachFeature: (f, l) => {
    const p = f.properties;
    const name = p.name || p.species || p.fuel_class || p.plot_code || p.kind || meta.title;
    const custom = RX.popupLines(meta, p);
    const bits = custom != null ? custom : Object.entries(p).filter(([k, v]) => v !== null && v !== "" && !["feature_id", "row_id", "valid", "release_id", "changed_by", "source_event", "id", "event_id", "recorded_by", "recorded_at"].includes(k))
      .slice(0, 8).map(([k, v]) => `${RX.esc(k)}: ${RX.esc(typeof v === "object" ? JSON.stringify(v) : v)}`).join("<br>");
    l.bindPopup(`<b>${RX.esc(name)}</b><br><span style="color:#666">${RX.esc(meta.title)}</span><br>${bits}`);
  },
});

RX.basemaps = () => ({
  "Imagery": L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, attribution: "Esri, Maxar, Earthstar Geographics" }),
  "Topographic": L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, attribution: "Esri" }),
  "OpenStreetMap": L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap contributors" }),
});

// Field-of-view wedge for a photo taken at (lat, lon) facing `heading` (deg from north) with a horizontal `fov`.
RX.fovWedge = (lat, lon, heading, fov, radiusM = 80, style = {}) => {
  const pts = [[lat, lon]], mLat = 111320, mLon = 111320 * Math.cos(lat * Math.PI / 180);
  for (let a = heading - fov / 2; a <= heading + fov / 2 + 0.01; a += fov / 12) {
    const r = a * Math.PI / 180;
    pts.push([lat + (radiusM * Math.cos(r)) / mLat, lon + (radiusM * Math.sin(r)) / mLon]);
  }
  return L.polygon(pts, { color: "#00838f", weight: 1.5, fillColor: "#00e5ff", fillOpacity: 0.25, ...style });
};
RX.compassName = (d) => d == null ? "" : ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(((d % 360) + 360) % 360 / 45) % 8];

// Raster layers (terrain tiles drawn from the DEM).
RX.rasterLayer = (meta) => L.tileLayer(meta.tiles, { opacity: (meta.style || {}).opacity ?? 0.6, minZoom: 0, maxZoom: 20,
  minNativeZoom: meta.min_zoom, maxNativeZoom: meta.native_zoom, bounds: meta.bounds, zIndex: 250,
  attribution: "Terrain: NRCan HRDEM / MRDEM; GEM-15 by Google (CC-BY 4.0)" });
