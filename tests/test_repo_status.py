"""Tests for read-only Git introspection (core.infra.repo_status).

These build a throwaway Git repo in tmp_path, so they never depend on the state of
the project's own repository.
"""

import shutil
import subprocess

import pytest

from core.infra.repo_status import RepoStatus, get_repo_status

_GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(_GIT is None, reason="git not installed")


def _run(repo, *args):
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   capture_output=True, text=True)


@pytest.fixture
def temp_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init")
    _run(repo, "config", "user.email", "test@friday.local")
    _run(repo, "config", "user.name", "FRIDAY Test")
    _run(repo, "config", "commit.gpgsign", "false")
    (repo / "models").mkdir()
    (repo / "models" / "demo.yaml").write_text("a: 1\n", encoding="utf-8")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "M1 complete")
    return repo


def test_available_and_branch(temp_repo):
    rs = RepoStatus(temp_repo)
    assert rs.git_installed() is True
    assert rs.is_repo() is True
    assert rs.available() is True
    assert rs.branch()                      # some branch name (master/main)


def test_latest_commit(temp_repo):
    rs = RepoStatus(temp_repo)
    c = rs.latest_commit()
    assert c["subject"] == "M1 complete"
    assert len(c["hash"]) == 40 and c["short"] and c["date"]


def test_clean_then_dirty(temp_repo):
    rs = RepoStatus(temp_repo)
    assert rs.is_dirty() is False
    (temp_repo / "models" / "demo.yaml").write_text("a: 2\n", encoding="utf-8")
    assert rs.is_dirty() is True
    assert "models/demo.yaml" in rs.modified_files()


def test_file_history_add_and_modify(temp_repo):
    _run(temp_repo, "add", "-A")            # nothing new yet
    # modify + commit a second time
    (temp_repo / "models" / "demo.yaml").write_text("a: 2\n", encoding="utf-8")
    _run(temp_repo, "add", "-A")
    _run(temp_repo, "commit", "-m", "M2 complete")
    rs = RepoStatus(temp_repo)
    hist = rs.file_history("models/demo.yaml")
    assert len(hist) == 2
    assert rs.file_last_modified("models/demo.yaml")["subject"] == "M2 complete"
    assert rs.file_added("models/demo.yaml")["subject"] == "M1 complete"


def test_milestone_tags(temp_repo):
    _run(temp_repo, "tag", "m1-complete")
    rs = RepoStatus(temp_repo)
    assert "m1-complete" in rs.tags("m*")


def test_status_payload(temp_repo):
    rs = RepoStatus(temp_repo)
    s = rs.status()
    assert s["available"] is True
    assert s["latest_commit"]["subject"] == "M1 complete"
    assert "branch" in s and "dirty" in s and "modified_files" in s


def test_health(temp_repo):
    rs = RepoStatus(temp_repo)
    h = rs.health()
    assert h["available"] is True and h["status"] == "clean"


def test_graceful_when_not_a_repo(tmp_path):
    rs = RepoStatus(tmp_path)               # a bare dir, not a git repo
    assert rs.available() is False
    assert rs.status() == {"available": False, "git_installed": rs.git_installed(),
                           "repo_root": str(tmp_path)}
    assert rs.health()["status"] == "unversioned"
    assert rs.file_history("anything") == []


def test_path_arg_not_treated_as_option(temp_repo):
    # a pathspec that looks like a flag must not crash or be parsed as an option
    rs = RepoStatus(temp_repo)
    assert rs.file_history("--all") == []    # no such path → empty, no error


def test_side_effect_free_import():
    import importlib
    importlib.import_module("core.infra.repo_status")
