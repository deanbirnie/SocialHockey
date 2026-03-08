from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.session import UserSession
from app.models.user import User
from app.services import auth_service
from app.templating import templates

router = APIRouter(prefix="/auth")


def _set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.BASE_URL.startswith("https"),
        max_age=settings.SESSION_EXPIRY_DAYS * 86400,
    )


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@router.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(
        "pages/auth/login.html", {"request": request, "user": None}
    )


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        return RedirectResponse(f"/auth/register?email={email}", status_code=303)

    token = await auth_service.create_auth_token(user.id, db)
    await auth_service.send_magic_link(email, token, is_registration=False)

    return templates.TemplateResponse(
        "pages/auth/check_email.html",
        {"request": request, "user": None, "email": email},
    )


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


@router.get("/register")
async def register_page(request: Request, email: str = ""):
    return templates.TemplateResponse(
        "pages/auth/register.html",
        {"request": request, "user": None, "email": email},
    )


@router.post("/register")
async def register_submit(
    request: Request,
    email: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    token = await auth_service.create_pending_registration(
        email, first_name, last_name, db
    )
    await auth_service.send_magic_link(email, token, is_registration=True)

    return templates.TemplateResponse(
        "pages/auth/check_email.html",
        {"request": request, "user": None, "email": email},
    )


# ---------------------------------------------------------------------------
# Verify (existing user login)
# ---------------------------------------------------------------------------


@router.get("/verify")
async def verify(token: str, db: AsyncSession = Depends(get_db)):
    user_id = await auth_service.validate_token(token, db)
    session_token = await auth_service.create_session(user_id, db)

    response = RedirectResponse("/", status_code=303)
    _set_session_cookie(response, session_token)
    return response


# ---------------------------------------------------------------------------
# Verify (new registration)
# ---------------------------------------------------------------------------


@router.get("/register/verify")
async def register_verify(token: str, db: AsyncSession = Depends(get_db)):
    pending = await auth_service.validate_registration_token(token, db)

    user = User(
        email=pending.email,
        first_name=pending.first_name,
        last_name=pending.last_name,
        role="player",
    )
    db.add(user)
    await db.delete(pending)
    await db.flush()   # Populates user.id via Postgres RETURNING
    await db.commit()

    session_token = await auth_service.create_session(user.id, db)

    response = RedirectResponse("/", status_code=303)
    _set_session_cookie(response, session_token)
    return response


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@router.post("/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get("session_token")
    if token:
        result = await db.execute(
            select(UserSession).where(UserSession.session_token == token)
        )
        session = result.scalar_one_or_none()
        if session:
            await db.delete(session)
            await db.commit()

    response = RedirectResponse("/auth/login", status_code=303)
    response.delete_cookie("session_token")
    return response
