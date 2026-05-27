"""Octa Watchdog — Admin Panel."""
import streamlit as st
from supabase import create_client

st.set_page_config(
    page_title="Watchdog Admin",
    page_icon="⚙️",
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
input,textarea{background:#232f45!important;border-radius:8px!important;
    color:#e2e8f0!important;border:1px solid rgba(255,255,255,0.09)!important}
[data-testid="stButton"]>button{background:#232f45!important;
    border:1px solid rgba(255,255,255,0.09)!important;color:#e2e8f0!important;border-radius:8px!important}
[data-testid="stButton"]>button[kind="primary"]{
    background:linear-gradient(135deg,#00BCD4,#0097A7)!important;
    border:none!important;color:white!important;font-weight:600!important}
[data-testid="stExpander"]{background:#1a2235!important;
    border:1px solid rgba(255,255,255,0.09)!important;border-radius:10px!important}
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def db():
    return create_client(
        st.secrets["supabase"]["url"],
        st.secrets["supabase"]["key"]
    )

with st.sidebar:
    st.markdown("""
<div style="text-align:center;padding:1rem 0 0.5rem">
<div style="font-size:2.5rem">⚙️</div>
<div style="font-weight:700;font-size:1rem;color:#e2e8f0">Admin Panel</div>
</div>""", unsafe_allow_html=True)
    st.markdown("---")
    if st.button("← Dashboard", use_container_width=True):
        st.switch_page("app.py")

st.markdown("""
<div style="background:linear-gradient(135deg,#1B2A4A,#2d4a7a);
padding:1.2rem 1.8rem;border-radius:12px;border-left:4px solid #00BCD4;margin-bottom:1.5rem">
<h1 style="margin:0;font-size:1.6rem;color:white">⚙️ Watchdog Admin Panel</h1>
<p style="margin:0.2rem 0 0;color:rgba(255,255,255,0.65);font-size:0.88rem">
Add, edit and manage monitored Streamlit apps
</p></div>""", unsafe_allow_html=True)

# ── Add new app ───────────────────────────────────────────────────────────────
st.markdown("<div style='font-size:0.72rem;font-weight:600;letter-spacing:0.08em;"
            "text-transform:uppercase;color:#00BCD4;margin-bottom:0.5rem;"
            "padding-bottom:0.3rem;border-bottom:1px solid rgba(255,255,255,0.09)'>"
            "➕ Add New App</div>", unsafe_allow_html=True)

with st.form("add_app_form", clear_on_submit=True):
    c1, c2 = st.columns([2, 4])
    with c1:
        new_name = st.text_input("App Name *",
                                  placeholder="e.g. Octa Proposals")
    with c2:
        new_url  = st.text_input("Streamlit URL *",
                                  placeholder="https://your-app.streamlit.app")

    if st.form_submit_button("➕ Add App", type="primary", use_container_width=True):
        if not new_name.strip() or not new_url.strip():
            st.error("❌ Both name and URL are required.")
        else:
            url = new_url.strip()
            if not url.startswith("http"):
                url = "https://" + url
            try:
                db().table("watchdog_apps").insert({
                    "name": new_name.strip(),
                    "url":  url,
                    "is_active": True,
                }).execute()
                st.success(f"✅ '{new_name}' added!")
                st.rerun()
            except Exception as e:
                if "unique" in str(e).lower():
                    st.error("❌ This URL is already registered.")
                else:
                    st.error(f"❌ {e}")

st.markdown("<br>", unsafe_allow_html=True)

# ── Bulk add ──────────────────────────────────────────────────────────────────
with st.expander("📋 Bulk Add (paste multiple URLs)"):
    st.markdown("<p style='color:#8899b0;font-size:0.84rem'>"
                "Paste one URL per line. Name will be auto-set from the URL.</p>",
                unsafe_allow_html=True)
    bulk_text = st.text_area("URLs (one per line)", height=150,
                              placeholder="https://app1.streamlit.app\nhttps://app2.streamlit.app")
    if st.button("Add All", type="primary", key="bulk_add"):
        lines = [l.strip() for l in bulk_text.splitlines() if l.strip()]
        added = 0
        for url in lines:
            if not url.startswith("http"):
                url = "https://" + url
            name = url.replace("https://","").replace(".streamlit.app","").replace("-"," ").title()
            try:
                db().table("watchdog_apps").insert(
                    {"name": name, "url": url, "is_active": True}
                ).execute()
                added += 1
            except Exception:
                pass
        st.success(f"✅ Added {added} / {len(lines)} apps.")
        st.rerun()

st.markdown("<br>", unsafe_allow_html=True)

# ── Manage existing apps ──────────────────────────────────────────────────────
st.markdown("<div style='font-size:0.72rem;font-weight:600;letter-spacing:0.08em;"
            "text-transform:uppercase;color:#00BCD4;margin-bottom:0.5rem;"
            "padding-bottom:0.3rem;border-bottom:1px solid rgba(255,255,255,0.09)'>"
            "📋 Registered Apps</div>", unsafe_allow_html=True)

try:
    apps = db().table("watchdog_apps").select("*").order("name").execute().data or []
except Exception:
    apps = []

if not apps:
    st.info("No apps registered yet. Add your first app above.")
else:
    # Summary
    active = sum(1 for a in apps if a.get("is_active"))
    st.markdown(
        f"<div style='color:#8899b0;font-size:0.83rem;margin-bottom:0.8rem'>"
        f"{len(apps)} apps registered · {active} active</div>",
        unsafe_allow_html=True)

    for app in apps:
        aid    = app["id"]
        name   = app.get("name","")
        url    = app.get("url","")
        active = app.get("is_active", True)
        status = app.get("last_status","unknown")
        ms     = app.get("last_response_ms",0) or 0

        STATUS_ICONS  = {"up":"🟢","down":"🔴","unknown":"🟡"}
        status_icon   = STATUS_ICONS.get(status,"🟡")
        border_color  = "#6fcf97" if status=="up" else ("#fc8181" if status=="down" else "#f6cc52")
        if not active: border_color = "#555577"

        with st.expander(
            f"{status_icon} {name}  ·  {'Active' if active else 'Paused'}",
            expanded=False
        ):
            with st.form(f"edit_{aid}"):
                ec1, ec2 = st.columns([2, 4])
                with ec1:
                    e_name = st.text_input("Name", value=name, key=f"en_{aid}")
                with ec2:
                    e_url  = st.text_input("URL",  value=url,  key=f"eu_{aid}")

                e_active = st.checkbox("Active (will be pinged)",
                                       value=active, key=f"ea_{aid}")

                col1, col2 = st.columns(2)
                with col1:
                    if st.form_submit_button("💾 Save", type="primary",
                                             use_container_width=True):
                        eu = e_url.strip()
                        if not eu.startswith("http"): eu = "https://" + eu
                        db().table("watchdog_apps").update({
                            "name":      e_name.strip(),
                            "url":       eu,
                            "is_active": e_active,
                        }).eq("id", aid).execute()
                        st.success("✅ Saved!"); st.rerun()
                with col2:
                    if st.form_submit_button("🗑 Delete", use_container_width=True):
                        db().table("watchdog_apps").delete().eq("id", aid).execute()
                        st.rerun()

            # Status info
            if app.get("last_checked"):
                checks = app.get("check_count",0) or 0
                fails  = app.get("fail_count",0)  or 0
                uptime = round((1-fails/checks)*100,1) if checks>0 else 0
                st.markdown(
                    f"<div style='font-size:0.78rem;color:#8899b0;margin-top:0.3rem'>"
                    f"Last check: {app['last_checked'][:19]}  ·  "
                    f"Response: {ms}ms  ·  "
                    f"Uptime: {uptime}%  ·  "
                    f"Checks: {checks}  ·  Fails: {fails}"
                    f"</div>", unsafe_allow_html=True)

# ── Danger zone ───────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
with st.expander("⚠️ Danger Zone"):
    st.markdown("<p style='color:#fc8181;font-size:0.84rem'>"
                "These actions cannot be undone.</p>",
                unsafe_allow_html=True)
    if st.button("🗑 Delete ALL Apps", key="del_all"):
        db().table("watchdog_apps").delete().neq("id", 0).execute()
        st.success("All apps deleted."); st.rerun()
