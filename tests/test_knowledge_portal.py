"""M8 — Knowledge Portal: framework-agnostic API, graph payload, sync, server."""

import pytest

from core.knowledge_portal.portal_api import PortalAPI
from core.knowledge_portal.portal_graph import build_graph
from core.knowledge_portal.portal_sync import PortalSync


# ── PortalAPI CRUD ────────────────────────────────────────────────────────────────
def test_api_create_and_get(knowledge_service):
    api = PortalAPI(knowledge_service)
    created = api.create({"title": "Created via portal", "content": "body text"})
    kid = created["item"]["id"]
    got = api.get(kid)
    assert got["item"]["title"] == "Created via portal"


def test_api_create_requires_title(knowledge_service):
    api = PortalAPI(knowledge_service)
    assert api.create({"content": "no title"}).get("error") == "title_required"


def test_api_list(knowledge_service):
    api = PortalAPI(knowledge_service)
    api.create({"title": "One", "content": "a"})
    api.create({"title": "Two", "content": "b"})
    out = api.list_knowledge()
    assert out["count"] >= 2


def test_api_update(knowledge_service):
    api = PortalAPI(knowledge_service)
    kid = api.create({"title": "Editable", "content": "old"})["item"]["id"]
    upd = api.update(kid, {"content": "new"})
    assert upd["item"]["content"] == "new"


def test_api_delete_archives(knowledge_service):
    api = PortalAPI(knowledge_service)
    kid = api.create({"title": "Temp", "content": "x"})["item"]["id"]
    assert api.delete(kid) == {"archived": kid}
    assert knowledge_service.get(kid).status == "archived"


def test_api_get_missing(knowledge_service):
    api = PortalAPI(knowledge_service)
    assert api.get("nope").get("error") == "not_found"


def test_api_search(knowledge_service):
    api = PortalAPI(knowledge_service)
    api.create({"title": "Exponential backoff", "content": "retry with backoff jitter"})
    res = api.search("backoff retry")
    assert res["items"]


def test_api_stats(knowledge_service):
    api = PortalAPI(knowledge_service)
    api.create({"title": "Counted", "content": "x"})
    stats = api.stats()
    assert stats["totals"]["total"] >= 1
    assert "by_category" in stats and "health" in stats


# ── graph payload ─────────────────────────────────────────────────────────────────
def test_graph_payload(knowledge_service):
    from core.knowledge.knowledge_models import KnowledgeRelation
    a = knowledge_service.teach("Python", "language")
    b = knowledge_service.teach("Flask", "web framework")
    knowledge_service.relate(a.id, b.id, KnowledgeRelation.RELATED.value)
    g = build_graph(knowledge_service.store)
    ids = {n["id"] for n in g["nodes"]}
    assert a.id in ids and b.id in ids
    assert g["edges"]
    # symmetric related pair collapses to a single undirected edge
    assert g["stats"]["edges"] == 1


def test_graph_nodes_have_color(knowledge_service):
    knowledge_service.teach("Python", "language")
    g = build_graph(knowledge_service.store)
    assert all("color" in n and "size" in n for n in g["nodes"])


# ── sync ──────────────────────────────────────────────────────────────────────────
def test_sync_db_to_vault(knowledge_service, tmp_path):
    knowledge_service.remember_knowledge("Syncable", "content to mirror to vault")
    sync = PortalSync(knowledge_service)
    n = sync.db_to_vault()
    assert n >= 1


def test_full_sync_roundtrip(tmp_path):
    from core.knowledge.knowledge_store import KnowledgeStore
    from core.knowledge.knowledge_index import KnowledgeIndex
    from core.knowledge.knowledge_service import KnowledgeService
    from core.knowledge.vault import ObsidianVault

    store = KnowledgeStore(path=tmp_path / "k.db")
    svc = KnowledgeService(store=store, index=KnowledgeIndex(),
                           vault=ObsidianVault(root=tmp_path / "vault"))
    svc.remember_knowledge("Alpha", "alpha body content")
    sync = PortalSync(svc)
    result = sync.full_sync()
    assert result.db_to_vault >= 1
    assert result.vault_to_db >= 1
    store.close()


# ── server (Flask wiring) ─────────────────────────────────────────────────────────
def test_server_builds_flask_app(knowledge_service):
    pytest.importorskip("flask")
    from core.knowledge_portal.portal_server import PortalServer
    server = PortalServer(knowledge_service)
    app = server.build_app()
    assert app is not None
    assert server.host == "127.0.0.1" and server.port == 5000


def test_server_routes_respond(knowledge_service):
    pytest.importorskip("flask")
    from core.knowledge_portal.portal_server import PortalServer
    knowledge_service.teach("Routed", "served over http")
    app = PortalServer(knowledge_service).build_app()
    client = app.test_client()
    assert client.get("/health").status_code == 200
    assert client.get("/stats").status_code == 200
    assert client.get("/").status_code == 200          # dashboard HTML
    r = client.get("/knowledge")
    assert r.status_code == 200 and r.get_json()["count"] >= 1


def test_server_search_route(knowledge_service):
    pytest.importorskip("flask")
    from core.knowledge_portal.portal_server import PortalServer
    knowledge_service.teach("Searchable concept", "find me via the search endpoint")
    app = PortalServer(knowledge_service).build_app()
    client = app.test_client()
    r = client.get("/search?q=searchable")
    assert r.status_code == 200 and "items" in r.get_json()


def test_portal_import_side_effect_free():
    import importlib
    importlib.import_module("core.knowledge_portal")
    importlib.import_module("core.knowledge_portal.portal_api")
    importlib.import_module("core.knowledge_portal.portal_ui")
