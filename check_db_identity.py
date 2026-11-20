import asyncio
from sqlalchemy import text
from app.db.session import engine

async def main():
    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT current_database(), current_schema(), current_user"
        ))
        row = result.one()
        print("Database:", row[0])
        print("Schema:", row[1])
        print("DB User:", row[2])
    await engine.dispose()

asyncio.run(main())