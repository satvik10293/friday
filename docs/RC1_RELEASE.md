# FRIDAY — Release Candidate 1 (RC1)

**Build tag:** `0.20.0-rc1` · **Channel:** `rc` · **Platform:** Windows (validated); macOS/Linux
share the same core + bootstrap · **Requires:** Python 3.10+ (CPU-first).

RC1 is the first **installable** FRIDAY build, intended for real-world testing — not a feature
milestone. It packages the completed M1–M20 cognitive stack behind an installer, a first-run
wizard, a diagnostics screen, and verbose logging, so bugs, crashes, missing dependencies, and
UX problems can be found before development continues.

---

## Packaging model (why there is no single frozen .exe)

FRIDAY depends on a heavy, CPU-first ML stack (mediapipe, faster-whisper, faiss, torch). Freezing
that into one binary is multi-gigabyte and notoriously fragile. RC1 instead uses the standard model
for this class of app — **ship source + a self-provisioning bootstrap**:

- `deploy/bootstrap.py` creates an isolated `.venv` beside the app on first run, installs the pinned
  `requirements.txt` into it, runs the first-run wizard, and launches FRIDAY with that interpreter.
- Subsequent launches skip straight to start-up (venv + first-run marker already exist).

A **native compiled installer** (`Setup.exe`) can still be produced from the same tree via
`deploy/windows/friday.iss` (Inno Setup 6+) when that toolchain is available — it wraps the identical
bootstrap. This is the optional path; the PowerShell installer below needs no external tooling.

---

## 1. Install

### Windows (recommended)
Run **`Install-FRIDAY.bat`** (double-click) or:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1
```

The installer: welcome + license → install-directory prompt → copy runtime files (excluding vcs /
venv / data / caches / secrets) → create the config folder → provision the `.venv` → create **Desktop
+ Start-Menu** shortcuts → register an **Add/Remove Programs** uninstall entry → verify → optionally
launch. Silent/unattended: `-InstallDir "C:\Apps\FRIDAY" -Silent -NoLaunch`.

### Portable / any OS
Unzip `friday-0.20.0.zip` and run:

```bash
python deploy/bootstrap.py            # provision venv + first-run, then launch the orb
python deploy/bootstrap.py --entry app   # launch the HUD instead
```

### Native compiled installer (optional)
```powershell
iscc deploy\windows\friday.iss        # → dist\FRIDAY-Setup-0.20.0-rc1.exe
```

---

## 2. First-run wizard

Runs once (guarded by a marker under the data dir). It detects the **OS**, verifies the **Python
runtime**, probes **microphone / speakers / camera**, captures the optional **Groq reasoning key**
into a gitignored `.env` (never printed, logged, or embedded), writes `friday_config.json`, and
reports **FRIDAY Ready**.

```bash
python -m core.launcher.first_run          # interactive
python -m core.launcher.first_run --json    # non-interactive report
```

Every device probe is best-effort and never fatal — a missing webcam or audio backend downgrades the
relevant subsystem, it does not block startup.

---

## 3. Startup & runtime verification

The launcher boots subsystems in a fixed, graceful order (`configuration → kernel → runtime → memory →
knowledge → perception → simulation → coordinator → executive → plugins → voice → ui → ready`); any
stage failure is logged and isolated so FRIDAY still reaches a usable (possibly degraded) state.

```bash
python friday_launch.py --json        # full startup + health report
python friday_launch.py --diagnostics # boot then print the diagnostics screen
```

---

## 4. Diagnostics

```bash
python -m core.launcher.diagnostics          # text panel
python -m core.launcher.diagnostics --json    # machine-readable
python -m core.launcher.diagnostics --gui     # Tkinter window (auto-refresh)
```

Shows: version/build, runtime status, the Cognitive Brains and their health, loaded plugins, the
**active AI provider** (presence-based; key values are never shown), event-bus/runtime status, and
process vitals (CPU / RAM / threads).

---

## 5. Logging

Verbose, rotating logs are configured at startup (`RotatingFileHandler`, 5 MB × 5):

- `data/logs/friday.log` — console + full runtime stream.
- `data/logs/friday-error.log` — errors only (fast triage).

Installer/bootstrap progress prints to the console. Override the location with `FRIDAY_LOG_DIR`.

---

## 6. Release packaging

`python -m deploy.rc` builds, into `dist/` (gitignored):

| Artifact | Description |
|---|---|
| `friday-0.20.0.zip` | Portable package (clean source + bootstrap + installer assets), SHA-256 verified |
| `RELEASE_NOTES-0.20.0-rc1.md` | Generated release notes (install, milestones, known issues, test checklist) |
| `RC-0.20.0-rc1.manifest.json` | RC manifest: build tag, package checksum + size, known issues, checklist |

The build excludes `.git`, `.venv`, `data/`, caches, `*.db`, `.env`, and model weights, and the
verifier fails if any excluded/secret pattern leaks into the archive.

---

## 7. Test summary

- **Automated:** full suite green (M1–M20 + RC1). RC1 adds `tests/test_first_run.py`,
  `tests/test_diagnostics.py`, `tests/test_rc_build.py` (secrets-never-leak, idempotent first-run,
  graceful device probes, verified/clean package).
- **Manual checklist** (please run on the test laptop):
  1. Clean install into an empty directory → venv provisions → **Ready**.
  2. First-run wizard detects OS/mic/speaker/camera and captures the key.
  3. `python friday_launch.py --json` → all stages ok/skipped, health `ok`.
  4. `python -m core.launcher.diagnostics` → brains, provider, vitals shown.
  5. Shutdown leaves no orphaned processes.
  6. Re-install over an existing install → `data/`, `.env`, config preserved.

---

## 8. Known issues / limitations

- No compiled single-file `.exe` in RC1 (bootstrap model, above). Native `Setup.exe` via `friday.iss`
  when Inno Setup is present.
- First launch installs ~50 dependencies into the venv — several minutes, needs network access.
- Without a cloud key in `.env`, FRIDAY runs **local-only** (flan-t5); no cloud fallback.
- Voice / gesture / vision require optional hardware + backends; each degrades gracefully if absent.
- Desktop integration (shortcuts, native HUD window) validated on **Windows** only.
- `docs/PRODUCTION_AUDIT.md` predates M18–M20 (refresh scheduled).

---

## 9. Deliverables (locations)

| Deliverable | Location |
|---|---|
| Installer (no tooling) | `deploy/windows/install.ps1` · `Install-FRIDAY.bat` |
| Native installer script | `deploy/windows/friday.iss` (Inno Setup) |
| Uninstaller | `deploy/windows/uninstall.ps1` |
| Launcher (executable entry) | `Launch-FRIDAY.bat` → `deploy/bootstrap.py` → orb/HUD |
| First-run wizard | `core/launcher/first_run.py` |
| Diagnostics | `core/launcher/diagnostics.py` |
| Build output | `dist/friday-0.20.0.zip` (+ notes + manifest) |
| Version / build tag | `deploy/version.py` → `0.20.0-rc1` |

_Report bugs with: FRIDAY build tag, your OS, and the tail of `data/logs/friday-error.log`._
