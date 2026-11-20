-- rx: core schemas, users, releases and the versioning machinery.
-- All geometry is stored in EPSG:4326. Areas and lengths use geography casts.

create extension if not exists postgis;
create extension if not exists pgcrypto;

create schema if not exists meta;
create schema if not exists plans;
create schema if not exists fuels;
create schema if not exists habitat;
create schema if not exists infra;
create schema if not exists ops;
create schema if not exists smoke;
create schema if not exists weather;

-- Users and sessions -------------------------------------------------------
create table meta.app_user (
  id           serial primary key,
  username     text not null unique,
  display_name text not null,
  role         text not null check (role in ('viewer','planner','burn_boss','admin')),
  pw_hash      text not null,
  active       boolean not null default true,
  created_at   timestamptz not null default now()
);

create table meta.session (
  token      text primary key,
  user_id    int not null references meta.app_user on delete cascade,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);

-- Layer catalogue ----------------------------------------------------------
-- kind 'state': versioned (never overwritten). kind 'event': append-only records.
create table meta.layer (
  name        text primary key,          -- schema.table
  title       text not null,
  kind        text not null check (kind in ('state','event')),
  geom_type   text not null,
  description text,
  sensitive   boolean not null default false,  -- exact locations restricted (species, cultural)
  style       jsonb not null default '{}'
);

-- Releases: named, reviewed versions of a state layer.
create table meta.release (
  id           serial primary key,
  layer        text not null references meta.layer(name),
  name         text not null,
  notes        text,
  created_at   timestamptz not null default now(),
  created_by   text,
  published_at timestamptz            -- null = draft
);

-- Versioning ---------------------------------------------------------------
-- Every state table carries these columns:
--   row_id       one row per version
--   feature_id   stable identity across versions
--   valid        when the row is true on the ground (world time)
--   recorded     when the database held the row as current knowledge (system time)
--   release_id, change_note, changed_by, source_event
-- Rows are never updated or deleted by hand. meta.vwrite / meta.vretire close and open rows.

create or replace function meta.guard_versioned() returns trigger language plpgsql as $$
begin
  if current_setting('rx.versioning', true) is distinct from 'on' then
    raise exception 'rows in % are versioned: use meta.vwrite / meta.vretire', tg_table_schema||'.'||tg_table_name;
  end if;
  if tg_op = 'DELETE' then return old; end if;
  return new;
end $$;

create or replace function meta.guard_append_only() returns trigger language plpgsql as $$
begin
  if current_setting('rx.versioning', true) is distinct from 'on' then
    raise exception 'rows in % are append-only records', tg_table_schema||'.'||tg_table_name;
  end if;
  if tg_op = 'DELETE' then return old; end if;
  return new;
end $$;

-- Add the version columns, indexes and guard to a state table.
create or replace function meta.make_versioned(tbl regclass) returns void language plpgsql as $$
begin
  execute format($f$
    alter table %1$s
      add column if not exists row_id       bigserial primary key,
      add column if not exists feature_id   uuid not null default gen_random_uuid(),
      add column if not exists valid        tstzrange not null default tstzrange(now(), null),
      add column if not exists recorded     tstzrange not null default tstzrange(now(), null),
      add column if not exists release_id   int references meta.release,
      add column if not exists change_note  text,
      add column if not exists changed_by   text,
      add column if not exists source_event uuid;
    create index on %1$s using gist (geom);
    create index on %1$s using gist (valid);
    create index on %1$s using gist (recorded);
    create index on %1$s (feature_id);
    create trigger guard before update or delete on %1$s
      for each row execute function meta.guard_versioned();
  $f$, tbl);
end $$;

-- Column list of a table minus the version bookkeeping columns.
create or replace function meta.attr_cols(tbl regclass) returns text[] language sql stable as $$
  select array_agg(attname::text order by attnum)
  from pg_attribute
  where attrelid = tbl and attnum > 0 and not attisdropped
    and attname not in ('row_id','feature_id','valid','recorded','release_id','change_note','changed_by','source_event');
$$;

-- Write a new version of a feature (or a new feature when fid is null).
--   data:       attributes as JSON; geometry as GeoJSON under "geom"
--   valid_from: when the change happened on the ground (default now)
-- Bitemporal: the current row's knowledge is closed, the part of its life before valid_from
-- is re-recorded, and the new state starts at valid_from.
create or replace function meta.vwrite(
  tbl regclass, fid uuid, data jsonb,
  valid_from timestamptz default now(), note text default null,
  who text default null, release int default null, src uuid default null
) returns uuid language plpgsql as $$
declare
  cols   text[] := meta.attr_cols(tbl);
  cur    jsonb;
  cur_valid tstzrange;
  merged jsonb;
  geomtxt text;
  newfid uuid := coalesce(fid, gen_random_uuid());
  collist text;
  sellist text;
begin
  perform set_config('rx.versioning', 'on', true);
  collist := array_to_string(array(select quote_ident(c) from unnest(cols) c), ',');
  sellist := array_to_string(array(select 'r.'||quote_ident(c) from unnest(cols) c), ',');

  if fid is not null then
    execute format('select to_jsonb(t) - %L - %L - %L - %L - %L - %L - %L - %L, t.valid from %s t
                    where feature_id = $1 and upper_inf(recorded) and valid @> $2 for update',
                   'row_id','feature_id','valid','recorded','release_id','change_note','changed_by','source_event', tbl)
      into cur, cur_valid using fid, valid_from;
    if cur is null then
      raise exception 'feature % has no current version valid at %', fid, valid_from;
    end if;
    -- close current knowledge of the old row
    execute format('update %s set recorded = tstzrange(lower(recorded), now())
                    where feature_id = $1 and upper_inf(recorded) and valid @> $2', tbl)
      using fid, valid_from;
    -- re-record its life before the change, if any
    if lower(cur_valid) < valid_from then
      execute format('insert into %1$s (%2$s, feature_id, valid, recorded, release_id, change_note, changed_by, source_event)
                      select %3$s, $1, tstzrange($2, $3), tstzrange(now(), null), $4, $5, $6, $7
                      from jsonb_populate_record(null::%1$s, $8) r', tbl, collist, sellist)
        using fid, lower(cur_valid), valid_from, release, 'split at change', who, src, cur;
    end if;
    merged := cur || (data - 'geom');
  else
    merged := data - 'geom';
  end if;

  if data ? 'geom' and jsonb_typeof(data->'geom') = 'object' then
    geomtxt := ST_AsEWKT(ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(data->>'geom'), 4326)));
    -- keep points as points
    if GeometryType(ST_GeomFromGeoJSON(data->>'geom')) = 'POINT' then
      geomtxt := ST_AsEWKT(ST_SetSRID(ST_GeomFromGeoJSON(data->>'geom'), 4326));
    end if;
    merged := merged || jsonb_build_object('geom', geomtxt);
  end if;

  execute format('insert into %1$s (%2$s, feature_id, valid, recorded, release_id, change_note, changed_by, source_event)
                  select %3$s, $1, tstzrange($2, null), tstzrange(now(), null), $3, $4, $5, $6
                  from jsonb_populate_record(null::%1$s, $7) r', tbl, collist, sellist)
    using newfid, valid_from, release, note, who, src, merged;
  perform set_config('rx.versioning', 'off', true);
  return newfid;
end $$;

-- Retire a feature: it stops existing on the ground at valid_to.
create or replace function meta.vretire(
  tbl regclass, fid uuid, valid_to timestamptz default now(),
  note text default null, who text default null, release int default null
) returns void language plpgsql as $$
declare
  cols text[] := meta.attr_cols(tbl);
  collist text; sellist text;
  cur jsonb; cur_valid tstzrange;
begin
  perform set_config('rx.versioning', 'on', true);
  collist := array_to_string(array(select quote_ident(c) from unnest(cols) c), ',');
  sellist := array_to_string(array(select 'r.'||quote_ident(c) from unnest(cols) c), ',');
  execute format('select to_jsonb(t), t.valid from %s t where feature_id = $1 and upper_inf(recorded) and upper_inf(valid) for update', tbl)
    into cur, cur_valid using fid;
  if cur is null then raise exception 'feature % is not current', fid; end if;
  execute format('update %s set recorded = tstzrange(lower(recorded), now())
                  where feature_id = $1 and upper_inf(recorded) and upper_inf(valid)', tbl) using fid;
  execute format('insert into %1$s (%2$s, feature_id, valid, recorded, release_id, change_note, changed_by)
                  select %3$s, $1, tstzrange($2, $3), tstzrange(now(), null), $4, $5, $6
                  from jsonb_populate_record(null::%1$s, $7) r', tbl, collist, sellist)
    using fid, lower(cur_valid), valid_to, release, coalesce(note, 'retired'), who, cur;
  perform set_config('rx.versioning', 'off', true);
end $$;
