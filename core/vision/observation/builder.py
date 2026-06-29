"""
core/vision/observation/builder.py — FRIDAY 6.1 (M14)
The Observation Builder. It converts a `ProcessingResult` (raw processor outputs for one
frame) into standardized `core.perception.Observation` objects — the SAME Observation
type the rest of FRIDAY already ingests (M6). This is the hard boundary the architecture
demands: vision processors produce detections; ONLY the builder turns them into
Observations, and no processor ever writes to the World Model.

Each Observation carries the mandated fields: source · entity candidates · confidence ·
timestamp · spatial information · visual evidence · processing metadata. Two kinds are
produced:

  • per persistent object  — one Observation per tracked object (subject keyed on the
    track id so the same object dedups/merges across frames).
  • a frame scene summary   — one low-significance Observation describing the whole frame
    (motion, brightness, object count, scene signature) for Visual Memory + metrics.

The builder reasons about nothing; it shapes evidence.
"""

from __future__ import annotations

from typing import Optional

from core.perception.models import (Observation, ObservationConfidence, ObservationSource,
                                    ObservationType, new_observation)

from ..processing.base import Detection, ProcessingResult
from ..transport.frame import Frame

# detection kinds that name a real-world entity (others are evidence only)
_ENTITY_KINDS = {"object", "person", "face"}
# friendly names for model-free proposals
_LABEL_NAMES = {"motion_region": "moving object"}


class ObservationBuilder:
    def __init__(self, config=None) -> None:
        self._source_name = getattr(config, "source_name", "vision")
        self._base_conf = float(getattr(config, "base_confidence", 0.6))
        self._emit_per_detection = bool(getattr(config, "emit_per_detection", True))
        self._min_significance = float(getattr(config, "min_significance", 0.0))
        self._built = 0

    # ── public ───────────────────────────────────────────────────────────────────
    def build(self, result: ProcessingResult, frame: Optional[Frame] = None) -> list:
        """Return the list of Observations for one processed frame (object observations
        first, then the frame summary)."""
        observations: list = []
        evidence = self._evidence(result, frame)

        if self._emit_per_detection:
            seen_tracks: set = set()
            for det in result.detections():
                if det.kind not in _ENTITY_KINDS or det.label == "segment":
                    continue
                key = det.track_id or f"{det.label}:{id(det)}"
                if det.track_id and det.track_id in seen_tracks:
                    continue
                seen_tracks.add(key)
                obs = self._object_observation(result, det, evidence)
                if obs is not None:
                    observations.append(obs)

        summary = self._summary_observation(result, evidence)
        if summary is not None:
            observations.append(summary)
        self._built += len(observations)
        return observations

    # ── object observation ───────────────────────────────────────────────────────
    def _object_observation(self, result: ProcessingResult, det: Detection,
                            evidence: dict) -> Optional[Observation]:
        kind = "person" if det.kind in ("person", "face") else "object"
        name = _LABEL_NAMES.get(det.label, det.label)
        confidence = ObservationConfidence.clamp(
            0.5 * self._base_conf + 0.5 * float(det.confidence))
        spatial = self._spatial(det, result.width, result.height)
        candidates = [{"kind": kind, "name": name,
                       "confidence": round(float(det.confidence), 4)}]
        if det.attributes.get("identity"):
            candidates.insert(0, {"kind": "person", "name": det.attributes["identity"],
                                  "confidence": float(det.attributes.get("identity_score", 0.6))})
        payload = {
            "name": name,
            "label": det.label,
            "track_id": det.track_id,
            "entity_candidates": candidates,
            "spatial": spatial,
            "visual_evidence": evidence,
            "processing": {"processor": det.processor, "attributes": det.attributes},
        }
        subject = f"vision:obj:{result.camera_id}:{det.track_id or det.label}"
        metadata = {
            "subject": subject,
            "entity_kind": kind,
            "entity_name": name,
            "camera_id": result.camera_id,
            "track_id": det.track_id,
            "impact": self._impact(result),
            "frame_id": result.frame_id,
        }
        return new_observation(
            ObservationType.VISION,
            ObservationSource(self._source_name, kind="camera"),
            payload=payload, confidence=confidence, metadata=metadata,
            timestamp=result.timestamp)

    # ── frame summary observation ────────────────────────────────────────────────
    def _summary_observation(self, result: ProcessingResult, evidence: dict) -> Optional[Observation]:
        motion = result.data_for("motion")
        scene = result.data_for("scene_stats")
        dets = result.detections()
        objects = [d for d in dets if d.kind in _ENTITY_KINDS and d.label != "segment"]
        labels = sorted({_LABEL_NAMES.get(d.label, d.label) for d in objects})
        payload = {
            "name": f"scene@{result.camera_id}",
            "object_count": len(objects),
            "labels": labels,
            "motion": bool(motion.get("motion", False)),
            "motion_score": motion.get("motion_score", 0.0),
            "brightness": scene.get("brightness"),
            "scene_signature": scene.get("signature"),
            "visual_evidence": evidence,
            "processing": {"processors": [r.processor for r in result.results],
                           "total_ms": round(result.total_ms, 3)},
        }
        confidence = ObservationConfidence.clamp(self._base_conf)
        metadata = {
            "subject": f"vision:scene:{result.camera_id}",
            "entity_kind": "scene",
            "entity_name": f"scene:{result.camera_id}",
            "camera_id": result.camera_id,
            "impact": self._impact(result),
            "frame_id": result.frame_id,
            "summary": True,
        }
        return new_observation(
            ObservationType.VISION,
            ObservationSource(self._source_name, kind="camera"),
            payload=payload, confidence=confidence, metadata=metadata,
            timestamp=result.timestamp)

    # ── helpers ──────────────────────────────────────────────────────────────────
    @staticmethod
    def _spatial(det: Detection, width: int, height: int) -> dict:
        if det.bbox is None:
            return {}
        nx, ny, nw, nh = det.bbox.normalized(width, height)
        cx, cy = det.bbox.center
        return {
            "bbox": det.bbox.to_dict(),
            "bbox_norm": {"x": round(nx, 4), "y": round(ny, 4),
                          "w": round(nw, 4), "h": round(nh, 4)},
            "center_norm": {"x": round(cx / width, 4) if width else 0.0,
                            "y": round(cy / height, 4) if height else 0.0},
            "area_fraction": round(nw * nh, 5),
        }

    @staticmethod
    def _evidence(result: ProcessingResult, frame: Optional[Frame]) -> dict:
        ev = {"frame_id": result.frame_id, "camera_id": result.camera_id,
              "frame_number": result.frame_number,
              "resolution": [result.width, result.height]}
        if frame is not None:
            ev["checksum"] = frame.checksum
            ev["latency_ms"] = frame.latency_ms
            ev["pixel_format"] = frame.pixel_format
        return ev

    @staticmethod
    def _impact(result: ProcessingResult) -> float:
        """Frames with motion or detected objects are more impactful."""
        motion = result.data_for("motion")
        objects = sum(1 for d in result.detections()
                      if d.kind in _ENTITY_KINDS and d.label != "segment")
        impact = 0.3
        if motion.get("motion"):
            impact += 0.3
        if objects:
            impact += min(0.4, 0.1 * objects)
        return ObservationConfidence.clamp(impact)

    def metrics(self) -> dict:
        return {"observations_built": self._built}
