// The burn program level: the season's operation order, meetings and people.
const Program = (() => {
  const P = { people: [], schema: null, year: null };
  const e = (x) => RX.esc(x == null ? "" : x);
  const fullName = (p) => [p.rank, p.name].filter(Boolean).join(" ");

  async function loadPeople() {
    [P.people, P.schema] = await Promise.all([RX.api("/api/people"), P.schema ? P.schema : RX.api("/api/opord-schema")]);
    let dl = document.getElementById("dl-people");
    if (!dl) { dl = document.createElement("datalist"); dl.id = "dl-people"; document.body.appendChild(dl); }
    dl.innerHTML = P.people.filter((p) => p.active).map((p) => `<option value="${e(p.name)}">${e([p.appointment, p.quals.join(" ")].filter(Boolean).join(" · "))}</option>`).join("");
  }

  // Is this person recorded as qualified for this Element 11 position?
  function check(name, position) {
    const needs = (P.schema.position_qual || {})[position || ""];
    const p = P.people.find((x) => x.name.toLowerCase() === name.toLowerCase());
    if (!p) return { needs, text: "not in People", ok: null };
    const quals = p.quals.join(", ");
    if (!needs) return { needs, quals, text: "", ok: null };
    if (!p.quals.length) return { needs, quals, text: "no quals recorded", ok: null };
    const ok = needs.startsWith("RXB") ? p.quals.some((q) => /^RXB\d$/.test(q) && +q[3] <= +needs[3]) : p.quals.includes(needs);
    return { needs, quals, ok, text: ok ? "qualified" : `needs ${needs}` };
  }

  const tabs = (on) => `<nav class="ptabs" aria-label="Burn program">${[["map", "Map", "#"], ["opord", "Op order", "#program/opord"], ["meetings", "Meetings", "#program/meetings"], ["people", "People", "#program/people"]]
    .map(([k, l, h]) => `<a href="${h}" ${k === on ? 'aria-current="page"' : ""}>${l}</a>`).join("")}</nav>`;

  async function show(page, id) {
    S.view = "program-" + page; S.plan = null; S.mode = "program";
    await loadPeople();
    const seasons = await call(() => RX.api("/api/seasons"));
    if (!P.year || !seasons.some((s) => s.year === P.year)) P.year = (seasons[0] || {}).year || null;
    const sel = seasons.length ? `<label class="hint" for="yr">Season</label><select id="yr">${seasons.map((s) => `<option value="${s.year}" ${s.year === P.year ? "selected" : ""}>${s.year} · ${e(s.op_name || "")}</option>`).join("")}</select>` : "";
    view.innerHTML = `<div class="ws-bar"><h2>Burn program</h2>${tabs(page)}<span class="spacer"></span>${page === "people" ? "" : sel}
        ${can("planner") && page === "opord" ? '<button class="btn small" id="newyr">New season</button>' : ""}</div><div id="pg" class="pg"></div>`;
    const yr = document.getElementById("yr"); if (yr) yr.onchange = () => { P.year = +yr.value; show(page, null); };
    const ny = document.getElementById("newyr"); if (ny) ny.onclick = () => newSeason(seasons);
    const pg = document.getElementById("pg");
    if (page === "opord") return opord(pg, seasons);
    if (page === "meetings") return meetingsPage(pg, id);
    return peoplePage(pg);
  }

  // ------------------------------------------------------------------ operation order
  async function newSeason(seasons) {
    const year = +prompt("Season (year)", String(Math.max(new Date().getFullYear(), ...seasons.map((s) => s.year + 1))));
    if (!year) return;
    const from = seasons.length ? prompt(`Carry the operation order forward from which season? (blank for the template)`, String(seasons[0].year)) : "";
    await call(() => RX.api("/api/seasons", { method: "POST", body: { year, copy_from: from ? +from : null } }));
    P.year = year; toast(`${year} season started${from ? `: copied from ${from}, dates cleared` : ""}`); show("opord");
  }

  function autoProgram(src, ctx) {
    if (src === "season_blocks") return ctx.blocks.length ? `<table class="grid"><thead><tr><th>Burn block</th><th class="num">ha</th><th>Complexity</th><th>Window</th><th>Status</th></tr></thead><tbody>${ctx.blocks.map((b) =>
      `<tr><td><a href="#plan/${b.id}">${e(b.name)}</a></td><td class="num">${b.area_ha ?? ""}</td><td>${e(b.complexity)}</td><td>${e(b.planned_window)}</td><td><span class="badge ${b.status}">${b.status}</span></td></tr>`).join("")}
      <tr><td><b>Total</b></td><td class="num"><b>${ctx.total_ha}</b></td><td colspan="3"></td></tr></tbody></table>` : `<span class="hint">No burn blocks in the ${P.year} season yet. Add them on the <a href="#">program map</a>.</span>`;
    if (src === "season_resources") {
      if (!ctx.positions.length && !ctx.equipment.length) return '<span class="hint">Nothing yet: fill in Element 11 (positions and equipment) in the burn plans.</span>';
      return `<div class="two"><table class="grid"><thead><tr><th>Position</th><th class="num">Number</th></tr></thead><tbody>${ctx.positions.map((r) => `<tr><td>${e(r.position)}</td><td class="num">${r.qty}</td></tr>`).join("")}</tbody></table>
        <table class="grid"><thead><tr><th>Equipment</th><th class="num">Number</th></tr></thead><tbody>${ctx.equipment.map((r) => `<tr><td>${e(r.type)}</td><td class="num">${r.qty}</td></tr>`).join("")}</tbody></table></div>`;
    }
    if (src === "season_pocs") return ctx.pocs.length ? `<table class="grid"><thead><tr><th>Name</th><th>Appointment</th><th>Organization</th><th>Phone</th></tr></thead><tbody>${ctx.pocs.map((p) =>
      `<tr><td>${e(fullName(p))}</td><td>${e(p.appointment)}</td><td>${e(p.organization)}</td><td>${e(p.phone)}</td></tr>`).join("")}</tbody></table>` : '<span class="hint">Mark people as a point of contact on the <a href="#program/people">People</a> page.</span>';
    return "";
  }

  async function opord(pg, seasons) {
    if (!P.year) {
      pg.innerHTML = `<div class="doc"><h2 class="doc-title">Operation order</h2><p>Each burn season has an operation order that the Base Commander signs: situation, mission, execution, resources, service support, and command and signals.</p>
        ${can("planner") ? '<p><button class="btn primary" id="first">Start a season</button></p>' : ""}${importBox()}</div>`;
      const f = document.getElementById("first"); if (f) f.onclick = () => newSeason(seasons);
      return wireImport();
    }
    const s = await call(() => RX.api(`/api/seasons/${P.year}`));
    const ro = s.status === "signed" || !can("planner");
    pg.innerHTML = `<div class="pv"><nav class="pv-nav" aria-label="Operation order sections"><div class="nav-sec">Op order ${P.year}</div>
        ${P.schema.sections.map((sec, i) => `<button type="button" class="nav-item" data-sec="${i}"><span></span><span class="nc">${i + 1}</span><span>${e(sec.section)}</span></button>`).join("")}
        <div class="nav-sec">Record</div><button type="button" class="nav-item" data-sec="sig"><span></span><span class="nc">✓</span><span>Signature and revisions</span></button></nav>
      <section class="pv-main"><div class="doc">
        <div class="el-headbar"><div><div class="owner">Revision ${s.revision} · ${s.status === "signed" ? `signed by ${e(s.signed_name)} ${String(s.signed_at).slice(0, 10)}` : "draft"}</div>
          <h2 class="doc-title"><input id="opname" class="title-in" value="${e(s.op_name)}" placeholder="Op name" ${ro ? "readonly" : ""} aria-label="Operation name"></h2></div>
          <div class="el-actions"><span class="badge ${s.status === "signed" ? "approved" : "draft"}">${s.status}</span>
            <a class="btn small" href="/api/seasons/${P.year}/opord.docx">Word</a>${ro ? "" : '<button class="btn primary" id="osave">Save</button>'}</div></div>
        ${s.status === "signed" ? `<div class="ok-note">Signed. ${can("planner") ? 'To change it, <button class="btn small" id="revise">start revision ' + (s.revision + 1) + "</button>; the signed version stays in the history." : ""}</div>` : ""}
        <div class="row2"><div class="ff"><label class="flabel" for="sd">Season start</label><input type="date" id="sd" value="${s.start_date || ""}" ${ro ? "readonly" : ""}></div>
          <div class="ff"><label class="flabel" for="ed">Season end</label><input type="date" id="ed" value="${s.end_date || ""}" ${ro ? "readonly" : ""}></div></div>
        ${P.schema.sections.map((sec, i) => `<h3 class="sec-bar" id="sec-${i}">${i + 1}. ${e(sec.section)}</h3><form class="ef" data-i="${i}" onsubmit="return false"></form>`).join("")}
        <h3 class="sec-bar" id="sec-sig">Signature and revisions</h3><div id="sigbox"></div>
        ${importBox()}</div></section></div>`;
    const readers = [...pg.querySelectorAll("form.ef")].map((f) => {
      const sec = P.schema.sections[+f.dataset.i];
      const r = Forms.render(f, sec.fields, s.opord, ro, { onChange: () => { S.dirty = true; const b = document.getElementById("osave"); if (b) b.textContent = "Save*"; } });
      f.querySelectorAll(".auto[data-src]").forEach((a) => (a.innerHTML = autoProgram(a.dataset.src, s.context)));
      return r;
    });
    pg.querySelectorAll(".nav-item").forEach((b) => (b.onclick = () => document.getElementById("sec-" + b.dataset.sec).scrollIntoView({ behavior: "smooth" })));
    const save = async () => {
      const content = Object.assign({}, s.opord, ...readers.map((r) => r()));
      await call(() => RX.api(`/api/seasons/${P.year}`, { method: "PUT", body: { op_name: document.getElementById("opname").value, start_date: sd.value || null, end_date: ed.value || null, opord: content } }));
      S.dirty = false; toast("Operation order saved"); show("opord");
    };
    const sv = document.getElementById("osave"); if (sv) sv.onclick = save;
    pg.onkeydown = (ev) => { if ((ev.ctrlKey || ev.metaKey) && ev.key === "s" && sv) { ev.preventDefault(); save(); } };
    const rv = document.getElementById("revise"); if (rv) rv.onclick = async () => { await call(() => RX.api(`/api/seasons/${P.year}/revise`, { method: "POST", body: {} })); show("opord"); };
    // signature block
    const hist = await call(() => RX.api(`/api/seasons/${P.year}/history`));
    const sig = document.getElementById("sigbox");
    const signer = [s.opord.auth_rank, s.opord.auth_name].filter(Boolean).join(" ") + (s.opord.auth_appointment ? ", " + s.opord.auth_appointment : "");
    sig.innerHTML = `${s.status === "signed" ? `<p>Signed by <b>${e(s.signed_name)}</b> on ${String(s.signed_at).slice(0, 10)}.</p>`
        : can("burn_boss") ? `<p class="hint">Export to Word, route it for signature, then record the signature here. This locks the order; changes after that start a new revision.</p>
          <form id="signf" class="row-actions"><input name="who" value="${e(signer)}" placeholder="Signed by" required style="flex:1"><input name="when" type="date" value="${new Date().toISOString().slice(0, 10)}"><button class="btn primary small">Record signature</button></form>`
        : '<p class="hint">Not signed yet.</p>'}
      <details><summary class="hint">${hist.length} saved version${hist.length === 1 ? "" : "s"}</summary>${hist.map((h) => `<div class="feat"><span class="lbl">Revision ${h.revision} · ${h.status}</span><span class="m">${h.saved_at.slice(0, 16).replace("T", " ")} · ${e(h.saved_by)}</span></div>`).join("")}</details>`;
    const sf = document.getElementById("signf");
    if (sf) sf.onsubmit = async (ev) => {
      ev.preventDefault();
      if (S.dirty && !confirm("There are unsaved changes; they will be lost. Record the signature anyway?")) return;
      await call(() => RX.api(`/api/seasons/${P.year}/sign`, { method: "POST", body: { signed_name: sf.who.value, signed_at: sf.when.value } }));
      S.dirty = false; toast("Signature recorded"); show("opord");
    };
    wireImport();
  }

  const importBox = () => can("burn_boss") ? `<details class="imp"><summary class="hint">Load a program file (operation order, people, role defaults)</summary>
      <p class="hint">A JSON file kept outside the code repository, e.g. last season's order with names and phone numbers. People are matched by name.</p>
      <input type="file" id="impf" accept=".json,application/json"></details>` : "";
  function wireImport() {
    const f = document.getElementById("impf"); if (!f) return;
    f.onchange = async () => {
      const data = JSON.parse(await f.files[0].text());
      const r = await call(() => RX.api("/api/program/import", { method: "POST", body: data }));
      if (r.season) P.year = r.season;
      toast(`Loaded: ${r.people_added} people added, ${r.people_updated} updated${r.season ? `, ${r.season} operation order` : ""}`); show("opord");
    };
  }

  // ------------------------------------------------------------------ meetings
  const KIND_LABEL = { planning: "Planning", coordination: "Coordination", briefing: "Briefing", aar: "After action review", other: "Other" };
  async function meetingsPage(pg, id) {
    const [ms, acts, plans] = await call(() => Promise.all([RX.api(`/api/meetings${P.year ? "?season=" + P.year : ""}`), RX.api(`/api/actions${P.year ? "?season=" + P.year : ""}`), RX.api("/api/plans")]));
    const cur = id === 0 ? null : ms.find((m) => m.id === id) || null;
    pg.innerHTML = `<div class="pv"><nav class="pv-nav" aria-label="Meetings"><div class="nav-sec">Meetings ${P.year || ""} <span class="hint">${ms.length}</span></div>
        ${can("planner") ? '<button class="btn primary small" id="newm" style="margin:4px 8px 8px">New meeting</button>' : ""}
        ${ms.map((m) => `<a class="nav-item mtg" href="#program/meetings/${m.id}" aria-current="${cur && cur.id === m.id ? "page" : "false"}"><span></span><span class="nc">${new Date(m.held_at).toLocaleDateString("en-CA", { day: "numeric", month: "short" })}</span><span>${e(m.title)}<br><span class="hint">${KIND_LABEL[m.kind]}${m.plan_name ? " · " + e(m.plan_name) : ""}</span></span></a>`).join("") || '<p class="hint" style="padding:8px">No meetings recorded.</p>'}
      </nav><section class="pv-main"><div class="doc" id="mdoc"></div></section></div>`;
    const nb = document.getElementById("newm"); if (nb) nb.onclick = () => meetingForm(null, plans);
    if (cur || id === 0) return meetingForm(cur, plans);
    document.getElementById("mdoc").innerHTML = `<h2 class="doc-title">Open actions</h2>${acts.length ? `<table class="grid"><thead><tr><th>Action</th><th>Owner</th><th>Due</th><th>From</th></tr></thead><tbody>${acts.map((a) =>
      `<tr class="${a.due && a.due < new Date().toISOString().slice(0, 10) ? "late" : ""}"><td>${e(a.action)}</td><td>${e(a.owner)}</td><td>${e(a.due)}</td><td><a href="#program/meetings/${a.meeting_id}">${e(a.meeting)}</a> ${a.held_at.slice(0, 10)}</td></tr>`).join("")}</tbody></table>`
      : '<p class="hint">No open actions. Actions come from the meeting records; tick them done there.</p>'}`;
  }

  function meetingForm(m, plans) {
    const ro = !can("planner");
    m = m || { kind: "planning", title: "", held_at: new Date().toISOString(), attendees: [], actions: [], season_year: P.year };
    const local = (iso) => { const d = new Date(iso); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
    const fields = [
      { key: "kind", label: "Kind", type: "select", options: P.schema.meeting_kinds },
      { key: "location", label: "Location", type: "text" },
      { key: "agenda", label: "Agenda", type: "textarea" }, { key: "notes", label: "Notes", type: "textarea" },
      { key: "decisions", label: "Decisions", type: "textarea" },
      { key: "actions", label: "Actions", type: "table", columns: [{ key: "action", label: "Action", type: "text" }, { key: "owner", label: "Owner", type: "text", list: "people" }, { key: "due", label: "Due", type: "date" }, { key: "done", label: "Done", type: "bool" }] },
      { key: "others", label: "Other attendees (not in People)", type: "text" }];
    const doc = document.getElementById("mdoc");
    doc.innerHTML = `<div class="el-headbar"><div><div class="owner">${m.id ? "Meeting record" : "New meeting"}${m.created_by ? " · " + e(m.created_by) : ""}</div>
        <h2 class="doc-title"><input id="mt" class="title-in" value="${e(m.title)}" placeholder="Title, e.g. Pre-season coordination" ${ro ? "readonly" : ""} aria-label="Title"></h2></div>
        <div class="el-actions">${ro ? "" : `${m.id ? '<button class="btn small danger" id="mdel">Delete</button>' : ""}<button class="btn primary" id="msave">Save</button>`}</div></div>
      <div class="row2"><div class="ff"><label class="flabel" for="mwhen">When</label><input type="datetime-local" id="mwhen" value="${local(m.held_at)}" ${ro ? "readonly" : ""}></div>
        <div class="ff"><label class="flabel" for="mplan">Burn block (optional)</label><select id="mplan" ${ro ? "disabled" : ""}><option value="">Whole program</option>${plans.filter((p) => !P.year || p.season_year === P.year).map((p) => `<option value="${p.id}" ${p.id === m.plan_id ? "selected" : ""}>${e(p.name)} v${p.version_no}</option>`).join("")}</select></div></div>
      <div class="ff"><span class="flabel">Attendees</span><div class="chips">${P.people.filter((p) => p.active || m.attendees.includes(p.id)).map((p) => `<label class="chipbox"><input type="checkbox" value="${p.id}" ${m.attendees.includes(p.id) ? "checked" : ""} ${ro ? "disabled" : ""}><span>${e(fullName(p))}</span></label>`).join("")}</div></div>
      <form id="mf" class="ef" onsubmit="return false"></form>`;
    const read = Forms.render(document.getElementById("mf"), fields, m, ro, {});
    const sv = document.getElementById("msave");
    if (sv) sv.onclick = async () => {
      const body = { ...read(), title: mt.value, held_at: new Date(mwhen.value).toISOString(), plan_id: mplan.value ? +mplan.value : null, season_year: m.season_year || P.year,
        attendees: [...doc.querySelectorAll(".chips input:checked")].map((x) => +x.value) };
      body.actions = (body.actions || []).filter((a) => a.action);
      const r = await call(() => RX.api(m.id ? `/api/meetings/${m.id}` : "/api/meetings", { method: m.id ? "PUT" : "POST", body }));
      toast("Meeting saved"); location.hash = `#program/meetings/${r.id}`; if (m.id) show("meetings", r.id);
    };
    const dl = document.getElementById("mdel");
    if (dl) dl.onclick = async () => { if (!confirm("Delete this meeting record?")) return; await call(() => RX.api(`/api/meetings/${m.id}`, { method: "DELETE" })); location.hash = "#program/meetings"; };
  }

  // ------------------------------------------------------------------ people
  async function peoplePage(pg) {
    const roles = await call(() => RX.api("/api/role-defaults"));
    const ed = can("planner");
    pg.innerHTML = `<div class="doc wide">
      <h2 class="doc-title">Usual roles</h2>
      <p class="hint">Who fills each role on every burn. New burn plans start with these names in Element 11; change them when someone else qualifies.</p>
      <form id="rolef" class="roles">${roles.map((r) => `<div class="ff"><label class="flabel" for="r-${r.role}">${e(r.label)}${r.position ? ` <span class="hint">(${e(r.position)})</span>` : ""}</label>
        <select id="r-${r.role}" data-role="${r.role}" ${can("burn_boss") ? "" : "disabled"}><option value="">—</option>${P.people.filter((p) => p.active).map((p) => `<option value="${p.id}" ${p.id === r.person_id ? "selected" : ""}>${e(fullName(p))}</option>`).join("")}</select>
        ${r.person_id && r.position ? `<span class="hint ${r.qualified === false ? "warn" : ""}">${r.qualified === true ? "qualified" : r.qualified === false ? "qualification not recorded for " + e(r.position) : "no quals recorded"}</span>` : ""}</div>`).join("")}</form>
      ${can("burn_boss") ? '<button class="btn primary small" id="rsave">Save roles</button>' : ""}
      <h2 class="doc-title" style="margin-top:28px">People</h2>
      <table class="grid people"><thead><tr><th>Name</th><th>Appointment</th><th>Organization</th><th>Phone</th><th>Email</th><th>Qualifications</th><th>Contact in op order</th><th></th></tr></thead>
        <tbody>${P.people.map((p) => `<tr class="${p.active ? "" : "inactive"}" data-id="${p.id}"><td><b>${e(fullName(p))}</b>${p.default_roles.length ? `<div class="hint">usual ${p.default_roles.map((k) => e(roles.find((r) => r.role === k).label.toLowerCase())).join(", ")}</div>` : ""}${p.notes ? `<div class="hint">${e(p.notes)}</div>` : ""}</td>
          <td>${e(p.appointment)}</td><td>${e(p.organization)}</td><td>${e(p.phone)}</td><td>${e(p.email)}</td><td>${p.quals.map((q) => `<span class="qual">${e(q)}</span>`).join(" ")}</td><td>${p.poc ? "yes" : ""}</td>
          <td>${ed ? '<button class="btn small" data-edit>Edit</button>' : ""}</td></tr>`).join("") || '<tr><td colspan="8" class="hint">Nobody yet.</td></tr>'}</tbody></table>
      ${ed ? `<div class="row-actions"><button class="btn small" id="padd">Add person</button></div><div id="pform"></div>
        <details class="imp"><summary class="hint">Paste points of contact from an operation order</summary>
          <p class="hint">One person per line: rank and name, appointment, phone (columns or commas), e.g. <code>Maj B. Smith    G3    CSN 258-0000</code>.</p>
          <textarea id="paste" rows="6" style="width:100%"></textarea><div class="row-actions"><button class="btn small" id="pcheck">Check</button><button class="btn primary small" id="pimport">Add them</button></div><div id="pout"></div></details>` : ""}</div>`;
    const rs = document.getElementById("rsave");
    if (rs) rs.onclick = async () => {
      const body = Object.fromEntries([...pg.querySelectorAll("[data-role]")].map((s) => [s.dataset.role, s.value ? +s.value : null]));
      await call(() => RX.api("/api/role-defaults", { method: "PUT", body })); toast("Usual roles saved: new plans will use them"); show("people");
    };
    pg.querySelectorAll("[data-edit]").forEach((b) => (b.onclick = () => personForm(P.people.find((p) => p.id === +b.closest("tr").dataset.id))));
    const pa = document.getElementById("padd"); if (pa) pa.onclick = () => personForm(null);
    const imp = async (dry) => {
      const r = await call(() => RX.api("/api/people/import", { method: "POST", body: { text: paste.value, dry_run: dry, poc: true } }));
      document.getElementById("pout").innerHTML = `<table class="grid"><tbody>${r.map((x) => x.error ? `<tr><td colspan="4" class="warn">Not understood: ${e(x.line)}</td></tr>`
        : `<tr><td>${e(fullName(x))}</td><td>${e(x.appointment)}</td><td>${e(x.phone)}</td><td class="hint">${x.existing_id ? "update" : "new"}</td></tr>`).join("")}</tbody></table>`;
      if (!dry) { toast(`${r.filter((x) => !x.error).length} people saved`); show("people"); }
    };
    const pc = document.getElementById("pcheck"); if (pc) pc.onclick = () => imp(true);
    const pi = document.getElementById("pimport"); if (pi) pi.onclick = () => imp(false);
  }

  function personForm(p) {
    const box = document.getElementById("pform");
    p = p || { name: "", quals: [], poc: false, active: true };
    box.innerHTML = `<form id="perf" class="card-form"><h3>${p.id ? "Edit " + e(p.name) : "Add person"}</h3><div class="ef">
      ${[["rank", "Rank / title"], ["name", "Name"], ["appointment", "Appointment"], ["organization", "Organization"], ["phone", "Phone / CSN"], ["email", "Email"]].map(([k, l]) =>
        `<div class="ff"><label class="flabel" for="p-${k}">${l}</label><input id="p-${k}" name="${k}" value="${e(p[k])}" ${k === "name" ? "required" : ""}></div>`).join("")}
      <div class="ff"><label class="flabel" for="p-quals">Qualifications</label><input id="p-quals" name="quals" value="${e(p.quals.join(", "))}" placeholder="e.g. RXB2, FIRB, ICT4, FFT1, EMR, EOD"></div>
      <div class="ff"><label class="flabel" for="p-notes">Notes</label><input id="p-notes" name="notes" value="${e(p.notes)}"></div>
      <div class="ff"><label class="chipbox"><input type="checkbox" name="poc" ${p.poc ? "checked" : ""}><span>Point of contact in the operation order</span></label></div>
      <div class="ff"><label class="chipbox"><input type="checkbox" name="active" ${p.active ? "checked" : ""}><span>Active</span></label></div></div>
      <div class="row-actions"><button class="btn primary small">Save</button>${p.id ? '<button type="button" class="btn small danger" id="pdel">Remove</button>' : ""}<button type="button" class="btn small" id="pcancel">Cancel</button></div></form>`;
    const f = document.getElementById("perf"); f.scrollIntoView({ behavior: "smooth" }); f.name.focus();
    f.onsubmit = async (ev) => {
      ev.preventDefault();
      const body = Object.fromEntries(["rank", "name", "appointment", "organization", "phone", "email", "quals", "notes"].map((k) => [k, f[k].value.trim() || null]));
      body.quals = body.quals || ""; body.poc = f.poc.checked; body.active = f.active.checked;
      await call(() => RX.api(p.id ? `/api/people/${p.id}` : "/api/people", { method: p.id ? "PUT" : "POST", body })); toast("Saved"); show("people");
    };
    document.getElementById("pcancel").onclick = () => (box.innerHTML = "");
    const d = document.getElementById("pdel");
    if (d) d.onclick = async () => { if (!confirm(`Remove ${p.name}? People named in meeting records are set inactive instead.`)) return; await call(() => RX.api(`/api/people/${p.id}`, { method: "DELETE" })); show("people"); };
  }

  return { loadPeople, check, tabs, show };
})();
