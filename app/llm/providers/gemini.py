import httpx

from app.config import settings
from app.llm.base import LLMProvider, LLMMessage, LLMResponse


class GeminiProvider(LLMProvider):
    """Gemini generateContent REST API — no SDK."""

    name = "gemini"
    _API_URL = (
        "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    )

    def is_configured(self) -> bool:
        return bool(settings.gemini_api_key)

    async def chat(
        self,
        messages: list[LLMMessage],
        max_tokens: int,
        timeout: float,
    ) -> LLMResponse:
        system_text = next((m.content for m in messages if m.role == "system"), None)
        contents = [
            {
                "role": "user" if m.role == "user" else "model",
                "parts": [{"text": m.content}],
            }
            for m in messages
            if m.role != "system"
        ]
        payload: dict = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}

        url = self._API_URL.format(model=settings.llm_model)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url, params={"key": settings.gemini_api_key}, json=payload
            )
            resp.raise_for_status()
            data = resp.json()

        text = data["candidates"][0]["content"]["parts"][0]["text"]

        usage = data.get("usageMetadata", {}) or {}
        return LLMResponse(
            text=text,
            provider=self.name,
            model=settings.llm_model,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
        )
