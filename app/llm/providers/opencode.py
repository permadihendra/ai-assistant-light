from app.config import settings
from app.llm.providers.openai import OpenAIProvider


class OpenCodeProvider(OpenAIProvider):
    """
    OpenCode-Go and Zen both speak the OpenAI-compatible API.
    Switch between them with LLM_PROVIDER=opencode or LLM_PROVIDER=zen.
    """

    name = "opencode"

    @property
    def _base_url(self) -> str:
        if settings.llm_provider == "zen":
            return settings.zen_base_url
        return settings.opencode_base_url

    @property
    def _api_key(self) -> str:
        key = (
            settings.zen_api_key
            if settings.llm_provider == "zen"
            else settings.opencode_api_key
        )
        return key or "no-key"  # some self-hosted instances need no auth

    def is_configured(self) -> bool:
        return bool(self._base_url)  # URL is enough; key is optional
