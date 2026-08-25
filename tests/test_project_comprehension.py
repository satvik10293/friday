"""
Project comprehension (M64): she goes into a new project and understands it.

These pin the honest properties — she identifies the language, how to run it,
the frameworks in play, the test suite, and can locate a class/function by name
from her symbol index — and that 'understand it' records the project so she
remembers it. Everything runs on a throwaway project built in a tmp dir.
"""

from __future__ import annotations

from core.comprehension.project import (
    analyze_project, understand_project, find_symbol,
)


def _make_project(root):
    (root / "requirements.txt").write_text("flask>=3.0\nnumpy\nrequests\n")
    (root / "README.md").write_text(
        "# Widget\n\nWidget is a tiny Flask service that returns widgets over "
        "HTTP for the demo, nothing more.\n")
    (root / "main.py").write_text("from app import create_app\n\n"
                                  "if __name__ == '__main__':\n    create_app().run()\n")
    (root / "app.py").write_text(
        "import flask\n\n"
        "class WidgetService:\n    def handle(self):\n        return 'ok'\n\n"
        "def create_app():\n    return flask.Flask(__name__)\n")
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("def test_ok():\n    assert True\n")
    sub = root / "widgets"
    sub.mkdir()
    (sub / "core.py").write_text("def build_widget(n):\n    return n * 2\n")


def test_analyze_identifies_the_shape_of_the_project(tmp_path):
    _make_project(tmp_path)
    u = analyze_project(tmp_path)
    assert u is not None
    assert u.primary_language == "Python"
    assert "Flask" in u.frameworks
    assert "NumPy" in u.frameworks
    assert any(e.endswith("main.py") for e in u.entry_points)
    assert u.has_tests
    assert u.file_count >= 4
    assert "Widget is a tiny Flask service" in u.readme_summary


def test_symbol_index_locates_classes_and_functions(tmp_path):
    _make_project(tmp_path)
    u = analyze_project(tmp_path)
    hits = find_symbol(u, "WidgetService")
    assert hits and hits[0][1] == "class WidgetService"
    assert hits[0][0] == "app.py"
    fn = find_symbol(u, "build_widget")
    assert fn and fn[0][0] == "widgets/core.py"


def test_non_project_path_is_handled(tmp_path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    u = analyze_project(empty)
    assert u is not None and u.file_count == 0
    assert analyze_project(tmp_path / "does_not_exist") is None


def test_understand_records_to_world_model_and_memory(tmp_path):
    _make_project(tmp_path)

    class _WM:
        def __init__(self): self.seen = []
        def observe(self, kind, name, **kw): self.seen.append((kind, name, kw))

    class _Mem:
        def __init__(self): self.saved = []
        def save(self, name, description, body, **kw):
            self.saved.append((name, description, body)); return name

    wm, mem = _WM(), _Mem()
    result = understand_project(tmp_path, world_model=wm, memory=mem)
    assert result["ok"]
    assert "Python project" in result["summary"]
    assert wm.seen and wm.seen[0][0] == "project"
    assert mem.saved and mem.saved[0][0].startswith("project ")


def test_route_regexes_match_natural_phrasings():
    from core.launcher.conversation import ConversationBridge as CB
    for phrase in ("understand this project",
                   "analyze the codebase",
                   "can you go into the code and help me with this project",
                   "what does this project do"):
        assert CB._PROJECT_RE.search(phrase), phrase
    m = CB._PROJECT_WHERE_RE.search("where is the class NeuralCore")
    assert m and m.group(1) == "NeuralCore"
    m2 = CB._PROJECT_WHERE_RE.search("find the function build_widget")
    assert m2 and m2.group(1) == "build_widget"
