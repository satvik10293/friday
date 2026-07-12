"""
deploy/setup — the official FRIDAY launcher/installer (M44).

A single self-contained executable per OS (built by `build_setup.py` with
PyInstaller) that identifies the machine, recommends the best FRIDAY edition
for it, installs, and launches:

    detect   → OS / arch / RAM / system Python / GPU (nvidia-smi, CIM, MPS)
    recommend→ edition + install dir + torch flavor (CUDA build when a real
               NVIDIA GPU is present, CPU otherwise)
    install  → extract the embedded source payload, provision the venv via the
               bundled bootstrap (GPU-aware torch), shortcuts, first run
    launch   → friday_launch.py inside the provisioned venv

Everything in `detect.py` / `recommend.py` is standard-library only: the
frozen binary stays small and the logic is unit-testable without hardware.
"""
