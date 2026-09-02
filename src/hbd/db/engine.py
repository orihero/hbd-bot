"""Engine and session construction. Nothing here knows what a table is.

One rule shapes the whole module: **a session is opened per repository call, inside a
transaction, and closed before the call returns.** ARQ workers are long-lived and highly
concurrent; a session held across awaits is how you get a connection leak that only shows
up under load, and detached-instance errors that only show up in production.

``async_sessionmaker.begin()`` gives exactly that shape — begin, commit on clean exit,
roll back on any exception, close either way — so the repositories use it directly rather
than re-implementing it.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from hbd.logging import get_logger

_log = get_logger(__name__)

__all__ = [
    "create_engine",
    "create_session_factory",
    "ping",
    "SQLITE_MEMORY_URL",
]

#: Used by tests and by nothing else. Named so no test hardcodes a DSN.
SQLITE_MEMORY_URL: Final[str] = "sqlite+aiosqlite:///:memory:"

_POOL_SIZE: Final[int] = 10
_MAX_OVERFLOW: Final[int] = 20
#: Recycle below the typical cloud-Postgres idle timeout so a pooled connection is never
#: handed out already dead.
_POOL_RECYCLE_S: Final[int] = 1_800


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def create_engine(
    url: str,
    *,
    is_echo: bool = False,
    pool_size: int = _POOL_SIZE,
    max_overflow: int = _MAX_OVERFLOW,
) -> AsyncEngine:
    """Build an async engine for ``url``.

    SQLite gets no pool arguments at all: ``aiosqlite`` uses ``StaticPool``/``NullPool``
    depending on the URL and rejects ``pool_size``, so passing the Postgres tuning would
    make the test suite fail for a reason that has nothing to do with the test — which is
    also why ``pool_size`` and ``max_overflow`` are silently ignored there.

    The two pool arguments exist for the third process: bot + worker + admin API at the
    defaults is ``3 × 30 = 90`` connections against a stock ``max_connections`` of 100, so
    the API asks for a smaller share rather than everyone quietly sharing a cliff edge.
    """
    if _is_sqlite(url):
        return create_async_engine(url, echo=is_echo, future=True)
    return create_async_engine(
        url,
        echo=is_echo,
        future=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=_POOL_RECYCLE_S,
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Sessions that do not expire attributes on commit.

    ``expire_on_commit=False`` is required, not a preference: with it on, reading any
    attribute of a row after the transaction closed triggers a lazy refresh, which inside
    async SQLAlchemy raises a greenlet error rather than doing anything useful. Mapping a
    row to a frozen contract model happens after the commit, so the attributes must
    survive it.
    """
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
        class_=AsyncSession,
    )


async def ping(engine: AsyncEngine) -> bool:
    """True when the database answers.

    Never raises — a health probe that crashes its caller is worse than one that reports
    failure. The failure is logged with its cause rather than swallowed.
    """
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        _log.warning("database ping failed", extra={"detail": str(exc)}, exc_info=True)
        return False
    except OSError as exc:
        _log.warning("database unreachable", extra={"detail": str(exc)}, exc_info=True)
        return False
    except Exception as exc:
        # Driver exceptions (e.g. asyncpg InvalidPasswordError) are not always wrapped by
        # SQLAlchemy during connect. Catching them here is what makes "never raises" true.
        _log.warning("database ping failed", extra={"detail": str(exc)}, exc_info=True)
        return False
    return True
