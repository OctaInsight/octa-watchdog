"""Runner tests: no VPN, no databases (stand-ins), a local web server for the pages."""
import http.server
import json
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import watchdog_run as w  # noqa: E402

SLEEPING = b"""<html><head><title>Sleeping app</title></head><body>
<p>This app has gone to sleep due to inactivity.</p>
<button onclick="document.body.innerHTML='<iframe title=app src=about:blank></iframe>';document.title='Woken app'">Yes, get this app back up!</button>
</body></html>"""
SITE = b"<html><head><title>A website</title></head><body><div style='height:3000px'>Hello</div></body></html>"


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = SLEEPING if "sleepy" in self.path else SITE
        self.send_response(404 if "missing" in self.path else 200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def server():
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{s.server_port}"


def test_proton_file_is_made_ipv4_only():
    text = """[Interface]
# Key for test
PrivateKey = abc=
Address = 10.2.0.2/32, 2a07:b944::2:2/128
DNS = 10.2.0.1, 2a07:b944::2:1

[Peer]
PublicKey = xyz=
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = 1.2.3.4:51820"""
    conf, dns = w.prepare_config(text)
    assert "Address = 10.2.0.2/32" in conf and "AllowedIPs = 0.0.0.0/0" in conf
    assert "DNS" not in conf and "::" not in conf and dns == ["10.2.0.1"]
    assert "PrivateKey = abc=" in conf and "Endpoint = 1.2.3.4:51820" in conf


def test_vpn_file_comes_from_the_github_secrets(monkeypatch):
    monkeypatch.setenv("SECRETS_JSON", json.dumps({"PROTON_WG_NL": "[Interface]", "GITHUB_TOKEN": "x"}))
    assert w.wireguard_config("NL") == "[Interface]" and w.wireguard_config("US") is None


def test_a_run_wakes_apps_and_saves_results(monkeypatch):
    base = server()
    calls = []
    targets = [dict(id="t1", name="Sleepy app", url=base + "/sleepy.streamlit.app", kind="streamlit"),
               dict(id="t2", name="Website", url=base + "/site", kind="website"),
               dict(id="t3", name="Gone", url=base + "/missing", kind="website"),
               dict(id="t4", name="Unreachable", url="http://127.0.0.1:9/", kind="website")]

    def fake_rpc(url, key, fn, **args):
        calls.append((url, fn, args))
        if fn == "watchdog_ping":
            return {"ok": True}
        act = args["p"]["action"]
        if act == "plan":
            return {"ok": True, "due": True, "run_id": "r1", "country": "JP", "dwell_seconds": 5, "targets": targets}
        return {"ok": True}

    monkeypatch.setattr(w, "rpc", fake_rpc)
    monkeypatch.setattr(w, "where_am_i", lambda: ("NO", "5.6.7.8"))
    for k, v in dict(OCTA_DB_URL="https://octa", OCTA_DB_KEY="k", DF_DB_URL="https://df", DF_DB_KEY="k2",
                     WATCHDOG_KEY="secret", SECRETS_JSON="{}").items():
        monkeypatch.setenv(k, v)
    assert w.main([]) == 0
    fns = [(u, f, a.get("p", {}).get("action")) for u, f, a in calls]
    assert fns[0] == ("https://octa", "watchdog_runner", "plan")            # the run is recorded first
    assert fns[1] == ("https://df", "watchdog_ping", None)                  # then the second database
    fin = calls[-1][2]["p"]
    assert fin["action"] == "finish" and fin["vpn_country"] == "NO" and fin["public_ip"] == "5.6.7.8"
    st = {r["id"]: r["status"] for r in fin["results"]}
    assert st == {"t1": "woke", "t2": "up", "t3": "down", "t4": "down"}, fin["results"]
    assert "no VPN file for JP" in fin["note"]
    assert next(r for r in fin["results"] if r["id"] == "t1")["title"] == "Woken app"


def test_check_writes_nothing(monkeypatch, capsys):
    monkeypatch.setattr(w, "rpc", lambda url, key, fn, **a: {"ok": True, "due": False})
    for k in ("OCTA_DB_URL", "OCTA_DB_KEY"):
        monkeypatch.setenv(k, "x")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert w.main(["--check"]) == 0 and "due=false" in capsys.readouterr().out


def test_vpn_commands(monkeypatch):
    ran = []
    monkeypatch.setattr(w, "sh", lambda *cmd, stdin=None: ran.append((cmd, stdin)))
    w.vpn_up("[Interface]\nPrivateKey = k\nAddress = 10.2.0.2/32\nDNS = 10.2.0.1\n[Peer]\nAllowedIPs = 0.0.0.0/0\n")
    w.vpn_down()
    cmds = [" ".join(c) for c, _ in ran]
    assert cmds[:4] == ["sudo install -d -m 700 /etc/wireguard", "sudo tee /etc/wireguard/wg0.conf",
                        "sudo chmod 600 /etc/wireguard/wg0.conf", "sudo wg-quick up wg0"]
    assert "PrivateKey = k" in ran[1][1] and "DNS" not in ran[1][1]
    assert "sudo resolvectl dns wg0 10.2.0.1" in cmds and cmds[-2:] == ["sudo wg-quick down wg0", "sudo rm -f /etc/wireguard/wg0.conf"]
