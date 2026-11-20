
import asyncio

from sqlalchemy import select

from app.db.session import AsyncSessionLocal, engine
from app.models.user import User


def mask_email(email: str) -> str:
    local, separator, domain = email.partition("@")

    if not separator:
        return "***"

    return f"{local[:1]}***@{domain}"


async def main():
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(
                    User.email,
                    User.is_active,
                    User.is_verified,
                    User.is_admin,
                ).order_by(User.created_at.desc())
            )

            users = result.all()

            print(f"\nTotal registered accounts: {len(users)}")

            for user in users:
                print(
                    f"Email: {mask_email(user.email)} | "
                    f"Active: {user.is_active} | "
                    f"Verified: {user.is_verified} | "
                    f"Admin: {user.is_admin}"
                )

            if not users:
                print("No registered accounts found in this database.")

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
