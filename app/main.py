import asyncio
import fcntl
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.routes.admin import router as admin_router
from app.routes.auth import router as auth_router
from app.routes.export import router as export_router
from app.routes.games import router as games_router
from app.routes.reservations import router as reservations_router
from app.templating import templates

BASE_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)
access_logger = logging.getLogger("app.access")


# ---------------------------------------------------------------------------
# Alembic migrations (run at startup, file-locked across workers)
# ---------------------------------------------------------------------------


def _run_migrations() -> None:
    """Apply pending Alembic migrations.

    Uses a file lock so that when uvicorn spawns multiple workers each calls
    this function independently but only one actually runs migrations at a time.
    """
    with open("/tmp/alembic_upgrade.lock", "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            from alembic import command
            from alembic.config import Config

            cfg = Config("alembic.ini")
            command.upgrade(cfg, "head")
            logger.info("Alembic migrations applied successfully")
        except Exception:
            logger.exception("Alembic migration failed — app may be misconfigured")
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_migrations)
    yield


# ---------------------------------------------------------------------------
# App + middleware
# ---------------------------------------------------------------------------

app = FastAPI(title="SocialHockey", lifespan=lifespan)

_parsed_base = urlparse(settings.BASE_URL)
_is_production = _parsed_base.scheme == "https"

# TrustedHostMiddleware — restrict accepted Host headers in production.
_allowed_hosts = (
    [_parsed_base.hostname, "localhost", "127.0.0.1"]
    if _is_production
    else ["*"]
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)

# CORSMiddleware — allow same origin only in production.
_cors_origins = [settings.BASE_URL.rstrip("/")] if _is_production else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    access_logger.info(
        "%s %s %d %.1fms",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


# ---------------------------------------------------------------------------
# Static files + routers
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(export_router)
app.include_router(games_router)
app.include_router(reservations_router)


@app.get("/")
async def home(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    return templates.TemplateResponse("pages/home.html", {"request": request, "user": user})
