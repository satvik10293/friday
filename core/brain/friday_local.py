"""
friday_local.py — Friday 3.0
On-device reasoning QA. Instead of parroting the nearest stored answer, Friday
RETRIEVES the knowledge most relevant to a question (from her Obsidian vault,
past conversations, and extracted facts), then READS it with a local generative
model and writes a fresh answer in her own words.

Architecture (good fit for small data on CPU):
  retrieval  → memorise: embed her knowledge with all-MiniLM-L6-v2 (this is what
               train() builds — the index over everything she knows)
  reader     → generalise: a pretrained instruction model (flan-t5) comprehends
               the retrieved passages and composes the answer

  answer(q)  = retrieve relevant passages → if none relevant, return None (defer
               to Groq); otherwise have the reader synthesise an answer from them.

Wired into friday_neural as the highest-priority responder (local-first).
Retrain the retrieval index after she learns:  python core/friday_local.py --train
"""

import sys
import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.local")

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

_DATA_DIR   = _ROOT / "data"
_INDEX_NPZ  = _DATA_DIR / "local_qa.npz"
_INDEX_META = _DATA_DIR / "local_qa.json"

_EMBED_MODEL    = "all-MiniLM-L6-v2"
_READER_MODEL   = "google/flan-t5-base"   # local generative reader (CPU-friendly)
_RETRIEVAL_FLOOR = 0.30   # min cosine sim to consider she has relevant knowledge
_TOPK            = 4      # passages fed to the reader

# ── lazy singletons ─────────────────────────────────────────────────────────--
_embedder = None
_reader   = None
_emb      = None      # np.ndarray (N, D) float32, L2-normalized
_meta     = None      # list[dict] parallel to _emb rows: {answer, source, key}


def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        log.info("Loading retrieval model: %s", _EMBED_MODEL)
        _embedder = SentenceTransformer(_EMBED_MODEL)
    return _embedder


def _get_reader():
    """Lazy-load the local generative reader as (tokenizer, model).
    Returns None if unavailable (caller then defers to the cloud)."""
    global _reader
    if _reader is None:
        try:
            from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
            log.info("Loading local reasoning model: %s (first run downloads it)", _READER_MODEL)
            tok = AutoTokenizer.from_pretrained(_READER_MODEL)
            mdl = AutoModelForSeq2SeqLM.from_pretrained(_READER_MODEL)
            _reader = (tok, mdl)
        except Exception as e:
            log.warning("Reader model unavailable (%s) — will defer to cloud", e)
            _reader = False   # sentinel: tried and failed
    return _reader or None


# ── corpus assembly (the retrieval "training" data) ─────────────────────────────
def _build_corpus() -> list[dict]:
    """Collect (key, answer, source) items from everything Friday knows."""
    items: list[dict] = []

    # 1. Obsidian vault notes — content is the knowledge; title + content are keys.
    try:
        from core.knowledge.friday_world import VaultStore, VAULT_DIR
        vs = VaultStore(VAULT_DIR)
        for rec in vs.get_recent(category="", limit=1_000_000):
            content = (rec.get("content") or "").strip()
            title   = (rec.get("title") or "").strip()
            if len(content) < 20:
                continue
            key = f"{title}. {content}" if title else content
            items.append({"key": key, "answer": content, "source": "vault"})
            if title:
                items.append({"key": title, "answer": content, "source": "vault"})
    except Exception as e:
        log.warning("vault corpus failed: %s", e)

    # 2. Chronicle — past Q&A pairs + extracted facts.
    try:
        import sqlite3
        cdb = _DATA_DIR / "chronicle.db"
        if cdb.exists():
            con = sqlite3.connect(str(cdb))
            rows = con.execute(
                "SELECT role, content FROM memories ORDER BY session_id, timestamp, id"
            ).fetchall()
            pending: Optional[str] = None
            for role, content in rows:
                content = (content or "").strip()
                if not content:
                    continue
                if role == "user":
                    pending = content
                elif role in ("friday", "assistant") and pending:
                    items.append({"key": pending, "answer": content, "source": "chat"})
                    pending = None
            for subj, pred, obj in con.execute(
                "SELECT subject, predicate, object FROM facts"
            ):
                sent = " ".join(
                    x for x in (str(subj or ""),
                                str(pred or "").replace("_", " "),
                                str(obj or "")) if x
                ).strip()
                if len(sent) >= 10:
                    items.append({"key": sent, "answer": sent, "source": "fact"})
            con.close()
    except Exception as e:
        log.warning("chronicle corpus failed: %s", e)

    seen, out = set(), []
    for it in items:
        sig = (it["key"], it["answer"])
        if sig not in seen:
            seen.add(sig)
            out.append(it)
    return out


# ── train (build the retrieval index) ───────────────────────────────────────────
def train() -> dict:
    import numpy as np
    corpus = _build_corpus()
    if not corpus:
        log.warning("Empty corpus — nothing to train on.")
        return {"trained": 0, "by_source": {}}

    keys = [it["key"][:512] for it in corpus]
    emb  = _get_embedder().encode(
        keys, normalize_embeddings=True, batch_size=32, show_progress_bar=False
    )
    emb  = np.asarray(emb, dtype="float32")

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(_INDEX_NPZ, emb=emb)
    meta = [{"answer": it["answer"], "source": it["source"], "key": it["key"][:160]}
            for it in corpus]
    _INDEX_META.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    global _emb, _meta
    _emb, _meta = emb, meta

    by_src: dict = {}
    for it in corpus:
        by_src[it["source"]] = by_src.get(it["source"], 0) + 1
    log.info("Local retrieval index trained on %d items %s", len(corpus), by_src)
    return {"trained": len(corpus), "by_source": by_src}


# ── load ──────────────────────────────────────────────────────────────────────--
def _ensure_loaded() -> bool:
    global _emb, _meta
    if _emb is not None and _meta is not None:
        return True
    if not (_INDEX_NPZ.exists() and _INDEX_META.exists()):
        return False
    try:
        import numpy as np
        _emb  = np.load(_INDEX_NPZ)["emb"]
        _meta = json.loads(_INDEX_META.read_text(encoding="utf-8"))
        return True
    except Exception as e:
        log.warning("Local index load failed: %s", e)
        return False


# ── retrieve ───────────────────────────────────────────────────────────────────
def retrieve(question: str, k: int = _TOPK) -> list[dict]:
    """Return the k knowledge passages most relevant to the question."""
    if not question or not question.strip() or not _ensure_loaded():
        return []
    import numpy as np
    qv   = np.asarray(_get_embedder().encode([question], normalize_embeddings=True),
                      dtype="float32")[0]
    sims = _emb @ qv
    order = np.argsort(-sims)[:k]
    # de-dupe identical answers while preserving order
    seen, out = set(), []
    for i in order:
        ans = _meta[int(i)]["answer"]
        if ans in seen:
            continue
        seen.add(ans)
        out.append({"passage": ans, "source": _meta[int(i)]["source"],
                    "score": float(sims[int(i)])})
    return out


# ── answer (retrieve → comprehend → generate) ───────────────────────────────────
def answer(question: str, floor: float = _RETRIEVAL_FLOOR) -> Optional[str]:
    """Reason over her own knowledge to answer. Returns None to defer to the cloud
    when she has no relevant knowledge, or when the local reader is unavailable."""
    if not question or not question.strip():
        return None
    hits = retrieve(question, _TOPK)
    if not hits or hits[0]["score"] < floor:
        log.debug("No relevant local knowledge (best=%.2f) — deferring to cloud",
                  hits[0]["score"] if hits else -1.0)
        return None

    reader = _get_reader()
    if reader is None:
        return None   # no local generator → let the cloud answer
    tok, mdl = reader

    context = "\n".join(f"- {h['passage']}" for h in hits)[:1500]
    prompt = (
        "Use the context to answer the question in a clear, complete sentence, "
        "in your own words. If the context doesn't cover it, say you are not sure.\n\n"
        f"Context:\n{context}\n\nQuestion: {question}\nAnswer:"
    )
    try:
        ids  = tok(prompt, return_tensors="pt", truncation=True, max_length=512).input_ids
        gen  = mdl.generate(ids, max_new_tokens=128, num_beams=2)
        text = tok.decode(gen[0], skip_special_tokens=True).strip()
    except Exception as e:
        log.warning("Local reader failed: %s — deferring to cloud", e)
        return None

    if not text or text.lower().startswith(("i am not sure", "i'm not sure", "not sure")):
        return None
    if len(text) < 20:
        # Too thin to be a good standalone reply — let the cloud answer fully.
        log.debug("Local answer too short (%r) — deferring to cloud", text)
        return None
    log.info("Local reasoned answer (top score=%.2f, %d passages)", hits[0]["score"], len(hits))
    return text


def is_ready() -> bool:
    return _ensure_loaded()


def stats() -> dict:
    if not _ensure_loaded():
        return {"ready": False, "items": 0, "by_source": {}}
    by_src: dict = {}
    for m in _meta:
        by_src[m["source"]] = by_src.get(m["source"], 0) + 1
    return {"ready": True, "items": len(_meta), "by_source": by_src, "reader": _READER_MODEL}


# ── CLI ───────────────────────────────────────────────────────────────────────--
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    import argparse
    ap = argparse.ArgumentParser(description="Friday local reasoning QA")
    ap.add_argument("--train", action="store_true", help="(re)build the retrieval index")
    ap.add_argument("--ask", type=str, default="", help="ask a question")
    ap.add_argument("--floor", type=float, default=_RETRIEVAL_FLOOR)
    args = ap.parse_args()

    if args.train:
        print("[train]", train())
    if args.ask:
        print("Q:", args.ask)
        hits = retrieve(args.ask)
        print("retrieved:", [(round(h["score"], 2), h["source"]) for h in hits])
        a = answer(args.ask, floor=args.floor)
        print("A:", a if a else "(no relevant knowledge — would fall back to Groq)")
    if not args.train and not args.ask:
        print("[stats]", stats())
