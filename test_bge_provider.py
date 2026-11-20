
import asyncio

from app.modules.ai.embeddings.factory import get_embedding_provider


async def main():
    provider = get_embedding_provider()

    print("PROVIDER:", provider.provider_name)
    print("MODEL:", provider.model_name)

    available = await provider.is_available()
    print("OLLAMA AVAILABLE:", available)

    if not available:
        raise RuntimeError("Ollama is not available")

    texts = [
        "What are the common symptoms of diabetes?",
        "ডায়াবেটিসের সাধারণ লক্ষণগুলো কী কী?",
    ]

    vectors = await provider.embed(texts)

    assert len(vectors) == len(texts)
    assert all(len(vector) == 1024 for vector in vectors)

    for index, vector in enumerate(vectors):
        print(f"TEXT {index + 1}: {texts[index]}")
        print("DIMENSIONS:", len(vector))
        print("VALID:", True)

    print("PROVIDER TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())
