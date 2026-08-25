"""
core/comprehension/ — FRIDAY reads and understands a codebase (M64).

Point her at a project folder and she goes into the code: languages, entry
points, dependencies/frameworks, tests, structure, and (for Python) a symbol
index — distilled into an understanding she can explain and help you with. The
understanding is recorded in the World Model and core memory so she remembers
the project across sessions.
"""

from .project import (
    ProjectUnderstanding,
    analyze_project,
    understand_project,
    find_symbol,
)

__all__ = [
    "ProjectUnderstanding",
    "analyze_project",
    "understand_project",
    "find_symbol",
]
