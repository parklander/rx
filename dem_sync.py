"""Keep a Shilo-area elevation model in step with NRCan's CanElevation series.

    python dem_sync.py              check; rebuild only if NRCan has published new data (or the area grew)
    python dem_sync.py --force      rebuild even if nothing looks new
    python dem_sync.py --dry-run    report what would be built; write nothing

Steps:
1. Check: look up the HRDEM Mosaic 2 m and MRDEM 30 m terrain models (DTM) for the area in NRCan's STAC
   catalogue, plus each file's HTTP headers. Compare with the version currently in use.
2. Read only the area needed, straight from NRCan's Cloud Optimized GeoTIFFs (no national download),
   at the coarsest overview that is still finer than the output resolution.
3. Build one grid in NAD83(CSRS) / UTM 14N (EPSG:2957) at RX_DEM_RES metres (default 5). Lidar (HRDEM) is
   used wherever it exists; MRDEM fills the gaps. Band 2 records which source each cell came from.
4. Save it as a new versioned COG under RX_SOURCE_DIR/nrcan_dem, mark it current, keep the one before it.
5. Log every check in meta.source_sync.

The area is RX_DEM_BBOX (lon/lat, default the Shilo RTA) widened to take in every burn block and
contingency area on record, so a new block outside it triggers a rebuild at the next check.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import rasterio
import rasterio.shutil
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window
from rasterio.windows import transform as win_transform

import db

SOURCE = "nrcan_dem"
LAYER = "terrain.dem"
WHO = "dem-sync"
STAC = os.environ.get("RX_DEM_STAC", "https://datacube.services.geo.ca/stac/api/search")
# Priority order: the first source with a value in a cell wins.
#   HRDEM Mosaic 2 m: NRCan lidar DTM, CGVD2013. Best where it exists.
#   GEM-15: Google's experimental 15 m DTM from stereo satellite imagery (bare earth predicted by a model),
#           heights on EGM96 (EPSG:5773), not CGVD2013; CC-BY 4.0, "This dataset was produced by Google".
#   MRDEM 30 m: NRCan national DTM, CGVD2013. Complete coverage, used last.
GEM_URLS = [u for u in os.environ.get("RX_DEM_GEM_URLS",
            "https://storage.googleapis.com/climate-and-sustainability/gem-15/p40_m100/wm100s49/dtm/zall/mosaic.tif").split(",") if u]
SOURCES = [{"collection": "hrdem-mosaic-2m", "asset": "dtm", "title": "HRDEM Mosaic 2 m (lidar)", "vertical": "CGVD2013"},
           *[{"collection": "gem-15", "url": u, "title": "GEM-15 15 m (Google, experimental)", "vertical": "EGM96"} for u in GEM_URLS],
           {"collection": "mrdem-30", "asset": "dtm", "title": "MRDEM 30 m", "vertical": "CGVD2013"}]
MRDEM_FALLBACK = "https://datacube-prod-data-public.s3.amazonaws.com/store/elevation/mrdem/mrdem-30/mrdem-30-dtm.tif"
DST_CRS = "EPSG:2957"
RES = float(os.environ.get("RX_DEM_RES", "5"))
BBOX = [float(v) for v in os.environ.get("RX_DEM_BBOX", "-99.95,49.55,-99.30,49.92").split(",")]
OUT_DIR = Path(os.environ.get("RX_SOURCE_DIR", "/var/lib/rx/sources")) / SOURCE
TILE = 1024
GDAL_ENV = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF,.vrt",
                GDAL_HTTP_MAX_RETRY=4, GDAL_HTTP_RETRY_DELAY=2, VSI_CACHE=True, GDAL_CACHEMAX=256)


# --- 1. check ------------------------------------------------------------------------------
def area_bbox():
    """The default bbox widened to every burn block and contingency area on record (plus ~1.5 km)."""
    x1, y1, x2, y2 = BBOX
    r = db.one("""select ST_XMin(e) x1, ST_YMin(e) y1, ST_XMax(e) x2, ST_YMax(e) y2 from
                  (select ST_Extent(geom) e from plans.feature where kind in ('burn_unit','contingency_area')) s""")
    if r and r["x1"] is not None:
        x1, y1 = min(x1, r["x1"] - 0.02), min(y1, r["y1"] - 0.015)
        x2, y2 = max(x2, r["x2"] + 0.02), max(y2, r["y2"] + 0.015)
    return [round(v, 4) for v in (x1, y1, x2, y2)]


def find_sources(client, bbox):
    """The DTM file for each source that covers the area, with its catalogue date and HTTP headers."""
    found = []
    for spec in SOURCES:
        coll, asset, title = spec["collection"], spec.get("asset"), spec["title"]
        href, item, updated = spec.get("url"), (spec.get("url") or "").split("/gem-15/")[-1] or None, None
        try:
            if href:
                raise StopIteration   # a direct file: no catalogue lookup
            r = client.get(STAC, params={"collections": coll, "bbox": ",".join(map(str, bbox)), "limit": 50}).raise_for_status().json()
            for f in r.get("features", []):
                a = (f.get("assets") or {}).get(asset)
                if a and a.get("href", "").endswith(".tif"):
                    href, item = a["href"], f["id"]
                    updated = (f.get("properties") or {}).get("updated") or (f.get("properties") or {}).get("datetime")
                    break   # mosaic collections: one item covers the area (first is enough at this size)
        except StopIteration:
            pass
        except (httpx.HTTPError, ValueError) as e:
            print(f"STAC lookup for {coll} failed ({e})")
        if href is None and coll == "mrdem-30":
            href, item = MRDEM_FALLBACK, "mrdem-30"
        if href is None:
            print(f"{title}: nothing in the catalogue for this area")
            continue
        h = client.head(href)
        if h.status_code >= 400:
            print(f"{title}: {href} answered HTTP {h.status_code}; skipped")
            continue
        updated = updated or h.headers.get("last-modified")
        found.append({"collection": coll, "title": title, "item": item, "updated": updated, "href": href,
                      "vertical": spec["vertical"],
                      "etag": h.headers.get("etag"), "last_modified": h.headers.get("last-modified"),
                      "size": h.headers.get("content-length"), "status": h.status_code})
    return found


def fingerprint(sources, bbox):
    key = {"bbox": bbox, "res": RES, "crs": DST_CRS,
           "sources": [{k: s.get(k) for k in ("collection", "item", "updated", "href", "etag", "last_modified", "size")} for s in sources]}
    return hashlib.sha1(json.dumps(key, sort_keys=True).encode()).hexdigest()


def current_version():
    return db.one("select * from meta.raster_version where layer = %s and current", (LAYER,))


# --- 2-3. build ----------------------------------------------------------------------------
def open_at(href, res):
    """Open a remote COG at the coarsest overview that is still at least as fine as `res`."""
    src = rasterio.open(href)
    native = abs(src.transform.a)
    level = None
    for i, f in enumerate(src.overviews(1)):
        if native * f <= res * 1.001:
            level = i
    if level is not None:
        src.close()
        src = rasterio.open(href, overview_level=level)
    return src


def grid(bbox):
    x1, y1, x2, y2 = transform_bounds("EPSG:4326", DST_CRS, *bbox, densify_pts=21)
    x1, y1 = np.floor(x1 / RES) * RES, np.floor(y1 / RES) * RES
    x2, y2 = np.ceil(x2 / RES) * RES, np.ceil(y2 / RES) * RES
    w, h = int(round((x2 - x1) / RES)), int(round((y2 - y1) / RES))
    return from_origin(x1, y2, RES, RES), w, h


def datum_offsets(srcs, sources, T, W, H):
    """Shift for each non-CGVD2013 source (GEM-15 is on EGM96) so it lines up with NRCan's heights:
    the median of (NRCan - source) over cells both cover, on a coarse grid. Without this, the seam
    between sources shows up as a false step (and a false steep slope)."""
    f = max(1, int(60 / RES))
    cw, ch = max(1, W // f), max(1, H // f)
    ct = T * T.scale(W / cw, H / ch)
    coarse = []
    for src in srcs:
        a = np.full((ch, cw), np.nan, np.float32)
        reproject(source=rasterio.band(src, 1), destination=a, src_transform=src.transform, src_crs=src.crs,
                  src_nodata=src.nodata, dst_transform=ct, dst_crs=DST_CRS, dst_nodata=np.nan, resampling=Resampling.average)
        a[(a < -500) | (a > 9000)] = np.nan
        coarse.append(a)
    offsets = []
    for i, s in enumerate(sources):
        if s["vertical"] == "CGVD2013":
            offsets.append(0.0)
            continue
        diffs = [coarse[j] - coarse[i] for j, r in enumerate(sources) if r["vertical"] == "CGVD2013"]
        best = None
        for d in diffs:                 # prefer the first NRCan source (lidar) that overlaps enough
            d = d[np.isfinite(d)]
            if d.size >= 20:
                best = float(np.median(d))
                break
        offsets.append(round(best, 2) if best is not None else 0.0)
        s["datum_shift_m"] = offsets[-1] if best is not None else None
        s["vertical_after_shift"] = "CGVD2013 (shifted)" if best is not None else s["vertical"]
        print(f"  {s['title']}: {'shifted %+.2f m to match NRCan heights' % best if best is not None else 'no overlap with NRCan data; not shifted'}")
    return offsets


def build(sources, bbox, path):
    T, W, H = grid(bbox)
    tmp = path.with_suffix(".build.tif")
    profile = dict(driver="GTiff", dtype="float32", count=2, width=W, height=H, crs=DST_CRS, transform=T,
                   nodata=np.nan, tiled=True, blockxsize=512, blockysize=512, compress="deflate", predictor=3, BIGTIFF="IF_SAFER")
    counts = np.zeros(len(sources) + 1, dtype=np.int64)
    with rasterio.Env(**GDAL_ENV):
        srcs = [open_at(s["href"], RES) for s in sources]
        try:
            offsets = datum_offsets(srcs, sources, T, W, H)
            with rasterio.open(tmp, "w", **profile) as dst:
                dst.set_band_description(1, "elevation_m")
                dst.set_band_description(2, "source (" + ", ".join(f"{i + 1}={s['collection']}" for i, s in enumerate(sources)) + ")")
                for r0 in range(0, H, TILE):
                    for c0 in range(0, W, TILE):
                        win = Window(c0, r0, min(TILE, W - c0), min(TILE, H - r0))
                        wt = win_transform(win, T)
                        out = np.full((win.height, win.width), np.nan, np.float32)
                        code = np.zeros_like(out)
                        for i, src in enumerate(srcs):
                            if not np.isnan(out).any():
                                break
                            arr = np.full_like(out, np.nan)
                            finer = abs(src.transform.a) < RES
                            reproject(source=rasterio.band(src, 1), destination=arr, src_transform=src.transform,
                                      src_crs=src.crs, src_nodata=src.nodata, dst_transform=wt, dst_crs=DST_CRS,
                                      dst_nodata=np.nan, resampling=Resampling.average if finer else Resampling.bilinear)
                            if src.nodata is not None and not np.isnan(src.nodata):
                                arr[arr == src.nodata] = np.nan
                            arr[(arr < -500) | (arr > 9000)] = np.nan   # stray nodata values
                            arr += offsets[i]
                            fill = np.isnan(out) & np.isfinite(arr)
                            out[fill], code[fill] = arr[fill], i + 1
                        dst.write(out, 1, window=win)
                        dst.write(code, 2, window=win)
                        counts += np.bincount(code.astype(np.int64).ravel(), minlength=len(counts))[:len(counts)]
                    print(f"  rows {min(r0 + TILE, H)}/{H}")
        finally:
            for s in srcs:
                s.close()
        rasterio.shutil.copy(tmp, path, driver="COG", compress="DEFLATE", predictor=3, overview_resampling="average", BIGTIFF="IF_SAFER")
    tmp.unlink(missing_ok=True)
    total = W * H
    share = {f'{s["collection"]}:{s["item"]}' if s["collection"] == "gem-15" else s["collection"]: round(100 * counts[i + 1] / total, 1)
             for i, s in enumerate(sources)}
    return {"width": W, "height": H, "empty_pct": round(100 * counts[0] / total, 1), "share": share}


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def log(c, status, fp=None, sha=None, remote=None, message=None):
    c.execute("""insert into meta.source_sync (source, status, remote_modified, etag, sha256, message)
                 values (%s, %s, %s, %s, %s, %s)""", (SOURCE, status, remote, fp, sha, message))


# --- run -----------------------------------------------------------------------------------
def run(force=False, dry_run=False, client=None):
    db.open_pool()
    try:
        bbox = area_bbox()
        own = client is None
        client = client or httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "rx.rtams.ca DEM sync"})
        try:
            sources = find_sources(client, bbox)
        finally:
            if own:
                client.close()
        if not sources:
            raise RuntimeError("no elevation source found for the area")
        fp = fingerprint(sources, bbox)
        remote = next((s["updated"] for s in sources if s["updated"]), None)
        cur = current_version()
        for s in sources:
            print(f"{s['title']}: {s['item']}, updated {s['updated']}")
        if cur and cur["fingerprint"] == fp and Path(cur["path"]).exists() and not force:
            if not dry_run:
                with db.tx() as c:
                    log(c, "unchanged", fp, cur["sha256"], remote, f"current version {cur['id']} ({cur['path']})")
            print(f"unchanged: version {cur['id']} built {cur['created_at']:%Y-%m-%d} is current")
            return "unchanged"
        T, W, H = grid(bbox)
        print(f"building {W} x {H} cells at {RES:g} m over {bbox} ({W * H * 4 / 1e6:.0f} MB uncompressed)")
        if dry_run:
            print("dry run: nothing built")
            return "would update"
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        path = OUT_DIR / f"shilo_dtm_{RES:g}m_{stamp}_{fp[:8]}.tif"
        info = build(sources, bbox, path)
        if info["empty_pct"] >= 99.9:
            path.unlink(missing_ok=True)
            raise RuntimeError("the sources returned no elevations for the area")
        sha = sha256_of(path)
        for s in sources:
            s["share_pct"] = info["share"].get(f'{s["collection"]}:{s["item"]}' if s["collection"] == "gem-15" else s["collection"], 0)
        datums = sorted({s.get("vertical_after_shift", s["vertical"]).replace(" (shifted)", "") for s in sources if s["share_pct"] > 0})
        with db.tx() as c:
            c.execute("update meta.raster_version set current = false where layer = %s and current", (LAYER,))
            vid = c.execute("""insert into meta.raster_version (layer, path, sha256, res_m, crs, vertical, bounds, sources, fingerprint, created_by, current)
                               values (%s,%s,%s,%s,%s,%s, ST_MakeEnvelope(%s,%s,%s,%s,4326), %s, %s, %s, true) returning id""",
                            (LAYER, str(path), sha, RES, DST_CRS, " + ".join(datums) or "CGVD2013", *bbox, db.jsonb(sources), fp, WHO)).fetchone()["id"]
            log(c, "updated", fp, sha, remote, f"version {vid}: {info['width']}x{info['height']} cells; "
                + ", ".join(f"{k} {v}%" for k, v in info["share"].items()) + f"; no data {info['empty_pct']}%")
            # keep the current file and the one before it
            old = c.execute("""select id, path from meta.raster_version where layer = %s and not current
                               order by created_at desc offset 1""", (LAYER,)).fetchall()
        for o in old:
            Path(o["path"]).unlink(missing_ok=True)
            import shutil
            shutil.rmtree(OUT_DIR / "tiles" / f"v{o['id']}", ignore_errors=True)
        print(f"updated: version {vid}, {path.name}, " + ", ".join(f"{k} {v}%" for k, v in info["share"].items())
              + f", no data {info['empty_pct']}%")
        return "updated"
    except Exception as e:
        if not dry_run:
            try:
                with db.tx() as c:
                    log(c, "failed", message=f"{type(e).__name__}: {e}"[:2000])
            except Exception:
                pass
        print(f"failed: {e}", file=sys.stderr)
        raise
    finally:
        db.pool.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="rebuild even if nothing looks new")
    ap.add_argument("--dry-run", action="store_true", help="report what would be built; write nothing")
    a = ap.parse_args(argv)
    run(a.force, a.dry_run)


if __name__ == "__main__":
    main()
