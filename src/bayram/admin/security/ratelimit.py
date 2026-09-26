"""Fixed-window credential limiters, checked **before** argon2 and closed when Redis is down.

Two counters per budget, and the pair is the point (ADMIN_PANEL_PLAN §12.1 T1):

* a strict one that bounds one principal, which is what actually stops credential stuffing;
* a loose ceiling keyed on the username alone, which catches the same attack spread across
  a botnet — and is the absolute cap on how much argon2 one account can buy in a window.

Keying the strict counter on the username alone — the obvious first design — hands anyone
who knows an operator's username a permanent 429 against that account, at exactly the
moment during an incident when the operator needs to log in. Hence the pair, hence the
WARNING on every per-username trip: the remaining denial-of-service is bounded, visible and
attributable rather than merely effective.

**Order matters twice.** The check runs before the password is verified, because a limiter
that runs after the hash *is* the CPU-exhaustion vector it was added to prevent. And a
request refused by the strict counter does not charge the loose one, or an attacker on one
IP would spend ten real attempts and then drive the username to its global ceiling for
free — turning the strict counter into the lockout primitive it exists to avoid.

**Fail closed.** When Redis is unreachable the answer is "denied", not "allowed". A login
attempt with no working limiter is an unlimited login attempt on the one unauthenticated,
CPU-expensive route in the process, reachable by anyone who can talk to the port; an
operator locked out for as long as Redis is down is an outage, and this deployment already
cannot serve sessions without Redis. The failure is logged at ERROR with the exception, so
it reads as an outage rather than as a mysterious 429.

**Two purposes, two key namespaces.** ``/auth/login`` is not the only route that verifies a
password: ``/auth/step-up`` and ``/auth/password`` re-verify it behind a session, which is
the whole of §12.1 T2's value — the re-verify "is the only thing that makes a step-up mean
anything against a session that was already stolen". Unmetered, those two are the same
argon2 oracle and the same CPU-exhaustion vector as the login route, one door over. So they
are metered by :func:`check_reauth_rate_limit`, with the same fail-closed rule but its
**own** ``reauth`` key namespace, because a shared per-username ceiling would let a thief
replaying a stolen cookie against ``/auth/step-up`` spend the *login* route's budget and
keep the real operator from signing in — precisely the denial-of-service T1's split key was
designed to avoid, arriving at the moment the operator needs to get in and revoke.

The re-auth budget is **not** shaped like the login one, and the two differences are the
whole of what makes it usable during an incident instead of a second lockout button.

**1. The strict counter is keyed on the session, not on ``(username, client_ip)``.** Ask
what actually separates the operator who just re-authenticated from the attacker holding
their cookie, and there is exactly one answer: **the attacker cannot mint a session, because
minting one costs the password.** So the budget is per session. A fresh sign-in is a fresh
session and therefore a fresh budget — which is the remedy an operator can act on — while
the thief is stuck grinding inside the one session they stole, forever, at
:data:`REAUTH_MAX_PER_SESSION` guesses a window. Keying on ``(username, client_ip)`` had the
opposite property: signing back in did **not** clear it, so a new OWNER who mistyped their
own password thirty times was locked out of ``/auth/password`` for the rest of the window —
and because ``must_change_password`` closes every other route, that is the entire panel.

**2. A re-auth that succeeds is given back.** The reservation is taken *before* argon2 runs
(:func:`check_reauth_rate_limit` increments, and a caller over budget is refused without
hashing — the CPU property is not negotiable), and :func:`refund_reauth_reservation` hands
the strict counter's charge back once the password has actually verified. Net: only
**failures** accumulate against the session. §12.1 T2 requires one step-up per reveal,
purge, force-deliver, block and config commit, so charging correct step-ups meant a busy
incident 429ing the operator who was handling it — a control that fires hardest exactly when
it is most expensive to be wrong.

The **per-username** ceiling is deliberately *not* refunded. It is not the operator-facing
budget; it is the hard bound on how much argon2 one account can buy in a window, and a bound
that only counts failures would not bound anything against a caller who knows the password.
An attacker cannot reach it — they are stopped at :data:`REAUTH_MAX_PER_SESSION` per stolen
session and cannot open a second one — so it costs the honest path nothing while keeping the
CPU arithmetic true.

**There is no session exemption here**, and :func:`check_reauth_rate_limit` does not take the
argument. Every caller of these routes holds a valid session by definition, so an exemption
keyed on that would exempt everyone — including the thief — and leave the oracle exactly as
open as it was.

The total argon2 a single username can buy stays bounded and small: 100 login verifies plus
120 re-auth verifies per window, ~11 seconds of one core.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

from redis.asyncio import Redis

from bayram.admin.security.tokens import sha256_hex
from bayram.logging import get_logger

__all__ = [
    "LOGIN_WINDOW_S",
    "LOGIN_MAX_PER_USER_IP",
    "LOGIN_MAX_PER_USERNAME",
    "REAUTH_WINDOW_S",
    "REAUTH_MAX_PER_SESSION",
    "REAUTH_MAX_PER_USERNAME",
    "LoginRateLimits",
    "ReauthRateLimits",
    "RateLimitPurpose",
    "RateLimitScope",
    "RateLimitOutcome",
    "RateLimitDecision",
    "WindowCounterStore",
    "RedisWindowCounterStore",
    "check_login_rate_limit",
    "is_first_login_refusal",
    "check_reauth_rate_limit",
    "refund_reauth_reservation",
]

_LOGGER: Final = get_logger(__name__)

#: 15 minutes, per §12.1 T1.
LOGIN_WINDOW_S: Final[int] = 900
LOGIN_MAX_PER_USER_IP: Final[int] = 10
LOGIN_MAX_PER_USERNAME: Final[int] = 100

#: The re-auth window matches the login one so an operator only ever has one number to
#: reason about when they are locked out of something.
REAUTH_WINDOW_S: Final[int] = 900
#: **Failed** password checks one session may make in a window; a correct one is refunded.
#: Ten is generous for a typo and hopeless as an attack: a thief cannot open a second
#: session without the password, so ten is their whole budget, per window, forever. It is
#: also the number a signed-in operator gets back simply by signing in again.
REAUTH_MAX_PER_SESSION: Final[int] = 10
#: Every re-auth an account makes in a window, correct ones included and never refunded.
#: Not the operator's budget — the ceiling on how much argon2 one account can buy. Out of
#: an attacker's reach (they are held at :data:`REAUTH_MAX_PER_SESSION`), and twelve fresh
#: sign-ins clear of any honest incident.
REAUTH_MAX_PER_USERNAME: Final[int] = 120

_KEY_PREFIX: Final[str] = "bayram:admin:rl"
#: Enough of the digest to make a collision irrelevant, short enough to keep keys readable.
_KEY_DIGEST_CHARS: Final[int] = 32
_UNKNOWN_IP: Final[str] = "unknown"


class RateLimitPurpose(StrEnum):
    """Which credential check is being metered, and therefore which key namespace.

    The value is part of every Redis key, which is what keeps the two budgets from being
    spendable against each other (see the module docstring).
    """

    LOGIN = "login"
    REAUTH = "reauth"


class RateLimitScope(StrEnum):
    """Which counter answered. Reported so the log and the audit row name the right one."""

    USER_IP = "user_ip"
    SESSION = "session"
    USERNAME = "username"


class RateLimitOutcome(StrEnum):
    """Why the limiter answered as it did.

    ``BACKEND_UNAVAILABLE`` is distinct from ``TRIPPED`` because they are different
    incidents: one is an attack in progress, the other is Redis being down. Collapsing them
    into a bare boolean is how a store outage gets read as a brute-force attempt for an
    hour.
    """

    ALLOWED = "allowed"
    TRIPPED = "tripped"
    BACKEND_UNAVAILABLE = "backend_unavailable"


@dataclass(frozen=True, slots=True)
class LoginRateLimits:
    """``/auth/login``'s two ceilings and their shared window. Frozen; overridable."""

    window_s: int = LOGIN_WINDOW_S
    max_per_user_ip: int = LOGIN_MAX_PER_USER_IP
    max_per_username: int = LOGIN_MAX_PER_USERNAME


@dataclass(frozen=True, slots=True)
class ReauthRateLimits:
    """The re-auth budget. A different **shape**, not just different numbers.

    ``max_per_session`` is where ``LoginRateLimits.max_per_user_ip`` would be, and the
    substitution is the fix: an address is not a principal here, a session is. Sharing one
    class would have made the two budgets look interchangeable in every signature.
    """

    window_s: int = REAUTH_WINDOW_S
    max_per_session: int = REAUTH_MAX_PER_SESSION
    max_per_username: int = REAUTH_MAX_PER_USERNAME


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """The limiter's answer. ``retry_after_s`` is what the 429's ``Retry-After`` carries."""

    is_allowed: bool
    outcome: RateLimitOutcome
    scope: RateLimitScope | None
    retry_after_s: int
    #: The counter a successful verify gives back, and the TTL to re-arm it with. Set only
    #: by :func:`check_reauth_rate_limit`, and only on an allowed decision; ``None``
    #: everywhere else, so :func:`refund_reauth_reservation` on any other decision is a
    #: no-op rather than a way to un-charge the login route.
    refundable_key: str | None = None
    refundable_ttl_s: int = 0


DEFAULT_LOGIN_LIMITS: Final[LoginRateLimits] = LoginRateLimits()
DEFAULT_REAUTH_LIMITS: Final[ReauthRateLimits] = ReauthRateLimits()


class WindowCounterStore(Protocol):
    """Bump a key by one or by N, expire it, and give one bump back. The whole contract.

    A protocol rather than a concrete Redis client so the limiter's own logic — ordering,
    fail-closed, the WARNING — is tested without a server, and so a future backend is a new
    class rather than an edit here. Implementations MAY raise; the callers below treat any
    exception from :meth:`increment` as "the limiter is not working" and deny.

    :meth:`increment_by` is here rather than in :mod:`bayram.admin.security.budget` because the
    seam has to be one seam: the reveal budget is counted in **records**, so it must add N
    units and read the post-charge total in a single round trip, and N calls to
    :meth:`increment` are N interleavable operations rather than one atomic charge — the
    race the record unit exists to survive. The delta is signed, which is how a refused
    reveal releases the charge it made (§12.3); a caller must not use a negative delta to
    undo anything it did not charge.
    """

    async def increment(self, key: str, *, ttl_s: int) -> int:
        """Increment ``key``, set its TTL on creation, and return the new count."""
        ...

    async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
        """Add ``amount`` to ``key`` atomically, re-arm the TTL, return the new total."""
        ...

    async def refund(self, key: str, *, ttl_s: int) -> None:
        """Give one increment back, re-arming the TTL. Only ever undoes a real charge."""
        ...


class RedisWindowCounterStore:
    """:class:`WindowCounterStore` over Redis, one round trip per counter.

    ``INCRBY`` then ``EXPIRE`` in a transaction: ``EXPIRE`` is issued unconditionally, which
    slides the key's lifetime, but the key name already carries the window index, so a
    window can never outlive its own bucket. Doing it this way avoids the classic bug where
    a crash between ``INCR`` and ``EXPIRE`` leaves an immortal counter that locks an account
    out permanently.

    :meth:`refund` is the same shape with ``DECR``, and re-arms the TTL for the same reason:
    a key the reservation created and the refund re-created must still expire. It can only
    follow a charge this process made in this window, so it cannot drive a counter below
    zero in any reachable sequence — and even if a key expired in between, the worst case is
    one extra attempt inside a window that is about to reset anyway.
    """

    __slots__ = ("_client",)

    def __init__(self, client: Redis[str]) -> None:
        self._client = client

    async def increment(self, key: str, *, ttl_s: int) -> int:
        return await self.increment_by(key, 1, ttl_s=ttl_s)

    async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
        # ``Redis.incr(name, amount)`` issues ``INCRBY``; one command, so the add and the
        # read of the new total are the same operation and cannot interleave. A negative
        # amount is the release path and is the same command.
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.incr(key, amount)
            pipe.expire(key, ttl_s)
            results = await pipe.execute()
        return int(results[0])

    async def refund(self, key: str, *, ttl_s: int) -> None:
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.decr(key, 1)
            pipe.expire(key, ttl_s)
            await pipe.execute()


@dataclass(frozen=True, slots=True)
class _Counter:
    """One key, the ceiling it answers to, and the scope name a refusal reports."""

    key: str
    ceiling: int
    scope: RateLimitScope


def _window_index(now: datetime, window_s: int) -> int:
    return int(now.timestamp()) // window_s


def _username_digest(username: str) -> str:
    """Usernames are personal-ish and operator-supplied, so they are hashed into the key.

    Case-folded first, so ``Alice`` and ``alice`` share a bucket — otherwise the ceiling is
    bypassed by varying the case of a username the lookup treats as one account.
    """
    return sha256_hex(username.casefold())[:_KEY_DIGEST_CHARS]


def _user_ip_key(
    *, purpose: RateLimitPurpose, username: str, client_ip: str | None, window: int
) -> str:
    ip = client_ip or _UNKNOWN_IP
    return f"{_KEY_PREFIX}:{purpose.value}:uip:{window}:{_username_digest(username)}:{ip}"


def _session_key(*, purpose: RateLimitPurpose, session_id: UUID, window: int) -> str:
    """The session's own bucket. Hashed like the username, and for the same reason.

    A session id is not a bearer credential — the cookie's digest is, and that never comes
    near this module — but it identifies one signed-in browser, and Redis keys end up in
    ``KEYS`` dumps and support tickets.
    """
    digest = sha256_hex(str(session_id))[:_KEY_DIGEST_CHARS]
    return f"{_KEY_PREFIX}:{purpose.value}:ses:{window}:{digest}"


def _username_key(*, purpose: RateLimitPurpose, username: str, window: int) -> str:
    return f"{_KEY_PREFIX}:{purpose.value}:usr:{window}:{_username_digest(username)}"


async def _bump(store: WindowCounterStore, key: str, *, ttl_s: int) -> int | None:
    """Increment one counter. ``None`` means the store failed and the caller must deny."""
    try:
        return await store.increment(key, ttl_s=ttl_s)
    except Exception:
        # Deliberately broad: any failure of the limiter is a failure to limit, and the
        # store is a protocol whose implementations raise whatever their client raises.
        _LOGGER.exception(
            "credential rate-limit store is unavailable; failing closed",
            extra={"event": "admin.ratelimit.store_unavailable"},
        )
        return None


def _denied(
    scope: RateLimitScope, outcome: RateLimitOutcome, retry_after_s: int
) -> RateLimitDecision:
    return RateLimitDecision(
        is_allowed=False, outcome=outcome, scope=scope, retry_after_s=retry_after_s
    )


_ALLOWED: Final[RateLimitDecision] = RateLimitDecision(
    is_allowed=True, outcome=RateLimitOutcome.ALLOWED, scope=None, retry_after_s=0
)


def _log_username_ceiling(
    purpose: RateLimitPurpose, username: str, *, total: int, window_s: int
) -> None:
    """Named, at WARNING, because this ceiling is also the targeting signal.

    It is the counter an attacker spread across many source addresses trips, and the one
    whose remaining denial-of-service is bounded, visible and attributable rather than merely
    effective. The username is operator data, not customer data, so it is safe to log.
    """
    _LOGGER.warning(
        "admin credential rate limit tripped for a username across addresses",
        extra={
            "event": "admin.ratelimit.username_tripped",
            "rate_limit_purpose": purpose.value,
            "admin_username": username,
            "attempts_in_window": total,
            "window_s": window_s,
        },
    )


async def _charge(
    store: WindowCounterStore, counter: _Counter, *, window_s: int
) -> tuple[int | None, RateLimitDecision | None]:
    """Charge one counter. The second element is the refusal, or ``None`` to carry on."""
    count = await _bump(store, counter.key, ttl_s=window_s)
    if count is None:
        return None, _denied(counter.scope, RateLimitOutcome.BACKEND_UNAVAILABLE, window_s)
    if count > counter.ceiling:
        return count, _denied(counter.scope, RateLimitOutcome.TRIPPED, window_s)
    return count, None


async def _charge_username_ceiling(
    store: WindowCounterStore,
    *,
    purpose: RateLimitPurpose,
    username: str,
    window: int,
    ceiling: int,
    window_s: int,
) -> RateLimitDecision:
    """The loose, address- and session-independent ceiling, plus its WARNING."""
    counter = _Counter(
        _username_key(purpose=purpose, username=username, window=window),
        ceiling,
        RateLimitScope.USERNAME,
    )
    total, refusal = await _charge(store, counter, window_s=window_s)
    if refusal is None:
        return _ALLOWED
    if total is not None:
        _log_username_ceiling(purpose, username, total=total, window_s=window_s)
    return refusal


async def check_login_rate_limit(
    store: WindowCounterStore,
    *,
    username: str,
    client_ip: str | None,
    now: datetime,
    limits: LoginRateLimits = DEFAULT_LOGIN_LIMITS,
    is_session_exempt: bool = False,
) -> RateLimitDecision:
    """Charge a sign-in attempt against both login counters and say whether it may proceed.

    Call this **before** verifying the password. Every attempt is charged, successful ones
    included: the check has to happen before the verify, so it cannot know the outcome, and
    ten attempts in fifteen minutes from one address is far outside how an operator with a
    twelve-hour session behaves.

    ``is_session_exempt`` skips the strict counter for a request that already carries a
    valid session for this username (§12.1 T1). The loose per-username ceiling still
    applies, so a stolen session cannot be used to grind passwords for free.

    ``client_ip`` may be ``None`` when the peer address is unknown; those attempts share
    one bucket, which is the conservative direction.
    """
    window = _window_index(now, limits.window_s)
    if not is_session_exempt:
        counter = _Counter(
            _user_ip_key(
                purpose=RateLimitPurpose.LOGIN,
                username=username,
                client_ip=client_ip,
                window=window,
            ),
            limits.max_per_user_ip,
            RateLimitScope.USER_IP,
        )
        _, refusal = await _charge(store, counter, window_s=limits.window_s)
        if refusal is not None:
            # Charging the username ceiling here too would let one IP drive the account to
            # its global limit for free — see the module docstring.
            return refusal
    return await _charge_username_ceiling(
        store,
        purpose=RateLimitPurpose.LOGIN,
        username=username,
        window=window,
        ceiling=limits.max_per_username,
        window_s=limits.window_s,
    )


async def is_first_login_refusal(
    store: WindowCounterStore,
    *,
    username: str,
    client_ip: str | None,
    now: datetime,
    limits: LoginRateLimits = DEFAULT_LOGIN_LIMITS,
) -> bool:
    """Whether this refusal is the FIRST in its window, so §12.6's row is written once.

    ``login.limited`` is a row an investigation genuinely wants — a brute-force campaign is
    exactly the thing an audit log should show. Writing one row per refused attempt would
    also turn a login flood into unbounded growth of the table with the longest clock in the
    system, which is a denial of service against the audit log itself. So the *event* is
    audited, once per limiter window per ``(username, ip)``, and the attempts behind it are
    counted by the limiter rather than enumerated in the log.

    A store failure answers ``True``: an unrecordable refusal is worse than a duplicated
    one, and the flood case is already bounded by the limiter that produced the refusal.
    """
    key = _user_ip_key(
        purpose=RateLimitPurpose.LOGIN,
        username=f"audit:{username}",
        client_ip=client_ip,
        window=_window_index(now, limits.window_s),
    )
    count = await _bump(store, key, ttl_s=limits.window_s)
    return count is None or count <= 1


async def check_reauth_rate_limit(
    store: WindowCounterStore,
    *,
    username: str,
    session_id: UUID,
    now: datetime,
    limits: ReauthRateLimits = DEFAULT_REAUTH_LIMITS,
) -> RateLimitDecision:
    """Reserve one re-verification — ``/auth/step-up``, ``/auth/password`` — and answer.

    Call this **before** verifying the password, for the same reason the login route does:
    behind a stolen cookie these routes are the identical argon2 oracle and the identical
    CPU-exhaustion vector, and a limiter that runs after the hash has already paid for the
    attack it is refusing. This is a *reservation*: it is charged now, and
    :func:`refund_reauth_reservation` gives the strict half back if the password verifies.

    The strict counter is the **session**, not ``(username, client_ip)``. Minting a session
    costs the password, so a fresh sign-in is the one thing an attacker with a stolen cookie
    cannot do — which makes "sign in again" a real remedy for a locked-out operator and no
    remedy at all for a thief. The full argument is in the module docstring.

    There is deliberately **no** ``is_session_exempt`` here: every caller of these routes
    holds a valid session, so an exemption keyed on holding one would meter nothing.
    """
    window = _window_index(now, limits.window_s)
    key = _session_key(purpose=RateLimitPurpose.REAUTH, session_id=session_id, window=window)
    counter = _Counter(key, limits.max_per_session, RateLimitScope.SESSION)
    _, refusal = await _charge(store, counter, window_s=limits.window_s)
    if refusal is not None:
        return refusal
    decision = await _charge_username_ceiling(
        store,
        purpose=RateLimitPurpose.REAUTH,
        username=username,
        window=window,
        ceiling=limits.max_per_username,
        window_s=limits.window_s,
    )
    if not decision.is_allowed:
        return decision
    return dataclasses.replace(decision, refundable_key=key, refundable_ttl_s=limits.window_s)


async def refund_reauth_reservation(store: WindowCounterStore, decision: RateLimitDecision) -> None:
    """Give the session's charge back, once the password has actually verified.

    Only the strict per-session counter is refunded. The per-username ceiling keeps every
    attempt, because it is the bound on how much argon2 an account can buy rather than the
    operator's working budget, and a bound that counted only failures would bound nothing
    against a caller who knows the password.

    A refund that cannot be written is **not** fatal and is not silent: it is logged at
    ERROR with the exception, and the consequence is that this one correct re-auth stays
    charged against the session — the conservative direction, and one the operator clears
    by signing in again.
    """
    if decision.refundable_key is None:
        return
    try:
        await store.refund(decision.refundable_key, ttl_s=decision.refundable_ttl_s)
    except Exception:
        # Broad for the same reason ``_bump`` is: the store is a protocol and raises
        # whatever its client raises. Unlike a failed charge, this one cannot deny.
        _LOGGER.exception(
            "could not refund a successful re-auth; the reservation stands",
            extra={"event": "admin.ratelimit.refund_failed"},
        )
