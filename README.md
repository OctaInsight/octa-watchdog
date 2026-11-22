# Octa Watchdog

Keeps the Octa Streamlit apps, websites and Supabase databases awake, and checks that they work when visited from
the country you choose.

| Part | What it does |
|---|---|
| **Watchdog app** (`app.py`, `pages/admin.py`, Streamlit) | Octa admins choose the VPN country (one, or taking turns), how often runs happen and how long each page stays open; manage the list of apps and websites; make the runner key; see every run |
| **Runner** (`runner/watchdog_run.py`, GitHub Actions `.github/workflows/watchdog.yml`) | Every 6 hours a run records its start in **both** databases, connects Proton VPN (WireGuard) for the chosen country, opens every app and website in a real Chromium browser (waking sleeping Streamlit apps, scrolling for a while so the sites' analytics count the visit), then saves how each page answered |
| **Databases** (`supabase/migrations/`) | Octa_projects: `watchdog_targets` (the list), `watchdog_settings`, `watchdog_runs`. Data_and_Future: `watchdog_runs` (start time of every run). All closed to the public; reached only through `watchdog_admin` (Octa admins), `watchdog_runner` (runner key) and `watchdog_ping` |

## Setting up

1. **Streamlit secrets** for the Watchdog app: `[octa_users]` (`url`, `key` of Octa_projects, as in the other Octa apps)
   and `[data_and_future]` (`url`, `key` of Data_and_Future). The app touches both databases whenever it is opened.
2. In the app, **Apps, websites and setup** → **Make the runner key**; save it in GitHub as the Actions secret `WATCHDOG_KEY`.
3. For every country you want: download a Proton VPN WireGuard file (account.protonvpn.com → Downloads → WireGuard
   configuration, platform Linux) and save its whole text as the GitHub secret `PROTON_WG_<CODE>`, e.g. `PROTON_WG_NL`.
4. GitHub → Actions → **Watchdog** → **Run workflow** for a first run.

The page lists the details. Secrets live only in GitHub Actions secrets and Streamlit secrets, never in the code; the
two Supabase keys in the workflow are publishable keys, which are meant to be public.

## Tests

`python -m pytest tests runner/tests` (no database, VPN or internet needed). Database tests in `supabase/tests/` run
inside a transaction that is rolled back.
