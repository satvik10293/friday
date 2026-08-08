"""
core/harness/ — FRIDAY's orchestration harness.

A thin, additive layer ABOVE the existing Intelligence OS. FRIDAY's job is to be
the orchestrator that coordinates stronger models, tools, and agents — this
package is where that coordination becomes reliable and provider-independent:

    · providers.py       — the ModelProvider interface every backend implements
    · reliability.py     — CircuitBreaker, RetryPolicy, timeout, reliable_call
    · registry.py        — ProviderRegistry (capability discovery + routing)
    · task.py            — Task + TaskState lifecycle FSM
    · groq_provider.py   — cloud adapter (unifies the scattered Groq clients)
    · local_provider.py  — local adapter over the Intelligence OS

Nothing here replaces the working intelligence stack; it wraps it so routing,
fallback, and verification operate over one uniform interface.
"""

from .anthropic_provider import AnthropicProvider, anthropic
from .browser_provider import (SITES, BrowserProvider, BrowserSite, ChatDriver,
                               browser_provider)
from .config import (browser_drivers_from_config, build_orchestrator,
                     build_registry, configured_vendors)
from .groq_provider import GroqProvider
from .local_provider import LocalProvider
from .openai_compatible import (OpenAICompatibleProvider, gemini, groq, openai,
                                xai_grok)
from .orchestrator import HarnessOrchestrator, Verdict, Verifier, is_hard
from .providers import (BaseProvider, Capability, GenRequest, GenResult,
                        ModelProvider, ProviderInfo, make_info)
from .reliability import (CircuitBreaker, CircuitOpenError, CircuitState,
                          RetryPolicy, reliable_call)
from .registry import ProviderRegistry
from .task import IllegalTransition, Task, TaskState, TERMINAL_STATES

__all__ = [
    # core
    "BaseProvider", "Capability", "GenRequest", "GenResult", "ModelProvider",
    "ProviderInfo", "make_info",
    "CircuitBreaker", "CircuitOpenError", "CircuitState", "RetryPolicy",
    "reliable_call",
    "ProviderRegistry",
    "IllegalTransition", "Task", "TaskState", "TERMINAL_STATES",
    "HarnessOrchestrator", "Verdict", "Verifier", "is_hard",
    # providers / adapters
    "OpenAICompatibleProvider", "openai", "xai_grok", "gemini", "groq",
    "AnthropicProvider", "anthropic", "GroqProvider", "LocalProvider",
    # browser-seat (plan-only users)
    "BrowserProvider", "BrowserSite", "ChatDriver", "browser_provider", "SITES",
    # wiring
    "build_registry", "build_orchestrator", "configured_vendors",
    "browser_drivers_from_config",
]
