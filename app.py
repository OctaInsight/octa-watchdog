"""
Octa Watchdog — Opens each Streamlit app in a headless browser to keep it alive.
Records every visit in watchdog_logs so the database also stays active.
"""
import streamlit as st
import threading
import time
from datetime import datetime, timezone
from supabase import create_client, Client
from streamlit_autorefresh import st_autorefresh

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
        return r.data[0] if r.data else {"interval_minutes": 240}
    except Exception:
        return {"interval_minutes": 240}


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
# interval is stored in minutes; convert to ms for autorefresh
st_autorefresh(interval=interval * 60 * 1000, key="watchdog")

# Visit all apps on every refresh
if apps:
    visit_all(apps)
    time.sleep(3)
    apps = get_apps()

logs = get_recent_logs(30)


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
    st.markdown(
        f"<div style='background:#1a2235;border-radius:8px;padding:0.6rem 0.8rem;"
        f"margin-top:0.5rem;font-size:0.82rem;color:#8899b0'>"
        f"Visit every <strong style='color:#00BCD4'>{interval_hrs}h</strong><br>"
        f"60s per app | {active_count} apps | ~{round_mins} min/round<br>"
        f"Log entries: <strong style='color:#00BCD4'>{len(logs)}</strong>"
        f"</div>", unsafe_allow_html=True)

    st.markdown("---")
    if st.button("Visit All Now", use_container_width=True, type="primary"):
        with st.spinner("Opening all apps in browser..."):
            visit_all(apps)
            time.sleep(len([a for a in apps if a.get("is_active")]) * 65)
        st.rerun()

    st.markdown("---")
    if st.button("Admin Panel", use_container_width=True):
        st.switch_page("pages/admin.py")


# ── Dashboard ─────────────────────────────────────────────────────────────────

st.markdown("""
<div style="background:linear-gradient(135deg,#1B2A4A,#2d4a7a);
padding:1.2rem 1.8rem;border-radius:12px;border-left:4px solid #00BCD4;margin-bottom:1.5rem">
<h1 style="margin:0;font-size:1.6rem;color:white">Octa Watchdog</h1>
<p style="margin:0.2rem 0 0;color:rgba(255,255,255,0.65);font-size:0.88rem">
Opens each Streamlit app in a headless browser every few minutes.
Every visit is logged to Supabase — keeping both the apps AND the database active.
</p></div>""", unsafe_allow_html=True)

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

    checked_str = ""
    if checked:
        try:
            dt = datetime.fromisoformat(checked.replace("Z","+00:00"))
            checked_str = dt.strftime("%d %b %H:%M")
        except Exception:
            checked_str = checked[:16]

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
        lt    = log.get("visited_at","")
        try:
            dt   = datetime.fromisoformat(lt.replace("Z","+00:00"))
            lt   = dt.strftime("%d %b %H:%M:%S")
        except Exception:
            lt = lt[:19]
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
    f"Last run: {datetime.now().strftime('%H:%M:%S')}</div>",
    unsafe_allow_html=True)
