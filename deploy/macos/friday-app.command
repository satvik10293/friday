#!/bin/bash
# friday-app.command — FRIDAY V3 (M53)
# Launch FRIDAY on macOS as a background app: the tray (menu-bar) presence +
# the private overlay + voice, detached from the Terminal. Double-click in
# Finder, or run from a shell. The mac counterpart of deploy/windows/
# friday-app.vbs.
#
# UNVERIFIED on a real Mac (written on Windows) — the launch path is standard,
# but menu-bar tray / overlay behaviour needs testing on macOS.

# resolve the install root (this file lives at <root>/deploy/macos/)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

PY="$ROOT/.venv/bin/python"
BOOT="$ROOT/deploy/bootstrap.py"

if [[ -x "$PY" && -f "$BOOT" ]]; then
    cd "$ROOT" || exit 1
    # detached: survives closing the Terminal window; logs go to data/logs
    nohup "$PY" "$BOOT" >/dev/null 2>&1 &
    disown
else
    osascript -e 'display alert "FRIDAY" message "Not fully installed yet (missing venv or bootstrap). Re-run the installer, then retry."'
fi
