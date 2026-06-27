"""M13 — Entity Resolver pipeline (exact/alias/normalize/similarity/create)."""

import pytest

from core.cognition_core.entity_registry import PersistentEntityRegistry
from core.cognition_core.entity_resolver import EntityResolver
from core.cognition_core.metrics import CognitionMetrics
from core.cognition_core.models import ResolveMethod
from core.cognition_core.repositories import InMemoryEntityRepository


@pytest.fixture
def resolver():
    reg = PersistentEntityRegistry(InMemoryEntityRepository())
    return EntityResolver(reg, metrics=CognitionMetrics())


def test_create_new_entity(resolver):
    r = resolver.resolve("application", "Chrome")
    assert r.created and r.method == ResolveMethod.CREATED.value
    assert r.stable_id.startswith("ENT_")


def test_exact_match_returns_same_id(resolver):
    a = resolver.resolve("application", "Chrome")
    b = resolver.resolve("application", "Chrome")
    assert a.stable_id == b.stable_id
    assert b.method == ResolveMethod.EXACT.value and not b.created


def test_normalization_collapses_variants(resolver):
    a = resolver.resolve("application", "Chrome").stable_id
    # .exe suffix, case, whitespace all normalize to the same key
    assert resolver.resolve("application", "chrome.exe").stable_id == a
    assert resolver.resolve("application", " CHROME ").stable_id == a
    assert resolver.resolve("application", "chrome").stable_id == a


def test_alias_is_learned(resolver):
    a = resolver.resolve("application", "Chrome").stable_id
    resolver.resolve("application", "chrome.exe")            # learns alias
    r = resolver.resolve("application", "chrome.exe")        # now a direct alias hit
    assert r.stable_id == a and r.method == ResolveMethod.ALIAS.value


def test_similarity_matches_typo(resolver):
    # the threshold (0.82) is deliberately strict to avoid false merges; a minor
    # variant of a longer name clears it, a short-word typo would not.
    a = resolver.resolve("application", "Notepad").stable_id
    r = resolver.resolve("application", "Notepadd")          # double-letter variant
    assert r.stable_id == a and r.method == ResolveMethod.SIMILARITY.value


def test_distinct_things_get_distinct_ids(resolver):
    a = resolver.resolve("application", "Chrome").stable_id
    b = resolver.resolve("application", "Firefox").stable_id
    assert a != b


def test_kind_separates_identity(resolver):
    a = resolver.resolve("application", "Monitor").stable_id
    b = resolver.resolve("device", "Monitor").stable_id
    assert a != b                                            # same name, different kind


def test_identity_independent_of_name(resolver):
    """The core invariant: the stable id is permanent even as labels accumulate."""
    sid = resolver.resolve("person", "Sat").stable_id
    resolver.resolve("person", "Satvik")                    # similar → same entity, new label
    e = resolver._registry.get(sid)
    assert e.stable_id == sid                                # id never changed
    assert "Sat" in e.labels


def test_metrics_track_resolution(resolver):
    resolver.resolve("application", "Chrome")
    resolver.resolve("application", "chrome.exe")
    snap = resolver._metrics.snapshot()
    assert snap["entities_created"] == 1 and snap["resolutions"] >= 1
