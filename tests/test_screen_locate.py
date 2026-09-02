"""
The "aim" faculty: read_screen sees WHAT is on screen; locate() finds WHERE, so
she can click a visible label instead of a blind coordinate. These pin the two
things that make aiming trustworthy — correct ranking, and DPI-safe scaling from
image pixels into the mouse coordinate space — plus honest misses. No real
display or OCR engine is touched (capture + boxes are stubbed).
"""

from __future__ import annotations

import core.io.screen as screen


class _Img:
    size = (2000, 1000)

    def convert(self, _mode):
        return self


def _stub(monkeypatch, items):
    monkeypatch.setattr(screen, "_capture_primary", lambda: _Img())
    monkeypatch.setattr(screen, "_backend_available", lambda n: True)
    monkeypatch.setattr(screen, "_boxes_rapidocr", lambda img: items)


def test_locate_scales_image_pixels_into_click_space(monkeypatch):
    # image is 2000x1000; the mouse space is half that → coords must halve (DPI)
    _stub(monkeypatch, [("Save", 1000, 500), ("Cancel", 1500, 500)])
    res = screen.locate("save", screen_size=(1000, 500))
    assert res["ok"]
    assert res["matches"][0] == {"text": "Save", "x": 500, "y": 250}


def test_locate_ranks_exact_over_partial(monkeypatch):
    _stub(monkeypatch, [("Save As", 100, 100), ("Save", 200, 200)])
    res = screen.locate("save", screen_size=(2000, 1000))   # 1:1, no scaling
    assert [m["text"] for m in res["matches"]][0] == "Save"  # exact beats starts-with


def test_locate_is_honest_when_text_absent(monkeypatch):
    _stub(monkeypatch, [("Home", 10, 10), ("File", 20, 20)])
    res = screen.locate("save", screen_size=(2000, 1000))
    assert not res["ok"]
    assert "save" in res["reason"].lower()


def test_locate_is_honest_with_no_display(monkeypatch):
    monkeypatch.setattr(screen, "_capture_primary", lambda: None)
    res = screen.locate("save")
    assert not res["ok"]
    assert res["matches"] == []
