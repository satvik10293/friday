"""Tests for the M8 KnowledgeWriter distillation + Obsidian note generation."""

from core.knowledge.knowledge_models import KnowledgeCategory
from core.knowledge.knowledge_writer import DistilledNote, KnowledgeWriter


def test_distilled_note_markdown_format():
    note = DistilledNote(title="Flask Routing",
                         concept="Maps URLs to Python functions.",
                         example='@app.route("/")',
                         related=["Python", "Web Development"])
    md = note.to_markdown()
    assert md.startswith("# Flask Routing")
    assert "## Concept" in md
    assert "## Example" in md
    assert "- [[Python]]" in md and "- [[Web Development]]" in md


def test_distill_extracts_concept():
    w = KnowledgeWriter(knowledge_service=None)
    note = w.distill("Flask Routing",
                     "Routing is short. Flask maps incoming request URLs to the "
                     "python view functions that should handle them.",
                     example='@app.route("/")')
    assert "maps incoming request urls" in note.concept.lower()
    assert note.example == '@app.route("/")'


def test_distill_infers_related():
    w = KnowledgeWriter(knowledge_service=None)
    note = w.distill("Flask Routing", "flask handles http route and url mapping")
    assert "Flask" in note.related
    assert "Web Development" in note.related


def test_write_stores_structured_entry(knowledge_service):
    w = KnowledgeWriter(knowledge_service)
    entry = w.write("Flask Routing",
                    "Flask maps URLs to python view functions using route decorators.",
                    example='@app.route("/")',
                    related=["Python"], category=KnowledgeCategory.FLASK)
    stored = knowledge_service.get(entry.id)
    assert stored is not None
    assert "## Concept" in stored.content
    assert stored.metadata.get("links") == ["Python"]
    assert stored.metadata.get("structured") is True


def test_write_creates_graph_relation_to_existing(knowledge_service):
    knowledge_service.teach("Python", "a programming language")
    w = KnowledgeWriter(knowledge_service)
    entry = w.write("Flask basics", "flask is a python web framework for routes",
                    related=["Python"], category=KnowledgeCategory.FLASK)
    neighbours = knowledge_service.graph.neighbors(entry.id)
    py = knowledge_service.store.find_by_title("Python")
    assert py.id in neighbours


def test_write_vaults_a_note(knowledge_service, tmp_path):
    w = KnowledgeWriter(knowledge_service)
    entry = w.write("Vaulted Concept", "a concept that should be written to disk")
    assert entry.vault_path
    assert (tmp_path / "vault" / entry.vault_path).exists()


def test_render_existing(knowledge_service):
    w = KnowledgeWriter(knowledge_service)
    entry = w.write("Renderable", "content for the renderable concept here",
                    related=["Python"])
    md = w.render(entry.id)
    assert md.startswith("# Renderable")
    assert "[[Python]]" in md


def test_distill_empty_concept():
    w = KnowledgeWriter(knowledge_service=None)
    note = w.distill("Title", "")
    assert note.concept == ""
    assert "(none)" in note.to_markdown()
