"""Field site visits: pre-burn recce, monitoring, post-burn. Records and photos are created on the
device with their own ids, so the phone can work offline and resend safely."""
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps

import auth
import db

router = APIRouter()
MEDIA = Path(os.environ.get("RX_MEDIA_DIR", Path(__file__).resolve().parent / "media"))
MAX_UPLOAD = 25 * 1024 * 1024
FULL_PX, THUMB_PX = 2560, 480

# Pre-burn recce checklist: what gets walked or driven before a burn.
RECCE_ITEMS = [
    ("holding_lines", "Holding lines: width, condition, regrowth, gaps"),
    ("contingency_lines", "Contingency lines passable and in condition"),
    ("anchor_point", "Anchor point and test fire site suitable"),
    ("access", "Access roads, gates and crossings for engines and tenders"),
    ("water", "Water sources: level and tender access"),
    ("safety_zones", "Safety zones adequate for crew size"),
    ("escape_routes", "Escape routes driven and timed"),
    ("hazards", "Hazards: UXO, snags, structures, power lines, fences"),
    ("values", "Values at risk protected (latrines, structures, habitat exclusions)"),
    ("fuels", "Fuels match the plan (curing, load, continuity, juniper)"),
    ("smoke", "Smoke receptors and sensitive roads checked"),
    ("comms", "Radio coverage checked at key points"),
]


def _dt(v):
    return datetime.fromisoformat(v.replace("Z", "+00:00")) if isinstance(v, str) else v


@router.get("/api/field/recce-items")
def recce_items(user=Depends(auth.current_user)):
    return [{"key": k, "label": l} for k, l in RECCE_ITEMS]


@router.post("/api/visits")
def visit_upsert(body: dict = Body(...), user=Depends(auth.require("planner"))):
    with db.tx() as c:
        c.execute("""insert into field.visit (id, plan_id, kind, title, started_at, ended_at, crew, weather, notes, created_by)
                     values (%(id)s, %(plan_id)s, %(kind)s, %(title)s, %(started_at)s, %(ended_at)s, %(crew)s, %(weather)s, %(notes)s, %(by)s)
                     on conflict (id) do update set plan_id = excluded.plan_id, kind = excluded.kind, title = excluded.title,
                       ended_at = excluded.ended_at, crew = excluded.crew, weather = excluded.weather, notes = excluded.notes,
                       synced_at = now()""",
                  {"id": body["id"], "plan_id": body.get("plan_id"), "kind": body.get("kind", "pre_burn_recce"),
                   "title": body.get("title"), "started_at": _dt(body["started_at"]), "ended_at": _dt(body.get("ended_at")),
                   "crew": body.get("crew"), "weather": body.get("weather"), "notes": body.get("notes"), "by": user["username"]})
    return {"id": body["id"]}


@router.get("/api/visits")
def visits(plan_id: Optional[int] = None, user=Depends(auth.current_user)):
    rows = db.all("""select v.*, (select count(*) from field.record r where r.visit_id = v.id) as n_records,
                            (select count(*) from field.media m join field.record r on r.id = m.record_id where r.visit_id = v.id) as n_photos,
                            (select count(*) from field.record r where r.visit_id = v.id and r.status = 'issue') as n_issues
                     from field.visit v where (%s::int is null or v.plan_id in (select plans.lineage(%s))) order by v.started_at desc limit 200""", (plan_id, plan_id))
    return [db._plain(r) for r in rows]


def _records(where, params):
    rows = db.all(f"""select r.id, r.visit_id, r.kind, r.item, r.status, r.text, r.data, r.accuracy_m, r.heading_deg,
                             r.observed_at, r.created_by, v.kind as visit_kind, v.plan_id,
                             coalesce((select json_agg(m.id order by m.taken_at) from field.media m where m.record_id = r.id), '[]') as media,
                             ST_AsGeoJSON(r.geom, 7)::json as gj
                      from field.record r join field.visit v on v.id = r.visit_id where {where} order by r.observed_at""", params)
    feats = []
    for r in rows:
        g = r.pop("gj")
        feats.append({"type": "Feature", "id": str(r["id"]), "geometry": g, "properties": db._plain(r)})
    return {"type": "FeatureCollection", "features": feats}


@router.get("/api/visits/{vid}")
def visit_get(vid: str, user=Depends(auth.current_user)):
    v = db.one("select * from field.visit where id = %s", (vid,))
    if not v:
        raise HTTPException(404, "no such visit")
    return {"visit": db._plain(v), "records": _records("r.visit_id = %s", (vid,))}


@router.get("/api/plans/{pid}/visit-records")
def plan_visit_records(pid: int, user=Depends(auth.current_user)):
    return _records("v.plan_id in (select plans.lineage(%s))", (pid,))


def _fuel_load(d):
    """kg/m² from what was measured: dry weight, or wet weight with moisture content (% of dry weight)."""
    try:
        if d.get("load_kg_m2") not in (None, ""):
            return float(d["load_kg_m2"])
        frame = float(d.get("frame_m2") or 0)
        if frame <= 0:
            return None
        if d.get("dry_g") not in (None, ""):
            return round(float(d["dry_g"]) / 1000 / frame, 3)
        if d.get("wet_g") not in (None, "") and d.get("moisture_pct") not in (None, ""):
            return round(float(d["wet_g"]) / (1 + float(d["moisture_pct"]) / 100) / 1000 / frame, 3)
    except (TypeError, ValueError):
        return None
    return None


@router.post("/api/visits/{vid}/records")
def record_upsert(vid: str, body: dict = Body(...), user=Depends(auth.require("planner"))):
    if not db.one("select 1 from field.visit where id = %s", (vid,)):
        raise HTTPException(404, "visit not synced yet")
    data = body.get("data") or {}
    if body["kind"] == "fuel_plot":
        load = _fuel_load(data)
        if load is not None:
            data["load_kg_m2"] = load
    lon, lat = body.get("lon"), body.get("lat")
    with db.tx() as c:
        c.execute("""insert into field.record (id, visit_id, kind, item, status, text, data, accuracy_m, heading_deg, observed_at, created_by, geom)
                     values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, case when %s::float is null then null else ST_SetSRID(ST_MakePoint(%s,%s),4326) end)
                     on conflict (id) do update set item = excluded.item, status = excluded.status, text = excluded.text, data = excluded.data,
                       accuracy_m = excluded.accuracy_m, heading_deg = excluded.heading_deg, geom = excluded.geom, synced_at = now()""",
                  (body["id"], vid, body["kind"], body.get("item"), body.get("status"), body.get("text"), db.jsonb(data),
                   body.get("accuracy_m"), body.get("heading_deg"), _dt(body["observed_at"]), user["username"], lon, lon, lat))
        # a fuel plot with a position also becomes a record in the fuels database (once)
        if body["kind"] == "fuel_plot" and lon is not None and not c.execute(
                "select 1 from fuels.plot where source_record = %s", (body["id"],)).fetchone():
            c.execute("select set_config('rx.versioning','on',true)")
            c.execute("""insert into fuels.plot (plot_code, sampled_on, fuel_class, load_kg_m2, curing_pct, height_cm, note, recorded_by, source_record, geom)
                         values (%s, %s::timestamptz::date, %s, %s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s,%s),4326))""",
                      (data.get("plot_code") or "field", _dt(body["observed_at"]), data.get("fuel_class"), data.get("load_kg_m2"),
                       data.get("curing_pct") or None, data.get("height_cm") or None, body.get("text"), user["username"], body["id"], lon, lat))
            c.execute("select set_config('rx.versioning','off',true)")
    return {"id": body["id"], "data": data}


@router.delete("/api/records/{rid}")
def record_delete(rid: str, user=Depends(auth.require("planner"))):
    with db.tx() as c:
        for m in c.execute("select filename from field.media where record_id = %s", (rid,)).fetchall():
            for f in (MEDIA / m["filename"], MEDIA / m["filename"].replace(".jpg", "_t.jpg")):
                f.unlink(missing_ok=True)
        c.execute("delete from field.record where id = %s", (rid,))
    return {"ok": True}


@router.post("/api/records/{rid}/media")
async def media_upload(rid: str, file: UploadFile = File(...), media_id: str = Form(...),
                       taken_at: Optional[str] = Form(None), user=Depends(auth.require("planner"))):
    if db.one("select 1 from field.media where id = %s", (media_id,)):
        return {"id": media_id, "duplicate": True}
    if not db.one("select 1 from field.record where id = %s", (rid,)):
        raise HTTPException(404, "record not synced yet")
    raw = await file.read()
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "photo too large")
    try:
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    except Exception:
        raise HTTPException(400, "not an image")
    im.thumbnail((FULL_PX, FULL_PX))
    sub = datetime.now(timezone.utc).strftime("%Y/%m")
    (MEDIA / sub).mkdir(parents=True, exist_ok=True)
    name = f"{sub}/{media_id}.jpg"
    im.save(MEDIA / name, "JPEG", quality=85)
    th = im.copy()
    th.thumbnail((THUMB_PX, THUMB_PX))
    th.save(MEDIA / name.replace(".jpg", "_t.jpg"), "JPEG", quality=80)
    with db.tx() as c:
        c.execute("""insert into field.media (id, record_id, filename, content_type, bytes, width, height, taken_at, created_by)
                     values (%s,%s,%s,'image/jpeg',%s,%s,%s,%s,%s) on conflict (id) do nothing""",
                  (media_id, rid, name, (MEDIA / name).stat().st_size, im.width, im.height, _dt(taken_at), user["username"]))
    return {"id": media_id}


@router.get("/api/media/{mid}")
def media_get(mid: str, size: str = "full", user=Depends(auth.current_user)):
    m = db.one("select filename from field.media where id = %s", (mid,))
    if not m:
        raise HTTPException(404)
    f = MEDIA / (m["filename"].replace(".jpg", "_t.jpg") if size == "thumb" else m["filename"])
    if not f.exists():
        raise HTTPException(404, "file missing")
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=31536000, immutable"})
