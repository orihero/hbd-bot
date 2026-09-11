"""The re-auth budget after slice 1b: keyed on the session, and refunded when it verifies.

Slice 1a metered ``/auth/step-up`` and ``/auth/password`` on ``(username, client_ip)`` at 30
per 15 minutes, charged **before** the verify and never given back. Two defects fell out of
that, and every test in the first two sections below fails against it:

* **An operator could lock themselves out of the whole panel.** Thirty wrong
  ``currentPassword`` attempts 429ed ``/auth/password`` for the rest of the window, and
  signing in again did not clear the counter, because the counter did not know what a
  session was. Since ``must_change_password`` closes every route except ``/auth/me`` and
  ``/auth/password``, a new OWNER who fat-fingered the password somebody else chose for them
  had no reachable route left at all —
  :func:`test_signing_in_again_clears_a_budget_that_mistyping_spent` is that scenario.
* **Correct step-ups were charged.** §12.1 T2 requires one per reveal, purge, force-deliver,
  block and config commit, each scoped to a single subject, so the ceiling fired hardest
  during exactly the incident it was supposed to survive —
  :func:`test_a_correct_step_up_costs_the_session_nothing` is that one.

The fix is a **session-keyed reservation that is refunded on success**, and both halves are
load-bearing:

* *session-keyed*, because minting a session costs the password, which is the one thing the
  attacker holding the stolen cookie cannot do. "Sign in again" is therefore a remedy for the
  operator and no remedy at all for the thief;
* *reserved before argon2 and refunded after*, because the CPU-exhaustion property is not
  negotiable — the charge has to land before the hash it is protecting, so the refund is the
  only place the accounting can express "that one was honest".
  :func:`test_a_caller_over_budget_is_refused_before_argon2_even_with_the_right_password`
  pins that the refund did not quietly turn the limiter into a post-hash check.

The panel harness is imported from :mod:`tests.test_admin.test_auth_ratelimit_coverage`
rather than copied: that module owns the ASGI client whose scheme lets a ``__Host-`` cookie
be replayed, and a second hand-rolled copy of it would drift.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4

import httpx
import pytest

from bayram.admin.container import AdminContainer
from bayram.admin.errors import AdminErrorCode
from bayram.admin.security.ratelimit import (
    LOGIN_MAX_PER_USER_IP,
    REAUTH_MAX_PER_SESSION,
    REAUTH_WINDOW_S,
    RateLimitPurpose,
    RateLimitScope,
    ReauthRateLimits,
    check_login_rate_limit,
    check_reauth_rate_limit,
    refund_reauth_reservation,
)
from tests.test_admin.conftest import (
    ORIGIN,
    PASSWORD,
    USERNAME,
    create_account,
    csrf_headers,
    sign_in,
)
from tests.test_admin.test_auth_ratelimit_coverage import (
    change_password,
    open_panel,
    step_up,
    watch_argon2,
)

_NOW: Final[datetime] = datetime(2026, 3, 21, 9, 0, 0, tzinfo=UTC)
_SESSION_ID: Final[UUID] = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_WRONG: Final[str] = "not-the-password"
_IP: Final[str] = "203.0.113.7"
_WINDOW_S: Final[int] = 900
_LIMITER_LOGGER: Final[str] = "bayram.admin.security.ratelimit"


# ---------------------------------------------------------------------------
# The lockout: a fresh sign-in is what the thief cannot do, so it is the remedy
# ---------------------------------------------------------------------------
async def test_signing_in_again_clears_a_budget_that_mistyping_spent() -> None:
    """A new OWNER who fat-fingers their own password is not locked out of the panel.

    ``must_change_password`` leaves exactly two reachable routes, and one of them is the one
    being 429ed, so under the old ``(username, client_ip)`` key this operator had no way
    back for fifteen minutes. Signing in again is now the way back — and it is a way back
    only for someone who knows the password, which is precisely the distinction the old key
    could not draw.
    """
    async with open_panel() as panel:
        # Arrange - the fresh OWNER of §12.6, holding a credential somebody else chose
        await create_account(panel.container, must_change_password=True)
        assert (await sign_in(panel.http)).status_code == 200

        # Act - spend the session's whole budget on the one route left open
        refusals = [
            (await change_password(panel.http, current=_WRONG)).status_code
            for _ in range(REAUTH_MAX_PER_SESSION)
        ]
        locked = await change_password(panel.http, current=_WRONG)
        assert (await sign_in(panel.http)).status_code == 200
        recovered = await change_password(panel.http, current=PASSWORD)

    # Assert - refused while that session lasted, and working again on the next one
    assert refusals == [403] * REAUTH_MAX_PER_SESSION
    assert locked.status_code == 429
    assert recovered.status_code == 200


async def test_the_refusal_tells_the_operator_how_to_clear_it() -> None:
    """A remedy an operator is not told about is fifteen minutes of waiting for nothing."""
    async with open_panel() as panel:
        # Arrange
        await create_account(panel.container)
        assert (await sign_in(panel.http)).status_code == 200

        # Act
        for _ in range(REAUTH_MAX_PER_SESSION):
            await step_up(panel.http, password=_WRONG)
        refused = await step_up(panel.http, password=_WRONG)

    # Assert
    assert refused.status_code == 429
    assert "sign in again" in refused.json()["error"]["message"]
    assert refused.json()["error"]["details"]["scope"] == str(RateLimitScope.SESSION)


async def test_a_stolen_cookie_cannot_refill_the_budget_it_spent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The thief's half of the same property: no password, so no second session, so no refill.

    Modelled the only way a stolen cookie *can* be modelled here — by continuing to use the
    session that was already issued. The budget is spent and stays spent, however many more
    requests arrive on it.
    """
    async with open_panel() as panel:
        # Arrange
        await create_account(panel.container)
        assert (await sign_in(panel.http)).status_code == 200
        spy = watch_argon2(monkeypatch)

        # Act - grind well past the ceiling on the one session the attacker holds
        for _ in range(REAUTH_MAX_PER_SESSION + 25):
            await step_up(panel.http, password=_WRONG)
        still_refused = await step_up(panel.http, password=_WRONG)

    # Assert - the hashing stopped at the ceiling and never resumed
    assert still_refused.status_code == 429
    assert spy.calls == REAUTH_MAX_PER_SESSION


# ---------------------------------------------------------------------------
# The refund: a step-up that verifies costs the session nothing
# ---------------------------------------------------------------------------
async def test_a_correct_step_up_costs_the_session_nothing() -> None:
    """§12.1 T2 wants one step-up per subject; the budget must survive an ordinary incident.

    Fifteen consecutive correct step-ups is a reveal, a purge and a handful of blocks — the
    shape of one incident, not of an attack. Under the pre-fix accounting the thirty-first
    would have been refused; under a ten-per-session budget that charged successes, the
    eleventh would have been.
    """
    async with open_panel() as panel:
        # Arrange
        await create_account(panel.container)
        assert (await sign_in(panel.http)).status_code == 200

        # Act - every one of them correct, through the real hasher
        codes = [
            (await step_up(panel.http, password=PASSWORD, subject=f"order-{index}")).status_code
            for index in range(REAUTH_MAX_PER_SESSION + 5)
        ]

        # Assert - all granted, and the session's counter is back where it started. The
        # second assertion is the one that bites: a budget merely *larger* than the incident
        # is a budget the next, longer incident still hits.
        assert codes == [200] * (REAUTH_MAX_PER_SESSION + 5)
        assert set(panel.limits.scoped(RateLimitPurpose.REAUTH, "ses").values()) == {0}


async def test_a_caller_over_budget_is_refused_before_argon2_even_with_the_right_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refund must not have turned the reservation into a check that runs after the hash.

    The correct password at the end is the load-bearing part: if the limiter had moved after
    the verify so that successes could be recognised rather than refunded, this request would
    have hashed — which is the 64 MiB, ~50 ms sink the whole ordering exists to deny.
    """
    async with open_panel() as panel:
        # Arrange
        await create_account(panel.container)
        assert (await sign_in(panel.http)).status_code == 200
        spy = watch_argon2(monkeypatch)
        for _ in range(REAUTH_MAX_PER_SESSION):
            await step_up(panel.http, password=_WRONG)
        spent = spy.calls

        # Act - the real password, arriving one attempt too late
        refused = await step_up(panel.http, password=PASSWORD)

    # Assert
    assert spent == REAUTH_MAX_PER_SESSION
    assert refused.status_code == 429
    assert spy.calls == spent


async def test_a_refund_the_store_cannot_write_does_not_fail_the_step_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refund is a courtesy, not a precondition: it changes nothing and denies nothing.

    Losing it costs the operator one attempt out of ten on this session, which signing in
    again clears — so failing the step-up over it would trade a real grant for a bookkeeping
    write. The charge simply stands, which is what is asserted here; that the loss is also an
    ERROR line rather than a silence is asserted at the limiter, in
    :func:`test_a_refund_that_cannot_be_written_is_logged_rather_than_swallowed`, because the
    admin app replaces the root handler at boot and ``caplog`` cannot see past that.
    """
    async with open_panel() as panel:
        # Arrange
        await create_account(panel.container)
        assert (await sign_in(panel.http)).status_code == 200
        monkeypatch.setattr(panel.limits, "refund", _raise_on_refund)

        # Act
        granted = await step_up(panel.http, password=PASSWORD)

        # Assert - granted, and the reservation the refund could not return is still charged
        assert granted.status_code == 200
        assert set(panel.limits.scoped(RateLimitPurpose.REAUTH, "ses").values()) == {1}


async def _raise_on_refund(key: str, *, ttl_s: int) -> None:
    del key, ttl_s
    raise ConnectionError("the limiter store is unavailable")


# ---------------------------------------------------------------------------
# The limiter itself: what the refund does and does not give back
# ---------------------------------------------------------------------------
class _MemoryStore:
    """A :class:`WindowCounterStore` that can also give a charge back."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def increment(self, key: str, *, ttl_s: int) -> int:
        return await self.increment_by(key, 1, ttl_s=ttl_s)

    async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
        del ttl_s
        self.counts[key] = self.counts.get(key, 0) + amount
        return self.counts[key]

    async def refund(self, key: str, *, ttl_s: int) -> None:
        del ttl_s
        self.counts[key] = max(0, self.counts.get(key, 0) - 1)

    def of_shape(self, marker: str) -> dict[str, int]:
        return {key: count for key, count in self.counts.items() if f":{marker}:" in key}


class _RefundBrokenStore(_MemoryStore):
    """Charges fine, cannot give anything back. The half-outage the refund has to survive."""

    async def refund(self, key: str, *, ttl_s: int) -> None:
        del key, ttl_s
        raise ConnectionError("redis is unreachable")


async def test_a_refund_that_cannot_be_written_is_logged_rather_than_swallowed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A lost refund is a real, if small, cost to the operator; it may not be invisible."""
    # Arrange
    store = _RefundBrokenStore()
    decision = await check_reauth_rate_limit(
        store, username=USERNAME, session_id=_SESSION_ID, now=_NOW
    )

    # Act
    with caplog.at_level(logging.ERROR, logger=_LIMITER_LOGGER):
        await refund_reauth_reservation(store, decision)

    # Assert - one ERROR naming the event, and the charge left standing
    lines = [record for record in caplog.records if record.name == _LIMITER_LOGGER]
    assert [record.levelno for record in lines] == [logging.ERROR]
    assert getattr(lines[0], "event", None) == "admin.ratelimit.refund_failed"
    assert set(store.of_shape("ses").values()) == {1}


async def test_the_refund_returns_the_session_counter_and_not_the_account_ceiling() -> None:
    """Which half comes back is the whole design: one is a budget, the other is a bound."""
    # Arrange
    store = _MemoryStore()

    # Act
    decision = await check_reauth_rate_limit(
        store, username=USERNAME, session_id=_SESSION_ID, now=_NOW
    )
    await refund_reauth_reservation(store, decision)

    # Assert
    assert decision.is_allowed is True
    assert set(store.of_shape("ses").values()) == {0}
    assert set(store.of_shape("usr").values()) == {1}


async def test_correct_reauths_still_count_against_the_account_wide_ceiling() -> None:
    """The bound on how much argon2 one account can buy must not count failures only.

    Otherwise a caller who knows the password — an insider, or anyone past a step-up — has
    an unmetered 64 MiB hash to call in a loop, and the module's "~11 seconds of one core"
    arithmetic stops being true.
    """
    # Arrange - a tiny ceiling, so the property is asserted rather than the default
    store = _MemoryStore()
    limits = ReauthRateLimits(window_s=_WINDOW_S, max_per_session=100, max_per_username=3)
    session = uuid4()

    # Act - three correct re-auths, every one of them refunded
    for _ in range(3):
        decision = await check_reauth_rate_limit(
            store, username=USERNAME, session_id=session, now=_NOW, limits=limits
        )
        assert decision.is_allowed is True
        await refund_reauth_reservation(store, decision)
    refused = await check_reauth_rate_limit(
        store, username=USERNAME, session_id=session, now=_NOW, limits=limits
    )

    # Assert
    assert refused.is_allowed is False
    assert refused.scope is RateLimitScope.USERNAME


async def test_a_refused_reservation_carries_nothing_to_refund() -> None:
    """A refusal that could be handed back would be a way to un-charge a failed guess."""
    # Arrange
    store = _MemoryStore()
    limits = ReauthRateLimits(window_s=_WINDOW_S, max_per_session=1, max_per_username=10)

    # Act
    await check_reauth_rate_limit(
        store, username=USERNAME, session_id=_SESSION_ID, now=_NOW, limits=limits
    )
    refused = await check_reauth_rate_limit(
        store, username=USERNAME, session_id=_SESSION_ID, now=_NOW, limits=limits
    )
    await refund_reauth_reservation(store, refused)

    # Assert - the charge that tripped the ceiling is still on the counter
    assert refused.is_allowed is False
    assert refused.refundable_key is None
    assert set(store.of_shape("ses").values()) == {2}


async def test_a_login_decision_is_never_refundable() -> None:
    """The login route charges successes on purpose; nothing here may hand that back."""
    # Arrange
    store = _MemoryStore()

    # Act
    decision = await check_login_rate_limit(store, username=USERNAME, client_ip=_IP, now=_NOW)
    await refund_reauth_reservation(store, decision)

    # Assert
    assert decision.refundable_key is None
    assert set(store.counts.values()) == {1}


async def test_two_sessions_of_one_operator_do_not_share_a_budget() -> None:
    """The strict counter names a browser, so one spent session cannot 429 another."""
    # Arrange
    store = _MemoryStore()
    limits = ReauthRateLimits(window_s=_WINDOW_S, max_per_session=1, max_per_username=10)
    spent, fresh = uuid4(), uuid4()

    # Act
    for _ in range(2):
        await check_reauth_rate_limit(
            store, username=USERNAME, session_id=spent, now=_NOW, limits=limits
        )
    other = await check_reauth_rate_limit(
        store, username=USERNAME, session_id=fresh, now=_NOW, limits=limits
    )

    # Assert
    assert other.is_allowed is True


# ---------------------------------------------------------------------------
# The code the SPA branches on
# ---------------------------------------------------------------------------
async def test_a_reauth_refusal_carries_its_own_code_not_the_login_routes(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    """``/auth/password`` is not login, and only one of the two refusals has a remedy.

    The message already said "sign in again"; the machine-readable code did not, so an SPA
    branching on it could not tell "you cannot sign in" from "this session has spent its
    re-auth budget". The key namespaces were carefully split and the taxonomy re-merged them.
    """
    # Arrange
    await create_account(container)
    await sign_in(client)

    # Act — burn the session's whole budget, then one more.
    for _ in range(REAUTH_MAX_PER_SESSION + 1):
        response = await client.post(
            "/api/auth/password",
            json={"currentPassword": "wrong", "newPassword": "a-brand-new-password-here"},
            headers=csrf_headers(client),
        )

    # Assert
    assert response.status_code == 429
    assert response.json()["error"]["code"] == AdminErrorCode.REAUTH_RATE_LIMITED.value
    assert response.headers["Retry-After"] == str(REAUTH_WINDOW_S)


async def test_the_login_route_keeps_its_own_code(
    container: AdminContainer, client: httpx.AsyncClient
) -> None:
    # Arrange
    await create_account(container)

    # Act
    for _ in range(LOGIN_MAX_PER_USER_IP + 1):
        response = await client.post(
            "/api/auth/login",
            json={"username": USERNAME, "password": "wrong"},
            headers={"Origin": ORIGIN},
        )

    # Assert
    assert response.status_code == 429
    assert response.json()["error"]["code"] == AdminErrorCode.LOGIN_RATE_LIMITED.value
