"""
Octa Watchdog — Auto-timer that opens all apps at preset intervals.
"""
import streamlit as st
import streamlit.components.v1 as components
import json
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
    border:none!important;color:white!important;font-weight:700!important}
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
    now = datetime.now(timezone.utc).isoformat()
    for app in apps:
        try:
            db().table("watchdog_logs").insert({
                "app_id": app["id"], "app_name": app.get("name",""),
                "url": app.get("url",""), "visited_at": now,
                "status": "up", "response_ms": 0,
                "notes": "Auto-timer browser wake",
            }).execute()
            db().table("watchdog_apps").update({
                "last_checked": now, "last_status": "up",
                "last_response_ms": 0,
            }).eq("id", app["id"]).execute()
        except Exception:
            pass

apps = get_apps()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
<div style="text-align:center;padding:1rem 0 0.5rem">
<div style="font-size:2.5rem">shield</div>
<div style="font-weight:700;font-size:1rem;color:#e2e8f0">Octa Watchdog</div>
<div style="color:#8899b0;font-size:0.7rem">Auto-timer · Real browser tabs</div>
</div>""", unsafe_allow_html=True)
    st.markdown("---")
    st.markdown(
        "<div style='background:#1a2235;border-radius:8px;padding:0.7rem 0.9rem;"
        "font-size:0.82rem;color:#8899b0'>"
        "<strong style='color:#e2e8f0'>How to use:</strong><br>"
        "1. Set the interval below<br>"
        "2. Click <strong style='color:#00BCD4'>Start Auto-Timer</strong><br>"
        "3. Allow popups when browser asks<br>"
        "4. Keep this tab open — apps wake automatically<br><br>"
        "<strong style='color:#f6cc52'>Important:</strong> "
        "Keep this browser tab open. Timer runs in your browser."
        "</div>", unsafe_allow_html=True)
    st.markdown("---")
    if st.button("Admin Panel", use_container_width=True):
        st.switch_page("pages/admin.py")


# ── Main ──────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="background:linear-gradient(135deg,#1B2A4A,#2d4a7a);
padding:1.5rem 1.8rem;border-radius:12px;border-left:4px solid #00BCD4;margin-bottom:1.5rem">
<h1 style="margin:0;font-size:1.8rem;color:white">Octa Watchdog</h1>
<p style="margin:0.4rem 0 0;color:rgba(255,255,255,0.65);font-size:0.9rem">
Set a timer — your browser automatically opens all apps at each interval.
Keep this tab open and apps will never sleep.
</p></div>""", unsafe_allow_html=True)

if not apps:
    st.info("No apps registered. Go to Admin Panel to add your Streamlit app URLs.")
    st.stop()

urls_json = json.dumps([a["url"] for a in apps])
names_json = json.dumps([a.get("name","") for a in apps])
n_apps = len(apps)

# ── Auto-timer widget ─────────────────────────────────────────────────────────
timer_html = f"""
<!DOCTYPE html>
<html>
<head>
<style>
  body {{
    background: transparent;
    font-family: 'Segoe UI', sans-serif;
    color: #e2e8f0;
    margin: 0;
    padding: 0;
  }}
  .card {{
    background: #1a2235;
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 12px;
    padding: 1.5rem;
    margin-bottom: 1rem;
  }}
  .countdown {{
    font-size: 3rem;
    font-weight: 700;
    color: #00BCD4;
    text-align: center;
    letter-spacing: 2px;
    font-variant-numeric: tabular-nums;
    margin: 0.5rem 0;
  }}
  .countdown.warning {{ color: #f6cc52; }}
  .countdown.firing  {{ color: #fc8181; }}
  .label {{
    text-align: center;
    color: #8899b0;
    font-size: 0.82rem;
    margin-bottom: 1rem;
  }}
  .controls {{
    display: flex;
    gap: 0.8rem;
    align-items: center;
    flex-wrap: wrap;
    margin-bottom: 1rem;
  }}
  select, input[type=number] {{
    background: #232f45;
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 8px;
    color: #e2e8f0;
    padding: 0.5rem 0.8rem;
    font-size: 0.9rem;
  }}
  button {{
    border: none;
    border-radius: 8px;
    padding: 0.55rem 1.2rem;
    font-size: 0.9rem;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.2s;
  }}
  button:hover {{ opacity: 0.85; }}
  #btnStart  {{ background: linear-gradient(135deg,#00BCD4,#0097A7); color: white; }}
  #btnStop   {{ background: #232f45; color: #fc8181; border: 1px solid #fc818166; }}
  #btnNow    {{ background: #232f45; color: #6fcf97; border: 1px solid #6fcf9766; }}
  .log {{
    background: #0f1421;
    border-radius: 8px;
    padding: 0.7rem 0.9rem;
    font-size: 0.78rem;
    color: #8899b0;
    max-height: 140px;
    overflow-y: auto;
  }}
  .log-entry {{ margin-bottom: 3px; }}
  .log-entry.ok   {{ color: #6fcf97; }}
  .log-entry.info {{ color: #8899b0; }}
  .status-bar {{
    background: #232f45;
    border-radius: 8px;
    height: 6px;
    margin: 0.5rem 0 1rem;
    overflow: hidden;
  }}
  .status-fill {{
    height: 100%;
    background: linear-gradient(90deg,#00BCD4,#6fcf97);
    transition: width 1s linear;
    border-radius: 8px;
  }}
</style>
</head>
<body>

<div class="card">
  <!-- Interval selector -->
  <div class="controls">
    <label style="color:#8899b0;font-size:0.85rem">Wake every</label>
    <select id="intervalSelect">
      <option value="1800">30 minutes</option>
      <option value="3600">1 hour</option>
      <option value="7200" selected>2 hours</option>
      <option value="10800">3 hours</option>
      <option value="14400">4 hours</option>
      <option value="21600">6 hours</option>
    </select>

    <button id="btnStart" onclick="startTimer()">▶ Start Auto-Timer</button>
    <button id="btnStop"  onclick="stopTimer()"  style="display:none">⏹ Stop</button>
    <button id="btnNow"   onclick="wakeNow()">🚀 Wake Now</button>
  </div>

  <!-- Countdown display -->
  <div class="countdown" id="countdown">--:--:--</div>
  <div class="label" id="statusLabel">Timer not started · Click Start Auto-Timer</div>

  <!-- Progress bar -->
  <div class="status-bar">
    <div class="status-fill" id="progressBar" style="width:0%"></div>
  </div>

  <!-- App count badge -->
  <div style="text-align:center;color:#8899b0;font-size:0.82rem">
    {n_apps} apps registered · Opens one tab every 4 seconds when timer fires
  </div>
</div>

<!-- Log -->
<div class="card">
  <div style="color:#8899b0;font-size:0.73rem;font-weight:600;
              text-transform:uppercase;letter-spacing:0.08em;margin-bottom:0.5rem">
    Activity Log
  </div>
  <div class="log" id="logBox">
    <div class="log-entry info">Waiting to start...</div>
  </div>
</div>

<script>
const URLS  = {urls_json};
const NAMES = {names_json};

let timerInterval = null;   // countdown tick
let nextWakeTime  = null;   // Date object for next wake
let totalSeconds  = 0;

function addLog(msg, cls="info") {{
  const box  = document.getElementById("logBox");
  const now  = new Date().toLocaleTimeString("no-NO", {{hour12:false}});
  const div  = document.createElement("div");
  div.className = "log-entry " + cls;
  div.textContent = now + "  " + msg;
  box.insertBefore(div, box.firstChild);
  if (box.children.length > 50) box.removeChild(box.lastChild);
}}

function fmtTime(secs) {{
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  return String(h).padStart(2,"0") + ":" +
         String(m).padStart(2,"0") + ":" +
         String(s).padStart(2,"0");
}}

function openApps() {{
  addLog("Waking " + URLS.length + " apps...", "ok");
  let i = 0;
  function openNext() {{
    if (i < URLS.length) {{
      try {{
        window.open(URLS[i], "_blank");
        addLog("Opened: " + NAMES[i], "ok");
      }} catch(e) {{
        addLog("Could not open: " + NAMES[i] + " (allow popups!)", "info");
      }}
      i++;
      setTimeout(openNext, 4000);
    }} else {{
      addLog("Done. All " + URLS.length + " apps opened.", "ok");
    }}
  }}
  openNext();
}}

function wakeNow() {{
  openApps();
  if (timerInterval) {{
    // Reset the countdown after manual wake
    const secs = parseInt(document.getElementById("intervalSelect").value);
    scheduleNext(secs);
  }}
}}

function scheduleNext(seconds) {{
  totalSeconds  = seconds;
  nextWakeTime  = new Date(Date.now() + seconds * 1000);
}}

function startTimer() {{
  const secs = parseInt(document.getElementById("intervalSelect").value);
  totalSeconds = secs;
  scheduleNext(secs);

  // Clear old ticker if any
  if (timerInterval) clearInterval(timerInterval);

  timerInterval = setInterval(() => {{
    const remaining = Math.max(0, Math.round((nextWakeTime - Date.now()) / 1000));
    const cd = document.getElementById("countdown");
    cd.textContent = fmtTime(remaining);
    cd.className = "countdown" +
                   (remaining < 300 ? " warning" : "") +
                   (remaining === 0 ? " firing"  : "");

    // Progress bar
    const pct = Math.round((1 - remaining / totalSeconds) * 100);
    document.getElementById("progressBar").style.width = pct + "%";
    document.getElementById("statusLabel").textContent =
      "Next wake in " + fmtTime(remaining);

    if (remaining === 0) {{
      openApps();
      scheduleNext(totalSeconds);   // schedule next round
    }}
  }}, 1000);

  document.getElementById("btnStart").style.display = "none";
  document.getElementById("btnStop").style.display  = "inline-block";
  document.getElementById("statusLabel").textContent = "Timer running...";
  addLog("Auto-timer started · every " +
         document.getElementById("intervalSelect").options[
           document.getElementById("intervalSelect").selectedIndex].text, "ok");

  // Wake immediately on start
  openApps();
}}

function stopTimer() {{
  clearInterval(timerInterval);
  timerInterval = null;
  document.getElementById("btnStart").style.display = "inline-block";
  document.getElementById("btnStop").style.display  = "none";
  document.getElementById("countdown").textContent  = "--:--:--";
  document.getElementById("progressBar").style.width = "0%";
  document.getElementById("statusLabel").textContent = "Timer stopped";
  addLog("Timer stopped", "info");
}}
</script>
</body>
</html>
"""

components.html(timer_html, height=420, scrolling=False)

# ── App list ──────────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.markdown("<div style='font-size:0.72rem;font-weight:600;text-transform:uppercase;"
            "color:#00BCD4;margin-bottom:0.5rem;padding-bottom:0.3rem;"
            "border-bottom:1px solid rgba(255,255,255,0.09)'>Registered Apps</div>",
            unsafe_allow_html=True)

for app in apps:
    url    = app.get("url","")
    name   = app.get("name","")
    checks = app.get("check_count",0) or 0
    fails  = app.get("fail_count",0)  or 0
    uptime = round((1-fails/checks)*100,1) if checks>0 else 0
    last   = app.get("last_checked","")
    last_str = ""
    if last:
        try:
            dt = datetime.fromisoformat(last.replace("Z","+00:00"))
            last_str = dt.astimezone(OSLO).strftime("%d %b %H:%M")
        except Exception:
            pass

    st.markdown(
        f"<div style='background:#1a2235;border:1px solid rgba(255,255,255,0.09);"
        f"border-radius:10px;padding:0.6rem 1rem;margin-bottom:0.3rem;"
        f"display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap'>"
        f"<div><strong style='color:#e2e8f0'>{name}</strong> &nbsp;"
        f"<a href='{url}' target='_blank' "
        f"style='color:#8899b0;font-size:0.77rem;text-decoration:none'>{url}</a></div>"
        + (f"<span style='color:#8899b0;font-size:0.75rem'>"
           f"Last: {last_str} (Oslo) · Uptime: {uptime}%</span>" if last_str else "")
        + "</div>",
        unsafe_allow_html=True)

st.markdown(
    f"<div style='text-align:center;color:#8899b0;font-size:0.73rem;margin-top:1rem'>"
    f"Oslo: {_now_oslo()} · {n_apps} apps · Keep this tab open for auto-timer</div>",
    unsafe_allow_html=True)
