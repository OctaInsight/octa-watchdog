"""
Octa Watchdog — Opens all Streamlit apps as real browser tabs.
Click ONE button → your browser opens every app → they wake up.
No server browser, no memory issues.
"""
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from supabase import create_client, Client

OSLO = ZoneInfo("Europe/Oslo")

def _now_oslo():
    return datetime.now(OSLO).strftime("%d %b %H:%M:%S")

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
    border:1px solid rgba(255,255,255,0.09)!important;
    color:#e2e8f0!important;border-radius:8px!important}
[data-testid="stButton"]>button[kind="primary"]{
    background:linear-gradient(135deg,#00BCD4,#0097A7)!important;
    border:none!important;color:white!important;
    font-weight:700!important;font-size:1.1rem!important;
    padding:0.8rem!important}
input,textarea{background:#232f45!important;border-radius:8px!important;color:#e2e8f0!important}
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def db() -> Client:
    return create_client(
        st.secrets["supabase"]["url"],
        st.secrets["supabase"]["key"]
    )

def get_apps() -> list:
    try:
        return db().table("watchdog_apps").select("*")                    .eq("is_active", True).order("name").execute().data or []
    except Exception:
        return []

def log_wake(apps: list):
    """Record the wake attempt in Supabase."""
    now = datetime.now(timezone.utc).isoformat()
    for app in apps:
        try:
            db().table("watchdog_logs").insert({
                "app_id":     app["id"],
                "app_name":   app.get("name",""),
                "url":        app.get("url",""),
                "visited_at": now,
                "status":     "up",
                "response_ms":0,
                "notes":      "Opened in real browser by user",
            }).execute()
            db().table("watchdog_apps").update({
                "last_checked":     now,
                "last_status":      "up",
                "last_response_ms": 0,
            }).eq("id", app["id"]).execute()
        except Exception:
            pass


# ── Load ──────────────────────────────────────────────────────────────────────

apps = get_apps()

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
<div style="text-align:center;padding:1rem 0 0.5rem">
<div style="font-size:2.5rem">shield</div>
<div style="font-weight:700;font-size:1rem;color:#e2e8f0">Octa Watchdog</div>
<div style="color:#8899b0;font-size:0.7rem">Real browser tabs</div>
</div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown(
        f"<div style='background:#1a2235;border-radius:8px;padding:0.7rem 0.9rem;"
        f"font-size:0.83rem;color:#8899b0'>"
        f"<strong style='color:#e2e8f0'>How it works:</strong><br>"
        f"Click <strong style='color:#00BCD4'>Wake All Apps</strong> — "
        f"your browser opens each app in a new tab. "
        f"Real visit, real WebSocket, Streamlit stays awake.<br><br>"
        f"<strong style='color:#e2e8f0'>To automate:</strong><br>"
        f"Bookmark this page. Open it every few hours.<br>"
        f"Or use UptimeRobot to ping this page — then click manually when needed."
        f"</div>", unsafe_allow_html=True)

    st.markdown("---")
    if st.button("Admin Panel", use_container_width=True):
        st.switch_page("pages/admin.py")


# ── Main ──────────────────────────────────────────────────────────────────────

st.markdown("""
<div style="background:linear-gradient(135deg,#1B2A4A,#2d4a7a);
padding:1.5rem 1.8rem;border-radius:12px;border-left:4px solid #00BCD4;margin-bottom:1.5rem">
<h1 style="margin:0;font-size:1.8rem;color:white">Octa Watchdog</h1>
<p style="margin:0.4rem 0 0;color:rgba(255,255,255,0.65);font-size:0.95rem">
Click the button below — your browser opens every app in a new tab.
That is a real visit. Streamlit sees real viewers. Apps stay awake.
</p></div>""", unsafe_allow_html=True)

if not apps:
    st.info("No apps registered. Go to Admin Panel to add your Streamlit app URLs.")
    st.stop()

# ── THE BIG BUTTON ────────────────────────────────────────────────────────────

st.markdown(f"<p style='color:#8899b0;font-size:0.9rem;margin-bottom:0.5rem'>"
            f"{len(apps)} apps registered · "
            f"Opens one tab every 5 seconds so your browser doesn't block them."
            f"</p>", unsafe_allow_html=True)

wake_clicked = st.button(
    f"🚀 Wake All {len(apps)} Apps — Open in Browser Tabs",
    type="primary",
    use_container_width=True
)

if wake_clicked:
    # Log to Supabase
    log_wake(apps)

    # Build JavaScript that opens each URL in a new tab, one every 5 seconds
    urls_list = [a["url"] for a in apps]
    urls_js   = str(urls_list).replace("'", '"')

    js = f"""
    <script>
    const urls = {urls_js};
    let i = 0;

    function openNext() {{
        if (i < urls.length) {{
            window.open(urls[i], '_blank');
            i++;
            setTimeout(openNext, 5000);
        }}
    }}

    // Start immediately (user just clicked = user gesture = popups allowed)
    openNext();
    </script>
    <div style="background:#6fcf9722;border:1px solid #6fcf97;border-radius:8px;
    padding:0.8rem 1.2rem;color:#6fcf97;font-weight:600;font-size:0.95rem">
    Opening {len(apps)} apps · one tab every 5 seconds...<br>
    <span style="font-size:0.8rem;font-weight:400;color:#8899b0">
    Allow popups if your browser asks. Total time: ~{len(apps)*5} seconds.
    </span>
    </div>
    """
    components.html(js, height=80)

    st.success(f"✅ Logged {len(apps)} wake attempts at {_now_oslo()} (Oslo)")
    st.info("💡 Allow popups if your browser shows a blocked popup notification.")

st.markdown("<br>", unsafe_allow_html=True)

# ── App list with individual open buttons ─────────────────────────────────────
st.markdown("<div style='font-size:0.72rem;font-weight:600;text-transform:uppercase;"
            "color:#00BCD4;margin-bottom:0.6rem;padding-bottom:0.3rem;"
            "border-bottom:1px solid rgba(255,255,255,0.09)'>"
            "Registered Apps</div>", unsafe_allow_html=True)

for app in apps:
    url     = app.get("url","")
    name    = app.get("name","")
    checked = app.get("last_checked","")
    checks  = app.get("check_count",0) or 0
    fails   = app.get("fail_count",0)  or 0
    uptime  = round((1-fails/checks)*100,1) if checks>0 else 0

    checked_str = ""
    if checked:
        try:
            from zoneinfo import ZoneInfo
            dt = datetime.fromisoformat(checked.replace("Z","+00:00"))
            checked_str = dt.astimezone(ZoneInfo("Europe/Oslo")).strftime("%d %b %H:%M")
        except Exception:
            pass

    c1, c2 = st.columns([6, 1])
    with c1:
        st.markdown(
            f"<div style='background:#1a2235;border:1px solid rgba(255,255,255,0.09);"
            f"border-radius:10px;padding:0.7rem 1.1rem'>"
            f"<strong style='color:#e2e8f0'>{name}</strong> &nbsp;"
            f"<a href='{url}' target='_blank' "
            f"style='color:#8899b0;font-size:0.78rem;text-decoration:none'>{url}</a>"
            + (f"<br><span style='color:#8899b0;font-size:0.73rem'>"
               f"Last opened: {checked_str} (Oslo) · Uptime: {uptime}%</span>"
               if checked_str else "")
            + "</div>", unsafe_allow_html=True)
    with c2:
        # Individual open button using JS
        if st.button("Open", key=f"open_{app['id']}"):
            components.html(
                f"<script>window.open('{url}', '_blank');</script>",
                height=0
            )

# ── Instructions ──────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.markdown(
    f"<div style='background:#1a2235;border-left:4px solid #f6cc52;"
    f"border-radius:8px;padding:0.9rem 1.2rem;font-size:0.85rem'>"
    f"<strong style='color:#f6cc52'>How to use:</strong><br>"
    f"1. Open this watchdog page<br>"
    f"2. Click <strong>Wake All Apps</strong><br>"
    f"3. Allow popups in your browser if asked<br>"
    f"4. All apps open as tabs — Streamlit sees real visitors<br>"
    f"5. Leave tabs open for a few minutes, then close<br><br>"
    f"<strong style='color:#f6cc52'>To automate:</strong> "
    f"Set a reminder every 5-6 hours to open this page and click the button. "
    f"Or add to UptimeRobot so you get an alert if apps sleep."
    f"</div>", unsafe_allow_html=True)

st.markdown(
    f"<div style='text-align:center;color:#8899b0;font-size:0.73rem;margin-top:1rem'>"
    f"Oslo: {_now_oslo()} · {len(apps)} apps registered</div>",
    unsafe_allow_html=True)
