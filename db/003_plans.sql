-- rx: prescribed fire plans (NWCG PMS 484-1, Dec 2021 template).

create table plans.element_def (
  code        text primary key,               -- '1', '2A', '2B', '3' ... '21', and appendices 'A'..'F'
  ord         int not null unique,
  title       text not null,
  owner_role  text not null,                  -- planner | burn_boss | agency_admin
  guidance    text,
  sections    jsonb not null                  -- [{key, label, hint}]
);

create table plans.plan (
  id             serial primary key,
  name           text not null,                -- prescribed fire name
  unit_name      text,                         -- ignition unit(s)
  admin_unit     text default 'CFB Shilo',
  status         text not null default 'draft'
                 check (status in ('draft','review','approved','implemented','closed','cancelled')),
  complexity     text check (complexity in ('low','moderate','high')),
  min_burn_boss  text,                         -- RXB1 | RXB2 | RXB3
  planned_window text,
  version_no     int not null default 1,
  parent_plan_id int references plans.plan,    -- previous version when amended
  amendment_note text,
  as_of          timestamptz,                  -- knowledge time frozen at approval
  release_ids    int[],                        -- layer releases in force at approval
  demo           boolean not null default false,
  created_at     timestamptz not null default now(),
  created_by     text,
  updated_at     timestamptz not null default now(),
  approved_at    timestamptz,
  approved_by    text
);

create table plans.element (
  plan_id    int not null references plans.plan on delete cascade,
  code       text not null references plans.element_def,
  content    jsonb not null default '{}',      -- {section_key: text}
  status     text not null default 'empty' check (status in ('empty','draft','complete')),
  updated_at timestamptz not null default now(),
  updated_by text,
  primary key (plan_id, code)
);

-- Every save of an element is kept.
create table plans.element_rev (
  id       bigserial primary key,
  plan_id  int not null,
  code     text not null,
  content  jsonb not null,
  status   text not null,
  saved_at timestamptz not null default now(),
  saved_by text
);

create table plans.feature (
  id         uuid primary key default gen_random_uuid(),
  plan_id    int not null references plans.plan on delete cascade,
  kind       text not null check (kind in (
               'burn_unit','ignition_unit','contingency_area','holding_line','contingency_line',
               'trigger_point','safety_zone','escape_route','anchor_point','test_fire_site',
               'drop_point','firing_line','lookout','other')),
  label      text,
  variant_id int,
  props      jsonb not null default '{}',
  geom       geometry(Geometry, 4326) not null,
  updated_at timestamptz not null default now(),
  updated_by text
);
create index on plans.feature using gist (geom);
create index on plans.feature (plan_id);

create table plans.feature_rev (
  id         bigserial primary key,
  feature_id uuid not null,
  plan_id    int not null,
  op         text not null,
  row_data   jsonb not null,
  saved_at   timestamptz not null default now()
);

create table plans.ignition_variant (
  id           serial primary key,
  plan_id      int not null references plans.plan on delete cascade,
  name         text not null,
  wind_dir_min numeric not null,              -- degrees the wind comes FROM
  wind_dir_max numeric not null,
  description  text,
  firing_sequence jsonb not null default '[]' -- [{step, text}]
);

create table plans.prescription_param (
  id      serial primary key,
  plan_id int not null references plans.plan on delete cascade,
  param   text not null,                       -- temp_c rh_pct wind_kmh ffmc isi bui fwi dmc dc curing_pct mixing_height_m vent_index
  low     numeric,
  high    numeric,
  note    text,
  unique (plan_id, param)
);

create table plans.signature (
  id            serial primary key,
  plan_id       int not null references plans.plan on delete cascade,
  role          text not null,                 -- preparer | technical_reviewer | agency_administrator | burn_boss
  name          text not null,
  qualification text,
  signed_at     timestamptz not null default now(),
  signed_by     text
);

create table plans.burn_day (
  id                   serial primary key,
  plan_id              int not null references plans.plan on delete cascade,
  burn_date            date not null,
  forecast_snapshot_id int references weather.forecast_snapshot,
  variant_id           int references plans.ignition_variant,
  decision             text not null default 'pending' check (decision in ('pending','go','no_go','postponed')),
  decided_by           text,
  decided_at           timestamptz,
  test_fire_result     text,
  observed_wx          jsonb,
  checklist            jsonb not null default '{}',   -- 2B answers {item_key: {ok, note}}
  notes                text
);

-- History triggers ----------------------------------------------------------
create or replace function plans.log_element() returns trigger language plpgsql as $$
begin
  insert into plans.element_rev (plan_id, code, content, status, saved_by)
  values (new.plan_id, new.code, new.content, new.status, new.updated_by);
  return new;
end $$;
create trigger log_element after insert or update on plans.element for each row execute function plans.log_element();

create or replace function plans.log_feature() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    insert into plans.feature_rev (feature_id, plan_id, op, row_data) values (old.id, old.plan_id, 'delete', to_jsonb(old) - 'geom' || jsonb_build_object('geom', ST_AsGeoJSON(old.geom)::jsonb));
    return old;
  end if;
  insert into plans.feature_rev (feature_id, plan_id, op, row_data) values (new.id, new.plan_id, lower(tg_op), to_jsonb(new) - 'geom' || jsonb_build_object('geom', ST_AsGeoJSON(new.geom)::jsonb));
  return new;
end $$;
create trigger log_feature after insert or update or delete on plans.feature for each row execute function plans.log_feature();

-- Approved plans are locked: changes need an amendment (a new plan version).
create or replace function plans.lock_approved() returns trigger language plpgsql as $$
declare st text; pid int;
begin
  pid := coalesce(new.plan_id, old.plan_id);
  select status into st from plans.plan where id = pid;
  if st in ('approved','implemented','closed') and current_setting('rx.allow_locked', true) is distinct from 'on' then
    raise exception 'plan % is %: amend it to make changes', pid, st;
  end if;
  if tg_op = 'DELETE' then return old; end if;
  return new;
end $$;
create trigger lock before insert or update or delete on plans.element          for each row execute function plans.lock_approved();
create trigger lock before insert or update or delete on plans.feature          for each row execute function plans.lock_approved();
create trigger lock before insert or update or delete on plans.ignition_variant for each row execute function plans.lock_approved();
create trigger lock before insert or update or delete on plans.prescription_param for each row execute function plans.lock_approved();

-- Overlay: what each state layer holds inside the burn unit and the contingency area,
-- as known at `known_at` (default now) and true on the ground at `on_ground` (default now).
create or replace function plans.overlay(pid int, known_at timestamptz default null, on_ground timestamptz default null)
returns table (layer text, feature_id uuid, zone text, props jsonb, geom_json jsonb)
language plpgsql stable as $$
declare
  unit_g geometry; cont_g geometry; k timestamptz; g timestamptz; l record;
begin
  select coalesce(p.as_of, now()) into k from plans.plan p where id = pid;
  k := coalesce(known_at, k); g := coalesce(on_ground, k);
  select ST_Union(geom) into unit_g from plans.feature where plan_id = pid and kind = 'burn_unit';
  select ST_Union(geom) into cont_g from plans.feature where plan_id = pid and kind = 'contingency_area';
  if unit_g is null then return; end if;
  cont_g := coalesce(cont_g, ST_Buffer(unit_g::geography, 500)::geometry);
  for l in select name from meta.layer where kind = 'state' loop
    return query execute format($q$
      select %1$L::text, t.feature_id,
             case when ST_Intersects(t.geom, $1) then 'unit' else 'contingency' end,
             to_jsonb(t) - 'geom' - 'row_id' - 'valid' - 'recorded',
             ST_AsGeoJSON(t.geom, 6)::jsonb
      from %1$s t
      where t.recorded @> $3 and t.valid @> $4
        and ST_Intersects(t.geom, ST_Union($1, $2))$q$, l.name)
      using unit_g, cont_g, k, g;
  end loop;
end $$;
