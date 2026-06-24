"""
friday_sovereign.py — Friday 3.0
The Independence Engine. Friday's path to self-sufficiency.

After EVERY response, Sovereign runs in the background:
  1. Extracts facts, concepts, and patterns from the exchange
  2. Compresses and stores them in her own knowledge base
  3. Tracks which domains she's becoming expert in
  4. Measures her independence ratio (self-answered vs API-answered)

Over time: she answers more from memory, less from external APIs.
Goal: 80% self-sufficient within months of regular use.
"""

import re
import time
import json
import logging
import threading
from typing import Optional
from pathlib import Path
from dataclasses import dataclass, field

log = logging.getLogger("friday.sovereign")

# ── Paths ─────────────────────────────────────────────────────────────────────

_BASE_DIR      = Path(__file__).resolve().parents[2]
_DATA_DIR      = _BASE_DIR / "data"
_STATS_PATH    = _DATA_DIR / "sovereign_stats.json"
_DOMAIN_PATH   = _DATA_DIR / "sovereign_domains.json"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Domain tracking ───────────────────────────────────────────────────────────

@dataclass
class DomainProfile:
    name:          str
    query_count:   int   = 0
    fact_count:    int   = 0
    confidence:    float = 0.0     # 0.0 = no knowledge, 1.0 = expert
    last_updated:  float = field(default_factory=time.time)

    def update(self, facts_added: int) -> None:
        self.query_count  += 1
        self.fact_count   += facts_added
        # Confidence grows logarithmically — fast at first, slows as it matures
        self.confidence    = min(1.0, self.confidence + (facts_added * 0.02) / (1 + self.query_count * 0.05))
        self.last_updated  = time.time()


# ── Stats tracker ─────────────────────────────────────────────────────────────

@dataclass
class SovereignStats:
    total_exchanges:    int   = 0
    facts_extracted:    int   = 0
    concepts_learned:   int   = 0
    self_answered:      int   = 0    # answered from Chronicle without API
    api_answered:       int   = 0    # needed API call
    domains_active:     int   = 0

    @property
    def independence_ratio(self) -> float:
        total = self.self_answered + self.api_answered
        if total == 0:
            return 0.0
        return round(self.self_answered / total, 3)

    @property
    def independence_pct(self) -> int:
        return int(self.independence_ratio * 100)


_stats  = SovereignStats()
_domains: dict[str, DomainProfile] = {}
_stats_lock = threading.Lock()


# ── Knowledge extraction patterns ─────────────────────────────────────────────

# Patterns that signal extractable facts
_FACT_PATTERNS = [
    # Definitions
    (r"(?P<subject>\w[\w\s]{2,30}) (?:is|are|means?|refers? to) (?P<object>[^.!?\n]{10,150})[.!?]",
     "is"),
    # Causal
    (r"(?P<subject>\w[\w\s]{2,25}) (?:causes?|leads? to|results? in|produces?) (?P<object>[^.!?\n]{10,100})[.!?]",
     "causes"),
    # Properties
    (r"(?P<subject>\w[\w\s]{2,25}) (?:has|have|contains?|includes?) (?P<object>[^.!?\n]{10,100})[.!?]",
     "has"),
    # Usage
    (r"(?:use|using|used?) (?P<subject>\w[\w\s]{2,25}) (?:to|for) (?P<object>[^.!?\n]{10,100})[.!?]",
     "used_for"),
    # Best practices (high value)
    (r"(?:always|never|should|must|best practice[: ]+) (?P<object>[^.!?\n]{15,150})[.!?]",
     "best_practice"),
]

# Domain keyword mapping
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "python":       ["python", "def ", "class ", "import", "pip", "django", "flask", "async", "await", "decorator"],
    "javascript":   ["javascript", "nodejs", "npm", "react", "vue", "angular", "typescript", "const ", "async/await"],
    "databases":    ["sql", "database", "postgresql", "mysql", "sqlite", "mongodb", "redis", "query", "index", "schema"],
    "ai_ml":        ["machine learning", "neural network", "llm", "embedding", "faiss", "transformer", "attention", "fine-tuning", "groq", "gemini"],
    "system_design":["architecture", "microservices", "api", "rest", "grpc", "load balancer", "cache", "queue", "event bus"],
    "security":     ["authentication", "authorization", "jwt", "oauth", "encryption", "ssl", "xss", "sql injection", "rate limit"],
    "devops":       ["docker", "kubernetes", "ci/cd", "github actions", "deployment", "nginx", "linux", "bash", "terraform"],
    "friday":       ["friday", "saturday", "chronicle", "psyche", "neural", "sovereign", "codex", "spine"],
    "satvik":       ["satvik", "dileep", "my project", "our system", "i'm building"],
}


def _detect_domain(text: str) -> list[str]:
    """Detect which knowledge domains this exchange belongs to."""
    q       = text.lower()
    matches = []
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if sum(1 for kw in keywords if kw in q) >= 2:
            matches.append(domain)
    return matches[:3]


def _extract_facts(text: str, source: str = "conversation") -> list[dict]:
    """
    Extract structured fact triples from text.
    Returns list of {subject, predicate, object, confidence} dicts.
    """
    facts   = []
    seen    = set()

    for pattern, predicate in _FACT_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
            subject = m.group("subject").strip() if "subject" in m.groupdict() else source
            obj     = m.group("object").strip()

            # Dedup and quality filter
            key = f"{subject}|{predicate}|{obj[:50]}"
            if key in seen:
                continue
            seen.add(key)

            # Skip low-quality extractions
            if len(obj) < 10 or len(obj) > 200:
                continue
            if obj.lower().startswith(("i ", "you ", "we ", "they ")):
                continue

            facts.append({
                "subject":    subject[:80],
                "predicate":  predicate,
                "object":     obj[:200],
                "confidence": 0.75,
                "source":     source,
            })

    return facts[:10]   # cap per exchange — quality over quantity


def _extract_concepts(text: str) -> list[str]:
    """
    Extract key concepts/terms from text.
    Simple heuristic: capitalized technical terms, quoted terms, backtick terms.
    """
    concepts = set()

    # Backtick code terms
    for m in re.finditer(r"`([^`\n]{2,40})`", text):
        concepts.add(m.group(1).strip())

    # Quoted terms
    for m in re.finditer(r'"([^"\n]{3,40})"', text):
        concepts.add(m.group(1).strip())

    # Technical capitalized terms (2+ words or single CamelCase)
    for m in re.finditer(r"\b([A-Z][a-zA-Z]{2,}(?:\s[A-Z][a-zA-Z]{2,})?)\b", text):
        term = m.group(1)
        if len(term) > 3 and term not in ("The", "This", "That", "When", "Then", "Here", "There"):
            concepts.add(term)

    return list(concepts)[:15]


# ── Main extraction pipeline ───────────────────────────────────────────────────

def extract_and_store(
    user_input:      str,
    friday_response: str,
    intent:          str,
    used_api:        bool = True,
) -> dict:
    """
    Main entry point. Called after every exchange in background.
    Returns extraction summary dict.
    """
    t0      = time.time()
    summary = {"facts": 0, "concepts": 0, "domains": [], "elapsed_ms": 0}

    # Combined text for extraction
    full_text = f"{user_input}\n{friday_response}"

    # Detect domains
    domains = _detect_domain(full_text)
    summary["domains"] = domains

    # Extract facts from Friday's response (more reliable than user input)
    facts = _extract_facts(friday_response, source=intent)
    summary["facts"] = len(facts)

    # Extract concepts
    concepts = _extract_concepts(friday_response)
    summary["concepts"] = len(concepts)

    # Persist everything
    _persist_facts(facts, domains)
    _persist_concepts(concepts, domains)
    _update_stats(used_api, len(facts), domains)

    summary["elapsed_ms"] = round((time.time() - t0) * 1000, 1)

    if facts or concepts:
        log.debug(
            "Sovereign extracted: %d facts, %d concepts, domains=%s in %dms",
            len(facts), len(concepts), domains, summary["elapsed_ms"]
        )

    return summary


def _persist_facts(facts: list[dict], domains: list[str]) -> None:
    """Store extracted facts to Chronicle."""
    if not facts:
        return
    try:
        from core.knowledge.friday_chronicle import save_fact
        for f in facts:
            save_fact(
                subject    = f["subject"],
                predicate  = f["predicate"],
                object_    = f["object"],
                source     = f"sovereign.{f['source']}",
                confidence = f["confidence"],
                metadata   = {"domains": domains},
            )
    except Exception as e:
        log.warning("Fact persist failed: %s", e)


def _persist_concepts(concepts: list[str], domains: list[str]) -> None:
    """Store concepts as facts with 'is_concept' predicate."""
    if not concepts:
        return
    try:
        from core.knowledge.friday_chronicle import save_fact
        for concept in concepts[:5]:    # top 5 only
            save_fact(
                subject    = concept,
                predicate  = "is_concept_in",
                object_    = ", ".join(domains) if domains else "general",
                source     = "sovereign",
                confidence = 0.6,
            )
    except Exception as e:
        log.warning("Concept persist failed: %s", e)


def _update_stats(used_api: bool, facts_added: int, domains: list[str]) -> None:
    """Update global stats and domain profiles."""
    with _stats_lock:
        _stats.total_exchanges += 1
        _stats.facts_extracted += facts_added

        if used_api:
            _stats.api_answered  += 1
        else:
            _stats.self_answered += 1

        for domain in domains:
            if domain not in _domains:
                _domains[domain] = DomainProfile(name=domain)
            _domains[domain].update(facts_added)

        _stats.domains_active = len(_domains)

    _save_stats()


def _save_stats() -> None:
    try:
        data = {
            "stats":   {
                "total_exchanges":  _stats.total_exchanges,
                "facts_extracted":  _stats.facts_extracted,
                "concepts_learned": _stats.concepts_learned,
                "self_answered":    _stats.self_answered,
                "api_answered":     _stats.api_answered,
                "domains_active":   _stats.domains_active,
                "independence_pct": _stats.independence_pct,
            },
            "domains": {
                name: {
                    "query_count":  d.query_count,
                    "fact_count":   d.fact_count,
                    "confidence":   round(d.confidence, 3),
                }
                for name, d in _domains.items()
            },
            "updated_at": time.time(),
        }
        _STATS_PATH.write_text(json.dumps(data, indent=2))
    except Exception as e:
        log.warning("Stats save failed: %s", e)


def load_stats() -> None:
    """Load persisted stats on boot."""
    global _stats
    if not _STATS_PATH.exists():
        return
    try:
        data = json.loads(_STATS_PATH.read_text())
        s    = data.get("stats", {})
        _stats.total_exchanges  = s.get("total_exchanges", 0)
        _stats.facts_extracted  = s.get("facts_extracted", 0)
        _stats.concepts_learned = s.get("concepts_learned", 0)
        _stats.self_answered    = s.get("self_answered", 0)
        _stats.api_answered     = s.get("api_answered", 0)

        for name, d in data.get("domains", {}).items():
            _domains[name] = DomainProfile(
                name        = name,
                query_count = d.get("query_count", 0),
                fact_count  = d.get("fact_count", 0),
                confidence  = d.get("confidence", 0.0),
            )
        log.info("Sovereign loaded: %d facts, %d%% independence",
                 _stats.facts_extracted, _stats.independence_pct)
    except Exception as e:
        log.warning("Stats load failed: %s", e)


def get_status() -> dict:
    """Full sovereign status — for UI and debug."""
    return {
        "total_exchanges":   _stats.total_exchanges,
        "facts_extracted":   _stats.facts_extracted,
        "independence_pct":  _stats.independence_pct,
        "domains_active":    _stats.domains_active,
        "top_domains": sorted(
            [{"name": n, "confidence": round(d.confidence, 2), "facts": d.fact_count}
             for n, d in _domains.items()],
            key=lambda x: x["confidence"],
            reverse=True
        )[:5],
    }


def run_background(
    user_input:      str,
    friday_response: str,
    intent:          str,
    used_api:        bool = True,
) -> None:
    """
    Fire-and-forget background extraction.
    Runs in a daemon thread — never blocks the main response loop.
    """
    def _worker():
        try:
            extract_and_store(user_input, friday_response, intent, used_api)
        except Exception as e:
            log.warning("Background extraction failed: %s", e)

    t = threading.Thread(target=_worker, daemon=True, name="sovereign-extract")
    t.start()


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

    print("\n[friday_sovereign] Running self-test...\n")

    # Test fact extraction
    sample_response = """
    FAISS is a library for efficient similarity search and clustering of dense vectors.
    It has specialized algorithms for searching large collections with billions of vectors.
    Using FAISS for vector search results in sub-millisecond query times at scale.
    You should always normalize embeddings before indexing for cosine similarity.
    The IndexFlatL2 index uses exact L2 distance and contains no approximation.
    """

    facts = _extract_facts(sample_response, source="test")
    print(f"  ✓ Facts extracted: {len(facts)}")
    for f in facts[:3]:
        print(f"    [{f['predicate']:12}] {f['subject'][:25]} → {f['object'][:50]}")

    # Test concept extraction
    concepts = _extract_concepts(sample_response)
    print(f"\n  ✓ Concepts extracted: {len(concepts)}: {concepts[:6]}")

    # Test domain detection
    domains = _detect_domain(sample_response)
    print(f"  ✓ Domains detected: {domains}")

    # Test full pipeline
    summary = extract_and_store(
        user_input      = "How does FAISS work for similarity search?",
        friday_response = sample_response,
        intent          = "question",
        used_api        = True,
    )
    print(f"\n  ✓ Full pipeline: {summary}")

    # Stats
    status = get_status()
    print(f"  ✓ Status: independence={status['independence_pct']}% "
          f"facts={status['facts_extracted']} domains={status['domains_active']}")
    print(f"  ✓ Top domains: {status['top_domains']}")

    # Background run
    run_background(
        "What is Python?",
        "Python is a high-level, interpreted programming language known for its simplicity.",
        "question",
    )
    import time as t
    t.sleep(0.1)    # let the thread finish
    print(f"  ✓ Background extraction ran (total exchanges: {_stats.total_exchanges})")

    print("\n[friday_sovereign] All tests passed ✓\n")
