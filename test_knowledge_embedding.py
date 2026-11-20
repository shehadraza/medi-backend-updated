import asyncio
from app.modules.ai.embeddings.factory import get_embedding_provider

async def main():
    provider = get_embedding_provider()

    texts = [
        "What are the common symptoms of diabetes?",
        "ডায়াবেটিসের সাধারণ লক্ষণগুলো কী কী?",
    ]

    vectors = await provider.embed(texts)

    print("PROVIDER:", provider.provider_name)
    print("MODEL:", provider.model_name)
    print("TEXT COUNT:", len(vectors))
    print("DIMENSIONS:", [len(v) for v in vectors])
    print("FINITE:", all(
        all(__import__("math").isfinite(x) for x in v)
        for v in vectors
    ))
    print("EMBEDDING TEST PASSED")

asyncio.run(main())