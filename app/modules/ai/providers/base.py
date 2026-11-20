from dataclasses import dataclass
from typing import AsyncIterator, Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    done: bool = True


class LLMProviderError(RuntimeError):
    """Sanitized provider failure suitable for safe handling by services."""


class LLMProvider(Protocol):
    async def is_available(self) -> bool: ...
    async def generate(self, messages: list[ChatMessage], *, temperature: float = 0.2, max_tokens: int | None = None) -> LLMResponse: ...
    def stream(self, messages: list[ChatMessage], *, temperature: float = 0.2, max_tokens: int | None = None) -> AsyncIterator[str]: ...
