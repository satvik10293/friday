"""
Point-and-teach icon memory: she learns an icon by name and finds it again. The
library is a small named store of template images (save / path_for / names /
forget), the bridge to clicking icons OCR can't read — without a vision model.
"""

from __future__ import annotations

from PIL import Image

from core.io.icon_library import IconLibrary


def _icon(color=(10, 120, 200)):
    return Image.new("RGB", (24, 24), color)


def test_save_then_find_by_name(tmp_path):
    lib = IconLibrary(root=tmp_path)
    path = lib.save("Settings", _icon())
    assert path.endswith(".png")
    assert lib.path_for("settings") == path          # case-insensitive lookup
    assert "settings" in lib.names()


def test_unknown_icon_returns_none(tmp_path):
    lib = IconLibrary(root=tmp_path)
    assert lib.path_for("nope") is None


def test_forget_removes_it(tmp_path):
    lib = IconLibrary(root=tmp_path)
    lib.save("trash", _icon())
    assert lib.forget("trash") is True
    assert lib.path_for("trash") is None
    assert lib.forget("trash") is False              # already gone → honest False


def test_persists_across_instances(tmp_path):
    IconLibrary(root=tmp_path).save("gear", _icon())
    assert IconLibrary(root=tmp_path).path_for("gear") is not None   # reloaded from disk
