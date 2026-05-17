from app.config import settings
from app.llm.base import LLMMessage, LLMProvider
from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.opencode import OpenCodeProvider
from app.llm.providers.openai import OpenAIProvider
from app.llm.providers.openrouter import OpenRouterProvider

_REGISTRY: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "openrouter": OpenRouterProvider,
    "gemini": GeminiProvider,
    "opencode": OpenCodeProvider,
    "zen": OpenCodeProvider,  # Zen is OAI-compat; reuse the same class
}


def get_provider() -> LLMProvider:
    cls = _REGISTRY.get(settings.llm_provider)
    if cls is None:
        raise RuntimeError(f"Unknown LLM provider: {settings.llm_provider}")
    provider = cls()
    if not provider.is_configured():
        raise RuntimeError(
            f"Provider '{settings.llm_provider}' is selected but its API key/URL is not set. "
            f"Check your .env file."
        )
    return provider


async def chat(messages: list[dict], system: str | None = None) -> str:
    """Convenience wrapper used by all plugins."""
    msgs = [LLMMessage(**m) for m in messages]
    if system:
        msgs = [LLMMessage(role="system", content=system)] + msgs
    result = await get_provider().chat(
        msgs,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout,
    )
    return result.text
