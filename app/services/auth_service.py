import secrets
from datetime import datetime, timedelta, timezone

import resend
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.auth_token import AuthToken
from app.models.pending_registration import PendingRegistration
from app.models.session import UserSession

# Must match a sender address verified in your Resend account.
FROM_EMAIL = "Hockey Test <login@birniedev.co.za>"


def generate_token() -> str:
    return secrets.token_hex(32)


async def send_magic_link(email: str, token: str, is_registration: bool = False) -> None:
    path = "/auth/register/verify" if is_registration else "/auth/verify"
    link = f"{settings.BASE_URL}{path}?token={token}"

    resend.api_key = settings.RESEND_API_KEY
    resend.Emails.send(
        {
            "from": FROM_EMAIL,
            "to": [email],
            "subject": "Your Hockey App Login Link",
            "html": (
                "<p>Click the link below to sign in to SocialHockey.</p>"
                f'<p><a href="{link}">{link}</a></p>'
                "<p>This link expires in 15 minutes. If you did not request it, "
                "you can safely ignore this email.</p>"
            ),
        }
    )


async def create_auth_token(user_id, db: AsyncSession) -> str:
    token = generate_token()
    db.add(
        AuthToken(
            user_id=user_id,
            token=token,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
    )
    await db.commit()
    return token


async def create_pending_registration(
    email: str, first_name: str, last_name: str, db: AsyncSession
) -> str:
    # Replace any existing pending registration for this email.
    existing = await db.execute(
        select(PendingRegistration).where(PendingRegistration.email == email)
    )
    row = existing.scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.flush()

    token = generate_token()
    db.add(
        PendingRegistration(
            email=email,
            first_name=first_name,
            last_name=last_name,
            token=token,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
    )
    await db.commit()
    return token


async def validate_token(token: str, db: AsyncSession):
    """Validate a login token, mark it used, and return the associated user_id."""
    result = await db.execute(
        select(AuthToken).where(
            AuthToken.token == token,
            AuthToken.used == False,  # noqa: E712
            AuthToken.expires_at > datetime.now(timezone.utc),
        )
    )
    auth_token = result.scalar_one_or_none()
    if not auth_token:
        raise HTTPException(status_code=400, detail="Invalid or expired login link.")

    auth_token.used = True
    await db.commit()
    return auth_token.user_id


async def validate_registration_token(token: str, db: AsyncSession) -> PendingRegistration:
    """Validate a registration token and return the PendingRegistration record."""
    result = await db.execute(
        select(PendingRegistration).where(
            PendingRegistration.token == token,
            PendingRegistration.expires_at > datetime.now(timezone.utc),
        )
    )
    pending = result.scalar_one_or_none()
    if not pending:
        raise HTTPException(status_code=400, detail="Invalid or expired registration link.")
    return pending


async def create_session(user_id, db: AsyncSession) -> str:
    """Create a UserSession and return the session token."""
    token = generate_token()
    db.add(
        UserSession(
            user_id=user_id,
            session_token=token,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.SESSION_EXPIRY_DAYS),
        )
    )
    await db.commit()
    return token
