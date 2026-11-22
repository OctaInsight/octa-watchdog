import hashlib
import os
import sys

from streamlit.testing.v1 import AppTest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fake_db  # noqa: E402

SCRIPT = os.path.join(HERE, "fake_app.py")


def page(name="app.py", role="admin"):
    fake_db.CURRENT = fake_db.FakeDB(role)
    os.environ["WD_PAGE"] = name
    at = AppTest.from_file(SCRIPT, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at, fake_db.CURRENT


def test_dashboard_shows_runs_and_changes_the_country():
    at, db = page()
    assert any("Japan" in m.value for m in at.metric), [m.value for m in at.metric]
    assert any("Runs have not started" in w.value for w in at.warning)
    assert db.df_pings == ["app"], "opening the app touches the second database"
    assert any("Data_and_Future" in m.value and "by the GitHub run" in m.value for m in at.markdown)
    next(b for b in at.button if b.label == "Reach both databases now").click().run()
    assert db.df_pings == ["app", "app"]
    at.selectbox[0].set_value("JP")
    at.radio[0].set_value("Take turns between countries")
    at.multiselect[0].set_value(["NL", "US", "SG"])
    next(b for b in at.button if b.label == "Save").click().run()
    assert not at.exception, at.exception
    assert db.settings["country"] == "JP" and db.settings["rotate"] and db.settings["rotate_countries"] == ["NL", "US", "SG"]
    assert any("Saved" in s.value for s in at.success)


def test_only_octa_admins():
    at, db = page(role="user")
    assert any("Octa admins only" in w.value for w in at.warning) and not at.metric


def test_admin_page_adds_sites_and_makes_a_key():
    at, db = page("pages/admin.py")
    at.text_input[0].input("Data and Future")
    at.text_input[1].input("dataandfuture.eu")
    next(b for b in at.button if b.label == "Add").click().run()
    assert not at.exception, at.exception
    assert db.targets[-1]["url"] == "https://dataandfuture.eu" and db.targets[-1]["kind"] == "website"
    next(b for b in at.button if b.label == "Make the runner key").click().run()
    key = at.code[0].value
    assert key.startswith("wd_") and hashlib.sha256(key.encode()).hexdigest() == db.hash
    next(b for b in at.button if b.label == "I have saved it in GitHub").click().run()
    assert not at.code, "key shown only once"


def test_next_scheduled_run_is_every_6_hours():
    from datetime import datetime, timezone
    import wd
    assert wd.next_scheduled(datetime(2026, 11, 22, 11, 5, tzinfo=timezone.utc)).hour == 12
    assert wd.next_scheduled(datetime(2026, 11, 22, 18, 20, tzinfo=timezone.utc)) == datetime(2026, 11, 23, 0, 17, tzinfo=timezone.utc)
