"""rx: prescribed fire planning (NWCG PMS 484-1) over a versioned PostGIS database.

Run:  uvicorn app:app --host 127.0.0.1 --port 8100
"""
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import auth
import db
import export_docx
import field
import forecast
import prep
import program
import schema

ROOT = Path(__file__).resolve().parent
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("rx")

LAYER_RE = re.compile(r"^[a-z_]+\.[a-z_]+$")
EVENT_FIELDS = {
    "fuels.treatment": ["kind", "occurred_on", "ended_on", "plan_id", "completeness_pct", "note"],
    "fuels.plot": ["plot_code", "sampled_on", "fuel_class", "load_kg_m2", "curing_pct", "height_cm", "note"],
    "fuels.test_fire": ["plan_id", "burn_day_id", "occurred_at", "fuel_class", "temp_c", "rh_pct", "wind_kmh", "wind_dir_deg", "result", "spread_note"],
    "habitat.observation": ["species", "observed_on", "kind", "count", "restricted", "note"],
}
PLAN_KINDS = ['burn_unit', 'ignition_unit', 'contingency_area', 'holding_line', 'contingency_line', 'trigger_point', 'safety_zone',
              'escape_route', 'anchor_point', 'test_fire_site', 'drop_point', 'firing_line', 'lookout', 'other']
LOCKED = ("approved", "implemented", "closed")


@asynccontextmanager
async def lifespan(app):
    db.open_pool()
    yield
    db.pool.close()

app = FastAPI(title="rx", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.include_router(field.router)
app.include_router(prep.router)
app.include_router(program.router)


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/m")
@app.get("/m/{rest:path}")
def mobile(rest: str = ""):
    return FileResponse(ROOT / "static" / "m.html")


@app.get("/sw.js")
def sw():
    return FileResponse(ROOT / "static" / "sw.js", media_type="text/javascript")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(ROOT / "static" / "manifest.webmanifest", media_type="application/manifest+json")


# --- auth ----------------------------------------------------------------------
@app.post("/api/login")
def login(response: Response, body: dict = Body(...)):
    token = auth.login(body.get("username", ""), body.get("password", ""))
    if not token:
        raise HTTPException(401, "wrong username or password")
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite="strict", secure=os.environ.get("RX_INSECURE_COOKIE") != "1",
                        max_age=auth.SESSION_DAYS * 86400, path="/")
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    tok = request.cookies.get(auth.COOKIE)
    if tok:
        auth.logout(tok)
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(auth.current_user)):
    return user


# --- catalogue -----------------------------------------------------------------
@app.get("/api/element-defs")
def element_defs(user=Depends(auth.current_user)):
    rows = db.all("select code, ord, title, owner_role, guidance from plans.element_def order by ord")
    for r in rows:
        r["fields"] = schema.fields(r["code"])
        r["map"] = schema.has_map(r["code"])
    return rows


@app.get("/api/layers")
def layers(user=Depends(auth.current_user)):
    rows = db.all("select * from meta.layer order by name")
    rel = db.all("select * from meta.release order by id desc")
    sync = db.one("""select checked_at, status, remote_modified, release_id from meta.source_sync
                     where source = 'eccc_critical_habitat' order by checked_at desc limit 1""")
    for r in rows:
        r["releases"] = [db._plain(x) for x in rel if x["layer"] == r["name"]]
        r["visible"] = not r["sensitive"] or auth.ROLES.index(user["role"]) >= 1
        if r["name"] == "habitat.critical_habitat" and sync:
            r["sync"] = db._plain(sync)
    return rows


def _layer(name, user):
    row = db.one("select * from meta.layer where name = %s", (name,))
    if not row or not LAYER_RE.match(name):
        raise HTTPException(404, "no such layer")
    if row["sensitive"] and auth.ROLES.index(user["role"]) < 1:
        raise HTTPException(403, "sensitive layer: planner role or higher")
    return row


@app.get("/api/layers/{name}")
def layer_features(name: str, bbox: Optional[str] = None, known_at: Optional[datetime] = None,
                   on_ground: Optional[datetime] = None, user=Depends(auth.current_user)):
    """State layers: the version true on the ground at `on_ground`, as known at `known_at` (both default now).
    Event layers: records up to `on_ground`."""
    meta = _layer(name, user)
    where, params = [], []
    if bbox:
        x1, y1, x2, y2 = [float(v) for v in bbox.split(",")]
        where.append("geom && ST_MakeEnvelope(%s,%s,%s,%s,4326)")
        params += [x1, y1, x2, y2]
    if meta["kind"] == "state":
        where.append("recorded @> %s::timestamptz and valid @> %s::timestamptz")
        k = known_at or datetime.now(timezone.utc)
        params += [k, on_ground or k]
        sql = f"select *, ST_AsGeoJSON(geom, 6)::json as gj from {name}"
        id_key = "feature_id"
    else:
        sql = f"select *, ST_AsGeoJSON(geom, 6)::json as gj from {name}"
        id_key = "event_id" if name == "fuels.treatment" else "id"
    if where:
        sql += " where " + " and ".join(where)
    rows = db.all(sql + " limit 5000", params)
    for r in rows:
        r.pop("geom", None)
        r.pop("recorded", None)
    return db.feature_collection(rows, geom_key="gj", id_key=id_key)


@app.get("/api/layers/{name}/history/{fid}")
def layer_history(name: str, fid: str, user=Depends(auth.current_user)):
    meta = _layer(name, user)
    if meta["kind"] != "state":
        raise HTTPException(400, "event layers have no versions")
    rows = db.all(f"""select row_id, valid, recorded, change_note, changed_by, release_id,
                             to_jsonb(t) - 'geom' - 'row_id' - 'valid' - 'recorded' - 'feature_id' as attrs
                      from {name} t where feature_id = %s order by lower(recorded), lower(valid)""", (fid,))
    return [db._plain(r) for r in rows]


@app.post("/api/layers/{name}/features")
def layer_add(name: str, body: dict = Body(...), user=Depends(auth.require("planner"))):
    """body: {data: {..attrs.., geom: GeoJSON}, valid_from?, note?, release_id?}"""
    meta = _layer(name, user)
    if meta["kind"] != "state":
        return _event_add(name, body, user)
    with db.tx() as c:
        fid = c.execute("select meta.vwrite(%s::regclass, null, %s, coalesce(%s::timestamptz, now()), %s, %s, %s) as fid",
                        (name, db.jsonb(body["data"]), body.get("valid_from"), body.get("note"), user["username"],
                         body.get("release_id"))).fetchone()["fid"]
    return {"feature_id": str(fid)}


@app.put("/api/layers/{name}/features/{fid}")
def layer_update(name: str, fid: str, body: dict = Body(...), user=Depends(auth.require("planner"))):
    meta = _layer(name, user)
    if meta["kind"] != "state":
        raise HTTPException(400, "event records are append-only")
    with db.tx() as c:
        c.execute("select meta.vwrite(%s::regclass, %s::uuid, %s, coalesce(%s::timestamptz, now()), %s, %s, %s)",
                  (name, fid, db.jsonb(body["data"]), body.get("valid_from"), body.get("note"), user["username"], body.get("release_id")))
    return {"feature_id": fid}


@app.delete("/api/layers/{name}/features/{fid}")
def layer_retire(name: str, fid: str, valid_to: Optional[datetime] = None, note: Optional[str] = None,
                 user=Depends(auth.require("planner"))):
    _layer(name, user)
    with db.tx() as c:
        c.execute("select meta.vretire(%s::regclass, %s::uuid, coalesce(%s::timestamptz, now()), %s, %s)",
                  (name, fid, valid_to, note, user["username"]))
    return {"retired": fid}


def _event_add(name, body, user):
    fields = EVENT_FIELDS.get(name)
    if not fields:
        raise HTTPException(400, "not an event layer")
    data = body["data"]
    cols = [f for f in fields if f in data]
    vals = [data[f] for f in cols]
    geom = json.dumps(data["geom"])
    gexpr = "ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s),4326))" if name == "fuels.treatment" else "ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)"
    sql = f"insert into {name} ({', '.join(cols + ['recorded_by', 'geom'])}) values ({', '.join(['%s'] * (len(cols) + 1))}, {gexpr}) returning *"
    with db.tx() as c:
        row = c.execute(sql, vals + [user["username"], geom]).fetchone()
    return {"id": str(row.get("id") or row.get("event_id"))}


@app.get("/api/releases")
def releases(user=Depends(auth.current_user)):
    return [db._plain(r) for r in db.all("select * from meta.release order by id desc")]


@app.post("/api/releases")
def release_add(body: dict = Body(...), user=Depends(auth.require("planner"))):
    with db.tx() as c:
        r = c.execute("""insert into meta.release (layer, name, notes, created_by) values (%s,%s,%s,%s) returning id""",
                      (body["layer"], body["name"], body.get("notes"), user["username"])).fetchone()
    return r


@app.post("/api/releases/{rid}/publish")
def release_publish(rid: int, user=Depends(auth.require("burn_boss"))):
    with db.tx() as c:
        c.execute("update meta.release set published_at = now() where id = %s and published_at is null", (rid,))
    return {"ok": True}


# --- plans -----------------------------------------------------------------------
def _plan(pid):
    p = db.one("select * from plans.plan where id = %s", (pid,))
    if not p:
        raise HTTPException(404, "no such plan")
    return p


def _editable(pid):
    p = _plan(pid)
    if p["status"] in LOCKED:
        raise HTTPException(409, f"plan is {p['status']}: amend it to make changes")
    return p


def _touch(c, pid, user):
    c.execute("update plans.plan set updated_at = now() where id = %s", (pid,))


@app.get("/api/plans")
def plans_list(user=Depends(auth.current_user)):
    rows = db.all("""select p.id, p.name, p.unit_name, p.status, p.complexity, p.version_no, p.demo, p.updated_at, p.planned_window, p.season_year,
                            (select round((sum(ST_Area(geom::geography))/10000)::numeric, 1) from plans.feature f
                              where f.plan_id = p.id and f.kind = 'burn_unit') as area_ha,
                            (select count(*) from plans.element e where e.plan_id = p.id and e.status = 'complete') as complete,
                            (select count(*) from plans.element_def) as total
                     from plans.plan p order by p.updated_at desc""")
    return [db._plain(r) for r in rows]


@app.post("/api/plans")
def plan_new(body: dict = Body(...), user=Depends(auth.require("planner"))):
    with db.tx() as c:
        season = body.get("season_year") or (c.execute("select max(year) y from plans.season").fetchone() or {}).get("y") \
            or datetime.now().year
        r = c.execute("""insert into plans.plan (name, unit_name, complexity, min_burn_boss, planned_window, created_by, season_year)
                         values (%s,%s,%s,%s,%s,%s,%s) returning id""",
                      (body["name"], body.get("unit_name"), body.get("complexity"), body.get("min_burn_boss"),
                       body.get("planned_window"), user["username"], season)).fetchone()
        for code, content in program.plan_defaults().items():  # e.g. the usual burn boss in Element 11
            c.execute("""insert into plans.element (plan_id, code, content, status, updated_by) values (%s,%s,%s,'draft',%s)
                         on conflict (plan_id, code) do update set content = plans.element.content || excluded.content""",
                      (r["id"], code, db.jsonb(content), "role defaults"))
        if body.get("geom"):  # drawn on the program map: the burn block becomes the plan's burn unit
            c.execute("""insert into plans.feature (plan_id, kind, label, geom, updated_by)
                         values (%s, 'burn_unit', %s, ST_SetSRID(ST_GeomFromGeoJSON(%s),4326), %s)""",
                      (r["id"], body["name"], json.dumps(body["geom"]), user["username"]))
    return r


@app.get("/api/blocks")
def blocks(user=Depends(auth.current_user)):
    """The program map: the burn unit of the newest version of every plan, with its status,
    area, last fire on record (fuels.treatment) and site visit count."""
    rows = db.all("""
        with latest as (select p.* from plans.plan p where not exists (select 1 from plans.plan n where n.parent_plan_id = p.id)),
        unit as (select plan_id, ST_Union(geom) g from plans.feature where kind = 'burn_unit' group by plan_id)
        select l.id, l.name, l.unit_name, l.status, l.version_no, l.complexity, l.planned_window, l.demo, l.updated_at, l.season_year,
               round((ST_Area(u.g::geography)/10000)::numeric, 1) as area_ha,
               (select max(coalesce(t.ended_on, t.occurred_on)) from fuels.treatment t
                 where t.kind in ('prescribed_burn','wildfire') and ST_Intersects(t.geom, u.g)) as last_fire,
               (select count(*) from plans.element e where e.plan_id = l.id and e.status = 'complete') as complete,
               (select count(*) from plans.element_def) as total,
               (select max(b.burn_date) from plans.burn_day b where b.plan_id = l.id and b.decision = 'go') as burned_on,
               (select count(*) from field.visit v where v.plan_id in (select plans.lineage(l.id))) as visits,
               ST_AsGeoJSON(u.g, 6)::json as gj
        from latest l join unit u on u.plan_id = l.id
        where l.status <> 'cancelled' order by l.updated_at desc""")
    return db.feature_collection(rows, geom_key="gj")


@app.get("/api/plans/{pid}")
def plan_get(pid: int, user=Depends(auth.current_user)):
    p = db._plain(_plan(pid))
    p["elements"] = {r["code"]: db._plain(r) for r in db.all("select * from plans.element where plan_id = %s", (pid,))}
    p["prescription"] = [db._plain(r) for r in db.all("select * from plans.prescription_param where plan_id = %s order by id", (pid,))]
    p["variants"] = [db._plain(r) for r in db.all("select * from plans.ignition_variant where plan_id = %s order by id", (pid,))]
    p["signatures"] = [db._plain(r) for r in db.all("select * from plans.signature where plan_id = %s order by id", (pid,))]
    p["burn_days"] = [db._plain(r) for r in db.all("select * from plans.burn_day where plan_id = %s order by burn_date desc", (pid,))]
    p["versions"] = [db._plain(r) for r in db.all(
        """with recursive up as (select id, parent_plan_id, version_no, status, amendment_note from plans.plan where id = %s
                                 union all select p.id, p.parent_plan_id, p.version_no, p.status, p.amendment_note from plans.plan p join up on p.id = up.parent_plan_id)
           select id, version_no, status, amendment_note from up order by version_no""", (pid,))]
    p["successor"] = db.one("select id from plans.plan where parent_plan_id = %s", (pid,))
    p["prep"] = prep.summarize(pid)
    c = db.one("""with u as (select ST_Centroid(ST_Union(geom)) g from plans.feature where plan_id = %s and kind = 'burn_unit')
                  select ST_Y(g) lat, ST_X(g) lon, ST_X(ST_Transform(g, 32614)) e, ST_Y(ST_Transform(g, 32614)) n from u where g is not null""", (pid,))
    p["centroid"] = {"lat": round(c["lat"], 5), "lon": round(c["lon"], 5), "utm": f"14U {c['e']:.0f} E {c['n']:.0f} N"} if c else None
    # smoke receptors within 40 km, with distance and bearing from the unit
    p["receptors"] = [db._plain(r) for r in db.all("""
        with u as (select ST_Centroid(ST_Union(geom)) g from plans.feature where plan_id = %s and kind = 'burn_unit'),
             k as (select coalesce(as_of, now()) t from plans.plan where id = %s)
        select r.name, r.kind, r.sensitivity, round((ST_Distance(r.geom::geography, u.g::geography)/1000)::numeric, 1) km,
               round(degrees(ST_Azimuth(u.g, r.geom))::numeric) bearing
        from smoke.receptor r, u, k where r.recorded @> k.t and r.valid @> k.t and ST_DWithin(r.geom::geography, u.g::geography, 40000)
        order by km""", (pid, pid))] if c else []
    return p


@app.patch("/api/plans/{pid}")
def plan_patch(pid: int, body: dict = Body(...), user=Depends(auth.require("planner"))):
    _editable(pid)
    allowed = ["name", "unit_name", "complexity", "min_burn_boss", "planned_window", "admin_unit", "season_year"]
    sets = [(k, body[k]) for k in allowed if k in body]
    if sets:
        with db.tx() as c:
            c.execute("update plans.plan set " + ", ".join(f"{k} = %s" for k, _ in sets) + ", updated_at = now() where id = %s",
                      [v for _, v in sets] + [pid])
    return {"ok": True}


@app.put("/api/plans/{pid}/elements/{code}")
def element_save(pid: int, code: str, body: dict = Body(...), user=Depends(auth.require("planner"))):
    _editable(pid)
    status = body.get("status", "draft")
    with db.tx() as c:
        c.execute("""insert into plans.element (plan_id, code, content, status, updated_at, updated_by)
                     values (%s,%s,%s,%s,now(),%s)
                     on conflict (plan_id, code) do update set content = excluded.content, status = excluded.status,
                       updated_at = now(), updated_by = excluded.updated_by""",
                  (pid, code, db.jsonb(body.get("content", {})), status, user["username"]))
        _touch(c, pid, user)
    return {"ok": True}


@app.get("/api/plans/{pid}/elements/{code}/history")
def element_history(pid: int, code: str, user=Depends(auth.current_user)):
    return [db._plain(r) for r in db.all("select * from plans.element_rev where plan_id = %s and code = %s order by id desc limit 100", (pid, code))]


@app.get("/api/plans/{pid}/features")
def plan_features(pid: int, user=Depends(auth.current_user)):
    rows = db.all("""select id, kind, label, variant_id, props, updated_at,
                            round((ST_Area(geom::geography)/10000)::numeric, 2) as area_ha,
                            round(ST_Length(geom::geography)::numeric) as length_m,
                            ST_AsGeoJSON(geom, 7)::json as gj
                     from plans.feature where plan_id = %s order by kind, label""", (pid,))
    return db.feature_collection(rows, geom_key="gj")


@app.post("/api/plans/{pid}/features")
def plan_feature_add(pid: int, body: dict = Body(...), user=Depends(auth.require("planner"))):
    _editable(pid)
    if body.get("kind") not in PLAN_KINDS:
        raise HTTPException(400, "unknown kind")
    with db.tx() as c:
        r = c.execute("""insert into plans.feature (plan_id, kind, label, variant_id, props, geom, updated_by)
                         values (%s,%s,%s,%s,%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s) returning id""",
                      (pid, body["kind"], body.get("label"), body.get("variant_id"), db.jsonb(body.get("props", {})),
                       json.dumps(body["geom"]), user["username"])).fetchone()
        _touch(c, pid, user)
    return {"id": str(r["id"])}


@app.put("/api/plans/{pid}/features/{fid}")
def plan_feature_put(pid: int, fid: str, body: dict = Body(...), user=Depends(auth.require("planner"))):
    _editable(pid)
    sets, vals = [], []
    for k in ("kind", "label", "variant_id"):
        if k in body:
            sets.append(f"{k} = %s")
            vals.append(body[k])
    if "props" in body:
        sets.append("props = %s")
        vals.append(db.jsonb(body["props"]))
    if "geom" in body:
        sets.append("geom = ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)")
        vals.append(json.dumps(body["geom"]))
    if sets:
        with db.tx() as c:
            c.execute("update plans.feature set " + ", ".join(sets) + ", updated_at = now(), updated_by = %s where id = %s and plan_id = %s",
                      vals + [user["username"], fid, pid])
            _touch(c, pid, user)
    return {"ok": True}


@app.delete("/api/plans/{pid}/features/{fid}")
def plan_feature_del(pid: int, fid: str, user=Depends(auth.require("planner"))):
    _editable(pid)
    with db.tx() as c:
        c.execute("delete from plans.feature where id = %s and plan_id = %s", (fid, pid))
        _touch(c, pid, user)
    return {"ok": True}


@app.put("/api/plans/{pid}/prescription")
def prescription_put(pid: int, body: list = Body(...), user=Depends(auth.require("planner"))):
    _editable(pid)
    with db.tx() as c:
        c.execute("delete from plans.prescription_param where plan_id = %s", (pid,))
        for p in body:
            if p.get("param"):
                c.execute("insert into plans.prescription_param (plan_id, param, low, high, note) values (%s,%s,%s,%s,%s)",
                          (pid, p["param"], p.get("low"), p.get("high"), p.get("note")))
        _touch(c, pid, user)
    return {"ok": True}


@app.post("/api/plans/{pid}/variants")
def variant_add(pid: int, body: dict = Body(...), user=Depends(auth.require("planner"))):
    _editable(pid)
    with db.tx() as c:
        r = c.execute("""insert into plans.ignition_variant (plan_id, name, wind_dir_min, wind_dir_max, description, firing_sequence)
                         values (%s,%s,%s,%s,%s,%s) returning id""",
                      (pid, body["name"], body["wind_dir_min"], body["wind_dir_max"], body.get("description"),
                       db.jsonb(body.get("firing_sequence", [])))).fetchone()
    return r


@app.put("/api/plans/{pid}/variants/{vid}")
def variant_put(pid: int, vid: int, body: dict = Body(...), user=Depends(auth.require("planner"))):
    _editable(pid)
    with db.tx() as c:
        c.execute("""update plans.ignition_variant set name=%s, wind_dir_min=%s, wind_dir_max=%s, description=%s, firing_sequence=%s
                     where id = %s and plan_id = %s""",
                  (body["name"], body["wind_dir_min"], body["wind_dir_max"], body.get("description"),
                   db.jsonb(body.get("firing_sequence", [])), vid, pid))
    return {"ok": True}


@app.delete("/api/plans/{pid}/variants/{vid}")
def variant_del(pid: int, vid: int, user=Depends(auth.require("planner"))):
    _editable(pid)
    with db.tx() as c:
        c.execute("delete from plans.ignition_variant where id = %s and plan_id = %s", (vid, pid))
    return {"ok": True}


@app.get("/api/plans/{pid}/overlay")
def plan_overlay(pid: int, user=Depends(auth.current_user)):
    """Everything in the versioned layers that falls in the burn unit or the contingency area,
    as known at approval (or now for a draft), with a fuel area summary."""
    p = _plan(pid)
    sens = {r["name"] for r in db.all("select name from meta.layer where sensitive")}
    rows = db.all("select * from plans.overlay(%s)", (pid,))
    if auth.ROLES.index(user["role"]) < 1:
        rows = [r for r in rows if r["layer"] not in sens]
    feats = [{"type": "Feature", "geometry": r["geom_json"],
              "properties": {"layer": r["layer"], "zone": r["zone"], **db._plain(r["props"] or {})}} for r in rows]
    fuels = db.all("""
        with k as (select coalesce(as_of, now()) t from plans.plan where id = %(p)s),
        u as (select ST_Union(geom) g from plans.feature where plan_id = %(p)s and kind = 'burn_unit'),
        ca as (select ST_Union(geom) g from plans.feature where plan_id = %(p)s and kind = 'contingency_area'),
        f as (select fuel_class, geom, row_id from fuels.fuel_class, k where recorded @> k.t and valid @> k.t),
        -- smaller polygons sit on top of the background class: give each point to its smallest polygon
        ranked as (select f1.fuel_class, ST_Difference(f1.geom, coalesce((select ST_Union(f2.geom) from f f2
                     where ST_Area(f2.geom) < ST_Area(f1.geom) and ST_Intersects(f1.geom, f2.geom)), ST_SetSRID('GEOMETRYCOLLECTION EMPTY'::geometry, 4326))) g
                   from f f1)
        select fuel_class,
               round((sum(ST_Area(ST_Intersection(ranked.g, u.g)::geography))/10000)::numeric, 1) as unit_ha,
               round((sum(ST_Area(ST_Intersection(ranked.g, ST_Difference(ca.g, u.g))::geography))/10000)::numeric, 1) as contingency_ha
        from ranked, u, ca group by fuel_class order by unit_ha desc nulls last""", {"p": pid})
    return {"as_of": p["as_of"].isoformat() if p["as_of"] else None, "features": feats,
            "fuels": [db._plain(f) for f in fuels]}


@app.get("/api/plans/{pid}/terrain")
def plan_terrain(pid: int, user=Depends(auth.current_user)):
    """Elevation, slope and aspect for the burn unit and each ignition unit, from the current DEM version."""
    import terrain
    _plan(pid)
    ver = terrain.current()
    out = {"dem": terrain.dem_info(ver), "unit": None, "ignition_units": []}
    if not ver:
        return out
    unit = db.one("select ST_AsGeoJSON(ST_Union(geom))::json g from plans.feature where plan_id = %s and kind = 'burn_unit'", (pid,))
    try:
        if unit and unit["g"]:
            out["unit"] = terrain.stats(unit["g"], ver)
        for r in db.all("""select coalesce(label, 'Ignition unit') label, ST_AsGeoJSON(geom)::json g from plans.feature
                           where plan_id = %s and kind = 'ignition_unit' order by label""", (pid,)):
            out["ignition_units"].append({"label": r["label"], **(terrain.stats(r["g"], ver) or {})})
    except Exception as e:   # a missing or unreadable DEM file should not break the plan view
        out["error"] = f"{type(e).__name__}: {e}"
    return out


@app.post("/api/plans/{pid}/status")
def plan_status(pid: int, body: dict = Body(...), user=Depends(auth.require("planner"))):
    p = _plan(pid)
    to = body.get("status")
    flow = {"draft": ["review", "cancelled"], "review": ["draft", "approved", "cancelled"],
            "approved": ["implemented", "cancelled"], "implemented": ["closed"], "closed": [], "cancelled": []}
    if to not in flow.get(p["status"], []):
        raise HTTPException(409, f"cannot go from {p['status']} to {to}")
    if to == "approved" and auth.ROLES.index(user["role"]) < auth.ROLES.index("burn_boss"):
        raise HTTPException(403, "approval needs the burn_boss role")
    with db.tx() as c:
        c.execute("select set_config('rx.allow_locked','on',true)")
        if to == "approved":
            # freeze: knowledge time + the latest published release of every layer
            c.execute("""update plans.plan set status = 'approved', approved_at = now(), approved_by = %s, as_of = now(),
                           release_ids = (select array_agg(id) from (select distinct on (layer) id from meta.release
                                          where published_at is not null order by layer, published_at desc) r),
                           updated_at = now() where id = %s""", (user["username"], pid))
        else:
            c.execute("update plans.plan set status = %s, updated_at = now() where id = %s", (to, pid))
    return {"ok": True}


@app.post("/api/plans/{pid}/amend")
def plan_amend(pid: int, body: dict = Body(...), user=Depends(auth.require("planner"))):
    """Copy an approved plan into a new draft version."""
    p = _plan(pid)
    if p["status"] not in LOCKED:
        raise HTTPException(409, "only approved, implemented or closed plans are amended; edit the draft instead")
    if db.one("select 1 from plans.plan where parent_plan_id = %s", (pid,)):
        raise HTTPException(409, "this version already has an amendment")
    with db.tx() as c:
        new = c.execute("""insert into plans.plan (name, unit_name, admin_unit, complexity, min_burn_boss, planned_window,
                             version_no, parent_plan_id, amendment_note, demo, created_by, season_year)
                           select name, unit_name, admin_unit, complexity, min_burn_boss, planned_window, version_no + 1, id, %s, demo, %s, season_year
                           from plans.plan where id = %s returning id""", (body.get("note"), user["username"], pid)).fetchone()["id"]
        c.execute("insert into plans.element (plan_id, code, content, status, updated_by) select %s, code, content, status, %s from plans.element where plan_id = %s",
                  (new, user["username"], pid))
        c.execute("insert into plans.feature (plan_id, kind, label, props, geom, updated_by) select %s, kind, label, props, geom, %s from plans.feature where plan_id = %s",
                  (new, user["username"], pid))
        c.execute("insert into plans.prescription_param (plan_id, param, low, high, note) select %s, param, low, high, note from plans.prescription_param where plan_id = %s", (new, pid))
        c.execute("""insert into plans.prep_task (plan_id, kind, title, width_m, depth_cm, spec, dac_required, required_for, required_by, assigned_to, mitigates, status, geom, created_by)
                     select %s, kind, title, width_m, depth_cm, spec, dac_required, required_for, required_by, assigned_to, mitigates, status, geom, %s
                     from plans.prep_task where plan_id = %s""", (new, user["username"], pid))
        c.execute("""insert into plans.ignition_variant (plan_id, name, wind_dir_min, wind_dir_max, description, firing_sequence)
                     select %s, name, wind_dir_min, wind_dir_max, description, firing_sequence from plans.ignition_variant where plan_id = %s""", (new, pid))
    return {"id": new}


@app.post("/api/plans/{pid}/signatures")
def signature_add(pid: int, body: dict = Body(...), user=Depends(auth.require("planner"))):
    with db.tx() as c:
        c.execute("insert into plans.signature (plan_id, role, name, qualification, signed_by) values (%s,%s,%s,%s,%s)",
                  (pid, body["role"], body["name"], body.get("qualification"), user["username"]))
    return {"ok": True}


# --- burn days and forecasts ---------------------------------------------------
@app.post("/api/plans/{pid}/burn-days")
def burn_day_add(pid: int, body: dict = Body(...), user=Depends(auth.require("planner"))):
    p = _plan(pid)
    if p["status"] not in ("approved", "implemented"):
        raise HTTPException(409, "burn days are added to approved plans")
    with db.tx() as c:
        r = c.execute("insert into plans.burn_day (plan_id, burn_date) values (%s,%s) returning id", (pid, body["burn_date"])).fetchone()
    return r


@app.post("/api/burn-days/{bid}/forecast")
def burn_day_forecast(bid: int, body: dict = Body(default={}), user=Depends(auth.require("planner"))):
    """Fetch the hourly forecast at the unit for the burn date, freeze it as a snapshot,
    and check it against the prescription and the ignition variants."""
    bd = db.one("select * from plans.burn_day where id = %s", (bid,))
    if not bd:
        raise HTTPException(404)
    c0 = db.one("select ST_X(ST_Centroid(ST_Union(geom))) x, ST_Y(ST_Centroid(ST_Union(geom))) y from plans.feature where plan_id = %s and kind='burn_unit'", (bd["plan_id"],))
    if c0["x"] is None:
        raise HTTPException(409, "draw the burn unit first")
    try:
        hourly = body.get("hourly") or forecast.fetch_hourly(c0["y"], c0["x"], bd["burn_date"])
    except Exception as e:
        log.warning("forecast fetch failed: %s", e)
        raise HTTPException(502, "the forecast service could not be reached; try again")
    if not hourly:
        raise HTTPException(502, "no forecast hours returned for that date")
    params = db.all("select param, low, high from plans.prescription_param where plan_id = %s", (bd["plan_id"],))
    variants = db.all("select id, name, wind_dir_min, wind_dir_max from plans.ignition_variant where plan_id = %s", (bd["plan_id"],))
    check = forecast.evaluate(hourly, params, variants)
    with db.tx() as c:
        sid = c.execute("""insert into weather.forecast_snapshot (source, issued_at, stage, hourly, note, geom)
                           values (%s, now(), %s, %s, %s, ST_SetSRID(ST_MakePoint(%s,%s),4326)) returning id""",
                        (body.get("source", forecast.SOURCE), body.get("stage", "burn_morning"), db.jsonb(hourly),
                         body.get("note"), c0["x"], c0["y"])).fetchone()["id"]
        c.execute("update plans.burn_day set forecast_snapshot_id = %s where id = %s", (sid, bid))
    return {"snapshot_id": sid, **check}


@app.get("/api/burn-days/{bid}")
def burn_day_get(bid: int, user=Depends(auth.current_user)):
    bd = db.one("select * from plans.burn_day where id = %s", (bid,))
    if not bd:
        raise HTTPException(404)
    out = db._plain(bd)
    if bd["forecast_snapshot_id"]:
        s = db.one("select * from weather.forecast_snapshot where id = %s", (bd["forecast_snapshot_id"],))
        params = db.all("select param, low, high from plans.prescription_param where plan_id = %s", (bd["plan_id"],))
        variants = db.all("select id, name, wind_dir_min, wind_dir_max from plans.ignition_variant where plan_id = %s", (bd["plan_id"],))
        out["forecast"] = {"source": s["source"], "issued_at": s["issued_at"].isoformat(), "stage": s["stage"],
                           **forecast.evaluate(s["hourly"], params, variants)}
    return out


@app.put("/api/burn-days/{bid}")
def burn_day_put(bid: int, body: dict = Body(...), user=Depends(auth.require("planner"))):
    bd = db.one("select * from plans.burn_day where id = %s", (bid,))
    if not bd:
        raise HTTPException(404)
    if body.get("decision") in ("go", "no_go") and auth.ROLES.index(user["role"]) < auth.ROLES.index("burn_boss"):
        raise HTTPException(403, "the go / no-go decision needs the burn_boss role")
    if body.get("decision") == "go":
        open_work = prep.summarize(bd["plan_id"])["outstanding_for_ignition"]
        if open_work and not body.get("override_reason"):
            raise HTTPException(409, "pre-burn work needed before ignition is not verified: " + "; ".join(f"{w['title']} ({w['status']})" for w in open_work))
        if open_work:
            body["notes"] = (body.get("notes") or bd["notes"] or "") + "\nGO with unverified pre-burn work (" + ", ".join(w["title"] for w in open_work) + "): " + body["override_reason"]
    with db.tx() as c:
        c.execute("""update plans.burn_day set variant_id = coalesce(%s, variant_id), checklist = coalesce(%s, checklist),
                       notes = coalesce(%s, notes), test_fire_result = coalesce(%s, test_fire_result),
                       observed_wx = coalesce(%s, observed_wx),
                       decision = coalesce(%s, decision),
                       decided_by = case when %s::text is not null then %s else decided_by end,
                       decided_at = case when %s::text is not null then now() else decided_at end
                     where id = %s""",
                  (body.get("variant_id"), db.jsonb(body["checklist"]) if "checklist" in body else None, body.get("notes"),
                   body.get("test_fire_result"), db.jsonb(body["observed_wx"]) if "observed_wx" in body else None,
                   body.get("decision"), body.get("decision"), user["username"], body.get("decision"), bid))
        if body.get("decision") == "go":
            c.execute("select set_config('rx.allow_locked','on',true)")
            c.execute("update plans.plan set status = 'implemented' where id = %s and status = 'approved'", (bd["plan_id"],))
    return {"ok": True}


# --- export and mobile bundle ----------------------------------------------------
@app.get("/api/plans/{pid}/export.docx")
def plan_export(pid: int, user=Depends(auth.current_user)):
    plan = plan_get(pid, user)
    defs = element_defs(user)
    overlay = plan_overlay(pid, user)
    plan["prep_tasks"] = prep.prep_list(pid, user)["features"]
    data = export_docx.render(plan, defs, overlay, plan_features(pid, user))
    fname = re.sub(r"[^A-Za-z0-9_-]+", "_", plan["name"]) + f"_v{plan['version_no']}.docx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.get("/api/plans/{pid}/bundle")
def plan_bundle(pid: int, user=Depends(auth.current_user)):
    """Everything the mobile review view needs, in one request it can cache for offline use."""
    return {"plan": plan_get(pid, user), "defs": element_defs(user), "features": plan_features(pid, user), "prep": prep.prep_list(pid, user),
            "overlay": plan_overlay(pid, user), "fetched_at": datetime.now(timezone.utc).isoformat()}
