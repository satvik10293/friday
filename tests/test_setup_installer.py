"""
M44 — the official launcher: detect → grade → recommend → install.

Pure-logic coverage (no hardware assumptions): nvidia-smi parsing, GPU
classification and grading (best/good/average/entry/none), the per-OS
recommendation matrix, torch-flavor selection, payload discovery/extraction,
and the dry-run flow of the installer CLI.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from deploy.setup.detect import (GPU, SystemReport, _parse_nvidia_smi,
                                 classify_gpu_names)
from deploy.setup.recommend import (default_install_dir, grade_gpu, recommend)
from deploy.setup import installer


# ── detection ─────────────────────────────────────────────────────────────────

def test_nvidia_smi_parsing():
    gpu = _parse_nvidia_smi("NVIDIA GeForce RTX 3060 Laptop GPU, 6144 MiB\n")
    assert gpu.vendor == "nvidia" and gpu.vram_mb == 6144
    assert gpu.torch_backend == "cuda"
    assert _parse_nvidia_smi("") is None


def test_nvidia_without_driver_stays_on_cpu_torch():
    """A named NVIDIA controller with no nvidia-smi means no usable driver —
    shipping a CUDA wheel would be dead weight."""
    gpu = classify_gpu_names(["NVIDIA GeForce GTX 1650"])
    assert gpu.vendor == "nvidia" and gpu.torch_backend == "cpu"


def test_non_nvidia_controllers_classify_by_vendor():
    assert classify_gpu_names(["AMD Radeon RX 6600"]).vendor == "amd"
    assert classify_gpu_names(["Intel(R) Iris(R) Xe Graphics"]).vendor == "intel"
    assert classify_gpu_names([]).vendor == "none"


# ── grading: best / good / average / entry / none ────────────────────────────

def test_gpu_grades_span_the_whole_range():
    best = GPU("nvidia", "NVIDIA GeForce RTX 4090", 24564, "cuda")
    flagship_low_vram = GPU("nvidia", "NVIDIA RTX 5090 Laptop", 8000, "cuda")
    good = GPU("nvidia", "NVIDIA GeForce RTX 3060", 6144, "cuda")
    average = GPU("nvidia", "NVIDIA GeForce GTX 1650", 4096, "cuda")
    entry = GPU("nvidia", "NVIDIA GeForce MX250", 2048, "cuda")
    assert grade_gpu(best)[0] == "best"
    assert grade_gpu(flagship_low_vram)[0] == "best"      # name bump
    assert grade_gpu(good)[0] == "good"
    assert grade_gpu(average)[0] == "average"
    assert grade_gpu(entry)[0] == "entry"
    assert grade_gpu(GPU("apple", "Apple Silicon", 0, "mps"))[0] == "good"
    assert grade_gpu(GPU("intel", "Iris Xe", 0, "cpu"))[0] == "entry"
    assert grade_gpu(GPU("none"))[0] == "none"


# ── recommendation ────────────────────────────────────────────────────────────

def _report(os_name="Windows", ram=16.0, gpu=None, python=True) -> SystemReport:
    return SystemReport(
        os_name=os_name, os_version="test", arch="x64", ram_gb=ram,
        gpu=gpu or GPU("none"),
        python={"exe": "python", "version": "3.12.0"} if python else None)


def test_good_gpu_gets_the_cuda_build():
    plan = recommend(_report(gpu=GPU("nvidia", "RTX 3060", 6144, "cuda")))
    assert plan.torch_flavor == "cuda"
    assert plan.gpu_grade == "good"
    assert "GOOD" in plan.gpu_summary


def test_average_gpu_still_gets_cuda_entry_does_not():
    average = recommend(_report(gpu=GPU("nvidia", "GTX 1650", 4096, "cuda")))
    entry = recommend(_report(gpu=GPU("nvidia", "MX250", 2048, "cuda")))
    assert average.torch_flavor == "cuda" and average.gpu_grade == "average"
    assert entry.torch_flavor == "cpu" and entry.gpu_grade == "entry"


def test_editions_follow_the_os():
    assert recommend(_report("Windows")).edition == "windows-desktop"
    assert recommend(_report("Darwin")).edition == "macos-desktop"
    assert recommend(_report("Linux")).edition == "linux-headless"


def test_low_ram_and_missing_python_are_warned():
    plan = recommend(_report(ram=4.0, python=False))
    text = " ".join(plan.warnings)
    assert "4.0 GB RAM" in text and "Python" in text


def test_install_dirs_are_per_os():
    assert "FRIDAY" in str(default_install_dir("Windows"))
    assert str(default_install_dir("Linux")).endswith("friday")


# ── payload + installer flow ──────────────────────────────────────────────────

def _tiny_payload(tmp_path: Path) -> Path:
    payload = tmp_path / "friday-9.9.9-test.zip"
    with zipfile.ZipFile(payload, "w") as zf:
        zf.writestr("friday_launch.py", "print('friday')")
        zf.writestr("deploy/bootstrap.py", "print('bootstrap')")
    return payload


def test_payload_discovery_and_version(tmp_path):
    payload = _tiny_payload(tmp_path)
    assert installer.find_payload(str(payload)) == payload
    assert installer.find_payload(str(tmp_path / "missing.zip")) is None
    assert installer.payload_version(payload) == "9.9.9-test"


def test_extraction_is_upgrade_safe(tmp_path):
    """User data sits next to the code and must survive an upgrade extract."""
    payload = _tiny_payload(tmp_path)
    dest = tmp_path / "install"
    dest.mkdir()
    (dest / ".env").write_text("GROQ_API_KEY=secret", encoding="utf-8")
    (dest / "data").mkdir()
    (dest / "data" / "memories.db").write_text("precious", encoding="utf-8")
    count = installer.extract_payload(payload, dest)
    assert count == 2
    assert (dest / "friday_launch.py").exists()
    assert (dest / ".env").read_text(encoding="utf-8") == "GROQ_API_KEY=secret"
    assert (dest / "data" / "memories.db").read_text(encoding="utf-8") == "precious"


def test_dry_run_plans_but_changes_nothing(tmp_path, capsys):
    payload = _tiny_payload(tmp_path)
    dest = tmp_path / "never-created"
    code = installer.run(["--dry-run", "--source", str(payload),
                          "--dir", str(dest)])
    out = capsys.readouterr().out
    assert code == 0
    assert "Dry run" in out and "9.9.9-test" in out
    assert not dest.exists()
