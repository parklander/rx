"""Keep habitat.critical_habitat in step with ECCC's national critical habitat dataset.

    python habitat_sync.py              check; download and load only if ECCC has published a new version
    python habitat_sync.py --force      download and load even if nothing looks new
    python habitat_sync.py --file CriticalHabitat.zip   load a zip you downloaded yourself
    python habitat_sync.py --dry-run    do everything except write to the database

Steps:
1. Check: the dataset record on open.canada.ca (date modified, download URL) and the download's HTTP
   headers (ETag, Last-Modified, size) against the last check in meta.source_sync.
2. Download the FGDB zip and compare its SHA-256 with the last one loaded.
3. Extract it into a new empty temporary folder and read every layer (areas and points, final and proposed).
4. Filter: keep features within RX_CH_RADIUS_KM (default 60) of RX_CH_CENTRE (default CFB Shilo).
5. Integrate: one release per ECCC version. New features are added, changed ones get a new version,
   features ECCC dropped are retired. Nothing is overwritten; earlier versions stay queryable.
   Features loaded by hand (source is null, e.g. the Red-headed Woodpecker grid) are left alone.
6. Every check is logged in meta.source_sync, including "unchanged" and "failed".
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import pyogrio.raw
import shapely
from pyproj import CRS, Transformer
from shapely import wkb
from shapely.geometry import MultiPoint, MultiPolygon, Point, Polygon, mapping

import db

SOURCE = "eccc_critical_habitat"
TABLE = "habitat.critical_habitat"
WHO = "eccc-sync"
DATASET_ID = "47caa405-be2b-4e9e-8f53-c478ade2ca74"
CKAN = f"https://open.canada.ca/data/api/action/package_show?id={DATASET_ID}"
FALLBACK_URL = "https://data-donnees.ec.gc.ca/data/species/protectrestore/critical-habitat-species-at-risk-canada/CriticalHabitat.zip"

CENTRE = [float(v) for v in os.environ.get("RX_CH_CENTRE", "-99.637,49.805").split(",")]   # lon, lat
RADIUS_KM = float(os.environ.get("RX_CH_RADIUS_KM", "60"))
SOURCE_DIR = Path(os.environ.get("RX_SOURCE_DIR", "/var/lib/rx/sources")) / SOURCE
MAX_UNZIPPED = 8 * 1024 ** 3     # refuse archives that would unpack to more than 8 GB


# --- 1. check ------------------------------------------------------------------------------
def remote_state(client):
    """What ECCC currently publishes: dataset date, download URL and the download's headers."""
    state = {"remote_modified": None, "url": os.environ.get("RX_CH_URL") or FALLBACK_URL}
    try:
        res = client.get(CKAN).raise_for_status().json()["result"]
        state["remote_modified"] = res.get("date_modified") or res.get("metadata_modified")
        for r in res.get("resources", []):
            fmt, lang = (r.get("format") or "").upper(), r.get("language") or []
            if ("GDB" in fmt or "FGDB" in fmt) and ("en" in lang or r.get("url", "").endswith("/CriticalHabitat.zip")):
                state["url"] = os.environ.get("RX_CH_URL") or r["url"]
                break
    except (httpx.HTTPError, KeyError, ValueError) as e:
        print(f"open.canada.ca record not readable ({e}); using {state['url']}")
    h = client.head(state["url"])
    if h.status_code >= 400:   # some servers refuse HEAD; a ranged GET gives the same headers
        h = client.get(state["url"], headers={"Range": "bytes=0-0"})
    h.raise_for_status()
    state["etag"] = h.headers.get("etag")
    state["last_modified"] = h.headers.get("last-modified")
    cl = h.headers.get("content-range", "").rpartition("/")[2] or h.headers.get("content-length")
    state["content_length"] = int(cl) if cl and cl.isdigit() else None
    return state


def last_check():
    return db.one("""select * from meta.source_sync where source = %s and status <> 'failed' and sha256 is not null
                     order by checked_at desc limit 1""", (SOURCE,))


def looks_unchanged(state, last):
    """Unchanged only if every signal both sides have agrees, and at least one was compared."""
    if not last:
        return False
    pairs = [(state.get(k), last[k]) for k in ("remote_modified", "etag", "last_modified", "content_length")]
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    return bool(pairs) and all(str(a) == str(b) for a, b in pairs)


# --- 2. download ---------------------------------------------------------------------------
def download(client, url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".part")
    h = hashlib.sha256()
    with client.stream("GET", url) as r:
        r.raise_for_status()
        with open(part, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                h.update(chunk)
    part.replace(dest)
    return h.hexdigest()


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --- 3. extract ----------------------------------------------------------------------------
def extract(zpath, into):
    """Unzip into an empty folder, refusing absolute paths, '..' and zip bombs. Returns the .gdb folder."""
    root = Path(into).resolve()
    with zipfile.ZipFile(zpath) as z:
        if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
            raise ValueError("archive unpacks to more than 8 GB")
        for i in z.infolist():
            target = (root / i.filename).resolve()
            if root not in target.parents and target != root:
                raise ValueError(f"unsafe path in archive: {i.filename}")
        z.extractall(root)
    gdbs = [p for p in root.rglob("*.gdb") if p.is_dir()]
    if not gdbs:
        raise ValueError("no .gdb folder in the archive")
    return gdbs[0]


# --- 4. read and filter --------------------------------------------------------------------
def transform(fn, geom):
    """Reproject a shapely geometry with a pyproj transform function (always_xy)."""
    return shapely.transform(geom, lambda xy: np.column_stack(fn(xy[:, 0], xy[:, 1])))


def aoi_circle():
    aeqd = CRS.from_proj4(f"+proj=aeqd +lat_0={CENTRE[1]} +lon_0={CENTRE[0]} +units=m")
    to_ll = Transformer.from_crs(aeqd, 4326, always_xy=True).transform
    return transform(to_ll, Point(0, 0).buffer(RADIUS_KM * 1000, 64))


def _s(v):
    if v is None:
        return None
    if hasattr(v, "item"):   # numpy scalar
        v = v.item()
    if isinstance(v, float) and v != v:   # NaN
        return None
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _int(v):
    v = _s(v)
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def read_features(gdb):
    """Every critical habitat feature within the AOI, in EPSG:4326, grouped by its stable key."""
    aoi = aoi_circle()
    groups, seen_layers = {}, []
    for name, gtype in pyogrio.list_layers(gdb):
        if not gtype:
            continue   # tables (e.g. lookups), not features
        info = pyogrio.read_info(gdb, layer=name)
        crs = CRS.from_user_input(info["crs"]) if info.get("crs") else CRS.from_epsg(3978)
        to_layer = Transformer.from_crs(4326, crs, always_xy=True).transform
        to_ll = Transformer.from_crs(crs, 4326, always_xy=True).transform
        aoi_l = transform(to_layer, aoi)
        meta, _, geoms, cols = pyogrio.raw.read(gdb, layer=name, bbox=aoi_l.bounds)
        fields = list(meta["fields"])
        proposed = "propos" in name.lower()
        seen_layers.append(f"{name}: {len(geoms)} in AOI box")
        for i, g in enumerate(geoms):
            if g is None:
                continue
            geom = wkb.loads(bytes(g))
            if geom.is_empty or not geom.intersects(aoi_l):
                continue
            geom = shapely.make_valid(transform(to_ll, geom))
            p = {f: _s(cols[j][i]) for j, f in enumerate(fields)}
            kind = "point" if geom.geom_type in ("Point", "MultiPoint") else "area"
            status = "proposed" if proposed else "final"
            site = p.get("SiteID")
            ident = site or "g" + hashlib.sha1(shapely.normalize(shapely.set_precision(geom, 1e-6)).wkb).hexdigest()[:12]
            key = "|".join(str(x) for x in (p.get("COSEWIC_ID") or p.get("SciName"), p.get("Population_E") or "", ident, kind, status))
            attrs = {
                "species": p.get("CommName_E") or p.get("SciName") or "unknown",
                "sci_name": p.get("SciName"),
                "status": status,
                "population": p.get("Population_E") or p.get("Sub_Species_E"),
                "site_id": site,
                "site_name": p.get("SiteName_E"),
                "cosewic_id": _int(p.get("COSEWIC_ID")),
                "sara_status": _int(p.get("SARA_Status")),
                "sensitivity": p.get("Sensitive_E"),
                "tenure": None,
                "grid_id": None,
                "source_doc": p.get("RDoc_Name_E"),
                "source": "eccc_national",
                "source_key": key,
            }
            grp = groups.setdefault(key, {"attrs": attrs, "parts": []})
            grp["parts"].append(geom)
    out = {}
    for key, grp in groups.items():
        g = shapely.union_all(grp["parts"])
        polys = [x for x in getattr(g, "geoms", [g]) if isinstance(x, (Polygon, MultiPolygon))]
        pts = [x for x in getattr(g, "geoms", [g]) if x.geom_type in ("Point", "MultiPoint")]
        if polys:
            g = MultiPolygon([q for x in polys for q in getattr(x, "geoms", [x])])
        elif pts:
            g = MultiPoint([q for x in pts for q in getattr(x, "geoms", [x])])
        else:
            continue
        g = shapely.normalize(shapely.set_precision(g, 1e-7))
        out[key] = {**grp["attrs"], "geom": g}
    return out, seen_layers


# --- 5. integrate --------------------------------------------------------------------------
ATTRS = ["species", "sci_name", "status", "population", "site_id", "site_name", "cosewic_id",
         "sara_status", "sensitivity", "source_doc"]


def current_features(c):
    rows = c.execute(f"""select feature_id, source_key, to_jsonb(t) - 'geom' as a, ST_AsBinary(geom) as g
                         from {TABLE} t where source = 'eccc_national' and upper_inf(recorded) and upper_inf(valid)""").fetchall()
    return {r["source_key"]: {"fid": r["feature_id"], "attrs": r["a"], "geom": shapely.normalize(wkb.loads(bytes(r["g"])))} for r in rows}


def same(cur, new):
    if any((cur["attrs"].get(k) if cur["attrs"].get(k) != "" else None) != new.get(k) for k in ATTRS):
        return False
    return cur["geom"].equals_exact(new["geom"], 1e-7) or cur["geom"].equals(new["geom"])


def plan_changes(cur, new):
    add = [k for k in new if k not in cur]
    change = [k for k in new if k in cur and not same(cur[k], new[k])]
    retire = [k for k in cur if k not in new]
    return add, change, retire


def valid_from(remote_modified):
    try:
        d = datetime.fromisoformat(str(remote_modified).replace(" ", "T"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def integrate(c, new, state, sha, dry_run=False):
    cur = current_features(c)
    add, change, retire = plan_changes(cur, new)
    counts = {"added": len(add), "changed": len(change), "retired": len(retire), "kept_in_aoi": len(new)}
    if dry_run or not (add or change or retire):
        return None, counts
    vf = valid_from(state.get("remote_modified"))
    label = str(state.get("remote_modified") or datetime.now(timezone.utc).date())[:10]
    rid = c.execute("""insert into meta.release (layer, name, notes, created_by, published_at)
                       values (%s, %s, %s, %s, now()) returning id""",
                    (TABLE, f"ECCC critical habitat {label}",
                     f"National dataset, {RADIUS_KM:g} km around {CENTRE[1]}, {CENTRE[0]}. "
                     f"{len(add)} added, {len(change)} changed, {len(retire)} retired. SHA-256 {sha[:12]}.", WHO)).fetchone()["id"]
    note = f"ECCC national dataset {label}"

    def not_before_current(fid):
        """A change or retirement can't take effect before the version it replaces began."""
        v = c.execute(f"select lower(valid) v from {TABLE} where feature_id = %s and upper_inf(recorded) and upper_inf(valid)", (fid,)).fetchone()
        return max(vf, v["v"]) if v and v["v"] else vf

    for k in add + change:
        data = {**new[k], "geom": mapping(new[k]["geom"])}
        fid = cur[k]["fid"] if k in cur else None
        c.execute("select meta.vwrite(%s::regclass, %s, %s, %s, %s, %s, %s)",
                  (TABLE, fid, db.jsonb(data), vf if fid is None else not_before_current(fid), note, WHO, rid))
    for k in retire:
        c.execute("select meta.vretire(%s::regclass, %s, %s, %s, %s, %s)",
                  (TABLE, cur[k]["fid"], not_before_current(cur[k]["fid"]), f"no longer in {note}", WHO, rid))
    return rid, counts


def log(c, status, state=None, sha=None, release=None, counts=None, message=None):
    state, counts = state or {}, counts or {}
    c.execute("""insert into meta.source_sync (source, status, remote_modified, etag, last_modified, content_length, sha256,
                                               release_id, added, changed, retired, kept_in_aoi, message)
                 values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              (SOURCE, status, state.get("remote_modified"), state.get("etag"), state.get("last_modified"),
               state.get("content_length"), sha, release, counts.get("added", 0), counts.get("changed", 0),
               counts.get("retired", 0), counts.get("kept_in_aoi"), message))


# --- run -----------------------------------------------------------------------------------
def run(force=False, file=None, dry_run=False):
    db.open_pool()
    state, sha = {}, None
    try:
        last = last_check()
        if file:
            zpath = Path(file)
            state = {"remote_modified": None, "url": str(zpath)}
            sha = sha256_of(zpath)
        else:
            with httpx.Client(timeout=httpx.Timeout(60, read=600), follow_redirects=True,
                              headers={"User-Agent": "rx.rtams.ca critical habitat sync"}) as client:
                state = remote_state(client)
                if not force and looks_unchanged(state, last):
                    if not dry_run:
                        with db.tx() as c:
                            log(c, "unchanged", state, last["sha256"], message="headers and dataset date match the last check")
                    print(f"unchanged since {last['checked_at']:%Y-%m-%d} (ECCC dataset {state.get('remote_modified')})")
                    return "unchanged"
                print(f"downloading {state['url']}")
                zpath = SOURCE_DIR / "CriticalHabitat.zip"
                sha = download(client, state["url"], zpath)
        if not force and last and sha == last["sha256"]:
            if not dry_run:
                with db.tx() as c:
                    log(c, "unchanged", state, sha, message="same file as the last load")
            print("downloaded file is identical to the last one loaded")
            return "unchanged"

        work = Path(tempfile.mkdtemp(prefix="eccc_ch_"))   # new, empty folder for the untrusted archive
        try:
            gdb = extract(zpath, work)
            new, layers = read_features(gdb)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        print("\n".join(layers))

        with db.tx() as c:
            rid, counts = integrate(c, new, state, sha, dry_run)
            status = ("would update" if dry_run and any(counts[k] for k in ("added", "changed", "retired"))
                      else "updated" if rid else "no_change_in_aoi")
            if not dry_run:
                log(c, status, state, sha, rid, counts)
        print(f"{status}: {json.dumps(counts)}" + (f", release {rid}" if rid else "") + (" (dry run)" if dry_run else ""))
        return status
    except Exception as e:
        if not dry_run:
            try:
                with db.tx() as c:
                    log(c, "failed", state, sha, message=f"{type(e).__name__}: {e}"[:2000])
            except Exception:
                pass
        print(f"failed: {e}", file=sys.stderr)
        raise
    finally:
        db.pool.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="download and load even if nothing looks new")
    ap.add_argument("--file", help="load this CriticalHabitat.zip instead of downloading")
    ap.add_argument("--dry-run", action="store_true", help="report what would change; write nothing")
    a = ap.parse_args(argv)
    run(a.force, a.file, a.dry_run)


if __name__ == "__main__":
    main()
