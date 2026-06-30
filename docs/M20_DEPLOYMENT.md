# M20 — Productization, Deployment & Release Engineering (FRIDAY V3)

> **Status:** complete (awaiting review). **Goal:** turn the finished cognitive
> architecture (M1–M19) into a production-ready, cross-platform, releasable application —
> **without redesigning the architecture**. Adds a production launcher, an installer +
> build/release framework, structured rotating logging, health diagnostics, and repository
> release-readiness. Additive only; one Python codebase for Windows / macOS / Linux.

---

## 1. Launcher architecture (`core/launcher/`)

The launcher brings FRIDAY up and keeps it observable — it contains **no cognitive logic**.

| Module | Role |
|---|---|
| `platform_adapter.py` | The single place that knows OS differences: `detect_os()`, data/config/log dirs (env-overridable, no hardcoded paths), desktop shortcut creation. |
| `logging_config.py` | Structured **rotating** logging — console + `friday.log` + `friday-error.log` (`RotatingFileHandler`, size-capped, backups). Idempotent. |
| `health.py` | `HealthMonitor` — aggregates service/runtime/coordinator/simulation health + process vitals (threads, CPU, RAM via psutil when present). |
| `startup.py` | `StartupSequence` — the ordered, graceful boot (below). |
| `launcher.py` | `Launcher` — detect OS → load config → validate deps → run startup → report health → recover; CLI `main()`. |
| `friday_launch.py` (root) | Production entry point. |

```
python friday_launch.py                 # headless boot + human-readable report
python friday_launch.py --json          # machine-readable startup report
python friday_launch.py --profile development --start-runtime
```

## 2. Runtime startup diagram

```
Configuration → Kernel(DI container) → Runtime → Memory(brains) → Knowledge(graph) →
Perception(brains) → Simulation → Coordinator → Executive → Plugins → Voice → UI → READY
```

Each stage is **isolated**: a failure is recorded (`failed`) and the sequence continues
(graceful degradation); optional stages (`voice`, `ui`) are `skipped` when headless or a
backend is absent. Verified boot: all 13 stages, **FRIDAY READY in ~300 ms** on CPU.

## 3. Installer architecture (`deploy/`)

One cross-platform installer (`deploy/install.py`); per-OS specifics delegate to the
platform adapter. Steps: verify Python ≥ 3.10 → install dependencies (`pip -r
requirements.txt`) → validate `friday_config.json` → **securely** capture the (temporary)
Groq reasoning key into a gitignored `.env` (never embedded/printed/logged/committed) →
create desktop shortcut → write uninstall info → prepare logs. `--dry-run` makes it fully
testable without mutating the system.

```
python -m deploy.install            # interactive (prompts for the Groq key via getpass)
python -m deploy.install --dry-run  # validate without changing anything
python -m deploy.install --no-key   # skip the key prompt
```

## 4. Release packaging (`deploy/`)

| Module | Role |
|---|---|
| `version.py` | Single source of truth: `VERSION = 0.20.0`, metadata, `python_ok()`. |
| `build.py` | `build_package()` → clean source zip (excludes `.venv`/`.git`/`data`/caches/**secrets**/**weights**) + manifest + **SHA-256**; `verify_package()` (CRC + checksum + exclusion safety). |
| `release.py` | `generate_changelog()` (from `FRIDAY_4.0_CHANGES.md`), `release_manifest()` (version + artifacts + checksums), `verify_release()`. |

```
python -m deploy.build              # build + verify a source package into dist/
python -m deploy.release --manifest # assemble the release manifest
```

> **Native installers** (PyInstaller `.exe`, macOS `.app`/`.pkg`, Linux package) are
> produced by per-platform CI from this same verified source tree — the OS toolchains run
> on their native platforms. This repo ships the verifiable payload + scripts, not
> prebuilt binaries (binaries are never committed).

## 5. Configuration & environments

Everything stays configuration-driven. The launcher reads `friday_config.json` and a
`--profile {development,testing,production}`; `development` keeps data project-local,
production resolves OS-standard dirs. No hardcoded paths. Secrets only via `.env`.

## 6. Logging & health

Structured logging with rotation (console + rotating file + dedicated error log). Health
diagnostics expose service/runtime/coordinator/simulation status + threads/CPU/RAM through
`HealthMonitor.diagnostics()`; the launcher includes it in the startup report.

## 7. Plugin validation

Plugins register through the `PluginService` (M16) and run behind the brains' never-raises
boundary — a failing plugin/brain is isolated and the society continues (verified by the
coordinator graceful-degradation tests). The startup `plugins` stage reports the registry
state.

## 8. Cross-platform report

Single Python codebase; only `platform_adapter` + the orb/shortcut creation branch per OS.
Pure-stdlib launcher/deploy code, no OS-specific logic elsewhere, portable paths
(pathlib + env), portable SQLite. The orb launcher (`friday_orb.py`) and `friday_launch.py`
both run on Windows/macOS/Linux.

## 9. Test results

`tests/test_launcher.py` + `tests/test_deploy.py` cover platform adapter, rotating logging,
the ordered startup sequence (+ graceful recovery), health diagnostics, the launcher boot,
version metadata, the installer (dry-run + **secret-never-leaked**), build packaging
(checksum + **no secrets/weights leaked** + tamper detection), and release changelog/
manifest verification. All green; the complete suite (M1–M20) is green.

## 10. Repository readiness

`README.md`, `LICENSE` (proprietary placeholder), `CONTRIBUTING.md`, `.gitignore`
(secrets/data/weights/`dist`/`build` excluded), `requirements.txt`, full `docs/`,
`friday_config.json` template — all present. No secrets, temporary, or debug artifacts in
version control (`.env`/`data/*.db`/weights/`.venv` ignored).

## 11. Known limitations

- Native installer binaries are produced by platform CI, not in this repo (by design).
- The launcher boots the cognitive kernel headless; full UI/voice handoff is started
  separately (`friday_app.py`) and is environment-dependent.
- Health vitals (CPU/RAM) need `psutil` (optional) for full detail; degrade gracefully
  without it.

## 12. Recommendations before v1.0

- Wire CI (GitHub Actions) to run the suite + `deploy.build`/`verify` and produce per-OS
  installer artifacts on tag.
- Choose the definitive `LICENSE` (open-source or commercial) before any public release.
- Add a code-signing step for the Windows/macOS installers.
- Run the launcher's `--start-runtime` path through a long-running soak test.

See `core/launcher/` and `deploy/` for the implementation; the production audit is in
`docs/PRODUCTION_AUDIT.md`.
