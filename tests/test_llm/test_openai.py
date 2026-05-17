import pytest
import respx
from httpx import Response

from app.llm.base import LLMMessage, LLMResponse
from app.llm.providers.openai import OpenAIProvider


@pytest.mark.asyncio
async def test_openai_provider_chat():
    """Test OpenAI provider with a mocked HTTP call."""
    provider = OpenAIProvider()

    with respx.mock:
        route = respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=Response(
                200,
                json={
                    "choices": [{"message": {"content": "Hello!"}}],
                    "model": "gpt-4o-mini",
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )
        )

        messages = [LLMMessage(role="user", content="Say hello")]
        response = await provider.chat(messages, max_tokens=100, timeout=10.0)

        assert response.text == "Hello!"
        assert response.provider == "openai"
        assert route.called


@pytest.mark.asyncio
async def test_openai_provider_not_configured():
    """Provider should not crash if key is missing — is_configured handles it."""
    provider = OpenAIProvider()
    # is_configured will return False if no key is set
    assert isinstance(provider.is_configured(), bool)
