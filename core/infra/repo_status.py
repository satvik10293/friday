"""
core/infra/repo_status.py — FRIDAY 4.0
Read-only Git introspection. Lets FRIDAY answer reproducibility/recoverability
questions from her own repository history:

    • current branch · latest commit · modified files · is the tree dirty?
    • when was a file (e.g. a model config) added / last modified, and in which
      commit / milestone tag?

This is the data a future Mission Control "Repository health" panel will render.
Safe and side-effect-free: it only ever runs read-only `git` commands with fixed
arguments (no user input is interpolated into a command), and it degrades
gracefully to {available: False} when Git is missing or the directory is not a repo.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.infra.repo_status")

_ROOT = Path(__file__).resolve().parents[2]


class RepoStatus:
    def __init__(self, repo_root: Optional[str | Path] = None, *, timeout: float = 5.0) -> None:
        self.repo_root = Path(repo_root) if repo_root else _ROOT
        self._timeout = timeout

    # ── low-level git runner (read-only, fixed args) ────────────────────────────
    def _git(self, *args: str) -> Optional[str]:
        """Run a read-only git command; return stripped stdout, or None on any
        failure (git missing, not a repo, non-zero exit)."""
        try:
            proc = subprocess.run(
                ["git", *args], cwd=str(self.repo_root), capture_output=True,
                text=True, timeout=self._timeout, check=False)
        except (FileNotFoundError, OSError, subprocess.SubprocessError) as e:
            log.debug("git unavailable: %s", e)
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.strip()

    # ── availability ───────────────────────────────────────────────────────────
    def git_installed(self) -> bool:
        return self._git("--version") is not None

    def is_repo(self) -> bool:
        return self._git("rev-parse", "--is-inside-work-tree") == "true"

    def available(self) -> bool:
        return self.is_repo()

    # ── snapshot fields ─────────────────────────────────────────────────────────
    def branch(self) -> Optional[str]:
        return self._git("rev-parse", "--abbrev-ref", "HEAD")

    def latest_commit(self) -> Optional[dict]:
        out = self._git("log", "-1", "--pretty=%H%x1f%h%x1f%s%x1f%an%x1f%cI")
        if not out:
            return None
        parts = out.split("\x1f")
        if len(parts) < 5:
            return None
        return {"hash": parts[0], "short": parts[1], "subject": parts[2],
                "author": parts[3], "date": parts[4]}

    def is_dirty(self) -> bool:
        out = self._git("status", "--porcelain")
        return bool(out)

    def modified_files(self) -> list[str]:
        out = self._git("status", "--porcelain")
        if not out:
            return []
        files = []
        for line in out.splitlines():
            # porcelain: 'XY <path>'. Split off the status code robustly (the
            # leading column may have been whitespace-trimmed upstream).
            parts = line.strip().split(None, 1)
            files.append(parts[-1] if parts else line.strip())
        return files

    def tags(self, pattern: str = "*") -> list[str]:
        out = self._git("tag", "--list", pattern)
        return out.splitlines() if out else []

    # ── per-file / per-model history ────────────────────────────────────────────
    def file_history(self, path: str, limit: int = 20) -> list[dict]:
        """Commits that touched `path`, newest first. Answers 'when added / last
        modified / which commit'. `path` is passed to git after `--`, so it is
        treated strictly as a pathspec, never as an option."""
        out = self._git("log", f"-{int(limit)}", "--follow",
                        "--pretty=%H%x1f%h%x1f%s%x1f%cI", "--", path)
        if not out:
            return []
        history = []
        for line in out.splitlines():
            parts = line.split("\x1f")
            if len(parts) >= 4:
                history.append({"hash": parts[0], "short": parts[1],
                                "subject": parts[2], "date": parts[3]})
        return history

    def file_added(self, path: str) -> Optional[dict]:
        """The commit that first introduced `path` (its oldest history entry)."""
        history = self.file_history(path, limit=1000)
        return history[-1] if history else None

    def file_last_modified(self, path: str) -> Optional[dict]:
        history = self.file_history(path, limit=1)
        return history[0] if history else None

    # ── aggregate snapshot (Mission Control payload) ────────────────────────────
    def status(self) -> dict:
        if not self.available():
            return {"available": False, "git_installed": self.git_installed(),
                    "repo_root": str(self.repo_root)}
        return {
            "available": True,
            "repo_root": str(self.repo_root),
            "branch": self.branch(),
            "latest_commit": self.latest_commit(),
            "dirty": self.is_dirty(),
            "modified_files": self.modified_files(),
            "milestone_tags": self.tags("m*"),
        }

    def health(self) -> dict:
        if not self.available():
            return {"status": "unversioned", "available": False}
        return {"status": "clean" if not self.is_dirty() else "dirty",
                "available": True, "branch": self.branch(),
                "modified": len(self.modified_files())}


def get_repo_status(repo_root: Optional[str | Path] = None) -> RepoStatus:
    return RepoStatus(repo_root)
