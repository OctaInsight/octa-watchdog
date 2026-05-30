"""
Octa Watchdog - Keeps Streamlit apps alive.
Strategy: HTTP GET with real browser headers + repeated pings.
- No Chrome, no Playwright, no WebSocket
- Uses <30MB RAM
- Wakes sleeping apps, prevents active ones from sleeping
- Combined with UptimeRobot pinging this watchdog every 5min = fully automatic
"""
import streamlit as st
import threading
import time
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from supabase import create_client, Client

OSLO = ZoneInfo("Europe/Oslo")

def _now_oslo() -> str:
    return datetime.now(OSLO).strftime("%d %b %H:%M:%S")

def _utc_to_oslo(ts: str) -> str:
    if not ts: return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(OSLO).strftime("%d %b %H:%M:%S")
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

# Browser-like headers so Streamlit Cloud accepts the request
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language":  "en-US,en;q=0.9",
    "Accept-Encoding":  "gzip, deflate, br",
    "Connection":       "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control":    "no-cache",
}


def visit_app(app: dict, hold_seconds: int = 60) -> tuple:
    """
    Make multiple HTTP requests to the app over hold_seconds duration.
    This simulates a user keeping the app open and prevents sleep.
    Returns (status, response_ms, notes).
    """
    url   = app["url"].rstrip("/")
    start = time.time()

    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        # Phase 1: Initial GET — wakes the app if sleeping
        resp = session.get(url, timeout=45, allow_redirects=True)
        code = resp.status_code

        if code >= 400:
            ms = int((time.time()-start)*1000)
            return "down", ms, f"HTTP {code}"

        # Phase 2: Hit the health endpoint
        try:
            session.get(f"{url}/_stcore/health", timeout=10)
        except Exception:
            pass

        # Phase 3: Keep session alive by polling health every 15s
        elapsed = time.time() - start
        while elapsed < hold_seconds:
            time.sleep(15)
            try:
                session.get(f"{url}/_stcore/health", timeout=10)
            except Exception:
                pass
            elapsed = time.time() - start

        ms    = int((time.time()-start)*1000)
        title = ""
        try:
            if "<title>" in resp.text:
                title = resp.text.split("<title>")[1].split("</title>")[0][:50]
        except Exception:
            pass
        return "up", ms, f"OK · {title}" if title else "OK"

    except requests.exceptions.ConnectionError:
        ms = int((time.time()-start)*1000)
        return "down", ms, "Connection refused (app may be sleeping)"
    except requests.exceptions.Timeout:
        ms = int((time.time()-start)*1000)
        return "down", ms, "Timeout (app may be starting up)"
    except Exception as e:
        ms = int((time.time()-start)*1000)
        return "down", ms, str(e)[:100]


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

def get_recent_logs(limit: int = 40) -> list:
    try:
        return db().table("watchdog_logs").select("*")                    .order("visited_at", desc=True).limit(limit).execute().data or []
    except Exception:
        return []

def _log_and_update(app: dict, status: str, ms: int, notes: str):
    now = datetime.now(timezone.utc).isoformat()
    try:
        db().table("watchdog_logs").insert({
            "app_id": app["id"], "app_name": app.get("name",""),
            "url": app.get("url",""), "visited_at": now,
            "status": status, "response_ms": ms, "notes": notes,
        }).execute()
    except Exception:
        pass
    try:
        row = db().table("watchdog_apps").select(
            "check_count,fail_count").eq("id", app["id"]).execute().data
        checks = (row[0]["check_count"] or 0) + 1 if row else 1
        fails  = (row[0]["fail_count"]  or 0) + (1 if status=="down" else 0) if row else 0
        db().table("watchdog_apps").update({
            "last_checked": now, "last_status": status,
            "last_response_ms": ms, "check_count": checks, "fail_count": fails,
        }).eq("id", app["id"]).execute()
    except Exception:
        pass

def _update_progress(sid, current, total, name):
    try:
        db().table("watchdog_settings").update({
            "progress_current": current,
            "progress_total":   total,
            "progress_app":     name,
        }).eq("id", sid).execute()
    except Exception:
        pass

def _clear_progress(sid):
    try:
        db().table("watchdog_settings").update({
            "progress_current": 0, "progress_total": 0, "progress_app": "",
            "last_round_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", sid).execute()
    except Exception:
        pass

def _run_visits(apps_list: list, settings_id: int, hold_seconds: int = 60):
    n = len(apps_list)
    for i, app in enumerate(apps_list):
        _update_progress(settings_id, i+1, n, app.get("name",""))
        status, ms, notes = visit_app(app, hold_seconds)
        _log_and_update(app, status, ms, notes)
    _clear_progress(settings_id)

def _should_visit(settings: dict, interval: int) -> bool:
    last = settings.get("last_round_at","")
    if not last: return True
    try:
        last_dt = datetime.fromisoformat(last.replace("Z","+00:00"))
        return datetime.now(timezone.utc) - last_dt >= timedelta(minutes=interval)
    except Exception:
        return True


# ── Load & trigger ────────────────────────────────────────────────────────────

settings = get_settings()
interval = settings.get("interval_minutes", 360)
apps     = get_apps()
sid      = settings.get("id", 1)

if "visit_thread" not in st.session_state:
    st.session_state.visit_thread = None

def _thread_alive() -> bool:
    t = st.session_state.get("visit_thread")
    return t is not None and t.is_alive()

active_apps = [a for a in apps if a.get("is_active")]

if active_apps and not _thread_alive() and _should_visit(settings, interval):
    t = threading.Thread(target=_run_visits, args=(active_apps, sid), daemon=True)
    t.start()
    st.session_state.visit_thread = t

logs             = get_recent_logs(40)
progress_current = settings.get("progress_current", 0) or 0
progress_total   = settings.get("progress_total",   0) or 0
progress_app     = settings.get("progress_app",    "") or ""
last_round_at    = _utc_to_oslo(settings.get("last_round_at",""))
interval_h       = max(1, interval // 60)


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
<div style="text-align:center;padding:1rem 0 0.5rem">
<div style="font-size:2.5rem">shield</div>
<div style="font-weight:700;font-size:1rem;color:#e2e8f0">Octa Watchdog</div>
<div style="color:#8899b0;font-size:0.7rem">HTTP keepalive · &lt;30MB RAM</div>
</div>""", unsafe_allow_html=True)
    st.markdown("---")

    st.markdown("<div style='color:#8899b0;font-size:0.75rem;font-weight:600;"
                "text-transform:uppercase'>Interval (hours)</div>",
                unsafe_allow_html=True)
    new_hrs = st.slider("h", 1, 12, interval_h, label_visibility="collapsed")
    if new_hrs * 60 != interval:
        save_interval(new_hrs * 60); st.success(f"Set to {new_hrs}h"); st.rerun()

    n_active = len(active_apps)
    round_min = n_active  # ~1 min per app (60s hold)
    st.markdown(
        f"<div style='background:#1a2235;border-radius:8px;padding:0.6rem 0.8rem;"
        f"margin-top:0.5rem;font-size:0.82rem;color:#8899b0'>"
        f"Every <strong style='color:#00BCD4'>{interval_h}h</strong><br>"
        f"{n_active} apps · 60s/app · ~{round_min} min/round<br>"
        f"<span style='font-size:0.73rem'>Add to UptimeRobot (5 min) for auto-run</span>"
        f"</div>", unsafe_allow_html=True)

    st.markdown("---")
    if st.button("Visit All Now", use_container_width=True, type="primary"):
        if _thread_alive():
            st.warning("Already running...")
        else:
            t = threading.Thread(target=_run_visits, args=(active_apps, sid), daemon=True)
            t.start()
            st.session_state.visit_thread = t
            st.success("Started!"); st.rerun()

    st.markdown("---")
    if st.button("Admin Panel", use_container_width=True):
        st.switch_page("pages/admin.py")


# ── Dashboard ─────────────────────────────────────────────────────────────────

st.markdown("""
<div style="background:linear-gradient(135deg,#1B2A4A,#2d4a7a);
padding:1.2rem 1.8rem;border-radius:12px;border-left:4px solid #00BCD4;margin-bottom:1rem">
<h1 style="margin:0;font-size:1.6rem;color:white">Octa Watchdog</h1>
<p style="margin:0.2rem 0 0;color:rgba(255,255,255,0.65);font-size:0.88rem">
Visits each app via HTTP every few hours to prevent sleeping. Under 30MB RAM.
Add this watchdog to UptimeRobot (5 min ping) for fully automatic operation.
</p></div>""", unsafe_allow_html=True)

# Progress / status banner
if _thread_alive() and progress_total > 0:
    suc = "#6fcf97"
    pct = progress_current / progress_total
    st.markdown(
        f"<div style='background:{suc}22;border:1px solid {suc};"
        f"border-radius:8px;padding:0.6rem 1rem;margin-bottom:0.5rem'>"
        f"<strong style='color:{suc}'>⚙ Running...</strong> "
        f"<span style='color:#e2e8f0'>{progress_current}/{progress_total} — {progress_app}</span>"
        f"</div>", unsafe_allow_html=True)
    st.progress(pct, text=f"{progress_app} ({progress_current}/{progress_total})")
elif _thread_alive():
    st.info("⚙ Starting...")
elif last_round_at:
    st.markdown(
        f"<div style='background:#1a2235;border-radius:8px;"
        f"padding:0.5rem 1rem;margin-bottom:0.5rem;font-size:0.82rem;color:#8899b0'>"
        f"Last round: <strong style='color:#00BCD4'>{last_round_at} (Oslo)</strong>"
        f" · Next in ~{interval_h}h</div>",
        unsafe_allow_html=True)

# KPI row
up_count   = sum(1 for a in active_apps if a.get("last_status")=="up")
down_count = sum(1 for a in active_apps if a.get("last_status")=="down")
k1,k2,k3,k4 = st.columns(4)
for col, label, val, color in [
    (k1,"Monitored",  len(active_apps), "#00BCD4"),
    (k2,"Online",     up_count,         "#6fcf97"),
    (k3,"Failed",     down_count,       "#fc8181"),
    (k4,"Log entries",len(logs),        "#f6cc52"),
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
    st.info("No apps yet. Go to Admin Panel to add your Streamlit URLs.")
    st.stop()

st.markdown("<div style='font-size:0.72rem;font-weight:600;text-transform:uppercase;"
            "color:#00BCD4;margin-bottom:0.5rem;padding-bottom:0.3rem;"
            "border-bottom:1px solid rgba(255,255,255,0.09)'>App Status</div>",
            unsafe_allow_html=True)

for app in sorted(apps, key=lambda x: x.get("name","")):
    status  = app.get("last_status","unknown")
    active  = app.get("is_active", True)
    ms      = app.get("last_response_ms",0) or 0
    checks  = app.get("check_count",0) or 0
    fails   = app.get("fail_count",0)  or 0
    uptime  = round((1-fails/checks)*100,1) if checks>0 else 0
    checked = _utc_to_oslo(app.get("last_checked",""))

    if not active:
        color="#555577"; badge="Paused"
    elif status=="up":
        color="#6fcf97"; badge=f"OK ({ms//1000}s)"
    elif status=="down":
        color="#fc8181"; badge="Failed"
    else:
        color="#f6cc52"; badge="Pending"

    st.markdown(
        f"<div style='background:#1a2235;border-left:5px solid {color};"
        f"border:1px solid rgba(255,255,255,0.09);border-radius:10px;"
        f"padding:0.8rem 1.2rem;margin-bottom:0.4rem'>"
        f"<div style='display:flex;justify-content:space-between;flex-wrap:wrap;gap:0.5rem'>"
        f"<div><strong style='color:#e2e8f0'>{app.get('name','')}</strong>"
        f"<a href='{app.get('url','')}' target='_blank' "
        f"style='color:#8899b0;font-size:0.75rem;margin-left:0.5rem;text-decoration:none'>"
        f"{app.get('url','')[:55]}{'...' if len(app.get('url',''))>55 else ''}</a></div>"
        f"<div style='text-align:right;font-size:0.8rem'>"
        f"<span style='color:{color};font-weight:600'>{badge}</span>"
        + (f"<br><span style='color:#8899b0;font-size:0.75rem'>"
           f"Last: {checked} (Oslo) | Uptime: {uptime}% | {checks} visits</span>"
           if checked else "")
        + "</div></div></div>",
        unsafe_allow_html=True)

# Log
st.markdown("<br>", unsafe_allow_html=True)
st.markdown("<div style='font-size:0.72rem;font-weight:600;text-transform:uppercase;"
            "color:#00BCD4;margin-bottom:0.5rem;padding-bottom:0.3rem;"
            "border-bottom:1px solid rgba(255,255,255,0.09)'>Visit Log (last 40)</div>",
            unsafe_allow_html=True)

if logs:
    st.markdown(
        "<div style='display:grid;grid-template-columns:2fr 1.2fr 1fr 1fr 3fr;"
        "gap:0.5rem;padding:0.4rem 0.8rem;background:#232f45;border-radius:6px;"
        "font-size:0.73rem;font-weight:600;color:#8899b0;margin-bottom:0.2rem'>"
        "<span>App</span><span>Time (Oslo)</span><span>Status</span>"
        "<span>Duration</span><span>Notes</span></div>",
        unsafe_allow_html=True)
    for log in logs:
        lstat = log.get("status","unknown")
        lc    = "#6fcf97" if lstat=="up" else "#fc8181"
        lms   = log.get("response_ms",0) or 0
        st.markdown(
            f"<div style='display:grid;grid-template-columns:2fr 1.2fr 1fr 1fr 3fr;"
            f"gap:0.5rem;padding:0.3rem 0.8rem;background:#1a2235;"
            f"border-radius:4px;font-size:0.78rem;margin-bottom:2px'>"
            f"<span style='color:#e2e8f0'>{log.get('app_name','')}</span>"
            f"<span style='color:#8899b0'>{_utc_to_oslo(log.get('visited_at',''))}</span>"
            f"<span style='color:{lc};font-weight:600'>{lstat}</span>"
            f"<span style='color:#8899b0'>{lms//1000}s</span>"
            f"<span style='color:#8899b0;font-size:0.72rem'>"
            f"{(log.get('notes','') or '')[:60]}</span>"
            f"</div>", unsafe_allow_html=True)
else:
    st.info("No visits logged yet. Click Visit All Now to run the first round.")

st.markdown(
    f"<div style='text-align:center;color:#8899b0;font-size:0.73rem;margin-top:1rem'>"
    f"Oslo: {_now_oslo()} · Every {interval_h}h · &lt;30MB RAM</div>",
    unsafe_allow_html=True)
