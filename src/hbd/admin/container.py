"""The admin process's composition root: engine, sessions, Redis, and nothing else.

Deliberately **narrower** than ``hbd.runtime.container.build_container``. There is no
``ProviderSet`` here, no ``Bot``, no ffmpeg post-processor and no ``httpx`` client — not
because they would go unused, but because the absence is the control: a process with no HTTP
client and no credential has no SSRF surface and no vendor spend to reach
(ADMIN_PANEL_PLAN §4.2, §12.1 T5, T12). Every action that needs one of those is an ARQ
enqueue performed by the worker.

It shares ``create_engine``/``create_session_factory`` with the runtime container so the
pool shape and the ``expire_on_commit=False`` rule cannot drift between the two, and it asks
for a **smaller** pool: bot + worker + API at the shared default is ``3 × 30 = 90``
connections against a stock Postgres ``max_connections`` of 100 (§4.4).

The container is a frozen dataclass built once per process. Tests construct one directly
with a fake Redis rather than reaching for a server, which is why the constructor takes
finished objects and :func:`build_admin_container` is a separate function.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Final

from argon2 import PasswordHasher
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from hbd.admin.security.clientip import IpNetwork
from hbd.admin.security.passwords import build_hasher
from hbd.admin.security.ratelimit import RedisWindowCounterStore, WindowCounterStore
from hbd.admin.settings import AdminSettings
from hbd.db.base import Base
from hbd.db.engine import create_engine, create_session_factory
from hbd.logging import get_logger

__all__ = [
    "AdminContainer",
    "ADMIN_POOL_SIZE",
    "ADMIN_MAX_OVERFLOW",
    "build_admin_container",
    "admin_container",
]

_LOGGER: Final = get_logger(__name__)

#: §4.4's share of the connection budget: five checked out, five of headroom.
ADMIN_POOL_SIZE: Final[int] = 5
ADMIN_MAX_OVERFLOW: Final[int] = 5

#: Fake and test runs point at SQLite, which has no migration history to honour, so the
#: schema is materialised directly — exactly as ``hbd.runtime.container`` does it.
_SQLITE_PREFIX: Final[str] = "sqlite"


@dataclass(frozen=True, slots=True)
class AdminContainer:
    """Every long-lived resource the API holds, already built. Immutable.

    ``hasher`` and ``trusted_proxies`` live here rather than being rebuilt per request for
    the same reason the engine does: an argon2 hasher is configuration, and re-parsing the
    proxy CIDRs on every rate-limit decision would put a parse in the authentication path.
    """

    settings: AdminSettings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    redis: Redis[str]
    hasher: PasswordHasher
    trusted_proxies: tuple[IpNetwork, ...]
    rate_limits: WindowCounterStore

    async def aclose(self) -> None:
        """Release the pool and the Redis connection, reporting each failure separately.

        One resource failing to close must not hide the other: a leaked Redis connection
        after a database error is how a restart loop turns into a connection exhaustion.
        """
        try:
            # ``aclose`` since redis-py 5.0.1; ``close`` is deprecated. The pinned
            # ``types-redis`` 4.6 stubs predate the rename and shadow redis-py's own inline
            # types, so the call is correct at runtime and invisible to mypy.
            await self.redis.aclose()  # type: ignore[attr-defined]
        except Exception as exc:
            _LOGGER.warning(
                "admin redis client did not close cleanly",
                extra={"event": "admin.container.redis_close_failed", "detail": repr(exc)},
            )
        await self.engine.dispose()


async def build_admin_container(settings: AdminSettings) -> AdminContainer:
    """Build everything from configuration. No I/O beyond the SQLite schema shortcut.

    ``Redis.from_url`` does not connect; the first command does. That is deliberate here —
    ``/healthz`` must answer without touching Redis, and the bootstrap CLI must reach the
    database on a host where Redis is not running yet.
    """
    engine = create_engine(
        settings.database_url,
        pool_size=ADMIN_POOL_SIZE,
        max_overflow=ADMIN_MAX_OVERFLOW,
    )
    if settings.database_url.startswith(_SQLITE_PREFIX):
        await _create_schema(engine)
    redis: Redis[str] = Redis.from_url(settings.redis_url, decode_responses=True)
    _LOGGER.info(
        "admin container built",
        extra={
            "event": "admin.container.built",
            "environment": settings.environment,
            "pool_size": ADMIN_POOL_SIZE,
            # The host half only. The full DSN carries a password and the redaction layer
            # would mask the whole value, which tells an operator nothing.
            "database": settings.database_url.split("@")[-1],
        },
    )
    return AdminContainer(
        settings=settings,
        engine=engine,
        session_factory=create_session_factory(engine),
        redis=redis,
        hasher=build_hasher(
            time_cost=settings.admin_argon2_time_cost,
            memory_kib=settings.admin_argon2_memory_kib,
            parallelism=settings.admin_argon2_parallelism,
        ),
        trusted_proxies=settings.trusted_proxies,
        rate_limits=RedisWindowCounterStore(redis),
    )


@asynccontextmanager
async def admin_container(settings: AdminSettings) -> AsyncIterator[AdminContainer]:
    """Build, hand over, and always release. The shape the lifespan and the CLI both use."""
    container = await build_admin_container(settings)
    try:
        yield container
    finally:
        await container.aclose()


async def _create_schema(engine: AsyncEngine) -> None:
    """SQLite has no migration history to honour, so the schema is materialised directly."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
