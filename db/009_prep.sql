-- rx: pre-burn work that lowers complexity (mulching along control lines, wet lines, snag felling...)
-- with where it goes, how wide, what it mitigates, and proof that it was done and checked.

create table plans.prep_task (
  id            uuid primary key default gen_random_uuid(),
  plan_id       int not null references plans.plan on delete cascade,
  kind          text not null,             -- mulch | mow | disc | grade | wet_line | black_line | brush_removal | snag_felling | protect_asset | water | signage | other
  title         text not null,
  width_m       numeric,                   -- for work along a line
  depth_cm      numeric,                   -- discing / grading depth
  spec          text,                      -- standard to meet, e.g. "mulch to < 10 cm, remove juniper"
  dac_required  boolean not null default false,  -- needs DAC clearance before ground disturbance
  required_for  text not null default 'ignition' check (required_for in ('approval','ignition','none')),
  required_by   date,
  assigned_to   text,
  mitigates     text[] not null default '{}',     -- PMS 424 complexity elements this lowers
  status        text not null default 'planned' check (status in ('planned','assigned','done','verified','not_needed')),
  geom          geometry(Geometry, 4326) not null,
  created_by    text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index on plans.prep_task (plan_id);
create index on plans.prep_task using gist (geom);

-- Every change of status, with who, when and what was found (measured width, note, site visit record).
create table plans.prep_event (
  id          bigserial primary key,
  task_id     uuid not null references plans.prep_task on delete cascade,
  status      text not null,
  note        text,
  measured    jsonb not null default '{}',  -- {width_m, depth_cm}
  record_id   uuid,                         -- field.record that carries the photos and GPS position
  at          timestamptz not null default now(),
  by_user     text
);
create unique index on plans.prep_event (record_id) where record_id is not null;
create index on plans.prep_event (task_id);

-- Site visit records can now be prep-work checks.
alter table field.record drop constraint if exists record_kind_check;
alter table field.record add constraint record_kind_check check (kind in ('note','photo','fuel_plot','check','hazard','water','access','prep'));

-- Amendments carry the work list forward.
