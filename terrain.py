"""Terrain figures for a polygon, from the current DEM version (see dem_sync.py).

Elevation low / high / mean, relief, slope (mean, median, 90th percentile, max, in %), and the share of
the area facing each of eight aspects or flat. Cells count when their centre is inside the polygon
(all cells touched for very small polygons). Slope is worked out with central differences on the
window around the polygon, so edge cells use their real neighbours outside it.
"""
import json
import os

import numpy as np
import rasterio
import rasterio.features
import rasterio.windows
import shapely
from pyproj import Transformer
from shapely.geometry import mapping, shape

import db

LAYER = "terrain.dem"
FLAT_PCT = float(os.environ.get("RX_FLAT_SLOPE_PCT", "2"))     # below this slope a cell counts as flat
ASPECTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def current():
    return db.one("select id, path, res_m, crs, vertical, sources, created_at from meta.raster_version where layer = %s and current", (LAYER,))


def _r(v, n=1):
    return None if v is None or not np.isfinite(v) else round(float(v), n)


def stats(geom, ver=None):
    """geom: GeoJSON geometry (EPSG:4326). Returns a dict of figures, or None if the polygon is off the DEM."""
    ver = ver or current()
    if not ver:
        return None
    g = shape(geom if isinstance(geom, dict) else json.loads(geom))
    with rasterio.open(ver["path"]) as src:
        to = Transformer.from_crs(4326, src.crs, always_xy=True).transform
        gp = shapely.transform(g, lambda xy: np.column_stack(to(xy[:, 0], xy[:, 1])))
        try:
            win = rasterio.features.geometry_window(src, [mapping(gp)], pad_x=2, pad_y=2)
        except rasterio.errors.WindowError:
            return None
        win = win.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
        z = src.read(1, window=win, masked=False).astype("float64")
        code = src.read(2, window=win) if src.count >= 2 else None
        wt = src.window_transform(win)
        res = abs(src.transform.a)
        names = None
        if code is not None:
            desc = src.descriptions[1] or ""
            names = dict(x.split("=") for x in desc[desc.find("(") + 1:desc.rfind(")")].split(", ") if "=" in x)
    inside = rasterio.features.geometry_mask([mapping(gp)], z.shape, wt, invert=True)
    if inside.sum() < 4:
        inside = rasterio.features.geometry_mask([mapping(gp)], z.shape, wt, invert=True, all_touched=True)
    zv = z[inside & np.isfinite(z)]
    if zv.size == 0:
        return None
    dz_row, dz_col = np.gradient(z, res)
    dzdx, dzdy = dz_col, -dz_row                     # east, north
    slope = 100 * np.hypot(dzdx, dzdy)
    aspect = (np.degrees(np.arctan2(-dzdx, -dzdy)) + 360) % 360   # direction the slope faces (downhill)
    ok = inside & np.isfinite(slope)
    sv, av = slope[ok], aspect[ok]
    flat = sv < FLAT_PCT
    sector = ((av[~flat] + 22.5) // 45).astype(int) % 8
    n = max(sv.size, 1)
    aspects = {"flat": round(100 * flat.sum() / n, 1), **{a: round(100 * (sector == i).sum() / n, 1) for i, a in enumerate(ASPECTS)}}
    src_share = {}
    if code is not None and names:
        cv = code[inside & np.isfinite(z)].astype(int)
        for k, v in names.items():
            pct = round(100 * (cv == int(k)).sum() / max(cv.size, 1), 1)
            if pct:
                src_share[v] = pct
    return {
        "elev_min": _r(zv.min()), "elev_max": _r(zv.max()), "elev_mean": _r(zv.mean()), "relief": _r(zv.max() - zv.min()),
        "slope_mean": _r(sv.mean()) if sv.size else None, "slope_median": _r(np.median(sv)) if sv.size else None,
        "slope_p90": _r(np.percentile(sv, 90)) if sv.size else None, "slope_max": _r(sv.max()) if sv.size else None,
        "aspects": aspects, "flat_below_pct": FLAT_PCT,
        "cells": int(zv.size), "res_m": float(res), "sources": src_share,
    }


def dem_info(ver):
    if not ver:
        return None
    return {"id": ver["id"], "built": ver["created_at"].isoformat()[:10], "res_m": float(ver["res_m"]), "vertical": ver["vertical"],
            "sources": [{"title": s.get("title"), "updated": s.get("updated"), "share_pct": s.get("share_pct"),
                         "datum_shift_m": s.get("datum_shift_m")} for s in ver["sources"]]}
