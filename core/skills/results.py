"""
core/skills/results.py — FRIDAY 4.0
Standardized skill results. Every execution returns a Result (Success or Failure)
— never a bare value or exception — so callers and the audit trail are uniform.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Result:
    success: bool
    data: Any = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "error_type": self.error_type,
            "metadata": self.metadata,
            "duration_ms": self.duration_ms,
        }


class SuccessResult(Result):
    def __init__(self, data: Any = None, duration_ms: float = 0.0,
                 metadata: Optional[dict] = None) -> None:
        super().__init__(True, data=data, error=None, error_type=None,
                         metadata=metadata or {}, duration_ms=duration_ms)


class FailureResult(Result):
    def __init__(self, error: str, error_type: Optional[str] = None,
                 duration_ms: float = 0.0, metadata: Optional[dict] = None) -> None:
        super().__init__(False, data=None, error=error, error_type=error_type,
                         metadata=metadata or {}, duration_ms=duration_ms)
