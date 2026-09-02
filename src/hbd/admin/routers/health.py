"""Liveness and readiness — deliberately two routes, because they answer two questions.

``/healthz`` is **liveness**: is this process able to answer at all? It returns a bare 200
with an empty body and touches neither the database nor Redis. That is not an optimisation.
An orchestrator restarts a container whose liveness probe fails, so a liveness probe that
depends on Postgres turns a database blip into a restart loop across every replica at once —
the outage amplifying itself precisely when the database is already struggling.

``/readyz`` is **readiness**, and its detail is gated. §6.3 made that change deliberately:
behind the reverse proxy this deployment assumes, an unauthenticated detailed body is fleet
telemetry for anyone who can reach the port — whether the panel is up, whether its database
is reachable, and, through ``configVersion``, whether a just-committed change has landed.
So the public answer is a **constant** word, and ``{database, redis, configVersion}`` needs
either a session or an ``X-Probe-Token`` matching ``admin_probe_token`` under
``compare_digest``. Constant, not merely short: "degraded" is the same fleet telemetry as
``{"database": false}`` with fewer characters — it tells an unauthenticated caller that a
backing service of this deployment is down, which is exactly what §6.3 gated. An
unauthenticated ``/readyz`` therefore also pings nothing, so it cannot be used to load the
database either.

The authorisation check is read-only on purpose (§12.1 T8): it goes through
``deps.has_live_session`` rather than ``get_current_admin``, because the latter advances
``last_seen_at`` and this is a GET.
"""

from __future__ import annotations

import secrets
from typing import Any, Final

from fastapi import APIRouter, Request, Response

from hbd.admin.container import AdminContainer
from hbd.admin.deps import Container, has_live_session
from hbd.db.engine import ping
from hbd.logging import get_logger

__all__ = [
    "PROBE_TOKEN_HEADER",
    "CONFIG_VERSION_KEY",
    "STATUS_OK",
    "STATUS_DEGRADED",
    "PUBLIC_STATUS",
    "build_health_router",
]

_LOGGER: Final = get_logger(__name__)

PROBE_TOKEN_HEADER: Final[str] = "X-Probe-Token"
#: Written by the config editor in Phase 7. Absent until then, which reads as ``null``.
CONFIG_VERSION_KEY: Final[str] = "hbd:settings:version"

STATUS_OK: Final[str] = "ok"
STATUS_DEGRADED: Final[str] = "degraded"
#: What every unauthenticated caller is told, whatever the deployment is actually doing.
PUBLIC_STATUS: Final[str] = STATUS_OK


async def _redis_ok(container: AdminContainer) -> bool:
    """True when Redis answers. Never raises — a probe that crashes reports nothing."""
    try:
        return bool(await container.redis.ping())
    except Exception as exc:
        _LOGGER.warning(
            "admin redis ping failed",
            extra={"event": "admin.health.redis_unreachable", "detail": repr(exc)},
        )
        return False


async def _config_version(container: AdminContainer) -> int | None:
    """The live settings version, or ``None`` when nothing has published one yet."""
    try:
        raw = await container.redis.get(CONFIG_VERSION_KEY)
    except Exception as exc:
        _LOGGER.warning(
            "admin config version could not be read",
            extra={"event": "admin.health.version_unreadable", "detail": repr(exc)},
        )
        return None
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        _LOGGER.warning(
            "admin config version key holds a non-integer",
            extra={"event": "admin.health.version_malformed"},
        )
        return None


def _is_probe_authorised(request: Request, container: AdminContainer) -> bool:
    """Constant-time match against ``admin_probe_token``. An empty setting authorises nobody.

    Checked first because it is cheap and because it must keep working when the database is
    the thing that is down — which is the exact moment a monitor most needs the detail.
    """
    configured = container.settings.admin_probe_token
    if not configured:
        return False
    presented = request.headers.get(PROBE_TOKEN_HEADER)
    if not presented or not presented.isascii():
        return False
    return secrets.compare_digest(presented, configured)


async def _may_see_detail(request: Request, container: AdminContainer) -> bool:
    """Whether this caller gets the detailed body rather than the constant word.

    The probe token is tried first: it is cheap, it needs no database, and a monitor holding
    one must still get an answer when the database is the thing that is down.
    """
    return _is_probe_authorised(request, container) or await has_live_session(request, container)


def build_health_router() -> APIRouter:
    """The two probes. Neither carries a permission guard, and both are on the exempt list."""
    router = APIRouter(tags=["health"])

    @router.get("/healthz", include_in_schema=False)
    async def healthz() -> Response:
        """Liveness. Bare 200, empty body, no database, no Redis, no version."""
        return Response(status_code=200)

    @router.get("/readyz")
    async def readyz(request: Request, container: Container) -> dict[str, Any]:
        """Readiness. A constant word in public; the detail needs a session or a probe token."""
        if not await _may_see_detail(request, container):
            return {"status": PUBLIC_STATUS}
        is_db_ok = await ping(container.engine)
        is_redis_ok = await _redis_ok(container)
        return {
            "status": STATUS_OK if is_db_ok and is_redis_ok else STATUS_DEGRADED,
            "database": is_db_ok,
            "redis": is_redis_ok,
            "configVersion": await _config_version(container),
        }

    return router
