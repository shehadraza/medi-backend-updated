
import math

import httpx

from app.core.config import settings
from app.modules.ai.embeddings.base import EmbeddingProviderError


class OllamaEmbeddingProvider:
    EXPECTED_DIMENSIONS = {
        "bge-m3": 1024,
    }

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = settings.AI_EMBEDDING_MODEL if model is None else model
        self.timeout = timeout or settings.AI_PROVIDER_TIMEOUT_SECONDS

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self.model

    def _validate_vector(self, vector: object) -> list[float]:
        if not isinstance(vector, list) or not vector:
            raise EmbeddingProviderError(
                "Embedding provider returned an invalid vector."
            )

        if not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for value in vector
        ):
            raise EmbeddingProviderError(
                "Embedding provider returned invalid numeric values."
            )

        expected = self.EXPECTED_DIMENSIONS.get(
            self.model.split(":")[0].lower()
        )

        if expected is not None and len(vector) != expected:
            raise EmbeddingProviderError(
                "Embedding provider returned an unexpected vector dimension."
            )

        return [float(value) for value in vector]

    async def is_available(self) -> bool:
        if not self.model:
            return False

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/tags"
                )
                return response.is_success

        except (httpx.HTTPError, ValueError):
            return False

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.model:
            raise EmbeddingProviderError(
                "Embedding model is not configured."
            )

        if not texts:
            return []

        if not all(isinstance(text, str) and text.strip() for text in texts):
            raise EmbeddingProviderError(
                "Embedding input contains invalid text."
            )

        vectors: list[list[float]] = []
        expected_dimension: int | None = None

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for text in texts:
                    response = await client.post(
                        f"{self.base_url}/api/embed",
                        json={
                            "model": self.model,
                            "input": text,
                        },
                    )
                    response.raise_for_status()

                    data = response.json()

                    if not isinstance(data, dict):
                        raise EmbeddingProviderError(
                            "Embedding provider returned invalid data."
                        )

                    embeddings = data.get("embeddings")

                    if not isinstance(embeddings, list) or not embeddings:
                        raise EmbeddingProviderError(
                            "Embedding provider returned no vectors."
                        )

                    vector = self._validate_vector(embeddings[0])

                    if expected_dimension is None:
                        expected_dimension = len(vector)
                    elif len(vector) != expected_dimension:
                        raise EmbeddingProviderError(
                            "Embedding dimensions are inconsistent."
                        )

                    vectors.append(vector)

            return vectors

        except EmbeddingProviderError:
            raise

        except (
            httpx.HTTPError,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
        ) as exc:
            raise EmbeddingProviderError(
                "Embedding provider is unavailable."
            ) from exc
