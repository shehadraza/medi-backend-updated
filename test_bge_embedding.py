
import asyncio
import math
import httpx

MODEL = "bge-m3:latest"
URL = "http://localhost:11434/api/embed"

TEXTS = [
    "What are the common symptoms of diabetes?",
    "ডায়াবেটিসের সাধারণ লক্ষণগুলো কী কী?",
    "What is hypertension and how is it managed?",
    "উচ্চ রক্তচাপ কী এবং এটি কীভাবে নিয়ন্ত্রণ করা হয়?",
]


async def main():
    async with httpx.AsyncClient(timeout=120) as client:
        for text in TEXTS:
            response = await client.post(
                URL,
                json={"model": MODEL, "input": text},
            )
            response.raise_for_status()

            data = response.json()
            embeddings = data.get("embeddings", [])

            if not embeddings:
                raise RuntimeError("No embedding returned")

            vector = embeddings[0]

            if not vector or not all(
                isinstance(x, (int, float)) and math.isfinite(x)
                for x in vector
            ):
                raise RuntimeError("Invalid embedding vector")

            print("TEXT:", text)
            print("DIMENSIONS:", len(vector))
            print("VALID:", True)
            print("-" * 45)


if __name__ == "__main__":
    asyncio.run(main())
