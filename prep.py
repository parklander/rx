"""Pre-burn work: the jobs that lower a burn's complexity (mulching along control lines, wet lines,
snag felling, protecting assets), drawn on the map with their width and standard, and tracked
planned → assigned → done → verified with evidence."""
import csv
import io
import json
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Response

import auth
import db

router = APIRouter()

KINDS = {
    "mulch": "Mulch vegetation", "mow": "Mow", "disc": "Disc", "grade": "Grade / blade", "wet_line": "Wet line",
    "black_line": "Black line (pre-burn)", "brush_removal": "Brush / juniper removal", "snag_felling": "Fell snags",
    "protect_asset": "Protect asset (gravel pad, wrap, clear around)", "water": "Water supply (tank, fill point)",
    "signage": "Signage / road closure", "other": "Other",
}
STATUSES = ["planned", "assigned", "done", "verified", "not_needed"]
LOCKED = ("approved", "implemented", "closed")


def _plan(pid):
    p = db.one("select id, status from plans.plan where id = %s", (pid,))
    if not p:
        raise HTTPException(404, "no such plan")
    return p


SELECT = """
  select t.*, ST_AsGeoJSON(t.geom, 7)::json as gj,
         case when GeometryType(t.geom) like '%%LINESTRING' and t.width_m > 0
              then ST_AsGeoJSON(ST_Buffer(t.geom::geography, t.width_m / 2, 'endcap=flat')::geometry, 7)::json end as band,
         round(ST_Length(t.geom::geography)::numeric) as length_m,
         round((case when GeometryType(t.geom) like '%%POLYGON' then ST_Area(t.geom::geography)
                     when t.width_m > 0 then ST_Length(t.geom::geography) * t.width_m else 0 end / 10000)::numeric, 2) as area_ha,
         (select json_agg(json_build_object('status', e.status, 'note', e.note, 'measured', e.measured, 'record_id', e.record_id,
                                            'at', e.at, 'by', e.by_user,
                                            'media', (select coalesce(json_agg(m.id), '[]') from field.media m where m.record_id = e.record_id))
                          order by e.at) from plans.prep_event e where e.task_id = t.id) as events
  from plans.prep_task t"""


def _fc(rows):
    feats = []
    for r in rows:
        g = r.pop("gj")
        r.pop("geom", None)
        r["kind_label"] = KINDS.get(r["kind"], r["kind"])
        feats.append({"type": "Feature", "id": str(r["id"]), "geometry": g, "properties": db._plain(r)})
    return {"type": "FeatureCollection", "features": feats}


@router.get("/api/prep/kinds")
def kinds(user=Depends(auth.current_user)):
    return [{"key": k, "label": v} for k, v in KINDS.items()]


@router.get("/api/plans/{pid}/prep")
def prep_list(pid: int, user=Depends(auth.current_user)):
    _plan(pid)
    return _fc(db.all(SELECT + " where t.plan_id = %s order by t.required_by nulls last, t.created_at", (pid,)))


def summarize(pid):
    rows = db.all(SELECT + " where t.plan_id = %s", (pid,))
    s = {"total": len(rows), "by_status": {k: 0 for k in STATUSES}, "outstanding_for_ignition": [], "outstanding_for_approval": [], "by_kind": {}}
    for r in rows:
        s["by_status"][r["status"]] += 1
        k = s["by_kind"].setdefault(KINDS.get(r["kind"], r["kind"]), {"n": 0, "length_m": 0, "area_ha": 0.0})
        k["n"] += 1
        k["length_m"] += float(r["length_m"] or 0) if r["width_m"] else 0
        k["area_ha"] += float(r["area_ha"] or 0)
        if r["status"] not in ("verified", "not_needed"):
            if r["required_for"] == "ignition":
                s["outstanding_for_ignition"].append({"id": str(r["id"]), "title": r["title"], "status": r["status"]})
            if r["required_for"] == "approval":
                s["outstanding_for_approval"].append({"id": str(r["id"]), "title": r["title"], "status": r["status"]})
    return s


@router.get("/api/plans/{pid}/prep/summary")
def prep_summary(pid: int, user=Depends(auth.current_user)):
    _plan(pid)
    return summarize(pid)


FIELDS = ["kind", "title", "width_m", "depth_cm", "spec", "dac_required", "required_for", "required_by", "assigned_to", "mitigates"]


@router.post("/api/plans/{pid}/prep")
def prep_add(pid: int, body: dict = Body(...), user=Depends(auth.require("planner"))):
    if _plan(pid)["status"] in LOCKED:
        raise HTTPException(409, "the plan is locked: amend it to add work")
    if body.get("kind") not in KINDS or not body.get("title") or not body.get("geom"):
        raise HTTPException(400, "kind, title and a location are needed")
    defaults = {"dac_required": False, "required_for": "ignition", "mitigates": []}
    vals = [body.get(f) if body.get(f) is not None else defaults.get(f) for f in FIELDS]
    with db.tx() as c:
        r = c.execute(f"""insert into plans.prep_task (plan_id, {', '.join(FIELDS)}, geom, created_by)
                          values (%s, {', '.join(['%s'] * len(FIELDS))}, ST_SetSRID(ST_GeomFromGeoJSON(%s),4326), %s) returning id""",
                      [pid] + vals + [json.dumps(body["geom"]), user["username"]]).fetchone()
        c.execute("insert into plans.prep_event (task_id, status, note, by_user) values (%s, 'planned', 'created', %s)", (r["id"], user["username"]))
    return {"id": str(r["id"])}


def _task(tid):
    t = db.one("select t.*, p.status as plan_status from plans.prep_task t join plans.plan p on p.id = t.plan_id where t.id = %s", (tid,))
    if not t:
        raise HTTPException(404, "no such task")
    return t


@router.put("/api/prep/{tid}")
def prep_edit(tid: str, body: dict = Body(...), user=Depends(auth.require("planner"))):
    t = _task(tid)
    if t["plan_status"] in LOCKED:
        raise HTTPException(409, "the plan is locked: the work specification can only change by amendment (status updates still work)")
    sets, vals = [], []
    for f in FIELDS:
        if f in body:
            sets.append(f"{f} = %s")
            vals.append(body[f] if f != "mitigates" else (body[f] or []))
    if "geom" in body:
        sets.append("geom = ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)")
        vals.append(json.dumps(body["geom"]))
    if sets:
        with db.tx() as c:
            c.execute("update plans.prep_task set " + ", ".join(sets) + ", updated_at = now() where id = %s", vals + [tid])
    return {"ok": True}


@router.delete("/api/prep/{tid}")
def prep_delete(tid: str, user=Depends(auth.require("planner"))):
    t = _task(tid)
    if t["plan_status"] in LOCKED:
        raise HTTPException(409, "the plan is locked: mark the work 'not needed' instead")
    with db.tx() as c:
        c.execute("delete from plans.prep_task where id = %s", (tid,))
    return {"ok": True}


def add_event(c, tid, status, note, measured, record_id, who):
    if status not in STATUSES:
        raise HTTPException(400, "unknown status")
    if record_id and c.execute("select 1 from plans.prep_event where record_id = %s", (record_id,)).fetchone():
        return  # already applied (the phone resent it)
    c.execute("insert into plans.prep_event (task_id, status, note, measured, record_id, by_user) values (%s,%s,%s,%s,%s,%s)",
              (tid, status, note, db.jsonb(measured or {}), record_id, who))
    c.execute("update plans.prep_task set status = %s, updated_at = now() where id = %s", (status, tid))


@router.post("/api/prep/{tid}/events")
def prep_event(tid: str, body: dict = Body(...), user=Depends(auth.require("planner"))):
    _task(tid)
    with db.tx() as c:
        add_event(c, tid, body.get("status"), body.get("note"), body.get("measured"), None, user["username"])
    return {"ok": True}


@router.get("/api/plans/{pid}/prep.csv")
def prep_csv(pid: int, user=Depends(auth.current_user)):
    """A work order for the crew or contractor."""
    fc = prep_list(pid, user)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Task", "Work", "Width m", "Depth cm", "Length m", "Area ha", "Standard", "DAC clearance", "Needed before", "By", "Assigned to", "Status", "Start (lat,lon)"])
    for f in fc["features"]:
        p = f["properties"]
        g = f["geometry"]
        first = g["coordinates"][0] if g["type"] == "LineString" else (g["coordinates"][0][0] if g["type"] == "Polygon" else g["coordinates"])
        w.writerow([p["title"], p["kind_label"], p["width_m"], p["depth_cm"], p["length_m"], p["area_ha"], p["spec"], "yes" if p["dac_required"] else "no",
                    p["required_for"], p["required_by"], p["assigned_to"], p["status"], f"{first[1]:.6f},{first[0]:.6f}"])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="prep_work_plan_{pid}.csv"'})


@router.get("/api/plans/{pid}/prep.geojson")
def prep_geojson(pid: int, user=Depends(auth.current_user)):
    return Response(json.dumps(prep_list(pid, user)), media_type="application/geo+json",
                    headers={"Content-Disposition": f'attachment; filename="prep_work_plan_{pid}.geojson"'})
