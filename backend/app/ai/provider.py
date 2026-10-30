"""LLM provider abstraction. One provider is configured at a time and there is NO fallback: if it fails,
the case goes to human review (`ai_failed`), it is never sent to another provider.

Implementations: `OpenAICompatibleProvider` (Ollama, vLLM, LM Studio, any OpenAI-compatible API).
Others (e.g. a native Anthropic client) can implement the same protocol later.
"""

from dataclasses import dataclass
from typing import Protocol


class LLMError(Exception):
    code = "llm_error"
    retryable = False


class LLMUnavailable(LLMError):
    """Timeout, connection error, 429 or 5xx: may be retried (same provider only)."""

    code = "llm_unavailable"
    retryable = True


class LLMInvalidOutput(LLMError):
    """Not JSON, wrong shape, tool call, truncated answer: never retried, never trusted."""

    code = "llm_invalid_output"


class LLMRefused(LLMError):
    """4xx other than 429 (bad request, authentication, unknown model)."""

    code = "llm_refused"


class LLMNotAllowed(LLMError):
    """The endpoint is not on a private network and no explicit decision allows an external provider."""

    code = "provider_not_allowed"


@dataclass(frozen=True)
class LLMResult:
    content: str  # raw JSON text, validated by the caller
    latency_ms: int
    tokens_in: int | None = None
    tokens_out: int | None = None


class LLMProvider(Protocol):
    name: str
    model: str
    is_local: bool

    def complete_json(self, system: str, user: str, schema: dict, *, max_tokens: int) -> LLMResult:
        """One structured completion. No tools are ever declared."""
        ...
