-- Octa Watchdog, second database (Supabase project Data_and_Future, elqdtcmewughlpwejtsn). Applied 2026-11-22 as
-- "watchdog". Each Watchdog run writes the moment it starts here too, which also keeps this free-plan project from
-- being paused for inactivity.
--
-- watchdog_ping can be called with the project's publishable key and no secret: it only adds a time stamp, at most
-- one a minute, and keeps 180 days. The table itself is closed to the public.

create table if not exists public.watchdog_runs (
  id bigint generated always as identity primary key,
  started_at timestamptz not null default clock_timestamp(),
  source text not null default 'github',
  country text
);
alter table public.watchdog_runs enable row level security;
revoke all on public.watchdog_runs from anon, authenticated;

create or replace function public.watchdog_ping(p_source text default 'github', p_country text default null)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare last timestamptz;
begin
  select max(started_at) into last from public.watchdog_runs;
  if last > clock_timestamp() - interval '1 minute' then
    return jsonb_build_object('ok', true, 'skipped', true, 'last', last);
  end if;
  insert into public.watchdog_runs(source, country) values (left(coalesce(p_source, 'github'), 40), left(p_country, 10));
  delete from public.watchdog_runs where started_at < now() - interval '180 days';
  return jsonb_build_object('ok', true, 'at', clock_timestamp());
end $$;
revoke execute on function public.watchdog_ping(text, text) from public;
grant execute on function public.watchdog_ping(text, text) to anon, authenticated;
