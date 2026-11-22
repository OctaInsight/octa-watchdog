"""Shared parts of the Watchdog app: sign-in, the database calls (watchdog_admin) and the look."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
import streamlit as st

from octa_auth import App, client, require_login, sidebar, token

APP = App(id="octa_watchdog", name="Octa Watchdog", family="science", url="https://octa-watchdog.streamlit.app/",
          tagline="Keeps the Octa apps, websites and databases awake, visiting from the country you choose", icon="🛡️")
OSLO = ZoneInfo("Europe/Oslo")
GITHUB_ACTIONS = "https://github.com/OctaInsight/octa-watchdog/actions/workflows/watchdog.yml"

# Countries on Proton VPN's free plan first; the others need a paid Proton plan (or another WireGuard VPN)
FREE = ["NL", "US", "JP", "PL", "RO", "NO", "CH", "SG", "MX", "CA"]
COUNTRIES = {
    "NL": "Netherlands", "US": "United States", "JP": "Japan", "PL": "Poland", "RO": "Romania", "NO": "Norway",
    "CH": "Switzerland", "SG": "Singapore", "MX": "Mexico", "CA": "Canada", "DE": "Germany", "FR": "France",
    "GB": "United Kingdom", "ES": "Spain", "IT": "Italy", "SE": "Sweden", "FI": "Finland", "DK": "Denmark",
    "AT": "Austria", "BE": "Belgium", "PT": "Portugal", "GR": "Greece", "IE": "Ireland", "AU": "Australia",
    "IN": "India", "BR": "Brazil", "ZA": "South Africa", "EG": "Egypt",
}

CSS = """<style>
html,body,[data-testid="stAppViewContainer"]{background:#0f1421!important;color:#e2e8f0!important}
[data-testid="stSidebar"]{background:#1B2A4A!important;border-right:3px solid #00BCD4!important}
[data-testid="stSidebar"] *{color:#e2e8f0!important}
h1,h2,h3,h4{color:#e2e8f0!important}
[data-testid="stButton"]>button,[data-testid="stFormSubmitButton"]>button{border-radius:8px!important}
[data-testid="stButton"]>button[kind="primary"],[data-testid="stFormSubmitButton"]>button[kind="primary"]{
  background:linear-gradient(135deg,#00BCD4,#0097A7)!important;border:none!important;color:white!important;font-weight:600!important}
.wd-head{background:linear-gradient(135deg,#1B2A4A,#2d4a7a);padding:1.2rem 1.6rem;border-radius:12px;
  border-left:4px solid #00BCD4;margin-bottom:1.2rem}
.wd-head h1{margin:0;font-size:1.6rem;color:white}
.wd-head p{margin:.3rem 0 0;color:rgba(255,255,255,.7);font-size:.9rem}
.wd-card{background:#1a2235;border:1px solid rgba(255,255,255,.09);border-radius:10px;padding:.9rem 1.1rem;margin-bottom:.6rem}
.wd-muted{color:#8899b0;font-size:.85rem}
</style>"""


def next_scheduled(now: datetime | None = None) -> datetime:
    """The next scheduled run: 00:17, 06:17, 12:17 or 18:17 UTC (the GitHub workflow's schedule)."""
    now = now or datetime.now(timezone.utc)
    t = now.replace(minute=17, second=0, microsecond=0, hour=(now.hour // 6) * 6)
    while t <= now:
        t += timedelta(hours=6)
    return t


# ---------------------------------------------------------------------------------------------------- the two databases
# Octa_projects holds the Watchdog's list, settings and runs ([octa_users] in the secrets, also used for sign-in).
# Data_and_Future ([data_and_future] in the secrets) gets a time stamp on every run and whenever this app is opened.
def second_db() -> tuple[str, str] | None:
    try:
        sec = st.secrets.get("data_and_future") or {}
        url, key = sec.get("url"), sec.get("key")
    except Exception:
        return None
    return (url, key) if url and key else None


def second_rpc(fn: str, **args) -> dict:
    cfg = second_db()
    if not cfg:
        raise WatchdogError("The second database is not in the secrets yet ([data_and_future] url and key).")
    url, key = cfg
    try:
        r = requests.post(f"{url.rstrip('/')}/rest/v1/rpc/{fn}", json=args, timeout=20,
                          headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    except requests.RequestException as e:
        raise WatchdogError(f"Data_and_Future could not be reached ({type(e).__name__}).") from None
    if r.status_code >= 400:
        raise WatchdogError(f"Data_and_Future answered with an error ({r.status_code}).")
    return r.json()


def ping_both(source: str = "app") -> dict:
    """Touch both databases now. Returns {"Octa_projects": "ok" | problem, "Data_and_Future": ...}."""
    out = {}
    try:
        api("overview", runs=1)
        out["Octa_projects"] = "ok"
    except WatchdogError as e:
        out["Octa_projects"] = str(e)
    try:
        r = second_rpc("watchdog_ping", p_source=source, p_country=None)
        out["Data_and_Future"] = "ok (reached less than a minute ago)" if r.get("skipped") else "ok"
    except WatchdogError as e:
        out["Data_and_Future"] = str(e)
    return out


def flag(code: str) -> str:
    if not code or len(code) != 2 or not code.isalpha():
        return "🌐"
    return chr(0x1F1E6 + ord(code[0].upper()) - 65) + chr(0x1F1E6 + ord(code[1].upper()) - 65)


def country_label(code: str | None) -> str:
    if not code or code == "NONE":
        return "🌐 No VPN (GitHub's own location)"
    return f"{flag(code)} {COUNTRIES.get(code, code)} ({code})" + ("" if code in FREE or code not in COUNTRIES else " · paid Proton plan")


def when(ts: str | None) -> str:
    if not ts:
        return "never"
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(OSLO).strftime("%d %b %H:%M")
    except ValueError:
        return ts[:16]


def page_setup(title: str, subtitle: str) -> dict:
    """Page config, look, sign-in (Octa admins only) and header. Returns the signed-in user."""
    st.set_page_config(page_title=title, page_icon="🛡️", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    user = require_login(APP)
    if user is None:
        st.error("The Octa user database is not set up. Add the [octa_users] section (url, key) to the Streamlit secrets.")
        st.stop()
    with st.sidebar:
        sidebar(APP)
        st.page_link("app.py", label="Dashboard", icon="🛡️")
        st.page_link("pages/admin.py", label="Apps, websites and setup", icon="⚙️")
    if user.get("role") != "admin":
        st.warning("The Watchdog is for Octa admins only.")
        st.stop()
    st.markdown(f"<div class='wd-head'><h1>{title}</h1><p>{subtitle}</p></div>", unsafe_allow_html=True)
    return user


class WatchdogError(Exception):
    pass


def api(action: str, **args) -> dict:
    r = client.rpc("watchdog_admin", p_token=token(), p={"action": action, **args})
    if not r or not r.get("ok"):
        raise WatchdogError((r or {}).get("error") or "The Watchdog database did not answer.")
    return r


def run(action: str, ok: str | None = None, **args) -> dict | None:
    try:
        r = api(action, **args)
    except WatchdogError as e:
        st.error(str(e))
        return None
    if ok:
        st.session_state["wd_flash"] = ok
    return r


def show_flash() -> None:
    msg = st.session_state.pop("wd_flash", None)
    if msg:
        st.success(msg)
