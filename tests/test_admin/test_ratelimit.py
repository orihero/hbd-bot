"""The login limiter: it runs first, it fails closed, and it cannot be used as a lockout.

fakeredis is **not** a dependency of this repo and this change does not add one. The store
is a protocol with exactly one method, so an in-memory implementation is four lines and
tests the limiter's own logic — ordering, fail-closed, the WARNING, the window — rather than
Redis's. The one Redis-shaped thing worth asserting is that the adapter issues ``INCR`` and
``EXPIRE`` in a transaction and returns the count, and that is asserted against a fake
pipeline rather than a server.

The load-bearing test is :func:`test_a_tripped_limiter_refuses_before_argon2_is_ever_called`:
a limiter that runs after the hash is the CPU-exhaustion vector it was added to prevent, and
the only way to assert the ordering is to model the call site's order and watch the hash.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Final, Self, cast

import pytest
from redis.asyncio import Redis

from bayram.admin.security.ratelimit import (
    LOGIN_MAX_PER_USER_IP,
    LOGIN_MAX_PER_USERNAME,
    LOGIN_WINDOW_S,
    LoginRateLimits,
    RateLimitOutcome,
    RateLimitScope,
    RedisWindowCounterStore,
    check_login_rate_limit,
)

_NOW: Final[datetime] = datetime(2026, 3, 21, 9, 0, 0, tzinfo=UTC)
_USERNAME: Final[str] = "operator"
_IP: Final[str] = "203.0.113.7"


class _MemoryStore:
    """An in-memory :class:`WindowCounterStore`. Records TTLs so expiry can be asserted."""

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
    """Redis is down. Every call raises, which is what the fail-closed path must survive."""

    def __init__(self) -> None:
        self.calls = 0

    async def increment(self, key: str, *, ttl_s: int) -> int:
        self.calls += 1
        raise ConnectionError("redis is unreachable")

    async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
        self.calls += 1
        raise ConnectionError("redis is unreachable")

    async def refund(self, key: str, *, ttl_s: int) -> None:
        self.calls += 1
        raise ConnectionError("redis is unreachable")


def _keys(store: _MemoryStore, marker: str) -> list[str]:
    return [key for key in store.counts if f":{marker}:" in key]


# ---------------------------------------------------------------------------
# The strict (username, ip) counter
# ---------------------------------------------------------------------------
async def test_the_eleventh_attempt_from_one_address_is_refused() -> None:
    store = _MemoryStore()

    for attempt in range(LOGIN_MAX_PER_USER_IP):
        decision = await check_login_rate_limit(store, username=_USERNAME, client_ip=_IP, now=_NOW)
        assert decision.is_allowed is True, f"attempt {attempt + 1} should have been allowed"

    refused = await check_login_rate_limit(store, username=_USERNAME, client_ip=_IP, now=_NOW)

    assert refused.is_allowed is False
    assert refused.outcome is RateLimitOutcome.TRIPPED
    assert refused.scope is RateLimitScope.USER_IP
    assert refused.retry_after_s == LOGIN_WINDOW_S


async def test_a_tripped_limiter_refuses_before_argon2_is_ever_called() -> None:
    """The acceptance criterion, modelled as the login route's own order of operations."""
    store = _MemoryStore()
    verifications: list[str] = []

    async def _login(password: str) -> bool:
        decision = await check_login_rate_limit(store, username=_USERNAME, client_ip=_IP, now=_NOW)
        if not decision.is_allowed:
            return False
        verifications.append(password)
        return False

    for _ in range(LOGIN_MAX_PER_USER_IP + 1):
        await _login("wrong")

    assert len(verifications) == LOGIN_MAX_PER_USER_IP


async def test_a_refused_attempt_does_not_charge_the_username_ceiling() -> None:
    """Otherwise one address could drive an account to its global limit for free."""
    store = _MemoryStore()

    for _ in range(LOGIN_MAX_PER_USER_IP + 5):
        await check_login_rate_limit(store, username=_USERNAME, client_ip=_IP, now=_NOW)

    username_counters = _keys(store, "usr")
    assert len(username_counters) == 1
    assert store.counts[username_counters[0]] == LOGIN_MAX_PER_USER_IP


async def test_a_different_address_gets_its_own_bucket() -> None:
    """Keying the strict counter on the username alone would be a remote lockout button."""
    store = _MemoryStore()

    for _ in range(LOGIN_MAX_PER_USER_IP):
        await check_login_rate_limit(store, username=_USERNAME, client_ip=_IP, now=_NOW)

    decision = await check_login_rate_limit(
        store, username=_USERNAME, client_ip="198.51.100.66", now=_NOW
    )

    assert decision.is_allowed is True


async def test_an_unknown_client_ip_shares_one_conservative_bucket() -> None:
    store = _MemoryStore()

    for _ in range(LOGIN_MAX_PER_USER_IP):
        await check_login_rate_limit(store, username=_USERNAME, client_ip=None, now=_NOW)
    decision = await check_login_rate_limit(store, username=_USERNAME, client_ip=None, now=_NOW)

    assert decision.is_allowed is False


async def test_the_window_rolls_over() -> None:
    store = _MemoryStore()
    for _ in range(LOGIN_MAX_PER_USER_IP):
        await check_login_rate_limit(store, username=_USERNAME, client_ip=_IP, now=_NOW)

    later = _NOW + timedelta(seconds=LOGIN_WINDOW_S)
    decision = await check_login_rate_limit(store, username=_USERNAME, client_ip=_IP, now=later)

    assert decision.is_allowed is True
    assert set(store.ttls.values()) == {LOGIN_WINDOW_S}


async def test_varying_the_case_of_a_username_does_not_buy_a_fresh_bucket() -> None:
    store = _MemoryStore()

    await check_login_rate_limit(store, username="Operator", client_ip=_IP, now=_NOW)
    await check_login_rate_limit(store, username="operator", client_ip=_IP, now=_NOW)

    assert len(_keys(store, "uip")) == 1


async def test_the_username_never_appears_in_a_redis_key() -> None:
    store = _MemoryStore()

    await check_login_rate_limit(store, username="ceo.of.bayram", client_ip=_IP, now=_NOW)

    assert all("ceo.of.bayram" not in key for key in store.counts)


# ---------------------------------------------------------------------------
# The loose per-username ceiling
# ---------------------------------------------------------------------------
async def test_the_username_ceiling_catches_an_attack_spread_across_addresses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _MemoryStore()
    limits = LoginRateLimits(window_s=LOGIN_WINDOW_S, max_per_user_ip=2, max_per_username=4)

    with caplog.at_level(logging.WARNING, logger="bayram.admin.security.ratelimit"):
        decisions = [
            await check_login_rate_limit(
                store,
                username=_USERNAME,
                client_ip=f"198.51.100.{index}",
                now=_NOW,
                limits=limits,
            )
            for index in range(5)
        ]

    assert [decision.is_allowed for decision in decisions] == [True, True, True, True, False]
    assert decisions[-1].scope is RateLimitScope.USERNAME
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert getattr(warnings[0], "admin_username", None) == _USERNAME


async def test_a_valid_session_is_exempt_from_the_strict_counter_but_not_the_ceiling() -> None:
    store = _MemoryStore()
    limits = LoginRateLimits(window_s=LOGIN_WINDOW_S, max_per_user_ip=1, max_per_username=3)

    allowed = [
        (
            await check_login_rate_limit(
                store,
                username=_USERNAME,
                client_ip=_IP,
                now=_NOW,
                limits=limits,
                is_session_exempt=True,
            )
        ).is_allowed
        for _ in range(4)
    ]

    assert allowed == [True, True, True, False]
    assert _keys(store, "uip") == []


def test_the_shipped_defaults_are_the_ones_the_plan_names() -> None:
    limits = LoginRateLimits()

    assert (limits.window_s, limits.max_per_user_ip, limits.max_per_username) == (
        900,
        LOGIN_MAX_PER_USER_IP,
        LOGIN_MAX_PER_USERNAME,
    )
    assert (LOGIN_MAX_PER_USER_IP, LOGIN_MAX_PER_USERNAME) == (10, 100)


# ---------------------------------------------------------------------------
# Fail closed
# ---------------------------------------------------------------------------
async def test_a_dead_store_refuses_the_login_and_logs_the_outage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No working limiter means unlimited argon2 on the one unauthenticated route."""
    store = _BrokenStore()

    with caplog.at_level(logging.ERROR, logger="bayram.admin.security.ratelimit"):
        decision = await check_login_rate_limit(store, username=_USERNAME, client_ip=_IP, now=_NOW)

    assert decision.is_allowed is False
    assert decision.outcome is RateLimitOutcome.BACKEND_UNAVAILABLE
    assert decision.scope is RateLimitScope.USER_IP
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0].exc_info is not None


async def test_a_store_that_dies_on_the_second_counter_also_fails_closed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _HalfBrokenStore:
        async def increment(self, key: str, *, ttl_s: int) -> int:
            if ":usr:" in key:
                raise TimeoutError("redis timed out")
            return 1

        async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
            return await self.increment(key, ttl_s=ttl_s)

        async def refund(self, key: str, *, ttl_s: int) -> None:
            raise TimeoutError("redis timed out")

    with caplog.at_level(logging.ERROR, logger="bayram.admin.security.ratelimit"):
        decision = await check_login_rate_limit(
            _HalfBrokenStore(), username=_USERNAME, client_ip=_IP, now=_NOW
        )

    assert decision.is_allowed is False
    assert decision.outcome is RateLimitOutcome.BACKEND_UNAVAILABLE
    assert decision.scope is RateLimitScope.USERNAME


# ---------------------------------------------------------------------------
# The Redis adapter
# ---------------------------------------------------------------------------
class _FakePipeline:
    def __init__(self, commands: list[tuple[str, object, object]]) -> None:
        self._commands = commands

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    def incr(self, name: str, amount: int = 1) -> None:
        self._commands.append(("incr", name, amount))

    def expire(self, name: str, seconds: int) -> None:
        self._commands.append(("expire", name, seconds))

    async def execute(self) -> Sequence[object]:
        return (7, True)


class _FakeRedis:
    def __init__(self) -> None:
        self.commands: list[tuple[str, object, object]] = []

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        assert transaction is True
        return _FakePipeline(self.commands)


async def test_the_redis_adapter_increments_and_expires_in_one_transaction() -> None:
    client = _FakeRedis()
    store = RedisWindowCounterStore(cast("Redis[str]", client))

    count = await store.increment("bayram:admin:rl:login:uip:1:abc:203.0.113.7", ttl_s=900)

    assert count == 7
    assert client.commands == [
        ("incr", "bayram:admin:rl:login:uip:1:abc:203.0.113.7", 1),
        ("expire", "bayram:admin:rl:login:uip:1:abc:203.0.113.7", 900),
    ]
