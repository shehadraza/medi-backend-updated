
import asyncio
from sqlalchemy import text

# Force development database before importing the engine.
from app.core.config import settings

database_url = settings.DATABASE_URL
settings.DATABASE_URL = database_url.rsplit("/", 1)[0] + "/medi_dev"

from app.db.session import engine


async def main():
    try:
        async with engine.connect() as conn:
            db = await conn.scalar(text("SELECT current_database()"))
            print("DATABASE:", db)

            if db != "medi_dev":
                raise RuntimeError("Safety check failed: expected medi_dev")

            for table in (
                "ai_knowledge_sources",
                "ai_knowledge_documents",
                "ai_knowledge_chunks",
            ):
                result = await conn.execute(
                    text(f"SELECT COUNT(*) FROM {table}")
                )
                print(f"{table}: {result.scalar_one()}")

            result = await conn.execute(text("""
                SELECT status, COUNT(*)
                FROM ai_knowledge_documents
                GROUP BY status
                ORDER BY status
            """))

            print("\nDOCUMENT STATUS:")
            for status, count in result:
                print(f"{status}: {count}")

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
