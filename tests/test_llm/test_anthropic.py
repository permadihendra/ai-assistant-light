import pytest
import respx
from httpx import Response

from app.llm.providers.anthropic import AnthropicProvider
from app.llm.base import LLMMessage


@pytest.mark.asyncio
async def test_anthropic_provider_chat():
    """Test Anthropic provider with a mocked HTTP call."""
    provider = AnthropicProvider()

    with respx.mock:
        route = respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=Response(
                200,
                json={
                    "content": [{"text": "Hello from Claude!"}],
                    "model": "claude-3-5-haiku-20241022",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            )
        )

        messages = [LLMMessage(role="user", content="Say hello")]
        response = await provider.chat(messages, max_tokens=100, timeout=10.0)

        assert response.text == "Hello from Claude!"
        assert response.provider == "anthropic"
        assert response.input_tokens == 10
        assert response.output_tokens == 5
        assert route.called
