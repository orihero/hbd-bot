"""Request-scoped dependencies: the container, a transaction, and who is asking.

The one rule that shapes this module is §12.1 T9: **``role``, ``is_active`` and
``password_changed_at`` are read from ``admin_users`` on every request.** Not from the
session row, not from the cookie, not from the Redis mirror. A cached role is a privilege
bug with a TTL — a demotion that takes effect in a minute is a minute of an operator holding
permissions somebody already removed — and a cached ``is_active`` is worse, because
deactivation is the hard stop every other control assumes works instantly.

``admin_sessions.revoked_at`` is read on every request for the same reason and in the same
statement: :func:`hbd.db.admin.accounts.get_for_live_session` joins the two tables, so a
revocation written by anything at all — ``sessions.revoke_session``, a future sweep, another
admin's "revoke that session", a hand-written ``UPDATE`` — is refused on the next request
rather than after the mirror's minute. The join adds no round trip, because the operator row
had to be read anyway.

The Redis mirror (:mod:`hbd.admin.sessions`) therefore holds only the session row, and even
that is re-checked against both clocks and its own ``revoked_at`` on every hit. What it saves
is one indexed ``SELECT`` per request; what it can never do is grant something the database
would refuse.

The order in :func:`get_current_admin` is deliberate and each step depends on the one above:
authenticate the token, load the operator behind an unrevoked session, refuse a dead account,
refuse a session older than the password, check CSRF against the **stored** token, then the
forced-rotation gate. CSRF comes after authentication because a CSRF verdict on an
unauthenticated request would tell an attacker whether their stolen cookie is live.

Everything up to and including the database read is :func:`_authenticate`, which **writes
nothing**. :func:`has_live_session` is that much and no more, so ``/readyz`` can ask whether
a caller is signed in without a GET route advancing ``last_seen_at`` (§12.1 T8).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.routing import Route

from hbd.admin.container import AdminContainer
from hbd.admin.csrf import SESSION_COOKIE_NAME, CsrfDecision, verify_csrf_request
from hbd.admin.errors import AdminErrorCode, AdminProblem, ProblemError, problem
from hbd.admin.security.budget import (
    RevealBudgetDecision,
    RevealBudgetLimits,
    RevealBudgetOutcome,
    charge_reveal_budget,
)
from hbd.admin.security.clientip import resolve_client_ip
from hbd.admin.security.permissions import (
    AccessDecision,
    Permission,
    StepUpAction,
    StepUpGrant,
    check_role,
    max_age_for_action,
    require_step_up,
    step_up_from_session,
)
from hbd.admin.security.tokens import sha256_hex
from hbd.admin.sessions import SessionSnapshot, invalidate_mirror, resolve_session, touch_session
from hbd.admin.settings import AdminSettings
from hbd.db.admin import accounts
from hbd.db.base import utc_now
from hbd.db.enums import AdminRole, AuditAction
from hbd.db.models.admin_audit import AuditOutcome
from hbd.db.models.admin_user import AdminUserRow
from hbd.errors import ErrorCode
from hbd.logging import get_logger

__all__ = [
    "ACCESS_ERROR_CODES",
    "API_PREFIX",
    "AUTH_PREFIX",
    "PASSWORD_GATE_EXEMPT_PATHS",
    "CurrentAdmin",
    "RequirePermission",
    "enforce_reveal_budget",
    "enforce_step_up",
    "get_container",
    "get_admin_settings",
    "get_db_session",
    "get_redis",
    "get_current_admin",
    "has_live_session",
    "require_permission",
    "resolve_request_ip",
    "reveal_budget_limits",
    "Container",
    "Settings",
    "Db",
    "RedisClient",
]

_LOGGER: Final = get_logger(__name__)

#: The API's path vocabulary lives here, beside the gate that reads it. Routers declare
#: **full** paths and are included without a prefix: FastAPI nests an included router rather
#: than rewriting its routes, so ``scope["route"].path`` is the router-relative path when a
#: prefix is used — and a gate that compares a relative path against an absolute one is a
#: gate that silently opens.
API_PREFIX: Final[str] = "/api"
AUTH_PREFIX: Final[str] = f"{API_PREFIX}/auth"

#: The two routes an operator may reach while ``must_change_password`` is true. Everything
#: else is 403 (§12.6): the account was created with a password somebody else chose, so it
#: is a credential to rotate rather than one to work with. ``/auth/me`` is here because the
#: SPA has to be able to read ``mustChangePassword`` to render the rotation screen at all,
#: and ``/auth/logout`` deliberately is **not**: dropping the cookie needs no route.
PASSWORD_GATE_EXEMPT_PATHS: Final[frozenset[str]] = frozenset(
    {f"{AUTH_PREFIX}/password", f"{AUTH_PREFIX}/me"}
)

_UNAUTHENTICATED_MESSAGE: Final[str] = "sign in to continue"


# ---------------------------------------------------------------------------
# Process-scoped resources, reached through the app rather than a module global
# ---------------------------------------------------------------------------
def get_container(request: Request) -> AdminContainer:
    """The container the lifespan built. A missing one is a wiring bug, not a request error."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise RuntimeError("admin container is not on app.state; the lifespan did not run")
    if not isinstance(container, AdminContainer):
        raise TypeError(f"app.state.container is a {type(container).__name__}, not a container")
    return container


Container = Annotated[AdminContainer, Depends(get_container)]


def get_admin_settings(container: Container) -> AdminSettings:
    return container.settings


Settings = Annotated[AdminSettings, Depends(get_admin_settings)]


async def get_db_session(container: Container) -> AsyncIterator[AsyncSession]:
    """One transaction per request: commit on a clean exit, roll back on any exception.

    ``session_factory.begin()`` is the same shape the repositories use. A login that writes a
    session row and then fails on its audit entry must leave neither, so the boundary is the
    request rather than the statement.
    """
    async with container.session_factory.begin() as session:
        yield session


Db = Annotated[AsyncSession, Depends(get_db_session)]


def get_redis(container: Container) -> Redis[str]:
    return container.redis


RedisClient = Annotated["Redis[str]", Depends(get_redis)]


# ---------------------------------------------------------------------------
# Who is asking
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CurrentAdmin:
    """The authenticated operator, assembled fresh from the database on every request."""

    admin_user_id: UUID
    username: str
    role: AdminRole
    must_change_password: bool
    last_login_at: datetime | None
    session: SessionSnapshot
    token_sha256: str
    client_ip: str | None

    @property
    def step_up(self) -> StepUpGrant | None:
        """The session's step-up grant, or ``None`` when half of it is missing."""
        return step_up_from_session(self.session.step_up_scope, self.session.step_up_at)


def resolve_request_ip(request: Request, container: AdminContainer) -> str | None:
    """The address to rate-limit and to record (§12.1 T13).

    ``X-Forwarded-For`` is read only when the transport peer is inside the configured CIDRs,
    and even then only the entry the configured number of hops from the right.
    """
    peer = request.client.host if request.client is not None else None
    return resolve_client_ip(
        peer_ip=peer,
        forwarded_for=request.headers.get("x-forwarded-for"),
        trusted_proxies=container.trusted_proxies,
        hops=container.settings.admin_trusted_proxy_hops,
    )


def _unauthenticated() -> ProblemError:
    return problem(AdminErrorCode.UNAUTHENTICATED, _UNAUTHENTICATED_MESSAGE)


_CSRF_CODES: Final[dict[CsrfDecision, AdminErrorCode]] = {
    CsrfDecision.ORIGIN_MISSING: AdminErrorCode.ORIGIN_REJECTED,
    CsrfDecision.ORIGIN_MISMATCH: AdminErrorCode.ORIGIN_REJECTED,
    CsrfDecision.TOKEN_MISSING: AdminErrorCode.CSRF_REJECTED,
    CsrfDecision.SESSION_TOKEN_MISSING: AdminErrorCode.CSRF_REJECTED,
    CsrfDecision.TOKEN_MISMATCH: AdminErrorCode.CSRF_REJECTED,
}


def enforce_csrf(request: Request, *, stored_token: str | None, expected_origin: str) -> None:
    """Raise unless every CSRF layer passes. Safe methods return without inspecting anything."""
    decision = verify_csrf_request(
        method=request.method,
        origin=request.headers.get("origin"),
        expected_origin=expected_origin,
        header_token=request.headers.get("x-csrf-token"),
        stored_token=stored_token,
    )
    if decision is CsrfDecision.ALLOWED:
        return
    _LOGGER.warning(
        "admin request refused by the CSRF check",
        extra={
            "event": "admin.csrf.refused",
            "reason": str(decision),
            "method": request.method,
        },
    )
    raise problem(_CSRF_CODES[decision], "this request could not be verified as yours")


def _route_path(request: Request) -> str | None:
    route = request.scope.get("route")
    return route.path if isinstance(route, Route) else None


def _enforce_password_rotation(request: Request, *, must_change_password: bool) -> None:
    """Everything but the rotation screen is closed until the given password is replaced.

    The path comes from the **matched route**, not from the raw URL, so a trailing slash, a
    dot segment or a percent-encoded variant cannot walk past the exempt set.
    """
    if not must_change_password:
        return
    path = _route_path(request)
    if path is not None and path in PASSWORD_GATE_EXEMPT_PATHS:
        return
    raise problem(
        AdminErrorCode.FORBIDDEN,
        "change your password before using the panel",
        reason="password_change_required",
    )


@dataclass(frozen=True, slots=True)
class _Authenticated:
    """What the token proved: a live session, the operator behind it, and the digest."""

    snapshot: SessionSnapshot
    user: AdminUserRow
    token_sha256: str


async def _authenticate(
    request: Request, db: Db, container: Container, *, now: datetime
) -> _Authenticated:
    """Prove the cookie, **reading only**. Raises 401 for every reason it cannot.

    Split out of :func:`get_current_admin` because two callers need exactly this much and no
    more: the dependency, which goes on to CSRF, the rotation gate and the ``last_seen_at``
    write, and :func:`has_live_session`, which must not write at all (§12.1 T8 — no GET
    changes state).

    ``accounts.get_for_live_session`` joins ``admin_sessions``, so ``role``, ``is_active``,
    ``password_changed_at`` **and** ``revoked_at`` are all read from the database on every
    request in one ``SELECT``. That is what makes a revocation written past
    ``sessions.revoke_session`` — a sweep, another admin's revoke, a hand-written
    ``UPDATE`` — take effect immediately rather than when the Redis mirror expires.
    """
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        raise _unauthenticated()
    digest = sha256_hex(raw_token)
    snapshot = await resolve_session(
        db,
        container.redis,
        token_sha256=digest,
        now=now,
        idle_ttl_s=container.settings.admin_session_idle_ttl_s,
    )
    if snapshot is None:
        raise _unauthenticated()
    user = await accounts.get_for_live_session(
        db, admin_user_id=snapshot.admin_user_id, admin_session_id=snapshot.session_id
    )
    if user is None or not user.is_active or user.password_changed_at > snapshot.created_at:
        # A revocation, a deactivation or a password change lands on the next request even
        # with the mirror warm, because all four facts come from the row. The mirror goes
        # with it rather than being left to time out.
        await invalidate_mirror(container.redis, digest)
        raise _unauthenticated()
    return _Authenticated(snapshot=snapshot, user=user, token_sha256=digest)


async def get_current_admin(request: Request, db: Db, container: Container) -> CurrentAdmin:
    """Authenticate the request and load the operator. Raises rather than returning ``None``.

    Every failure answers 401 with the same body and the same code: an attacker holding a
    cookie must not learn whether it was ever valid, whether it was revoked, whether the
    account was deactivated, or whether the password moved underneath it.
    """
    now = utc_now()
    proven = await _authenticate(request, db, container, now=now)
    snapshot, user = proven.snapshot, proven.user
    settings = container.settings
    enforce_csrf(
        request, stored_token=snapshot.csrf_token, expected_origin=settings.admin_public_origin
    )
    _enforce_password_rotation(request, must_change_password=user.must_change_password)
    client_ip = resolve_request_ip(request, container)
    await touch_session(
        db,
        container.redis,
        snapshot=snapshot,
        token_sha256=proven.token_sha256,
        now=now,
        ip=client_ip,
        idle_ttl_s=settings.admin_session_idle_ttl_s,
    )
    return CurrentAdmin(
        admin_user_id=user.id,
        username=user.username,
        role=user.role,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
        session=snapshot,
        token_sha256=proven.token_sha256,
        client_ip=client_ip,
    )


async def has_live_session(request: Request, container: AdminContainer) -> bool:
    """Whether this request carries a usable session — **without writing anything**.

    ``/readyz`` is a GET, and :func:`get_current_admin` advances ``last_seen_at``, so asking
    it this question turned a readiness probe into a write. Slice 1c's route-enumeration test
    asserts that no GET route changes state (§12.1 T8, which is also what makes
    ``SameSite=Lax`` safe), and a special case for one route is not an answer.

    CSRF and the forced-rotation gate are deliberately skipped: a probe is a safe method, and
    an operator who still owes a password change is signed in for the purpose of "may this
    caller see the fleet detail". The refusal is converted to ``False`` rather than
    swallowed — this is the one call site where "not signed in" is an expected answer.
    """
    async with container.session_factory.begin() as db:
        try:
            await _authenticate(request, db, container, now=utc_now())
        except ProblemError:
            return False
        return True


Admin = Annotated[CurrentAdmin, Depends(get_current_admin)]


# ---------------------------------------------------------------------------
# The permission guard, as a dependency
# ---------------------------------------------------------------------------
#: §6.2's decision → code table, public because the router-level guard is no longer its only
#: reader: :func:`enforce_step_up` maps the same three step-up decisions, and a second copy
#: of this table is a second answer to "what does a scope mismatch look like on the wire".
ACCESS_ERROR_CODES: Final[dict[AccessDecision, AdminErrorCode]] = {
    AccessDecision.FORBIDDEN_ROLE: AdminErrorCode.FORBIDDEN,
    AccessDecision.STEP_UP_REQUIRED: AdminErrorCode.STEP_UP_REQUIRED,
    AccessDecision.STEP_UP_SCOPE_MISMATCH: AdminErrorCode.STEP_UP_REQUIRED,
    AccessDecision.STEP_UP_EXPIRED: AdminErrorCode.STEP_UP_REQUIRED,
}


@dataclass(frozen=True, slots=True)
class RequirePermission:
    """The router-level guard. Carries ``permission`` so a route can be enumerated.

    Applied with ``APIRouter(dependencies=[Depends(require_permission(...))])`` — never per
    handler, because a per-handler guard is a guard somebody forgets on the next route
    (§12.1 T3). The Slice 1c route-enumeration test reads this attribute off each builder's
    ``APIRouter.dependencies`` to assert every route outside the exempt set carries exactly
    one. It cannot read it off ``APIRoute.dependencies``: FastAPI copies a handler's own
    ``dependencies=`` into that list too, so the shape this class forbids would satisfy it.

    Subject-scoped step-up is **not** decided here: the subject is a path parameter and only
    the handler knows which one, so a route whose cell demands a step-up asks for it
    explicitly with ``require_step_up`` on the subject it is about to act on. That is why
    this calls :func:`check_role` and not :func:`check_access` — with no subject there is no
    grant to weigh, so there is no window to apply, and taking
    ``admin_step_up_grace_seconds`` as a dependency here would be wiring that decides
    nothing. The handler that does hold the subject reads the setting.
    """

    permission: Permission

    async def __call__(self, admin: Admin, container: Container) -> CurrentAdmin:
        decision = check_role(self.permission, admin.role)
        if decision is AccessDecision.ALLOWED:
            return admin
        # §12.6: a refusal is the audit row that matters most — it is the one a
        # "successes only" log would not have. Written in its own committed transaction
        # because this raises, and the request's transaction is about to roll back.
        from hbd.admin import audit_sink

        await audit_sink.record_refusal(
            container,
            audit_sink.auth_entry(
                AuditAction.PERMISSION_DENIED,
                username=admin.username,
                role=admin.role,
                outcome=AuditOutcome.DENIED,
                actor_id=admin.admin_user_id,
                error_code=str(ACCESS_ERROR_CODES[decision]),
                ip=admin.client_ip,
            ),
            now=utc_now(),
        )
        _LOGGER.warning(
            "admin request refused by the permission matrix",
            extra={
                "event": "admin.rbac.refused",
                "permission": str(self.permission),
                "role": str(admin.role),
                "reason": str(decision),
                "admin_username": admin.username,
            },
        )
        raise problem(
            ACCESS_ERROR_CODES[decision],
            "your role does not allow this",
            permission=str(self.permission),
        )


def require_permission(permission: Permission) -> RequirePermission:
    """Declare what a router needs. One call per router, at the router."""
    return RequirePermission(permission=permission)


# ---------------------------------------------------------------------------
# The handler-level guards: subject-scoped step-up, and the reveal budget
# ---------------------------------------------------------------------------
# Both live here rather than in :mod:`hbd.admin.security` for one reason: they need
# :class:`CurrentAdmin` and :class:`AdminContainer`, and ``security`` is imported *by*
# ``settings``, which the container is built from — so a guard that reached back for either
# would be a cycle. ``security`` keeps the pure decision (``check_step_up``,
# ``charge_reveal_budget``); this module is where a decision becomes a status code, exactly
# as :class:`RequirePermission` already is for the role half.
#
# They are called from inside a handler, not attached with ``Depends``. §12.1 T3's
# router-level rule is about the *permission*, and it is satisfied by
# :func:`require_permission`; the step-up is about a **subject**, and the subject is a path
# parameter or a body field that only the handler has read. ``deps.RequirePermission``
# answers ``STEP_UP_REQUIRED`` for any cell carrying a step-up precisely because it holds no
# subject — so a route on an ``A+S`` cell layers the two: the router guard decides the role,
# and one of these decides the scope.
async def enforce_step_up(
    admin: CurrentAdmin,
    container: AdminContainer,
    *,
    action: StepUpAction,
    subject_id: str,
    now: datetime,
) -> str:
    """Require a live step-up grant for ``action`` **on this subject**, or refuse.

    Returns the scope that was satisfied, so the caller can record it. Raises
    :class:`ProblemError` — ``STEP_UP_REQUIRED`` (403) when there is no grant, when the grant
    was obtained for a different action or a different subject, or when it has aged past the
    window; ``INVALID_INPUT`` (422) when the subject id could not have been stored as a scope
    in the first place, because that is a malformed request rather than a missing credential
    and answering 403 would send the SPA into a re-authentication loop it cannot win.

    ``action`` is typed :class:`StepUpAction` rather than ``str`` on purpose.
    ``require_step_up`` takes ``str``, so ``require_step_up("reveal.personal_data", …)``
    type-checks, builds a perfectly storable scope, and then never matches the grant
    ``/auth/step-up`` issued — ``StepUpRequest.scope`` is a ``StepUpAction`` and yields
    ``reveal``. That mismatch is a permanent, silent 403 that only a test driving the real
    route catches. The enum closes it here.

    ``subject_id`` must be **byte-identical** to the one the SPA sent to ``/auth/step-up``:
    the scope is compared whole (``check_step_up``), so ``str(uuid)`` — lowercase, unbraced —
    on one side and an uppercase or braced spelling on the other is a scope mismatch nobody
    can debug from the 403.

    The refusal is audited in its own committed transaction before this raises, because the
    request's transaction is about to roll back and §12.6's refusal row is the one a
    "successes only" log would not have. ``auth_entry`` records it under
    ``subject_type="admin"``, which is what the ``STEP_UP_SUCCESS`` and ``STEP_UP_FAILURE``
    rows written by ``/auth/step-up`` already do for the same subject id.
    """
    try:
        guard = require_step_up(str(action), subject_id)
    except ValueError as exc:
        raise ProblemError(
            AdminProblem(
                code=ErrorCode.INVALID_INPUT,
                message="that step-up subject is not a storable identifier",
            )
        ) from exc
    decision = guard(
        admin.step_up,
        now=now,
        max_age_s=max_age_for_action(
            action, grace_s=container.settings.admin_step_up_grace_seconds
        ),
    )
    if decision is AccessDecision.ALLOWED:
        return guard.scope

    from hbd.admin import audit_sink

    code = ACCESS_ERROR_CODES[decision]
    await audit_sink.record_refusal(
        container,
        audit_sink.auth_entry(
            AuditAction.PERMISSION_DENIED,
            username=admin.username,
            role=admin.role,
            outcome=AuditOutcome.DENIED,
            actor_id=admin.admin_user_id,
            subject_id=subject_id,
            error_code=str(code),
            ip=admin.client_ip,
        ),
        now=now,
    )
    _LOGGER.warning(
        "admin request refused for want of a scoped step-up",
        extra={
            "event": "admin.stepup.refused",
            "step_up_action": str(action),
            "reason": str(decision),
            "admin_username": admin.username,
        },
    )
    raise problem(
        code,
        "re-authenticate for this action and this subject",
        stepUpAction=str(action),
        subjectId=subject_id,
    )


def reveal_budget_limits(settings: AdminSettings) -> RevealBudgetLimits:
    """§12.3's two ceilings, as the operator configured them."""
    return RevealBudgetLimits(
        max_records_per_hour=settings.admin_reveal_records_per_hour,
        max_conversations_per_day=settings.admin_reveal_conversations_per_day,
    )


async def enforce_reveal_budget(
    admin: CurrentAdmin,
    container: AdminContainer,
    *,
    record_count: int,
    conversation_count: int = 0,
    now: datetime,
) -> RevealBudgetDecision:
    """Charge one reveal against §12.3's budgets, or refuse it.

    ``record_count`` is what the reveal is **authorised to return** — one for a name, a note
    or a lyric, and the page size for a conversation — and it is charged *before* the read,
    because a budget charged afterwards has already let the read happen. Pass
    ``conversation_count=1`` for a page of a transcript so the daily transcript ceiling is
    charged too; the two budgets are separately exhaustible by design.

    Raises :class:`ProblemError`: ``REVEAL_BUDGET_EXHAUSTED`` (429, with ``Retry-After``
    counting down to the refusing window's reset) when a ceiling is spent, and
    ``SERVICE_UNAVAILABLE`` (503) when the counter store cannot answer. The second is not the
    first: telling an operator their budget is spent for the hour that Redis is down would
    have them opening an incident against the wrong system, and the whole reason
    ``RevealBudgetOutcome`` has two refusal members is so this mapping can exist. A
    ``record_count`` outside ``1..MAX_RECORDS_PER_REVEAL`` is ``INVALID_INPUT`` (422) — the
    caller is expected to have validated its body, and this is the backstop.
    """
    try:
        decision = await charge_reveal_budget(
            container.rate_limits,
            username=admin.username,
            record_count=record_count,
            conversation_count=conversation_count,
            now=now,
            limits=reveal_budget_limits(container.settings),
        )
    except ValueError as exc:
        raise ProblemError(AdminProblem(code=ErrorCode.INVALID_INPUT, message=str(exc))) from exc
    if decision.is_allowed:
        return decision
    headers = {"Retry-After": str(decision.retry_after_s)}
    if decision.outcome is RevealBudgetOutcome.BACKEND_UNAVAILABLE:
        raise problem(
            AdminErrorCode.SERVICE_UNAVAILABLE,
            "the reveal budget cannot be checked right now; try again shortly",
            headers=headers,
        )
    raise problem(
        AdminErrorCode.REVEAL_BUDGET_EXHAUSTED,
        "this operator's reveal budget for the window is spent",
        headers=headers,
        budget=None if decision.scope is None else decision.scope.value,
        recordsRequested=decision.records_requested,
        recordsRemaining=decision.records_remaining,
        conversationsRemaining=decision.conversations_remaining,
    )
