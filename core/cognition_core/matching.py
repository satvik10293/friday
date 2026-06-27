"""
core/cognition_core/matching.py — FRIDAY 6.0 (M13)
Name normalization + similarity used by the Entity Resolver. Pure, deterministic
functions (no I/O, no state). Normalization collapses surface variants ("chrome.exe",
"Chrome", " chrome ") to one key; similarity scores residual fuzziness for the final
resolver stage.
"""

from __future__ import annotations

import re

_EXE_SUFFIX = re.compile(r"\.(exe|app|bin|lnk)$", re.IGNORECASE)
_NONWORD = re.compile(r"[^a-z0-9]+")
_WS = re.compile(r"\s+")


def normalize(name: str) -> str:
    """Canonical key for a name: lowercased, executable/app suffixes stripped,
    punctuation collapsed to single spaces, trimmed. Deterministic and stable."""
    s = (name or "").strip().lower()
    s = _EXE_SUFFIX.sub("", s)
    s = _NONWORD.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s


def _bigrams(s: str) -> set:
    s = s.replace(" ", "")
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else ({s} if s else set())


def similarity(a: str, b: str) -> float:
    """Character-bigram Jaccard similarity of two normalized names, in [0, 1].
    Robust to small edits/typos without a heavy model."""
    na, nb = normalize(a), normalize(b)
    if na == nb:
        return 1.0
    ba, bb = _bigrams(na), _bigrams(nb)
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)
