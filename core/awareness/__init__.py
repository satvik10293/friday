"""
core/awareness/ — FRIDAY's situational awareness + self-explanation (M64).

Two honest faculties:

  · describe_situation() — "what's going on right now": fuses what she perceives
    (vision/audio/space via the perception hub), what she knows (World Model:
    people, devices, the project she's in), what she's working on (active goals),
    and what she just did (the decision log) into one plain-language brief.

  · explain_last_decision() — "why did you do that": reads the last entry in the
    decision log and says, in plain words, HOW she answered (her own notes, her
    own reasoning, or the cloud) and how sure she was.

Both are best-effort and never raise: a missing subsystem is simply left out of
the picture rather than crashing the turn.
"""

from .situation import Situation, describe_situation, explain_last_decision, gather

__all__ = ["Situation", "describe_situation", "explain_last_decision", "gather"]
