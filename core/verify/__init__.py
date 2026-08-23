"""core/verify/ — the Verify gate, extracted from friday-v0's OPVER loop.

One gate, one result contract: `Verifier().verify(...)` rules a `VerifyResult`
(success true/false + tier + detail) on a produced result, strongest check
first. See gate.py for the tier design. Pure-stdlib and never-raises."""

from .gate import Verifier, VerifyResult

__all__ = ["Verifier", "VerifyResult"]
