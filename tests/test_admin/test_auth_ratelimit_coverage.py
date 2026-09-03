"""The two password-verifying routes behind the session, and the budget they answer to.

Slice 1a shipped a limiter on ``/auth/login`` and nothing on ``/auth/step-up`` or
``/auth/password``. Both of those verify a password with argon2, so an attacker holding a
stolen VIEWER-or-better cookie had unlimited guesses at an operator's password at 64 MiB and
~50 ms each — simultaneously the credential attack step-up exists to stop (§12.1 T2: the
re-verify "is the only thing that makes a step-up mean anything against a session that was
already stolen") and T1's CPU-exhaustion vector, moved one route over. The reviewer's probe
was 25 wrong-password POSTs to each route: all 403, zero 429.

Every test in the first three sections fails against the pre-fix tree.

The re-auth counters live in their **own** key namespace rather than sharing the login ones,
and :func:`test_grinding_a_step_up_cannot_lock_the_operator_out_of_signing_in` pins why:
one shared per-username ceiling would hand anyone with a stolen cookie the ability to spend
the login route's budget and keep the real operator from signing in — the lockout primitive
§12.1 T1's split key exists to avoid, arriving at the moment the operator most needs to get
in and revoke.

The last test is a **characterisation** rather than a regression: it pins what the login
route actually costs the database before its limiter answers, so "two unauthenticated DB
reads per request" cannot quietly become true. It passes against the pre-fix tree by design.

**Why this file drives the app through its own client** rather than the package fixtures:
the session and CSRF cookies are ``__Host-`` prefixed and therefore ``Secure``, and no HTTP
client will replay a ``Secure`` cookie to an ``http://`` origin. The client here talks to the
https form of the configured origin while still sending the configured ``Origin`` header, so
these tests hold whichever scheme the shared fixtures settle on.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from hbd.admin.app import create_app
from hbd.admin.container import AdminContainer
from hbd.admin.errors import AdminErrorCode
from hbd.admin.routers import auth as auth_router
from hbd.admin.security.ratelimit import (
    LOGIN_MAX_PER_USER_IP,
    LOGIN_MAX_PER_USERNAME,
    REAUTH_MAX_PER_SESSION,
    REAUTH_MAX_PER_USERNAME,
    REAUTH_WINDOW_S,
    RateLimitOutcome,
    RateLimitPurpose,
    RateLimitScope,
    ReauthRateLimits,
    check_login_rate_limit,
    check_reauth_rate_limit,
)
from tests.test_admin.conftest import (
    ORIGIN,
    PASSWORD,
    USERNAME,
    FakeRedis,
    create_account,
    csrf_headers,
    make_settings,
    open_container,
    sign_in,
)

#: A fixed instant, so a test that asserts on a window is not a race.
NOW: Final[datetime] = datetime(2026, 3, 21, 9, 0, 0, tzinfo=UTC)
#: The origin the client *connects* to. The ``Origin`` header it sends stays :data:`ORIGIN`,
#: which is what the server compares; this only decides whether a ``Secure`` cookie is sent.
COOKIE_ORIGIN: Final[str] = ORIGIN.replace("http://", "https://", 1)
_NEW_PASSWORD: Final[str] = "a-brand-new-passphrase"
_WRONG: Final[str] = "not-the-password"
_IP: Final[str] = "203.0.113.7"
_SESSION_COOKIE: Final[str] = "__Host-hbd_session"
#: A stand-in for the session the limiter keys on, for the tests that call it directly.
_SESSION_ID: Final[UUID] = UUID("11111111-2222-3333-4444-555555555555")


# ---------------------------------------------------------------------------
# A panel to drive: real container, in-memory database, countable limiter
# ---------------------------------------------------------------------------
class CountingRateLimits:
    """A ``WindowCounterStore`` that records every key, and can be taken down mid-test.

    ``is_down`` is how the fail-closed path is asserted from a signed-in session: sign in
    while the store works, break it, and require a refusal rather than a grant.
    """

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.is_down = False

    async def increment(self, key: str, *, ttl_s: int) -> int:
        return await self.increment_by(key, 1, ttl_s=ttl_s)

    async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
        del ttl_s
        if self.is_down:
            raise ConnectionError("the limiter store is unavailable")
        self.counts[key] = self.counts.get(key, 0) + amount
        return self.counts[key]

    async def refund(self, key: str, *, ttl_s: int) -> None:
        del ttl_s
        if self.is_down:
            raise ConnectionError("the limiter store is unavailable")
        self.counts[key] = max(0, self.counts.get(key, 0) - 1)

    def keys_for(self, purpose: RateLimitPurpose) -> dict[str, int]:
        return {key: count for key, count in self.counts.items() if f":{purpose.value}:" in key}

    def scoped(self, purpose: RateLimitPurpose, marker: str) -> dict[str, int]:
        """The counters of one shape — ``ses`` for the session budget, ``usr`` for the cap."""
        return {key: count for key, count in self.keys_for(purpose).items() if f":{marker}:" in key}


@dataclass(frozen=True, slots=True)
class Panel:
    """One running admin API, its container, and the limiter store behind it."""

    container: AdminContainer
    http: httpx.AsyncClient
    limits: CountingRateLimits


@asynccontextmanager
async def open_panel() -> AsyncIterator[Panel]:
    """The app, its lifespan entered, reachable over the scheme a ``Secure`` cookie needs."""
    store = CountingRateLimits()
    async with open_container(make_settings(), FakeRedis(), store) as container:
        application = create_app(container=container)
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(transport=transport, base_url=COOKIE_ORIGIN) as http:
                yield Panel(container=container, http=http, limits=store)


@pytest.fixture
async def panel() -> AsyncIterator[Panel]:
    async with open_panel() as running:
        yield running


async def signed_in(panel: Panel) -> None:
    """One operator, one live session. The state an attacker with a stolen cookie is in."""
    await create_account(panel.container)
    assert (await sign_in(panel.http)).status_code == 200


# ---------------------------------------------------------------------------
# Route helpers
# ---------------------------------------------------------------------------
def step_up(
    client: httpx.AsyncClient, *, password: str, subject: str = "order-42"
) -> Awaitable[httpx.Response]:
    """POST /api/auth/step-up the way the SPA does, CSRF header included."""
    return client.post(
        "/api/auth/step-up",
        json={"password": password, "scope": "reveal", "subjectId": subject},
        headers=csrf_headers(client),
    )


def change_password(
    client: httpx.AsyncClient, *, current: str, new: str = _NEW_PASSWORD
) -> Awaitable[httpx.Response]:
    """POST /api/auth/password the way the SPA does."""
    return client.post(
        "/api/auth/password",
        json={"currentPassword": current, "newPassword": new},
        headers=csrf_headers(client),
    )


@dataclass(frozen=True, slots=True)
class _Rejected:
    """What ``verify_password_async`` returns for a password that does not match."""

    is_valid: bool = False
    needs_rehash: bool = False


class _VerifySpy:
    """A stand-in for ``verify_password_async`` that counts calls and always refuses.

    Counting is the point: the criterion for both routes is that a refused attempt never
    reaches argon2. Replacing the function rather than wrapping it also keeps a fifty-attempt
    loop at milliseconds instead of a second and a half.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, *args: object, **kwargs: object) -> _Rejected:
        del args, kwargs
        self.calls += 1
        return _Rejected()


def watch_argon2(monkeypatch: pytest.MonkeyPatch) -> _VerifySpy:
    """Install the spy. Called **after** signing in, so the sign-in is the real path."""
    spy = _VerifySpy()
    monkeypatch.setattr(auth_router, "verify_password_async", spy)
    return spy


# ---------------------------------------------------------------------------
# /auth/step-up is no longer an unmetered password oracle
# ---------------------------------------------------------------------------
async def test_step_up_is_429_once_the_reauth_budget_is_spent(
    panel: Panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange - a signed-in operator whose cookie an attacker now holds
    await signed_in(panel)
    spy = watch_argon2(monkeypatch)

    # Act - the reviewer's probe: grind the password through the step-up route
    codes = [
        (await step_up(panel.http, password=_WRONG)).status_code
        for _ in range(REAUTH_MAX_PER_SESSION)
    ]
    refused = await step_up(panel.http, password=_WRONG)

    # Assert - the budget answers, and the refusal costs no argon2
    assert codes == [403] * REAUTH_MAX_PER_SESSION
    assert refused.status_code == 429
    # Its own code, not the login route's: only this refusal has a remedy the operator can
    # act on, and the SPA renders that remedy from the code.
    assert refused.json()["error"]["code"] == AdminErrorCode.REAUTH_RATE_LIMITED.value
    assert refused.headers["retry-after"] == str(REAUTH_WINDOW_S)
    assert spy.calls == REAUTH_MAX_PER_SESSION
    assert panel.limits.keys_for(RateLimitPurpose.REAUTH)


async def test_step_up_charges_its_counter_before_argon2_not_after(
    panel: Panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A limiter that runs after the hash *is* the vector it was added to prevent."""
    # Arrange
    await signed_in(panel)
    spy = watch_argon2(monkeypatch)

    # Act - well past the ceiling
    for _ in range(REAUTH_MAX_PER_SESSION + 20):
        await step_up(panel.http, password=_WRONG)

    # Assert - the hashing stops the moment the budget does
    assert spy.calls == REAUTH_MAX_PER_SESSION


# ---------------------------------------------------------------------------
# /auth/password is the same oracle with a different body
# ---------------------------------------------------------------------------
async def test_password_change_is_429_once_the_reauth_budget_is_spent(
    panel: Panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    await signed_in(panel)
    spy = watch_argon2(monkeypatch)

    # Act
    codes = [
        (await change_password(panel.http, current=_WRONG)).status_code
        for _ in range(REAUTH_MAX_PER_SESSION)
    ]
    refused = await change_password(panel.http, current=_WRONG)

    # Assert
    assert codes == [403] * REAUTH_MAX_PER_SESSION
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == AdminErrorCode.REAUTH_RATE_LIMITED.value
    assert spy.calls == REAUTH_MAX_PER_SESSION
    assert panel.limits.keys_for(RateLimitPurpose.REAUTH)


async def test_the_two_reauth_routes_share_one_budget(
    panel: Panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The counters are keyed by session, not by route, so a second door is not a refill."""
    # Arrange
    await signed_in(panel)
    watch_argon2(monkeypatch)

    # Act - spend the whole budget on step-up, then knock on the other door
    for _ in range(REAUTH_MAX_PER_SESSION):
        await step_up(panel.http, password=_WRONG)
    spillover = await change_password(panel.http, current=_WRONG)

    # Assert
    assert spillover.status_code == 429


async def test_a_correct_reauth_gives_the_session_its_charge_back(panel: Panel) -> None:
    """Reserved before argon2, refunded after it verifies. Only failures accumulate.

    The charge still has to *happen* first — the limiter cannot know the attempt was honest
    until the hash it is protecting has already run — so this asserts the net, not the
    absence of a write. §12.1 T2 requires a step-up per reveal, purge, block, force-deliver
    and config commit, and charging the correct ones is what made a busy incident 429 the
    operator handling it.
    """
    # Arrange
    await signed_in(panel)

    # Act - one real, successful step-up, through the real hasher
    granted = await step_up(panel.http, password=PASSWORD)

    # Assert - granted; the session budget is untouched, the account-wide cap is not
    assert granted.status_code == 200
    assert set(panel.limits.scoped(RateLimitPurpose.REAUTH, "ses").values()) == {0}
    assert set(panel.limits.scoped(RateLimitPurpose.REAUTH, "usr").values()) == {1}


# ---------------------------------------------------------------------------
# Why the re-auth budget is its own, and not the login one
# ---------------------------------------------------------------------------
async def test_grinding_a_step_up_cannot_lock_the_operator_out_of_signing_in(
    panel: Panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole argument for a separate namespace, as a test.

    A shared per-username ceiling would let a stolen cookie spend the login route's budget
    and keep the real operator out — the denial of service §12.1 T1 designed the split key to
    avoid, biting hardest during the incident that motivated the theft.
    """
    # Arrange
    await signed_in(panel)
    login_counters = dict(panel.limits.keys_for(RateLimitPurpose.LOGIN))
    spy = watch_argon2(monkeypatch)

    # Act - burn the entire re-auth budget and then some
    for _ in range(REAUTH_MAX_PER_SESSION + 5):
        await step_up(panel.http, password=_WRONG)

    # Assert - re-auth is shut, the login counters never moved, and signing in still works
    assert (await step_up(panel.http, password=_WRONG)).status_code == 429
    assert spy.calls == REAUTH_MAX_PER_SESSION
    assert panel.limits.keys_for(RateLimitPurpose.LOGIN) == login_counters
    monkeypatch.undo()
    assert (await sign_in(panel.http)).status_code == 200


async def test_a_limiter_outage_refuses_a_step_up_rather_than_waving_it_through() -> None:
    """Fail closed here too: no working limiter means unlimited argon2 behind one cookie."""
    # Arrange
    async with open_panel() as panel:
        await signed_in(panel)
        panel.limits.is_down = True

        # Act - the *correct* password, which an unmetered route would have granted
        response = await step_up(panel.http, password=PASSWORD)

    # Assert
    assert response.status_code == 503
    assert response.json()["error"]["code"] == AdminErrorCode.SERVICE_UNAVAILABLE.value


# ---------------------------------------------------------------------------
# The limiter itself
# ---------------------------------------------------------------------------
class _MemoryStore:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def increment(self, key: str, *, ttl_s: int) -> int:
        return await self.increment_by(key, 1, ttl_s=ttl_s)

    async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
        self.counts[key] = self.counts.get(key, 0) + amount
        self.ttls[key] = ttl_s
        return self.counts[key]

    async def refund(self, key: str, *, ttl_s: int) -> None:
        self.counts[key] = max(0, self.counts.get(key, 0) - 1)
        self.ttls[key] = ttl_s


class _BrokenStore:
    async def increment(self, key: str, *, ttl_s: int) -> int:
        raise ConnectionError("redis is unreachable")

    async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
        raise ConnectionError("redis is unreachable")

    async def refund(self, key: str, *, ttl_s: int) -> None:
        raise ConnectionError("redis is unreachable")


def _by_purpose(store: _MemoryStore, purpose: RateLimitPurpose) -> dict[str, int]:
    return {key: count for key, count in store.counts.items() if f":{purpose.value}:" in key}


async def test_the_two_purposes_never_share_a_key() -> None:
    # Arrange
    store = _MemoryStore()

    # Act - same operator, both purposes
    await check_login_rate_limit(store, username=USERNAME, client_ip=_IP, now=NOW)
    await check_reauth_rate_limit(store, username=USERNAME, session_id=_SESSION_ID, now=NOW)

    # Assert - four keys, two namespaces, nothing spendable across them
    assert len(store.counts) == 4
    assert len(_by_purpose(store, RateLimitPurpose.LOGIN)) == 2
    assert len(_by_purpose(store, RateLimitPurpose.REAUTH)) == 2
    assert set(store.counts.values()) == {1}


async def test_the_reauth_limiter_keeps_the_username_and_the_session_out_of_the_key() -> None:
    """Both identifiers are hashed: Redis keys end up in ``KEYS`` dumps and support tickets."""
    store = _MemoryStore()

    await check_reauth_rate_limit(store, username="ceo.of.hbd", session_id=_SESSION_ID, now=NOW)

    assert store.counts
    assert all("ceo.of.hbd" not in key for key in store.counts)
    assert all(str(_SESSION_ID) not in key for key in store.counts)


async def test_the_reauth_ceiling_catches_one_account_ground_across_many_sessions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The per-session budget is escapable by opening a new session; this is what is not.

    Opening one costs the password, so this ceiling is out of an attacker's reach — but it
    is the arithmetic that keeps "how much argon2 can one account buy in a window" a finite
    number rather than a hope, so it is asserted rather than assumed.
    """
    # Arrange
    store = _MemoryStore()
    limits = ReauthRateLimits(window_s=REAUTH_WINDOW_S, max_per_session=2, max_per_username=4)

    # Act
    with caplog.at_level(logging.WARNING, logger="hbd.admin.security.ratelimit"):
        decisions = [
            await check_reauth_rate_limit(
                store,
                username=USERNAME,
                session_id=uuid4(),
                now=NOW,
                limits=limits,
            )
            for _ in range(5)
        ]

    # Assert - the ceiling trips, and the WARNING names which budget it was
    assert [decision.is_allowed for decision in decisions] == [True, True, True, True, False]
    assert decisions[-1].scope is RateLimitScope.USERNAME
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert getattr(warnings[0], "rate_limit_purpose", None) == RateLimitPurpose.REAUTH.value
    assert getattr(warnings[0], "admin_username", None) == USERNAME


async def test_the_reauth_limiter_fails_closed() -> None:
    decision = await check_reauth_rate_limit(
        _BrokenStore(), username=USERNAME, session_id=_SESSION_ID, now=NOW
    )

    assert decision.is_allowed is False
    assert decision.outcome is RateLimitOutcome.BACKEND_UNAVAILABLE
    assert decision.retry_after_s == REAUTH_WINDOW_S


def test_the_reauth_limiter_offers_no_session_exemption() -> None:
    """Every caller here already holds a session; an exemption would exempt the thief too."""
    parameters = inspect.signature(check_reauth_rate_limit).parameters

    assert "is_session_exempt" not in parameters


def test_the_reauth_ceilings_are_stated_rather_than_inherited() -> None:
    """A separate budget only means something if it is a different, deliberate number."""
    assert (REAUTH_MAX_PER_SESSION, REAUTH_MAX_PER_USERNAME) == (10, 120)
    # The session budget counts failures only, so it sits at the login route's strict
    # ceiling rather than above it; the account-wide cap is the one that had to grow, since
    # it keeps every correct step-up an incident needs.
    assert REAUTH_MAX_PER_SESSION == LOGIN_MAX_PER_USER_IP
    assert REAUTH_MAX_PER_USERNAME > LOGIN_MAX_PER_USERNAME
    assert REAUTH_WINDOW_S == 900


# ---------------------------------------------------------------------------
# What the login route costs the database before its limiter answers
# ---------------------------------------------------------------------------
@contextmanager
def _recorded_sql(engine: AsyncEngine) -> Iterator[list[str]]:
    """Every statement the engine executes inside the block, in order."""
    statements: list[str] = []

    def _on_execute(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del conn, cursor, parameters, context, executemany
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _on_execute)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _on_execute)


def _reads_of(table: str, statements: list[str]) -> int:
    return sum(1 for statement in statements if table in statement)


async def test_a_rate_limited_login_reads_at_most_the_session_it_was_handed(
    panel: Panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Characterisation, not a regression: this already held, and it must keep holding.

    The session lookup that decides §12.1 T1's exemption cannot move after the limiter — the
    limiter's answer depends on it — but it is reached only when the request actually carries
    a session cookie. An attacker who sends none therefore costs zero queries once the window
    is spent, and one indexed ``admin_sessions`` read (never a second one on ``admin_users``)
    if they bother to attach a junk cookie.
    """
    # Arrange - spend the login window
    await create_account(panel.container)
    watch_argon2(monkeypatch)
    for _ in range(LOGIN_MAX_PER_USER_IP):
        await sign_in(panel.http, password=_WRONG)
    panel.http.cookies.clear()

    # Act
    with _recorded_sql(panel.container.engine) as cookieless:
        assert (await sign_in(panel.http, password=_WRONG)).status_code == 429
    panel.http.cookies.set(_SESSION_COOKIE, "x" * 43, domain="127.0.0.1")
    with _recorded_sql(panel.container.engine) as with_junk_cookie:
        assert (await sign_in(panel.http, password=_WRONG)).status_code == 429

    # Assert
    assert _reads_of("admin_users", cookieless) == 0
    assert _reads_of("admin_sessions", cookieless) == 0
    assert _reads_of("admin_users", with_junk_cookie) == 0
    assert _reads_of("admin_sessions", with_junk_cookie) == 1
