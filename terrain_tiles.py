"""Map tiles drawn from the current DEM version: shaded relief, elevation tint and slope classes.

Tiles are Web Mercator XYZ, 256 px, rendered on first request and cached on disk per DEM version
(RX_SOURCE_DIR/nrcan_dem/tiles/v<id>/<style>/z/x/y.png). The version is part of the URL, so browsers
and the phone's offline cache can keep them for good and a new DEM version gets new tiles.
"""
import io
import math
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import reproject, transform_bounds

import db

STYLES = {
    "hillshade": {"title": "Shaded relief", "opacity": 0.55},
    "elevation": {"title": "Elevation (tinted relief)", "opacity": 0.7},
    "slope": {"title": "Slope classes", "opacity": 0.75},
}
# Slope classes (%): upper bound, RGBA. Under 2% is left clear.
SLOPE_CLASSES = [(2, (0, 0, 0, 0)), (5, (255, 241, 168, 150)), (10, (254, 204, 92, 180)),
                 (20, (253, 141, 60, 200)), (35, (227, 26, 28, 215)), (1e9, (128, 0, 38, 230))]
SLOPE_LEGEND = "clear under 2% · 2–5 · 5–10 · 10–20 · 20–35 · over 35%"
EXAG = float(os.environ.get("RX_HILLSHADE_EXAG", "3"))   # vertical exaggeration for the shading (prairie relief is low)
MIN_Z, NATIVE_Z = 9, 15        # 5 m cells are about 3 m tile pixels at z15 at Shilo's latitude
TILE_DIR = Path(os.environ.get("RX_SOURCE_DIR", "/var/lib/rx/sources")) / "nrcan_dem" / "tiles"
R = 6378137.0
EMPTY = None


def current():
    return db.one("select id, path, created_at, bounds is not null as ok, ST_XMin(bounds) x1, ST_YMin(bounds) y1, ST_XMax(bounds) x2, ST_YMax(bounds) y2 "
                  "from meta.raster_version where layer = 'terrain.dem' and current")


def layers():
    """Entries for /api/layers: one per style, pointing at the current version's tiles."""
    v = current()
    if not v:
        return []
    note = f"DEM v{v['id']}, built {v['created_at']:%Y-%m-%d}"
    return [{"name": f"terrain.{k}", "title": s["title"], "kind": "raster", "geom_type": "raster", "visible": True,
             "sensitive": False, "style": {"opacity": s["opacity"]}, "releases": [],
             "tiles": f"/tiles/terrain/{v['id']}/{k}/{{z}}/{{x}}/{{y}}.png", "min_zoom": MIN_Z, "native_zoom": NATIVE_Z,
             "bounds": [[v["y1"], v["x1"]], [v["y2"], v["x2"]]],
             "note": note + (f" · {SLOPE_LEGEND}" if k == "slope" else "")} for k, s in STYLES.items()]


def tile_bounds(z, x, y):
    n = 2 ** z
    size = 2 * math.pi * R / n
    x1 = -math.pi * R + x * size
    y2 = math.pi * R - y * size
    return x1, y2 - size, x1 + size, y2


def _png(rgba):
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _empty():
    global EMPTY
    if EMPTY is None:
        EMPTY = _png(np.zeros((256, 256, 4), np.uint8))
    return EMPTY


@lru_cache(maxsize=8)
def elev_range(path):
    """2nd and 98th percentile of elevation, for the tint (from the coarsest overview)."""
    with rasterio.open(path) as src:
        ov = src.overviews(1)
        f = ov[-1] if ov else 1
        a = src.read(1, out_shape=(max(1, src.height // f), max(1, src.width // f)), resampling=Resampling.nearest).astype("float64")
    a = a[np.isfinite(a)]
    return (float(np.percentile(a, 2)), float(np.percentile(a, 98))) if a.size else (0.0, 1.0)


def _read(path, b, pad):
    """Elevations for the tile (plus `pad` px each side) in Web Mercator, from the right overview."""
    x1, y1, x2, y2 = b
    px = (x2 - x1) / 256
    shape = (256 + 2 * pad, 256 + 2 * pad)
    dst_t = from_bounds(x1 - pad * px, y1 - pad * px, x2 + pad * px, y2 + pad * px, shape[1], shape[0])
    out = np.full(shape, np.nan, np.float32)
    with rasterio.open(path) as src0:
        lat = math.degrees(math.atan(math.sinh(((y1 + y2) / 2) / R)))
        ground = px * math.cos(math.radians(lat))
        native = abs(src0.transform.a)
        level = None
        for i, f in enumerate(src0.overviews(1)):
            if native * f <= ground * 1.001:
                level = i
    with rasterio.open(path, overview_level=level) if level is not None else rasterio.open(path) as src:
        reproject(source=rasterio.band(src, 1), destination=out, src_transform=src.transform, src_crs=src.crs,
                  src_nodata=np.nan, dst_transform=dst_t, dst_crs="EPSG:3857", dst_nodata=np.nan, resampling=Resampling.bilinear)
    return out, ground


def _hillshade(z, ground, azimuth=315.0, altitude=45.0):
    dzdy, dzdx = np.gradient(z, ground)      # rows go south: dzdy here is per metre southward
    slope = np.arctan(np.hypot(dzdx, dzdy))
    aspect = np.arctan2(-dzdx, dzdy)          # downhill direction, radians clockwise from north
    az, alt = math.radians(azimuth), math.radians(altitude)
    hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    return np.clip(hs, 0, 1), slope


def render(style, z, x, y):
    v = current()
    if not v or style not in STYLES or z < MIN_Z:
        return _empty()
    b = tile_bounds(z, x, y)
    vb = transform_bounds("EPSG:4326", "EPSG:3857", v["x1"], v["y1"], v["x2"], v["y2"])
    if b[2] < vb[0] or b[0] > vb[2] or b[3] < vb[1] or b[1] > vb[3]:
        return _empty()
    cache = TILE_DIR / f"v{v['id']}" / style / str(z) / str(x) / f"{y}.png"
    if cache.exists():
        return cache.read_bytes()
    zz, ground = _read(v["path"], b, 1)
    f = np.isfinite(zz)
    # a cell is drawn only if it and its four neighbours have heights (no false edge along the DEM boundary)
    valid = f[1:-1, 1:-1] & f[:-2, 1:-1] & f[2:, 1:-1] & f[1:-1, :-2] & f[1:-1, 2:]
    filled = np.where(f, zz, np.nanmean(zz) if f.any() else 0)
    hs, _ = _hillshade(filled * EXAG, ground)
    _, slope = _hillshade(filled, ground)
    hs, slope = hs[1:-1, 1:-1], slope[1:-1, 1:-1]
    rgba = np.zeros((256, 256, 4), np.uint8)
    if style == "hillshade":
        g = (hs * 255).astype(np.uint8)
        rgba[..., 0] = rgba[..., 1] = rgba[..., 2] = g
        rgba[..., 3] = 255
    elif style == "elevation":
        lo, hi = elev_range(v["path"])
        t = np.nan_to_num(np.clip((zz[1:-1, 1:-1] - lo) / max(hi - lo, 1e-6), 0, 1))
        stops = np.array([[38, 115, 0], [133, 176, 64], [222, 214, 125], [196, 150, 82], [140, 92, 60], [245, 240, 235]], float)
        pos = t * (len(stops) - 1)
        i = np.clip(pos.astype(int), 0, len(stops) - 2)
        f = (pos - i)[..., None]
        col = stops[i] * (1 - f) + stops[i + 1] * f
        shade = (0.45 + 0.55 * hs)[..., None]
        rgba[..., :3] = np.clip(col * shade, 0, 255).astype(np.uint8)
        rgba[..., 3] = 255
    else:   # slope classes
        pct = 100 * np.tan(slope)
        lo = 0
        for hi, colr in SLOPE_CLASSES:
            m = (pct >= lo) & (pct < hi)
            rgba[m] = colr
            lo = hi
    rgba[~valid] = 0
    data = _png(rgba)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(cache)
    return data
