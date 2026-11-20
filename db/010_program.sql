-- rx: the burn program level: a season's operation order, people reused across burns, meetings.

-- One season (year) of the burn program, with its operation order.
create table plans.season (
  year         int primary key,
  op_name      text,                          -- e.g. Op BURNING STAG
  start_date   date,
  end_date     date,
  opord        jsonb not null default '{}',   -- content, structured by schema.OPORD
  status       text not null default 'draft' check (status in ('draft','signed')),
  signed_name  text,                          -- who signed (e.g. Base Commander)
  signed_at    timestamptz,
  revision     int not null default 1,
  updated_at   timestamptz not null default now(),
  updated_by   text
);
create table plans.opord_rev (
  id        bigserial primary key,
  year      int not null,
  revision  int not null,
  opord     jsonb not null,
  status    text not null,
  saved_at  timestamptz not null default now(),
  saved_by  text
);
create or replace function plans.log_opord() returns trigger language plpgsql as $$
begin
  insert into plans.opord_rev (year, revision, opord, status, saved_by) values (new.year, new.revision, new.opord, new.status, new.updated_by);
  return new;
end $$;
create trigger log_opord after insert or update of opord, status on plans.season for each row execute function plans.log_opord();

alter table plans.plan add column if not exists season_year int;
update plans.plan set season_year = coalesce(season_year, extract(year from created_at)::int + 1);

-- People reused on every burn: name, rank, appointment, contact, qualifications.
create table plans.person (
  id           serial primary key,
  name         text not null,
  rank         text,
  appointment  text,                          -- e.g. Chief Range Controller, Fire Control Officer
  organization text,                          -- e.g. SES, Range Control, G3 Ops, RTAMS
  phone        text,                          -- CSN or other
  email        text,
  quals        text[] not null default '{}',  -- RXB2, FIRB, ICT4, FFT1, ENGB, FEMP, EMR ...
  poc          boolean not null default false,-- listed as a point of contact in the operation order
  active       boolean not null default true,
  notes        text,
  updated_at   timestamptz not null default now()
);

-- Who normally fills a role on every burn (e.g. burn boss) until changed.
create table plans.role_default (
  role       text primary key,                -- burn_boss | firing_boss | holding_boss | lookout | medic | uxo_advisor | range_control | agency_administrator | technical_reviewer | preparer
  person_id  int references plans.person on delete set null
);

-- Meetings: planning, coordination, briefings, after action reviews.
create table plans.meeting (
  id          serial primary key,
  season_year int,
  plan_id     int references plans.plan on delete set null,
  kind        text not null default 'planning',   -- planning | coordination | briefing | aar | other
  title       text not null,
  held_at     timestamptz not null,
  location    text,
  attendees   int[] not null default '{}',        -- plans.person ids
  others      text,                                -- attendees not in the directory
  agenda      text,
  notes       text,
  decisions   text,
  actions     jsonb not null default '[]',         -- [{action, owner, due, done}]
  created_by  text,
  updated_at  timestamptz not null default now()
);
create index on plans.meeting (season_year);
create index on plans.meeting (plan_id);
