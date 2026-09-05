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
    def __init__(self, size=(1200, 800)):     # <= _MAX_OCR_DIM → no downscale
        self.size = size

    def convert(self, _mode):
        return self

    def resize(self, size):
        return _Img(size)


def _stub(monkeypatch, items, size=(1200, 800)):
    monkeypatch.setattr(screen, "_capture_primary", lambda: _Img(size))
    monkeypatch.setattr(screen, "_backend_available", lambda n: True)
    monkeypatch.setattr(screen, "_boxes_rapidocr", lambda img: items)


def test_locate_scales_image_pixels_into_click_space(monkeypatch):
    # image 1200x800; the mouse space is half that → coords must halve (DPI)
    _stub(monkeypatch, [("Save", 600, 400), ("Cancel", 900, 400)])
    res = screen.locate("save", screen_size=(600, 400))
    assert res["ok"]
    assert res["matches"][0] == {"text": "Save", "x": 300, "y": 200}


def test_locate_downscales_a_big_screen_then_maps_back(monkeypatch):
    # 3200x1800 > cap(1600) → OCR runs on 1600x900; coords map to the real screen
    _stub(monkeypatch, [("Save", 800, 450)], size=(3200, 1800))
    res = screen.locate("save", screen_size=(3200, 1800))
    assert res["ok"]
    m = res["matches"][0]
    assert abs(m["x"] - 1600) <= 2 and abs(m["y"] - 900) <= 2   # 1600-wide OCR, 2x back


def test_locate_ranks_exact_over_partial(monkeypatch):
    _stub(monkeypatch, [("Save As", 100, 100), ("Save", 200, 200)])
    res = screen.locate("save", screen_size=(1200, 800))    # 1:1, no scaling
    assert [m["text"] for m in res["matches"]][0] == "Save"  # exact beats starts-with


def test_locate_is_honest_when_text_absent(monkeypatch):
    _stub(monkeypatch, [("Home", 10, 10), ("File", 20, 20)])
    res = screen.locate("save", screen_size=(1200, 800))
    assert not res["ok"]
    assert "save" in res["reason"].lower()


def test_locate_is_honest_with_no_display(monkeypatch):
    monkeypatch.setattr(screen, "_capture_primary", lambda: None)
    res = screen.locate("save")
    assert not res["ok"]
    assert res["matches"] == []


# ── seeing ICONS: real cv2 template matching (no text involved) ────────────────

def _blank():
    from PIL import Image
    return Image.new("RGB", (400, 300), (200, 200, 200))


def _screen_with_icon(tmp_path):
    """A grey 'screen' with a structured 'icon' (a two-colour X in a bordered box)
    at a known spot — internal detail so template matching is well-posed. The icon
    is saved as a template file. Returns (screen_img, template_path)."""
    from PIL import ImageDraw
    scr = _blank()
    d = ImageDraw.Draw(scr)
    d.rectangle([100, 80, 119, 99], fill=(255, 255, 255), outline=(0, 0, 0))
    d.line([100, 80, 119, 99], fill=(220, 20, 20), width=2)
    d.line([100, 99, 119, 80], fill=(20, 20, 220), width=2)
    tpl_path = tmp_path / "icon.png"
    scr.crop((100, 80, 120, 100)).save(tpl_path)          # the icon alone (20x20)
    return scr, str(tpl_path)


def test_locate_image_finds_an_icon_by_template(monkeypatch, tmp_path):
    scr, tpl = _screen_with_icon(tmp_path)
    monkeypatch.setattr(screen, "_capture_primary", lambda: scr)
    res = screen.locate_image(tpl, screen_size=(400, 300), threshold=0.8)
    assert res["ok"]
    m = res["matches"][0]
    assert abs(m["x"] - 110) <= 3 and abs(m["y"] - 90) <= 3   # centre of the icon


def test_locate_image_is_honest_when_icon_absent(monkeypatch, tmp_path):
    _, tpl = _screen_with_icon(tmp_path)
    monkeypatch.setattr(screen, "_capture_primary", lambda: _blank())   # no icon
    res = screen.locate_image(tpl, screen_size=(400, 300), threshold=0.9)
    assert not res["ok"]
    assert res["matches"] == []
