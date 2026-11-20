from typing import Protocol


class EmbeddingProviderError(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    @property
    def provider_name(self) -> str: ...
    @property
    def model_name(self) -> str: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
