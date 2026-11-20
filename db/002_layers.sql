-- rx: landscape layers. State layers are versioned; event layers are append-only.

-- Fuels --------------------------------------------------------------------
create table fuels.fuel_class (
  fuel_class  text not null,                -- mixed_grass | grass_juniper | juniper | aspen | shrub | other
  load_kg_m2  numeric,
  juniper_pct numeric,
  fbp_equiv   text,                          -- nearest FBP fuel type, for reference only
  source      text,                          -- e.g. '2026 classification, Sentinel-2 + drone'
  geom        geometry(MultiPolygon, 4326) not null
);
select meta.make_versioned('fuels.fuel_class');

create table fuels.treatment (               -- burns, mowing, discing, wildfire: what changed the fuels
  event_id    uuid primary key default gen_random_uuid(),
  kind        text not null check (kind in ('prescribed_burn','wildfire','mow','disc','graze','other')),
  occurred_on date not null,
  ended_on    date,
  plan_id     int,                           -- set when it came from an rx plan
  completeness_pct numeric,
  note        text,
  recorded_at timestamptz not null default now(),
  recorded_by text,
  geom        geometry(MultiPolygon, 4326) not null
);
create index on fuels.treatment using gist (geom);
create trigger guard before update or delete on fuels.treatment for each row execute function meta.guard_append_only();

create table fuels.plot (
  id          uuid primary key default gen_random_uuid(),
  plot_code   text not null,
  sampled_on  date not null,
  fuel_class  text,
  load_kg_m2  numeric,
  curing_pct  numeric,
  height_cm   numeric,
  note        text,
  recorded_at timestamptz not null default now(),
  recorded_by text,
  geom        geometry(Point, 4326) not null
);
create index on fuels.plot using gist (geom);
create trigger guard before update or delete on fuels.plot for each row execute function meta.guard_append_only();

create table fuels.test_fire (
  id          uuid primary key default gen_random_uuid(),
  plan_id     int,
  burn_day_id int,
  occurred_at timestamptz not null,
  fuel_class  text,
  temp_c numeric, rh_pct numeric, wind_kmh numeric, wind_dir_deg numeric,
  result      text not null check (result in ('go','no_go','marginal')),
  spread_note text,
  recorded_at timestamptz not null default now(),
  recorded_by text,
  geom        geometry(Point, 4326) not null
);
create index on fuels.test_fire using gist (geom);
create trigger guard before update or delete on fuels.test_fire for each row execute function meta.guard_append_only();

-- Operations ---------------------------------------------------------------
create table ops.fireguard (
  name            text,
  guard_type      text not null,             -- disced | mowed | graded | road | wet_line | black_line
  width_m         numeric,
  condition       text,                      -- good | fair | poor
  last_maintained date,
  dac_cleared     boolean,
  geom            geometry(MultiLineString, 4326) not null
);
select meta.make_versioned('ops.fireguard');

create table ops.road (
  name          text,
  road_class    text,                        -- highway | range_road | trail
  engine_access boolean,
  tender_access boolean,
  load_limit_t  numeric,
  geom          geometry(MultiLineString, 4326) not null
);
select meta.make_versioned('ops.road');

create table ops.water_source (
  name          text,
  kind          text,                        -- dugout | hydrant | fill_point | draft_site
  capacity_m3   numeric,
  tender_access boolean,
  seasonal_note text,
  geom          geometry(Point, 4326) not null
);
select meta.make_versioned('ops.water_source');

create table ops.restricted_area (
  name  text,
  kind  text not null,                       -- impact_area | no_ground_access | dudded | other
  note  text,
  geom  geometry(MultiPolygon, 4326) not null
);
select meta.make_versioned('ops.restricted_area');

create table ops.bivouac (
  name           text,
  designated     boolean not null default false,
  treatment_note text,
  geom           geometry(MultiPolygon, 4326) not null
);
select meta.make_versioned('ops.bivouac');

-- Infrastructure -----------------------------------------------------------
create table infra.asset (
  name          text,
  asset_type    text not null,               -- power_line | latrine | structure | target | bunker | tower | other
  material      text,                        -- plastic | wood | steel | concrete
  vulnerability text check (vulnerability in ('high','moderate','low')),
  owner         text,
  geom          geometry(Geometry, 4326) not null
);
select meta.make_versioned('infra.asset');

-- Habitat ------------------------------------------------------------------
create table habitat.critical_habitat (
  species    text not null,
  sci_name   text,
  status     text not null default 'final',  -- final | proposed
  grid_id    text,
  tenure     text,
  source_doc text,
  geom       geometry(MultiPolygon, 4326) not null
);
select meta.make_versioned('habitat.critical_habitat');

create table habitat.sensitive_feature (
  kind       text not null,                  -- rare_plant | nest_area | cultural | monitoring_plot | snag_bluff | other
  name       text,
  restricted boolean not null default false, -- exact location restricted: generalized for print
  fire_effect text,                          -- benefits | harmed | mixed | unknown
  measure    text,
  geom       geometry(Geometry, 4326) not null
);
select meta.make_versioned('habitat.sensitive_feature');

create table habitat.observation (
  id          uuid primary key default gen_random_uuid(),
  species     text not null,
  observed_on date not null,
  kind        text,                          -- nest | sighting | survey_point
  count       int,
  restricted  boolean not null default true,
  note        text,
  recorded_at timestamptz not null default now(),
  recorded_by text,
  geom        geometry(Point, 4326) not null
);
create index on habitat.observation using gist (geom);
create trigger guard before update or delete on habitat.observation for each row execute function meta.guard_append_only();

-- Smoke --------------------------------------------------------------------
create table smoke.receptor (
  name        text not null,
  kind        text,                          -- community | housing | hospital | school | highway | airport | farmstead
  sensitivity text check (sensitivity in ('high','moderate','low')),
  note        text,
  geom        geometry(Point, 4326) not null
);
select meta.make_versioned('smoke.receptor');

-- Weather snapshots (frozen at decision points) ------------------------------
create table weather.forecast_snapshot (
  id           serial primary key,
  source       text not null,                -- RDPS | HRDPS | NAEFS | spot | station
  model_run    timestamptz,
  issued_at    timestamptz not null,
  retrieved_at timestamptz not null default now(),
  stage        text,                         -- outlook | day_before | burn_morning | observed
  hourly       jsonb not null,               -- [{time, temp_c, rh_pct, wind_kmh, wind_dir_deg, ffmc, isi, fwi, ...}]
  note         text,
  geom         geometry(Point, 4326)
);

-- Catalogue ---------------------------------------------------------------
insert into meta.layer (name, title, kind, geom_type, description, sensitive, style) values
 ('fuels.fuel_class',        'Fuel classes',            'state', 'polygon', 'Local fuel classification (juniper split out)', false, '{"color":"#7a8b3a","fill":true}'),
 ('fuels.treatment',         'Fuel treatments',         'event', 'polygon', 'Burns, wildfires, mowing, discing', false, '{"color":"#5a5a5a","dash":"4 4"}'),
 ('fuels.plot',              'Fuel plots',              'event', 'point',   'Fuel load and curing samples', false, '{"color":"#222222"}'),
 ('fuels.test_fire',         'Test fires',              'event', 'point',   'Go / no-go test fire records', false, '{"color":"#c62828"}'),
 ('ops.fireguard',           'Fireguards',              'state', 'line',    'Disced, mowed and graded guards', false, '{"color":"#8b5a2b","weight":5}'),
 ('ops.road',                'Roads and trails',        'state', 'line',    'Access, engine and tender capability', false, '{"color":"#6e6e6e","weight":3}'),
 ('ops.water_source',        'Water sources',           'state', 'point',   'Dugouts, hydrants, fill points', false, '{"color":"#1f6fb2"}'),
 ('ops.restricted_area',     'Restricted areas',        'state', 'polygon', 'Impact areas, no ground access', false, '{"color":"#8a2a2a","fill":true}'),
 ('ops.bivouac',             'Bivouac areas',           'state', 'polygon', 'Designated and pre-treated bivouacs', false, '{"color":"#4a4a8a"}'),
 ('infra.asset',             'Infrastructure',          'state', 'any',     'Assets by vulnerability class', false, '{"color":"#d84315"}'),
 ('habitat.critical_habitat','Critical habitat (SARA)', 'state', 'polygon', 'ECCC critical habitat', false, '{"color":"#6a3d9a","fill":true}'),
 ('habitat.sensitive_feature','Sensitive features',     'state', 'any',     'Rare plants, nests, cultural, plots', true, '{"color":"#6a3d9a"}'),
 ('habitat.observation',     'Species observations',    'event', 'point',   'Species at risk observations', true, '{"color":"#6a3d9a"}'),
 ('smoke.receptor',          'Smoke receptors',         'state', 'point',   'Smoke-sensitive receptors', false, '{"color":"#b26a00"}');
