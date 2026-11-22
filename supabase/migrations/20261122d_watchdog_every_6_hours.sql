-- Runs every 6 hours (GitHub schedule). Applied 2026-11-22 as "watchdog_every_6_hours".
-- The database's minimum gap between runs is 5 hours, so a scheduled run that GitHub starts late never makes the
-- next one look "too soon".
alter table public.watchdog_settings alter column interval_minutes set default 300;
update public.watchdog_settings set interval_minutes = 300 where id = 1;
