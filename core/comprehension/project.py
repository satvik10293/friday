"""
core/comprehension/project.py — FRIDAY 5.x (M64)
She goes into a new project and understands it.

Given a folder, `analyze_project` walks the tree (skipping the usual noise:
.git, node_modules, venvs, build output) and builds a `ProjectUnderstanding`:

  · languages           — file counts per language, and the primary one
  · entry points        — how you actually run it (main.py, manage.py, package
                          .json scripts, cmd/*/main.go, src/main.rs, …)
  · dependencies        — parsed from requirements.txt / pyproject / package.json
                          / go.mod / Cargo.toml, plus the frameworks they imply
  · tests               — is there a test suite, and where
  · structure           — the top-level shape of the repo
  · README summary      — the first real paragraph of the readme
  · Python symbol index — top-level classes/functions per file (AST), so she can
                          answer "where is X" and "what's in this file"

Everything is best-effort and never raises: an unreadable file is skipped, not
fatal. Import is side-effect free.

`understand_project` is the high-level call the assistant uses: it analyses,
records the project in the World Model + core memory (so she remembers it), and
returns a spoken-style summary.
"""

from __future__ import annotations

import ast
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.comprehension.project")

# Directories that are never part of "the code you wrote".
_SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv",
    "env", ".env", "dist", "build", ".idea", ".vscode", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "target", "bin", "obj", ".next",
    ".gradle", ".tox", "site-packages", "vendor", ".cache", "coverage",
    ".DS_Store", "__MACOSX",
}

# Extension → language name. The keys are the vocabulary of "what is this repo".
_LANG_BY_EXT = {
    ".py": "Python", ".pyi": "Python", ".ipynb": "Jupyter",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "Java", ".kt": "Kotlin", ".scala": "Scala",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++", ".hpp": "C++",
    ".cs": "C#", ".swift": "Swift", ".m": "Objective-C",
    ".html": "HTML", ".css": "CSS", ".scss": "CSS",
    ".sh": "Shell", ".ps1": "PowerShell",
    ".sql": "SQL", ".r": "R", ".dart": "Dart", ".lua": "Lua",
    ".vue": "Vue", ".svelte": "Svelte",
}

# Well-known entry-point filenames (checked at any depth, shallow first).
_ENTRY_NAMES = {
    "main.py", "__main__.py", "app.py", "manage.py", "run.py", "wsgi.py",
    "asgi.py", "cli.py", "server.py",
    "index.js", "main.js", "server.js", "app.js", "index.ts", "main.ts",
    "main.go", "main.rs", "Main.java", "Program.cs", "main.cpp",
}

# Dependency name (lowercased substring) → framework/library label.
_FRAMEWORK_HINTS = {
    "django": "Django", "flask": "Flask", "fastapi": "FastAPI",
    "tornado": "Tornado", "aiohttp": "aiohttp", "starlette": "Starlette",
    "react": "React", "next": "Next.js", "vue": "Vue", "svelte": "Svelte",
    "angular": "Angular", "express": "Express", "nestjs": "NestJS",
    "torch": "PyTorch", "tensorflow": "TensorFlow", "keras": "Keras",
    "numpy": "NumPy", "pandas": "pandas", "scikit-learn": "scikit-learn",
    "sklearn": "scikit-learn", "transformers": "HuggingFace Transformers",
    "pytest": "pytest", "unittest": "unittest", "jest": "Jest",
    "spring": "Spring", "gin": "Gin", "actix": "Actix", "rocket": "Rocket",
    "opencv": "OpenCV", "sqlalchemy": "SQLAlchemy", "pydantic": "Pydantic",
    "electron": "Electron", "pygame": "Pygame", "streamlit": "Streamlit",
}

_TEXT_MAX_BYTES = 400_000        # don't read enormous files for LOC/symbols
_MAX_FILES = 6000                # a walk guard on pathological trees
_MAX_PY_SYMBOL_FILES = 2500      # cap AST parsing work (covers large repos)


@dataclass
class ProjectUnderstanding:
    root: str
    name: str
    languages: dict = field(default_factory=dict)         # language -> file count
    primary_language: str = ""
    entry_points: list = field(default_factory=list)
    dependencies: dict = field(default_factory=dict)      # manager -> [packages]
    frameworks: list = field(default_factory=list)
    has_tests: bool = False
    test_locations: list = field(default_factory=list)
    readme_summary: str = ""
    structure: list = field(default_factory=list)         # top-level entries
    key_modules: list = field(default_factory=list)
    file_count: int = 0
    total_loc: int = 0
    git: dict = field(default_factory=dict)
    python_symbols: dict = field(default_factory=dict)    # relpath -> [names]
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    def summary(self) -> str:
        """A warm, spoken-style brief — what this project is and how to work in it."""
        lines = []
        lang = self.primary_language or "mixed"
        fw = ", ".join(self.frameworks[:4]) if self.frameworks else ""
        head = f"{self.name} is a {lang} project"
        if fw:
            head += f" built with {fw}"
        head += f" — {self.file_count} source files"
        if self.total_loc:
            head += f", about {self.total_loc:,} lines"
        lines.append(head + ".")

        if self.entry_points:
            lines.append("You run it from: " + ", ".join(self.entry_points[:4]) + ".")
        if self.key_modules:
            lines.append("The main parts are: " + ", ".join(self.key_modules[:6]) + ".")
        if self.has_tests:
            where = self.test_locations[0] if self.test_locations else "the test suite"
            lines.append(f"It has tests ({where}).")
        else:
            lines.append("I don't see a test suite.")
        if self.readme_summary:
            lines.append("The README says: " + self.readme_summary)
        if self.git.get("branch"):
            g = self.git
            tail = f"On git branch {g['branch']}"
            if g.get("last_commit"):
                tail += f"; last commit: {g['last_commit']}"
            lines.append(tail + ".")
        return "\n".join(lines)


# ── the walk ──────────────────────────────────────────────────────────────────
def _iter_files(root: Path):
    """Yield source files under root, skipping noise dirs. Bounded."""
    count = 0
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = list(d.iterdir())
        except OSError:
            continue
        for p in entries:
            name = p.name
            if p.is_dir():
                if name in _SKIP_DIRS or name.startswith("."):
                    continue
                stack.append(p)
            else:
                count += 1
                if count > _MAX_FILES:
                    return
                yield p


def _read_text(p: Path) -> str:
    try:
        if p.stat().st_size > _TEXT_MAX_BYTES:
            return ""
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


# ── dependency parsers (best-effort, tolerant) ────────────────────────────────
def _parse_requirements(text: str) -> list:
    pkgs = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        name = re.split(r"[<>=!~;\[ ]", line, 1)[0].strip()
        if name:
            pkgs.append(name)
    return pkgs


def _parse_pyproject(text: str) -> list:
    # tolerant: pull quoted requirement strings out of [project].dependencies
    pkgs = []
    for m in re.finditer(r'["\']([A-Za-z0-9_.\-]+)\s*[<>=!~\[]', text):
        pkgs.append(m.group(1))
    return pkgs


def _parse_package_json(text: str) -> tuple:
    """Return (deps, scripts, main). Never raises."""
    try:
        data = json.loads(text)
    except ValueError:
        return [], {}, ""
    deps = list((data.get("dependencies") or {}).keys())
    deps += list((data.get("devDependencies") or {}).keys())
    scripts = data.get("scripts") or {}
    return deps, scripts, str(data.get("main") or "")


def _parse_go_mod(text: str) -> list:
    return re.findall(r"^\s*([\w./\-]+)\s+v[\d.]", text, re.M)


def _parse_cargo(text: str) -> list:
    out, in_deps = [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            in_deps = s.startswith("[dependencies")
            continue
        if in_deps and "=" in s:
            out.append(s.split("=", 1)[0].strip())
    return out


# ── git (read the plumbing directly; no subprocess) ───────────────────────────
def _git_info(root: Path) -> dict:
    g = root / ".git"
    if not g.is_dir():
        return {}
    info: dict = {}
    try:
        head = (g / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = head.split(" ", 1)[1].strip()
            info["branch"] = ref.rsplit("/", 1)[-1]
    except OSError:
        pass
    # last commit subject from the reflog tail (cheap, no git binary needed)
    try:
        reflog = (g / "logs" / "HEAD").read_text(encoding="utf-8").strip().splitlines()
        if reflog:
            last = reflog[-1]
            msg = last.split("\t", 1)[1] if "\t" in last else ""
            info["last_commit"] = msg.split(":", 1)[-1].strip()[:80] or msg[:80]
    except OSError:
        pass
    try:
        cfg = (g / "config").read_text(encoding="utf-8")
        m = re.search(r"url\s*=\s*(.+)", cfg)
        if m:
            info["remote"] = m.group(1).strip()
    except OSError:
        pass
    return info


# ── README ────────────────────────────────────────────────────────────────────
def _readme_summary(root: Path) -> str:
    for name in ("README.md", "README.rst", "README.txt", "README",
                 "readme.md"):
        p = root / name
        if p.exists():
            text = _read_text(p)
            for para in re.split(r"\n\s*\n", text):
                clean = re.sub(r"^[#>*\-\s`]+", "", para).strip()
                clean = re.sub(r"\s+", " ", clean)
                # skip badges / title-only lines
                if len(clean) > 40 and not clean.startswith("!["):
                    return clean[:280]
    return ""


# ── Python symbols (AST) ──────────────────────────────────────────────────────
def _py_symbols(text: str) -> list:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(f"def {node.name}")
        elif isinstance(node, ast.ClassDef):
            names.append(f"class {node.name}")
    return names


# ── the analysis ──────────────────────────────────────────────────────────────
def analyze_project(path) -> Optional[ProjectUnderstanding]:
    """Read a project folder and build an understanding of it. Returns None if
    the path isn't a directory. Never raises."""
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        return None

    u = ProjectUnderstanding(root=str(root), name=root.name)
    lang_counts: dict = {}
    loc = 0
    file_count = 0
    dir_py_counts: dict = {}
    entry_hits: list = []
    py_symbol_files = 0

    for p in _iter_files(root):
        ext = p.suffix.lower()
        lang = _LANG_BY_EXT.get(ext)
        if lang:
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
            file_count += 1
            # LOC + which top-level dir the code lives in
            text = _read_text(p)
            if text:
                loc += text.count("\n") + 1
            try:
                top = p.relative_to(root).parts[0]
            except ValueError:
                top = ""
            if lang == "Python":
                dir_py_counts[top] = dir_py_counts.get(top, 0) + 1
                if py_symbol_files < _MAX_PY_SYMBOL_FILES and text:
                    syms = _py_symbols(text)
                    if syms:
                        rel = str(p.relative_to(root)).replace("\\", "/")
                        u.python_symbols[rel] = syms
                        py_symbol_files += 1
        if p.name in _ENTRY_NAMES:
            rel = str(p.relative_to(root)).replace("\\", "/")
            entry_hits.append(rel)

    u.languages = dict(sorted(lang_counts.items(), key=lambda kv: -kv[1]))
    u.primary_language = next(iter(u.languages), "")
    u.file_count = file_count
    u.total_loc = loc

    # entry points: shallowest first (the real ones live near the root)
    entry_hits.sort(key=lambda r: (r.count("/"), r))
    u.entry_points = entry_hits[:8]

    # dependencies + frameworks — matched against declared dependency NAMES only
    # (matching against file paths gave false positives, e.g. "gin" inside
    # "imaging"/"plugin"). Deps are specific, so a substring match is safe here.
    deps, scripts = _collect_dependencies(root, u)
    dep_hay = [d.lower() for d in deps]
    fw = []
    for hint, label in _FRAMEWORK_HINTS.items():
        if label in fw:
            continue
        if any(hint in d for d in dep_hay):
            fw.append(label)
    u.frameworks = fw
    # npm start script is a real entry point
    if scripts.get("start"):
        u.entry_points.insert(0, "npm start")
    elif scripts.get("dev"):
        u.entry_points.insert(0, "npm run dev")

    # tests
    _detect_tests(root, u)

    # structure (top-level, dirs first)
    try:
        top = [e for e in root.iterdir()
               if not e.name.startswith(".") and e.name not in _SKIP_DIRS]
        top.sort(key=lambda e: (e.is_file(), e.name.lower()))
        u.structure = [e.name + ("/" if e.is_dir() else "") for e in top[:30]]
    except OSError:
        pass

    # key modules: the code dirs with the most Python (or top-level pkg dirs)
    key = sorted((k for k in dir_py_counts if k and (root / k).is_dir()),
                 key=lambda k: -dir_py_counts[k])
    u.key_modules = key[:8]

    u.readme_summary = _readme_summary(root)
    u.git = _git_info(root)

    if not file_count:
        u.notes.append("No recognized source files found — this may not be a code project.")
    return u


def _collect_dependencies(root: Path, u: ProjectUnderstanding) -> tuple:
    """Fill u.dependencies from any manifest present. Returns (all_deps, scripts)."""
    all_deps: list = []
    scripts: dict = {}
    req = root / "requirements.txt"
    if req.exists():
        pk = _parse_requirements(_read_text(req))
        if pk:
            u.dependencies["pip"] = pk[:40]
            all_deps += pk
    pyp = root / "pyproject.toml"
    if pyp.exists():
        pk = _parse_pyproject(_read_text(pyp))
        if pk:
            u.dependencies.setdefault("pip", [])
            u.dependencies["pip"] = (u.dependencies["pip"] + pk)[:40]
            all_deps += pk
    pkgj = root / "package.json"
    if pkgj.exists():
        deps, scripts, _main = _parse_package_json(_read_text(pkgj))
        if deps:
            u.dependencies["npm"] = deps[:40]
            all_deps += deps
    gomod = root / "go.mod"
    if gomod.exists():
        pk = _parse_go_mod(_read_text(gomod))
        if pk:
            u.dependencies["go"] = pk[:40]
            all_deps += pk
    cargo = root / "Cargo.toml"
    if cargo.exists():
        pk = _parse_cargo(_read_text(cargo))
        if pk:
            u.dependencies["cargo"] = pk[:40]
            all_deps += pk
    return all_deps, scripts


def _detect_tests(root: Path, u: ProjectUnderstanding) -> None:
    locations = []
    for cand in ("tests", "test", "__tests__", "spec"):
        if (root / cand).is_dir():
            locations.append(cand + "/")
    for marker in ("pytest.ini", "tox.ini", "jest.config.js", "conftest.py"):
        if (root / marker).exists():
            locations.append(marker)
    # any test_*.py / *_test.go anywhere shallow
    for p in _iter_files(root):
        n = p.name
        if n.startswith("test_") and n.endswith(".py") or n.endswith("_test.go") \
                or n.endswith(".test.js") or n.endswith(".spec.ts"):
            locations.append("test files present")
            break
    u.test_locations = sorted(set(locations))
    u.has_tests = bool(u.test_locations)


# ── symbol lookup: "where is X?" ──────────────────────────────────────────────
def find_symbol(understanding: ProjectUnderstanding, name: str) -> list:
    """Find files defining a class/function whose name matches `name` (case-
    insensitive substring). Returns [(relpath, symbol)]."""
    q = (name or "").strip().lower()
    if not q:
        return []
    hits = []
    for rel, syms in understanding.python_symbols.items():
        for s in syms:
            bare = s.split(" ", 1)[-1].lower()
            if q == bare or q in bare:
                hits.append((rel, s))
    # exact matches first
    hits.sort(key=lambda rs: (q != rs[1].split(" ", 1)[-1].lower(), rs[0]))
    return hits[:20]


# ── the high-level call the assistant uses ────────────────────────────────────
def understand_project(path=None, *, world_model=None, memory=None) -> dict:
    """Analyse a project and REMEMBER it: record it in the World Model and core
    memory so she can help with it later. Returns {'ok', 'summary', 'understanding'}.
    Never raises."""
    try:
        target = path or "."
        u = analyze_project(target)
        if u is None:
            return {"ok": False,
                    "summary": f"I couldn't find a project folder at {target}.",
                    "understanding": None}

        # 1) World Model — the project becomes a first-class entity she tracks
        try:
            if world_model is None:
                from core.world.world_model import WorldModel
                world_model = WorldModel()
            world_model.observe(
                "project", u.name,
                state={"primary_language": u.primary_language,
                       "frameworks": u.frameworks,
                       "entry_points": u.entry_points[:4],
                       "has_tests": u.has_tests,
                       "root": u.root},
                attributes={"file_count": u.file_count, "loc": u.total_loc,
                            "key_modules": u.key_modules},
            )
        except Exception:  # noqa: BLE001 — memory is best-effort, never fatal
            log.debug("world-model record failed", exc_info=True)

        # 2) Core memory — a standing note so she remembers this project (project
        #    facts, not personal → not private to the cloud boundary either way)
        try:
            if memory is None:
                from core.memory.core_memory import get_core_memory
                memory = get_core_memory()
            memory.save(
                name=f"project {u.name}",
                description=(f"{u.primary_language} project at {u.root} "
                             f"({u.file_count} files)")[:200],
                body=u.summary() + f"\n\nRoot: {u.root}",
                type="project", private=True,
            )
        except Exception:  # noqa: BLE001
            log.debug("core-memory record failed", exc_info=True)

        return {"ok": True, "summary": u.summary(), "understanding": u}
    except Exception:  # noqa: BLE001 — comprehension must never break a turn
        log.debug("understand_project failed", exc_info=True)
        return {"ok": False,
                "summary": "I hit a snag reading that project.",
                "understanding": None}
