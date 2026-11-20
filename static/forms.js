// Structured forms for the plan elements: renders a schema (from schema.py) and reads it back.
const Forms = (() => {
  const esc = RX.esc;
  const YNA = [["yes", "Yes"], ["no", "No"], ["n/a", "N/A"]];
  let uid = 0;

  function input(type, name, value, ro, extra = "") {
    const v = value == null ? "" : value;
    if (type === "textarea") return `<textarea name="${name}" ${ro ? "readonly" : ""} ${extra}>${esc(v)}</textarea>`;
    const t = { number: "number", date: "date", time: "time" }[type] || "text";
    return `<input type="${t}" name="${name}" value="${esc(v)}" ${t === "number" ? 'step="any"' : ""} ${ro ? "readonly" : ""} ${extra}>`;
  }
  const select = (name, options, value, ro) => `<select name="${name}" ${ro ? "disabled" : ""}><option value=""></option>${options.map((o) => `<option ${o === value ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;

  function cell(col, value, ro) {
    if (col.type === "fixed") return `<span class="fixed">${esc(value)}</span>`;
    if (col.type === "select") return select(col.key, col.options, value, ro);
    if (col.type === "bool") return `<input type="checkbox" name="${col.key}" ${value ? "checked" : ""} ${ro ? "disabled" : ""} aria-label="${esc(col.label)}">`;
    return input(col.type, col.key, value, ro, `aria-label="${esc(col.label)}"`);
  }
  const rowHtml = (f, r, ro) => `<tr>${f.columns.map((c) => `<td class="c-${c.type}">${cell(c, r[c.key], ro)}</td>`).join("")}${ro || f.fixed ? "" : '<td><button type="button" class="btn small danger" data-delrow aria-label="Remove row">✕</button></td>'}</tr>`;

  function fieldHtml(f, content, ro) {
    const id = `f${++uid}`;
    const val = content[f.key] !== undefined ? content[f.key] : f.default;
    const lab = f.label ? `<label class="flabel" for="${id}">${esc(f.label)}</label>` : "";
    switch (f.type) {
      case "info": return `<p class="hint info">${esc(f.text)}</p>`;
      case "auto": return `<div class="ff" data-auto="${f.source}"><span class="flabel">${esc(f.label)} <span class="auto-tag">${["complexity_summary", "cost_total", "mbca"].includes(f.source) ? "calculated" : "from the map and database"}</span></span><div class="auto" data-src="${f.source}"></div></div>`;
      case "component": return `<div class="ff"><span class="flabel">${esc(f.label)}</span><div class="component" data-component="${f.component}"></div></div>`;
      case "select": return `<div class="ff" data-key="${f.key}" data-type="select">${lab}${select(f.key, f.options, val, ro).replace("<select", `<select id="${id}"`)}</div>`;
      case "multi": return `<div class="ff" data-key="${f.key}" data-type="multi"><span class="flabel">${esc(f.label)}</span><div class="chips">${f.options.map((o) => `<label class="chipbox"><input type="checkbox" value="${esc(o)}" ${(val || []).includes(o) ? "checked" : ""} ${ro ? "disabled" : ""}><span>${esc(o)}</span></label>`).join("")}</div></div>`;
      case "bool": return `<div class="ff" data-key="${f.key}" data-type="bool"><label class="chipbox"><input type="checkbox" ${val ? "checked" : ""} ${ro ? "disabled" : ""}><span>${esc(f.label)}</span></label></div>`;
      case "table": {
        const rows = Array.isArray(val) ? val : (f.rows || []);
        const fixedRows = f.fixed ? (f.rows || []).map((fr) => ({ ...fr, ...(rows.find((r) => r[f.columns[0].key] === fr[f.columns[0].key]) || {}) })) : rows;
        return `<div class="ff" data-key="${f.key}" data-type="table"><span class="flabel">${esc(f.label)}</span><div class="tscroll"><table class="grid ftable"><thead><tr>${f.columns.map((c) => `<th>${esc(c.label)}</th>`).join("")}${ro || f.fixed ? "" : "<th></th>"}</tr></thead>
          <tbody>${fixedRows.map((r) => rowHtml(f, r, ro)).join("")}</tbody></table></div>${ro || f.fixed ? "" : '<button type="button" class="btn small" data-addrow>Add row</button>'}</div>`;
      }
      case "checklist": {
        const v = val || {};
        return `<div class="ff" data-key="${f.key}" data-type="checklist"><span class="flabel">${esc(f.label)}</span><div class="clist">${f.items.map(([k, l]) => {
          const a = (v[k] || {}).a || "", note = (v[k] || {}).note || "";
          return `<div class="crow" data-item="${k}"><span class="cl">${esc(l)}</span><span class="seg small" role="radiogroup" aria-label="${esc(l)}">${YNA.map(([o, ol]) => `<label><input type="radio" name="${id}-${k}" value="${o}" ${a === o ? "checked" : ""} ${ro ? "disabled" : ""}><span>${ol}</span></label>`).join("")}</span>
            <input type="text" class="cnote" placeholder="Note" value="${esc(note)}" ${ro ? "readonly" : ""} aria-label="Note: ${esc(l)}"></div>`; }).join("")}</div></div>`;
      }
      default: return `<div class="ff ${f.type === "textarea" ? "wide" : ""}" data-key="${f.key}" data-type="${f.type}">${lab}${input(f.type, f.key, val, ro, `id="${id}"`)}</div>`;
    }
  }

  function render(root, fields, content, ro, opts = {}) {
    root.innerHTML = fields.map((f) => fieldHtml(f, content || {}, ro)).join("");
    root.addEventListener("click", (e) => {
      if (e.target.matches("[data-addrow]")) {
        const ff = e.target.closest(".ff"); const f = fields.find((x) => x.key === ff.dataset.key);
        ff.querySelector("tbody").insertAdjacentHTML("beforeend", rowHtml(f, {}, ro)); opts.onChange && opts.onChange();
      }
      if (e.target.matches("[data-delrow]")) { e.target.closest("tr").remove(); opts.onChange && opts.onChange(); }
    });
    root.addEventListener("input", () => opts.onChange && opts.onChange());
    root.addEventListener("change", () => opts.onChange && opts.onChange());
    const read = () => {
      const out = {};
      for (const ff of root.querySelectorAll(".ff[data-key]")) {
        const k = ff.dataset.key, t = ff.dataset.type, f = fields.find((x) => x.key === k);
        if (t === "select") out[k] = ff.querySelector("select").value || null;
        else if (t === "multi") out[k] = [...ff.querySelectorAll("input:checked")].map((i) => i.value);
        else if (t === "bool") out[k] = ff.querySelector("input").checked;
        else if (t === "number") { const v = ff.querySelector("input").value; out[k] = v === "" ? null : +v; }
        else if (t === "table") {
          out[k] = [...ff.querySelectorAll("tbody tr")].map((tr) => {
            const r = {};
            f.columns.forEach((c, i) => {
              const td = tr.children[i];
              if (c.type === "fixed") r[c.key] = td.textContent;
              else if (c.type === "bool") r[c.key] = td.querySelector("input").checked;
              else if (c.type === "select") r[c.key] = td.querySelector("select").value || null;
              else if (c.type === "number") { const v = td.querySelector("input").value; r[c.key] = v === "" ? null : +v; }
              else r[c.key] = td.querySelector("input,textarea").value;
            });
            return r;
          }).filter((r) => f.fixed || Object.values(r).some((v) => v !== null && v !== "" && v !== false));
        } else if (t === "checklist") {
          out[k] = {};
          for (const row of ff.querySelectorAll(".crow")) {
            const a = row.querySelector("input[type=radio]:checked"); const note = row.querySelector(".cnote").value;
            if (a || note) out[k][row.dataset.item] = { a: a ? a.value : null, note };
          }
        } else out[k] = ff.querySelector("input,textarea").value;
      }
      return out;
    };
    return read;
  }
  // Plain read-only view of an element's content (mobile).
  function view(fields, content) {
    const c = content || {}, out = [];
    for (const f of fields) {
      const v = c[f.key];
      if (["info", "auto", "component"].includes(f.type)) continue;
      if (v == null || v === "" || (Array.isArray(v) && !v.length)) continue;
      let html;
      if (f.type === "multi") html = esc(v.join(", "));
      else if (f.type === "bool") html = v ? "Yes" : "No";
      else if (f.type === "table") html = `<table class="grid">${v.map((r) => `<tr>${f.columns.map((col) => `<td>${esc(typeof r[col.key] === "boolean" ? (r[col.key] ? "✓" : "") : r[col.key] ?? "")}</td>`).join("")}</tr>`).join("")}</table>`;
      else if (f.type === "checklist") html = f.items.filter(([k]) => v[k]).map(([k, l]) => `<div>${esc(l)}: <b>${esc(v[k].a || "")}</b>${v[k].note ? " · " + esc(v[k].note) : ""}</div>`).join("");
      else html = `<p>${esc(v)}</p>`;
      out.push(`<h5>${esc(f.label)}</h5>${html}`);
    }
    const known = new Set(fields.map((f) => f.key));
    for (const [k, v] of Object.entries(c)) if (!known.has(k) && v) out.push(`<h5>${esc(k)}</h5><p>${esc(typeof v === "string" ? v : JSON.stringify(v))}</p>`);
    return out.join("") || "<p>—</p>";
  }
  return { render, view };
})();
