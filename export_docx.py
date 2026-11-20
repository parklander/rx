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
                elif src in ("mbca", "complexity_summary"):
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
