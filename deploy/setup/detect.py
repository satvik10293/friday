"""
deploy/setup/detect.py — hardware & platform detection for the official
launcher (M44). Standard library only; every probe is guarded and returns
"unknown"/empty rather than raising — the installer must run on a machine
that has nothing on it yet (no torch, possibly no Python).

GPU detection here is PRE-INSTALL detection: it answers "which torch build
should the installer provision?" (CUDA vs CPU). The authoritative *placement*
decision stays with the M35 device wizard, which MEASURES the GPU with the
torch this installer chose — detect here, measure there.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional

_RUN_TIMEOUT_S = 10


def _run(cmd: list[str]) -> str:
    """Run a probe command; empty string on any failure."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=_RUN_TIMEOUT_S,
                              creationflags=getattr(subprocess,
                                                    "CREATE_NO_WINDOW", 0))
        return proc.stdout if proc.returncode == 0 else ""
    except Exception:  # noqa: BLE001 — probes never break the installer
        return ""


# ── GPU ───────────────────────────────────────────────────────────────────────

@dataclass
class GPU:
    vendor: str                 # nvidia | amd | intel | apple | none
    name: str = ""
    vram_mb: int = 0
    torch_backend: str = "cpu"  # cuda | mps | cpu — what torch could use


def _parse_nvidia_smi(output: str) -> Optional[GPU]:
    """Parse `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader`.
    Example line: 'NVIDIA GeForce RTX 3060 Laptop GPU, 6144 MiB'."""
    for line in (output or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2:
            m = re.search(r"(\d+)", parts[1])
            vram = int(m.group(1)) if m else 0
            return GPU(vendor="nvidia", name=parts[0], vram_mb=vram,
                       torch_backend="cuda")
    return None


def _windows_video_controllers() -> list[str]:
    out = _run(["powershell", "-NoProfile", "-Command",
                "(Get-CimInstance Win32_VideoController).Name"])
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _linux_video_controllers() -> list[str]:
    out = _run(["lspci"])
    return [ln.strip() for ln in out.splitlines()
            if re.search(r"VGA|3D controller|Display", ln)]


def classify_gpu_names(names: list[str]) -> GPU:
    """Classify raw controller names when nvidia-smi is unavailable. NVIDIA
    without nvidia-smi means no usable driver → CPU torch (a CUDA wheel would
    be dead weight); AMD/Intel have no torch backend we provision today."""
    joined = " | ".join(names).lower()
    if "nvidia" in joined or "geforce" in joined or "quadro" in joined:
        name = next(n for n in names if re.search(r"nvidia|geforce|quadro", n, re.I))
        return GPU(vendor="nvidia", name=name, torch_backend="cpu")
    if "amd" in joined or "radeon" in joined:
        name = next(n for n in names if re.search(r"amd|radeon", n, re.I))
        return GPU(vendor="amd", name=name, torch_backend="cpu")
    if "intel" in joined:
        name = next(n for n in names if re.search(r"intel", n, re.I))
        return GPU(vendor="intel", name=name, torch_backend="cpu")
    return GPU(vendor="none", torch_backend="cpu")


def detect_gpu(os_name: Optional[str] = None) -> GPU:
    """Best GPU the installer can act on. Order of trust:
    working nvidia-smi (driver present, CUDA build worth installing) →
    Apple Silicon (MPS ships with the default torch wheel) →
    named-but-driverless controllers (recorded, CPU torch)."""
    os_name = os_name or platform.system()

    if shutil.which("nvidia-smi"):
        gpu = _parse_nvidia_smi(_run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader"]))
        if gpu:
            return gpu

    if os_name == "Darwin" and platform.machine() == "arm64":
        return GPU(vendor="apple", name="Apple Silicon", torch_backend="mps")

    if os_name == "Windows":
        return classify_gpu_names(_windows_video_controllers())
    if os_name == "Linux":
        return classify_gpu_names(_linux_video_controllers())
    return GPU(vendor="none")


# ── RAM ───────────────────────────────────────────────────────────────────────

def detect_ram_gb() -> float:
    try:
        if platform.system() == "Windows":
            import ctypes

            class _MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(_MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return round(status.ullTotalPhys / (1024 ** 3), 1)
        if platform.system() == "Darwin":
            out = _run(["sysctl", "-n", "hw.memsize"])
            return round(int(out.strip()) / (1024 ** 3), 1) if out.strip() else 0.0
        # Linux
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    kb = int(re.search(r"(\d+)", line).group(1))
                    return round(kb / (1024 ** 2), 1)
    except Exception:  # noqa: BLE001
        pass
    return 0.0


# ── Python ────────────────────────────────────────────────────────────────────

_MIN_PYTHON = (3, 10)


def find_python() -> Optional[dict]:
    """A system Python ≥3.10 the installer can provision a venv with. The
    frozen installer's own interpreter doesn't count — sys.executable is the
    installer exe itself when frozen."""
    candidates: list[list[str]] = []
    if not getattr(sys, "frozen", False):
        candidates.append([sys.executable])
    if platform.system() == "Windows":
        candidates += [["py", "-3"], ["python"], ["python3"]]
    else:
        candidates += [["python3"], ["python"]]

    seen: set = set()
    for cand in candidates:
        if shutil.which(cand[0]) is None:
            continue
        out = _run(cand + ["-c", "import sys; "
                           "print('%d.%d.%d' % sys.version_info[:3]); "
                           "print(sys.executable)"])
        lines = out.strip().splitlines()
        m = re.match(r"(\d+)\.(\d+)\.(\d+)", lines[0].strip()) if lines else None
        if m is None or len(lines) < 2:
            continue
        version = tuple(int(x) for x in m.groups())
        exe = lines[1].strip()
        if exe in seen:
            continue
        seen.add(exe)
        if version[:2] >= _MIN_PYTHON:
            return {"exe": exe, "version": ".".join(map(str, version))}
    return None


# ── the system report ─────────────────────────────────────────────────────────

@dataclass
class SystemReport:
    os_name: str                # Windows | Darwin | Linux
    os_version: str
    arch: str
    ram_gb: float
    gpu: GPU
    python: Optional[dict]      # {"exe", "version"} or None
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"os": self.os_name, "os_version": self.os_version,
                "arch": self.arch, "ram_gb": self.ram_gb,
                "gpu": self.gpu.__dict__, "python": self.python,
                "notes": list(self.notes)}


def detect_system() -> SystemReport:
    os_name = platform.system()
    report = SystemReport(
        os_name=os_name,
        os_version=platform.version() if os_name == "Windows" else
        platform.release(),
        arch=platform.machine(),
        ram_gb=detect_ram_gb(),
        gpu=detect_gpu(os_name),
        python=find_python(),
    )
    if report.python is None:
        report.notes.append("No Python >= 3.10 found — install from "
                            "https://python.org (or `winget install Python.Python.3.12`).")
    if report.gpu.vendor == "nvidia" and report.gpu.torch_backend == "cpu":
        report.notes.append("NVIDIA GPU present but nvidia-smi is missing — "
                            "install the NVIDIA driver to enable GPU acceleration, "
                            "then reinstall.")
    return report
