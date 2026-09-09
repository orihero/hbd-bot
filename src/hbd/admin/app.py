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
place where it matters. The list covers a second population as well: secrets belonging to a
settings model this host never loads at all — today the Payme cashbox key — which is what
keeps the merchant endpoint a separate process rather than a router somebody could quietly
add here later.

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
from pathlib import Path
from typing import Final

from dotenv import dotenv_values
from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from hbd.admin.container import AdminContainer, build_admin_container
from hbd.admin.deps import API_PREFIX
from hbd.admin.errors import handle_unexpected, install_error_handlers
from hbd.admin.logging_mw import RequestLogMiddleware
from hbd.admin.middleware import (
    CorrelationIdMiddleware,
    SecurityHeadersMiddleware,
    UnhandledErrorMiddleware,
)
from hbd.admin.middleware.security_headers import (
    IMMUTABLE_PATH_PREFIX,
    STYLE_NONCE_STATE_KEY,
)
from hbd.admin.routers import (
    build_admins_router,
    build_asset_media_router,
    build_assets_router,
    build_audience_lists_router,
    build_audit_router,
    build_auth_router,
    build_broadcast_actions_router,
    build_broadcasts_router,
    build_chats_router,
    build_config_router,
    build_credit_grant_router,
    build_credits_router,
    build_dashboard_router,
    build_generations_router,
    build_health_router,
    build_login_router,
    build_orders_router,
    build_retention_router,
    build_reveal_router,
    build_segment_fields_router,
    build_segments_router,
    build_user_block_router,
    build_users_router,
    build_vendors_router,
    build_wizard_state_router,
)
from hbd.admin.settings import (
    ADMIN_ENV_FILE,
    ADMIN_ENV_FILE_VAR,
    AdminSettings,
    build_admin_settings,
)
from hbd.admin.shell import render_shell
from hbd.config import (
    ENV_PREFIX,
    FOREIGN_SECRET_ENV_VARS,
    VENDOR_SECRET_FIELDS,
    resolve_env_file,
)
from hbd.errors import ConfigError
from hbd.logging import configure_logging, get_logger

__all__ = [
    "FORBIDDEN_ENV_VARS",
    "derive_forbidden_env_vars",
    "ADMIN_ENV_FILE",
    "ADMIN_ENV_FILE_VAR",
    "STATIC_DIR",
    "SPA_INDEX",
    "create_app",
    "app",
]

_LOGGER: Final = get_logger(__name__)


def derive_forbidden_env_vars() -> tuple[str, ...]:
    """The variable names this host must not have within reach, derived from ``hbd.config``.

    **Two populations, and they are different kinds of thing.** The first is every
    credential declared as a FIELD on :class:`hbd.config.Settings` — ``HBD_TELEGRAM_BOT_TOKEN``,
    ``HBD_ELEVENLABS_API_KEY``, ``HBD_LLM_API_KEY``, ``HBD_LLM_FALLBACK_API_KEY``,
    ``HBD_OPENROUTER_MANAGEMENT_KEY`` — spelled by upper-casing ``VENDOR_SECRET_FIELDS``, so a
    sixth credential added to that class is covered here without anyone remembering this file
    exists. The second is ``FOREIGN_SECRET_ENV_VARS``: environment variable NAMES belonging to
    a settings model this process never loads at all (``hbd.payme.settings.PaymeSettings``),
    which is why they cannot be derived from a field tuple and why the forbidden set is now
    wider than the field tuple it used to mirror one-for-one.

    ``HBD_PAYME_MERCHANT_KEY`` is in that second population, and it is the mechanism that
    makes "the Payme endpoint is not a router on the panel" a fact rather than an intention:
    a prod admin host that can reach the cashbox key refuses to boot, so the endpoint cannot
    quietly be moved onto this app later. Its blast radius is also different in kind from the
    five outbound credentials — stealing it mints credits by forging settlements at our own
    gateway rather than spending our money at a vendor — which is the argument for a fourth
    process holding it, recorded in full at ``hbd.config.FOREIGN_SECRET_ENV_VARS``.

    A function rather than a pair of expressions because ``test_error_envelope.py``'s
    ``test_the_forbidden_list_is_derived_rather_than_restated`` calls it: one place to read
    from cannot drift from itself, whereas a test that restated the derivation would keep
    passing while the two spellings diverged. Never restate this list anywhere.
    """
    return tuple(f"{ENV_PREFIX}{name.upper()}" for name in VENDOR_SECRET_FIELDS) + (
        FOREIGN_SECRET_ENV_VARS
    )


#: Evaluated once at import: both tuples it reads are module constants, so this is a spelling
#: of them and not a decision made at boot time.
FORBIDDEN_ENV_VARS: Final[tuple[str, ...]] = derive_forbidden_env_vars()

_DISABLED_MESSAGE: Final[str] = (
    "The admin panel is disabled. Set HBD_ADMIN_ENABLED=true in .env.admin to run it."
)

#: Where ``admin-ui``'s ``vite build`` writes (``build.outDir`` in ``admin-ui/vite.config.ts``).
#: Gitignored source-side and force-included in the wheel through
#: ``[tool.hatch.build.targets.wheel] artifacts``, because a committed bundle drifts from the
#: TypeScript it was built from with nothing to notice.
STATIC_DIR: Final[Path] = Path(__file__).resolve().parent / "static"

#: The SPA shell. A one-substitution template rather than a static file: it carries this
#: response's style nonce so the bundle can hand it to the libraries that inject a ``<style>``
#: element at runtime. See :mod:`hbd.admin.shell` for why that is not optional and why the
#: nonce reaches the client through a meta element rather than an inline script.
SPA_INDEX: Final[Path] = STATIC_DIR / "index.html"

#: The catch-all's route template. Named so it is recognisable in a log line, and a plain
#: Starlette ``Route`` rather than an ``APIRoute`` on purpose — see ``_mount_spa``.
_SPA_ROUTE_TEMPLATE: Final[str] = "/{spa_path:path}"


def _admin_env_file() -> str:
    """The dotenv file this process actually reads — ``.env.admin`` or ``HBD_ADMIN_ENV_FILE``.

    Resolved here rather than imported as a value because the scan below is a security
    control: it has to read the SAME file ``build_admin_settings`` read, or it clears a host
    whose credentials are sitting in the file that was loaded. The module global is read at
    call time so a test that monkeypatches ``ADMIN_ENV_FILE`` redirects the scan with it.
    """
    return resolve_env_file(ADMIN_ENV_FILE_VAR, ADMIN_ENV_FILE)


def _env_file_names() -> frozenset[str]:
    """The variable NAMES set in the admin dotenv file, upper-cased. Values never returned.

    Parsed with the same library pydantic-settings uses to read this file, so the two agree
    on what "set" means, and upper-cased because that read is case-insensitive: a lowercase
    ``hbd_llm_api_key`` line is just as live as the shouted form.
    """
    path = _admin_env_file()
    try:
        parsed = dotenv_values(path)
    except OSError as exc:
        # Not swallowed. The file is unreadable rather than absent, so the check below is
        # weaker than it looks and an operator has to be told which half ran.
        _LOGGER.warning(
            "could not read the admin env file; the vendor-credential check saw the "
            "process environment only",
            extra={"event": "admin.boot.env_file_unreadable", "path": path},
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
            f"are within reach of it — in its environment or in {_admin_env_file()}: {listed}. "
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


async def _serve_spa_index(request: Request) -> Response:
    """Serve the SPA shell for a browser URL, and refuse to serve it for anything else.

    This is the catch-all, so it is also the last thing standing between an unknown path and
    a wrong answer. Two refusals matter more than the success case.

    **An unknown ``/api`` path must stay a JSON 404.** Without this check the catch-all would
    hand an HTML document to a JSON client for every typo'd endpoint — a 200 where a 404
    belongs, and a caller that parses it gets a syntax error instead of ``NOT_FOUND``.
    ``tests/test_admin/test_asgi_smoke.py`` asserts the envelope for ``/api/nothing-here``.
    Raising ``HTTPException`` routes through ``install_error_handlers`` and produces exactly
    that envelope, correlation id and all.

    **A missing bundle must 404, not 500.** ``src/hbd/admin/static/`` is gitignored, so in a
    checkout where nobody has run ``make ui-build`` it simply is not there — and the API is
    perfectly usable in that state (that is how every test in this suite runs). An unbuilt
    console answers 404; it does not take the process down.

    And one success-case detail: the body is **rendered per response**, not streamed off
    disk, because it carries this response's style nonce (:mod:`hbd.admin.shell`). That is
    why this is an ``HTMLResponse`` and not a ``FileResponse`` — a ``FileResponse``'s
    ``ETag``/``Last-Modified`` would advertise a body that is different on every request as
    revalidatable, which is the one caching shape a per-response nonce cannot survive.
    """
    path = request.url.path
    if path == API_PREFIX or path.startswith(f"{API_PREFIX}/"):
        raise HTTPException(status_code=404)
    if not SPA_INDEX.is_file():
        raise HTTPException(status_code=404)
    # Read off the scope rather than ``request.state`` so a shell served by an application
    # assembled without SecurityHeadersMiddleware renders an empty nonce instead of raising.
    # An empty nonce is the honest answer there: that response carries no CSP either.
    state: dict[str, object] = request.scope.get("state") or {}
    nonce = state.get(STYLE_NONCE_STATE_KEY, "")
    # ``Cache-Control`` is set for us: SecurityHeadersMiddleware stamps ``no-store`` on
    # everything outside IMMUTABLE_PATH_PREFIX, and the shell is deliberately outside it —
    # it is the one file whose name never changes, so caching it would pin the operator to
    # an old bundle across a deploy.
    return HTMLResponse(render_shell(SPA_INDEX.read_text(encoding="utf-8"), str(nonce)))


def _mount_spa(application: FastAPI) -> None:
    """Mount the built SPA: hashed assets under ``/assets``, the shell everywhere else.

    Called from the **lifespan**, not from ``create_app``, and that is the load-bearing
    detail. A catch-all shadows every route registered after it, because Starlette matches in
    registration order — so installing it inside ``create_app`` would silently swallow any
    route a caller adds to the returned application. That is not hypothetical: several tests
    in this package do exactly that (``@application.get(BOOM_PATH)`` in
    ``test_error_envelope.py``), and a future ``include_router`` after the factory would
    behave the same way, 404ing with no error anywhere. Deferring to startup means the
    fallback is installed once everything else has finished claiming its paths, whoever
    added them and whenever.

    It is idempotent, because a lifespan may be entered more than once on one application and
    a second copy of the catch-all would be dead weight the router still walks.

    The rest uses Starlette primitives rather than FastAPI ones, which is what keeps it
    invisible to the API's own contract:

    * ``StaticFiles`` is a ``Mount`` and the catch-all is a plain ``Route``. Neither is an
      ``APIRoute``, so neither appears in ``tests/test_admin/conftest.py``'s ``api_routes``
      and neither can widen §12.1 T8's frozen route table. The enumeration test asserts the
      served set equals ``MOUNTED_ROUTES`` **in both directions**; an ``@app.get("/{path}")``
      here would fail it, and rightly — a catch-all is not an endpoint.
    * The catch-all accepts ``GET`` only. Starlette answers a method it has no full match for
      out of the first PARTIAL match it found, which is the real route registered earlier, so
      ``POST /healthz`` is still a 405 rather than being swallowed here.
    * ``check_dir=False`` because the directory legitimately does not exist until
      ``make ui-build`` has run; ``StaticFiles`` then 404s per request instead of refusing to
      construct the application at import time.

    Route ORDER is the whole mechanism: Starlette matches in registration order, so every API
    template wins before the catch-all is consulted, and ``/assets/...`` is claimed by the
    mount before the catch-all sees it.
    """
    if any(getattr(route, "name", None) == "spa-index" for route in application.routes):
        return
    # A ``Mount`` STRIPS its own prefix before handing the rest to the sub-application, so
    # the directory is ``static/assets`` and not ``static``: mounting ``static`` here would
    # look right and resolve ``/assets/index-abc.js`` to ``static/index-abc.js``, which is a
    # 404 for every chunk in the bundle. It also, less obviously, keeps ``index.html`` out of
    # reach of the static handler, so the shell has exactly one way to be served — the one
    # that sets ``no-store``.
    assets_prefix = IMMUTABLE_PATH_PREFIX.strip("/")
    application.mount(
        f"/{assets_prefix}",
        StaticFiles(directory=STATIC_DIR / assets_prefix, check_dir=False),
        name="spa-assets",
    )
    application.router.routes.append(
        Route(_SPA_ROUTE_TEMPLATE, endpoint=_serve_spa_index, methods=["GET"], name="spa-index")
    )


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
        # Last, so the catch-all cannot shadow a route somebody registered after the factory.
        _mount_spa(application)
        _LOGGER.info(
            "admin api started",
            extra={
                "event": "admin.boot.ok",
                "environment": settings.environment,
                # Which file this came from, for the same reason ``verify_host`` logs it:
                # HBD_ADMIN_ENV_FILE can boot a prod panel from a dev checkout.
                "env_file": _admin_env_file(),
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
    #
    # Order is not semantic: no route here is a literal sibling of another's ``{param}``
    # segment, so no template can shadow another however they are ordered. The list is
    # grouped to read like §11.2's left rail. ``tests/test_admin/test_routes_enumeration.py``
    # asserts the full table, so a router that is written but never included fails there
    # rather than being discovered by an operator hitting a 404.
    application.include_router(build_health_router())
    application.include_router(build_login_router())
    application.include_router(build_auth_router())
    application.include_router(build_audit_router())
    application.include_router(build_retention_router())
    application.include_router(build_dashboard_router())
    # ``dashboard.py`` ships two routers, and the split is the control rather than a
    # filing choice: ``/dashboard/audience-lists`` returns the ACCOUNT HOLDER's Telegram
    # id, handle and first name unmasked and stands on RECORDS_READ with an audit row on
    # every call, while the six aggregate routes beside it carry no personal data at all
    # and need no masking branch. The guard is per-router (§12.1 T3), so each needs its
    # own line — and mounting only the first would drop the identified route silently.
    application.include_router(build_audience_lists_router())
    application.include_router(build_orders_router())
    application.include_router(build_users_router())
    application.include_router(build_chats_router())
    # ``users.py`` ships three routers: the wizard-state projection sits behind
    # WIZARD_STATE_READ rather than RECORDS_READ, and block/unblock behind the role half of
    # §12.2's ``W+S`` cell. The guard is per-router (§12.1 T3), so each needs its own line.
    application.include_router(build_wizard_state_router())
    application.include_router(build_user_block_router())
    # ``credits.py`` splits the same way: the ledger is an ordinary record read and the grant
    # issues value, so they cannot share a guard.
    application.include_router(build_credits_router())
    application.include_router(build_credit_grant_router())
    application.include_router(build_generations_router())
    # Vendor spend. Its own router rather than three more routes on ``dashboard.py``: the
    # two share a guard and nothing else — that module reads ``orders`` and
    # ``generation_attempts`` and refuses to print a cost figure from either, and this one
    # reads a table built so it can.
    application.include_router(build_vendors_router())
    application.include_router(build_assets_router())
    # ``assets.py`` ships two routers for the same reason ``users.py`` does: the two media
    # reveals stand on the REVEAL_MEDIA_READ cell, not on RECORDS_READ, and the guard is
    # per-router (§12.1 T3).
    application.include_router(build_asset_media_router())
    # The one path by which masked data becomes plaintext (§12.2). Its router guard
    # decides the role and its handler decides the subject-scoped step-up; see
    # ``routers/reveal.py`` for why an ``A+S`` cell cannot be enforced at the router.
    application.include_router(build_reveal_router())
    # ``segments.py`` ships two routers, and the split is a permission rather than a filing
    # choice: the audience PREVIEW counts the same population ``/users`` pages and stands on
    # RECORDS_READ beside it, while the field REGISTRY is the broadcast builder's vocabulary
    # and stands on BROADCAST_READ. The guard is per-router (§12.1 T3), so each needs its own
    # line — and mounting only one would drop the other with no error anywhere.
    application.include_router(build_segments_router())
    application.include_router(build_segment_fields_router())
    # ``broadcasts.py`` ships two routers, and the split is §12.2's ``W+S`` row rather than a
    # filing choice: reading a campaign is BROADCAST_READ (M in all four cells — the record
    # holds operator copy and counters, no customer data), while composing, sending, pausing
    # and cancelling stand on BROADCAST_WRITE, the ROLE half whose step-up the send handlers
    # enforce on the campaign id. The guard is per-router (§12.1 T3), so each needs its own
    # line — and mounting only the read one would leave the campaign screen unable to act.
    application.include_router(build_broadcasts_router())
    application.include_router(build_broadcast_actions_router())
    application.include_router(build_admins_router())
    application.include_router(build_config_router())
    # The SPA's catch-all is NOT added here. It is installed by the lifespan, after everything
    # else — including anything a caller adds to the application this returns — has claimed
    # its paths. See ``_mount_spa``.
    return application


#: The uvicorn entry point (``make admin``). Constructing it reads nothing.
app: Final[FastAPI] = create_app()
