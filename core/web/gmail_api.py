"""
core/web/gmail_api.py — FRIDAY reads and sends Gmail through the Gmail API.

Why not the browser: Google blocks sign-in on automation-driven browsers, so
FRIDAY's isolated Chrome can't log into Gmail. The API is the reliable path —
authorize once, then read/send with no browser at all. (Instagram/WhatsApp stay
on the browser; they don't block automation.)

Setup (one-time, owner):
  1. console.cloud.google.com  ->  create a project.
  2. Enable the Gmail API.
  3. OAuth consent screen: External; add yourself as a Test user.
  4. Credentials -> Create -> OAuth client ID -> Desktop app -> download the JSON.
  5. Save it as  <data_dir>/gmail/credentials.json .
First use runs the consent flow in your REAL browser (Google allows that) and
writes <data_dir>/gmail/token.json; after that it is silent.

Scopes are read + send ONLY (no delete, no settings). Everything degrades
honestly: missing libraries or credentials report not-ready, never a crash.
"""

from __future__ import annotations

import base64
import logging
from email.mime.text import MIMEText
from typing import Optional

log = logging.getLogger("friday.web.gmail")

# least privilege: read messages and send. Nothing that deletes or reconfigures.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/gmail.send"]


def _paths():
    """(dir, credentials.json, token.json) under the app data dir."""
    from core.launcher.platform_adapter import PlatformAdapter
    base = PlatformAdapter().data_dir() / "gmail"
    return base, base / "credentials.json", base / "token.json"


def _dotenv_value(key: str) -> str:
    """Read one KEY from the app-root .env (best-effort). The app loads .env at
    boot, but a standalone call may not have, so read it directly too."""
    try:
        from core.launcher.platform_adapter import PlatformAdapter
        env = PlatformAdapter().config_dir() / ".env"
        if not env.exists():
            return ""
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001
        pass
    return ""


class GmailClient:
    """Read/send Gmail over the API. Lazy, never-raises."""

    def __init__(self) -> None:
        self._svc = None

    # ── availability ─────────────────────────────────────────────────────────
    @staticmethod
    def libs_available() -> bool:
        import importlib.util as u
        return all(u.find_spec(m) for m in
                   ("googleapiclient", "google.auth", "google.oauth2"))

    @staticmethod
    def credentials_present() -> bool:
        _, creds, token = _paths()
        return creds.exists() or token.exists()

    @staticmethod
    def _app_creds():
        """(address, app_password) from the environment / .env, or None. This is
        the SIMPLE path: one Google App Password (2-Step Verification + one
        screen) unlocks IMAP read + SMTP send with zero Cloud-Console setup."""
        import os
        addr = (os.environ.get("GMAIL_ADDRESS") or "").strip()
        pw = (os.environ.get("GMAIL_APP_PASSWORD") or "").replace(" ", "").strip()
        if not (addr and pw):                       # fall back to the app-root .env
            addr = addr or _dotenv_value("GMAIL_ADDRESS")
            pw = pw or (_dotenv_value("GMAIL_APP_PASSWORD") or "").replace(" ", "")
        return (addr, pw) if addr and pw else None

    def available(self) -> bool:
        # the app-password path (IMAP/SMTP) needs no google libs at all
        if self._app_creds():
            return True
        return self.libs_available() and self.credentials_present()

    def setup_hint(self) -> str:
        _, creds, _t = _paths()
        return ("Gmail isn't connected yet. The easy way: turn on 2-Step "
                "Verification, create an App Password at "
                "myaccount.google.com/apppasswords, and give it to me — no Google "
                "Cloud setup needed.")

    # ── auth ─────────────────────────────────────────────────────────────────
    def _service(self):
        if self._svc is not None:
            return self._svc
        creds = self._creds()
        if creds is None:
            return None
        try:
            from googleapiclient.discovery import build
            self._svc = build("gmail", "v1", credentials=creds,
                              cache_discovery=False)
        except Exception:  # noqa: BLE001
            log.debug("gmail service build failed", exc_info=True)
            return None
        return self._svc

    def _creds(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        base, creds_path, token_path = _paths()
        creds = None
        if token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            except Exception:  # noqa: BLE001
                creds = None
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                token_path.write_text(creds.to_json(), encoding="utf-8")
                return creds
            except Exception:  # noqa: BLE001
                log.debug("gmail token refresh failed", exc_info=True)
        # first run: the interactive consent flow (needs credentials.json + oauthlib)
        if not creds_path.exists():
            return None
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except Exception:  # noqa: BLE001
            return None
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)     # opens the REAL browser once
            base.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception:  # noqa: BLE001
            log.debug("gmail oauth flow failed", exc_info=True)
            return None

    # ── read ─────────────────────────────────────────────────────────────────
    def check(self, *, max_results: int = 5, query: str = "is:unread") -> dict:
        """Recent unread messages as {from, subject, snippet}. Never raises. Uses
        the app-password IMAP path when configured, else the OAuth API."""
        app = self._app_creds()
        if app:
            return self._imap_check(app, max_results)
        svc = self._service()
        if svc is None:
            return {"ok": False, "error": "not_ready"}
        try:
            listing = svc.users().messages().list(
                userId="me", q=query, maxResults=max_results).execute()
            out = []
            for m in listing.get("messages", []):
                full = svc.users().messages().get(
                    userId="me", id=m["id"], format="metadata",
                    metadataHeaders=["From", "Subject"]).execute()
                headers = {h["name"]: h["value"]
                           for h in full.get("payload", {}).get("headers", [])}
                out.append({"from": headers.get("From", ""),
                            "subject": headers.get("Subject", "(no subject)"),
                            "snippet": (full.get("snippet") or "")[:160]})
            return {"ok": True, "messages": out}
        except Exception as e:  # noqa: BLE001
            log.debug("gmail check failed", exc_info=True)
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ── read: app-password IMAP (no google libs, no Cloud setup) ──────────────
    @staticmethod
    def _imap_check(app, max_results: int) -> dict:
        addr, pw = app
        import imaplib
        from email import message_from_bytes
        from email.header import decode_header, make_header
        try:
            box = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            try:
                box.login(addr, pw)
                box.select("INBOX")
                _typ, data = box.search(None, "UNSEEN")
                ids = (data[0].split() if data and data[0] else [])[-max_results:][::-1]
                out = []
                for mid in ids:
                    _t, md = box.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
                    raw = md[0][1] if md and md[0] else b""
                    msg = message_from_bytes(raw)
                    frm = str(make_header(decode_header(msg.get("From", ""))))
                    subj = str(make_header(decode_header(msg.get("Subject", "(no subject)"))))
                    out.append({"from": frm, "subject": subj, "snippet": ""})
                return {"ok": True, "messages": out}
            finally:
                try:
                    box.logout()
                except Exception:  # noqa: BLE001
                    pass
        except Exception as e:  # noqa: BLE001
            log.debug("gmail imap check failed", exc_info=True)
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ── send ─────────────────────────────────────────────────────────────────
    def send(self, to: str, subject: str, body: str) -> dict:
        """Send an email. Called ONLY after the owner confirmed the draft. Uses
        the app-password SMTP path when configured, else the OAuth API."""
        app = self._app_creds()
        if app:
            return self._smtp_send(app, to, subject, body)
        svc = self._service()
        if svc is None:
            return {"ok": False, "error": "not_ready"}
        try:
            msg = MIMEText(body or "")
            msg["to"] = to
            msg["subject"] = subject or "(no subject)"
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            svc.users().messages().send(userId="me", body={"raw": raw}).execute()
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            log.debug("gmail send failed", exc_info=True)
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    @staticmethod
    def _smtp_send(app, to: str, subject: str, body: str) -> dict:
        addr, pw = app
        import smtplib
        try:
            msg = MIMEText(body or "")
            msg["From"] = addr
            msg["To"] = to
            msg["Subject"] = subject or "(no subject)"
            server = smtplib.SMTP("smtp.gmail.com", 587, timeout=20)
            try:
                server.starttls()
                server.login(addr, pw)
                server.sendmail(addr, [to], msg.as_string())
            finally:
                try:
                    server.quit()
                except Exception:  # noqa: BLE001
                    pass
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            log.debug("gmail smtp send failed", exc_info=True)
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


_client: Optional[GmailClient] = None


def get_gmail() -> GmailClient:
    global _client
    if _client is None:
        _client = GmailClient()
    return _client
