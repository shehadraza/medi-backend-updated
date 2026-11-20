import asyncio
import os
import subprocess
import sys

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings


async def main():
    dev_url = make_url(settings.DATABASE_URL).set(
        database="medi_dev"
    )

    engine = create_async_engine(dev_url)

    try:
        async with engine.connect() as conn:
            db_name = await conn.scalar(
                text("SELECT current_database()")
            )

            print("Connected database:", db_name)

            if db_name != "medi_dev":
                raise RuntimeError(
                    "Safety check failed. Migration cancelled."
                )
    finally:
        await engine.dispose()

    env = os.environ.copy()
    env["DATABASE_URL"] = dev_url.render_as_string(
        hide_password=False
    )
    env.pop("MEDI_TEST_MODE", None)

    print("\nApplying migrations to medi_dev only...\n")

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=env,
        check=False,
    )

    if result.returncode != 0:
        raise SystemExit(result.returncode)

    print("\nMEDI development database migration completed.")


if __name__ == "__main__":
    asyncio.run(main())