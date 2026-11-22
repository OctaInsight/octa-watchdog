-- Run after the migration text inside one transaction; the final exception rolls everything back.
do $$
declare t_admin text; t_user text; r jsonb; key text := 'test-runner-key-123'; rid uuid; tid uuid; c1 text; c2 text;
begin
  insert into public."User_accounts"(email, username, password_hash, role) values ('w.admin@example.org', 'zz_w_admin', 'x', 'admin');
  insert into public."User_accounts"(email, username, password_hash) values ('w.user@example.org', 'zz_w_user', 'x');
  t_admin := public.octa_user_new_session((select id from public."User_accounts" where username = 'zz_w_admin'), null);
  t_user := public.octa_user_new_session((select id from public."User_accounts" where username = 'zz_w_user'), null);

  assert not (public.watchdog_admin(t_user, '{"action":"overview"}')->>'ok')::boolean, 'non-admin';
  r := public.watchdog_admin(t_admin, '{"action":"overview"}');
  assert (r->>'ok')::boolean and jsonb_array_length(r->'targets') >= 2, 'overview ' || left(r::text, 300);
  assert not (r->'settings' ? 'runner_key_hash') and not (r->'settings'->>'key_set')::boolean, 'hash hidden';

  -- the runner cannot work without a key
  assert not (public.watchdog_runner(key, '{"action":"plan"}')->>'ok')::boolean, 'no key yet';
  r := public.watchdog_admin(t_admin, jsonb_build_object('action', 'set_runner_key', 'hash', encode(extensions.digest(key, 'sha256'), 'hex')));
  assert (r->>'ok')::boolean, 'set key';
  assert not (public.watchdog_runner('wrong', '{"action":"plan"}')->>'ok')::boolean, 'wrong key';

  -- targets
  r := public.watchdog_admin(t_admin, '{"action":"save_target","name":"ZZ site","url":"https://zz-example.org/"}');
  tid := (r->'target'->>'id')::uuid; assert tid is not null and r->'target'->>'kind' = 'website', 'add ' || r::text;
  assert not (public.watchdog_admin(t_admin, '{"action":"save_target","url":"https://zz-example.org/"}')->>'ok')::boolean, 'duplicate';
  assert not (public.watchdog_admin(t_admin, '{"action":"save_target","url":"ftp://x"}')->>'ok')::boolean, 'bad url';

  -- settings and rotation
  r := public.watchdog_admin(t_admin, '{"action":"save_settings","country":"JP","interval_minutes":30}');
  assert (r->>'ok')::boolean, 'settings ' || r::text;
  assert not (public.watchdog_admin(t_admin, '{"action":"save_settings","country":"Japan"}')->>'ok')::boolean, 'bad country';
  assert not (public.watchdog_admin(t_admin, '{"action":"save_settings","rotate":true,"rotate_countries":[]}')->>'ok')::boolean, 'empty rotation';
  assert (select country from public.watchdog_settings) = 'JP' and not (select rotate from public.watchdog_settings), 'rolled back bad save';

  delete from public.watchdog_runs;
  r := public.watchdog_runner(key, '{"action":"plan"}');
  assert (r->>'due')::boolean and r->>'country' = 'JP' and jsonb_array_length(r->'targets') >= 3, 'plan ' || left(r::text, 300);
  rid := (r->>'run_id')::uuid;
  assert (select planned_country from public.watchdog_runs where id = rid) = 'JP', 'run recorded at start';
  -- not due again straight away, unless forced
  assert not (public.watchdog_runner(key, '{"action":"plan"}')->>'due')::boolean, 'not due';
  r := public.watchdog_runner(key, jsonb_build_object('action', 'finish', 'run_id', rid, 'vpn_country', 'JP', 'public_ip', '1.2.3.4',
       'results', jsonb_build_array(jsonb_build_object('id', tid, 'status', 'woke', 'ms', 1200),
                                    jsonb_build_object('id', gen_random_uuid(), 'status', 'down', 'error', 'timeout'))));
  assert (r->>'ok')::boolean, 'finish ' || r::text;
  assert (select up || '/' || woke || '/' || down || ' ' || vpn_country from public.watchdog_runs where id = rid) = '0/1/1 JP', 'counts';
  assert (select last_status || last_country from public.watchdog_targets where id = tid) = 'wokeJP', 'target status';

  r := public.watchdog_admin(t_admin, '{"action":"save_settings","rotate":true,"rotate_countries":["NL","US"]}');
  c1 := public.watchdog_runner(key, '{"action":"plan","force":true}')->>'country';
  c2 := public.watchdog_runner(key, '{"action":"plan","force":true}')->>'country';
  assert c1 = 'NL' and c2 = 'US' and public.watchdog_runner(key, '{"action":"plan","force":true}')->>'country' = 'NL', 'rotation ' || c1 || c2;
  assert not has_table_privilege('anon', 'public.watchdog_settings', 'select'), 'table closed';
  raise exception 'WATCHDOG TEST PASSED (rolled back)';
end $$;
