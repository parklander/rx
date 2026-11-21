-- rx: critical habitat kept in step with ECCC's national dataset.
-- ECCC publishes critical habitat as areas and as points, final and proposed. The layer now takes any
-- geometry, and features loaded by the sync carry the dataset's own attributes and a stable key.

alter table habitat.critical_habitat
  alter column geom type geometry(Geometry, 4326),
  add column if not exists population   text,
  add column if not exists site_id      text,
  add column if not exists site_name    text,
  add column if not exists cosewic_id   int,
  add column if not exists sara_status  int,     -- ECCC code; see the dataset's data dictionary
  add column if not exists sensitivity  text,    -- ECCC Sensitive_E
  add column if not exists source       text,    -- 'eccc_national' when loaded by the sync; null = loaded by hand
  add column if not exists source_key   text;    -- identity within the source, across ECCC releases

create index if not exists critical_habitat_source_key on habitat.critical_habitat (source, source_key);

update meta.layer set geom_type = 'any',
  description = 'ECCC critical habitat (SARA), final and proposed, areas and points. Synced from the national dataset.'
  where name = 'habitat.critical_habitat';

-- One row per check of an outside source, whether or not anything changed.
create table if not exists meta.source_sync (
  id             serial primary key,
  source         text not null,                 -- e.g. 'eccc_critical_habitat'
  checked_at     timestamptz not null default now(),
  status         text not null check (status in ('unchanged','updated','no_change_in_aoi','failed')),
  remote_modified text,                          -- dataset date from open.canada.ca
  etag           text,
  last_modified  text,                           -- HTTP Last-Modified of the download
  content_length bigint,
  sha256         text,
  release_id     int references meta.release,
  added          int not null default 0,
  changed        int not null default 0,
  retired        int not null default 0,
  kept_in_aoi    int,
  message        text
);
create index if not exists source_sync_source on meta.source_sync (source, checked_at desc);
