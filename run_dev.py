
import asyncio
import os


def main():
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from app.core.config import settings

    dev_url = make_url(settings.DATABASE_URL).set(
        database="medi_dev"
    )
    rendered_url = dev_url.render_as_string(
        hide_password=False
    )

    settings.DATABASE_URL = rendered_url
    os.environ["DATABASE_URL"] = rendered_url

    from app.db.session import engine

    async def verify_database():
        async with engine.connect() as conn:
            database = await conn.scalar(
                text("SELECT current_database()")
            )

            print("Verified runtime database:", database)

            if database != "medi_dev":
                raise RuntimeError(
                    "Refusing to start: expected medi_dev database."
                )

        await engine.dispose()

    asyncio.run(verify_database())

    import uvicorn

    print("Starting MEDI with verified medi_dev database.")

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=["app"],
    )


if __name__ == "__main__":
    main()
