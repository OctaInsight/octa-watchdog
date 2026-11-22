-- Octa Watchdog, main database (Supabase project Octa_projects). Applied 2026-11-22 as "watchdog".
--
--   watchdog_targets   the Streamlit apps and websites every run opens
--   watchdog_settings  one row: VPN country (or rotation), how often, how long each page stays open, runner key hash
--   watchdog_runs      one row per run: when it started (written the moment a run begins), country, results
--
-- Tables have row-level security on and no public access. The Watchdog app (Octa admins, signed in with their Octa
-- account) uses watchdog_admin(token, …); the GitHub Actions runner uses watchdog_runner(runner key, …), where the
-- key is created in the Watchdog app and only its SHA-256 hash is stored here.

create table if not exists public.watchdog_targets (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 1 and 120),
  url text not null unique check (url ~ '^https?://'),
  kind text not null default 'website' check (kind in ('streamlit', 'website')),
  active boolean not null default true,
  sort int not null default 100,
  created_at timestamptz not null default now(),
  last_checked_at timestamptz,
  last_status text,                 -- up | woke | down
  last_ms int,
  last_country text,
  last_error text
);

create table if not exists public.watchdog_settings (
  id int primary key default 1 check (id = 1),
  country text not null default 'NL' check (country ~ '^([A-Z]{2}|NONE)$'),
  rotate boolean not null default false,
  rotate_countries text[] not null default '{NL,US,JP,PL,RO,NO,CH,SG,MX,CA}',
  interval_minutes int not null default 30 check (interval_minutes between 15 and 1440),
  dwell_seconds int not null default 20 check (dwell_seconds between 5 and 120),
  runner_key_hash text,
  runner_key_set_at timestamptz,
  updated_at timestamptz not null default now(),
  updated_by uuid references public."User_accounts"(id) on delete set null
);
insert into public.watchdog_settings(id) values (1) on conflict do nothing;

create table if not exists public.watchdog_runs (
  id uuid primary key default gen_random_uuid(),
  started_at timestamptz not null default clock_timestamp(),
  finished_at timestamptz,
  source text not null default 'github',
  planned_country text,
  vpn_country text,                 -- the country the visits really came from (checked after connecting)
  public_ip text,
  up int, woke int, down int,
  results jsonb,
  note text
);
create index if not exists watchdog_runs_started on public.watchdog_runs(started_at desc);

alter table public.watchdog_targets enable row level security;
alter table public.watchdog_settings enable row level security;
alter table public.watchdog_runs enable row level security;
revoke all on public.watchdog_targets, public.watchdog_settings, public.watchdog_runs from anon, authenticated;

-- Live Octa apps from the suite's catalogue, to start with
insert into public.watchdog_targets(name, url, kind, sort)
select a.name, a.url, case when a.url like '%streamlit.app%' then 'streamlit' else 'website' end, a.sort_order
from public."User_apps" a where a.status = 'live' and coalesce(a.url, '') ~ '^https?://'
on conflict (url) do nothing;
insert into public.watchdog_targets(name, url, kind, sort)
values ('CloudEARTHi MOOC website', 'https://octainsight.github.io/mooc/', 'website', 25)
on conflict (url) do nothing;

-- ---------------------------------------------------------------------------------------------------- admin (app)
create or replace function public.watchdog_admin(p_token text, p jsonb) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare uid uuid; act text := p->>'action'; s public.watchdog_settings; r jsonb; n int;
begin
  update public."User_sessions" x set last_active_at = now(), expires_at = now() + interval '3 hours'
  where x.token_hash = public.octa_user_hash(coalesce(p_token, '')) and x.expires_at > now()
    and exists (select 1 from public."User_accounts" a where a.id = x.user_id and a.status <> 'suspended' and a.role = 'admin')
  returning x.user_id into uid;
  if uid is null then return jsonb_build_object('ok', false, 'error', 'Only Octa admins can use the Watchdog. Please sign in again.'); end if;

  if act = 'overview' then
    select * into s from public.watchdog_settings where id = 1;
    return jsonb_build_object('ok', true,
      'settings', to_jsonb(s) - 'runner_key_hash' || jsonb_build_object('key_set', s.runner_key_hash is not null),
      'targets', coalesce((select jsonb_agg(to_jsonb(t) order by t.sort, t.name) from public.watchdog_targets t), '[]'::jsonb),
      'runs', coalesce((select jsonb_agg(to_jsonb(x) order by x.started_at desc)
                        from (select * from public.watchdog_runs order by started_at desc limit coalesce((p->>'runs')::int, 30)) x), '[]'::jsonb));

  elsif act = 'save_settings' then
    if p ? 'country' and (p->>'country') !~ '^([A-Z]{2}|NONE)$' then return jsonb_build_object('ok', false, 'error', 'Choose a country.'); end if;
    if p ? 'rotate_countries' and exists (select 1 from jsonb_array_elements_text(p->'rotate_countries') c where c !~ '^[A-Z]{2}$') then
      return jsonb_build_object('ok', false, 'error', 'Countries are two-letter codes such as NL or US.'); end if;
    update public.watchdog_settings set
      country = coalesce(p->>'country', country),
      rotate = coalesce((p->>'rotate')::boolean, rotate),
      rotate_countries = case when p ? 'rotate_countries' then array(select jsonb_array_elements_text(p->'rotate_countries')) else rotate_countries end,
      interval_minutes = coalesce((p->>'interval_minutes')::int, interval_minutes),
      dwell_seconds = coalesce((p->>'dwell_seconds')::int, dwell_seconds),
      updated_at = now(), updated_by = uid
    where id = 1;
    if (select rotate and cardinality(rotate_countries) = 0 from public.watchdog_settings where id = 1) then
      raise exception 'Choose at least one country to rotate through.';
    end if;
    return jsonb_build_object('ok', true);

  elsif act = 'save_target' then
    if coalesce(p->>'url', '') !~ '^https?://[^\s]+$' then return jsonb_build_object('ok', false, 'error', 'The address must start with https://'); end if;
    if exists (select 1 from public.watchdog_targets where url = p->>'url' and id is distinct from (p->>'id')::uuid) then
      return jsonb_build_object('ok', false, 'error', 'This address is already in the list.'); end if;
    if p->>'id' is null then
      insert into public.watchdog_targets(name, url, kind, active, sort)
      values (left(coalesce(nullif(trim(p->>'name'), ''), p->>'url'), 120), p->>'url',
              coalesce(p->>'kind', case when p->>'url' like '%streamlit.app%' then 'streamlit' else 'website' end),
              coalesce((p->>'active')::boolean, true), coalesce((p->>'sort')::int, 100))
      returning to_jsonb(watchdog_targets.*) into r;
    else
      update public.watchdog_targets set name = left(coalesce(nullif(trim(p->>'name'), ''), name), 120), url = p->>'url',
             kind = coalesce(p->>'kind', kind), active = coalesce((p->>'active')::boolean, active), sort = coalesce((p->>'sort')::int, sort)
      where id = (p->>'id')::uuid returning to_jsonb(watchdog_targets.*) into r;
    end if;
    return jsonb_build_object('ok', r is not null, 'target', r);

  elsif act = 'delete_target' then
    delete from public.watchdog_targets where id = (p->>'id')::uuid;
    return jsonb_build_object('ok', true);

  elsif act = 'add_octa_apps' then
    insert into public.watchdog_targets(name, url, kind, sort)
    select a.name, a.url, case when a.url like '%streamlit.app%' then 'streamlit' else 'website' end, a.sort_order
    from public."User_apps" a where a.status = 'live' and coalesce(a.url, '') ~ '^https?://'
    on conflict (url) do nothing;
    get diagnostics n = row_count;
    return jsonb_build_object('ok', true, 'added', n);

  elsif act = 'set_runner_key' then
    if coalesce(p->>'hash', '') !~ '^[0-9a-f]{64}$' then return jsonb_build_object('ok', false, 'error', 'bad key hash'); end if;
    update public.watchdog_settings set runner_key_hash = p->>'hash', runner_key_set_at = now(), updated_at = now(), updated_by = uid where id = 1;
    return jsonb_build_object('ok', true);
  end if;
  return jsonb_build_object('ok', false, 'error', 'Unknown action ' || coalesce(act, ''));
exception when others then
  return jsonb_build_object('ok', false, 'error', sqlerrm);
end $$;

-- ---------------------------------------------------------------------------------------------------- runner (GitHub)
create or replace function public.watchdog_runner(p_key text, p jsonb) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare s public.watchdog_settings; act text := p->>'action'; last public.watchdog_runs; c text; i int; rid uuid;
        x jsonb; n_up int := 0; n_woke int := 0; n_down int := 0;
begin
  select * into s from public.watchdog_settings where id = 1;
  if s.runner_key_hash is null or encode(extensions.digest(coalesce(p_key, ''), 'sha256'), 'hex') <> s.runner_key_hash then
    return jsonb_build_object('ok', false, 'error', 'Wrong runner key (WATCHDOG_KEY). Create a new one in the Watchdog app.');
  end if;

  if act = 'plan' then
    select * into last from public.watchdog_runs order by started_at desc limit 1;
    if not coalesce((p->>'force')::boolean, false) and last.id is not null
       and last.started_at > now() - make_interval(mins => greatest(s.interval_minutes - 3, 1)) then
      return jsonb_build_object('ok', true, 'due', false,
                                'next_at', last.started_at + make_interval(mins => s.interval_minutes));
    end if;
    if s.rotate and cardinality(s.rotate_countries) > 0 then
      i := array_position(s.rotate_countries, last.planned_country);
      c := s.rotate_countries[coalesce(i, 0) % cardinality(s.rotate_countries) + 1];
    else
      c := s.country;
    end if;
    -- the run is recorded the moment it starts
    insert into public.watchdog_runs(source, planned_country, note)
    values (coalesce(nullif(p->>'source', ''), 'github'), c, 'running') returning id into rid;
    delete from public.watchdog_runs where started_at < now() - interval '180 days';
    return jsonb_build_object('ok', true, 'due', true, 'run_id', rid, 'country', c, 'dwell_seconds', s.dwell_seconds,
      'targets', coalesce((select jsonb_agg(jsonb_build_object('id', t.id, 'name', t.name, 'url', t.url, 'kind', t.kind) order by t.sort, t.name)
                           from public.watchdog_targets t where t.active), '[]'::jsonb));

  elsif act = 'finish' then
    rid := (p->>'run_id')::uuid;
    for x in select * from jsonb_array_elements(coalesce(p->'results', '[]'::jsonb)) loop
      if x->>'status' = 'up' then n_up := n_up + 1; elsif x->>'status' = 'woke' then n_woke := n_woke + 1; else n_down := n_down + 1; end if;
      update public.watchdog_targets set last_checked_at = now(), last_status = left(x->>'status', 10),
             last_ms = (x->>'ms')::int, last_country = left(p->>'vpn_country', 10), last_error = left(x->>'error', 300)
      where id = (x->>'id')::uuid;
    end loop;
    update public.watchdog_runs set finished_at = now(), vpn_country = left(p->>'vpn_country', 10),
           public_ip = left(p->>'public_ip', 60), up = n_up, woke = n_woke, down = n_down,
           results = p->'results', note = left(p->>'note', 500)
    where id = rid;
    return jsonb_build_object('ok', found);
  end if;
  return jsonb_build_object('ok', false, 'error', 'Unknown action');
end $$;

revoke execute on function public.watchdog_admin(text, jsonb) from public;
revoke execute on function public.watchdog_runner(text, jsonb) from public;
grant execute on function public.watchdog_admin(text, jsonb) to anon, authenticated;
grant execute on function public.watchdog_runner(text, jsonb) to anon, authenticated;
