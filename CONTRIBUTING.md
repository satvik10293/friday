# Contributing to FRIDAY

FRIDAY is a private project. These notes keep contributions consistent with the
architecture and quality bar.

## Principles

- **Additive, never destructive.** Build on completed milestones; do not rewrite them
  except to fix a verified defect. Preserve public APIs and backward compatibility.
- **Service-mediated.** From M16 on, subsystems communicate only through the
  dependency-injected services (`core/services`) and the Runtime / Situation-Report buses.
  Do not import another subsystem's internals (no circular imports).
- **Side-effect-free imports.** Importing `core` must open nothing — no I/O, threads, DB,
  model loads, or sockets at import time.
- **Never-raises hot paths.** Perception, brains, the coordinator, and the simulation
  pipeline must isolate failures and degrade gracefully — a fault must never crash the
  Cognitive Core.
- **Configuration-driven.** No hardcoded paths, values, or OS behavior. Add tunables to a
  typed `*Config` with a tolerant `from_dict`.

## Workflow

1. Read the relevant `docs/M*.md` and `FRIDAY_4.0_CHANGES.md` before changing a subsystem.
2. Keep each module to one responsibility (mirror the existing package layout).
3. Add tests for every public service (`tests/test_*.py`); they must run fast and offline.
4. Run the suite: `python -m pytest -q`. Fix verified defects only.
5. Run a quick audit: no unused imports, no circular imports, side-effect-free import,
   stdlib-or-existing-deps only, no hardcoded paths.
6. Update the milestone doc + `FRIDAY_4.0_CHANGES.md`.

## Secrets & data

- API keys live in a gitignored `.env` (loaded by `core/infra/friday_secrets.py`) — never
  in code, config, or commits.
- `data/*.db`, model weights, and `.venv/` are gitignored. Never commit them.

## Commits

- One logical commit per milestone; end commit messages with the project's
  `Co-Authored-By` trailer. Tag completed milestones `m<NN>-complete`.
- Do not push or publish without the owner's explicit confirmation.
