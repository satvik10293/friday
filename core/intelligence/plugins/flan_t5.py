"""
core/intelligence/plugins/flan_t5.py — FRIDAY 4.0 (M12)
Optional local LLM plugin: Google flan-t5 via HuggingFace transformers. Loaded only
when transformers is installed (the loader guards this). This is the bridge to the
existing 3.0 local reasoning reader, now behind the M12 Model protocol — and like
that reader, it answers by READING the retrieved evidence (memories + knowledge
stitched into the prompt), not by free-generating from its own small weights.

Honesty rules:
  * with evidence in context → extractive QA, confidence 0.75
  * without evidence → whatever flan-t5-base makes up is a guess; confidence 0.4,
    LOW ENOUGH that the escalation path (deep pass → teacher) still fires
  * the heavy pipeline warms on a background thread at load() so the first user
    turn never eats the multi-second model load
"""

from __future__ import annotations

import logging
import threading

from ..base import BaseModel, InferenceRequest, ModelInfo, TaskType

log = logging.getLogger("friday.intelligence.plugins.flan_t5")

_EVIDENCE_BUDGET_CHARS = 1200


def _evidence(request: InferenceRequest) -> str:
    """Stitch the context builder's retrieved memories + knowledge into one
    evidence block (highest-signal first, char-budgeted)."""
    parts: list[str] = []
    for m in request.context.get("memories", []) or []:
        text = (m.get("content") if isinstance(m, dict) else str(m)) or ""
        if text.strip():
            parts.append(text.strip())
    for e in request.context.get("knowledge", []) or []:
        text = (e.get("content") if isinstance(e, dict) else str(e)) or ""
        if text.strip():
            parts.append(text.strip())
    block = " ".join(parts)
    return block[:_EVIDENCE_BUDGET_CHARS]


class FlanT5Model(BaseModel):
    def __init__(self, model_id: str = "google/flan-t5-base") -> None:
        super().__init__(ModelInfo(
            name="flan-t5", version="base", author="google",
            capabilities={TaskType.GENERAL.value, TaskType.WRITING.value,
                          TaskType.RESEARCH.value, TaskType.SCIENTIFIC.value},
            context_length=512, ram_mb=900.0, avg_speed_ms=400.0, avg_accuracy=0.7,
            is_local=True))
        self._model_id = model_id
        self._pipe = None
        self._pipe_lock = threading.Lock()

    def load(self) -> None:
        super().load()          # mark loaded immediately (registry visibility)
        # warm the heavy pipeline OFF the request path: the first user turn
        # must never pay the multi-second model load
        threading.Thread(target=self._warm, name="flan-t5-warm",
                         daemon=True).start()

    def _warm(self) -> None:
        try:
            self._get()
        except Exception:  # noqa: BLE001 — first infer will retry and report
            log.debug("flan-t5 warm-up failed", exc_info=True)

    def _get(self):
        with self._pipe_lock:
            if self._pipe is None:
                from transformers import pipeline
                from core.intelligence.device import preferred_device
                device = preferred_device("local_models")   # wizard's device plan (M35)
                log.info("loading flan-t5 pipeline %s on %s", self._model_id, device)
                self._pipe = pipeline("text2text-generation", model=self._model_id,
                                      device=device)
            return self._pipe

    def _run(self, request: InferenceRequest):
        evidence = _evidence(request)
        if evidence:
            # extractive QA over what FRIDAY actually knows — the 3.0 local
            # reader design. flan-t5 is strong at this shape.
            prompt = (f"Answer the question using the context.\n"
                      f"context: {evidence}\nquestion: {request.prompt}")
        else:
            prompt = request.prompt
        prompt = prompt[: max(self.info.context_length * 4, 512)]
        out = self._get()(prompt, max_new_tokens=min(256, request.max_tokens))
        text = (out[0]["generated_text"] if out else "").strip()
        if not text:
            return ("", {"model_id": self._model_id, "grounded": bool(evidence)}, 0.2)
        # evidence-grounded answers are trustworthy; free generation from a
        # base-size model is a guess and must stay below the escalation
        # threshold so the deep pass / teacher can overrule it
        confidence = 0.75 if evidence else 0.4
        return (text, {"model_id": self._model_id,
                       "grounded": bool(evidence)}, confidence)
