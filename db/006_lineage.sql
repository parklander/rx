-- rx: a plan and all its earlier versions (amendments keep site visits and burn days with the version they were made on).
create or replace function plans.lineage(pid int) returns setof int language sql stable as $$
  with recursive up as (select id, parent_plan_id from plans.plan where id = pid
                        union all select p.id, p.parent_plan_id from plans.plan p join up on p.id = up.parent_plan_id)
  select id from up;
$$;
