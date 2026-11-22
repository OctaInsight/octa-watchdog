"""Login, registration, password reset and the sidebar account box, shared by all Octa apps.

Typical use in an app:

    from octa_auth import App, require_login, sidebar
    APP = App(id="igneosuite", name="IgneoSuite", family="science", url="https://igneosuite.streamlit.app/")
    user = require_login(APP)        # shows the app's own login/register page until the user is signed in
    with st.sidebar:
        sidebar(APP)                 # Log in / Log out / Octa suite

The sign-in lives in the address bar (?session=…), so it survives a browser refresh and is carried to other
Octa apps through their links. It ends after 3 hours without activity.
"""
from __future__ import annotations
import base64
import html
import re
import time
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from . import client, mail

FAMILIES = {
    "cloudearthi": "CloudEARTHi-Octa apps",
    "science": "Octa scientific apps",
    "education": "Innovation, Education and Training apps",
    "games": "Octa games",
}
FAMILY_HELP = {
    "cloudearthi": "Proposals and funded projects: partners, proposals, KPIs, project progress, finances, risks, hours and tasks",
    "science": "Open scientific tools, such as IgneoSuite for igneous geochemistry",
    "education": "Matchmaking and tools for innovation, education and training projects and events",
    "games": "Octa games (coming soon)",
}
RECHECK_SECONDS = 60
_LOGO = Path(__file__).with_name("octa_logo.png")
_USERNAME = re.compile(r"^[A-Za-z0-9._-]{3,40}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


@dataclass
class App:
    id: str                 # id in User_apps ("igneosuite", "octa_kpi", …) or "portal"
    name: str
    family: str = "science"  # science | cloudearthi | games
    url: str = ""            # public address of this app (used in email links)
    tagline: str = ""
    icon: str = "🔷"


def _state() -> dict:
    return st.session_state.setdefault("_octa_auth", {})


def _app_id(app: App):
    return None if app.id == "portal" else app.id


SUITE_URL = "https://octa-suite.streamlit.app/"


def portal_url() -> str:
    return client.setting("portal_url", "") or SUITE_URL


def _same_site(a: str, b: str) -> bool:
    norm = lambda u: (u or "").strip().lower().split("?")[0].rstrip("/")  # noqa: E731
    return bool(a) and norm(a) == norm(b)


def suite_link(app: App) -> str:
    """The Octa suite's address for this app's buttons. If the secrets point portal_url at this app itself (an easy
    copy-paste slip), the buttons would just reopen this app, so the suite's own address is used instead."""
    u = portal_url()
    return SUITE_URL if app.id != "portal" and _same_site(u, app.url) else u


def _base_url(app: App) -> str:
    u = app.url or (portal_url() if app.id == "portal" else "")
    return u.rstrip("/") + "/" if u else ""


def token() -> str | None:
    return _state().get("token")


def with_session(url: str) -> str:
    """Address of another Octa app that keeps the user signed in."""
    t = token()
    if not url or not t:
        return url
    return f"{url}{'&' if '?' in url else '?'}session={t}"


def display_name(u: dict) -> str:
    n = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x)
    return n or u.get("username", "")


def flash(kind: str, msg: str):
    _state()["flash"] = (kind, msg)


def _show_flash():
    f = _state().pop("flash", None)
    if f:
        getattr(st, f[0], st.info)(f[1])


# ------------------------------------------------------------------------------------------------ session
def _set_session(tok: str, user: dict):
    s = _state()
    s.update(token=tok, user=user, checked=time.time())
    s.pop("want_login", None)
    st.query_params["session"] = tok


def _clear_session():
    s = _state()
    for k in ("token", "user", "checked"):
        s.pop(k, None)
    if "session" in st.query_params:
        del st.query_params["session"]


def current_user(app: App) -> dict | None:
    """The signed-in user (dict) or None. Checks the session with the database at most once a minute;
    every check keeps the session alive for another 3 hours."""
    if not client.enabled():
        return None
    s = _state()
    qtok = st.query_params.get("session")
    tok = s.get("token")
    if qtok and qtok != tok:
        tok = qtok
    if not tok:
        return None
    if tok == s.get("token") and s.get("user") and time.time() - s.get("checked", 0) < RECHECK_SECONDS:
        if st.query_params.get("session") != tok:
            st.query_params["session"] = tok
        return s["user"]
    try:
        r = client.session(tok, _app_id(app))
    except client.OctaError as e:
        if s.get("user") and tok == s.get("token"):
            return s["user"]          # database briefly unreachable: keep working
        st.warning(str(e))
        return None
    if r and r.get("ok"):
        _set_session(tok, r["user"])
        return r["user"]
    _clear_session()
    flash("info", r.get("error", "Please log in again.") if r else "Please log in again.")
    return None


def logout(app: App):
    tok = token()
    if tok:
        try:
            client.logout(tok, _app_id(app))
        except client.OctaError:
            pass
    _clear_session()
    flash("success", "You are logged out.")


def has_access(user: dict, app: App) -> bool:
    return app.id == "portal" or app.id in (user.get("apps") or []) or not _known_app(app.id)


@st.cache_data(ttl=600, show_spinner=False)
def _catalogue_public():
    try:
        return client.catalogue(None) or {}
    except client.OctaError:
        return {}


def _known_app(app_id: str) -> bool:
    return any(a["id"] == app_id for a in _catalogue_public().get("apps", []))


# ------------------------------------------------------------------------------------------------ pages
def _header(app: App, subtitle: str = ""):
    if _LOGO.exists():
        b64 = base64.b64encode(_LOGO.read_bytes()).decode()
        st.markdown(f"<img src='data:image/png;base64,{b64}' alt='Octa Insight' style='width:120px;height:auto'>",
                    unsafe_allow_html=True)
    st.markdown(f"## {app.icon} {html.escape(app.name)}")
    if app.tagline:
        st.markdown(f"<span style='color:#52514e'>{html.escape(app.tagline)}</span>", unsafe_allow_html=True)
    if subtitle:
        st.caption(subtitle)


def require_login(app: App, required: bool = True) -> dict | None:
    """Return the signed-in user. If nobody is signed in, show this app's login page and stop the script
    (unless `required` is False and the user did not ask to log in). Returns None when the user database
    is not set up (e.g. a local copy without secrets), so the app still runs."""
    if not client.enabled():
        return None
    if st.query_params.get("reset"):
        _page_wrap(app, _reset_page)
        st.stop()
    user = current_user(app)
    if user:
        if user.get("force_password_change"):
            _page_wrap(app, lambda a: _force_change_page(a, user))
            st.stop()
        if not has_access(user, app):
            _page_wrap(app, lambda a: _no_access_page(a, user))
            st.stop()
        return user
    if not required and not _state().get("want_login") and not st.query_params.get("register"):
        return None
    _page_wrap(app, auth_page)
    st.stop()


def _page_wrap(app: App, fn):
    _, mid, _ = st.columns([1, 2.2, 1])
    with mid:
        fn(app)


def auth_page(app: App):
    """Login / register / forgot page for this app (or for the common Octa suite)."""
    _header(app, "One Octa account for all Octa Insight apps." if app.id != "portal" else
            "Log in or create your Octa account to reach all Octa Insight apps.")
    _show_flash()
    s = _state()
    if st.query_params.get("register"):
        s["view"] = "Create account"
        del st.query_params["register"]
    view = st.segmented_control("Account", ["Log in", "Create account", "Forgot username or password"],
                                default=s.get("view", "Log in"), key=f"octa_view_{s.get('view_n', 0)}",
                                label_visibility="collapsed")
    view = view or "Log in"
    if view == "Log in":
        _login_form(app)
    elif view == "Create account":
        _register_form(app)
    else:
        _forgot_form(app)
    if app.id != "portal":
        st.caption(f"Other Octa apps: [Octa suite]({suite_link(app)})")


def _go(view: str):
    s = _state()
    s["view"] = view
    s["view_n"] = s.get("view_n", 0) + 1     # new widget key so the default applies


def _login_form(app: App):
    with st.form("octa_login"):
        who = st.text_input("Email or username", autocomplete="username")
        pw = st.text_input("Password", type="password", autocomplete="current-password")
        ok = st.form_submit_button("Log in", type="primary", use_container_width=True)
    if ok:
        if not who.strip() or not pw:
            st.error("Please enter your email or username and your password.")
            return
        try:
            with st.spinner("Logging in…"):
                r = client.login(who.strip(), pw, _app_id(app))
        except client.OctaError as e:
            st.error(str(e))
            return
        if not r.get("ok"):
            st.error(r.get("error", "Log in failed."))
            return
        _set_session(r["token"], r["user"])
        st.rerun()
    c1, c2 = st.columns(2)
    c1.button("New here? Create an account", on_click=_go, args=("Create account",), use_container_width=True)
    c2.button("Forgot username or password?", on_click=_go, args=("Forgot username or password",),
              use_container_width=True)


def _cloud_apps():
    return [a for a in _catalogue_public().get("apps", []) if a["family"] == "cloudearthi"]


def _register_form(app: App):
    family = app.family
    if app.id == "portal":
        family = st.radio("Which Octa apps are you mainly here for?", list(FAMILIES), format_func=FAMILIES.get,
                          captions=[FAMILY_HELP[f] for f in FAMILIES], key="octa_reg_family")
    req = family in ("science", "cloudearthi", "education")
    with st.form("octa_register"):
        c1, c2 = st.columns(2)
        first = c1.text_input("First name *")
        last = c2.text_input("Family name *")
        email = c1.text_input("Email *", autocomplete="email")
        username = c2.text_input("Username *", help="3–40 letters, numbers, dots, dashes or underscores.",
                                 autocomplete="username")
        pw = c1.text_input("Password *", type="password", help="At least 8 characters.", autocomplete="new-password")
        pw2 = c2.text_input("Repeat password *", type="password", autocomplete="new-password")
        affiliation = st.text_input("Affiliation (university, institute or company)" + (" *" if req else ""))
        c3, c4 = st.columns(2)
        country = c3.text_input("Country")
        job = c4.text_input("Position / job title")
        profile, extra = {}, {}
        if family == "science":
            st.markdown("**Scientific profile**")
            c5, c6 = st.columns(2)
            extra["orcid"] = c5.text_input("ORCID iD", placeholder="0000-0000-0000-0000")
            profile["research_field"] = c6.text_input("Research field", placeholder="e.g. igneous petrology")
            extra["website"] = st.text_input("Web page")
            extra["biography"] = st.text_area("Short profile", max_chars=2000, height=90)
        elif family == "cloudearthi":
            st.markdown("**Social media**")
            c5, c6 = st.columns(2)
            profile["linkedin"] = c5.text_input("LinkedIn")
            profile["researchgate"] = c6.text_input("ResearchGate")
            profile["x"] = c5.text_input("X (Twitter)")
            profile["other_social"] = c6.text_input("Other (web page, Mastodon, …)")
            st.markdown("**Institutes and projects**")
            profile["institutes"] = st.text_area("Affiliated institutes (one per line)", height=80)
            profile["projects"] = st.text_area("Proposals or projects you work on (one per line)", height=80)
            apps = _cloud_apps()
            names = {a["id"]: f"{a['icon']} {a['name']}" + ("" if a["status"] == "live" else " (coming soon)")
                     for a in apps}
            default = [app.id] if app.id in names else []
            asked = st.multiselect("Apps you need access to (an Octa administrator approves each one)",
                                   list(names), default=default, format_func=names.get)
        elif family == "education":
            st.markdown("**Innovation, education and training profile**")
            c5, c6 = st.columns(2)
            profile["organisation_type"] = c5.selectbox(
                "Type of organisation", ["", "University or school", "Research institute", "Company or start-up",
                                         "Public body", "NGO or association", "Other"])
            profile["linkedin"] = c6.text_input("LinkedIn")
            profile["interests"] = st.text_area("Topics you work on or want partners for (one per line)", height=80)
        elif family == "games":
            profile["nickname"] = st.text_input("Player name")
        ok = st.form_submit_button("Create account", type="primary", use_container_width=True)
    if not ok:
        return
    problems = []
    if not first.strip() or not last.strip():
        problems.append("first name and family name")
    if not _EMAIL.match(email.strip()):
        problems.append("a valid email")
    if not _USERNAME.match(username.strip()):
        problems.append("a username of 3–40 letters, numbers, dots, dashes or underscores")
    if len(pw) < 8:
        problems.append("a password of at least 8 characters")
    elif pw != pw2:
        problems.append("the same password twice")
    if req and not affiliation.strip():
        problems.append("your affiliation")
    if problems:
        st.error("Please give " + ", ".join(problems) + ".")
        return
    for k in ("institutes", "projects", "interests"):
        if k in profile:
            profile[k] = [x.strip() for x in profile[k].splitlines() if x.strip()]
    profile = {k: (v.strip() if isinstance(v, str) else v) for k, v in profile.items() if v}
    fields = dict(email=email.strip(), username=username.strip(), password=pw, first_name=first.strip(),
                  last_name=last.strip(), affiliation=affiliation.strip(), country=country.strip(),
                  job_title=job.strip(), family=family, profile=profile, app=_app_id(app) or "",
                  **{k: v.strip() for k, v in extra.items() if v and v.strip()})
    try:
        with st.spinner("Creating your account…"):
            r = client.register(fields)
            if r.get("ok") and family == "cloudearthi":
                for a in asked:
                    client.request_access(r["token"], a)
    except client.OctaError as e:
        st.error(str(e))
        return
    if not r.get("ok"):
        st.error(r.get("error", "The account could not be created."))
        return
    _welcome_email(app, r["user"])
    _set_session(r["token"], r["user"])
    msg = f"Welcome, {display_name(r['user'])}! Your Octa account is ready."
    if family == "cloudearthi" and asked:
        msg += " Your access requests were sent to the Octa administrators."
    flash("success", msg)
    st.rerun()


def _welcome_email(app: App, u: dict):
    if not mail.enabled():
        return
    link = suite_link(app)
    try:
        mail.send(u["email"], "Welcome to Octa Insight",
                  [f"Dear {html.escape(display_name(u))},",
                   f"your Octa account was created in {html.escape(app.name)}. "
                   f"Your username is <b>{html.escape(u['username'])}</b>; you can also log in with this email address.",
                   "The same account opens every Octa Insight app you have access to."],
                  button=("Open the Octa suite", link) if link else None,
                  after=["If you did not create this account, please reply to this email."])
    except Exception:
        pass


def _forgot_form(app: App):
    st.write("Enter the email address of your account. We will email you your username and a link to choose "
             "a new password (and, if you like, a new username).")
    with st.form("octa_forgot"):
        email = st.text_input("Email", autocomplete="email")
        ok = st.form_submit_button("Send me an email", type="primary", use_container_width=True)
    st.button("Back to log in", on_click=_go, args=("Log in",))
    if not ok:
        return
    email = email.strip()
    if not _EMAIL.match(email):
        st.error("Please enter a valid email address.")
        return
    if not mail.enabled() or client.server_key_looks_unset():
        missing = (["the [email] settings"] if not mail.enabled() else []) + \
                  (["the server_key in [octa_users]"] if client.server_key_looks_unset() else [])
        st.error(f"Password reset by email is not set up for this app yet ({' and '.join(missing)} missing in its "
                 "Streamlit secrets). Please contact octainsight@gmail.com.")
        return
    base = _base_url(app)
    try:
        with st.spinner("Sending…"):
            r = client.reset_request(email, _app_id(app) or "")
            if not r.get("ok"):
                st.error(r.get("error", "The request failed.") if r.get("error") != "not allowed" else
                         "Password reset is not set up correctly for this app: the server_key in its Streamlit "
                         "secrets is not the same as the Octa suite's. Copy it exactly from the Octa suite app's "
                         "secrets ([octa_users] server_key).")
                return
            if r.get("exists"):
                link = f"{base}?reset={r['token']}"
                mail.send(r["email"], f"Your Octa account: username and new password",
                          [f"Dear {html.escape(r.get('first_name') or r['username'])},",
                           f"you (or someone using your email address) asked for help with your Octa account in "
                           f"{html.escape(app.name)}.",
                           f"Your username is <b>{html.escape(r['username'])}</b>.",
                           "To choose a new password, or a new username, open this link within one hour:"],
                          button=("Choose a new password", link),
                          after=["If you did not ask for this, you can ignore this email; nothing changes."])
            else:
                mail.send(email, "Octa Insight: no account with this email",
                          [f"Someone asked to reset the password of an Octa account for {html.escape(email)} in "
                           f"{html.escape(app.name)}, but there is no Octa account with this email address.",
                           "If you would like one, you can register here:"],
                          button=("Create an Octa account", f"{base}?register=1"),
                          after=["If you did not ask for this, you can ignore this email."])
    except client.OctaError as e:
        st.error(str(e))
        return
    except mail.MailError as e:
        st.error(f"The email could not be sent. {e} If this keeps happening, please contact octainsight@gmail.com.")
        return
    except Exception:
        st.error("The email could not be sent. Please try again later or contact octainsight@gmail.com.")
        return
    st.success(f"We have sent an email to **{email}**. Please check your inbox (and the spam folder).")


def _reset_page(app: App):
    _header(app, "Choose a new password")
    tok = st.query_params.get("reset", "")
    try:
        r = client.reset_check(tok)
    except client.OctaError as e:
        st.error(str(e))
        return
    if not r.get("ok"):
        st.error(r.get("error"))
        if st.button("Ask for a new link"):
            del st.query_params["reset"]
            _go("Forgot username or password")
            st.rerun()
        return
    st.info(f"Account: **{r['email']}**  \nYour username: **{r['username']}**")
    with st.form("octa_reset"):
        new_user = st.text_input("New username (optional)", placeholder=f"leave empty to keep {r['username']}")
        pw = st.text_input("New password", type="password", help="At least 8 characters.", autocomplete="new-password")
        pw2 = st.text_input("Repeat the new password", type="password", autocomplete="new-password")
        ok = st.form_submit_button("Save", type="primary", use_container_width=True)
    if not ok:
        return
    if len(pw) < 8:
        st.error("The password needs at least 8 characters.")
        return
    if pw != pw2:
        st.error("The two passwords are not the same.")
        return
    if new_user.strip() and not _USERNAME.match(new_user.strip()):
        st.error("Username: 3–40 letters, numbers, dots, dashes or underscores.")
        return
    try:
        out = client.reset_complete(tok, pw, new_user.strip())
    except client.OctaError as e:
        st.error(str(e))
        return
    if not out.get("ok"):
        st.error(out.get("error"))
        return
    del st.query_params["reset"]
    _clear_session()
    _go("Log in")
    flash("success", f"Saved. Please log in with your username **{out['username']}** and the new password.")
    st.rerun()


def _force_change_page(app: App, user: dict):
    _header(app, "Please choose a new password before you continue.")
    with st.form("octa_force"):
        old = st.text_input("Current password", type="password", autocomplete="current-password")
        pw = st.text_input("New password", type="password", help="At least 8 characters.", autocomplete="new-password")
        pw2 = st.text_input("Repeat the new password", type="password", autocomplete="new-password")
        ok = st.form_submit_button("Save", type="primary")
    if ok:
        if pw != pw2 or len(pw) < 8:
            st.error("Use the same new password twice, with at least 8 characters.")
            return
        r = client.change_password(token(), old, pw)
        if not r.get("ok"):
            st.error(r.get("error"))
            return
        _state()["checked"] = 0
        flash("success", "Your password was changed.")
        st.rerun()


def _no_access_page(app: App, user: dict):
    _header(app)
    st.warning(f"Your account (**{user['username']}**) does not have access to {app.name} yet.")
    if st.button("Ask an Octa administrator for access", type="primary"):
        try:
            r = client.request_access(token(), app.id)
            st.success("Your request was sent." if r.get("ok") else r.get("error"))
        except client.OctaError as e:
            st.error(str(e))
    st.link_button("Go to the Octa suite", with_session(suite_link(app)))
    if st.button("Log out"):
        logout(app)
        st.rerun()


# ------------------------------------------------------------------------------------------------ sidebar
def sidebar(app: App):
    """Account box for the sidebar: who is signed in, and Log in / Log out / Octa suite buttons."""
    if not client.enabled():
        return
    s = _state()
    u = s.get("user")
    if u:
        st.markdown(f"<div style='font-size:0.9rem'>👤 <b>{html.escape(display_name(u))}</b>"
                    f"<br><span style='color:#52514e;font-size:0.8rem'>{html.escape(u.get('username', ''))}"
                    f"</span></div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    if u:
        if c1.button("Log out", key="octa_logout", use_container_width=True):
            logout(app)
            st.rerun()
    else:
        if c1.button("Log in", key="octa_login_btn", use_container_width=True):
            s["want_login"] = True
            st.rerun()
    if app.id != "portal":
        c2.link_button("Octa suite", with_session(suite_link(app)), use_container_width=True)
