"""
core/launcher/diagnostics.py — FRIDAY V3 (RC1)
The diagnostics screen. Aggregates a single, human-readable status picture of a running
(or partially-running) FRIDAY: version + build channel, overall runtime status, the
Cognitive Brains, loaded plugins, the active AI reasoning provider, the event-bus /
runtime status, and process vitals (CPU / RAM / threads). It reads whatever launcher
components are available and degrades gracefully when a subsystem is absent.

It builds on `HealthMonitor` (process + subsystem health) and adds the RC-level operator
view (brains, plugins, provider, version). Pure data first — `report()` returns a dict and
`render()` a text panel; `show()` opens an optional stdlib-Tkinter window (never required).

CLI:  python -m core.launcher.diagnostics            (boots headless, prints panel)
      python -m core.launcher.diagnostics --json      (report as JSON)
      python -m core.launcher.diagnostics --gui        (Tkinter window)
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from .health import HealthMonitor

log = logging.getLogger("friday.launcher.diagnostics")

# reasoning providers in fallback order (matches the respond pipeline); the "active" one is
# the first with a key present in the environment (secrets are read, never displayed).
_PROVIDERS = (("groq", "GROQ_API_KEY"), ("gemini", "GEMINI_API_KEY"),
              ("openai", "OPENAI_API_KEY"))


class Diagnostics:
    def __init__(self, *, components: Optional[dict] = None) -> None:
        self.components = components or {}

    # ── individual panels ────────────────────────────────────────────────────────
    @staticmethod
    def version() -> dict:
        try:
            from deploy.version import metadata, release_tag
            info = metadata()
            info["build"] = release_tag()
            return info
        except Exception:  # noqa: BLE001 — deploy package optional at runtime
            return {"name": "FRIDAY", "version": "unknown"}

    def brains(self) -> dict:
        brains = self.components.get("brains") or {}
        out = {}
        for name, brain in brains.items():
            status = "online"
            if hasattr(brain, "health"):
                try:
                    h = brain.health()
                    status = h.get("status", "online") if isinstance(h, dict) else "online"
                except Exception:  # noqa: BLE001
                    status = "error"
            out[name] = status
        return out

    def plugins(self) -> dict:
        kernel = self.components.get("kernel")
        plugin = None
        if kernel is not None and hasattr(kernel, "try_get"):
            try:
                plugin = kernel.try_get("plugin")
            except Exception:  # noqa: BLE001
                plugin = None
        if plugin is None:
            return {"available": False, "kinds": [], "count": 0}
        try:
            kinds = list(plugin.kinds())
        except Exception:  # noqa: BLE001
            kinds = []
        return {"available": True, "kinds": kinds, "count": len(kinds)}

    @staticmethod
    def active_provider() -> dict:
        """Report which reasoning provider FRIDAY would use, based on which key is present
        in the environment. Presence only — the key value is never read out or displayed."""
        for name, env in _PROVIDERS:
            if os.environ.get(env):
                return {"provider": name, "source": "env", "configured": True}
        return {"provider": "local-only", "source": "none", "configured": False,
                "detail": "no cloud key present; local reasoning only"}

    def event_bus(self) -> dict:
        rt = self.components.get("runtime")
        if rt is None:
            return {"status": "not started"}
        info: dict = {"status": "constructed"}
        for attr in ("is_running", "running"):
            if hasattr(rt, attr):
                try:
                    val = getattr(rt, attr)
                    info["status"] = "running" if (val() if callable(val) else val) \
                        else "stopped"
                except Exception:  # noqa: BLE001
                    pass
        if hasattr(rt, "health"):
            try:
                h = rt.health()
                if isinstance(h, dict):
                    info.update({k: h[k] for k in ("subscribers", "published", "queue")
                                 if k in h})
            except Exception:  # noqa: BLE001
                pass
        return info

    # ── full report ──────────────────────────────────────────────────────────────
    def report(self) -> dict:
        monitor = HealthMonitor(container=self.components.get("kernel"),
                                runtime=self.components.get("runtime"),
                                coordinator=self.components.get("coordinator"),
                                simulation=self.components.get("simulation"))
        diag = monitor.diagnostics()
        return {
            "version": self.version(),
            "runtime_status": diag.get("status", "unknown"),
            "system": diag.get("system", {}),
            "brains": self.brains(),
            "plugins": self.plugins(),
            "provider": self.active_provider(),
            "event_bus": self.event_bus(),
            "services": diag.get("services", {}),
        }

    # ── rendering ────────────────────────────────────────────────────────────────
    def render(self) -> str:
        r = self.report()
        v = r["version"]
        sysv = r["system"]
        prov = r["provider"]
        lines = [
            f"FRIDAY Diagnostics — v{v.get('version', '?')} "
            f"({v.get('build', v.get('release', '?'))})",
            "=" * 52,
            f"  runtime status : {r['runtime_status']}",
            f"  ai provider    : {prov['provider']}"
            + ("" if prov.get("configured") else "  (local-only)"),
            f"  event bus      : {r['event_bus'].get('status', '?')}",
            f"  cpu / ram      : {sysv.get('cpu_percent', '?')}% / "
            f"{sysv.get('ram_percent', '?')}%   threads: {sysv.get('threads', '?')}",
            "-" * 52,
            f"  brains ({len(r['brains'])}):",
        ]
        for name, status in sorted(r["brains"].items()):
            lines.append(f"     - {name:<18} {status}")
        pl = r["plugins"]
        lines.append(f"  plugins        : {pl['count']} kind(s)"
                     + (f" [{', '.join(pl['kinds'])}]" if pl["kinds"] else ""))
        lines.append("=" * 52)
        return "\n".join(lines)

    # ── optional Tkinter viewer (stdlib; never required) ─────────────────────────
    def show(self) -> bool:
        """Open a simple diagnostics window. Returns False if no display / Tk available."""
        try:
            import tkinter as tk
        except Exception as e:  # noqa: BLE001
            log.info("[Diagnostics] Tk unavailable (%s); use --json/text instead", e)
            return False
        try:
            win = tk.Tk()
            win.title("FRIDAY Diagnostics")
            win.configure(bg="#0b0f14")
            text = tk.Text(win, width=64, height=24, bg="#0b0f14", fg="#19d3ff",
                           insertbackground="#19d3ff", relief="flat",
                           font=("Consolas", 10))
            text.pack(padx=12, pady=12)

            def refresh() -> None:
                text.configure(state="normal")
                text.delete("1.0", "end")
                text.insert("1.0", self.render())
                text.configure(state="disabled")
                win.after(2000, refresh)

            refresh()
            win.mainloop()
            return True
        except Exception as e:  # noqa: BLE001
            log.info("[Diagnostics] window failed: %s", e)
            return False


def from_launcher(launcher) -> Diagnostics:
    """Build a Diagnostics view from a Launcher instance (uses its live components)."""
    return Diagnostics(components=getattr(launcher, "components", {}) or {})


def main(argv: Optional[list] = None) -> int:
    import argparse
    import json
    p = argparse.ArgumentParser(prog="friday-diagnostics",
                                description="FRIDAY diagnostics screen")
    p.add_argument("--json", action="store_true")
    p.add_argument("--gui", action="store_true", help="open the Tkinter diagnostics window")
    args = p.parse_args(argv)

    # boot FRIDAY headless so diagnostics reflect a real (degraded-ok) system
    try:
        from .launcher import Launcher
        launcher = Launcher(profile="production", headless=True)
        launcher.run()
        diag = from_launcher(launcher)
    except Exception as e:  # noqa: BLE001
        log.warning("boot for diagnostics failed: %s", e)
        diag = Diagnostics()

    if args.gui:
        if not diag.show():
            print(diag.render())
    elif args.json:
        print(json.dumps(diag.report(), indent=2, default=str))
    else:
        print(diag.render())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
