
import asyncio
import sys
import traceback

from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import AsyncSessionLocal, engine
from app.models.user import User


async def main() -> int:
    email = settings.MEDI_SUPER_ADMIN_EMAIL.strip().lower()

    if not email:
        print("ERROR: MEDI_SUPER_ADMIN_EMAIL is not configured.")
        return 1

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User)
            .where(func.lower(User.email) == email)
            .with_for_update()
        )

        user = result.scalar_one_or_none()

        if user is None:
            print("ERROR: Configured Super Admin account does not exist.")
            return 1

        if not user.is_active or not user.is_verified:
            print("ERROR: Account must be active and email verified.")
            return 1

        if user.role == "super_admin" and user.is_admin:
            print("Super Admin is already initialized.")
            return 0

        print("Account found:")
        print(f"Name: {user.full_name}")
        print(f"Verified: {user.is_verified}")
        print(f"Active: {user.is_active}")

        confirmation = input(
            "Type INITIALIZE-SUPER-ADMIN to continue: "
        ).strip()

        if confirmation != "INITIALIZE-SUPER-ADMIN":
            print("Cancelled.")
            return 0

        user.role = "super_admin"
        user.is_admin = True

        await db.commit()

        print("Super Admin initialized successfully.")
        return 0


async def run() -> int:
    try:
        return await main()
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        code = asyncio.run(run())
    except KeyboardInterrupt:
        print("Cancelled.")
        code = 130

    sys.exit(code)
