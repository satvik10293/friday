"""Tests for the RC1 first-run wizard (core/launcher/first_run.py)."""

from __future__ import annotations

import json

from core.launcher.first_run import CheckResult, FirstRunReport, FirstRunWizard


def _wizard(tmp_path):
    (tmp_path / "data").mkdir()
    return FirstRunWizard(root=tmp_path,
                          platform=_FakePlatform(tmp_path))


class _FakePlatform:
    """Minimal PlatformAdapter stand-in that keeps all paths inside tmp_path."""

    def __init__(self, root):
        self.os = "windows"
        self._root = root

    def data_dir(self):
        return self._root / "data"

    def config_dir(self):
        return self._root

    def log_dir(self):
        return self._root / "data" / "logs"

    def ensure_dirs(self):
        for d in (self.data_dir(), self.log_dir()):
            d.mkdir(parents=True, exist_ok=True)


def test_import_is_side_effect_free():
    # importing must not probe devices or write anything (already imported at top)
    import core.launcher.first_run as m
    assert hasattr(m, "FirstRunWizard")


def test_first_run_completes_and_is_idempotent(tmp_path):
    w = _wizard(tmp_path)
    assert w.is_first_run() is True
    report = w.run(groq_key=None)
    assert report.completed is True
    assert report.already_done is False
    assert w.is_first_run() is False           # marker written
    # second run short-circuits
    again = w.run()
    assert again.already_done is True


def test_runtime_check_ok():
    w = FirstRunWizard()
    r = w.check_runtime()
    assert r.name == "runtime"
    assert r.status == "ok"                    # test runner is 3.10+


def test_secret_written_to_env_and_never_returned(tmp_path):
    w = _wizard(tmp_path)
    env = tmp_path / ".env"
    ok = w.configure_secret("secret-key-123", env_path=env)
    assert ok is True
    content = env.read_text(encoding="utf-8")
    assert "GROQ_API_KEY=secret-key-123" in content
    # the report never carries the key value
    report = FirstRunReport(secret_configured=True)
    assert "secret-key-123" not in json.dumps(report.to_dict())


def test_blank_key_is_skipped(tmp_path):
    w = _wizard(tmp_path)
    assert w.configure_secret("") is False
    assert w.configure_secret("   ") is False
    assert w.configure_secret(None) is False


def test_config_written_only_when_absent(tmp_path):
    w = _wizard(tmp_path)
    assert w.write_config() is True
    cfg = tmp_path / "friday_config.json"
    assert cfg.exists()
    cfg.write_text('{"owner_name": "custom"}', encoding="utf-8")
    assert w.write_config() is True            # does not overwrite
    assert "custom" in cfg.read_text(encoding="utf-8")


def test_report_ok_requires_runtime():
    good = FirstRunReport(checks=[CheckResult("runtime", "ok", "Python 3.12")])
    assert good.ok() is True
    bad = FirstRunReport(checks=[CheckResult("runtime", "failed", "3.9")])
    assert bad.ok() is False


def test_device_probes_never_raise():
    w = FirstRunWizard()
    for probe in (w.check_microphone, w.check_speakers, w.check_camera, w.check_os):
        r = probe()
        assert isinstance(r, CheckResult)
        assert r.status in ("ok", "warn", "absent", "unknown", "failed")


def test_key_prompt_callback_used(tmp_path):
    w = _wizard(tmp_path)
    calls = []

    def prompt():
        calls.append(1)
        return "from-prompt"

    report = w.run(key_prompt=prompt)
    assert calls == [1]
    assert report.secret_configured is True
    assert "GROQ_API_KEY=from-prompt" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_prompt_exception_is_swallowed(tmp_path):
    w = _wizard(tmp_path)

    def boom():
        raise RuntimeError("no tty")

    report = w.run(key_prompt=boom)            # must not raise
    assert report.completed is True
    assert report.secret_configured is False
