"""octa_auth: one Octa account for all Octa Insight apps (shared login, registration and password reset).

Copy this folder into an app (or install the launch repo) and see `ui.py` for usage.
"""
from .ui import (App, FAMILIES, require_login, current_user, sidebar, logout, token, with_session,  # noqa: F401
                 display_name, portal_url, flash)
from . import client, mail  # noqa: F401

__version__ = "1.0.0"
