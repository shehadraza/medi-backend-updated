import asyncio
import getpass
import asyncpg
from sqlalchemy.engine import make_url
from app.core.config import settings

url = make_url(settings.DATABASE_URL)

password = getpass.getpass("Enter your new PostgreSQL password: ")

print("Matches backend configuration:", password == url.password)

async def test():
    try:
        conn = await asyncpg.connect(
            user=url.username,
            password=password,
            host=url.host,
            port=url.port,
            database=url.database
        )
        print("DIRECT CONNECTION: SUCCESS")
        await conn.close()
    except Exception as e:
        print("DIRECT CONNECTION: FAILED")
        print("Error:", type(e).__name__)

asyncio.run(test())