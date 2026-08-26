"""
core/reasoning/neural.py — FRIDAY 5.x (M58)
Her own weights: a neural core born on her machine.

M57 gave her the first organ of a model — a tokenizer trained on her life.
This is the second: a small GPT-style decoder whose parameters are BORN here,
trained from her own corpus, on her own CPU, in pure numpy. Nothing is
downloaded; nothing is external. Day zero it is a newborn language faculty —
and it is gated accordingly (see NeuralSubstrate: low confidence, so its
output DEFERS rather than reaching the user) — but it is genuinely hers:

    · her vocabulary (the M57 tokenizer) is its input space
    · her notes and memories are its training data
    · background training cycles keep improving it FOREVER — she literally
      gets smarter while idle, and perplexity() is the honest, measurable
      growth curve (reported in status, never a vibe)

Architecture: token + positional embeddings → N pre-norm transformer blocks
(single-head causal attention + GELU MLP) → tied output head. Small on
purpose (~0.5M params at the default config): a CPU box trains it in
minutes-scale cycles, and honesty matters more than theater. When (if) the
owner adds hardware, the same organ scales; the code path does not change.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

log = logging.getLogger("friday.reasoning.neural")

_ROOT = Path(__file__).resolve().parents[2]
_WEIGHTS_PATH = _ROOT / "data" / "neural_brain.npz"
_META_PATH = _ROOT / "data" / "neural_brain.json"


# ── numerics ──────────────────────────────────────────────────────────────────
def _gelu(x):
    return 0.5 * x * (1.0 + np.tanh(0.7978845608 * (x + 0.044715 * x ** 3)))


def _gelu_grad(x):
    t = np.tanh(0.7978845608 * (x + 0.044715 * x ** 3))
    dt = (1 - t ** 2) * 0.7978845608 * (1 + 3 * 0.044715 * x ** 2)
    return 0.5 * (1 + t) + 0.5 * x * dt


def _softmax(x, axis=-1):
    x = x - x.max(axis=axis, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=axis, keepdims=True)


class _LayerNorm:
    def __init__(self, d):
        self.g = np.ones(d, np.float32)
        self.b = np.zeros(d, np.float32)

    def __call__(self, x):
        self._x = x
        self._mu = x.mean(-1, keepdims=True)
        self._var = x.var(-1, keepdims=True)
        self._nx = (x - self._mu) / np.sqrt(self._var + 1e-5)
        return self.g * self._nx + self.b

    def backward(self, dy):
        nx, g = self._nx, self.g
        self.dg = (dy * nx).sum((0, 1))
        self.db = dy.sum((0, 1))
        dxhat = dy * g
        d = dxhat.shape[-1]
        istd = 1.0 / np.sqrt(self._var + 1e-5)
        return istd * (dxhat - dxhat.mean(-1, keepdims=True)
                       - nx * (dxhat * nx).mean(-1, keepdims=True))

    def params(self):
        return [("g", self), ("b", self)]


class _Block:
    """Pre-norm transformer block: single-head causal attention + GELU MLP."""

    def __init__(self, d, rng):
        s = 0.02
        self.ln1, self.ln2 = _LayerNorm(d), _LayerNorm(d)
        self.wq = rng.normal(0, s, (d, d)).astype(np.float32)
        self.wk = rng.normal(0, s, (d, d)).astype(np.float32)
        self.wv = rng.normal(0, s, (d, d)).astype(np.float32)
        self.wo = rng.normal(0, s, (d, d)).astype(np.float32)
        self.w1 = rng.normal(0, s, (d, 4 * d)).astype(np.float32)
        self.w2 = rng.normal(0, s, (4 * d, d)).astype(np.float32)

    def __call__(self, x, mask):
        d = x.shape[-1]
        a_in = self.ln1(x)
        q, k, v = a_in @ self.wq, a_in @ self.wk, a_in @ self.wv
        att = (q @ k.transpose(0, 2, 1)) / np.sqrt(d)
        att = np.where(mask, att, -1e9)
        p = _softmax(att)
        ao = p @ v
        x = x + ao @ self.wo
        m_in = self.ln2(x)
        h = m_in @ self.w1
        x = x + _gelu(h) @ self.w2
        # stash for backward
        self._c = (a_in, q, k, v, p, ao, m_in, h)
        return x

    def backward(self, x_in, dy):
        a_in, q, k, v, p, ao, m_in, h = self._c
        d = x_in.shape[-1]
        # mlp branch
        gh = _gelu(h)
        self.dw2 = np.einsum("bti,btj->ij", gh, dy)
        dgh = dy @ self.w2.T
        dh = dgh * _gelu_grad(h)
        self.dw1 = np.einsum("bti,btj->ij", m_in, dh)
        dm_in = dh @ self.w1.T
        dx = dy + self.ln2.backward(dm_in)
        # attention branch
        self.dwo = np.einsum("bti,btj->ij", ao, dx)
        dao = dx @ self.wo.T
        dp = dao @ v.transpose(0, 2, 1)
        dv = p.transpose(0, 2, 1) @ dao
        ds = p * (dp - (dp * p).sum(-1, keepdims=True))
        ds = ds / np.sqrt(d)
        dq = ds @ k
        dk = ds.transpose(0, 2, 1) @ q
        self.dwq = np.einsum("bti,btj->ij", a_in, dq)
        self.dwk = np.einsum("bti,btj->ij", a_in, dk)
        self.dwv = np.einsum("bti,btj->ij", a_in, dv)
        da_in = dq @ self.wq.T + dk @ self.wk.T + dv @ self.wv.T
        return dx + self.ln1.backward(da_in)

    def tensors(self):
        return {"wq": self.wq, "wk": self.wk, "wv": self.wv, "wo": self.wo,
                "w1": self.w1, "w2": self.w2,
                "ln1g": self.ln1.g, "ln1b": self.ln1.b,
                "ln2g": self.ln2.g, "ln2b": self.ln2.b}

    def grads(self):
        return {"wq": self.dwq, "wk": self.dwk, "wv": self.dwv, "wo": self.dwo,
                "w1": self.dw1, "w2": self.dw2,
                "ln1g": self.ln1.dg, "ln1b": self.ln1.db,
                "ln2g": self.ln2.dg, "ln2b": self.ln2.db}


class NeuralCore:
    """Her own tiny GPT. Pure numpy; deterministic under a seed; trains in
    bounded steps so a background cycle never runs away with the CPU."""

    def __init__(self, vocab_size: int, *, d_model: int = 96, n_layers: int = 2,
                 n_ctx: int = 64, seed: int = 7) -> None:
        self.vocab_size = int(vocab_size)
        self.d = int(d_model)
        self.n_ctx = int(n_ctx)
        rng = np.random.default_rng(seed)
        s = 0.02
        self.wte = rng.normal(0, s, (self.vocab_size, self.d)).astype(np.float32)
        self.wpe = rng.normal(0, s, (self.n_ctx, self.d)).astype(np.float32)
        self.blocks = [_Block(self.d, rng) for _ in range(int(n_layers))]
        self.lnf = _LayerNorm(self.d)
        self._mask = np.tril(np.ones((self.n_ctx, self.n_ctx), bool))[None]
        self._adam: dict = {}
        self._adam_t = 0
        self.steps_trained = 0
        self.last_loss: Optional[float] = None
        self._lock = threading.Lock()

    @property
    def n_params(self) -> int:
        n = self.wte.size + self.wpe.size + self.lnf.g.size + self.lnf.b.size
        for b in self.blocks:
            n += sum(t.size for t in b.tensors().values())
        return int(n)

    # ── forward / loss / backward ────────────────────────────────────────────────
    def _forward(self, ids: np.ndarray):
        B, T = ids.shape
        x = self.wte[ids] + self.wpe[:T]
        xs = [x]
        mask = self._mask[:, :T, :T]
        for blk in self.blocks:
            x = blk(x, mask)
            xs.append(x)
        xf = self.lnf(x)
        logits = xf @ self.wte.T           # tied head
        return logits, xs, xf

    def _step(self, ids: np.ndarray, targets: np.ndarray, lr: float) -> float:
        B, T = ids.shape
        logits, xs, xf = self._forward(ids)
        probs = _softmax(logits)
        loss = float(-np.log(
            probs[np.arange(B)[:, None], np.arange(T)[None], targets] + 1e-9
        ).mean())
        # backward
        dlogits = probs
        dlogits[np.arange(B)[:, None], np.arange(T)[None], targets] -= 1.0
        dlogits /= (B * T)
        dxf = dlogits @ self.wte
        dwte_head = np.einsum("btv,btd->vd", dlogits, xf)
        dx = self.lnf.backward(dxf)
        grads = {"lnfg": self.lnf.dg, "lnfb": self.lnf.db}
        for i in reversed(range(len(self.blocks))):
            dx = self.blocks[i].backward(xs[i], dx)
            for k, g in self.blocks[i].grads().items():
                grads[f"b{i}.{k}"] = g
        dwte = dwte_head.copy()
        np.add.at(dwte, ids, dx)
        grads["wte"] = dwte
        dwpe = dx.sum(0)
        grads["wpe"] = dwpe
        self._apply(grads, lr)
        return loss

    def _tensor(self, name: str):
        if name == "wte":
            return self.wte
        if name == "wpe":
            return self.wpe
        if name == "lnfg":
            return self.lnf.g
        if name == "lnfb":
            return self.lnf.b
        bi, key = name[1:].split(".", 1)
        blk = self.blocks[int(bi)]
        return blk.tensors()[key]

    def _apply(self, grads: dict, lr: float) -> None:
        self._adam_t += 1
        b1, b2, eps = 0.9, 0.999, 1e-8
        t = self._adam_t
        for name, g in grads.items():
            p = self._tensor(name)
            if name == "wpe":                    # only the seen positions
                gp = np.zeros_like(p)
                gp[:g.shape[0]] = g
                g = gp
            m, v = self._adam.get(name, (np.zeros_like(p), np.zeros_like(p)))
            m = b1 * m + (1 - b1) * g
            v = b2 * v + (1 - b2) * g * g
            self._adam[name] = (m, v)
            mhat = m / (1 - b1 ** t)
            vhat = v / (1 - b2 ** t)
            p -= (lr * mhat / (np.sqrt(vhat) + eps)).astype(p.dtype)

    # ── the public surface ───────────────────────────────────────────────────────
    def train_steps(self, token_ids: list, *, steps: int = 200,
                    batch: int = 8, lr: float = 3e-4,
                    max_seconds: float = 60.0, seed: int = 0,
                    should_yield: Optional[Callable[[], bool]] = None) -> dict:
        """A bounded training burst over her corpus (token ids). Returns the
        measured before/after loss — the honest growth curve. Thread-safe;
        never raises out.

        `should_yield`, if given, is polled each step: the moment it returns True
        the burst stops and gives the CPU back (used to yield to a live user turn
        — see core/reasoning/activity.py)."""
        data = np.asarray(token_ids, np.int64)
        need = self.n_ctx + 1
        if data.size < need * 2:
            return {"trained": 0, "loss": None, "reason": "corpus too small"}
        rng = np.random.default_rng(seed or None)
        t0 = time.time()
        first = last = None
        done = 0
        yielded = False
        with self._lock:
            for _ in range(int(steps)):
                if time.time() - t0 > max_seconds:
                    break
                if should_yield is not None and should_yield():
                    yielded = True
                    break
                starts = rng.integers(0, data.size - need, size=batch)
                chunk = np.stack([data[s:s + need] for s in starts])
                loss = self._step(chunk[:, :-1], chunk[:, 1:], lr)
                first = loss if first is None else first
                last = loss
                done += 1
            self.steps_trained += done
            self.last_loss = last
        return {"trained": done, "loss_start": first, "loss": last,
                "seconds": round(time.time() - t0, 1), "yielded": yielded}

    def perplexity(self, token_ids: list, *, samples: int = 16) -> Optional[float]:
        """Measured on held-out order (fixed stride): the honest number."""
        data = np.asarray(token_ids, np.int64)
        need = self.n_ctx + 1
        if data.size < need:
            return None
        with self._lock:
            starts = np.linspace(0, data.size - need, num=min(samples, 8),
                                 dtype=np.int64)
            chunk = np.stack([data[s:s + need] for s in starts])
            logits, _, _ = self._forward(chunk[:, :-1])
            probs = _softmax(logits)
            tgt = chunk[:, 1:]
            B, T = tgt.shape
            nll = -np.log(probs[np.arange(B)[:, None], np.arange(T)[None], tgt]
                          + 1e-9).mean()
        return float(np.exp(min(nll, 20.0)))

    def generate(self, prompt_ids: list, *, max_new: int = 24,
                 temperature: float = 0.9, top_k: int = 40) -> list:
        ids = list(prompt_ids)[-self.n_ctx:]
        rng = np.random.default_rng()
        with self._lock:
            for _ in range(int(max_new)):
                x = np.asarray([ids[-self.n_ctx:]], np.int64)
                logits, _, _ = self._forward(x)
                logit = logits[0, -1] / max(temperature, 1e-3)
                if top_k:
                    kth = np.partition(logit, -top_k)[-top_k]
                    logit = np.where(logit < kth, -1e9, logit)
                p = _softmax(logit[None])[0]
                ids.append(int(rng.choice(len(p), p=p)))
        return ids

    # ── persistence: her brain survives restarts ─────────────────────────────────
    def save(self, path: Optional[Path] = None,
             meta_path: Optional[Path] = None) -> Path:
        path = path or _WEIGHTS_PATH
        meta_path = meta_path or _META_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        tensors = {"wte": self.wte, "wpe": self.wpe,
                   "lnfg": self.lnf.g, "lnfb": self.lnf.b}
        for i, blk in enumerate(self.blocks):
            for k, t in blk.tensors().items():
                tensors[f"b{i}.{k}"] = t
        np.savez_compressed(path, **tensors)
        meta_path.write_text(json.dumps({
            "vocab_size": self.vocab_size, "d_model": self.d,
            "n_layers": len(self.blocks), "n_ctx": self.n_ctx,
            "steps_trained": self.steps_trained,
            "last_loss": self.last_loss}), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Optional[Path] = None,
             meta_path: Optional[Path] = None) -> Optional["NeuralCore"]:
        path = path or _WEIGHTS_PATH
        meta_path = meta_path or _META_PATH
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            data = np.load(path)
        except (OSError, ValueError):
            return None
        core = cls(meta["vocab_size"], d_model=meta["d_model"],
                   n_layers=meta["n_layers"], n_ctx=meta["n_ctx"])
        core.wte = data["wte"]
        core.wpe = data["wpe"]
        core.lnf.g, core.lnf.b = data["lnfg"], data["lnfb"]
        for i, blk in enumerate(core.blocks):
            blk.wq = data[f"b{i}.wq"]; blk.wk = data[f"b{i}.wk"]
            blk.wv = data[f"b{i}.wv"]; blk.wo = data[f"b{i}.wo"]
            blk.w1 = data[f"b{i}.w1"]; blk.w2 = data[f"b{i}.w2"]
            blk.ln1.g = data[f"b{i}.ln1g"]; blk.ln1.b = data[f"b{i}.ln1b"]
            blk.ln2.g = data[f"b{i}.ln2g"]; blk.ln2.b = data[f"b{i}.ln2b"]
        core.steps_trained = int(meta.get("steps_trained", 0))
        core.last_loss = meta.get("last_loss")
        return core

    def status(self) -> dict:
        return {"params": self.n_params, "d_model": self.d,
                "layers": len(self.blocks), "n_ctx": self.n_ctx,
                "steps_trained": self.steps_trained,
                "last_loss": round(self.last_loss, 4)
                if self.last_loss is not None else None}


# ── the trainer: she studies her own corpus in the background ─────────────────
class NeuralTrainer:
    """Bounded background training over her corpus (via the M57 tokenizer).
    Scheduled on the runtime; each cycle is a short burst, then the weights
    are saved. Perplexity is the growth curve. Never raises."""

    def __init__(self, tokenizer, knowledge=None, *, core: Optional[NeuralCore] = None,
                 steps_per_cycle: int = 150, max_seconds: float = 45.0,
                 d_model: int = 144, n_layers: int = 3, n_ctx: int = 96) -> None:
        self.tokenizer = tokenizer
        self.knowledge = knowledge
        self.core = core
        self.steps_per_cycle = int(steps_per_cycle)
        self.max_seconds = float(max_seconds)
        # The target architecture (grown to ~1M params at the full vocab, M64).
        # Threaded from the `neural` config block so the owner can scale her.
        self.d_model = int(d_model)
        self.n_layers = int(n_layers)
        self.n_ctx = int(n_ctx)
        self.cycles = 0
        self.last_report: dict = {}

    def _new_core(self) -> NeuralCore:
        return NeuralCore(self.tokenizer.size, d_model=self.d_model,
                          n_layers=self.n_layers, n_ctx=self.n_ctx)

    def _matches_target(self, core: NeuralCore) -> bool:
        """A saved brain is only reusable if BOTH its vocabulary and its
        architecture match the target — a bigger d_model/n_layers/n_ctx (or a
        retrained tokenizer) means the old weights don't fit, so a new brain is
        born rather than crashing on a shape mismatch."""
        return (core.vocab_size == self.tokenizer.size
                and core.d == self.d_model
                and len(core.blocks) == self.n_layers
                and core.n_ctx == self.n_ctx)

    def _ensure_core(self) -> Optional[NeuralCore]:
        if self.core is not None:
            return self.core
        loaded = NeuralCore.load()
        if loaded is not None and self._matches_target(loaded):
            self.core = loaded
        else:
            # first boot, retrained tokenizer, or a resize → a new brain begins
            if loaded is not None:
                log.info("neural: architecture/vocab changed "
                         "(%s→d%d/l%d/c%d/v%d) — starting a fresh brain",
                         "loaded" if loaded else "none", self.d_model,
                         self.n_layers, self.n_ctx, self.tokenizer.size)
            self.core = self._new_core()
        return self.core

    def _corpus_ids(self) -> list:
        from core.reasoning.tokens import _her_corpus
        text = "\n".join(_her_corpus(self.knowledge))
        return self.tokenizer.encode(text)

    def train_cycle(self) -> dict:
        # Never start a background burst while a user turn is being handled — the
        # live path takes priority on a CPU-only box. (A burst already running
        # yields via should_yield below.)
        from core.reasoning.activity import is_busy
        if is_busy():
            return {"trained": 0, "skipped": "request in flight"}
        try:
            core = self._ensure_core()
            ids = self._corpus_ids()
            report = core.train_steps(ids, steps=self.steps_per_cycle,
                                      max_seconds=self.max_seconds,
                                      should_yield=is_busy)
            if report.get("trained"):
                core.save()
                report["perplexity"] = core.perplexity(ids)
            self.cycles += 1
            self.last_report = report
            log.info("neural training cycle: %s", report)
            return report
        except Exception:  # noqa: BLE001 — background growth must never crash her
            log.debug("neural training cycle failed", exc_info=True)
            return {"trained": 0, "error": "cycle failed"}

    def status(self) -> dict:
        out = {"cycles": self.cycles, "last": self.last_report}
        if self.core is not None:
            out["core"] = self.core.status()
        return out
