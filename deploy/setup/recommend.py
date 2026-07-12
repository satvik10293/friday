"""
deploy/setup/recommend.py — the "best FRIDAY for this machine" policy (M44).

Takes the SystemReport from detect.py and produces an InstallPlan: which
edition to install, where, and with which torch build. This is deliberately a
small, readable decision table — the machine-specific *placement* tuning
(which model runs on which device) is measured post-install by the M35 device
wizard; this module only ensures the wizard has the right torch to measure.

Editions:
    windows-desktop  full experience: HUD window, voice, gestures, vision
    macos-desktop    core + voice; HUD validated on Windows only (honest label)
    linux-headless   core cognition + voice; no desktop integration
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .detect import SystemReport

# a CUDA wheel below this VRAM buys nothing for FRIDAY's models
_MIN_CUDA_VRAM_MB = 3000
_MIN_RAM_GB = 8.0

# install-time GPU grading — pre-install expectation, phrased against the M35
# wizard's measured tiers (the wizard's benchmark on first boot is the truth;
# these grades tell the user what to expect before anything is installed)
_BEST_NAME_RE = r"(rtx\s*[345]0(80|90)|rtx\s*40(80|90)|titan|\ba\d{4}\b|h100|l40)"
_GPU_GRADES = (
    # (grade, min VRAM MB, what the user should expect)
    ("best", 12000, "top-tier: every local model and all perception on the GPU"),
    ("good", 6000, "strong: local models + perception expected on the GPU"),
    ("average", 3000, "capable: perception on the GPU, reasoning models on CPU"),
)


def grade_gpu(gpu) -> tuple[str, str]:
    """(grade, expectation) for a detected GPU: best / good / average /
    entry / none. NVIDIA grades by VRAM with a name bump for flagship parts;
    Apple Silicon's unified memory grades 'good'."""
    if gpu.torch_backend == "cuda":
        if re.search(_BEST_NAME_RE, (gpu.name or "").lower()):
            return _GPU_GRADES[0][0], _GPU_GRADES[0][2]
        for grade, floor, expectation in _GPU_GRADES:
            if gpu.vram_mb >= floor:
                return grade, expectation
        return ("entry", "below what FRIDAY's models need — staying on the "
                         "CPU build (still fully functional)")
    if gpu.torch_backend == "mps":
        return "good", "Apple Silicon unified memory: models measured on Metal"
    if gpu.vendor != "none":
        return ("entry", "no torch backend FRIDAY provisions for this GPU "
                         "today — running on CPU")
    return "none", "no discrete GPU — CPU-only, FRIDAY's home turf"

_EDITIONS = {
    "Windows": ("windows-desktop",
                "Full desktop experience — HUD window, voice, gestures, vision"),
    "Darwin": ("macos-desktop",
               "Core + voice (desktop HUD is Windows-validated; runs best-effort)"),
    "Linux": ("linux-headless",
              "Core cognition + voice, headless (no desktop integration)"),
}


def default_install_dir(os_name: str) -> Path:
    if os_name == "Windows":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData/Local")
        return Path(base) / "FRIDAY"
    if os_name == "Darwin":
        return Path.home() / "Applications" / "FRIDAY"
    return Path.home() / ".local" / "share" / "friday"


@dataclass
class InstallPlan:
    edition: str
    edition_note: str
    install_dir: Path
    torch_flavor: str           # cuda | cpu  (mps ships in the default wheel)
    gpu_grade: str              # best | good | average | entry | none
    gpu_summary: str
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"edition": self.edition, "edition_note": self.edition_note,
                "install_dir": str(self.install_dir),
                "torch_flavor": self.torch_flavor,
                "gpu_grade": self.gpu_grade,
                "gpu_summary": self.gpu_summary,
                "warnings": list(self.warnings)}


def recommend(report: SystemReport) -> InstallPlan:
    edition, note = _EDITIONS.get(report.os_name,
                                  ("linux-headless", _EDITIONS["Linux"][1]))
    warnings = list(report.notes)

    gpu = report.gpu
    grade, expectation = grade_gpu(gpu)
    torch_flavor = "cuda" if (gpu.torch_backend == "cuda"
                              and gpu.vram_mb >= _MIN_CUDA_VRAM_MB) else "cpu"
    label = f"{gpu.name} ({gpu.vram_mb} MB)" if gpu.vram_mb else \
        (gpu.name or "no GPU")
    gpu_summary = f"{label} — grade: {grade.upper()} — {expectation}"

    if report.ram_gb and report.ram_gb < _MIN_RAM_GB:
        warnings.append(f"{report.ram_gb} GB RAM is below the recommended "
                        f"{_MIN_RAM_GB:.0f} GB — vision and heavy perception "
                        f"may run degraded.")
    if report.python is None:
        warnings.append("Install cannot proceed until Python >= 3.10 is available.")

    return InstallPlan(edition=edition, edition_note=note,
                       install_dir=default_install_dir(report.os_name),
                       torch_flavor=torch_flavor, gpu_grade=grade,
                       gpu_summary=gpu_summary, warnings=warnings)
