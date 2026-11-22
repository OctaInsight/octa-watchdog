import copy
import uuid


class FakeDB:
    def __init__(self, role="admin"):
        self.user = dict(id="u1", username="tamer", role=role, email="t@x.org")
        self.settings = dict(country="NL", rotate=False, rotate_countries=["NL", "US"], interval_minutes=30,
                             dwell_seconds=20, key_set=False, runner_key_set_at=None)
        self.hash = None
        self.df_pings = []
        self.targets = [dict(id="t1", name="MOOC Studio", url="https://cloudearthi-mooc.streamlit.app/", kind="streamlit",
                             active=True, sort=1, last_status="woke", last_checked_at="2026-11-22T10:00:00+00:00",
                             last_ms=8300, last_country="JP", last_error=None)]
        self.runs = [dict(id="r1", started_at="2026-11-22T10:00:00+00:00", finished_at="2026-11-22T10:04:00+00:00",
                          planned_country="JP", vpn_country="JP", public_ip="1.2.3.4", up=3, woke=1, down=0,
                          note="second database: ok")]

    def second(self, fn, **a):
        if fn == "watchdog_ping":
            self.df_pings.append(a.get("p_source"))
            return {"ok": True}
        if fn == "watchdog_status":
            return {"ok": True, "runs": [{"started_at": "2026-11-22T06:17:30+00:00", "source": "github", "country": "NL"}]}
        raise AssertionError(fn)

    def __call__(self, p):
        a = p["action"]
        if a == "overview":
            return dict(ok=True, settings=dict(self.settings), targets=copy.deepcopy(self.targets), runs=self.runs)
        if a == "save_settings":
            self.settings.update({k: v for k, v in p.items() if k != "action"})
            return dict(ok=True)
        if a == "save_target":
            if any(t["url"] == p["url"] and t["id"] != p.get("id") for t in self.targets):
                return dict(ok=False, error="This address is already in the list.")
            if p.get("id"):
                t = next(t for t in self.targets if t["id"] == p["id"])
                t.update({k: v for k, v in p.items() if k not in ("action", "id")})
            else:
                t = dict(id=str(uuid.uuid4()), name=p["name"], url=p["url"],
                         kind=p.get("kind") or ("streamlit" if "streamlit.app" in p["url"] else "website"), active=True,
                         sort=100, last_status=None, last_checked_at=None, last_ms=None, last_country=None, last_error=None)
                self.targets.append(t)
            return dict(ok=True, target=t)
        if a == "delete_target":
            self.targets = [t for t in self.targets if t["id"] != p["id"]]
            return dict(ok=True)
        if a == "add_octa_apps":
            return dict(ok=True, added=0)
        if a == "set_runner_key":
            self.hash = p["hash"]
            self.settings.update(key_set=True, runner_key_set_at="2026-11-22T11:00:00+00:00")
            return dict(ok=True)
        return dict(ok=False, error="unknown")


CURRENT = FakeDB()
