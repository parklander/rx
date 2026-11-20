"""The burn program level: a season's operation order (to sign), the people reused on every burn
and who normally fills each role, and the record of meetings."""
import io
import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import Response

import auth
import db
import schema

router = APIRouter()
ROLE_KEYS = [r[0] for r in schema.ROLES]
ROLE_POSITION = {r[0]: r[2] for r in schema.ROLES if r[2]}
# Qualification each Element 11 position needs (NWCG PMS 310-1 and local equivalents).
POSITION_QUAL = {"RXB1": "RXB1", "RXB2": "RXB2", "RXB3": "RXB3", "FIRB": "FIRB", "IGNITION SPECIALIST": "FIRB",
                 "HOLDING BOSS": "ICT4", "ENGB": "ENGB", "FFT1": "FFT1", "FEMP": "FEMP", "EMT / MEDIC": "EMR",
                 "UXO ADVISOR": "EOD"}


def _season(year):
    s = db.one("select * from plans.season where year = %s", (year,))
    if not s:
        raise HTTPException(404, "no such season")
    return s


def _defaults():
    out = {}
    for sec in schema.OPORD:
        for f in sec["fields"]:
            if "default" in f:
                out[f["key"]] = f["default"]
            elif f["type"] == "table" and f.get("rows"):
                out[f["key"]] = f["rows"]
    return out


def _person(pid):
    p = db.one("select * from plans.person where id = %s", (pid,))
    if not p:
        raise HTTPException(404, "no such person")
    return p


# ---------------------------------------------------------------- seasons and the operation order
@router.get("/api/opord-schema")
def opord_schema(user=Depends(auth.current_user)):
    return {"sections": schema.OPORD, "roles": [{"key": k, "label": l, "position": p} for k, l, p in schema.ROLES],
            "position_qual": POSITION_QUAL, "meeting_kinds": MEETING_KINDS}


@router.get("/api/seasons")
def seasons(user=Depends(auth.current_user)):
    return [db._plain(r) for r in db.all("""
        select s.year, s.op_name, s.status, s.revision, s.signed_name, s.signed_at, s.updated_at, s.start_date, s.end_date,
               (select count(*) from plans.plan p where p.season_year = s.year
                  and not exists (select 1 from plans.plan n where n.parent_plan_id = p.id)) as blocks,
               (select count(*) from plans.meeting m where m.season_year = s.year) as meetings
        from plans.season s order by s.year desc""")]


@router.post("/api/seasons")
def season_new(body: dict = Body(...), user=Depends(auth.require("planner"))):
    """Start a season. copy_from: a previous year whose operation order is carried forward
    (dates and signature cleared); otherwise the template wording."""
    year = int(body["year"])
    if db.one("select 1 from plans.season where year = %s", (year,)):
        raise HTTPException(409, f"{year} already exists")
    content, op = _defaults(), body.get("op_name")
    if body.get("copy_from"):
        prev = _season(int(body["copy_from"]))
        content = dict(prev["opord"])
        op = op or prev["op_name"]
        for k in ("phases", "timings"):  # keep the rows, clear last year's dates
            content[k] = [{**r, "from": None, "to": None, "when": None} for r in content.get(k) or []]
    if body.get("opord"):
        content.update(body["opord"])
    with db.tx() as c:
        c.execute("""insert into plans.season (year, op_name, start_date, end_date, opord, updated_by)
                     values (%s,%s,%s,%s,%s,%s)""",
                  (year, op, body.get("start_date"), body.get("end_date"), db.jsonb(content), user["username"]))
    return season_get(year, user)


@router.get("/api/seasons/{year}")
def season_get(year: int, user=Depends(auth.current_user)):
    s = db._plain(_season(year))
    s["context"] = season_context(year)
    return s


@router.put("/api/seasons/{year}")
def season_save(year: int, body: dict = Body(...), user=Depends(auth.require("planner"))):
    s = _season(year)
    if s["status"] == "signed":
        raise HTTPException(409, "signed: start a revision to change it")
    with db.tx() as c:
        c.execute("""update plans.season set op_name = coalesce(%s, op_name), start_date = %s, end_date = %s,
                     opord = %s, updated_at = now(), updated_by = %s where year = %s""",
                  (body.get("op_name"), body.get("start_date", s["start_date"]), body.get("end_date", s["end_date"]),
                   db.jsonb(body.get("opord", s["opord"])), user["username"], year))
    return season_get(year, user)


@router.post("/api/seasons/{year}/sign")
def season_sign(year: int, body: dict = Body(...), user=Depends(auth.require("burn_boss"))):
    """Record the signature (the signed PDF itself stays in the records system)."""
    s = _season(year)
    if s["status"] == "signed":
        raise HTTPException(409, "already signed")
    name = (body.get("signed_name") or s["opord"].get("auth_name") or "").strip()
    if not name:
        raise HTTPException(400, "who signed it?")
    with db.tx() as c:
        c.execute("""update plans.season set status = 'signed', signed_name = %s, signed_at = %s, updated_at = now(),
                     updated_by = %s where year = %s""",
                  (name, body.get("signed_at") or datetime.now(timezone.utc), user["username"], year))
    return season_get(year, user)


@router.post("/api/seasons/{year}/revise")
def season_revise(year: int, body: dict = Body(default={}), user=Depends(auth.require("planner"))):
    s = _season(year)
    if s["status"] != "signed":
        raise HTTPException(409, "only a signed order is revised")
    with db.tx() as c:
        c.execute("""update plans.season set status = 'draft', revision = revision + 1, signed_name = null, signed_at = null,
                     updated_at = now(), updated_by = %s where year = %s""", (user["username"], year))
    return season_get(year, user)


@router.get("/api/seasons/{year}/history")
def season_history(year: int, user=Depends(auth.current_user)):
    return [db._plain(r) for r in db.all(
        "select id, revision, status, saved_at, saved_by from plans.opord_rev where year = %s order by id desc", (year,))]


def season_context(year):
    """What the operation order pulls from the rest of rx: the season's burn blocks, the resources
    their burn plans need (Element 11), and the points of contact."""
    blocks = [db._plain(r) for r in db.all("""
        with latest as (select p.* from plans.plan p where p.season_year = %s and p.status <> 'cancelled'
                          and not exists (select 1 from plans.plan n where n.parent_plan_id = p.id))
        select l.id, l.name, l.unit_name, l.status, l.complexity, l.planned_window,
               (select round((ST_Area(ST_Union(f.geom)::geography)/10000)::numeric, 1) from plans.feature f
                 where f.plan_id = l.id and f.kind = 'burn_unit') as area_ha
        from latest l order by l.name""", (year,))]
    pos, eq = {}, {}
    for r in db.all("""select e.content from plans.element e where e.code = '11' and e.plan_id in (
                         select p.id from plans.plan p where p.season_year = %s and p.status <> 'cancelled'
                           and not exists (select 1 from plans.plan n where n.parent_plan_id = p.id))""", (year,)):
        for row in (r["content"] or {}).get("positions") or []:
            if row.get("position"):
                q = int(float(row.get("qty") or 1))
                pos[row["position"]] = max(pos.get(row["position"], 0), q)  # burns run one at a time: the most any burn needs
        for row in (r["content"] or {}).get("equipment") or []:
            if row.get("type") and row.get("qty"):
                eq[row["type"]] = max(eq.get(row["type"], 0), int(float(row["qty"])))
    pocs = [db._plain(r) for r in db.all(
        "select id, name, rank, appointment, organization, phone, email from plans.person where poc and active order by id")]
    return {"blocks": blocks, "positions": [{"position": k, "qty": v} for k, v in sorted(pos.items())],
            "equipment": [{"type": k, "qty": v} for k, v in sorted(eq.items())], "pocs": pocs,
            "total_ha": round(sum(b["area_ha"] or 0 for b in blocks), 1)}


# ---------------------------------------------------------------- people and role defaults
@router.get("/api/people")
def people(user=Depends(auth.current_user)):
    rows = [db._plain(r) for r in db.all("select * from plans.person order by active desc, name")]
    roles = {r["role"]: r["person_id"] for r in db.all("select * from plans.role_default")}
    for p in rows:
        p["default_roles"] = [k for k, v in roles.items() if v == p["id"]]
    return rows


def _person_vals(b):
    quals = b.get("quals") or []
    if isinstance(quals, str):
        quals = [q.strip().upper() for q in re.split(r"[,;\s]+", quals) if q.strip()]
    return (b["name"].strip(), b.get("rank"), b.get("appointment"), b.get("organization"), b.get("phone"), b.get("email"),
            quals, bool(b.get("poc")), b.get("active", True), b.get("notes"))


@router.post("/api/people")
def person_add(body: dict = Body(...), user=Depends(auth.require("planner"))):
    if not (body.get("name") or "").strip():
        raise HTTPException(400, "name is required")
    with db.tx() as c:
        return c.execute("""insert into plans.person (name, rank, appointment, organization, phone, email, quals, poc, active, notes)
                            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *""", _person_vals(body)).fetchone()


@router.put("/api/people/{pid}")
def person_edit(pid: int, body: dict = Body(...), user=Depends(auth.require("planner"))):
    merged = {**_person(pid), **body}
    with db.tx() as c:
        return c.execute("""update plans.person set name=%s, rank=%s, appointment=%s, organization=%s, phone=%s, email=%s,
                            quals=%s, poc=%s, active=%s, notes=%s, updated_at=now() where id=%s returning *""",
                         (*_person_vals(merged), pid)).fetchone()


@router.delete("/api/people/{pid}")
def person_delete(pid: int, user=Depends(auth.require("planner"))):
    """People named in meetings are kept and set inactive instead."""
    _person(pid)
    with db.tx() as c:
        used = c.execute("select 1 from plans.meeting where %s = any(attendees) limit 1", (pid,)).fetchone()
        if used:
            c.execute("update plans.person set active = false, updated_at = now() where id = %s", (pid,))
            return {"ok": True, "deactivated": True}
        c.execute("delete from plans.person where id = %s", (pid,))
    return {"ok": True}


RANKS = {"gen", "lgen", "mgen", "bgen", "col", "lcol", "maj", "capt", "lt", "2lt", "ocdt", "cwo", "mwo", "wo", "sgt", "mcpl",
         "cpl", "pte", "avr", "mr", "mrs", "ms", "dr"}


def parse_poc(line):
    """'Maj B. Smith    G3 Ops    CSN 258-0000' (columns from a pasted OPORD) or 'Maj B. Smith, G3 Ops, 258-0000'."""
    parts = [x.strip() for x in re.split(r"\t|\s{2,}|\s*[,;|]\s*|\s+[–—-]\s+", line.strip()) if x.strip()]
    if not parts:
        return None
    phone = None
    if re.search(r"\d{3}[\s-]?\d{3,4}", parts[-1]) and len(parts) > 1:
        phone = re.sub(r"^(?:CSN|tel|ph|phone)\s*:?\s*", "", parts.pop(), flags=re.I).strip()
    words = parts[0].split()
    rank = None
    if len(words) > 1 and words[0].lower().rstrip(".") in RANKS:
        rank = words.pop(0).rstrip(".")
    name = " ".join(words)
    if not re.match(r"^[A-Z][\w.'’\- ]+$", name) or len(words) < 2 or not (rank or phone or parts[1:]):
        return None  # headings such as "Points of Contact"
    return {"name": name, "rank": rank, "appointment": " ".join(parts[1:]) or None, "phone": phone}


@router.post("/api/people/import")
def people_import(body: dict = Body(...), user=Depends(auth.require("planner"))):
    """Paste the points of contact from an operation order, one person per line. Matches existing people by name.
    dry_run returns what would be added."""
    out = []
    for line in (body.get("text") or "").splitlines():
        if not line.strip():
            continue
        rec = parse_poc(line)
        if not rec:
            out.append({"line": line, "error": "not understood"})
            continue
        rec["poc"] = bool(body.get("poc", True))
        found = db.one("select id from plans.person where lower(name) = lower(%s)", (rec["name"],))
        rec["existing_id"] = found["id"] if found else None
        out.append(rec)
    if not body.get("dry_run"):
        for r in out:
            if r.get("error"):
                continue
            if r["existing_id"]:
                person_edit(r["existing_id"], {k: v for k, v in r.items() if v and k not in ("existing_id",)}, user)
            else:
                r["id"] = person_add(r, user)["id"]
    return out


@router.get("/api/role-defaults")
def role_defaults(user=Depends(auth.current_user)):
    cur = {r["role"]: r["person_id"] for r in db.all("select * from plans.role_default")}
    names = {r["id"]: r for r in db.all("select id, name, quals, active from plans.person")}
    return [{"role": k, "label": l, "position": p, "person_id": cur.get(k),
             "name": names[cur[k]]["name"] if cur.get(k) in names else None,
             "qualified": _qualified(names.get(cur.get(k)), p)} for k, l, p in schema.ROLES]


@router.put("/api/role-defaults")
def role_defaults_set(body: dict = Body(...), user=Depends(auth.require("burn_boss"))):
    """body: {role: person_id or null}"""
    with db.tx() as c:
        for role, pid in body.items():
            if role not in ROLE_KEYS:
                raise HTTPException(400, f"unknown role {role}")
            c.execute("""insert into plans.role_default (role, person_id) values (%s,%s)
                         on conflict (role) do update set person_id = excluded.person_id""", (role, pid or None))
    return role_defaults(user)


def _qualified(person, position):
    need = POSITION_QUAL.get(position or "")
    if not person or not need:
        return None
    have = set(person["quals"] or [])
    if not have:
        return None  # nothing recorded yet
    if need.startswith("RXB"):  # a higher burn boss qualification covers a lower one
        lvl = int(need[-1])
        return any(q.startswith("RXB") and q[-1:].isdigit() and int(q[-1]) <= lvl for q in have)
    return need in have


def plan_defaults():
    """Element 11 positions and the Element 2A administrator for a new plan, from the role defaults."""
    rows = db.all("""select d.role, p.name from plans.role_default d join plans.person p on p.id = d.person_id
                     where p.active""")
    by = {r["role"]: r["name"] for r in rows}
    positions = [{"position": ROLE_POSITION[k], "qty": 1, "name": by[k]} for k in ROLE_KEYS if k in by and k in ROLE_POSITION]
    out = {}
    if positions:
        out["11"] = {"positions": positions}
    if by.get("agency_administrator"):
        out["2A"] = {"administrator": by["agency_administrator"]}
    return out


@router.get("/api/plans/{pid}/quals")
def plan_quals(pid: int, user=Depends(auth.current_user)):
    """Check the names in Element 11 against the qualifications recorded in People."""
    e = db.one("select content from plans.element where plan_id = %s and code = '11'", (pid,))
    people_ = {r["name"].lower(): r for r in db.all("select id, name, quals, active from plans.person")}
    out = []
    for row in ((e or {}).get("content") or {}).get("positions") or []:
        for nm in [n.strip() for n in re.split(r"[,;/]", row.get("name") or "") if n.strip()]:
            p = people_.get(nm.lower())
            out.append({"position": row.get("position"), "name": nm, "known": bool(p),
                        "needs": POSITION_QUAL.get(row.get("position") or ""), "quals": (p or {}).get("quals") or [],
                        "qualified": _qualified(p, row.get("position")) if p else None})
    return out


@router.post("/api/program/import")
def program_import(body: dict = Body(...), user=Depends(auth.require("burn_boss"))):
    """Load a program file kept outside the repo: {season: {...}, people: [...], role_defaults: {role: name}}.
    People are matched by name; an existing season is updated unless it is signed."""
    out = {"people_added": 0, "people_updated": 0}
    ids = {r["name"].lower(): r["id"] for r in db.all("select id, name from plans.person")}
    for p in body.get("people") or []:
        if p["name"].lower() in ids:
            person_edit(ids[p["name"].lower()], p, user); out["people_updated"] += 1
        else:
            ids[p["name"].lower()] = person_add(p, user)["id"]; out["people_added"] += 1
    if body.get("role_defaults"):
        missing = [n for n in body["role_defaults"].values() if n and n.lower() not in ids]
        if missing:
            raise HTTPException(400, f"role defaults name people not in the file or directory: {', '.join(missing)}")
        role_defaults_set({r: ids[n.lower()] if n else None for r, n in body["role_defaults"].items()}, user)
        out["role_defaults"] = len(body["role_defaults"])
    s = body.get("season")
    if s:
        year = int(s["year"])
        content = {**_defaults(), **(s.get("opord") or {})}
        cur = db.one("select status from plans.season where year = %s", (year,))
        with db.tx() as c:
            if not cur:
                c.execute("""insert into plans.season (year, op_name, start_date, end_date, opord, updated_by) values (%s,%s,%s,%s,%s,%s)""",
                          (year, s.get("op_name"), s.get("start_date"), s.get("end_date"), db.jsonb(content), user["username"]))
            elif cur["status"] == "signed":
                raise HTTPException(409, f"{year} is signed: start a revision first")
            else:
                c.execute("""update plans.season set op_name=%s, start_date=%s, end_date=%s, opord=%s, updated_at=now(), updated_by=%s
                             where year=%s""", (s.get("op_name"), s.get("start_date"), s.get("end_date"), db.jsonb(content), user["username"], year))
            if s.get("signed_name"):  # an order already signed on paper or by PDF signature
                c.execute("update plans.season set status='signed', signed_name=%s, signed_at=%s where year=%s",
                          (s["signed_name"], s.get("signed_at"), year))
        out["season"] = year
    return out


# ---------------------------------------------------------------- meetings
MEETING_KINDS = ["planning", "coordination", "briefing", "aar", "other"]


@router.get("/api/meetings")
def meetings(season: int | None = None, plan_id: int | None = None, user=Depends(auth.current_user)):
    q, a = "select m.*, p.name as plan_name from plans.meeting m left join plans.plan p on p.id = m.plan_id where true", []
    if season:
        q += " and m.season_year = %s"; a.append(season)
    if plan_id:
        q += " and m.plan_id = %s"; a.append(plan_id)
    return [db._plain(r) for r in db.all(q + " order by m.held_at desc", a)]


def _meeting_vals(b, user):
    if b.get("kind", "planning") not in MEETING_KINDS:
        raise HTTPException(400, "unknown meeting kind")
    if not (b.get("title") or "").strip() or not b.get("held_at"):
        raise HTTPException(400, "title and date are required")
    return (b.get("season_year"), b.get("plan_id") or None, b.get("kind", "planning"), b["title"].strip(), b["held_at"],
            b.get("location"), [int(x) for x in b.get("attendees") or []], b.get("others"), b.get("agenda"),
            b.get("notes"), b.get("decisions"), db.jsonb(b.get("actions") or []), user["username"])


@router.post("/api/meetings")
def meeting_add(body: dict = Body(...), user=Depends(auth.require("planner"))):
    with db.tx() as c:
        return db._plain(c.execute("""insert into plans.meeting (season_year, plan_id, kind, title, held_at, location, attendees, others,
                            agenda, notes, decisions, actions, created_by) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *""",
                         _meeting_vals(body, user)).fetchone())


@router.put("/api/meetings/{mid}")
def meeting_edit(mid: int, body: dict = Body(...), user=Depends(auth.require("planner"))):
    m = db.one("select * from plans.meeting where id = %s", (mid,))
    if not m:
        raise HTTPException(404, "no such meeting")
    with db.tx() as c:
        return db._plain(c.execute("""update plans.meeting set season_year=%s, plan_id=%s, kind=%s, title=%s, held_at=%s, location=%s,
                            attendees=%s, others=%s, agenda=%s, notes=%s, decisions=%s, actions=%s, created_by=%s, updated_at=now()
                            where id=%s returning *""", (*_meeting_vals({**m, **body}, user), mid)).fetchone())


@router.delete("/api/meetings/{mid}")
def meeting_delete(mid: int, user=Depends(auth.require("planner"))):
    with db.tx() as c:
        c.execute("delete from plans.meeting where id = %s", (mid,))
    return {"ok": True}


@router.get("/api/actions")
def open_actions(season: int | None = None, user=Depends(auth.current_user)):
    """Open action items across meetings."""
    out = []
    for m in meetings(season, None, user):
        for i, a in enumerate(m["actions"] or []):
            if not a.get("done"):
                out.append({**a, "meeting_id": m["id"], "meeting": m["title"], "held_at": m["held_at"], "index": i})
    return sorted(out, key=lambda a: a.get("due") or "9999")


# ---------------------------------------------------------------- Word export in the OPORD layout
@router.get("/api/seasons/{year}/opord.docx")
def opord_docx(year: int, user=Depends(auth.current_user)):
    import export_docx
    s = db._plain(_season(year))
    data = export_docx.opord(s, season_context(year), schema.OPORD)
    fn = f"{year}-{re.sub(r'[^A-Za-z0-9]+', '_', s['op_name'] or 'OPORD').strip('_')}_OPORD.docx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="{fn}"'})
