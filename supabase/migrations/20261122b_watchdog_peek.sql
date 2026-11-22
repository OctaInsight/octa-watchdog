-- watchdog_runner action "peek": is a run due? (read only, used before the GitHub job installs the browser).
-- Applied 2026-11-22 as "watchdog_peek".
do $$ declare f oid; def text; old text; begin
  select p.oid into f from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname = 'watchdog_runner';
  def := pg_get_functiondef(f);
  old := E'  if act = ''plan'' then';
  if position(old in def) = 0 then raise exception 'watchdog_runner: plan not found'; end if;
  def := replace(def, old,
       E'  if act = ''peek'' then\n'
    || E'    select * into last from public.watchdog_runs order by started_at desc limit 1;\n'
    || E'    return jsonb_build_object(''ok'', true, ''due'', last.id is null or last.started_at <= now() - make_interval(mins => greatest(s.interval_minutes - 3, 1)));\n'
    || E'  elsif act = ''plan'' then');
  execute def;
end $$;
