"""Compatibility entry point for FRIDAY's production Orb.

The Orb is the primary FRIDAY interface. This file remains so existing shortcuts and
installer entries keep working, but it no longer launches a separate Tk stub.
"""

from __future__ import annotations

from friday_orb_app import main


if __name__ == "__main__":
    raise SystemExit(main())
