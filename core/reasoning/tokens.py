"""
core/reasoning/tokens.py — FRIDAY 5.x (M57)
Her own tokens: the internal language she thinks in.

The owner's directive: the user speaks natural language, but ALL of her
thinking happens in tokens — the way a real model works. This module is her
tokenizer, and it is genuinely HERS twice over:

    · the vocabulary is LEARNED from her own corpus (vault notes + knowledge
      store) by byte-pair encoding — her merges reflect what she has read,
      so "photosynthesis" tokenizes tightly once she has studied it
    · the special tokens are her COGNITIVE ops — <plan> <step> <exact>
      <recall> <native> <answer> <defer> — so a thought trace is a readable
      program of her own mind, not a string

Natural language exists only at the boundary (STT in, TTS out). Between the
stages of the deliberate engine, plans, steps, and working memory travel as
token-ID sequences; the DecisionLog-adjacent thought trace records them.

This is also the load-bearing first organ of any future neural core of her
own: a model is a tokenizer plus weights — the tokenizer now exists, trained
on her life. Training is pure Python (no external deps), lazy, and cached to
data/tokenizer.json; retrain with  python -m core.reasoning.tokens --train
after she has learned a lot of new material.
"""

from __future__ import annotations

import json
import logging
import re
import string
import threading
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("friday.reasoning.tokens")

_ROOT = Path(__file__).resolve().parents[2]
_CACHE_PATH = _ROOT / "data" / "tokenizer.json"

_DEFAULT_VOCAB = 2048          # small, honest, CPU-friendly
_MIN_PAIR_COUNT = 2            # a merge must be seen at least twice
_WORD_RE = re.compile(r"\s+")

# her cognitive ops — the grammar of a thought trace
SPECIALS = ["<pad>", "<unk>", "<q>", "</q>", "<plan>", "<step>", "<exact>",
            "<recall>", "<native>", "<code>", "<answer>", "<defer>", "<sep>"]


def _pretokenize(text: str) -> list[str]:
    """Whitespace words, lowercased, with a word-boundary marker so merges
    never cross words (the classic BPE setup)."""
    return [w + "▁" for w in _WORD_RE.split((text or "").lower()) if w]


class FridayTokenizer:
    """Byte-pair encoding learned from her own corpus. Deterministic,
    dependency-free, reversible (decode(encode(x)) round-trips modulo
    whitespace/case — thinking doesn't need capitalization)."""

    def __init__(self, merges: Optional[list] = None,
                 vocab: Optional[list] = None) -> None:
        self.merges: list[tuple[str, str]] = [tuple(m) for m in (merges or [])]
        self._ranks = {m: i for i, m in enumerate(self.merges)}
        # id space: specials first, then single characters, then merge tokens
        self.vocab: list[str] = list(vocab or [])
        self._ids = {tok: i for i, tok in enumerate(self.vocab)}
        self._lock = threading.Lock()

    # ── training: her vocabulary, from her life ──────────────────────────────────
    @classmethod
    def train(cls, corpus: Iterable[str], *, vocab_size: int = _DEFAULT_VOCAB
              ) -> "FridayTokenizer":
        words = Counter()
        for text in corpus:
            words.update(_pretokenize(text))
        # every word starts as a tuple of characters. The full printable-ASCII
        # base alphabet is always present so thinking is LOSSLESS: a math step
        # ("48 * 12 + 5") must survive token space with every digit intact.
        splits = {w: tuple(w) for w in words}
        base = {c for c in string.printable if not c.isspace()} | {"▁"}
        chars = sorted({c for w in words for c in w} | base)
        merges: list[tuple[str, str]] = []
        budget = max(0, vocab_size - len(SPECIALS) - len(chars))
        for _ in range(budget):
            pairs: Counter = Counter()
            for w, freq in words.items():
                sym = splits[w]
                for a, b in zip(sym, sym[1:]):
                    pairs[(a, b)] += freq
            if not pairs:
                break
            (a, b), count = pairs.most_common(1)[0]
            if count < _MIN_PAIR_COUNT:
                break
            merges.append((a, b))
            merged = a + b
            for w, sym in splits.items():
                if a not in sym:
                    continue
                out, i = [], 0
                while i < len(sym):
                    if i < len(sym) - 1 and sym[i] == a and sym[i + 1] == b:
                        out.append(merged)
                        i += 2
                    else:
                        out.append(sym[i])
                        i += 1
                splits[w] = tuple(out)
        vocab = list(SPECIALS) + chars + [a + b for a, b in merges]
        tok = cls(merges=merges, vocab=vocab)
        log.info("tokenizer trained: %d tokens (%d merges) from %d words",
                 len(vocab), len(merges), len(words))
        return tok

    # ── encode / decode ──────────────────────────────────────────────────────────
    def _bpe(self, word: str) -> list[str]:
        sym = list(word)
        while len(sym) > 1:
            best, best_rank = None, None
            for i, pair in enumerate(zip(sym, sym[1:])):
                rank = self._ranks.get(pair)
                if rank is not None and (best_rank is None or rank < best_rank):
                    best, best_rank = i, rank
            if best is None:
                break
            sym[best:best + 2] = [sym[best] + sym[best + 1]]
        return sym

    def encode(self, text: str, *, marker: Optional[str] = None) -> list[int]:
        """Text → her token IDs. `marker` prefixes a cognitive op token."""
        unk = self._ids.get("<unk>", 1)
        ids: list[int] = []
        if marker is not None:
            ids.append(self._ids.get(marker, unk))
        for word in _pretokenize(text):
            for piece in self._bpe(word):
                ids.append(self._ids.get(piece, unk))
        return ids

    def decode(self, ids: Iterable[int]) -> str:
        parts: list[str] = []
        for i in ids:
            if 0 <= i < len(self.vocab):
                tok = self.vocab[i]
                if tok in SPECIALS:
                    continue                    # ops are thought, not speech
                parts.append(tok)
        return "".join(parts).replace("▁", " ").strip()

    def explain(self, ids: Iterable[int]) -> list[str]:
        """The human-readable token strings — for showing her thoughts."""
        return [self.vocab[i] if 0 <= i < len(self.vocab) else "<unk>"
                for i in ids]

    def op(self, name: str) -> int:
        return self._ids.get(name, self._ids.get("<unk>", 1))

    @property
    def size(self) -> int:
        return len(self.vocab)

    # ── persistence ──────────────────────────────────────────────────────────────
    def save(self, path: Optional[Path] = None) -> Path:
        path = path or _CACHE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "version": 1, "merges": self.merges, "vocab": self.vocab,
        }), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Optional[Path] = None) -> Optional["FridayTokenizer"]:
        path = path or _CACHE_PATH
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(merges=data.get("merges"), vocab=data.get("vocab"))
        except (OSError, ValueError):
            return None


# ── her corpus: what she has read and learned ─────────────────────────────────
def _her_corpus(knowledge=None, max_docs: int = 400) -> list[str]:
    texts: list[str] = []
    if knowledge is not None:
        try:                                   # everything in her own store
            for e in knowledge.store.all_entries()[:max_docs]:
                body = f"{getattr(e, 'title', '')} {getattr(e, 'content', '')}"
                if body.strip():
                    texts.append(body)
        except Exception:  # noqa: BLE001 — a store fault just means less corpus
            log.debug("knowledge corpus read failed", exc_info=True)
    if not texts:                              # cold start: seed with her docs
        for name in ("README.md", "CLAUDE.md"):
            try:
                texts.append((_ROOT / name).read_text(encoding="utf-8")[:40000])
            except OSError:
                pass
    return texts or ["friday thinks in her own tokens"]


_tokenizer: Optional[FridayTokenizer] = None
_tok_lock = threading.Lock()


def get_tokenizer(knowledge=None) -> FridayTokenizer:
    """The process-wide tokenizer: cached on disk, trained from her corpus on
    first need. Never raises — worst case is a fresh minimal training."""
    global _tokenizer
    with _tok_lock:
        if _tokenizer is not None:
            return _tokenizer
        tok = FridayTokenizer.load()
        if tok is None or tok.size <= len(SPECIALS):
            tok = FridayTokenizer.train(_her_corpus(knowledge))
            try:
                tok.save()
            except OSError:                     # read-only disk → in-memory only
                log.debug("tokenizer cache save failed", exc_info=True)
        _tokenizer = tok
        return tok


def _main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="FRIDAY's own tokenizer")
    ap.add_argument("--train", action="store_true", help="retrain from her corpus")
    ap.add_argument("--encode", type=str, default="", help="show tokens for text")
    args = ap.parse_args(argv)
    if args.train:
        knowledge = None
        try:
            from core.knowledge.knowledge_service import get_knowledge_service
            knowledge = get_knowledge_service()
        except Exception:  # noqa: BLE001
            pass
        tok = FridayTokenizer.train(_her_corpus(knowledge))
        print(f"trained: {tok.size} tokens -> {tok.save()}")
        return 0
    tok = get_tokenizer()
    text = args.encode or "friday thinks in her own tokens"
    ids = tok.encode(text, marker="<q>")
    print(f"vocab={tok.size}  ids={ids}")
    # cp1252 consoles can't render the word marker — display it as "_"
    shown = " ".join(t.replace("▁", "_") for t in tok.explain(ids))
    print("tokens:", shown.encode("ascii", "replace").decode("ascii"))
    print("decoded:", tok.decode(ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
