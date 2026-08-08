"""
core/launcher/account_setup.py — FRIDAY

Launch-time onboarding for the user's AI accounts. On the first launch FRIDAY
asks which cloud AI seats the user has and how to reach each one:

  * an **API key** — stored securely in the gitignored `.env`, or
  * a **linked browser seat** — a paid chat subscription (ChatGPT / Claude /
    Gemini) the user logs into by hand once; FRIDAY reuses that session.

Once the user completes (or skips) the window, a marker is written so FRIDAY
never auto-prompts again — the tray's "AI Accounts…" item reopens it on demand.

Design rules (same as first_run):
  * side-effect-free to import (no GUI, no I/O, no network at import time),
  * never-raises: every path is guarded and degrades cleanly (headless-safe),
  * secrets are never printed, logged, embedded, or committed — only the value
    of an env var is written to `.env` (chmod 600 where the OS supports it).

The provider list is derived from the harness (`_CLOUD_VENDORS`) so that stays
the single source of truth: add a vendor there and it appears here too.

CLI:
    python -m core.launcher.account_setup --status   # JSON, no UI
    python -m core.launcher.account_setup --ui        # show the window (tray uses this)
    python -m core.launcher.account_setup --force     # show even if already completed
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .platform_adapter import PlatformAdapter

log = logging.getLogger("friday.launcher.account_setup")

_MARKER_NAME = "accounts_setup.json"     # written under the data dir once completed

# Per-vendor presentation + how to reach it. Keyed by the harness vendor name.
# `browser_site` is the key into harness.browser_provider.SITES (None = no browser
# seat, API key only). `keys_url` is where the user gets an API key.
_AUGMENT = {
    "openai":    ("OpenAI · ChatGPT",   "chatgpt", "https://platform.openai.com/api-keys"),
    "anthropic": ("Anthropic · Claude", "claude",  "https://console.anthropic.com/settings/keys"),
    "gemini":    ("Google · Gemini",    "gemini",  "https://aistudio.google.com/apikey"),
    "xai-grok":  ("xAI · Grok",         None,      "https://console.x.ai"),
    "groq":      ("Groq",               None,      "https://console.groq.com/keys"),
}


@dataclass(frozen=True)
class Provider:
    id: str                              # harness vendor name (e.g. "openai")
    label: str                           # human label for the UI
    env_var: str                         # the .env / environment key it reads
    browser_site: Optional[str]          # harness SITES key, or None (key-only)
    keys_url: str                        # where to obtain an API key


def _providers() -> list[Provider]:
    """The vendors the harness knows about, in a stable display order. Any vendor
    without an augment entry still appears (key-only), so the harness stays the
    single source of truth."""
    try:
        from core.harness.config import _CLOUD_VENDORS
        vendors = [(name, env) for name, env, _factory in _CLOUD_VENDORS]
    except Exception:  # noqa: BLE001 — harness import must never block onboarding
        log.debug("harness vendor list unavailable; using built-in fallback", exc_info=True)
        vendors = [(k, f"{k.upper().replace('-', '_')}_API_KEY") for k in _AUGMENT]
    out: list[Provider] = []
    for name, env in vendors:
        label, site, url = _AUGMENT.get(
            name, (name.replace("-", " ").title(), None, ""))
        out.append(Provider(id=name, label=label, env_var=env,
                            browser_site=site, keys_url=url))
    return out


class AccountManager:
    """Reads/writes the user's AI-account configuration. GUI-free and safe to use
    headlessly (tests, CLI, the tray subprocess) — the window lives in `show_ui`."""

    def __init__(self, *, root: Optional[Path] = None,
                 data_dir: Optional[Path] = None,
                 platform: Optional[PlatformAdapter] = None) -> None:
        self.platform = platform or PlatformAdapter()
        self.root = Path(root) if root else self.platform.config_dir()
        self.data = Path(data_dir) if data_dir else self.platform.data_dir()
        self.env_path = self.root / ".env"
        self.marker_path = self.data / _MARKER_NAME
        self.seats_root = self.data / "friday_seats"

    # ── provider list ────────────────────────────────────────────────────────────
    def providers(self) -> list[Provider]:
        return _providers()

    # ── key state ────────────────────────────────────────────────────────────────
    def _env_file_value(self, name: str) -> Optional[str]:
        """Value for `name` as written in .env (may be ""), or None if absent."""
        if not self.env_path.exists():
            return None
        try:
            for raw in self.env_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == name:
                    return v.strip().strip('"').strip("'")
        except OSError:
            log.debug("could not read .env", exc_info=True)
        return None

    def key_present(self, name: str) -> bool:
        """True if a non-empty key exists in the live environment or in .env."""
        if os.environ.get(name):
            return True
        val = self._env_file_value(name)
        return bool(val)

    def seat_dir(self, site: str) -> Path:
        return self.seats_root / site

    def seat_linked(self, site: Optional[str]) -> bool:
        return bool(site) and (self.seat_dir(site) / "linked.json").exists()

    def status(self, p: Provider) -> dict:
        return {"id": p.id, "label": p.label, "env_var": p.env_var,
                "keys_url": p.keys_url, "can_browser": bool(p.browser_site),
                "key": self.key_present(p.env_var),
                "browser": self.seat_linked(p.browser_site)}

    def summary(self) -> list[dict]:
        return [self.status(p) for p in self.providers()]

    def any_configured(self) -> bool:
        return any(s["key"] or s["browser"] for s in self.summary())

    # ── secure key write (only the value ever touches .env) ──────────────────────
    def save_key(self, name: str, value: Optional[str]) -> bool:
        """Persist (or clear, when value is blank) an API key in the gitignored
        .env and apply it to the live process so it takes effect immediately.
        Returns whether a non-empty key is now set. Never logs the value."""
        value = (value or "").strip()
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            lines: list[str] = []
            if self.env_path.exists():
                lines = [ln for ln in self.env_path.read_text(encoding="utf-8").splitlines()
                         if not ln.strip().startswith(f"{name}=")]
            if value:
                lines.append(f"{name}={value}")
            self.env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            try:
                self.env_path.chmod(0o600)
            except OSError:
                pass
        except OSError:
            log.warning("could not write .env for %s", name, exc_info=True)
            return False
        # real env wins in friday_secrets, so update it live for this session
        if value:
            os.environ[name] = value
            log.info("stored API key for %s", name)
        else:
            os.environ.pop(name, None)
            log.info("cleared API key for %s", name)
        return bool(value)

    # ── the marker: "don't ask again" ────────────────────────────────────────────
    def is_done(self) -> bool:
        return self.marker_path.exists()

    def mark_done(self, meta: Optional[dict] = None) -> str:
        try:
            self.marker_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"completed": True}
            if meta:
                payload.update(meta)
            self.marker_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return str(self.marker_path)
        except OSError:
            log.debug("could not write account marker", exc_info=True)
            return ""

    def should_prompt(self, *, headless: bool) -> bool:
        """Auto-prompt only on a real GUI launch that hasn't completed setup yet.
        Per the chosen policy we never nag after the first time — the tray reopens
        it on demand."""
        return not headless and not self.is_done()

    # ── on-demand browser linking ────────────────────────────────────────────────
    def ensure_playwright(self, on_status: Optional[Callable[[str], None]] = None) -> tuple[bool, str]:
        """Make Playwright + Chromium available, installing them on first use.
        Returns (ok, message). Heavy (~150MB) but only ever runs when the user
        actually clicks 'Link via browser'."""
        def say(m: str) -> None:
            if on_status:
                try:
                    on_status(m)
                except Exception:  # noqa: BLE001
                    pass
        import importlib.util
        import subprocess
        import sys
        if importlib.util.find_spec("playwright") is None:
            say("Installing browser support (one-time, ~1–2 min)…")
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", "playwright"],
                               check=True)
            except Exception as e:  # noqa: BLE001
                return False, f"could not install playwright: {type(e).__name__}"
        say("Downloading Chromium (one-time)…")
        try:
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                           check=True)
        except Exception as e:  # noqa: BLE001
            return False, f"could not install chromium: {type(e).__name__}"
        return True, "browser support ready"

    def link_browser(self, p: Provider,
                     on_status: Optional[Callable[[str], None]] = None) -> bool:
        """Open the provider's site in a persistent (logged-in) browser profile so
        the user signs in by hand once; FRIDAY reuses the session thereafter.
        Marks the seat linked when the site's compose box is reachable (i.e. the
        user is signed in). Returns success. Never raises."""
        def say(m: str) -> None:
            if on_status:
                try:
                    on_status(m)
                except Exception:  # noqa: BLE001
                    pass
        if not p.browser_site:
            return False
        ok, msg = self.ensure_playwright(on_status=on_status)
        if not ok:
            say(msg)
            return False
        try:
            from core.harness.browser_provider import SITES
            from core.harness.browser_drivers import PlaywrightChatDriver
            site = SITES.get(p.browser_site)
            if site is None:
                say("no browser profile for this provider")
                return False
            seat = self.seat_dir(p.browser_site)
            seat.mkdir(parents=True, exist_ok=True)
            say("Opening the sign-in window — log in, then return here…")
            driver = PlaywrightChatDriver(site, user_data_dir=str(seat), headless=False)
            # is_ready() opens the (visible) profile and waits for the compose box,
            # which only appears once the user is signed in.
            ready = driver.is_ready()
            if ready:
                (seat / "linked.json").write_text(
                    json.dumps({"vendor": p.browser_site, "linked": True}),
                    encoding="utf-8")
                say("Linked ✓")
                return True
            say("Not signed in yet — click Link again after logging in.")
            return False
        except Exception as e:  # noqa: BLE001
            log.debug("browser link failed", exc_info=True)
            say(f"link failed: {type(e).__name__}")
            return False


# ── native window (tkinter; guarded, never required) ─────────────────────────────
def gui_available() -> bool:
    """Whether a Tk display can be opened here (False on headless/servers)."""
    try:
        import tkinter as tk
        r = tk.Tk()
        r.destroy()
        return True
    except Exception:  # noqa: BLE001
        return False


def show_ui(manager: Optional[AccountManager] = None) -> dict:
    """Show the account-setup window (native desktop window — never a browser tab).
    Blocks until the user closes it. Returns a summary dict. Safe to call only on
    the main thread; headless callers should gate on `gui_available()` first."""
    mgr = manager or AccountManager()
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:  # noqa: BLE001
        log.debug("tkinter unavailable; skipping account UI", exc_info=True)
        mgr.mark_done({"skipped": "no_gui"})
        return {"shown": False, "summary": mgr.summary()}

    import threading
    import webbrowser

    root = tk.Tk()
    root.title("FRIDAY — Connect your AI accounts")
    root.resizable(False, False)
    try:
        root.attributes("-topmost", True)
    except Exception:  # noqa: BLE001
        pass

    pad = {"padx": 10, "pady": 6}
    header = ttk.Frame(root)
    header.grid(row=0, column=0, columnspan=4, sticky="we", **pad)
    ttk.Label(header, text="Connect the AI accounts you have",
              font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w")
    ttk.Label(header,
              text=("Paste an API key, or link a paid chat account through your "
                    "browser. Leave the rest blank — you can add more anytime from "
                    "the tray menu. Keys are stored only on this machine."),
              wraplength=560, foreground="#555").grid(row=1, column=0, sticky="w")

    entries: dict[str, "tk.StringVar"] = {}
    status_labels: dict[str, "ttk.Label"] = {}
    providers = mgr.providers()

    body = ttk.Frame(root)
    body.grid(row=1, column=0, columnspan=4, sticky="we", **pad)

    def _refresh_status(p: Provider) -> None:
        st = mgr.status(p)
        if st["key"]:
            txt, color = "● API key set", "#2e7d32"
        elif st["browser"]:
            txt, color = "● browser linked", "#2e7d32"
        else:
            txt, color = "○ not connected", "#999"
        status_labels[p.id].configure(text=txt, foreground=color)

    for i, p in enumerate(providers):
        st = mgr.status(p)
        ttk.Label(body, text=p.label, width=20).grid(row=i, column=0, sticky="w", pady=4)
        var = tk.StringVar()
        entries[p.id] = var
        ent = ttk.Entry(body, textvariable=var, width=34, show="•")
        ent.grid(row=i, column=1, sticky="w", padx=4)
        if st["key"]:
            var.set("")                  # never echo the stored key
            ent.configure(foreground="#999")

        def _open_keys(url=p.keys_url) -> None:
            if url:
                try:
                    webbrowser.open(url)
                except Exception:  # noqa: BLE001
                    pass
        ttk.Button(body, text="Get key ↗", width=9,
                   command=_open_keys).grid(row=i, column=2, padx=2)

        def _link(prov=p) -> None:
            def worker() -> None:
                status_labels[prov.id].configure(text="linking…", foreground="#555")
                mgr.link_browser(prov, on_status=lambda m: status_labels[prov.id]
                                 .configure(text=m, foreground="#555"))
                root.after(0, lambda: _refresh_status(prov))
            threading.Thread(target=worker, daemon=True).start()
        link_btn = ttk.Button(body, text="Link via browser", width=15, command=_link)
        link_btn.grid(row=i, column=3, padx=2)
        if not p.browser_site:
            link_btn.state(["disabled"])

        lbl = ttk.Label(body, text="")
        lbl.grid(row=i, column=4, sticky="w", padx=6)
        status_labels[p.id] = lbl
        _refresh_status(p)

    result = {"shown": True, "saved": []}

    def _save_and_close() -> None:
        for p in providers:
            typed = entries[p.id].get().strip()
            if typed:
                if mgr.save_key(p.env_var, typed):
                    result["saved"].append(p.id)
        mgr.mark_done({"configured": mgr.any_configured()})
        result["summary"] = mgr.summary()
        root.destroy()

    def _later() -> None:
        mgr.mark_done({"configured": mgr.any_configured(), "deferred": True})
        result["summary"] = mgr.summary()
        result["deferred"] = True
        root.destroy()

    footer = ttk.Frame(root)
    footer.grid(row=2, column=0, columnspan=4, sticky="e", **pad)
    ttk.Button(footer, text="I'll do this later", command=_later).grid(row=0, column=0, padx=6)
    ttk.Button(footer, text="Save & Continue", command=_save_and_close).grid(row=0, column=1)

    root.protocol("WM_DELETE_WINDOW", _later)
    root.update_idletasks()
    try:
        root.eval("tk::PlaceWindow . center")
    except Exception:  # noqa: BLE001
        pass
    root.mainloop()
    return result


def maybe_prompt(*, headless: bool, manager: Optional[AccountManager] = None) -> dict:
    """Called from the launcher on a GUI boot. Shows the window only on the first
    launch (marker absent) and only if a display is available. Never raises;
    returns a small report for the startup summary."""
    mgr = manager or AccountManager()
    if not mgr.should_prompt(headless=headless):
        return {"shown": False, "reason": "done" if mgr.is_done() else "headless"}
    if not gui_available():
        return {"shown": False, "reason": "no_display"}
    try:
        return show_ui(mgr)
    except Exception:  # noqa: BLE001 — onboarding must never take the boot down
        log.debug("account setup UI failed", exc_info=True)
        return {"shown": False, "reason": "error"}


def main(argv: Optional[list] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="friday-account-setup",
                                description="Connect FRIDAY to your AI accounts")
    p.add_argument("--status", action="store_true", help="print JSON status, no UI")
    p.add_argument("--ui", action="store_true", help="show the setup window")
    p.add_argument("--force", action="store_true", help="show even if already completed")
    args = p.parse_args(argv)
    mgr = AccountManager()
    if args.status:
        print(json.dumps({"done": mgr.is_done(), "providers": mgr.summary()}, indent=2))
        return 0
    # default action (and the tray's invocation) is to show the window
    if args.force or args.ui or not args.status:
        if not gui_available():
            print("No display available for the setup window.")
            return 1
        show_ui(mgr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
