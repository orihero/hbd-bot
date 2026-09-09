"""The five authentication routes, and the order of operations that makes them safe.

**Login runs its checks in exactly this order, and each position is a control:**

1. ``Origin`` is matched against ``admin_public_origin``. Login is the one route that cannot
   compare a stored CSRF token — there is no session yet — so the origin check is the whole
   of §12.1 T8 here, and a missing ``Origin`` on a POST is a refusal.
2. The client IP is derived (§12.1 T13), because every limiter key depends on it and a
   spoofable one is no key at all.
3. The rate limiter runs **before** argon2. A limiter that runs after the hash is the
   CPU-exhaustion vector it was added to prevent: 64 MiB and ~50 ms per attempt, on an
   unauthenticated route.
4. The password is verified — always, including for a username that does not exist, against a
   dummy hash of matching cost, so "no such user" and "wrong password" cost the same and say
   the same thing. Skipping the call for an unknown account puts the enumeration oracle
   straight back.
5. Only then is a session issued, and any session the request arrived with is revoked first:
   a login that leaves the presented token valid is session fixation.

``/auth/password`` revokes **every** session the operator holds, mirrors included, and issues
a fresh one for the caller. It has to: ``set_password`` moves ``password_changed_at``, which
is what voids sessions issued before it, so without the rotation the operator would change
their password and immediately 401 themselves.

``/auth/step-up`` grants for one action **on one subject**, and re-verifies the password
rather than trusting the session — which is the only thing that makes a step-up mean anything
against a session that was already stolen.

**Both of those re-verify a password, so both are rate-limited too, and for the same two
reasons login is.** A session cookie is not an entitlement to unlimited argon2: unmetered,
``/auth/step-up`` and ``/auth/password`` are a password oracle for whoever stole the cookie —
against the very control that exists to survive that theft — and a 64 MiB, ~50 ms CPU sink
that anyone past the router guard can run in a loop. They are metered by
``check_reauth_rate_limit``, whose counters sit in their **own** key namespace rather than
sharing the login route's: a shared per-username ceiling would let a thief grinding
``/auth/step-up`` spend the login route's budget and lock the real operator out of signing in
to revoke, which is the denial of service §12.1 T1's split key was designed to avoid.

**That budget is per session, and a correct password is given back.** The strict counter used
to be ``(username, client_ip)``, which signing in again did not clear — so a new OWNER who
mistyped their own password thirty times was 429ed on ``/auth/password`` for the rest of the
window, and since ``must_change_password`` closes every other route, that is the whole panel.
It is now the session id, because minting a session costs the password and is therefore the
one thing the thief with the cookie cannot do; and because the reservation is refunded when
the verify succeeds, only *failures* accumulate. §12.1 T2 requires a step-up per reveal,
purge, force-deliver, block and config commit, so charging correct step-ups meant the control
fired hardest during exactly the incident it was meant to survive. The full argument, and the
numbers, are in ``security/ratelimit.py``.

**The order on those two routes, and why each position is where it is:**

1. The router-level ``require_permission`` guard has already authenticated the session and
   checked CSRF, so ``admin.username`` and ``admin.session`` are the account and the browser
   being re-verified — never a name from the body. A limiter keyed on an attacker-supplied
   username here would be a way to spend *someone else's* budget.
2. Step-up validates its subject id first (422). It performs no I/O and no hashing, so a
   malformed body is a client bug that should not spend an operator's re-auth budget.
3. The reservation is taken, keyed on the session and on the username, and refuses **before**
   the verify — an unmetered re-auth is the CPU-exhaustion vector one door over. The refusal
   is what keeps argon2 from running, so it cannot move after the hash however the accounting
   changes.
4. Only then ``_verified_account`` — and only once *that* has returned is the session's half
   of the reservation refunded, which is why the refund is written out at both call sites
   rather than hidden in a helper that could quietly refund a failure.

**Not done here, and deliberately:** ``verify_password`` reports ``needs_rehash`` when the
argon2 parameters have been raised, and this router does not act on it. The only write
primitive that exists is ``accounts.set_password``, which also clears
``must_change_password`` — silently un-forcing a rotation is a worse bug than a late
parameter bump, so the bump lands on the operator's next password change instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from hbd.admin import audit_sink
from hbd.admin.container import AdminContainer
from hbd.admin.csrf import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, CsrfDecision, verify_origin
from hbd.admin.deps import (
    AUTH_PREFIX,
    Admin,
    Container,
    CurrentAdmin,
    Db,
    require_permission,
    resolve_request_ip,
)
from hbd.admin.errors import AdminErrorCode, AdminProblem, ProblemError, problem
from hbd.admin.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    PasswordChangeRequest,
    StepUpRequest,
    StepUpResponse,
)
from hbd.admin.security.passwords import hash_password_async, verify_password_async
from hbd.admin.security.permissions import (
    Permission,
    build_step_up_scope,
    max_age_for_action,
)
from hbd.admin.security.ratelimit import (
    RateLimitDecision,
    RateLimitOutcome,
    RateLimitScope,
    check_login_rate_limit,
    check_reauth_rate_limit,
    is_first_login_refusal,
    refund_reauth_reservation,
)
from hbd.admin.security.tokens import sha256_hex
from hbd.admin.sessions import (
    IssuedSession,
    SessionSnapshot,
    grant_step_up,
    issue_session,
    resolve_session,
    revoke_session,
    revoke_sessions_for_user,
)
from hbd.admin.settings import AdminSettings
from hbd.db.admin import accounts
from hbd.db.base import utc_now
from hbd.db.enums import AdminRole, AuditAction
from hbd.db.models.admin_audit import AuditOutcome
from hbd.db.models.admin_user import AdminUserRow
from hbd.errors import ErrorCode
from hbd.logging import get_logger

__all__ = ["build_login_router", "build_auth_router"]

_LOGGER: Final = get_logger(__name__)

#: One message for every way a sign-in can fail. Distinguishing "no such account" from
#: "wrong password" from "deactivated" is an enumeration oracle in three flavours.
_REJECTED: Final[str] = "that username and password do not match an active account"
#: A re-check inside an authenticated flow. A 401 here would sign the operator out for
#: mistyping their own password, so it is a refusal of the action, not of the session.
_WRONG_CURRENT: Final[str] = "that is not your current password"
#: Truncated to ``admin_sessions.user_agent``'s ``String(256)``; it is diagnostic context.
_MAX_USER_AGENT_CHARS: Final[int] = 256
_NO_CONTENT: Final[int] = 204


@dataclass(frozen=True, slots=True)
class _Presented:
    """Whatever session the request arrived carrying, resolved once."""

    digest: str | None
    snapshot: SessionSnapshot | None


async def _presented_session(
    request: Request, db: AsyncSession, container: AdminContainer, *, now: datetime
) -> _Presented:
    """The caller's existing session, if any. Never raises — an absent cookie is normal."""
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw:
        return _Presented(digest=None, snapshot=None)
    digest = sha256_hex(raw)
    snapshot = await resolve_session(
        db,
        container.redis,
        token_sha256=digest,
        now=now,
        idle_ttl_s=container.settings.admin_session_idle_ttl_s,
    )
    return _Presented(digest=digest, snapshot=snapshot)


def _enforce_origin(request: Request, settings: AdminSettings) -> None:
    """The only CSRF layer available before a session exists."""
    decision = verify_origin(
        request.headers.get("origin"), accepted_origins=settings.accepted_origins
    )
    if decision is CsrfDecision.ALLOWED:
        return
    _LOGGER.warning(
        "admin login refused by the origin check",
        extra={"event": "admin.login.origin_refused", "reason": str(decision)},
    )
    raise problem(AdminErrorCode.ORIGIN_REJECTED, "this request did not come from the panel")


#: The one refusal an operator can act on themselves. A session-scoped budget is spent by
#: *this browser*, and signing in again mints a new session with a new one — which is the
#: whole reason the counter is keyed on the session rather than on an address.
_SIGN_IN_AGAIN: Final[str] = ", or sign in again to start a fresh one"


def _refuse_if_limited(decision: RateLimitDecision, *, subject: str, code: AdminErrorCode) -> None:
    """Turn a refusal into the 429 — or, for a store outage, the 503 — and say which.

    One renderer for both budgets, but **not one code**. The two counters answer in the same
    shape and sit in disjoint key namespaces on purpose (see the module docstring), and the
    taxonomy has to keep them apart too: an SPA branching on ``LOGIN_RATE_LIMITED`` for a
    refused ``/auth/password`` cannot tell "you cannot sign in" from "this session has spent
    its re-auth budget, sign in again", and only the second has a remedy the operator can
    act on. ``subject`` is what the operator reads; ``code`` is what the client branches on.

    A refusal from the session-scoped counter names its remedy, because there is one and an
    operator who is not told it waits out fifteen minutes for nothing.
    """
    if decision.is_allowed:
        return
    is_outage = decision.outcome is RateLimitOutcome.BACKEND_UNAVAILABLE
    remedy = _SIGN_IN_AGAIN if decision.scope is RateLimitScope.SESSION else ""
    raise problem(
        AdminErrorCode.SERVICE_UNAVAILABLE if is_outage else code,
        f"the {subject} limiter is unavailable, so the request is refused"
        if is_outage
        else f"too many {subject} attempts; try again later{remedy}",
        headers={"Retry-After": str(decision.retry_after_s)},
        scope="" if decision.scope is None else str(decision.scope),
    )


async def _enforce_login_rate_limit(
    container: AdminContainer,
    *,
    username: str,
    client_ip: str | None,
    now: datetime,
    is_exempt: bool,
) -> None:
    """Charge the sign-in attempt and refuse before any hashing happens."""
    _refuse_if_limited(
        await check_login_rate_limit(
            container.rate_limits,
            username=username,
            client_ip=client_ip,
            now=now,
            is_session_exempt=is_exempt,
        ),
        subject="sign-in",
        code=AdminErrorCode.LOGIN_RATE_LIMITED,
    )


async def _reserve_reauth(
    container: AdminContainer, admin: CurrentAdmin, *, now: datetime
) -> RateLimitDecision:
    """Reserve a re-verification on ``/auth/step-up`` or ``/auth/password``, before argon2.

    The username and the session both come from :class:`CurrentAdmin` — the authenticated
    session, never the request body — so no caller can aim this counter at an account or a
    browser other than their own.

    The returned decision is the receipt: hand it to :func:`refund_reauth_reservation` once
    the password has verified, and the session's half of the charge comes back. A refusal
    never returns at all, it raises, so nothing downstream can refund an attempt that was
    denied.

    There is no session exemption to pass: holding a session is the precondition for reaching
    these routes at all, so exempting session-holders would exempt everyone, the thief
    included.
    """
    decision = await check_reauth_rate_limit(
        container.rate_limits,
        username=admin.username,
        session_id=admin.session.session_id,
        now=now,
    )
    _refuse_if_limited(decision, subject="password check", code=AdminErrorCode.REAUTH_RATE_LIMITED)
    return decision


async def _verified_account(
    db: AsyncSession,
    container: AdminContainer,
    *,
    username: str,
    password: str,
    code: AdminErrorCode = AdminErrorCode.UNAUTHENTICATED,
    message: str = _REJECTED,
) -> AdminUserRow:
    """The account this password belongs to, or the caller's one rejection.

    The verify runs even when there is no row, against a dummy hash of matching cost —
    ``verify_password_async(password, None, …)`` — so an unknown username costs the same
    ~50 ms as a wrong password and answers identically.
    """
    user = await accounts.get_by_username(db, username)
    verification = await verify_password_async(
        password, user.password_hash if user is not None else None, hasher=container.hasher
    )
    if user is None or not user.is_active or not verification.is_valid:
        _LOGGER.warning(
            "admin password check refused",
            extra={"event": "admin.password.refused", "admin_username": username},
        )
        raise problem(code, message)
    return user


def _set_session_cookies(
    response: Response, issued: IssuedSession, settings: AdminSettings
) -> None:
    """Both cookies, ``__Host-`` prefixed, ``SameSite=Lax``, scoped to the whole origin.

    The session cookie is ``HttpOnly`` — script must never read a bearer credential. The CSRF
    cookie deliberately is **not**: it is the transport that hands the SPA the value it echoes
    in ``X-CSRF-Token``, and it is not the thing being compared (the stored column is).

    ``SameSite=Lax`` rather than ``Strict`` (§12.1): ``Strict`` drops the cookie on every
    top-level navigation from elsewhere, so every filter URL pasted into a chat lands on a
    login screen and loses its deep link. ``Lax`` still blocks every cross-site POST.
    """
    max_age = settings.admin_session_ttl_s
    for name, value, is_http_only in (
        (SESSION_COOKIE_NAME, issued.token.raw, True),
        (CSRF_COOKIE_NAME, issued.csrf_token, False),
    ):
        response.set_cookie(
            name,
            value,
            max_age=max_age,
            path="/",
            secure=settings.is_cookie_secure,
            httponly=is_http_only,
            samesite="lax",
        )


def _clear_session_cookies(response: Response, settings: AdminSettings) -> None:
    for name in (SESSION_COOKIE_NAME, CSRF_COOKIE_NAME):
        response.delete_cookie(name, path="/", secure=settings.is_cookie_secure, samesite="lax")


def _user_agent(request: Request) -> str | None:
    raw = request.headers.get("user-agent")
    return None if raw is None else raw[:_MAX_USER_AGENT_CHARS]


async def _is_same_account(db: AsyncSession, presented: _Presented, *, username: str) -> bool:
    """Whether the request already holds a live session for the username being signed in.

    §12.1 T1's exemption from the strict ``(username, ip)`` counter. The looser per-username
    ceiling still applies, so a stolen session cannot grind passwords for free.
    """
    if presented.snapshot is None:
        return False
    user = await accounts.get_by_id(db, presented.snapshot.admin_user_id)
    return user is not None and user.username == accounts.normalize_username(username)


async def _issue(
    db: AsyncSession,
    container: AdminContainer,
    *,
    admin_user_id: UUID,
    request: Request,
    ip: str | None,
    now: datetime,
) -> IssuedSession:
    """One place that mints a session, so every caller gets the same clocks and columns."""
    settings = container.settings
    return await issue_session(
        db,
        container.redis,
        admin_user_id=admin_user_id,
        now=now,
        absolute_ttl_s=settings.admin_session_ttl_s,
        idle_ttl_s=settings.admin_session_idle_ttl_s,
        ip=ip,
        user_agent=_user_agent(request),
    )


#: The role recorded for a sign-in that never established one. ``actor_role`` is NOT NULL —
#: it is a snapshot of the role AT THE TIME, and a refused login has none — so the lowest
#: privilege in the matrix is written rather than inventing a plausible one. ``actor_id`` is
#: NULL beside it, which is how a reader tells "no such account" from "this account failed".
_NO_ESTABLISHED_ROLE: Final[AdminRole] = AdminRole.VIEWER


async def _audit_login_refusal(
    db: AsyncSession,
    container: AdminContainer,
    *,
    action: AuditAction,
    username: str,
    client_ip: str | None,
    now: datetime,
) -> None:
    """Record a refused sign-in, in its own committed transaction.

    The request transaction is about to roll back with the refusal, so a row written into it
    would disappear along with the thing it records — which is the whole failure §12.6's
    ``login.failure`` and ``login.limited`` rows exist to prevent.

    The account is looked up only to fill ``actor_id`` and ``actor_role`` honestly. It is not
    an enumeration signal: nothing about it reaches the response, which is identical either
    way, and the row is visible only to an operator who can already list accounts.
    """
    user = await accounts.get_by_username(db, username)
    await audit_sink.record_refusal(
        container,
        audit_sink.auth_entry(
            action,
            username=username,
            role=user.role if user is not None else _NO_ESTABLISHED_ROLE,
            outcome=AuditOutcome.DENIED,
            actor_id=user.id if user is not None else None,
            ip=client_ip,
        ),
        now=now,
    )


def _scope_or_422(body: StepUpRequest) -> str:
    """Build the stored scope, refusing a subject id that could not be stored intact.

    ``build_step_up_scope`` raises rather than truncating, because a truncated scope is a
    **wider** grant than the one that was asked for.
    """
    try:
        return build_step_up_scope(str(body.scope), body.subject_id)
    except ValueError as exc:
        raise ProblemError(
            AdminProblem(
                code=ErrorCode.INVALID_INPUT,
                message="that step-up subject is not a storable identifier",
            )
        ) from exc


def build_login_router() -> APIRouter:
    """The one public route. Exempt from the permission guard, never from the origin check."""
    router = APIRouter(tags=["auth"])

    @router.post(f"{AUTH_PREFIX}/login")
    async def login(
        request: Request,
        response: Response,
        body: LoginRequest,
        db: Db,
        container: Container,
    ) -> LoginResponse:
        """Verify, rotate, and hand back a fresh session."""
        settings = container.settings
        _enforce_origin(request, settings)
        now = utc_now()
        client_ip = resolve_request_ip(request, container)
        presented = await _presented_session(request, db, container, now=now)
        try:
            await _enforce_login_rate_limit(
                container,
                username=body.username,
                client_ip=client_ip,
                now=now,
                is_exempt=await _is_same_account(db, presented, username=body.username),
            )
        except ProblemError:
            # No account lookup on this path, deliberately: a refused request must do no
            # database read at all, which is the property that makes the limiter a defence
            # against load rather than another way to spend it. The row therefore carries
            # the attempted username and no actor. It is written once per limiter window —
            # see :func:`is_first_login_refusal` — so a flood cannot grow the table.
            if await is_first_login_refusal(
                container.rate_limits, username=body.username, client_ip=client_ip, now=now
            ):
                await audit_sink.record_refusal(
                    container,
                    audit_sink.auth_entry(
                        AuditAction.LOGIN_RATE_LIMITED,
                        username=body.username,
                        role=_NO_ESTABLISHED_ROLE,
                        outcome=AuditOutcome.DENIED,
                        ip=client_ip,
                    ),
                    now=now,
                )
            raise
        try:
            user = await _verified_account(
                db, container, username=body.username, password=body.password
            )
        except ProblemError:
            await _audit_login_refusal(
                db,
                container,
                action=AuditAction.LOGIN_FAILURE,
                username=body.username,
                client_ip=client_ip,
                now=now,
            )
            raise
        if presented.snapshot is not None and presented.digest is not None:
            # Session fixation: a login must not leave the token it arrived with usable.
            await revoke_session(
                db,
                container.redis,
                session_id=presented.snapshot.session_id,
                token_sha256=presented.digest,
                now=now,
            )
        issued = await _issue(
            db, container, admin_user_id=user.id, request=request, ip=client_ip, now=now
        )
        await accounts.touch_login(db, admin_user_id=user.id, now=now)
        # In the REQUEST's transaction: a login that issues a session and then cannot audit
        # itself must leave neither (§12.6).
        await audit_sink.record(
            db,
            container,
            audit_sink.auth_entry(
                AuditAction.LOGIN_SUCCESS,
                username=user.username,
                role=user.role,
                outcome=AuditOutcome.OK,
                actor_id=user.id,
                ip=client_ip,
            ),
            now=now,
        )
        _set_session_cookies(response, issued, settings)
        _LOGGER.info(
            "admin signed in", extra={"event": "admin.login.ok", "admin_username": user.username}
        )
        return LoginResponse(must_change_password=user.must_change_password)

    return router


def build_auth_router() -> APIRouter:
    """Everything that needs a session. The guard is declared on the router, once."""
    router = APIRouter(
        tags=["auth"],
        dependencies=[Depends(require_permission(Permission.SESSION_SELF))],
    )

    @router.get(f"{AUTH_PREFIX}/me")
    async def me(admin: Admin) -> MeResponse:
        """Who am I, and must I rotate my password before doing anything else?"""
        return MeResponse(
            id=admin.admin_user_id,
            username=admin.username,
            role=admin.role,
            last_login_at=admin.last_login_at,
            must_change_password=admin.must_change_password,
        )

    @router.post(f"{AUTH_PREFIX}/logout", status_code=_NO_CONTENT)
    async def logout(admin: Admin, db: Db, container: Container) -> Response:
        """Revoke the session row **and its mirror**, then drop both cookies."""
        now = utc_now()
        await revoke_session(
            db,
            container.redis,
            session_id=admin.session.session_id,
            token_sha256=admin.token_sha256,
            now=now,
        )
        await audit_sink.record(
            db,
            container,
            audit_sink.auth_entry(
                AuditAction.LOGOUT,
                username=admin.username,
                role=admin.role,
                outcome=AuditOutcome.OK,
                actor_id=admin.admin_user_id,
                ip=admin.client_ip,
            ),
            now=now,
        )
        response = Response(status_code=_NO_CONTENT)
        _clear_session_cookies(response, container.settings)
        return response

    @router.post(f"{AUTH_PREFIX}/password")
    async def change_password(
        request: Request,
        response: Response,
        body: PasswordChangeRequest,
        admin: Admin,
        db: Db,
        container: Container,
    ) -> LoginResponse:
        """Rotate the credential, kill every session it authorised, and re-issue one."""
        now = utc_now()
        # Before the verify, not after: this route hashes the current password exactly as
        # the login route does, and a cookie is not a licence to do it without limit.
        reservation = await _reserve_reauth(container, admin, now=now)
        try:
            user = await _verified_account(
                db,
                container,
                username=admin.username,
                password=body.current_password,
                code=AdminErrorCode.FORBIDDEN,
                message=_WRONG_CURRENT,
            )
        except ProblemError:
            await audit_sink.record_refusal(
                container,
                audit_sink.auth_entry(
                    AuditAction.ADMIN_PASSWORD_CHANGE,
                    username=admin.username,
                    role=admin.role,
                    outcome=AuditOutcome.DENIED,
                    actor_id=admin.admin_user_id,
                    ip=admin.client_ip,
                ),
                now=now,
            )
            raise
        # The password was right, so this attempt was not an attack on it: the session gets
        # its charge back. Only reachable past ``_verified_account``, which raises otherwise.
        await refund_reauth_reservation(container.rate_limits, reservation)
        new_hash = await hash_password_async(body.new_password, hasher=container.hasher)
        await accounts.set_password(db, admin_user_id=user.id, password_hash=new_hash, now=now)
        await revoke_sessions_for_user(db, container.redis, admin_user_id=user.id, now=now)
        issued = await _issue(
            db,
            container,
            admin_user_id=user.id,
            request=request,
            ip=resolve_request_ip(request, container),
            now=now,
        )
        # The field NAME, never the value (§12.4): the row says the credential moved, and
        # nothing in it could ever be replayed.
        await audit_sink.record(
            db,
            container,
            audit_sink.auth_entry(
                AuditAction.ADMIN_PASSWORD_CHANGE,
                username=user.username,
                role=admin.role,
                outcome=AuditOutcome.OK,
                actor_id=user.id,
                field_names=("password_hash",),
                ip=admin.client_ip,
            ),
            now=now,
        )
        _set_session_cookies(response, issued, container.settings)
        _LOGGER.info(
            "admin password changed",
            extra={"event": "admin.password.changed", "admin_username": user.username},
        )
        return LoginResponse(must_change_password=False)

    @router.post(f"{AUTH_PREFIX}/step-up")
    async def step_up(
        body: StepUpRequest, admin: Admin, db: Db, container: Container
    ) -> StepUpResponse:
        """Re-authenticate for one action on one subject. Never session-wide."""
        # The scope first: it is pure string work, so a body the SPA built wrong is a 422
        # rather than a charge against the operator's budget. Then the limiter, then argon2 —
        # a step-up that hashes before it meters is the oracle it exists to close.
        scope = _scope_or_422(body)
        now = utc_now()
        reservation = await _reserve_reauth(container, admin, now=now)
        try:
            await _verified_account(
                db,
                container,
                username=admin.username,
                password=body.password,
                code=AdminErrorCode.FORBIDDEN,
                message=_WRONG_CURRENT,
            )
        except ProblemError:
            # The row an investigation wants most: somebody holding the cookie tried to
            # escalate and could not produce the password.
            await audit_sink.record_refusal(
                container,
                audit_sink.auth_entry(
                    AuditAction.STEP_UP_FAILURE,
                    username=admin.username,
                    role=admin.role,
                    outcome=AuditOutcome.DENIED,
                    actor_id=admin.admin_user_id,
                    subject_id=body.subject_id,
                    ip=admin.client_ip,
                ),
                now=now,
            )
            raise
        # §12.1 T2 wants one step-up per reveal, purge, block, force-deliver and config
        # commit; charging the correct ones is what made a busy incident 429 the operator.
        await refund_reauth_reservation(container.rate_limits, reservation)
        await grant_step_up(
            db,
            container.redis,
            session_id=admin.session.session_id,
            token_sha256=admin.token_sha256,
            scope=scope,
            now=now,
        )
        await audit_sink.record(
            db,
            container,
            audit_sink.auth_entry(
                AuditAction.STEP_UP_SUCCESS,
                username=admin.username,
                role=admin.role,
                outcome=AuditOutcome.OK,
                actor_id=admin.admin_user_id,
                subject_id=body.subject_id,
                ip=admin.client_ip,
            ),
            now=now,
        )
        _LOGGER.info(
            "admin step-up granted",
            extra={
                "event": "admin.stepup.granted",
                "admin_username": admin.username,
                "step_up_scope": scope,
            },
        )
        # The expiry the SPA is told is the one the guard will actually honour: the
        # configured grace for an ordinary action, and zero for the two §12.1 T2 marks
        # "grace 0". Quoting the grace for a purge would promise five minutes that the very
        # next request refuses.
        max_age_s = max_age_for_action(
            body.scope, grace_s=container.settings.admin_step_up_grace_seconds
        )
        return StepUpResponse(
            scope=scope, granted_at=now, expires_at=now + timedelta(seconds=max_age_s)
        )

    return router
