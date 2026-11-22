"""Emails sent from Octa apps (welcome, forgot username/password).

Sent through Resend (https://resend.com), the same service the matchmaking platform uses. Gmail (SMTP with an app
password) is only a fallback for an app whose secrets have no Resend key yet.

Streamlit secrets:

    [email]
    resend_api_key = "re_..."                    # Resend -> API Keys (sending access)
    from_email = "accounts@<verified domain>"    # an address on a domain verified in Resend
    from_name = "Octa Insight"
    reply_to = "<address that receives replies>" # optional

    # fallback only, used when resend_api_key is missing:
    # user = "<gmail address>"
    # app_password = "abcd efgh ijkl mnop"

Key names are read case-insensitively, and the matchmaking platform's top-level RESEND_API_KEY and
RESEND_FROM_EMAIL are accepted too. The Resend free plan allows 100 emails a day and 3,000 a month for the whole Resend account (shared with the
matchmaking platform).
"""
from __future__ import annotations
import html
import smtplib
import ssl
import uuid
from email.message import EmailMessage
from email.utils import formataddr

import requests
import streamlit as st

RESEND_URL = "https://api.resend.com/emails"


class MailError(RuntimeError):
    """The email could not be sent; the message says why (never contains a key)."""


_KEY_NAMES = ("resend_api_key", "resend_key", "api_key")
_FROM_NAMES = ("from_email", "resend_from_email", "from", "sender")


def _section() -> dict:
    """The [email] section of the secrets with lower-case key names ({} if there is none)."""
    try:
        sec = st.secrets.get("email") or {}
        return {str(k).strip().lower(): v for k, v in dict(sec).items()}
    except Exception:
        return {}


def _top(name: str):
    """A top-level secret, as the matchmaking platform writes them (RESEND_API_KEY, RESEND_FROM_EMAIL)."""
    try:
        for k in st.secrets.keys():
            if str(k).strip().lower() == name:
                v = st.secrets[k]
                return v if isinstance(v, str) else None
    except Exception:
        pass
    return None


def _first(c: dict, names) -> str:
    for n in names:
        v = c.get(n)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _cfg() -> dict:
    """Email settings. The [email] section is read case-insensitively; the matchmaking platform's top-level
    RESEND_API_KEY / RESEND_FROM_EMAIL also work."""
    c = _section()
    c["resend_api_key"] = _first(c, _KEY_NAMES) or (_top("resend_api_key") or "").strip()
    c["from_email"] = _first(c, _FROM_NAMES) or (_top("resend_from_email") or "").strip()
    return c


def sender() -> dict:
    """The sender shown on admin pages: from_name, from_email, reply_to (no key)."""
    c = _cfg()
    return {"from_name": c.get("from_name") or "Octa Insight", "from_email": c.get("from_email") or c.get("user") or "",
            "reply_to": c.get("reply_to") or ""}


def diagnose() -> str:
    """Why email is not set up, naming the settings found (never their values)."""
    try:
        has_email = any(str(k).strip().lower() == "email" for k in st.secrets.keys())
        top = sorted(str(k) for k in st.secrets.keys())
    except Exception:
        return "The app could not read its Streamlit secrets."
    c = _cfg()
    missing = [n for n, v in (("resend_api_key", c.get("resend_api_key")), ("from_email", c.get("from_email"))) if not v]
    if not missing:
        return "Resend is set up."
    if not has_email:
        return (f"There is no [email] section in the secrets (sections and settings found: {', '.join(top) or 'none'}). "
                f"Missing: {', '.join(missing)}.")
    found = sorted(k for k in _section())
    return (f"The [email] section is missing {' and '.join(missing)} "
            f"(settings found in it: {', '.join(found) or 'none'}). Names must be written exactly like this, "
            "each on its own line under [email], with the value in double quotes.")


def provider() -> str | None:
    """'resend', 'gmail' or None (not set up)."""
    c = _cfg()
    if c.get("resend_api_key") and c.get("from_email"):
        return "resend"
    if c.get("user") and c.get("app_password"):
        return "gmail"
    return None


def enabled() -> bool:
    return provider() is not None


def _render(paragraphs: list[str], button: tuple[str, str] | None, after: list[str]) -> tuple[str, str]:
    text = "\n\n".join(paragraphs + ([f"{button[0]}: {button[1]}"] if button else []) + after)
    text += "\n\n— Octa Insight"
    p = lambda s: f"<p style='margin:0 0 14px 0'>{s}</p>"  # noqa: E731
    btn = ""
    if button:
        btn = (f"<p style='margin:20px 0'><a href='{html.escape(button[1], quote=True)}' "
               "style='background:#2a78d6;color:#ffffff;text-decoration:none;padding:10px 18px;border-radius:6px;"
               f"font-weight:600'>{html.escape(button[0])}</a></p>"
               f"<p style='font-size:12px;color:#6b6a66;margin:0 0 14px 0'>Or copy this link: "
               f"{html.escape(button[1])}</p>")
    body = ("<div style='font-family:Arial,Helvetica,sans-serif;font-size:15px;color:#0b0b0b;max-width:560px'>"
            + "".join(p(s) for s in paragraphs) + btn + "".join(p(s) for s in after)
            + "<p style='color:#52514e;margin-top:24px'>— Octa Insight</p></div>")
    return text, body


def send(to: str, subject: str, paragraphs: list[str], button: tuple[str, str] | None = None,
         after: list[str] | None = None) -> str:
    """Send a plain + HTML email. `button` = (label, url). Returns the provider's message id (Resend) or ''.
    Raises MailError when the email could not be handed over to the provider."""
    c = _cfg()
    text, body = _render(paragraphs, button, after or [])
    kind = provider()
    if kind == "resend":
        return _send_resend(c, to, subject, text, body)
    if kind == "gmail":
        _send_gmail(c, to, subject, text, body)
        return ""
    raise MailError("Email is not set up for this app (no [email] resend_api_key in the Streamlit secrets).")


def _send_resend(c: dict, to: str, subject: str, text: str, body: str) -> str:
    sender = c["from_email"]
    if "<" not in sender:                       # "Name <address>" is used as it is
        sender = formataddr((c.get("from_name", "Octa Insight"), sender))
    payload = {"from": sender,
               "to": [to], "subject": subject, "text": text, "html": body}
    if c.get("reply_to"):
        payload["reply_to"] = c["reply_to"]
    headers = {"Authorization": f"Bearer {c['resend_api_key']}", "Content-Type": "application/json",
               "Idempotency-Key": uuid.uuid4().hex}
    try:
        r = requests.post(RESEND_URL, json=payload, headers=headers, timeout=15)
    except requests.RequestException:
        raise MailError("Could not reach Resend. Please try again in a moment.") from None
    if r.status_code >= 400:
        reasons = {
            401: "Resend rejected the API key. Check [email] resend_api_key in the Streamlit secrets.",
            403: "Resend refused the sender. The from_email domain must be verified in Resend and allowed for this key.",
            422: "Resend rejected the email settings. Check from_email and reply_to.",
            429: "The daily Resend sending limit was reached. Emails work again after midnight UTC.",
        }
        raise MailError(reasons.get(r.status_code, f"Resend answered {r.status_code}. See the Resend dashboard logs."))
    try:
        msg_id = r.json().get("id")
    except ValueError:
        msg_id = None
    if not msg_id:
        raise MailError("Resend did not confirm the email.")
    return msg_id


def _send_gmail(c: dict, to: str, subject: str, text: str, body: str) -> None:
    sender, name = c["user"], c.get("from_name", "Octa Insight")
    host, port = c.get("host", "smtp.gmail.com"), int(c.get("port", 465))
    msg = EmailMessage()
    msg["From"] = formataddr((name, sender))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(body, subtype="html")
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=25) as s:
                s.login(sender, c["app_password"].replace(" ", ""))
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=25) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(sender, c["app_password"].replace(" ", ""))
                s.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        raise MailError(f"Gmail could not send the email ({type(e).__name__}).") from None
