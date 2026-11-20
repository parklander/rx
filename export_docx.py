"""Render a plan as a PMS 484-1 ordered Word document."""
import io
from datetime import datetime

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

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


def render(plan, defs, overlay):
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
    for d in defs:
        doc.add_heading(f"{'Element ' if d['code'][0].isdigit() else ''}{d['code']}: {d['title']}" if d['code'][0].isdigit() else d["title"], level=1)
        e = els.get(d["code"])
        content = (e or {}).get("content") or {}
        auto = {}
        if d["code"] == "1":
            auto = {"admin_unit": plan.get("admin_unit"), "burn_name": plan.get("name"), "ignition_unit": plan.get("unit_name"),
                    "complexity": plan.get("complexity"), "min_rxb": plan.get("min_burn_boss")}
        for s in d["sections"]:
            doc.add_heading(s["label"], level=2)
            txt = (content.get(s["key"]) or auto.get(s["key"]) or "").strip()
            doc.add_paragraph(txt if txt else "[not yet written]")
        if d["code"] == "1" and plan.get("signatures"):
            tbl = doc.add_table(rows=1, cols=4)
            tbl.style = "Table Grid"
            for i, h in enumerate(["Role", "Name", "Qualification", "Signed"]):
                tbl.rows[0].cells[i].text = h
            for s in plan["signatures"]:
                row = tbl.add_row().cells
                row[0].text, row[1].text, row[2].text, row[3].text = s["role"], s["name"], s.get("qualification") or "", s["signed_at"][:16]
        if d["code"] == "4" and overlay.get("fuels"):
            doc.add_paragraph("Fuel classes from the fuels layer (ha):")
            tbl = doc.add_table(rows=1, cols=3)
            tbl.style = "Table Grid"
            for i, h in enumerate(["Fuel class", "Burn unit", "Contingency area"]):
                tbl.rows[0].cells[i].text = h
            for f in overlay["fuels"]:
                row = tbl.add_row().cells
                row[0].text, row[1].text, row[2].text = str(f["fuel_class"]), str(f.get("unit_ha") or 0), str(f.get("contingency_ha") or 0)
        if d["code"] == "4":
            vals = [f["properties"] for f in overlay.get("features", []) if f["properties"]["layer"] in ("infra.asset", "habitat.critical_habitat", "habitat.sensitive_feature")]
            if vals:
                doc.add_paragraph("Values in the unit and contingency area (from the database):")
                tbl = doc.add_table(rows=1, cols=3)
                tbl.style = "Table Grid"
                for i, h in enumerate(["Value", "Type", "Where"]):
                    tbl.rows[0].cells[i].text = h
                for v in vals:
                    row = tbl.add_row().cells
                    row[0].text = str(v.get("name") or v.get("species") or v.get("grid_id") or "")
                    row[1].text = str(v.get("asset_type") or v.get("kind") or v.get("status") or "")
                    row[2].text = v["zone"]
        if d["code"] == "7" and plan.get("prescription"):
            tbl = doc.add_table(rows=1, cols=3)
            tbl.style = "Table Grid"
            for i, h in enumerate(["Parameter", "Range", "Note"]):
                tbl.rows[0].cells[i].text = h
            for p in plan["prescription"]:
                row = tbl.add_row().cells
                row[0].text = PARAM_LABELS.get(p["param"], p["param"])
                row[1].text = _rng(p.get("low"), p.get("high"))
                row[2].text = p.get("note") or ""
        if d["code"] == "15" and plan.get("variants"):
            doc.add_heading("Ignition variants by wind direction", level=2)
            for v in plan["variants"]:
                doc.add_paragraph(f"{v['name']}: wind from {v['wind_dir_min']:g}° to {v['wind_dir_max']:g}°. {v.get('description') or ''}", style="List Bullet")
                for i, s in enumerate(v.get("firing_sequence") or [], 1):
                    doc.add_paragraph(f"{i}. {s.get('step', '')}")
        if d["code"] == "19":
            rec = [f["properties"] for f in overlay.get("features", []) if f["properties"]["layer"] == "smoke.receptor"]
            if rec:
                doc.add_paragraph("Receptors near the unit: " + "; ".join(f"{r['name']} ({r.get('sensitivity')})" for r in rec))
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
