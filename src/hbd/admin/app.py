"""The ASGI application, and the three refusals its lifespan makes before it serves anything.

**1. The panel is off unless somebody turned it on.** ``HBD_ADMIN_ENABLED`` defaults to
false and the lifespan refuses to start while it is. An admin surface that appears because a
dependency was installed is not a decision anybody made, and it is also the kill switch: the
way to take the panel down during an incident is one variable and a restart, not a code
change.

**2. In prod, a vendor credential this host can reach is a refusal, and the message names
the variable.** This is the enforcement half of D10. ``AdminSettings`` cannot read
``HBD_ELEVENLABS_API_KEY`` — there is no field — so the *value* is already unreachable; this
check is about the host. A credential the deploy put within reach means it handed the admin
host something the design says it must never hold, and in prod that is a mistake to stop
rather than to note. In dev it is a WARNING naming the variable, because a shared dev
``.env`` is normal and a hard failure there would push people to weaken the check in the
place where it matters.

**Both places count as reach.** The check reads ``os.environ`` *and* the names parsed out of
``.env.admin``. A key written into that file is exactly as present on this host as an
exported one — it is simply invisible to a check that only looks at the environment, which
is how a vendor key could land in the panel's own config file and draw not even the dev
warning. Values are never read, logged or carried into the refusal; only names are.

**3. A ``__Host-`` cookie without ``Secure`` is refused outside dev** — enforced in
``AdminSettings``' own validator, so ``create_app`` cannot be handed a settings object that
would serve one.

``app`` is built at import so ``uvicorn hbd.admin.app:app`` works, and ``create_app()``
therefore reads **no** configuration: settings are built inside the lifespan. Importing this
module must never fail on a missing environment variable, or the failure mode of a typo in
``.env.admin`` becomes an unimportable module rather than a message naming the variable.

Nothing here names an individual setting. The three refusals above are the only per-field
decisions this module makes, and the vendor list is derived from ``hbd.config``; every other
bound — including "required in prod" — belongs to ``AdminSettings``' own validators and
reaches the operator through ``build_admin_settings``' ``ConfigError``. Adding a setting,
even a required one, therefore needs no change to this file.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Final

from dotenv import dotenv_values
from fastapi import FastAPI

from hbd.admin.container import AdminContainer, build_admin_container
from hbd.admin.errors import handle_unexpected, install_error_handlers
from hbd.admin.logging_mw import RequestLogMiddleware
from hbd.admin.middleware import (
    CorrelationIdMiddleware,
    SecurityHeadersMiddleware,
    UnhandledErrorMiddleware,
)
from hbd.admin.routers import (
    build_audit_router,
    build_auth_router,
    build_health_router,
    build_login_router,
    build_retention_router,
)
from hbd.admin.settings import ADMIN_ENV_FILE, AdminSettings, build_admin_settings
from hbd.config import ENV_PREFIX, VENDOR_SECRET_FIELDS
from hbd.errors import ConfigError
from hbd.logging import configure_logging, get_logger

__all__ = ["FORBIDDEN_ENV_VARS", "ADMIN_ENV_FILE", "create_app", "app"]

_LOGGER: Final = get_logger(__name__)

#: ``HBD_TELEGRAM_BOT_TOKEN``, ``HBD_ELEVENLABS_API_KEY``, ``HBD_LLM_API_KEY`` — derived from
#: ``hbd.config`` rather than restated, so a fourth vendor credential added there is covered
#: here without anyone remembering to add it. Never restate this list anywhere.
FORBIDDEN_ENV_VARS: Final[tuple[str, ...]] = tuple(
    f"{ENV_PREFIX}{name.upper()}" for name in VENDOR_SECRET_FIELDS
)

_DISABLED_MESSAGE: Final[str] = (
    "The admin panel is disabled. Set HBD_ADMIN_ENABLED=true in .env.admin to run it."
)


def _env_file_names() -> frozenset[str]:
    """The variable NAMES set in ``.env.admin``, upper-cased. Values are never returned.

    Parsed with the same library pydantic-settings uses to read this file, so the two agree
    on what "set" means, and upper-cased because that read is case-insensitive: a lowercase
    ``hbd_llm_api_key`` line is just as live as the shouted form.
    """
    try:
        parsed = dotenv_values(ADMIN_ENV_FILE)
    except OSError as exc:
        # Not swallowed. The file is unreadable rather than absent, so the check below is
        # weaker than it looks and an operator has to be told which half ran.
        _LOGGER.warning(
            "could not read the admin env file; the vendor-credential check saw the "
            "process environment only",
            extra={"event": "admin.boot.env_file_unreadable", "path": ADMIN_ENV_FILE},
            exc_info=exc,
        )
        return frozenset()
    return frozenset(name.upper() for name, value in parsed.items() if value)


def _present_vendor_vars() -> tuple[str, ...]:
    """Which forbidden variables this host puts within reach. Names only, never values.

    Two sources, because both are real: what the deploy exported, and what somebody wrote
    into the panel's own ``.env.admin``. An empty value in either is "not set", which is the
    normal shape of a blanked or commented-out key.
    """
    from_file = _env_file_names()
    return tuple(name for name in FORBIDDEN_ENV_VARS if os.environ.get(name) or name in from_file)


def _refuse_vendor_credentials(settings: AdminSettings) -> None:
    """Refuse in prod, warn elsewhere. Either way the message names the variable."""
    present = _present_vendor_vars()
    if not present:
        return
    listed = ", ".join(present)
    if settings.is_production:
        raise ConfigError(
            "The admin process must not hold a vendor credential or a bot token, and these "
            f"are within reach of it — in its environment or in {ADMIN_ENV_FILE}: {listed}. "
            "Remove them from the admin host: every action needing a credential is an ARQ "
            "job the worker performs.",
            context={"variables": list(present)},
        )
    _LOGGER.warning(
        "vendor credentials are within reach of the admin process",
        extra={"event": "admin.boot.vendor_env_present", "variables": list(present)},
    )


def _refuse_disabled_panel(settings: AdminSettings) -> None:
    if not settings.admin_enabled:
        raise ConfigError(_DISABLED_MESSAGE, context={"environment": settings.environment})


def _lifespan_factory(
    preset_settings: AdminSettings | None, preset_container: AdminContainer | None
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Build the lifespan bound to whatever the caller pre-supplied. Called once per app."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        settings = _resolve_settings(preset_settings, preset_container)
        configure_logging(level=settings.log_level, is_json=not settings.is_debug)
        _refuse_disabled_panel(settings)
        _refuse_vendor_credentials(settings)
        container = preset_container or await build_admin_container(settings)
        application.state.settings = settings
        application.state.container = container
        _LOGGER.info(
            "admin api started",
            extra={
                "event": "admin.boot.ok",
                "environment": settings.environment,
                "is_cookie_secure": settings.is_cookie_secure,
                "public_origin": settings.admin_public_origin,
            },
        )
        try:
            yield
        finally:
            # A container the caller handed in is the caller's to close; closing it here
            # would dispose a pool a test still needs for its assertions.
            if preset_container is None:
                await container.aclose()

    return lifespan


def _resolve_settings(
    preset_settings: AdminSettings | None, preset_container: AdminContainer | None
) -> AdminSettings:
    """The container's settings win, so an application can never run under two of them."""
    if preset_container is not None:
        return preset_container.settings
    return preset_settings or build_admin_settings()


def create_app(
    settings: AdminSettings | None = None, *, container: AdminContainer | None = None
) -> FastAPI:
    """Build the application. Reads no configuration — the lifespan does that.

    ``container`` is the composition seam: a test hands in one built over in-memory SQLite
    and a fake Redis, and owns its lifetime. Production passes neither argument.
    """
    application = FastAPI(
        title="hbd admin",
        version="1",
        lifespan=_lifespan_factory(settings, container),
        # The panel is a JSON API behind a login. Publishing an interactive schema browser
        # from the same origin adds a second HTML surface under the CSP for no operator
        # benefit; the OpenAPI document itself stays available for tooling.
        docs_url=None,
        redoc_url=None,
    )
    install_error_handlers(application)
    # Added outermost-last: Starlette inserts each at position 0, so the correlation id is
    # bound before anything else runs and is still bound when the log line is written.
    #
    # The catch-all goes first, which puts it INNERMOST — just outside Starlette's own
    # ExceptionMiddleware and inside all three below. It is a middleware rather than an
    # ``add_exception_handler(Exception, ...)`` because Starlette routes that key to
    # ServerErrorMiddleware, which it installs outside every layer here: a 500 answered
    # there carried no nosniff, no CSP, no no-store, no X-Correlation-ID, an envelope and an
    # incident line both reading "-", and no response.start for the request log to see.
    # Final stack, outermost first:
    #   ServerErrorMiddleware (Starlette's, now handler-less — the backstop for a failure in
    #     UnhandledErrorMiddleware itself)
    #   CorrelationIdMiddleware -> SecurityHeadersMiddleware -> RequestLogMiddleware
    #   UnhandledErrorMiddleware -> ExceptionMiddleware -> router
    application.add_middleware(UnhandledErrorMiddleware, render=handle_unexpected)
    application.add_middleware(RequestLogMiddleware)
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(CorrelationIdMiddleware)
    # No ``prefix=``: each router declares full paths, so ``scope["route"].path`` is the
    # exact template the forced-rotation gate and the request log compare against.
    application.include_router(build_health_router())
    application.include_router(build_login_router())
    application.include_router(build_auth_router())
    application.include_router(build_audit_router())
    application.include_router(build_retention_router())
    return application


#: The uvicorn entry point (``make admin``). Constructing it reads nothing.
app: Final[FastAPI] = create_app()
