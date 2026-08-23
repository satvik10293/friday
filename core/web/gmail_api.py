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

    def available(self) -> bool:
        return self.libs_available() and self.credentials_present()

    def setup_hint(self) -> str:
        base, creds, _ = _paths()
        if not self.libs_available():
            return ("Gmail's Python libraries aren't installed "
                    "(google-api-python-client, google-auth-oauthlib).")
        if not creds.exists():
            return (f"Gmail isn't connected yet. Put your Google OAuth "
                    f"credentials.json at {creds} — see the setup steps.")
        return "Gmail is set up."

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
        """Recent messages matching `query` (default: unread) as {from, subject,
        snippet}. Never raises."""
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

    # ── send ─────────────────────────────────────────────────────────────────
    def send(self, to: str, subject: str, body: str) -> dict:
        """Send an email. Called ONLY after the owner confirmed the draft."""
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


_client: Optional[GmailClient] = None


def get_gmail() -> GmailClient:
    global _client
    if _client is None:
        _client = GmailClient()
    return _client
