-- The Watchdog in the Octa suite catalogue (applied 2026-11-22 as "watchdog_in_octa_suite").
-- Approval-only, like the other internal Octa Insight apps: it opens only for accounts granted access, and the app
-- itself also accepts only Octa admins. Octa admins are granted access now.
insert into public."User_apps"(id, family, name, description, icon, url, status, access_mode, group_label, sort_order)
values ('octa_watchdog', 'cloudearthi', 'Octa Watchdog',
        'Keeps the Octa apps, websites and databases awake, visiting from chosen countries (Octa Insight only)',
        '🛡️', 'https://octa-watchdog.streamlit.app/', 'live', 'approval', 'Administration', 900)
on conflict (id) do update set name = excluded.name, description = excluded.description, icon = excluded.icon,
  url = excluded.url, status = excluded.status, access_mode = excluded.access_mode,
  group_label = excluded.group_label, family = excluded.family;
insert into public."User_app_access"(user_id, app_id, status)
select id, 'octa_watchdog', 'granted' from public."User_accounts" where role = 'admin'
on conflict (user_id, app_id) do update set status = 'granted', updated_at = now();
