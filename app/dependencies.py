from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.session import UserSession
from app.models.user import User


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Read the session cookie and return the User, or None if not authenticated."""
    token = request.cookies.get("session_token")
    if not token:
        return None

    result = await db.execute(
        select(UserSession).where(
            UserSession.session_token == token,
            UserSession.expires_at > datetime.now(timezone.utc),
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return None

    result = await db.execute(select(User).where(User.id == session.user_id))
    return result.scalar_one_or_none()


async def get_current_user_required(
    current_user: User | None = Depends(get_current_user),
) -> User:
    """Like get_current_user, but redirects to /auth/login if not authenticated."""
    if current_user is None:
        raise HTTPException(status_code=303, headers={"Location": "/auth/login"})
    return current_user


async def require_admin(
    current_user: User = Depends(get_current_user_required),
) -> User:
    if current_user.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


async def require_super_admin(
    current_user: User = Depends(get_current_user_required),
) -> User:
    if current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")
    return current_user
