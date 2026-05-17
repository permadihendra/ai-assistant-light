import httpx

from app.config import settings
from app.llm.base import LLMMessage, LLMResponse
from app.llm.providers.openai import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    """OAI-compat with required HTTP-Referer header."""

    name = "openrouter"

    @property
    def _base_url(self) -> str:
        return "https://openrouter.ai/api/v1"

    @property
    def _api_key(self) -> str:
        return settings.openrouter_api_key

    def is_configured(self) -> bool:
        return bool(settings.openrouter_api_key)

    async def chat(
        self,
        messages: list[LLMMessage],
        max_tokens: int,
        timeout: float,
    ) -> LLMResponse:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "HTTP-Referer": "https://github.com/youruser/ai-assistant-light",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.llm_model,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": m.role, "content": m.content} for m in messages
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            provider=self.name,
            model=data["model"],
        )
