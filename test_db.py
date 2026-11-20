import asyncio
import os

from app.core.test_database import (
    InvalidTestDatabaseConfiguration,
    validate_test_database_url,
)

async def main():
    try:
        test_url = validate_test_database_url(
            os.environ.get("MEDI_TEST_DATABASE_URL")
        )
    except InvalidTestDatabaseConfiguration as exc:
        raise SystemExit(str(exc)) from None

    # Import only after validating and installing the explicitly supplied URL.
    os.environ["MEDI_TEST_MODE"] = "1"
    os.environ["DATABASE_URL"] = test_url
    from sqlalchemy import text
    from app.db.session import engine

    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            if result.scalar() != 1:
                raise RuntimeError("Test database connectivity check returned an unexpected result.")
            print("Isolated test database connection succeeded.")
    except Exception:
        print("Isolated test database connection failed.")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
