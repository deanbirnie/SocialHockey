"""
SocialHockey admin CLI.

Usage:
    python -m app.cli promote-super-admin user@example.com
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.user import User


async def _promote_super_admin(email: str) -> None:
    async with AsyncSessionLocal() as db:
        # Look up the target user.
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user is None:
            print(f"Error: no user found with email '{email}'.", file=sys.stderr)
            sys.exit(1)

        if user.role == "super_admin":
            print(f"{user.first_name} {user.last_name} ({email}) is already super_admin.")
            return

        # Check whether a different super_admin already exists.
        result = await db.execute(
            select(User).where(User.role == "super_admin")
        )
        existing_super = result.scalar_one_or_none()

        if existing_super is not None:
            print(
                f"Warning: {existing_super.first_name} {existing_super.last_name}"
                f" ({existing_super.email}) is already super_admin."
            )
            answer = input("Proceed and promote this user anyway? [y/N] ").strip().lower()
            if answer != "y":
                print("Aborted.")
                return

        user.role = "super_admin"
        await db.commit()
        print(f"Done: {user.first_name} {user.last_name} ({email}) is now super_admin.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    promote_parser = subparsers.add_parser(
        "promote-super-admin",
        help="Promote a registered user to the super_admin role.",
    )
    promote_parser.add_argument("email", help="Email address of the user to promote.")

    args = parser.parse_args()

    if args.command == "promote-super-admin":
        asyncio.run(_promote_super_admin(args.email))


if __name__ == "__main__":
    main()
