
import argparse
import asyncio
import os
import traceback

from sqlalchemy import func, or_, select, text
from sqlalchemy.engine import make_url

from app.core.config import settings

# Force medi_dev before importing the database engine.
dev_url = make_url(settings.DATABASE_URL).set(database="medi_dev")
settings.DATABASE_URL = dev_url.render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = settings.DATABASE_URL

from app.db.session import engine, AsyncSessionLocal
from app.models.ai import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from app.modules.ai.embeddings.factory import get_embedding_provider


BATCH_SIZE = 16


async def main(apply_changes: bool):
    try:
        # Hard safety check.
        async with engine.connect() as conn:
            database = await conn.scalar(text("SELECT current_database()"))
            print("CONNECTED DATABASE:", database)

            if database != "medi_dev":
                raise RuntimeError("STOPPED: Database is not medi_dev.")

        provider = get_embedding_provider()
        print("PROVIDER:", provider.provider_name)
        print("MODEL:", provider.model_name)

        async with AsyncSessionLocal() as db:
            # Only missing embeddings from approved, published documents.
            base_query = (
                select(KnowledgeChunk)
                .join(
                    KnowledgeDocument,
                    KnowledgeDocument.id == KnowledgeChunk.document_id,
                )
                .join(
                    KnowledgeSource,
                    KnowledgeSource.id == KnowledgeDocument.source_id,
                )
                .where(
                    or_(KnowledgeChunk.embedding.is_(None), func.json_typeof(KnowledgeChunk.embedding) == 'null'),
                    KnowledgeDocument.status == "published",
                    KnowledgeSource.review_status == "approved",
                    KnowledgeChunk.text.is_not(None),
                )
                .order_by(
                    KnowledgeDocument.id,
                    KnowledgeChunk.chunk_index,
                )
            )

            count_query = (
                select(func.count())
                .select_from(KnowledgeChunk)
                .join(
                    KnowledgeDocument,
                    KnowledgeDocument.id == KnowledgeChunk.document_id,
                )
                .join(
                    KnowledgeSource,
                    KnowledgeSource.id == KnowledgeDocument.source_id,
                )
                .where(
                    or_(KnowledgeChunk.embedding.is_(None), func.json_typeof(KnowledgeChunk.embedding) == 'null'),
                    KnowledgeDocument.status == "published",
                    KnowledgeSource.review_status == "approved",
                    KnowledgeChunk.text.is_not(None),
                )
            )

            missing_count = await db.scalar(count_query)
            print("MISSING EMBEDDINGS:", missing_count)

            if not apply_changes:
                print("\nDRY RUN ONLY. No database changes made.")
                return

            if not await provider.is_available():
                raise RuntimeError("Embedding provider is unavailable.")

            if not missing_count:
                print("Nothing to backfill.")
                return

            processed = 0

            while True:
                result = await db.execute(
                    base_query.limit(BATCH_SIZE)
                )
                chunks = list(result.scalars().all())

                if not chunks:
                    break

                vectors = await provider.embed(
                    [chunk.text for chunk in chunks]
                )

                if len(vectors) != len(chunks):
                    raise RuntimeError("Embedding batch size mismatch.")

                for chunk, vector in zip(chunks, vectors):
                    if not isinstance(vector, list) or len(vector) != 1024:
                        raise RuntimeError(
                            "Invalid BGE-M3 embedding dimensions."
                        )

                    chunk.embedding = vector
                    chunk.embedding_provider = provider.provider_name
                    chunk.embedding_model = provider.model_name

                await db.commit()
                processed += len(chunks)

                print(
                    f"BACKFILLED: {processed}/{missing_count}"
                )

            print("\nBACKFILL COMPLETED:", processed)

    except Exception:
        print("\nBACKFILL FAILED")
        traceback.print_exc()
        raise

    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write missing embeddings to medi_dev.",
    )
    args = parser.parse_args()

    asyncio.run(main(args.apply))


