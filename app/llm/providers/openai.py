import httpx

from app.config import settings
from app.llm.base import LLMProvider, LLMMessage, LLMResponse


class OpenAIProvider(LLMProvider):
    """Base for OpenAI and any OAI-compatible endpoint."""

    name = "openai"

    @property
    def _base_url(self) -> str:
        return settings.openai_base_url

    @property
    def _api_key(self) -> str:
        return settings.openai_api_key

    def is_configured(self) -> bool:
        return bool(self._api_key)

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
            input_tokens=data.get("usage", {}).get("prompt_tokens"),
            output_tokens=data.get("usage", {}).get("completion_tokens"),
        )
