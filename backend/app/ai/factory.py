from app.ai.openai_compat import OpenAICompatibleProvider
from app.ai.provider import LLMProvider
from app.core.config import Settings


def build_llm_provider(s: Settings) -> LLMProvider | None:
    """The single configured provider (or none). There is deliberately no list and no fallback."""
    if s.ai_provider == "openai_compatible":
        return OpenAICompatibleProvider(
            base_url=s.ai_base_url,
            model=s.ai_model,
            api_key=s.ai_api_key.get_secret_value() if s.ai_api_key else None,
            timeout=s.ai_timeout_seconds,
            allow_external=s.ai_allow_external,
            json_mode=s.ai_json_mode,
        )
    return None
