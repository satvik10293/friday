"""
Her own weights (M58): a neural core born on her machine.

Pure-numpy GPT-style decoder over her M57 vocabulary, trained from her own
corpus in bounded background cycles. These tests pin the honest properties:
it LEARNS (loss measurably drops), it persists (her brain survives restarts),
training is bounded (a cycle can't run away with the CPU), a changed
vocabulary births a new brain, and the growth metric (perplexity) is real.
"""

from __future__ import annotations

import numpy as np

from core.reasoning.neural import NeuralCore, NeuralTrainer
from core.reasoning.tokens import FridayTokenizer

_TOY = (list(range(10, 26)) * 120)      # a learnable repeating language


def _tiny():
    return NeuralCore(vocab_size=48, d_model=32, n_layers=1, n_ctx=16, seed=5)


# ── it learns (the non-negotiable) ────────────────────────────────────────────

def test_loss_drops_on_a_learnable_pattern():
    core = _tiny()
    r = core.train_steps(_TOY, steps=60, batch=6, lr=3e-3, max_seconds=30, seed=1)
    assert r["trained"] == 60
    assert r["loss"] < r["loss_start"] * 0.6        # real learning, not noise
    assert core.steps_trained == 60


def test_perplexity_reflects_learning():
    core = _tiny()
    before = core.perplexity(_TOY)
    core.train_steps(_TOY, steps=80, batch=6, lr=3e-3, max_seconds=30, seed=1)
    after = core.perplexity(_TOY)
    assert after < before                            # the growth curve is real


def test_generate_returns_token_ids_in_vocab():
    core = _tiny()
    core.train_steps(_TOY, steps=40, batch=6, lr=3e-3, max_seconds=30, seed=1)
    out = core.generate(_TOY[:8], max_new=12)
    assert len(out) == 8 + 12
    assert all(0 <= i < core.vocab_size for i in out)


# ── boundedness: a background cycle can't run away ────────────────────────────

def test_training_burst_respects_the_time_budget():
    core = _tiny()
    r = core.train_steps(_TOY, steps=100000, batch=6, lr=1e-3,
                         max_seconds=1.0, seed=1)
    assert 0 < r["trained"] < 100000                 # the clock stopped it
    assert r["seconds"] <= 3.0


def test_tiny_corpus_is_refused_not_crashed():
    core = _tiny()
    r = core.train_steps(list(range(10)), steps=10)
    assert r["trained"] == 0 and "small" in r["reason"]


# ── persistence: her brain survives restarts ──────────────────────────────────

def test_save_and_load_round_trip(tmp_path):
    core = _tiny()
    core.train_steps(_TOY, steps=30, batch=6, lr=3e-3, max_seconds=30, seed=1)
    w, m = tmp_path / "brain.npz", tmp_path / "brain.json"
    core.save(w, meta_path=m)
    loaded = NeuralCore.load(w, meta_path=m)
    assert loaded is not None
    assert loaded.steps_trained == core.steps_trained
    assert np.allclose(loaded.wte, core.wte)
    # the loaded brain thinks identically
    a = core.perplexity(_TOY)
    b = loaded.perplexity(_TOY)
    assert abs(a - b) < 1e-3


# ── the trainer: her corpus, her tokenizer, bounded cycles ────────────────────

class _Knowledge:
    class _Store:
        def all_entries(self):
            class _E:
                title = "photosynthesis"
                content = ("photosynthesis converts sunlight into sugar. "
                           "the plant uses chlorophyll to capture light. " * 40)
            return [_E()]
    store = _Store()


def test_trainer_cycle_trains_and_reports(tmp_path, monkeypatch):
    import core.reasoning.neural as neural_mod
    monkeypatch.setattr(neural_mod, "_WEIGHTS_PATH", tmp_path / "b.npz")
    monkeypatch.setattr(neural_mod, "_META_PATH", tmp_path / "b.json")
    tok = FridayTokenizer.train(
        ["photosynthesis converts sunlight into sugar for the plant"] * 4,
        vocab_size=200)
    trainer = NeuralTrainer(tok, _Knowledge(),
                            core=NeuralCore(tok.size, d_model=32, n_layers=1,
                                            n_ctx=16),
                            steps_per_cycle=25, max_seconds=20.0)
    report = trainer.train_cycle()
    assert report["trained"] > 0
    assert report.get("perplexity") is not None
    assert (tmp_path / "b.npz").exists()             # her brain persisted
    assert trainer.status()["core"]["steps_trained"] > 0


def test_vocab_change_births_a_new_brain(tmp_path, monkeypatch):
    import core.reasoning.neural as neural_mod
    monkeypatch.setattr(neural_mod, "_WEIGHTS_PATH", tmp_path / "b.npz")
    monkeypatch.setattr(neural_mod, "_META_PATH", tmp_path / "b.json")
    tok = FridayTokenizer.train(["sunlight into sugar"] * 3, vocab_size=150)
    old = NeuralCore(vocab_size=tok.size + 7, d_model=32, n_layers=1, n_ctx=16)
    old.save(tmp_path / "b.npz", meta_path=tmp_path / "b.json")
    trainer = NeuralTrainer(tok, None)
    core = trainer._ensure_core()
    assert core.vocab_size == tok.size               # reborn to fit her vocab


def test_trainer_never_raises_without_material():
    tok = FridayTokenizer.train(["tiny"], vocab_size=120)
    trainer = NeuralTrainer(tok, None,
                            core=NeuralCore(tok.size, d_model=32, n_layers=1,
                                            n_ctx=16))
    report = trainer.train_cycle()                   # corpus falls back / tiny
    assert isinstance(report, dict)                  # quiet, never an exception
