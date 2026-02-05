"""
Async SQLAlchemy session management.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import Base

_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker] = None


def _ensure_sqlite_dir(database_url: str) -> None:
    if not database_url.startswith("sqlite"):
        return

    # Example: sqlite+aiosqlite:///./data/tasks.db
    if ":///" not in database_url:
        return
    path_part = database_url.split(":///")[-1]
    db_path = Path(path_part).expanduser()
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is not None:
        return _engine

    _ensure_sqlite_dir(settings.database_url)
    _engine = create_async_engine(settings.database_url, future=True, echo=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker:
    global _sessionmaker
    if _sessionmaker is not None:
        return _sessionmaker

    _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def init_db() -> None:
    """
    Create tables (idempotent).
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized")

