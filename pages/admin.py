"""Octa Watchdog: the apps and websites every run opens, the runner key, and how to set up GitHub and Proton VPN."""
import hashlib
import secrets

import streamlit as st

import wd

wd.page_setup("Apps, websites and setup", "What every run opens, and what GitHub needs to run it.")
wd.show_flash()

try:
    data = wd.api("overview", runs=1)
except wd.WatchdogError as e:
    st.error(str(e))
    st.stop()
s, targets = data["settings"], data["targets"]
KINDS = {"streamlit": "Streamlit app", "website": "Website"}

# ------------------------------------------------------------------------------------------------ add
st.markdown("### Add an app or website")
with st.form("add", clear_on_submit=True):
    a, b, c = st.columns([2, 4, 1.4])
    name = a.text_input("Name", placeholder="e.g. Proposal Tracker")
    url = b.text_input("Address", placeholder="https://your-app.streamlit.app")
    kind = c.selectbox("Type", ["auto", "streamlit", "website"],
                       format_func=lambda k: "Find out" if k == "auto" else KINDS[k])
    if st.form_submit_button("Add", type="primary"):
        u = url.strip()
        if u and not u.startswith("http"):
            u = "https://" + u
        if not u:
            st.error("Enter the address.")
        else:
            args = {"name": name.strip() or u.split("//")[-1].split("/")[0], "url": u}
            if kind != "auto":
                args["kind"] = kind
            wd.run("save_target", f"Added {args['name']}.", **args) and st.rerun()

a, b = st.columns(2)
with a.expander("Add several at once (one address per line)"):
    text = st.text_area("Addresses", height=120, placeholder="https://app1.streamlit.app\nhttps://www.example.org")
    if st.button("Add all"):
        added = 0
        for line in (x.strip() for x in text.splitlines()):
            if not line:
                continue
            u = line if line.startswith("http") else "https://" + line
            nm = u.split("//")[-1].split("/")[0].replace(".streamlit.app", "").replace("-", " ").title()
            try:
                wd.api("save_target", name=nm, url=u)
                added += 1
            except wd.WatchdogError:
                pass
        st.session_state["wd_flash"] = f"Added {added} of {len([x for x in text.splitlines() if x.strip()])}."
        st.rerun()
if b.button("Add all live apps of the Octa suite", help="Every app marked live in the Octa suite's catalogue."):
    r = wd.run("add_octa_apps")
    if r is not None:
        st.session_state["wd_flash"] = f"Added {r['added']} app{'s' * (r['added'] != 1)}."
        st.rerun()

# ------------------------------------------------------------------------------------------------ list
st.markdown(f"### Opened by every run ({sum(t['active'] for t in targets)} of {len(targets)})")
for t in targets:
    cols = st.columns([3, 4, 1.6, 1.3, 0.9])
    cols[0].markdown(f"**{t['name']}**  \n<span class='wd-muted'>{KINDS[t['kind']]}</span>", unsafe_allow_html=True)
    cols[1].markdown(f"[{t['url']}]({t['url']})")
    active = cols[2].toggle("Included", t["active"], key=f"on_{t['id']}")
    if active != t["active"]:
        wd.run("save_target", "Saved.", id=t["id"], url=t["url"], active=active) and st.rerun()
    with cols[3].popover("Edit"):
        with st.form(f"edit_{t['id']}"):
            nm = st.text_input("Name", t["name"])
            u = st.text_input("Address", t["url"])
            k = st.selectbox("Type", list(KINDS), index=list(KINDS).index(t["kind"]), format_func=KINDS.get)
            if st.form_submit_button("Save"):
                wd.run("save_target", "Saved.", id=t["id"], name=nm, url=u.strip(), kind=k) and st.rerun()
    if cols[4].button("🗑", key=f"del_{t['id']}", help="Remove from the list"):
        wd.run("delete_target", f"Removed {t['name']}.", id=t["id"]) and st.rerun()

# ------------------------------------------------------------------------------------------------ runner key
st.markdown("### Runner key")
st.caption("GitHub uses this key to read the list above and save each run. Only its fingerprint is kept in the "
           "database, so it is shown once. Making a new key stops the old one.")
if s["key_set"]:
    st.caption(f"A key is set (made {wd.when(s['runner_key_set_at'])}).")
if st.session_state.get("wd_new_key"):
    st.success("Copy this key now and save it in GitHub as the secret **WATCHDOG_KEY** (steps below). "
               "It will not be shown again.")
    st.code(st.session_state["wd_new_key"], language=None)
    if st.button("I have saved it in GitHub"):
        st.session_state.pop("wd_new_key")
        st.rerun()
elif st.button("Make a new runner key" if s["key_set"] else "Make the runner key", type="primary" if not s["key_set"] else "secondary"):
    key = "wd_" + secrets.token_urlsafe(32)
    if wd.run("set_runner_key", hash=hashlib.sha256(key.encode()).hexdigest()) is not None:
        st.session_state["wd_new_key"] = key
        st.rerun()

# ------------------------------------------------------------------------------------------------ setup
st.markdown("### Setting up GitHub and Proton VPN (once)")
st.markdown(f"""
**1. The runner key.** Make it above, then in GitHub open the repository **OctaInsight/octa-watchdog** →
**Settings** → **Secrets and variables** → **Actions** → **New repository secret**. Name: `WATCHDOG_KEY`, value: the key.

**2. A Proton VPN file for each country.** Sign in at **account.protonvpn.com** (the free plan works) →
**Downloads** → **WireGuard configuration**. Choose platform *Linux*, give it a name, and pick a **free server** in the
country you want; turn **off** "NetShield" and "VPN Accelerator" if offered. Click **Create** and download the
`.conf` file. Open it with a text editor, copy **everything**, and save it in GitHub as a new secret named
`PROTON_WG_` plus the country code, for example `PROTON_WG_NL`, `PROTON_WG_US`, `PROTON_WG_JP`. Repeat for every
country you choose on the dashboard. A run whose country has no file still opens all pages, without the VPN, and
says so in its notes.

**3. Start the first run.** Open [the Watchdog workflow on GitHub]({wd.GITHUB_ACTIONS}) → **Run workflow**. After
3–8 minutes the dashboard shows the run, the country the visits came from, and how each page answered. From then
on GitHub checks every 15 minutes and runs as often as set on the dashboard.

Good to know:
- Proton's free plan allows one connection at a time, so don't use the same Proton account on your own computer
  during a run, or that run goes without the VPN.
- Every run is recorded in both databases (table `watchdog_runs` in Octa_projects and in Data_and_Future) the moment
  it starts, which also keeps the free Supabase projects from pausing.
- GitHub switches off schedules in repositories without commits for 60 days; the workflow makes an empty commit
  every ~45 days to prevent that.
""")
