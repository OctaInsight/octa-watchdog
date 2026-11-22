"""Octa Watchdog: keeps the Octa Streamlit apps, websites and databases awake.

Every run (on GitHub Actions, see .github/workflows/watchdog.yml) connects Proton VPN for the country chosen here,
opens every app and website in a real browser, and records the run in both databases. This page sets the country
and the interval, and shows how the last runs went.
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

import wd

wd.page_setup("Octa Watchdog", "Keeps the Octa apps, websites and databases awake, visiting from the country you choose.")
wd.show_flash()

try:
    data = wd.api("overview", runs=40)
except wd.WatchdogError as e:
    st.error(str(e))
    st.stop()
s, targets, runs = data["settings"], data["targets"], data["runs"]

# ------------------------------------------------------------------------------------------------ is it working?
if not s["key_set"]:
    st.warning("Runs have not started yet: create the runner key and add it to GitHub. See **Apps, websites and setup**.")
last = runs[0] if runs else None
c1, c2, c3, c4 = st.columns(4)
if last:
    started = datetime.fromisoformat(last["started_at"].replace("Z", "+00:00"))
    age = datetime.now(timezone.utc) - started
    c1.metric("Last run", wd.when(last["started_at"]), f"{int(age.total_seconds() // 60)} min ago", delta_color="off")
    c2.metric("Visited from", wd.country_label(last.get("vpn_country") or ("…" if not last.get("finished_at") else None)).split(" (")[0],
              f"planned: {last.get('planned_country') or '-'}", delta_color="off")
    if last.get("finished_at"):
        c3.metric("Pages answering", f"{(last.get('up') or 0) + (last.get('woke') or 0)} of "
                  f"{(last.get('up') or 0) + (last.get('woke') or 0) + (last.get('down') or 0)}",
                  f"{last.get('woke') or 0} woken up" if last.get("woke") else None, delta_color="off")
    else:
        c3.metric("Pages answering", "running…")
    nxt = started + timedelta(minutes=s["interval_minutes"])
    c4.metric("Next run", wd.when(nxt.isoformat()) if nxt > datetime.now(timezone.utc) else "due now",
              "GitHub may start it up to ~15 min later", delta_color="off")
    if age > timedelta(minutes=s["interval_minutes"] * 2 + 30) and s["key_set"]:
        st.error("No run for a long time. Open the GitHub Actions page to see why (for example a missing secret).")
else:
    c1.metric("Last run", "none yet")
st.link_button("Open the runs on GitHub (and start one now with “Run workflow”)", wd.GITHUB_ACTIONS)
if last and last.get("note"):
    st.caption(f"Last run notes: {last['note']}")

# ------------------------------------------------------------------------------------------------ settings
st.markdown("### Where the visits come from")
codes = wd.FREE + [c for c in wd.COUNTRIES if c not in wd.FREE] + ["NONE"]
with st.form("settings"):
    mode = st.radio("Country", ["One country", "Take turns between countries"], horizontal=True,
                    index=1 if s["rotate"] else 0,
                    help="Take turns: each run uses the next country in the list, so the apps are checked from "
                         "several countries.")
    a, b = st.columns(2)
    country = a.selectbox("Country for every run", codes, index=codes.index(s["country"]) if s["country"] in codes else 0,
                          format_func=wd.country_label)
    rotate = b.multiselect("Countries to take turns between", [c for c in codes if c != "NONE"],
                           default=[c for c in s["rotate_countries"] if c in codes], format_func=wd.country_label)
    a, b = st.columns(2)
    intervals = [15, 30, 60, 120, 240, 480, 720, 1440]
    interval = a.select_slider("How often", intervals, value=s["interval_minutes"] if s["interval_minutes"] in intervals else 30,
                               format_func=lambda m: f"every {m} min" if m < 60 else f"every {m // 60} h")
    dwell = b.slider("Seconds on each page", 5, 60, min(s["dwell_seconds"], 60),
                     help="How long the browser stays on each page, scrolling like a reader. Analytics tools such as "
                          "Google Analytics count a visit as engaged after about 10 seconds.")
    st.caption("Proton VPN's free plan has servers in the Netherlands, the United States, Japan, Poland, Romania, Norway, "
               "Switzerland, Singapore, Mexico and Canada. Each country you use needs its WireGuard file in GitHub "
               "(see **Apps, websites and setup**).")
    if st.form_submit_button("Save", type="primary"):
        if mode.startswith("Take") and not rotate:
            st.error("Choose at least one country to take turns between.")
        else:
            wd.run("save_settings", "Saved. The next run uses these settings.", country=country,
                   rotate=mode.startswith("Take"), rotate_countries=rotate, interval_minutes=interval,
                   dwell_seconds=dwell) and st.rerun()

# ------------------------------------------------------------------------------------------------ apps and websites
st.markdown("### Apps and websites")
ICON = {"up": "🟢 answering", "woke": "🟡 was asleep, woken up", "down": "🔴 not answering", None: "⚪ not checked yet"}
if targets:
    st.dataframe(pd.DataFrame([{
        "Name": t["name"], "Address": t["url"], "Type": "Streamlit app" if t["kind"] == "streamlit" else "Website",
        "Status": ICON.get(t["last_status"], t["last_status"]) if t["active"] else "⏸ paused",
        "Checked": wd.when(t["last_checked_at"]), "From": wd.flag(t["last_country"]) + " " + (t["last_country"] or ""),
        "Load time": f"{t['last_ms'] / 1000:.1f} s" if t["last_ms"] else "", "Problem": t["last_error"] or "",
    } for t in targets]), hide_index=True, width="stretch",
        column_config={"Address": st.column_config.LinkColumn("Address")})
else:
    st.info("No apps or websites yet. Add them under **Apps, websites and setup**.")

# ------------------------------------------------------------------------------------------------ run history
st.markdown("### Recent runs")
if runs:
    st.dataframe(pd.DataFrame([{
        "Started": wd.when(r["started_at"]), "Planned": r.get("planned_country") or "",
        "Visited from": (wd.flag(r["vpn_country"]) + " " + r["vpn_country"]) if r.get("vpn_country") else "",
        "IP address": r.get("public_ip") or "",
        "Answering": "" if r.get("up") is None else (r.get("up") or 0) + (r.get("woke") or 0),
        "Woken": r.get("woke") or "", "Down": r.get("down") or "",
        "Finished": wd.when(r["finished_at"]) if r.get("finished_at") else "running or stopped",
        "Notes": r.get("note") or "",
    } for r in runs]), hide_index=True, width="stretch")
    st.caption("Each run is also written to the Data_and_Future database (table watchdog_runs) when it starts. "
               "Compare these times and countries with the visits in Google Analytics.")
else:
    st.caption("No runs yet.")
