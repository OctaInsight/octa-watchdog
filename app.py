"""
Octa Watchdog — Opens each Streamlit app in a headless browser to keep it alive.
Records every visit in watchdog_logs so the database also stays active.
"""
import streamlit as st
import threading
import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from supabase import create_client, Client

OSLO = ZoneInfo("Europe/Oslo")

def _now_oslo() -> str:
    return datetime.now(OSLO).strftime("%d %b %H:%M:%S")

def _utc_to_oslo(ts: str) -> str:
    """Convert UTC ISO timestamp to Oslo local time string."""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        oslo = dt.astimezone(OSLO)
        return oslo.strftime("%d %b %H:%M:%S")
    except Exception:
        return ts[:19]

st.set_page_config(
    page_title="Octa Watchdog",
    page_icon=":shield:",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
html,body,[data-testid="stAppViewContainer"]{background:#0f1421!important;color:#e2e8f0!important}
[data-testid="stSidebar"]{background:#1B2A4A!important;border-right:3px solid #00BCD4!important}
[data-testid="stSidebar"] *{color:#e2e8f0!important}
[data-testid="stSidebarNav"]{display:none!important}
h1,h2,h3{color:#e2e8f0!important}
[data-testid="stButton"]>button{background:#232f45!important;
    border:1px solid rgba(255,255,255,0.09)!important;color:#e2e8f0!important;border-radius:8px!important}
[data-testid="stButton"]>button[kind="primary"]{
    background:linear-gradient(135deg,#00BCD4,#0097A7)!important;
    border:none!important;color:white!important;font-weight:600!important}
input{background:#232f45!important;border-radius:8px!important;color:#e2e8f0!important}
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def db() -> Client:
    return create_client(
        st.secrets["supabase"]["url"],
        st.secrets["supabase"]["key"]
    )


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_settings() -> dict:
    try:
        r = db().table("watchdog_settings").select("*").limit(1).execute()
        return r.data[0] if r.data else {"interval_minutes": 360}
    except Exception:
        return {"interval_minutes": 360}


def save_interval(minutes: int):
    try:
        rows = db().table("watchdog_settings").select("id").limit(1).execute().data
        if rows:
            db().table("watchdog_settings").update({
                "interval_minutes": minutes,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", rows[0]["id"]).execute()
        else:
            db().table("watchdog_settings").insert({"interval_minutes": minutes}).execute()
    except Exception:
        pass


def get_apps() -> list:
    try:
        return db().table("watchdog_apps").select("*").order("name").execute().data or []
    except Exception:
        return []


def get_recent_logs(limit: int = 30) -> list:
    try:
        return db().table("watchdog_logs").select("*")                    .order("visited_at", desc=True)                    .limit(limit).execute().data or []
    except Exception:
        return []


def log_visit(app_id: int, app_name: str, url: str,
              status: str, response_ms: int, notes: str = ""):
    """Write one row to watchdog_logs — this also keeps Supabase active."""
    try:
        db().table("watchdog_logs").insert({
            "app_id":      app_id,
            "app_name":    app_name,
            "url":         url,
            "visited_at":  datetime.now(timezone.utc).isoformat(),
            "status":      status,
            "response_ms": response_ms,
            "notes":       notes,
        }).execute()
    except Exception:
        pass


def update_app_status(app_id: int, status: str, ms: int):
    try:
        row = db().table("watchdog_apps").select(
            "check_count,fail_count"
        ).eq("id", app_id).execute().data
        checks = (row[0]["check_count"] or 0) + 1 if row else 1
        fails  = (row[0]["fail_count"]  or 0) + (1 if status == "down" else 0) if row else 0
        db().table("watchdog_apps").update({
            "last_checked":     datetime.now(timezone.utc).isoformat(),
            "last_status":      status,
            "last_response_ms": ms,
            "check_count":      checks,
            "fail_count":       fails,
        }).eq("id", app_id).execute()
    except Exception:
        pass


# ── Headless browser visit ────────────────────────────────────────────────────

def _make_driver():
    import os
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,720")
    opts.add_argument("--disable-software-rasterizer")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 Chrome/120 Safari/537.36 OctaWatchdog/1.0"
    )
    # Try multiple known Chromium paths on Linux
    for binary in ["/usr/bin/chromium",
                   "/usr/bin/chromium-browser",
                   "/usr/bin/google-chrome-stable",
                   "/usr/bin/google-chrome"]:
        if os.path.exists(binary):
            opts.binary_location = binary
            break

    # Try multiple known chromedriver paths
    for driver_path in ["/usr/bin/chromedriver",
                        "/usr/lib/chromium/chromedriver",
                        "/usr/lib/chromium-browser/chromedriver"]:
        if os.path.exists(driver_path):
            svc = Service(driver_path)
            return webdriver.Chrome(service=svc, options=opts)

    # Last resort: let Selenium find it automatically
    return webdriver.Chrome(options=opts)


def visit_app(app: dict):
    """
    Open the app in headless Chromium, wait for Streamlit WebSocket,
    then log the result to Supabase (which also keeps the DB awake).
    """
    url    = app["url"]
    app_id = app["id"]
    name   = app.get("name","")
    start  = time.time()
    driver = None
    status = "down"
    notes  = ""

    try:
        driver = _make_driver()
        driver.get(url)
        time.sleep(60)  # keep browser open 60s so Streamlit registers a real session
        ms     = int((time.time() - start) * 1000)
        status = "up"
        notes  = f"Page title: {driver.title[:60]}" if driver.title else ""
    except Exception as e:
        ms    = int((time.time() - start) * 1000)
        notes = str(e)[:120]
    finally:
        if driver:
            try: driver.quit()
            except Exception: pass

    # Write to both tables — this double-pings Supabase
    log_visit(app_id, name, url, status, ms, notes)
    update_app_status(app_id, status, ms)


def visit_all(apps: list):
    """
    Visit apps one at a time (sequential, not parallel).
    Safer for memory — only one Chrome instance open at a time.
    Each visit: ~10-15 seconds. 10 apps = ~2 minutes total.
    """
    active = [a for a in apps if a.get("is_active")]
    for app in active:
        visit_app(app)   # wait for this one to fully close before next


# ── Load data & auto-visit ────────────────────────────────────────────────────

settings = get_settings()
interval = settings.get("interval_minutes", 10)
apps     = get_apps()

# Auto-refresh at the set interval
# Auto-visit logic handled by time-based trigger below (no autorefresh needed)

# ── Time-based auto-visit trigger ────────────────────────────────────────────
# Runs on every page load (UptimeRobot pings watchdog every 5 min).
# Starts visits only if interval_hours have passed since last round.

def _run_visits_in_background(apps_to_visit: list):
    """Background thread: visits each app, updates progress in DB."""
    n = len(apps_to_visit)
    for i, app in enumerate(apps_to_visit):
        # Save progress to settings so UI can show it
        try:
            rows = db().table("watchdog_settings").select("id").limit(1).execute().data
            if rows:
                db().table("watchdog_settings").update({
                    "progress_current": i + 1,
                    "progress_total":   n,
                    "progress_app":     app.get("name",""),
                }).eq("id", rows[0]["id"]).execute()
        except Exception:
            pass
        visit_app(app)
    # Clear progress when done
    try:
        rows = db().table("watchdog_settings").select("id").limit(1).execute().data
        if rows:
            db().table("watchdog_settings").update({
                "progress_current": 0,
                "progress_total":   0,
                "progress_app":     "",
                "last_round_at":    datetime.now(timezone.utc).isoformat(),
            }).eq("id", rows[0]["id"]).execute()
    except Exception:
        pass


if "visit_thread" not in st.session_state:
    st.session_state.visit_thread = None

def _thread_alive() -> bool:
    t = st.session_state.get("visit_thread")
    return t is not None and t.is_alive()


# Check if it is time to run a visit round
def _should_visit() -> bool:
    if _thread_alive():
        return False
    last_round = settings.get("last_round_at","")
    if not last_round:
        return True   # never run before
    try:
        last_dt  = datetime.fromisoformat(last_round.replace("Z","+00:00"))
        interval_h = interval // 60
        return datetime.now(timezone.utc) - last_dt >= timedelta(hours=interval_h)
    except Exception:
        return True

if apps and _should_visit():
    active_apps_list = [a for a in apps if a.get("is_active")]
    if active_apps_list:
        t = threading.Thread(
            target=_run_visits_in_background,
            args=(active_apps_list,),
            daemon=True
        )
        t.start()
        st.session_state.visit_thread = t

logs = get_recent_logs(30)
progress_current = settings.get("progress_current", 0) or 0
progress_total   = settings.get("progress_total",   0) or 0
progress_app     = settings.get("progress_app",    "") or ""
last_round_at    = _utc_to_oslo(settings.get("last_round_at",""))


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
<div style="text-align:center;padding:1rem 0 0.5rem">
<div style="font-size:2.5rem">shield</div>
<div style="font-weight:700;font-size:1rem;color:#e2e8f0">Octa Watchdog</div>
<div style="color:#8899b0;font-size:0.7rem">Real browser visits</div>
</div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("<div style='color:#8899b0;font-size:0.75rem;font-weight:600;"
                "text-transform:uppercase;letter-spacing:0.08em'>Visit Interval (hours)</div>",
                unsafe_allow_html=True)
    # interval stored as minutes internally; display as hours
    interval_hrs = max(1, interval // 60)
    new_hrs = st.slider("hours", 1, 12, interval_hrs, label_visibility="collapsed",
                         help="How many hours between browser visits to each app")
    new_interval = new_hrs * 60   # convert back to minutes
    if new_interval != interval:
        save_interval(new_interval)
        st.success(f"Set to every {new_hrs}h"); st.rerun()

    active_count = len([a for a in apps if a.get("is_active")])
    round_mins   = active_count * 1   # ~1 min per app (60s visit)
    active_count = len([a for a in apps if a.get("is_active")])
    interval_h2  = interval // 60
    round_mins2  = active_count   # ~1 min per app
    st.markdown(
        f"<div style='background:#1a2235;border-radius:8px;padding:0.6rem 0.8rem;"
        f"margin-top:0.5rem;font-size:0.82rem;color:#8899b0'>"
        f"Every <strong style='color:#00BCD4'>{interval_h2}h</strong> · "
        f"60s/app · {active_count} apps<br>"
        f"~{round_mins2} min/round · {len(logs)} log entries<br>"
        f"<span style='font-size:0.75rem'>UptimeRobot keeps this app awake</span>"
        f"</div>", unsafe_allow_html=True)

    st.markdown("---")
    if st.button("Visit All Now", use_container_width=True, type="primary"):
        if _thread_alive():
            st.warning("Already running...")
        else:
            active_now = [a for a in apps if a.get("is_active")]
            t = threading.Thread(
                target=_run_visits_in_background,
                args=(active_now,), daemon=True
            )
            t.start()
            st.session_state.visit_thread = t
            st.success("Started!"); st.rerun()

    st.markdown("---")
    if st.button("Admin Panel", use_container_width=True):
        st.switch_page("pages/admin.py")


# ── Dashboard ─────────────────────────────────────────────────────────────────

st.markdown("""
<div style="background:linear-gradient(135deg,#1B2A4A,#2d4a7a);
padding:1.2rem 1.8rem;border-radius:12px;border-left:4px solid #00BCD4;margin-bottom:1.5rem">
<h1 style="margin:0;font-size:1.6rem;color:white">Octa Watchdog</h1>
<p style="margin:0.2rem 0 0;color:rgba(255,255,255,0.65);font-size:0.88rem">
Opens each Streamlit app in a headless browser every few hours.
Every visit is logged to Supabase — keeping both the apps AND the database active.
</p></div>""", unsafe_allow_html=True)

# Show live status of background visits
# Progress bar + status
if _thread_alive() and progress_total > 0:
    suc = "#6fcf97"
    pct = progress_current / progress_total
    st.markdown(
        f"<div style='background:{suc}22;border:1px solid {suc};border-radius:8px;"
        f"padding:0.7rem 1rem;margin-bottom:0.8rem'>"
        f"<strong style='color:{suc}'>⚙ Visiting apps...</strong> &nbsp;"
        f"<span style='color:#e2e8f0;font-size:0.85rem'>"
        f"{progress_current}/{progress_total} — currently: {progress_app}</span>"
        f"</div>", unsafe_allow_html=True)
    st.progress(pct, text=f"{progress_app} ({progress_current}/{progress_total})")
elif _thread_alive():
    st.info("⚙ Visit round starting...")
elif last_round_at:
    interval_h = interval // 60
    st.markdown(
        f"<div style='background:#1a2235;border-radius:8px;"
        f"padding:0.5rem 1rem;margin-bottom:0.8rem;font-size:0.82rem;color:#8899b0'>"
        f"Last visit round: <strong style='color:#00BCD4'>{last_round_at} (Oslo)</strong>"
        f" &nbsp;|&nbsp; Next in ~{interval_h}h</div>",
        unsafe_allow_html=True)

# KPI row
active_apps   = [a for a in apps if a.get("is_active")]
up_count      = sum(1 for a in active_apps if a.get("last_status") == "up")
down_count    = sum(1 for a in active_apps if a.get("last_status") == "down")
total_logs    = len(logs)
success_logs  = sum(1 for l in logs if l.get("status") == "up")

k1,k2,k3,k4 = st.columns(4)
for col, label, val, color in [
    (k1,"Monitored",      len(active_apps), "#00BCD4"),
    (k2,"Online",         up_count,         "#6fcf97"),
    (k3,"Offline",        down_count,       "#fc8181"),
    (k4,"Recent Visits",  total_logs,       "#f6cc52"),
]:
    col.markdown(
        f"<div style='background:#1a2235;border-top:3px solid {color};"
        f"border:1px solid {color}44;border-radius:10px;"
        f"padding:0.8rem;text-align:center'>"
        f"<div style='font-size:1.8rem;font-weight:700;color:{color}'>{val}</div>"
        f"<div style='font-size:0.75rem;color:#8899b0'>{label}</div></div>",
        unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

if not apps:
    st.info("No apps registered. Go to Admin Panel to add your Streamlit URLs.")
    st.stop()

# App status cards
st.markdown("<div style='font-size:0.72rem;font-weight:600;letter-spacing:0.08em;"
            "text-transform:uppercase;color:#00BCD4;margin-bottom:0.6rem;"
            "padding-bottom:0.3rem;border-bottom:1px solid rgba(255,255,255,0.09)'>"
            "App Status</div>", unsafe_allow_html=True)

for app in sorted(apps, key=lambda x: x.get("name","")):
    status = app.get("last_status","unknown")
    active = app.get("is_active", True)
    ms     = app.get("last_response_ms",0) or 0
    checked= app.get("last_checked","")
    checks = app.get("check_count",0) or 0
    fails  = app.get("fail_count",0)  or 0
    uptime = round((1 - fails/checks)*100,1) if checks>0 else 0

    if not active:
        color="  #555577"; badge="Paused"
    elif status=="up":
        color="#6fcf97"; badge=f"Visited OK ({ms/1000:.1f}s)"
    elif status=="down":
        color="#fc8181"; badge="Visit failed"
    else:
        color="#f6cc52"; badge="Not yet visited"

    checked_str = _utc_to_oslo(checked)

    st.markdown(
        f"<div style='background:#1a2235;border:1px solid rgba(255,255,255,0.09);"
        f"border-left:5px solid {color};border-radius:10px;"
        f"padding:0.8rem 1.2rem;margin-bottom:0.4rem'>"
        f"<div style='display:flex;justify-content:space-between;flex-wrap:wrap;gap:0.5rem'>"
        f"<div><strong style='color:#e2e8f0'>{app.get('name','')}</strong>"
        f"<a href='{app.get('url','')}' target='_blank' "
        f"style='color:#8899b0;font-size:0.75rem;margin-left:0.5rem;text-decoration:none'>"
        f"{app.get('url','')[:55]}{'...' if len(app.get('url',''))>55 else ''}</a></div>"
        f"<div style='text-align:right;font-size:0.8rem'>"
        f"<span style='color:{color};font-weight:600'>{badge}</span>"
        + (f"<br><span style='color:#8899b0;font-size:0.75rem'>"
           f"Last: {checked_str} | Uptime: {uptime}% | {checks} visits</span>"
           if checked_str else "")
        + "</div></div></div>",
        unsafe_allow_html=True)


# ── Visit log ─────────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.markdown("<div style='font-size:0.72rem;font-weight:600;letter-spacing:0.08em;"
            "text-transform:uppercase;color:#00BCD4;margin-bottom:0.6rem;"
            "padding-bottom:0.3rem;border-bottom:1px solid rgba(255,255,255,0.09)'>"
            "Recent Visit Log (last 30)</div>", unsafe_allow_html=True)

if not logs:
    st.info("No visits logged yet. Visits will appear here after the first run.")
else:
    # Table header
    st.markdown(
        "<div style='display:grid;grid-template-columns:2fr 1fr 1fr 1fr 3fr;"
        "gap:0.5rem;padding:0.4rem 0.8rem;background:#232f45;border-radius:6px;"
        "font-size:0.73rem;font-weight:600;color:#8899b0;margin-bottom:0.2rem'>"
        "<span>App</span><span>Time</span><span>Status</span>"
        "<span>Response</span><span>Notes</span></div>",
        unsafe_allow_html=True)

    for log in logs:
        lstat = log.get("status","unknown")
        lc    = "#6fcf97" if lstat=="up" else "#fc8181"
        lms   = log.get("response_ms",0) or 0
        lt = _utc_to_oslo(log.get("visited_at",""))
        lnotes= (log.get("notes","") or "")[:60]

        st.markdown(
            f"<div style='display:grid;grid-template-columns:2fr 1fr 1fr 1fr 3fr;"
            f"gap:0.5rem;padding:0.3rem 0.8rem;background:#1a2235;"
            f"border-radius:4px;font-size:0.78rem;margin-bottom:2px'>"
            f"<span style='color:#e2e8f0'>{log.get('app_name','')}</span>"
            f"<span style='color:#8899b0'>{lt}</span>"
            f"<span style='color:{lc};font-weight:600'>{lstat}</span>"
            f"<span style='color:#8899b0'>{lms/1000:.1f}s</span>"
            f"<span style='color:#8899b0;font-size:0.72rem'>{lnotes}</span>"
            f"</div>",
            unsafe_allow_html=True)

st.markdown(
    f"<div style='text-align:center;color:#8899b0;font-size:0.73rem;margin-top:1rem'>"
    f"Browser visit every {interval//60}h &nbsp;|&nbsp; "
    f"60s per app &nbsp;|&nbsp; "
    f"Time (Oslo): {_now_oslo()}</div>",
    unsafe_allow_html=True)
