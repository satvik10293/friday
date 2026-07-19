"""
Packaging regression guards (M59, audit-driven — docs/AUDIT_2026-07.md §2).

FRIDAY "runs outside the IDE" only while three invariants hold; each broke
silently at least once before this audit, so each is pinned here:

1. every third-party package imported at module top level in core/ is declared
   in requirements.txt (Pillow and opencv-python were missing → tray icons and
   gesture control were silently dead in fresh installs)
2. the one-file installer stays stdlib-only (an eager core import once
   ballooned the freeze to 367 MB) and declares its lazily-exported deploy
   modules as hidden imports (PEP 562 laziness hides them from PyInstaller)
3. the source payload includes the current tree — new subsystems (reasoning,
   nervous, screen sight, the agentic workflow) must never be silently
   excluded, and secrets/data must never be silently INCLUDED
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_REQUIREMENTS = (_ROOT / "requirements.txt").read_text(encoding="utf-8").lower()

# import name → requirements.txt package name, where they differ
_PKG_NAME = {
    "pil": "pillow", "cv2": "opencv-python", "faiss": "faiss-cpu",
    "google": "google-generativeai", "edge_tts": "edge-tts",
    "faster_whisper": "faster-whisper", "flask_cors": "flask-cors",
    "sentence_transformers": "sentence-transformers",
    "rapidocr_onnxruntime": "rapidocr-onnxruntime",
    "dotenv": "python-dotenv",
}
# imports that are deliberately OPTIONAL (guarded at use, degrade gracefully)
# or provided by another declared package — each entry is a decision, not a gap
_ALLOWED_MISSING = {
    "llama_cpp",          # optional local-model substrate (M54) — user-pulled
    "huggingface_hub",    # only for the optional --pull path
    "winrt",              # transitive of winocr (platform-marked)
    "objc",               # transitive of pyobjc (darwin-marked)
    "pyi_splash",         # PyInstaller runtime-only helper
}
_LOCAL_TOP = {"core", "deploy", "tests", "trading_ai", "legacy", "friday_launch",
              "friday_spine", "friday_app", "setup"}

def _top_level_imports(py: Path) -> set:
    """Module-level import targets only (via ast — no docstring false
    positives). Function-local imports are runtime-optional by convention in
    this codebase and deliberately not counted."""
    import ast
    names = set()
    try:
        tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return names
    for node in tree.body:                      # top-level statements only
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0].lower() for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0].lower())
    return names


def _third_party_imports(package_dir: Path) -> set:
    stdlib = {m.lower() for m in sys.stdlib_module_names} | {"__future__"}
    found = set()
    for py in package_dir.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        for name in _top_level_imports(py):
            if name in stdlib or name in _LOCAL_TOP:
                continue
            found.add(name)
    return found


# ── 1. requirements ↔ imports drift ───────────────────────────────────────────

def test_every_core_top_level_import_is_in_requirements():
    missing = []
    for name in sorted(_third_party_imports(_ROOT / "core")):
        if name in _ALLOWED_MISSING:
            continue
        pkg = _PKG_NAME.get(name, name)
        if pkg.lower() not in _REQUIREMENTS:
            missing.append(f"{name} (requirements name: {pkg})")
    assert not missing, (
        "core/ imports these at module top level but requirements.txt does "
        "not declare them — fresh installs will lose the features that need "
        f"them: {missing}")


def test_audit_regressions_stay_fixed():
    # the two packages the 2026-07 audit found missing — never again
    assert "pillow" in _REQUIREMENTS
    assert "opencv-python" in _REQUIREMENTS


# ── 2. the installer freeze stays slim and complete ───────────────────────────

def test_installer_modules_are_stdlib_only():
    stdlib = {m.lower() for m in sys.stdlib_module_names} | {"__future__"}
    offenders = []
    for py in [*(_ROOT / "deploy" / "setup").glob("*.py"),
               _ROOT / "deploy" / "build.py", _ROOT / "deploy" / "version.py"]:
        for name in _top_level_imports(py):
            if name not in stdlib and name not in _LOCAL_TOP:
                offenders.append(f"{py.name}: {name}")
    assert not offenders, (
        "the one-file installer must stay stdlib-only (a heavy import once "
        f"made a 367 MB setup exe): {offenders}")


def test_freeze_declares_the_lazy_deploy_modules_as_hidden_imports():
    src = (_ROOT / "deploy" / "setup" / "build_setup.py").read_text(
        encoding="utf-8")
    for mod in ("deploy.build", "deploy.version", "deploy.setup.detect",
                "deploy.setup.recommend", "deploy.setup.installer"):
        assert mod in src, (
            f"build_setup no longer declares {mod} as a hidden import — "
            "deploy/__init__'s lazy exports hide it from PyInstaller")


# ── 3. payload completeness (and exclusion) ───────────────────────────────────

def test_payload_includes_every_current_subsystem():
    from deploy.build import _included
    must_ship = [
        "core/reasoning/engine.py",          # M54 deliberate mind
        "core/reasoning/native.py",          # M56 native mind
        "core/reasoning/tokens.py",          # M57 token mind
        "core/reasoning/neural.py",          # M58 neural core
        "core/nervous/system.py",            # M50 + M59 reload
        "core/executive/agentic.py",         # M59 agentic workflow
        "core/knowledge/distiller.py",       # M55 notebook
        "core/io/screen.py",                 # M52 screen sight
        "core/io/overlay.py",                # M51 overlay
        "core/io/models/hand_landmarker.task",   # gesture model asset
        "friday_launch.py", "requirements.txt", "deploy/bootstrap.py",
    ]
    missing = [p for p in must_ship if not _included(Path(p))]
    assert not missing, f"payload filter would exclude: {missing}"
    for path in must_ship:
        assert (_ROOT / path).exists(), f"expected shipped file missing: {path}"


def test_payload_never_ships_secrets_or_user_data():
    from deploy.build import _included
    for forbidden in (".env", "data/chronicle.db", "data/tokenizer.json",
                      "models/llm/weights.gguf", "friday_config.local.json"):
        assert not _included(Path(forbidden)), f"payload would leak {forbidden}"
