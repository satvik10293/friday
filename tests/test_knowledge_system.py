"""M8 — VaultManager organisation + ExecutiveKnowledgeBridge integration."""

from core.context.context_package import ContextPackage
from core.knowledge.executive_bridge import ExecutiveKnowledgeBridge
from core.knowledge.knowledge_models import KnowledgeCategory, new_knowledge
from core.knowledge.vault import ObsidianVault
from core.knowledge.vault_manager import STANDARD_FOLDERS, VaultManager


# ── VaultManager ──────────────────────────────────────────────────────────────────
def test_ensure_structure_creates_folders(tmp_path):
    vm = VaultManager(ObsidianVault(root=tmp_path / "vault"))
    folders = vm.ensure_structure()
    assert set(folders) == set(STANDARD_FOLDERS)
    for f in STANDARD_FOLDERS:
        assert (tmp_path / "vault" / f).is_dir()


def test_folder_routing_by_category(tmp_path):
    vm = VaultManager(ObsidianVault(root=tmp_path / "vault"))
    e = new_knowledge("Flask thing", "body", category=KnowledgeCategory.FLASK)
    rel = vm.create_note(e)
    assert rel.startswith("Programming/")
    assert (tmp_path / "vault" / rel).exists()


def test_lesson_routes_to_reflections(tmp_path):
    vm = VaultManager(ObsidianVault(root=tmp_path / "vault"))
    e = new_knowledge("A lesson", "learned something", category=KnowledgeCategory.LESSON)
    rel = vm.create_note(e)
    assert rel.startswith("Reflections/")


def test_backlinks_extracted(tmp_path):
    vm = VaultManager(ObsidianVault(root=tmp_path / "vault"))
    e = new_knowledge("Linked", "see [[Python]] and [[Flask]]")
    e.metadata["links"] = ["Web Development"]
    links = vm.backlinks(e)
    assert "Python" in links and "Flask" in links and "Web Development" in links


def test_integrity_detects_broken_link(tmp_path):
    vm = VaultManager(ObsidianVault(root=tmp_path / "vault"))
    vm.ensure_structure()
    vm.create_note(new_knowledge("Has broken link", "points to [[Nonexistent Note]]"))
    report = vm.integrity_check()
    assert report.notes == 1
    assert any(b["target"] == "Nonexistent Note" for b in report.broken_links)
    assert report.ok is False


def test_integrity_clean(tmp_path):
    vm = VaultManager(ObsidianVault(root=tmp_path / "vault"))
    vm.ensure_structure()
    vm.create_note(new_knowledge("Self contained", "no outgoing links here"))
    report = vm.integrity_check()
    assert report.ok is True


def test_vault_manager_stats(tmp_path):
    vm = VaultManager(ObsidianVault(root=tmp_path / "vault"))
    vm.create_note(new_knowledge("P", "x", category=KnowledgeCategory.PYTHON))
    stats = vm.stats()
    assert stats["total_notes"] >= 1
    assert "Programming" in stats["folders"]


# ── ExecutiveKnowledgeBridge ──────────────────────────────────────────────────────
def test_bridge_search(knowledge_service):
    knowledge_service.teach("Flask templates", "templates live under templates/")
    bridge = ExecutiveKnowledgeBridge(knowledge_service)
    res = bridge.search_knowledge("flask templates location")
    assert res.found


def test_bridge_store(knowledge_service):
    bridge = ExecutiveKnowledgeBridge(knowledge_service)
    entry = bridge.store_knowledge("Stored by brain", "the executive stored this")
    assert knowledge_service.get(entry.id) is not None
    assert entry.source == "executive"


def test_bridge_build_context(knowledge_service):
    knowledge_service.teach("Retry policy", "retry with exponential backoff and jitter")
    bridge = ExecutiveKnowledgeBridge(knowledge_service)
    frag = bridge.build_context("how should retries work")
    assert "knowledge" in frag
    assert frag["knowledge"]


def test_bridge_augments_context_package(knowledge_service):
    knowledge_service.teach("Logging", "log at the boundary with context")
    bridge = ExecutiveKnowledgeBridge(knowledge_service)
    pkg = ContextPackage(query="logging best practice")
    bridge.augment_context(pkg, "logging best practice")
    assert "knowledge" in pkg.world
    assert any(l.get("source") == "knowledge" for l in pkg.lessons)
    assert not pkg.is_empty
