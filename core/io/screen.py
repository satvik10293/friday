"""
core/io/screen.py — FRIDAY V3 (M52)
Her screen sight: she captures the screen and reads the text on it HERSELF,
on-device. The screenshot never leaves the machine — only the extracted text
is ever reasoned over, through her normal (privacy-bounded) path.

OCR uses the OS's OWN engine where possible (fast, no model download, best
quality), with a universal fallback so it works everywhere:

    Windows  → winocr        (Windows.Media.Ocr)
    macOS    → ocrmac         (Apple Vision framework)
    any OS   → rapidocr       (onnxruntime — the cross-platform fallback)

Everything is guarded: no OCR backend / no display → she says she can't read
the screen, never crashes.
"""

from __future__ import annotations

import logging
import platform
import re
from typing import Optional

log = logging.getLogger("friday.io.screen")


def _capture():
    """Grab the whole desktop (all monitors) as a PIL image, or None."""
    try:
        from PIL import ImageGrab
        try:
            return ImageGrab.grab(all_screens=True)      # Windows: every monitor
        except TypeError:
            return ImageGrab.grab()                       # older Pillow / macOS
    except Exception:  # noqa: BLE001
        log.debug("screen capture failed", exc_info=True)
        return None


# ── OCR backends (each: available() + read(image) -> str) ─────────────────────

def _read_winocr(image) -> Optional[str]:
    try:
        import winocr
        res = winocr.recognize_pil_sync(image)
        return (res.get("text") if isinstance(res, dict) else getattr(res, "text", "")) or ""
    except Exception:  # noqa: BLE001
        log.debug("winocr failed", exc_info=True)
        return None


def _read_ocrmac(image) -> Optional[str]:
    # macOS Vision framework — UNVERIFIED here (built on Windows); runs on a Mac.
    try:
        import tempfile
        from ocrmac import ocrmac
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        image.save(path)
        annotations = ocrmac.OCR(path).recognize()
        return "\n".join(a[0] for a in annotations) if annotations else ""
    except Exception:  # noqa: BLE001
        log.debug("ocrmac failed", exc_info=True)
        return None


def _read_rapidocr(image) -> Optional[str]:
    try:
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
        global _RAPID
        try:
            _RAPID
        except NameError:
            _RAPID = RapidOCR()
        result, _ = _RAPID(np.asarray(image.convert("RGB")))
        return "\n".join(line[1] for line in result) if result else ""
    except Exception:  # noqa: BLE001
        log.debug("rapidocr failed", exc_info=True)
        return None


def _backends() -> list:
    """OCR backends to try. RapidOCR is PRIMARY on every OS (owner-directed,
    M59): one engine across dev, packaged builds, and platforms — models ship
    in the wheel, fully offline, no WinRT/Vision dependency. The OS-native
    engines remain as fallbacks when rapidocr is missing or fails."""
    os_name = platform.system()
    order = [("rapidocr", _read_rapidocr)]           # primary everywhere
    if os_name == "Windows":
        order.append(("winocr", _read_winocr))
    elif os_name == "Darwin":
        order.append(("ocrmac", _read_ocrmac))
    return order


def _backend_available(name: str) -> bool:
    import importlib.util
    mod = {"winocr": "winocr", "ocrmac": "ocrmac", "rapidocr": "rapidocr_onnxruntime"}[name]
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:  # noqa: BLE001
        return False


def available() -> bool:
    """True if the screen can be read (a capture path + at least one OCR backend)."""
    try:
        from PIL import ImageGrab  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return any(_backend_available(n) for n, _ in _backends())


def _clean(text: str) -> str:
    """Tidy OCR output: collapse whitespace, drop empty lines."""
    lines = [ln.strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    return re.sub(r"[ \t]{2,}", " ", "\n".join(lines)).strip()


def read_screen() -> dict:
    """Capture + OCR the screen. Returns {ok, text, backend, chars}. The image
    is never returned or stored — only the extracted text. Never raises."""
    image = _capture()
    if image is None:
        return {"ok": False, "text": "", "backend": None,
                "reason": "no display / capture unavailable"}
    for name, reader in _backends():
        if not _backend_available(name):
            continue
        text = reader(image)
        if text is not None:
            cleaned = _clean(text)
            return {"ok": bool(cleaned), "text": cleaned, "backend": name,
                    "chars": len(cleaned)}
    return {"ok": False, "text": "", "backend": None,
            "reason": "no OCR backend available"}
