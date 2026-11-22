"""Runs one Watchdog page signed in, against an in-memory stand-in for watchdog_admin."""
import os
import runpy
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import octa_auth  # noqa: E402
import wd  # noqa: E402
import fake_db  # noqa: E402

DB = fake_db.CURRENT
wd.require_login = lambda app, required=True: DB.user
wd.sidebar = lambda app: None
wd.token = lambda: "tok"
wd.client.rpc = lambda fn, **a: DB(a["p"])
wd.second_rpc = lambda fn, **a: DB.second(fn, **a)
st_page_link = __import__("streamlit").page_link
__import__("streamlit").page_link = lambda *a, **k: None
runpy.run_path(os.path.join(ROOT, os.environ.get("WD_PAGE", "app.py")), run_name="__main__")
