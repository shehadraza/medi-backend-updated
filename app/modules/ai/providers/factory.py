from app.core.config import settings
from app.modules.ai.providers.base import LLMProviderError
from app.modules.ai.providers.ollama import OllamaProvider


def get_llm_provider():
    if settings.AI_LLM_PROVIDER.lower() == "ollama":
        return OllamaProvider()
    raise LLMProviderError("Configured language model provider is unsupported.")
