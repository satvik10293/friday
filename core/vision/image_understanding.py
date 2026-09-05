"""
core/vision/image_understanding.py — she LOOKS at a picture and says what's in it.

A general image describer (captioning), built to NOT slow Friday down:

  · lazy — the model loads only the first time she's actually asked to look at
    something, never at startup;
  · on-demand — it lives off her everyday voice/reasoning path, so normal turns
    never pay for it;
  · local + offline after a one-time model download.

Honest: if transformers/torch or the model aren't available, she says she can't
see the image — she never invents a description. On a CPU box a caption takes a
couple of seconds; that cost is only paid when you actually ask her to look.
"""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("friday.vision.describe")

# a small, well-known captioner; downloaded once on first use, then cached
_MODEL_ID = "Salesforce/blip-image-captioning-base"
_PIPE = None
_LOAD_FAILED = False


def available() -> bool:
    """True if the libraries needed to describe an image are installed."""
    import importlib.util as u
    return all(u.find_spec(m) is not None for m in ("transformers", "torch", "PIL"))


def _load():
    """Lazily build the image-to-text pipeline (downloads the model on first use).
    Cached after the first call; a failure is remembered so we don't retry hard."""
    global _PIPE, _LOAD_FAILED
    if _PIPE is not None or _LOAD_FAILED:
        return _PIPE
    try:
        from transformers import pipeline
        _PIPE = pipeline("image-to-text", model=_MODEL_ID)
    except Exception:  # noqa: BLE001
        log.debug("image model load failed", exc_info=True)
        _LOAD_FAILED = True
    return _PIPE


def _open(path_or_image):
    from PIL import Image
    if hasattr(path_or_image, "convert"):
        return path_or_image.convert("RGB")
    return Image.open(path_or_image).convert("RGB")


def describe_image(path_or_image, *, max_tokens: int = 40) -> dict:
    """Describe an image (a file path or a PIL image). Returns {ok, text, reason}.
    On-demand and never raises."""
    if not available():
        return {"ok": False, "text": "",
                "reason": "image understanding needs transformers + torch installed"}
    try:
        img = _open(path_or_image)
    except Exception:  # noqa: BLE001
        return {"ok": False, "text": "",
                "reason": f"couldn't open the image '{path_or_image}'"}
    pipe = _load()
    if pipe is None:
        return {"ok": False, "text": "",
                "reason": "the image model isn't available (first-use download may have failed)"}
    try:
        out = pipe(img, max_new_tokens=max_tokens)
        text = (out[0].get("generated_text", "") if out else "").strip()
        return {"ok": bool(text), "text": text,
                "reason": None if text else "no description produced"}
    except Exception:  # noqa: BLE001
        log.debug("describe failed", exc_info=True)
        return {"ok": False, "text": "", "reason": "image description failed"}
