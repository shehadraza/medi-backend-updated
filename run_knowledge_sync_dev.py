
import asyncio
import os
import traceback

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import settings

# Force the development database before importing the DB engine.
dev_url = make_url(settings.DATABASE_URL).set(database="medi_dev")
settings.DATABASE_URL = dev_url.render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = settings.DATABASE_URL

from app.db.session import engine, AsyncSessionLocal
from app.modules.ai.knowledge_sync import sync_medlineplus


async def main():
    try:
        async with engine.connect() as conn:
            database = await conn.scalar(text("SELECT current_database()"))
            print("Verified database:", database)

            if database != "medi_dev":
                raise RuntimeError("STOPPED: Not connected to medi_dev.")

        print("Starting direct MedlinePlus-only sync...")

        async with AsyncSessionLocal() as db:
            result = await sync_medlineplus(db)
            print("\nMEDLINEPLUS RESULT:")
            print(result)

    except Exception as exc:
        print("\nMEDLINEPLUS SYNC FAILED")
        print("Exception type:", type(exc).__name__)
        print("Exception message:", str(exc))
        print("\nFULL TRACEBACK:")
        traceback.print_exc()

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
