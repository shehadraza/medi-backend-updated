import json
from collections.abc import AsyncIterator

import httpx

from app.core.config import settings
from app.modules.ai.providers.base import ChatMessage, LLMProviderError, LLMResponse


class OllamaProvider:
    """Optional Ollama HTTP provider; it never assumes the daemon is installed."""

    def __init__(self, base_url: str | None = None, model: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.AI_CHAT_MODEL
        self.timeout = timeout or settings.AI_PROVIDER_TIMEOUT_SECONDS

    async def is_available(self) -> bool:
        if not self.model:
            return False
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.is_success
        except (httpx.HTTPError, ValueError):
            return False

    def _payload(self, messages: list[ChatMessage], temperature: float, max_tokens: int | None) -> dict:
        if not self.model:
            raise LLMProviderError("Language model is not configured.")
        if not messages or any(m.role not in {"system", "user", "assistant"} for m in messages):
            raise LLMProviderError("Invalid model request.")
        token_limit = settings.AI_MAX_OUTPUT_TOKENS if max_tokens is None else max_tokens
        if not 1 <= token_limit <= 8192:
            raise LLMProviderError("Invalid response token limit.")
        return {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": token_limit},
        }

    async def generate(self, messages: list[ChatMessage], *, temperature: float = 0.2, max_tokens: int | None = None) -> LLMResponse:
        payload = self._payload(messages, temperature, max_tokens)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
            content = data.get("message", {}).get("content")
            model = data.get("model")
            if not isinstance(content, str) or not content.strip() or not isinstance(model, str):
                raise LLMProviderError("Language model returned an invalid response.")
            return LLMResponse(content=content.strip(), model=model, done=bool(data.get("done", True)))
        except LLMProviderError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise LLMProviderError("Language model is unavailable.") from exc

    async def stream(self, messages: list[ChatMessage], *, temperature: float = 0.2, max_tokens: int | None = None) -> AsyncIterator[str]:
        payload = self._payload(messages, temperature, max_tokens)
        payload["stream"] = True
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        item = json.loads(line)
                        piece = item.get("message", {}).get("content", "")
                        if piece:
                            yield piece
                        if item.get("done"):
                            break
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise LLMProviderError("Language model stream is unavailable.") from exc
