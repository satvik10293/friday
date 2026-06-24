"""
core/cognition — FRIDAY 4.0 (M5) Cognitive Loop.

FRIDAY's thinking cycle: Observe → Context → World → Attention → Reason → Plan →
Select → Execute → Reflect → Learn, driven through the Executive Brain and
scheduled on the Runtime (never an infinite loop). Import is side-effect free.

    from core.cognition import CognitiveLoop
    loop = CognitiveLoop(brain, runtime=rt, goal_service=goals, memory_service=mem)
    loop.run_cycle()      # one pass
    loop.start()          # schedule periodic cycles
    loop.stop()
"""

from .loop import CognitionEvent, CognitiveLoop, CognitivePhase, CycleResult

__all__ = ["CognitionEvent", "CognitiveLoop", "CognitivePhase", "CycleResult"]
