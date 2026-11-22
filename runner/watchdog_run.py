"""Octa Watchdog runner, started by GitHub Actions (.github/workflows/watchdog.yml).

One run:
  1. asks the main database (Octa_projects) whether a run is due, and if so records that it starts, with the country
     chosen in the Watchdog app (watchdog_runner "plan");
  2. records the start in the second database too (Data_and_Future, watchdog_ping);
  3. connects Proton VPN (WireGuard) for that country, using the GitHub secret PROTON_WG_<CODE> (e.g. PROTON_WG_NL),
     and checks which country the visits really come from;
  4. opens every app and website in a real Chromium browser, wakes sleeping Streamlit apps, stays a while on each page
     (so the pages' own analytics, such as Google Analytics, count the visit) and notes how each one answered;
  5. disconnects and saves the results (watchdog_runner "finish").

  python runner/watchdog_run.py --check     prints due=true|false for the workflow (writes nothing)
  python runner/watchdog_run.py [--force]   does a run (--force: even if the last run was recent)

Environment: OCTA_DB_URL, OCTA_DB_KEY, DF_DB_URL, DF_DB_KEY (publishable keys, public), WATCHDOG_KEY (secret, made in
the Watchdog app), SECRETS_JSON (all GitHub secrets as JSON, to find PROTON_WG_<CODE>), GITHUB_OUTPUT (set by GitHub).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
# language and time zone the browser presents in each country
PLACE = {
    "NL": ("nl-NL", "Europe/Amsterdam"), "US": ("en-US", "America/New_York"), "JP": ("ja-JP", "Asia/Tokyo"),
    "PL": ("pl-PL", "Europe/Warsaw"), "RO": ("ro-RO", "Europe/Bucharest"), "NO": ("nb-NO", "Europe/Oslo"),
    "CH": ("de-CH", "Europe/Zurich"), "SG": ("en-SG", "Asia/Singapore"), "MX": ("es-MX", "America/Mexico_City"),
    "CA": ("en-CA", "America/Toronto"), "DE": ("de-DE", "Europe/Berlin"), "FR": ("fr-FR", "Europe/Paris"),
    "GB": ("en-GB", "Europe/London"), "ES": ("es-ES", "Europe/Madrid"), "IT": ("it-IT", "Europe/Rome"),
    "SE": ("sv-SE", "Europe/Stockholm"), "FI": ("fi-FI", "Europe/Helsinki"), "DK": ("da-DK", "Europe/Copenhagen"),
    "AT": ("de-AT", "Europe/Vienna"), "BE": ("nl-BE", "Europe/Brussels"), "PT": ("pt-PT", "Europe/Lisbon"),
    "GR": ("el-GR", "Europe/Athens"), "IE": ("en-IE", "Europe/Dublin"), "AU": ("en-AU", "Australia/Sydney"),
    "IN": ("en-IN", "Asia/Kolkata"), "BR": ("pt-BR", "America/Sao_Paulo"), "ZA": ("en-ZA", "Africa/Johannesburg"),
    "EG": ("ar-EG", "Africa/Cairo"),
}
WG_CONF = Path("/etc/wireguard/wg0.conf")      # WireGuard's own folder, owned by root (not /tmp, where root may not read)
WAKE_TEXT = re.compile(r"get this app back up|wake.*app", re.I)


# ---------------------------------------------------------------------------------------------------- databases
def rpc(url: str, key: str, fn: str, **args) -> dict:
    r = requests.post(f"{url.rstrip('/')}/rest/v1/rpc/{fn}", json=args, timeout=30,
                      headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    r.raise_for_status()
    return r.json()


def octa(action: str, **p) -> dict:
    r = rpc(os.environ["OCTA_DB_URL"], os.environ["OCTA_DB_KEY"], "watchdog_runner",
            p_key=os.environ.get("WATCHDOG_KEY", ""), p={"action": action, **p})
    if not r.get("ok"):
        raise SystemExit(f"Watchdog database: {r.get('error')}")
    return r


def ping_second_db(country: str) -> str:
    try:
        r = rpc(os.environ["DF_DB_URL"], os.environ["DF_DB_KEY"], "watchdog_ping", p_source="github", p_country=country)
        return "skipped (pinged under a minute ago)" if r.get("skipped") else "ok"
    except Exception as e:  # noqa: BLE001 - a run goes on without it
        return f"failed: {type(e).__name__}"


# ---------------------------------------------------------------------------------------------------- VPN
def wireguard_config(country: str) -> str | None:
    """The Proton WireGuard file for this country from the GitHub secrets (PROTON_WG_NL, …)."""
    try:
        secrets = json.loads(os.environ.get("SECRETS_JSON") or "{}")
    except ValueError:
        secrets = {}
    return secrets.get(f"PROTON_WG_{country}") or os.environ.get(f"PROTON_WG_{country}")


def prepare_config(text: str) -> tuple[str, list[str]]:
    """Proton's file, made to work on a GitHub runner: IPv4 only, DNS set separately (systemd-resolved)."""
    out, dns = [], []
    for line in text.splitlines():
        key = line.split("=", 1)[0].strip().lower()
        if key == "dns":
            dns = [d.strip() for d in line.split("=", 1)[1].split(",") if d.strip() and ":" not in d]
            continue
        if key in ("address", "allowedips"):
            vals = [v.strip() for v in line.split("=", 1)[1].split(",") if ":" not in v]
            if not vals:
                continue
            line = f"{line.split('=', 1)[0].rstrip()} = {', '.join(vals)}"
        out.append(line)
    return "\n".join(out) + "\n", dns


def sh(*cmd: str, stdin: str | None = None) -> None:
    subprocess.run(cmd, check=True, input=stdin.encode() if stdin is not None else None,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)


def vpn_up(text: str) -> None:
    conf, dns = prepare_config(text)
    sh("sudo", "install", "-d", "-m", "700", str(WG_CONF.parent))
    sh("sudo", "tee", str(WG_CONF), stdin=conf)          # written by root, readable only by root
    sh("sudo", "chmod", "600", str(WG_CONF))
    sh("sudo", "wg-quick", "up", "wg0")
    if dns:
        sh("sudo", "resolvectl", "dns", "wg0", *dns)
        sh("sudo", "resolvectl", "domain", "wg0", "~.")


def vpn_down() -> None:
    try:
        sh("sudo", "wg-quick", "down", "wg0")
        sh("sudo", "rm", "-f", str(WG_CONF))
    except Exception:  # noqa: BLE001
        pass


def where_am_i() -> tuple[str | None, str | None]:
    for url, cc, ip in (("https://ipinfo.io/json", "country", "ip"), ("https://api.country.is/", "country", "ip")):
        try:
            j = requests.get(url, timeout=15).json()
            return j.get(cc), j.get(ip)
        except Exception:  # noqa: BLE001
            continue
    return None, None


# ---------------------------------------------------------------------------------------------------- visits
def visit(context, target: dict, dwell: int) -> dict:
    page = context.new_page()
    t0 = time.time()
    res = {"id": target["id"], "name": target["name"], "url": target["url"]}
    try:
        resp = page.goto(target["url"], wait_until="domcontentloaded", timeout=60_000)
        res["http"] = resp.status if resp else None
        status = "up" if (resp is None or resp.status < 400) else "down"
        if target["kind"] == "streamlit" or "streamlit.app" in target["url"]:
            page.wait_for_timeout(4000)
            wake = page.get_by_role("button", name=WAKE_TEXT)
            if wake.count():
                wake.first.click()
                status = "woke"
                page.wait_for_timeout(5000)
            try:   # the app itself runs in a frame; wait until it is there
                page.wait_for_selector("iframe", timeout=120_000)
            except Exception:  # noqa: BLE001
                pass
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:  # noqa: BLE001
            pass
        res["ms"] = int((time.time() - t0) * 1000)
        # stay on the page like a reader: scroll down slowly, then back up
        steps = max(1, dwell // 4)
        for i in range(steps):
            page.mouse.wheel(0, 500 if i < steps / 2 else -500)
            page.wait_for_timeout(4000)
        res["title"] = (page.title() or "")[:120]
        res["status"] = status
    except Exception as e:  # noqa: BLE001
        res.update(status="down", ms=int((time.time() - t0) * 1000), error=f"{type(e).__name__}: {str(e)[:200]}")
    finally:
        page.close()
    return res


def visit_all(targets: list[dict], country: str, dwell: int) -> list[dict]:
    from playwright.sync_api import sync_playwright
    locale, tz = PLACE.get(country, ("en-US", "UTC"))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent=UA, locale=locale, timezone_id=tz,
                                      viewport={"width": 1440, "height": 900})
        try:
            return [visit(context, t, dwell) for t in targets]
        finally:
            browser.close()


# ---------------------------------------------------------------------------------------------------- main
def output(name: str, value: str) -> None:
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"{name}={value}\n")
    print(f"{name}={value}")


def main(argv: list[str]) -> int:
    if "--check" in argv:
        output("due", "true" if octa("peek")["due"] else "false")
        return 0
    plan = octa("plan", force="--force" in argv, source="github")
    if not plan["due"]:
        print(f"Not due yet; next run after {plan.get('next_at')}.")
        return 0
    country = plan["country"]
    notes = [f"second database: {ping_second_db(country)}"]
    vpn_country = ip = None
    connected = False
    if country != "NONE":
        conf = wireguard_config(country)
        if not conf:
            notes.append(f"no VPN file for {country} (GitHub secret PROTON_WG_{country}); visited without VPN")
        else:
            try:
                vpn_up(conf)
                connected = True
            except Exception as e:  # noqa: BLE001
                err = getattr(e, "stderr", b"") or b""
                notes.append(f"VPN for {country} did not connect ({err.decode(errors='ignore')[-160:].strip() or type(e).__name__}); visited without VPN")
    vpn_country, ip = where_am_i()
    if connected and vpn_country and vpn_country != country:
        notes.append(f"VPN exit is in {vpn_country}, not {country}")
    print(f"Run {plan['run_id']}: planned {country}, visiting from {vpn_country} ({ip}), {len(plan['targets'])} pages")
    try:
        results = visit_all(plan["targets"], country, int(plan.get("dwell_seconds") or 20))
    finally:
        if connected:
            vpn_down()
    for r in results:
        print(f"  {r['status']:5} {r.get('ms', 0):>6} ms  {r['name']}  {r.get('error', '')}")
    octa("finish", run_id=plan["run_id"], vpn_country=vpn_country, public_ip=ip,
         note="; ".join(notes), results=results)
    return 1 if all(r["status"] == "down" for r in results) and results else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
