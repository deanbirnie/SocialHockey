from collections.abc import AsyncGenerator
from urllib.parse import urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# asyncpg rejects query params it doesn't know (e.g. Neon adds channel_binding).
# Strip all query params from the URL and handle SSL via connect_args instead.
_parsed = urlparse(settings.DATABASE_URL)
_db_url = urlunparse(_parsed._replace(query=""))
_connect_args = {} if _parsed.hostname in ("localhost", "127.0.0.1") else {"ssl": True}

engine = create_async_engine(_db_url, echo=False, connect_args=_connect_args)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
