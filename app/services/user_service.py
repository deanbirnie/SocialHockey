import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_all_users(db: AsyncSession) -> list[User]:
    result = await db.execute(
        select(User).order_by(User.last_name.asc(), User.first_name.asc())
    )
    return list(result.scalars().all())


async def set_role(user_id: uuid.UUID, new_role: str, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.role = new_role
    await db.commit()
    await db.refresh(user)
    return user


async def count_admins(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).select_from(User).where(
            User.role.in_(("admin", "super_admin"))
        )
    )
    return result.scalar() or 0
