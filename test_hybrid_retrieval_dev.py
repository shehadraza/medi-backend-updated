
import asyncio
import os

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import settings

url = make_url(settings.DATABASE_URL).set(database="medi_dev")
settings.DATABASE_URL = url.render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = settings.DATABASE_URL

from app.db.session import engine, AsyncSessionLocal
from app.modules.ai.rag.retrieval import retrieve_chunks


async def main():
    try:
        async with engine.connect() as conn:
            database = await conn.scalar(text("SELECT current_database()"))
            print("DATABASE:", database)

            if database != "medi_dev":
                raise RuntimeError("Wrong database. Stopped.")

        test_queries = [
            "What are the common symptoms of diabetes?",
            "ডায়াবেটিসের সাধারণ লক্ষণ কী?"
        ]

        async with AsyncSessionLocal() as db:
            for query in test_queries:
                print("\n" + "=" * 60)
                print("QUERY:", query)

                results = await retrieve_chunks(db, query, limit=5)

                print("RESULT COUNT:", len(results))

                for index, item in enumerate(results, 1):
                    print(f"\nRESULT {index}:")
                    print(repr(item))

                if not results:
                    print("NO RETRIEVAL RESULTS")

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
