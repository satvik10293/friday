"""
General image understanding: she looks at a picture and says what's in it. The
model is lazy + on-demand (never loaded at startup, off the everyday path) so it
can't slow her down. These pin: honest fallback when the model isn't there, the
success path (model stubbed — no 1GB download in CI), and honest bad-path.
"""

from __future__ import annotations

import core.vision.image_understanding as vi


def test_describe_is_honest_when_libs_missing(monkeypatch):
    monkeypatch.setattr(vi, "available", lambda: False)
    res = vi.describe_image("anything.png")
    assert not res["ok"]
    assert "transformers" in res["reason"]


def test_describe_success_with_stubbed_model(monkeypatch):
    monkeypatch.setattr(vi, "available", lambda: True)
    monkeypatch.setattr(vi, "_open", lambda p: object())          # skip real PIL
    monkeypatch.setattr(vi, "_load",
                        lambda: (lambda img, **k: [{"generated_text": "a cat on a sofa"}]))
    res = vi.describe_image("cat.png")
    assert res["ok"]
    assert res["text"] == "a cat on a sofa"


def test_describe_is_honest_when_model_unavailable(monkeypatch):
    monkeypatch.setattr(vi, "available", lambda: True)
    monkeypatch.setattr(vi, "_open", lambda p: object())
    monkeypatch.setattr(vi, "_load", lambda: None)               # download/load failed
    res = vi.describe_image("cat.png")
    assert not res["ok"]
    assert res["text"] == ""
