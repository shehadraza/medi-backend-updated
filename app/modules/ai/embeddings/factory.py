from app.core.config import settings
from app.modules.ai.embeddings.base import EmbeddingProviderError
from app.modules.ai.embeddings.ollama import OllamaEmbeddingProvider


def get_embedding_provider():
    if settings.AI_EMBEDDING_PROVIDER.lower() == "ollama":
        return OllamaEmbeddingProvider()
    raise EmbeddingProviderError("Configured embedding provider is unsupported.")
