
import asyncio
import math
import os

from sqlalchemy import select, text, func
from sqlalchemy.engine import make_url

from app.core.config import settings

url = make_url(settings.DATABASE_URL).set(database="medi_dev")
settings.DATABASE_URL = url.render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = settings.DATABASE_URL

from app.db.session import engine, AsyncSessionLocal
from app.models.ai import KnowledgeChunk, KnowledgeDocument, KnowledgeSource


async def main():
    try:
        async with engine.connect() as conn:
            database = await conn.scalar(text("SELECT current_database()"))
            print("DATABASE:", database)
            if database != "medi_dev":
                raise RuntimeError("Wrong database. Stopped.")

        async with AsyncSessionLocal() as db:
            query = (
                select(
                    KnowledgeChunk.embedding_provider,
                    KnowledgeChunk.embedding_model,
                    func.count(KnowledgeChunk.id),
                )
                .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
                .join(KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id)
                .where(
                    KnowledgeDocument.status == "published",
                    KnowledgeSource.review_status == "approved",
                )
                .group_by(
                    KnowledgeChunk.embedding_provider,
                    KnowledgeChunk.embedding_model,
                )
            )

            result = await db.execute(query)
            print("\nEMBEDDING DISTRIBUTION:")
            for provider, model, count in result.all():
                print(provider, "|", model, "|", count)

            chunks_query = (
                select(KnowledgeChunk)
                .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
                .join(KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id)
                .where(
                    KnowledgeDocument.status == "published",
                    KnowledgeSource.review_status == "approved",
                )
            )

            result = await db.execute(chunks_query)
            chunks = result.scalars().all()

            missing = 0
            wrong_model = 0
            wrong_dimension = 0
            invalid_values = 0

            for chunk in chunks:
                vector = chunk.embedding

                if vector is None:
                    missing += 1
                    continue

                if (
                    chunk.embedding_provider != "ollama"
                    or chunk.embedding_model != "bge-m3:latest"
                ):
                    wrong_model += 1

                if not isinstance(vector, list) or len(vector) != 1024:
                    wrong_dimension += 1
                    continue

                if not all(
                    isinstance(v, (int, float))
                    and not isinstance(v, bool)
                    and math.isfinite(v)
                    for v in vector
                ):
                    invalid_values += 1

            print("\nTOTAL CHUNKS:", len(chunks))
            print("MISSING:", missing)
            print("WRONG MODEL:", wrong_model)
            print("WRONG DIMENSION:", wrong_dimension)
            print("INVALID VALUES:", invalid_values)

            if not any((missing, wrong_model, wrong_dimension, invalid_values)):
                print("\nEMBEDDING INTEGRITY: PASSED")
            else:
                print("\nEMBEDDING INTEGRITY: NEEDS ATTENTION")

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
