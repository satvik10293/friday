"""
core/intelligence/plugins/flan_t5.py — FRIDAY 4.0 (M12)
Optional local LLM plugin: Google flan-t5 via HuggingFace transformers. Loaded only
when transformers is installed (the loader guards this). The model is loaded lazily
on first inference, so importing this module is cheap. This is the bridge to the
existing 3.0 local reasoning reader, now behind the M12 Model protocol.
"""

from __future__ import annotations

import logging

from ..base import BaseModel, InferenceRequest, ModelInfo, TaskType

log = logging.getLogger("friday.intelligence.plugins.flan_t5")


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

    def load(self) -> None:
        super().load()  # mark loaded; the heavy model loads lazily on first infer

    def _get(self):
        if self._pipe is None:
            from transformers import pipeline
            from core.intelligence.device import preferred_device
            device = preferred_device("local_models")   # wizard's device plan (M35)
            log.info("loading flan-t5 pipeline %s on %s", self._model_id, device)
            self._pipe = pipeline("text2text-generation", model=self._model_id,
                                  device=device)
        return self._pipe

    def _run(self, request: InferenceRequest):
        prompt = request.prompt[: self.info.context_length]
        out = self._get()(prompt, max_new_tokens=min(256, request.max_tokens))
        text = out[0]["generated_text"] if out else ""
        return (text, {"model_id": self._model_id}, 0.7 if text else 0.2)
