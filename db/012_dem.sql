-- rx: elevation model for the Shilo area, built from NRCan's CanElevation series and kept as versions.
-- Each version is a Cloud Optimized GeoTIFF on disk; this table records where it is, what it was built
-- from, and which one is current. Terrain figures for plans are worked out from the current version.
create table if not exists meta.raster_version (
  id          serial primary key,
  layer       text not null,                   -- 'terrain.dem'
  path        text not null,                   -- file on the server
  sha256      text not null,
  res_m       numeric not null,
  crs         text not null,                   -- e.g. EPSG:2957 (NAD83(CSRS) / UTM 14N)
  vertical    text,                            -- e.g. CGVD2013
  bounds      geometry(Polygon, 4326) not null,
  sources     jsonb not null,                  -- [{collection, item, updated, href, share_pct}]
  fingerprint text not null,                   -- what the sources looked like when built (for update checks)
  created_at  timestamptz not null default now(),
  created_by  text,
  current     boolean not null default false
);
create unique index if not exists raster_version_one_current on meta.raster_version (layer) where current;

-- The terrain figures a plan used are kept with the element content when the planner fills the fields,
-- so an approved plan does not change when a new DEM version arrives.
