"""M9 — InterestGraph: interest tracking, linking, evolution, relevance boost."""

from core.user_model.interests import InterestGraph


def test_express_creates_interest(user_model_store):
    ig = InterestGraph(user_model_store)
    i = ig.express("Genetics")
    assert i.name == "Genetics" and i.count == 1 and i.weight > 0.5


def test_repeated_expression_grows_weight(user_model_store):
    ig = InterestGraph(user_model_store)
    before = ig.express("AI").weight
    for _ in range(4):
        ig.express("AI")
    assert ig.weight("AI") > before


def test_weight_clamped(user_model_store):
    ig = InterestGraph(user_model_store)
    for _ in range(50):
        ig.express("Robotics")
    assert ig.weight("Robotics") <= 1.0


def test_link_and_related(user_model_store):
    ig = InterestGraph(user_model_store)
    ig.express("Genetics"); ig.express("Biology")
    ig.link("Genetics", "Biology")
    assert "Biology" in ig.related("Genetics")
    assert "Genetics" in ig.related("Biology")


def test_self_link_ignored(user_model_store):
    ig = InterestGraph(user_model_store)
    ig.express("AI")
    ig.link("AI", "AI")
    assert ig.related("AI") == []


def test_top_interests_ranked(user_model_store):
    ig = InterestGraph(user_model_store)
    for _ in range(5):
        ig.express("Stocks")
    ig.express("Cooking")
    top = ig.top(1)
    assert top[0].name == "Stocks"


def test_evolution_tracks_events(user_model_store):
    ig = InterestGraph(user_model_store)
    ig.express("Coding"); ig.express("Coding")
    evo = ig.evolution("Coding")
    assert len(evo) >= 2


def test_relevance_boost(user_model_store):
    ig = InterestGraph(user_model_store)
    for _ in range(3):
        ig.express("Python")
    boost = ig.relevance_boost("a tutorial about Python decorators")
    assert boost > 0
    assert ig.relevance_boost("a recipe for soup") == 0
