"""Render a plan as a PMS 484-1 ordered Word document."""
import io
from datetime import datetime

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor

PARAM_LABELS = {"temp_c": "Temperature (°C)", "rh_pct": "Relative humidity (%)", "wind_kmh": "20-ft / 10-m wind (km/h)",
                "wind_dir_deg": "Wind direction (°)", "gust_kmh": "Gusts (km/h)", "ffmc": "FFMC", "isi": "ISI", "bui": "BUI",
                "fwi": "FWI", "dmc": "DMC", "dc": "DC", "curing_pct": "Grass curing (%)", "mixing_height_m": "Mixing height (m)",
                "vent_index": "Ventilation index"}


def _rng(lo, hi):
    if lo is not None and hi is not None:
        return f"{lo:g} – {hi:g}"
    if lo is not None:
        return f"≥ {lo:g}"
    if hi is not None:
        return f"≤ {hi:g}"
    return "—"


def render(plan, defs, overlay, features=None):
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(11)

    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("PRESCRIBED FIRE PLAN")
    r.bold = True
    r.font.size = Pt(18)
    sub = doc.add_paragraph(f"{plan['name']} · {plan.get('unit_name') or ''}\n{plan.get('admin_unit') or ''} · version {plan['version_no']} · status: {plan['status']}")
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if plan.get("demo"):
        w = doc.add_paragraph()
        w.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rr = w.add_run("DEMO PLAN: notional data, not for implementation")
        rr.bold = True
        rr.font.color.rgb = RGBColor(0xA0, 0x20, 0x20)
    meta = doc.add_paragraph(
        f"Complexity: {plan.get('complexity') or '—'} · Minimum burn boss: {plan.get('min_burn_boss') or '—'} · Window: {plan.get('planned_window') or '—'}\n"
        f"Data as of: {plan.get('as_of') or 'draft (current data)'} · Exported {datetime.now():%Y-%m-%d %H:%M}")
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER

    els = plan.get("elements", {})
    feats = [f["properties"] for f in (features or {}).get("features", [])]

    def table(headers, rows):
        t = doc.add_table(rows=1, cols=len(headers))
        t.style = "Table Grid"
        for i, h in enumerate(headers):
            t.rows[0].cells[i].text = h
            for r in t.rows[0].cells[i].paragraphs[0].runs:
                r.bold = True
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = "" if v is None else (("yes" if v else "no") if isinstance(v, bool) else str(v))
        doc.add_paragraph()

    def kv(label, value):
        para = doc.add_paragraph()
        r = para.add_run(f"{label}: ")
        r.bold = True
        para.add_run(value if value not in (None, "", []) else "[not given]")

    def auto(src, content):
        flist = lambda kind: [f for f in feats if f.get("kind") == kind]
        if src == "plan_name":
            return plan["name"]
        if src == "ignition_units":
            return ", ".join(f"{f.get('label')} ({f.get('area_ha')} ha)" for f in flist("ignition_unit")) or "none drawn"
        if src == "location":
            c = plan.get("centroid")
            return f"{c['lat']}, {c['lon']} ({c['utm']})" if c else "not drawn"
        if src == "size":
            return f"{sum(f.get('area_ha') or 0 for f in flist('burn_unit')):.1f} ha"
        if src in ("test_fire_site", "trigger_points"):
            return ", ".join(f.get("label") or "" for f in flist(src[:-1] if src.endswith("s") else src)) or "none drawn"
        if src == "holding_lines":
            return "; ".join(f"{f.get('label')} ({round(f.get('length_m') or 0)} m)" for f in flist("holding_line")) or "none drawn"
        if src == "cost_total":
            return f"${sum((r.get('amount') or 0) for r in content.get('costs') or []):,.0f}"
        return None

    for d in defs:
        title = f"Element {d['code']}: {d['title']}" if d["code"][0].isdigit() else d["title"]
        doc.add_heading(title, level=1)
        e = els.get(d["code"]) or {}
        content = e.get("content") or {}
        known = set()
        for f in d["fields"]:
            known.add(f["key"])
            t, label, v = f["type"], f.get("label", ""), content.get(f["key"], f.get("default"))
            if t == "info":
                continue
            if t == "auto":
                src = f["source"]
                if src == "fuels" and overlay.get("fuels"):
                    doc.add_heading(label, level=2)
                    table(["Fuel class", "Burn unit ha", "Contingency ha"], [[x["fuel_class"], x.get("unit_ha") or 0, x.get("contingency_ha") or 0] for x in overlay["fuels"]])
                elif src == "values":
                    vals = [x["properties"] for x in overlay.get("features", []) if x["properties"]["layer"] not in ("fuels.fuel_class", "ops.road", "ops.fireguard")]
                    if vals:
                        doc.add_heading(label, level=2)
                        table(["Value", "Layer", "Detail", "Where"], [[x.get("name") or x.get("species") or x.get("kind"), x["layer"], x.get("vulnerability") or x.get("measure") or x.get("status") or "", x["zone"]] for x in vals])
                elif src == "receptors":
                    if plan.get("receptors"):
                        doc.add_heading(label, level=2)
                        table(["Receptor", "Type", "Sensitivity", "km", "Bearing °"], [[r["name"], r.get("kind"), r.get("sensitivity"), r["km"], r["bearing"]] for r in plan["receptors"]])
                elif src == "mitigation" and plan.get("prep_tasks"):
                    doc.add_heading(label, level=2)
                    table(["Work", "Lowers", "Status"], [[t["properties"]["title"], ", ".join(t["properties"]["mitigates"] or []), t["properties"]["status"]] for t in plan["prep_tasks"]])
                elif src in ("mbca", "complexity_summary", "mitigation"):
                    continue
                else:
                    kv(label, auto(src, content))
                continue
            if t == "component":
                comp = f["component"]
                if comp == "signatures" and plan.get("signatures"):
                    doc.add_heading(label, level=2)
                    table(["Role", "Name", "Qualification", "Signed"], [[x["role"], x["name"], x.get("qualification") or "", x["signed_at"][:16]] for x in plan["signatures"]])
                if comp == "prescription" and plan.get("prescription"):
                    doc.add_heading(label, level=2)
                    table(["Parameter", "Range", "Note"], [[PARAM_LABELS.get(x["param"], x["param"]), _rng(x.get("low"), x.get("high")), x.get("note") or ""] for x in plan["prescription"]])
                if comp == "prep_tasks" and plan.get("prep_tasks"):
                    doc.add_heading(label, level=2)
                    table(["Work", "Type", "Width m", "Length m", "Area ha", "Standard", "Needed before", "Status"],
                          [[t["properties"]["title"], t["properties"]["kind_label"], t["properties"]["width_m"], t["properties"]["length_m"],
                            t["properties"]["area_ha"], t["properties"]["spec"], t["properties"]["required_for"], t["properties"]["status"]] for t in plan["prep_tasks"]])
                if comp == "variants" and plan.get("variants"):
                    doc.add_heading(label, level=2)
                    for vv in plan["variants"]:
                        doc.add_paragraph(f"{vv['name']}: wind from {vv['wind_dir_min']:g}° to {vv['wind_dir_max']:g}°. {vv.get('description') or ''}", style="List Bullet")
                        for i, st in enumerate(vv.get("firing_sequence") or [], 1):
                            doc.add_paragraph(f"{i}. {st.get('step', '')}")
                continue
            if t == "textarea":
                doc.add_heading(label, level=2)
                doc.add_paragraph(v.strip() if isinstance(v, str) and v.strip() else "[not yet written]")
            elif t == "multi":
                kv(label, ", ".join(v or []))
            elif t == "bool":
                kv(label, "yes" if v else "no")
            elif t == "table":
                rows = v if isinstance(v, list) else []
                if rows:
                    doc.add_heading(label, level=2)
                    table([c["label"] for c in f["columns"]], [[r.get(c["key"]) for c in f["columns"]] for r in rows])
            elif t == "checklist":
                vv = v or {}
                doc.add_heading(label, level=2)
                table(["Item", "Answer", "Note"], [[l, (vv.get(k) or {}).get("a") or "", (vv.get(k) or {}).get("note") or ""] for k, l in f["items"]])
            else:
                kv(label, "" if v is None else str(v))
        for k, v in content.items():
            if k not in known and v:
                doc.add_paragraph(f"{k}: {v if isinstance(v, str) else v}")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- the season's operation order
def _shade(cell, hex_fill):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def opord(season, ctx, sections):
    """The season's operation order, laid out like the CFB Shilo OPORD: dark numbered section bars,
    grid tables, signature block."""
    o = season.get("opord") or {}
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Arial"
    st.font.size = Pt(10.5)

    def para(text="", bold=False, size=None, align=None, italic=False):
        p = doc.add_paragraph()
        if align:
            p.alignment = align
        r = p.add_run(text)
        r.bold, r.italic = bold, italic
        if size:
            r.font.size = Pt(size)
        return p

    def bar(text):
        t = doc.add_table(rows=1, cols=1)
        c = t.rows[0].cells[0]
        t.autofit = False
        t.columns[0].width = c.width = Cm(16.5)
        _shade(c, "1F2A36")
        r = c.paragraphs[0].add_run(text.upper())
        r.bold = True
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        doc.add_paragraph().paragraph_format.space_after = Pt(0)

    def grid(headers, rows, weights=None):
        t = doc.add_table(rows=1, cols=len(headers))
        t.style = "Table Grid"
        t.autofit = False
        weights = weights or [1] * len(headers)
        for i, h in enumerate(headers):
            c = t.rows[0].cells[i]
            _shade(c, "D9DEE4")
            c.text = ""
            c.paragraphs[0].add_run(h).bold = True
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = "" if v in (None, "") else str(v)
        for i, col in enumerate(t.columns):  # 16.5 cm of usable width, shared by weight
            w = Cm(16.5 * weights[i] / sum(weights))
            col.width = w
            for c in col.cells:
                c.width = w
        doc.add_paragraph()

    def sub(label, text):
        p = doc.add_paragraph()
        p.add_run(f"{label}. ").bold = True
        p.add_run(text if text else "[not given]")

    if season.get("status") != "signed":
        para(f"DRAFT · revision {season.get('revision', 1)}", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER).runs[0].font.color.rgb = RGBColor(0xA0, 0x20, 0x20)
    head = doc.add_table(rows=1, cols=2)
    head.rows[0].cells[0].text = ""
    head.rows[0].cells[0].paragraphs[0].add_run(o.get("title") or season.get("op_name") or "Operation order").bold = True
    when = datetime.fromisoformat(str(season["signed_at"])) if season.get("signed_at") else datetime.now()
    head.rows[0].cells[1].text = f"{o.get('file_number') or ''}\n{when:%d %b %Y}"
    head.rows[0].cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if o.get("drafted_by"):
        para(f"Drafted by: {o['drafted_by']}", italic=True)
    if o.get("references"):
        para("References:", bold=True)
        grid(["Ref", "Document"], [[r.get("ref"), r.get("title")] for r in o["references"]], [1, 9])

    n = 0
    for sec in sections:
        if sec["section"] in ("Heading", "Authorization", "Annexes"):
            continue
        n += 1
        bar(f"{n}. {sec['section']}")
        letter = 0
        for f in sec["fields"]:
            v = o.get(f["key"], f.get("default"))
            label = f["label"]
            if f["type"] == "auto":
                if f["source"] == "season_blocks":
                    para(f"{label} · {len(ctx['blocks'])} blocks, {ctx['total_ha']} ha", bold=True)
                    grid(["Burn block", "Unit", "Area (ha)", "Complexity", "Window", "Status"],
                         [[b["name"], b.get("unit_name"), b.get("area_ha"), b.get("complexity"), b.get("planned_window"), b["status"]] for b in ctx["blocks"]])
                elif f["source"] == "season_resources":
                    para(label, bold=True)
                    if ctx["positions"]:
                        grid(["Position", "Number (largest single burn)"], [[p["position"], p["qty"]] for p in ctx["positions"]])
                    if ctx["equipment"]:
                        grid(["Equipment", "Number"], [[e["type"], e["qty"]] for e in ctx["equipment"]])
                    if not (ctx["positions"] or ctx["equipment"]):
                        para("No resources entered in the burn plans yet.", italic=True)
                elif f["source"] == "season_pocs":
                    para(label, bold=True)
                    grid(["Name", "Appointment", "Organization", "Phone / CSN", "Email"],
                         [[" ".join(x for x in [p.get("rank"), p["name"]] if x), p.get("appointment"), p.get("organization"), p.get("phone"), p.get("email")] for p in ctx["pocs"]], [3, 3, 2, 2, 3])
                continue
            letter += 1
            tag = chr(96 + letter)
            if f["type"] == "table":
                para(f"{tag}. {label}", bold=True)
                cols = f["columns"]
                grid([c["label"] for c in cols], [[r.get(c["key"]) for c in cols] for r in (v or [])],
                     [4 if c["type"] == "textarea" else 1.4 if c["type"] == "date" else 2 for c in cols])
            elif len(sec["fields"]) == 1:
                doc.add_paragraph(v or "[not given]")
            else:
                sub(f"{tag}. {label}", v)

    if o.get("annexes"):
        bar("Annexes")
        grid(["Annex", "Title"], [[a.get("annex"), a.get("title")] for a in o["annexes"]], [1, 9])
    dist_a, dist_i = o.get("dist_action"), o.get("dist_info")
    if dist_a or dist_i:
        bar("Distribution")
        grid(["Action", "Info"], [[dist_a or "", dist_i or ""]])

    doc.add_paragraph()
    sig = doc.add_table(rows=1, cols=2)
    left = sig.rows[0].cells[1]
    left.text = ""
    if season.get("status") == "signed":
        left.paragraphs[0].add_run(f"Signed by {season.get('signed_name')}\n{str(season.get('signed_at'))[:10]}").italic = True
    else:
        left.paragraphs[0].add_run("\n\n______________________________").bold = False
    left.add_paragraph(" ".join(x for x in [o.get("auth_rank"), o.get("auth_name")] if x) or "[name]")
    left.add_paragraph(o.get("auth_appointment") or "")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
