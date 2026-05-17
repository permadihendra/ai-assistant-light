import httpx

from app.config import settings
from app.llm.base import LLMProvider, LLMMessage, LLMResponse


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    _API_URL = "https://api.anthropic.com/v1/messages"

    def is_configured(self) -> bool:
        return bool(settings.anthropic_api_key)

    async def chat(
        self,
        messages: list[LLMMessage],
        max_tokens: int,
        timeout: float,
    ) -> LLMResponse:
        system_msgs = [m for m in messages if m.role == "system"]
        chat_msgs = [m for m in messages if m.role != "system"]

        payload: dict = {
            "model": settings.llm_model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": m.role, "content": m.content} for m in chat_msgs
            ],
        }
        if system_msgs:
            payload["system"] = system_msgs[0].content

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                self._API_URL,
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        return LLMResponse(
            text=data["content"][0]["text"],
            provider=self.name,
            model=data["model"],
            input_tokens=data["usage"]["input_tokens"],
            output_tokens=data["usage"]["output_tokens"],
        )
