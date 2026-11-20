-- rx: field site visits (pre-burn recce, monitoring, post-burn), their records and photos.
create schema if not exists field;

create table field.visit (
  id          uuid primary key,                 -- made on the device so it can be created offline
  plan_id     int references plans.plan on delete set null,
  kind        text not null check (kind in ('pre_burn_recce','burn_day','post_burn','monitoring','fuel_survey','other')),
  title       text,
  started_at  timestamptz not null,
  ended_at    timestamptz,
  crew        text,
  weather     text,
  notes       text,
  created_by  text,
  synced_at   timestamptz not null default now()
);
create index on field.visit (plan_id);

-- One thing seen or measured at a place: a note, a photo point, a fuel plot, a recce check, a hazard.
create table field.record (
  id          uuid primary key,                 -- made on the device; resending is harmless
  visit_id    uuid not null references field.visit on delete cascade,
  kind        text not null check (kind in ('note','photo','fuel_plot','check','hazard','water','access')),
  item        text,                             -- recce checklist key, hazard type, etc.
  status      text,                             -- ok | issue | n/a
  text        text,
  data        jsonb not null default '{}',      -- fuel plot measurements and the like
  accuracy_m  numeric,
  heading_deg numeric,
  observed_at timestamptz not null,
  created_by  text,
  synced_at   timestamptz not null default now(),
  geom        geometry(Point, 4326)
);
create index on field.record (visit_id);
create index on field.record using gist (geom);

create table field.media (
  id           uuid primary key,
  record_id    uuid not null references field.record on delete cascade,
  filename     text not null,                   -- under RX_MEDIA_DIR
  content_type text not null,
  bytes        int,
  width        int,
  height       int,
  taken_at     timestamptz,
  created_by   text,
  synced_at    timestamptz not null default now()
);
create index on field.media (record_id);

-- Fuel plots captured in the field also land in the landscape database.
alter table fuels.plot add column if not exists source_record uuid;
