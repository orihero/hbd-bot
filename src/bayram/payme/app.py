"""The gateway's ASGI application: three routes, four refusals, and one unbreakable rule.

**EVERY REPLY ON THE MERCHANT ENDPOINT IS HTTP 200.** Bad authentication, an unparseable body,
a malformed envelope, an unknown method and any unhandled exception all render
``{"jsonrpc": "2.0", "id": …, "error": {…}}`` at status 200. Payme reads any other status as
transport error ``-32400`` and retries — and a 500 costs us the ``id`` echo as well, which
turns their retry into a call nobody can match to the original. That is the whole reason this
endpoint is not a router on the admin app: ``bayram.admin.errors.install_error_handlers`` is
application-wide and answers 422, 405 and 500 with the panel's own
``{"error": {code, message, correlationId}}`` envelope, which Payme cannot read at all. This
module installs its OWN exception middleware and never reuses that one.

**Why this is a fourth process and not a route.** Four independent reasons, each sufficient:
``bayram/admin/app.py`` derives ``FORBIDDEN_ENV_VARS`` from a tuple this integration widens with
the merchant key, so a prod admin process would refuse to boot once the key was in reach;
``BAYRAM_ADMIN_ENABLED=false`` is the documented incident kill switch and refusing operator logins
is not the same incident as refusing money; the error envelope above; and
``tests/test_admin/test_routes_enumeration.py`` freezes ``EXEMPT_PATHS`` at three paths
precisely to stop an unauthenticated POST being added. It cannot live in the bot either:
``bayram-bot.service``'s own header is "Long polling, so it needs outbound HTTPS and nothing
inbound", and that process holds all four outbound credentials.

**The order of checks on ``POST /payme``, and why it is that order.**

1. Not a POST → ``-32300`` at 200. A route-level guard rather than FastAPI's 405, because a
   405 is a status Payme reads as a transport failure.
2. The caller allowlist, when one is configured at all — see :func:`_refuse_unknown_caller`.
3. Authorization → ``-32504``, logging the login that was PRESENTED and never the key.
4. The raw body is parsed HERE, by us → ``-32700``. The documented ``Content-Type`` is
   ``text/json; charset=UTF-8``, which FastAPI's body parser does not recognise as JSON; it
   would hand back an empty body and produce a 422 through the framework's own handler. Parsing
   ourselves is also what makes ``-32700`` ours to return rather than a 422 to explain.
5. The envelope → ``-32600``.
6. Everything else is :class:`bayram.payme.service.PaymeService`'s, including the unknown-method
   ``-32601``.

Authentication before parsing means a ``-32504`` carries ``id: null``: we have not read a body
from an unauthenticated caller, and we are not going to in order to improve an error message.
That is the one place the id echo is deliberately not honoured, and it is the safe direction.

**``bayram.runtime.startup.verify_host`` is deliberately NOT called.** It checks ffmpeg, the
locale catalogues and the workspace root. This process renders nothing, speaks no locale to a
customer and writes no files; running it would let a missing i18n string stop a payment
endpoint from booting, which is a strictly worse outcome than the one it prevents.

**``bayram.config.get_settings()`` is never called either.** That function is an
``lru_cache(maxsize=1)`` over a frozen model bound to a DIFFERENT dotenv. A second settings
model in the same interpreter must not touch it: the cache would hand whichever process asked
first its own answer forever, and here that would mean reading the bot's ``.env`` — the file
with the Telegram token in it — from the process that must never hold one.

``app`` is built at import so ``uvicorn bayram.payme.app:app`` works, and :func:`create_app`
therefore reads no configuration: settings are built inside the lifespan. Importing this module
must never fail on a missing environment variable, or a typo in ``/etc/bayram/payme.env`` becomes
an unimportable module instead of a message naming the variable.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from ipaddress import IPv6Address, ip_address, ip_network
from time import perf_counter
from typing import Any, Final

from dotenv import dotenv_values
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from bayram.config import ENV_PREFIX, VENDOR_SECRET_FIELDS, resolve_env_file
from bayram.db.engine import ping
from bayram.errors import ConfigError
from bayram.logging import configure_logging, get_logger
from bayram.payme.auth import presented_login, verify_basic
from bayram.payme.container import PaymeContainer, build_payme_container
from bayram.payme.protocol import PaymeErrorCode, RpcRequest, render_fault
from bayram.payme.settings import (
    PAYME_ENV_FILE,
    PAYME_ENV_FILE_VAR,
    PaymeSettings,
    build_payme_settings,
)

__all__ = [
    "FORBIDDEN_ENV_VARS",
    "PAYME_PATH",
    "HEALTH_PATH",
    "READY_PATH",
    "PROBE_TOKEN_HEADER",
    "AUTHORIZATION_HEADER",
    "FORWARDED_FOR_HEADER",
    "STATUS_OK",
    "STATUS_DEGRADED",
    "PUBLIC_STATUS",
    "UNPARSED_METHOD",
    "JsonRpcErrorMiddleware",
    "create_app",
    "app",
]

_LOGGER: Final = get_logger(__name__)

#: The one path Payme is given in the cabinet, and the only one this process serves POSTs on.
PAYME_PATH: Final[str] = "/payme"
HEALTH_PATH: Final[str] = "/healthz"
READY_PATH: Final[str] = "/readyz"

PROBE_TOKEN_HEADER: Final[str] = "X-Probe-Token"
AUTHORIZATION_HEADER: Final[str] = "Authorization"
FORWARDED_FOR_HEADER: Final[str] = "X-Forwarded-For"

STATUS_OK: Final[str] = "ok"
STATUS_DEGRADED: Final[str] = "degraded"
#: What every unauthenticated ``/readyz`` caller is told, whatever the deployment is doing.
#: Constant rather than merely short, for ``bayram.admin.routers.health``'s reason: "degraded" is
#: the same fleet telemetry as ``{"database": false}`` with fewer characters.
PUBLIC_STATUS: Final[str] = STATUS_OK

#: What a call that never got as far as a method name is journalled as. A body that did not
#: parse has no ``method``, and the row still has to exist — "Payme called and we refused them"
#: is the question the journal is asked most often.
UNPARSED_METHOD: Final[str] = "-"

#: The methods the merchant endpoint claims, so that a GET is answered by our own ``-32300``
#: rather than by Starlette's 405. Every one of them but POST is refused; the point is that the
#: refusal is a 200 with a JSON-RPC body.
_HANDLED_METHODS: Final[list[str]] = ["POST", "GET", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]

_POST: Final[str] = "POST"
_HTTP_SCOPE: Final[str] = "http"
_RESPONSE_START: Final[str] = "http.response.start"

#: ``BAYRAM_TELEGRAM_BOT_TOKEN``, ``BAYRAM_ELEVENLABS_API_KEY``, ``BAYRAM_LLM_API_KEY``,
#: ``BAYRAM_LLM_FALLBACK_API_KEY`` — the credentials that belong to ``bayram.config.Settings`` and
#: that THIS host must never hold either. Derived from ``bayram.config`` rather than restated, so
#: a fifth vendor credential added there is covered here without anyone remembering this file
#: exists. It is the mirror image of ``bayram.admin.app.FORBIDDEN_ENV_VARS`` and derives from the
#: same tuple deliberately: ``VENDOR_SECRET_FIELDS`` is "every credential a host that is not the
#: bot or the worker must never hold", while ``REQUIRED_VENDOR_SECRET_FIELDS`` is the narrower
#: "the bot cannot start without these" — using the second here would let the LLM failover key
#: sit on the one host with an inbound internet socket.
#:
#: ``BAYRAM_PAYME_MERCHANT_KEY`` is of course NOT on this list. This is the process that holds it;
#: the admin app's list is the one that gains it.
FORBIDDEN_ENV_VARS: Final[tuple[str, ...]] = tuple(
    f"{ENV_PREFIX}{name.upper()}" for name in VENDOR_SECRET_FIELDS
)

_DISABLED_MESSAGE: Final[str] = (
    "The Payme gateway is disabled. Set BAYRAM_PAYME_ENABLED=true in the file named by "
    "BAYRAM_PAYME_ENV_FILE to run it."
)


# ---------------------------------------------------------------------------
# The boot-time credential scan — the mirror image of bayram.admin.app's
# ---------------------------------------------------------------------------
def _payme_env_file() -> str:
    """The dotenv this process actually reads — ``.env.payme`` or ``BAYRAM_PAYME_ENV_FILE``.

    Resolved here rather than imported as a value because the scan below is a security control:
    it must read the SAME file ``build_payme_settings`` read, or it clears a host whose
    credentials are sitting in the file that was loaded. The module global is read at call time
    so a test that monkeypatches :data:`bayram.payme.settings.PAYME_ENV_FILE` redirects both.
    """
    return resolve_env_file(PAYME_ENV_FILE_VAR, PAYME_ENV_FILE)


def _env_file_names() -> frozenset[str]:
    """The variable NAMES set in the gateway's dotenv, upper-cased. Values never returned.

    Parsed with the same library pydantic-settings uses to read the file, so the two agree on
    what "set" means, and upper-cased because that read is case-insensitive: a lowercase
    ``bayram_telegram_bot_token`` line is just as live as the shouted form.
    """
    path = _payme_env_file()
    try:
        parsed = dotenv_values(path)
    except OSError as exc:
        # Not swallowed. The file is unreadable rather than absent, so the check below is
        # weaker than it looks and an operator has to be told which half of it ran.
        _LOGGER.warning(
            "could not read the payme env file; the credential check saw the process "
            "environment only",
            extra={"event": "payme.boot.env_file_unreadable", "path": path},
            exc_info=exc,
        )
        return frozenset()
    return frozenset(name.upper() for name, value in parsed.items() if value)


def _present_foreign_vars() -> tuple[str, ...]:
    """Which forbidden variables this host puts within reach. Names only, never values."""
    from_file = _env_file_names()
    return tuple(name for name in FORBIDDEN_ENV_VARS if os.environ.get(name) or name in from_file)


def _refuse_foreign_credentials(settings: PaymeSettings) -> None:
    """Refuse in prod, warn elsewhere. Either way the message names the variable.

    The gateway is reachable from the public internet and authenticates its callers with one
    shared secret. A Telegram token in this address space would mean a compromise here could
    message every customer in the fleet as the bot, in perpetuity; an ElevenLabs or LLM key
    would mean it could spend the vendor balance. Neither is anything the payment endpoint can
    do or needs to do, and the separation is only real if a deployment that breaks it stops.

    In dev it is a WARNING for ``bayram.admin.app``'s reason: a shared developer ``.env`` is
    normal, and a hard failure there pushes people to weaken the check where it matters.
    """
    present = _present_foreign_vars()
    if not present:
        return
    listed = ", ".join(present)
    if settings.is_production:
        raise ConfigError(
            "The Payme gateway must not hold a vendor credential or a bot token, and these "
            f"are within reach of it — in its environment or in {_payme_env_file()}: {listed}. "
            "Remove them from this host: it terminates an inbound internet endpoint and holds "
            "one inbound verification secret, and nothing more.",
            context={"variables": list(present)},
        )
    _LOGGER.warning(
        "vendor credentials are within reach of the payme gateway",
        extra={"event": "payme.boot.vendor_env_present", "variables": list(present)},
    )


def _refuse_disabled_gateway(settings: PaymeSettings) -> None:
    if not settings.payme_enabled:
        raise ConfigError(_DISABLED_MESSAGE, context={"environment": settings.environment})


def _refuse_a_blank_key(settings: PaymeSettings) -> None:
    """A second, independent check that the endpoint can authenticate somebody.

    ``PaymeSettings`` already refuses an empty key when the rail is enabled, so this looks
    redundant — and it is not, for two reasons. It catches a whitespace-only key, which the
    model's emptiness test accepts and which is what a botched paste into a dotenv actually
    produces. And it is belt-and-braces on the single control standing between the public
    internet and an unlimited credit mint, which is the same argument
    ``bayram-payme.service``'s ``InaccessiblePaths`` makes against the application-level check
    it duplicates.
    """
    if not settings.merchant_key.strip():
        raise ConfigError(
            f"{ENV_PREFIX}PAYME_MERCHANT_KEY is blank: every inbound call is authenticated by "
            "comparing the whole login:key pair against it, so the gateway would answer -32504 "
            "to Payme and to everybody else.",
            context={"environment": settings.environment},
        )


# ---------------------------------------------------------------------------
# Caller identification
# ---------------------------------------------------------------------------
def _normalised_ip(value: str | None) -> str | None:
    """One address in canonical form, or ``None``. Never raises.

    Tolerates the two forms proxies actually emit — ``203.0.113.7:443`` and
    ``[2001:db8::1]:443`` — and unwraps IPv4-mapped IPv6 so the same caller reads the same way
    over a v4 and a dual-stack socket. The same rules
    ``bayram.admin.security.clientip._parse_ip`` applies, restated in a dozen lines because
    :mod:`bayram.payme` may not import :mod:`bayram.admin`: they are different processes with
    different blast radii, and a shared import would be the first thread pulling that apart.
    """
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.startswith("["):
        candidate = candidate.partition("]")[0][1:]
    elif candidate.count(":") == 1:
        candidate = candidate.split(":", 1)[0]
    try:
        parsed = ip_address(candidate)
    except ValueError:
        return None
    if isinstance(parsed, IPv6Address) and parsed.ipv4_mapped is not None:
        return str(parsed.ipv4_mapped)
    return str(parsed)


#: A proxy chain deeper than this does not exist in this deployment; an attacker-supplied
#: 10 000-entry header does. Matches ``bayram.admin.security.clientip.MAX_FORWARDED_ENTRIES``.
_MAX_FORWARDED_ENTRIES: Final[int] = 32


def _peer_ip(request: Request, *, hops: int) -> str | None:
    """Who called, as this process can best tell. Journalled on every request.

    With ``hops == 0`` — the shipped configuration — the socket peer IS the answer and
    ``X-Forwarded-For`` is not read at all. That is not laziness: behind a terminator the peer
    is the terminator, so believing a header nobody declared a hop count for would let the
    caller name itself. Above zero, the entry ``hops`` places from the right is the one the
    outermost trusted proxy observed; everything further left was supplied by whoever spoke to
    it, which includes the client. A position that does not exist, or does not parse, falls
    back to the peer — an address that is wrong-but-ours beats one that is attacker-chosen.
    """
    client = request.client
    peer = _normalised_ip(client.host if client is not None else None)
    if hops <= 0:
        return peer
    forwarded = request.headers.get(FORWARDED_FOR_HEADER)
    if not forwarded:
        return peer
    entries = forwarded.split(",")[-_MAX_FORWARDED_ENTRIES:]
    index = len(entries) - hops
    if index < 0:
        return peer
    return _normalised_ip(entries[index]) or peer


def _refuse_unknown_caller(peer: str | None, settings: PaymeSettings) -> bool:
    """Whether this caller is outside a configured allowlist. **Off in every shipped config.**

    :attr:`bayram.payme.settings.PaymeSettings.allowed_networks` is empty unless an operator has
    set BOTH a CIDR list and a non-zero hop count, and the shipped configuration sets neither.
    The reason is stated in the plan and worth repeating where the code is: Payme originates
    from ``185.234.113.0/28``, and that range belongs in the TLS terminator's configuration.
    With zero hops this process sees the terminator's address on every request, so a filter
    here would match one address and either pass everything or refuse everything — a filter
    matching the wrong address is worse than no filter, because it looks like a control.

    Returns ``True`` when the call should be refused, so the caller reads as a guard.
    """
    networks = settings.allowed_networks
    if not networks:
        return False
    parsed = _normalised_ip(peer)
    if parsed is None:
        return True
    address = ip_address(parsed)
    return not any(address in ip_network(entry, strict=False) for entry in networks)


# ---------------------------------------------------------------------------
# The exception middleware — the rule this module exists to keep
# ---------------------------------------------------------------------------
class _StartWatch:
    """Remembers whether a response has begun. One bit, but it decides recoverability."""

    __slots__ = ("has_started",)

    def __init__(self) -> None:
        self.has_started = False

    def watching(self, send: Send) -> Send:
        async def send_watching(message: Message) -> None:
            if message["type"] == _RESPONSE_START:
                self.has_started = True
            await send(message)

        return send_watching


class JsonRpcErrorMiddleware:
    """Render any unhandled exception on the merchant path as ``-32400`` at HTTP 200.

    **Ours, and never ``bayram.admin.errors.install_error_handlers``.** That one is application
    wide and emits the panel's envelope; this one emits a JSON-RPC fault and touches nothing
    else. It is a middleware rather than ``add_exception_handler(Exception, …)`` for the reason
    ``bayram.admin.middleware.unhandled`` documents: Starlette routes that key to
    ``ServerErrorMiddleware``, which it installs outside every ``add_middleware`` layer, and a
    response rendered there is one nothing in this application observes.

    **Scoped to :data:`PAYME_PATH` on purpose.** An exception on ``/readyz`` must stay a 500: a
    readiness probe answered with ``200 {"error": …}`` reads as healthy to every monitor ever
    written, which would turn a broken gateway into a silent one. The 200 rule is a property of
    the rail's endpoint, not of the process.
    """

    __slots__ = ("_app",)

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != _HTTP_SCOPE or scope.get("path") != PAYME_PATH:
            await self._app(scope, receive, send)
            return
        started = _StartWatch()
        try:
            await self._app(scope, receive, started.watching(send))
        except Exception as exc:
            if started.has_started:
                # Bytes are already on the wire and a second ``http.response.start`` is a
                # protocol violation, so the only honest move is to let the server tear the
                # connection down. Never swallowed: it reaches ServerErrorMiddleware.
                raise
            _LOGGER.exception(
                "an inbound payme call raised",
                extra={"event": "payme.rpc.unhandled", "detail": repr(exc)},
            )
            # ``id: null``: the exception may have happened before anything was parsed, and
            # guessing an id we did not read would be worse than the honest null.
            await _rpc_response(
                render_fault(
                    PaymeErrorCode.INTERNAL, "internal error", request_id=None
                )
            )(scope, receive, send)


def _rpc_response(body: dict[str, object]) -> Response:
    """One JSON-RPC envelope as an HTTP 200. The only response builder on this path."""
    return JSONResponse(content=body, status_code=200)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def _integer_id(payload: object) -> int | None:
    """The ``id`` to echo on an envelope refusal, when the body parsed far enough to have one.

    ``bool`` is excluded: ``isinstance(True, int)`` is ``True``, and echoing ``true`` where an
    integer belongs would break the match on Payme's side more thoroughly than ``null`` does.
    """
    if not isinstance(payload, dict):
        return None
    value = payload.get("id")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _container_of(request: Request) -> PaymeContainer:
    """The container this application was started with.

    Raises ``AttributeError`` when the lifespan never ran, which the middleware above renders
    as ``-32400`` at 200 — the correct answer to "the process is not ready": a retryable
    transport-level failure, not a business refusal Payme would act on.
    """
    container: PaymeContainer = request.app.state.container
    return container


def _register_routes(application: FastAPI) -> None:
    """The three routes, and there are no others. Declared in one function so that is visible."""

    @application.api_route(PAYME_PATH, methods=_HANDLED_METHODS, include_in_schema=False)
    async def merchant_endpoint(request: Request) -> Response:
        """The Merchant API. See the module docstring for the order of checks."""
        started = perf_counter()
        container = _container_of(request)
        settings = container.settings
        service = container.service
        peer = _peer_ip(request, hops=settings.payme_trusted_proxy_hops)

        if request.method != _POST:
            # Not a 405: Payme reads any non-200 as a transport failure and retries it.
            #
            # It is journalled like every other refusal, and the write amplification that
            # implies was weighed rather than missed: a stranger's GET writes one ~100-byte row
            # bounded by the ninety-day sweep, while Payme's own sandbox opens with exactly
            # this kind of probe — so a journal that recorded only well-formed calls would be
            # silent about the first thing certification does. The endpoint is loopback-bound
            # behind a terminator that enforces the caller allowlist, which is what keeps the
            # write path off the open internet in the first place.
            body = render_fault(
                PaymeErrorCode.TRANSPORT, "the merchant endpoint accepts POST", request_id=None
            )
            await service.record_refusal(
                method=UNPARSED_METHOD,
                reply_code=int(PaymeErrorCode.TRANSPORT),
                peer_ip=peer,
                started=started,
            )
            return _rpc_response(body)

        if _refuse_unknown_caller(peer, settings):
            _LOGGER.warning(
                "an inbound payme call came from outside the configured allowlist",
                extra={"event": "payme.caller.refused", "peer_ip": peer},
            )
            await service.record_refusal(
                method=UNPARSED_METHOD,
                reply_code=int(PaymeErrorCode.UNAUTHORISED),
                peer_ip=peer,
                started=started,
            )
            return _rpc_response(_unauthorised(request_id=None))

        header = request.headers.get(AUTHORIZATION_HEADER)
        if not verify_basic(
            header, login=settings.payme_basic_login, key=settings.merchant_key
        ):
            # The RECEIVED login and never the key. The undocumented username is then learned
            # from the first sandbox call rather than from a support ticket, and the one secret
            # on this host stays out of a log file that has no retention clock.
            _LOGGER.warning(
                "an inbound payme call failed authentication",
                extra={
                    "event": "payme.auth.refused",
                    "presented_login": presented_login(header),
                    "peer_ip": peer,
                },
            )
            await service.record_refusal(
                method=UNPARSED_METHOD,
                reply_code=int(PaymeErrorCode.UNAUTHORISED),
                peer_ip=peer,
                started=started,
            )
            return _rpc_response(_unauthorised(request_id=None))

        raw = await request.body()
        try:
            payload: object = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            await service.record_refusal(
                method=UNPARSED_METHOD,
                reply_code=int(PaymeErrorCode.PARSE),
                peer_ip=peer,
                started=started,
            )
            return _rpc_response(
                render_fault(PaymeErrorCode.PARSE, "the body is not JSON", request_id=None)
            )

        try:
            parsed = RpcRequest.model_validate(payload)
        except ValueError:
            # ``jsonrpc`` may be present or absent — ``RpcRequest`` ignores extras, which is
            # what accepts both populations. What fails here is a missing or mistyped
            # ``method``/``params``/``id``, and the id is echoed when the body carried a usable
            # one, which is the whole reason it is dug out separately.
            await service.record_refusal(
                method=UNPARSED_METHOD,
                reply_code=int(PaymeErrorCode.ENVELOPE),
                peer_ip=peer,
                started=started,
            )
            return _rpc_response(
                render_fault(
                    PaymeErrorCode.ENVELOPE,
                    "method, params and id are required",
                    request_id=_integer_id(payload),
                )
            )

        body, _ = await service.dispatch(parsed, peer_ip=peer)
        return _rpc_response(body)

    @application.get(HEALTH_PATH, include_in_schema=False)
    async def healthz() -> Response:
        """Liveness. Bare 200, empty body, no container, no database, no Redis.

        It answers even if the lifespan never ran, which is the point: an orchestrator restarts
        a container whose liveness probe fails, so a probe that depended on Postgres would turn
        a database blip into a restart loop at the exact moment the database is struggling.
        """
        return Response(status_code=200)

    @application.get(READY_PATH)
    async def readyz(request: Request) -> dict[str, Any]:
        """Readiness. A constant word in public; the detail needs ``X-Probe-Token``.

        Gated for ``bayram.admin.routers.health``'s reason: an unauthenticated detailed body is
        fleet telemetry for anyone who can reach the port. An unauthenticated caller therefore
        also pings nothing, so this cannot be used to load the database either.
        """
        container = _container_of(request)
        if not _is_probe_authorised(request, container.settings):
            return {"status": PUBLIC_STATUS}
        is_db_ok = await ping(container.engine)
        is_redis_ok = await _redis_ok(container)
        return {
            "status": STATUS_OK if is_db_ok and is_redis_ok else STATUS_DEGRADED,
            "database": is_db_ok,
            "redis": is_redis_ok,
            "isSandbox": container.settings.payme_is_sandbox,
        }


def _unauthorised(*, request_id: int | None) -> dict[str, object]:
    """``-32504`` at HTTP 200. One builder, so the two callers cannot render it differently."""
    return render_fault(
        PaymeErrorCode.UNAUTHORISED, "authorisation failed", request_id=request_id
    )


def _is_probe_authorised(request: Request, settings: PaymeSettings) -> bool:
    """Constant-time match against ``payme_probe_token``. An empty setting authorises nobody."""
    configured = settings.payme_probe_token
    if not configured:
        return False
    presented = request.headers.get(PROBE_TOKEN_HEADER)
    if not presented or not presented.isascii():
        return False
    return secrets.compare_digest(presented, configured)


async def _redis_ok(container: PaymeContainer) -> bool:
    """True when Redis answers. Never raises — a probe that crashes reports nothing."""
    try:
        return bool(await container.redis.ping())
    except Exception as exc:
        _LOGGER.warning(
            "payme redis ping failed",
            extra={"event": "payme.health.redis_unreachable", "detail": repr(exc)},
        )
        return False


# ---------------------------------------------------------------------------
# Application assembly
# ---------------------------------------------------------------------------
def _resolve_settings(
    preset_settings: PaymeSettings | None, preset_container: PaymeContainer | None
) -> PaymeSettings:
    """The container's settings win, so an application can never run under two of them."""
    if preset_container is not None:
        return preset_container.settings
    return preset_settings or build_payme_settings()


def _lifespan_factory(
    preset_settings: PaymeSettings | None, preset_container: PaymeContainer | None
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Build the lifespan bound to whatever the caller pre-supplied. Called once per app."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        settings = _resolve_settings(preset_settings, preset_container)
        configure_logging(level=settings.log_level, is_json=not settings.is_debug)
        _refuse_disabled_gateway(settings)
        _refuse_a_blank_key(settings)
        _refuse_foreign_credentials(settings)
        container = preset_container or await build_payme_container(settings)
        application.state.settings = settings
        application.state.container = container
        _LOGGER.info(
            "payme gateway started",
            extra={
                "event": "payme.boot.ok",
                "environment": settings.environment,
                # Which file this came from, for the reason ``verify_host`` logs it:
                # BAYRAM_PAYME_ENV_FILE can boot a production gateway from a dev checkout.
                "env_file": _payme_env_file(),
                "merchant_id": settings.payme_merchant_id,
                "is_sandbox": settings.payme_is_sandbox,
                "account_field": settings.payme_account_field,
                "basic_login": settings.payme_basic_login,
                "duplicate_transaction_code": settings.payme_duplicate_transaction_code,
                # The LENGTH and never the value. The documentation says 36; the sandbox
                # TEST_KEY's length is unverified, so this is logged instead of asserted —
                # a truncated paste is then one line of the journal rather than a
                # certification slot spent on -32504.
                "merchant_key_length": len(settings.merchant_key),
            },
        )
        try:
            yield
        finally:
            # A container the caller handed in is the caller's to close; closing it here would
            # dispose a pool a test still needs for its assertions.
            if preset_container is None:
                await container.aclose()

    return lifespan


def create_app(
    settings: PaymeSettings | None = None, *, container: PaymeContainer | None = None
) -> FastAPI:
    """Build the application. Reads no configuration — the lifespan does that.

    ``container`` is the composition seam: a test hands in one built over in-memory SQLite with
    a placeholder key and owns its lifetime. Production passes neither argument.
    """
    application = FastAPI(
        title="Bayram Payme",
        version="1",
        lifespan=_lifespan_factory(settings, container),
        # No schema browser. There is exactly one caller of this API, it is a machine, and it
        # was given the specification by Payme rather than by us.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.add_middleware(JsonRpcErrorMiddleware)
    _register_routes(application)
    return application


#: The uvicorn entry point (``make payme``, ``bayram-payme.service``). Constructing it reads
#: nothing: a typo in the dotenv must be a message naming the variable, not an ImportError.
app: Final[FastAPI] = create_app()
