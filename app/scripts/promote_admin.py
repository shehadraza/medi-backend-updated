
import argparse
import asyncio
import sys

from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal, engine
from app.models.user import User


async def promote_admin(email: str) -> int:
    normalized_email = email.strip().lower()

    if not normalized_email:
        print("Error: Email is required.")
        return 1

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User)
            .where(func.lower(User.email) == normalized_email)
            .with_for_update()
        )

        user = result.scalar_one_or_none()

        if user is None:
            print("Error: No account found with this email.")
            return 1

        if not user.is_active:
            print("Error: This account is inactive.")
            return 1

        if not user.is_verified:
            print("Error: This account has not verified its email.")
            return 1

        if user.is_admin:
            print("This account already has administrator access.")
            return 0

        print("\nAccount selected for administrator promotion:")
        print(f"Name: {user.full_name}")
        print(f"Email: {user.email}")
        print(f"Verified: {user.is_verified}")
        print(f"Active: {user.is_active}")

        confirmation = input(
            "\nType PROMOTE to grant administrator access: "
        ).strip()

        if confirmation != "PROMOTE":
            print("Cancelled. No database changes were made.")
            return 0

        user.is_admin = True

        await db.commit()

        print("\nAdministrator access granted successfully.")
        print("The account can now access protected admin endpoints.")

        return 0


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely promote an existing verified MEDI user."
    )

    parser.add_argument(
        "email",
        help="Email address of the existing verified account.",
    )

    args = parser.parse_args()

    try:
        return await promote_admin(args.email)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        exit_code = 130
    except Exception as exc:
        print(f"\nPromotion failed: {type(exc).__name__}")
        exit_code = 1

    sys.exit(exit_code)
