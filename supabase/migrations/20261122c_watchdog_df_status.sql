-- Data_and_Future (elqdtcmewughlpwejtsn): the last runs, for the Watchdog app's dashboard. Applied 2026-11-22 as
-- "watchdog_status". Only time stamps, sources and countries; callable with the publishable key.
create or replace function public.watchdog_status(p_limit int default 10) returns jsonb
language sql security definer set search_path = '' as $$
  select jsonb_build_object('ok', true, 'runs', coalesce(jsonb_agg(jsonb_build_object('started_at', r.started_at,
           'source', r.source, 'country', r.country) order by r.started_at desc), '[]'::jsonb))
  from (select * from public.watchdog_runs order by started_at desc limit least(greatest(coalesce(p_limit, 10), 1), 50)) r
$$;
revoke execute on function public.watchdog_status(int) from public;
grant execute on function public.watchdog_status(int) to anon, authenticated;
