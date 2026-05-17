from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMProvider(ABC):
    name: str  # snake_case, matches LLM_PROVIDER env value

    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        max_tokens: int,
        timeout: float,
    ) -> LLMResponse: ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if the required credentials are present in settings."""
        ...
