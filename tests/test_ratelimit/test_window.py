"""The inbound throttle's arithmetic, and the one rule that separates it from the admin's.

Every test here runs against :class:`InMemoryWindowCounterStore` with an injected monotonic
clock, so a window boundary is crossed by moving a number rather than by sleeping.

The single most important assertion in this file is
``test_a_counter_store_that_raises_lets_the_update_through``: this limiter FAILS OPEN, which
is the exact opposite of ``hbd.admin.security.ratelimit``'s fail-closed login limiter. Both
rules are correct for what they guard, and neither is a default anyone should flip.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hbd.config import Settings
from hbd.errors import ConfigError
from hbd.ratelimit import (
    DEFAULT_INBOUND_POLICY,
    InboundPolicy,
    InMemoryWindowCounterStore,
    check_erasure_rate,
    check_update_rate,
    claim_notice,
    resolve_inbound_policy,
)

USER_ID = 4_242
#: 09:00:00 exactly, so "seconds left in a 60s window" is a round number to assert on.
MOMENT = datetime(2026, 3, 21, 9, 0, 0, tzinfo=UTC)


class ExplodingCounterStore:
    """A store that is simply down. Structurally a ``WindowCounterStore``."""

    def __init__(self) -> None:
        self.calls = 0

    async def increment(self, key: str, *, ttl_s: int) -> int:
        self.calls += 1
        raise ConnectionError("the counter backend is unreachable")


class FakeMonotonic:
    """A monotonic clock a test can move. Seconds since an arbitrary origin."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


# ---------------------------------------------------------------------------
# The in-memory store
# ---------------------------------------------------------------------------
async def test_a_counter_climbs_within_its_window() -> None:
    # Arrange
    store = InMemoryWindowCounterStore(monotonic=FakeMonotonic())

    # Act
    counts = [await store.increment("k", ttl_s=60) for _ in range(3)]

    # Assert
    assert counts == [1, 2, 3]


async def test_a_counter_starts_over_once_its_ttl_has_passed() -> None:
    """The TTL is what makes this a *window* rather than a lifetime total."""
    # Arrange
    clock = FakeMonotonic()
    store = InMemoryWindowCounterStore(monotonic=clock)
    await store.increment("k", ttl_s=60)
    await store.increment("k", ttl_s=60)

    # Act
    clock.now += 61
    after = await store.increment("k", ttl_s=60)

    # Assert
    assert after == 1


async def test_two_keys_do_not_share_a_counter() -> None:
    # Arrange
    store = InMemoryWindowCounterStore(monotonic=FakeMonotonic())

    # Act
    await store.increment("a", ttl_s=60)
    await store.increment("a", ttl_s=60)
    other = await store.increment("b", ttl_s=60)

    # Assert
    assert other == 1


async def test_the_store_drops_expired_keys_rather_than_growing_forever() -> None:
    """A long-lived process must not accumulate a key per account per window, for ever."""
    # Arrange — a cap small enough to reach, and keys that are all dead by the time it is
    clock = FakeMonotonic()
    store = InMemoryWindowCounterStore(max_keys=4, monotonic=clock)
    for index in range(5):
        await store.increment(f"old:{index}", ttl_s=10)

    # Act — every one of those has expired; the next write is what triggers the prune
    clock.now += 11
    await store.increment("fresh", ttl_s=10)

    # Assert — the fresh key survives on its own and the dead ones are gone
    assert await store.increment("fresh", ttl_s=10) == 2
    assert await store.increment("old:0", ttl_s=10) == 1


async def test_a_full_store_of_live_keys_forgets_everything_rather_than_growing() -> None:
    """The last-resort branch: forgetting grants a fresh window, which is this module's
    failure policy anyway, and is strictly better than an unbounded dict."""
    # Arrange — every key still live, so pruning cannot reclaim anything
    store = InMemoryWindowCounterStore(max_keys=3, monotonic=FakeMonotonic())
    for index in range(5):
        await store.increment(f"live:{index}", ttl_s=600)

    # Act — one more write, which finds the map still over cap after the prune
    await store.increment("live:0", ttl_s=600)

    # Assert — the counter it had been keeping was dropped, not doubled
    assert await store.increment("live:1", ttl_s=600) == 1


# ---------------------------------------------------------------------------
# The throttle
# ---------------------------------------------------------------------------
async def test_updates_up_to_the_ceiling_are_allowed_and_the_next_one_is_not() -> None:
    # Arrange
    store = InMemoryWindowCounterStore(monotonic=FakeMonotonic())
    policy = InboundPolicy(window_s=60, max_updates=3)

    # Act
    verdicts = [
        await check_update_rate(store, telegram_user_id=USER_ID, now=MOMENT, policy=policy)
        for _ in range(4)
    ]

    # Assert
    assert [verdict.is_allowed for verdict in verdicts] == [True, True, True, False]
    assert verdicts[-1].count == 4


async def test_a_refused_update_still_counts_against_the_window() -> None:
    """A limiter that only counted what it allowed would let a caller sit on the line."""
    # Arrange
    store = InMemoryWindowCounterStore(monotonic=FakeMonotonic())
    policy = InboundPolicy(window_s=60, max_updates=1)
    for _ in range(3):
        await check_update_rate(store, telegram_user_id=USER_ID, now=MOMENT, policy=policy)

    # Act
    verdict = await check_update_rate(store, telegram_user_id=USER_ID, now=MOMENT, policy=policy)

    # Assert
    assert verdict.count == 4
    assert verdict.is_allowed is False


async def test_two_accounts_are_metered_separately() -> None:
    """The key carries the account, or one busy customer would throttle the whole bot."""
    # Arrange
    store = InMemoryWindowCounterStore(monotonic=FakeMonotonic())
    policy = InboundPolicy(window_s=60, max_updates=1)
    await check_update_rate(store, telegram_user_id=USER_ID, now=MOMENT, policy=policy)
    await check_update_rate(store, telegram_user_id=USER_ID, now=MOMENT, policy=policy)

    # Act
    other = await check_update_rate(store, telegram_user_id=99, now=MOMENT, policy=policy)

    # Assert
    assert other.is_allowed is True


async def test_the_next_window_gives_the_same_account_a_fresh_budget() -> None:
    # Arrange
    store = InMemoryWindowCounterStore(monotonic=FakeMonotonic())
    policy = InboundPolicy(window_s=60, max_updates=1)
    await check_update_rate(store, telegram_user_id=USER_ID, now=MOMENT, policy=policy)
    await check_update_rate(store, telegram_user_id=USER_ID, now=MOMENT, policy=policy)

    # Act — the wall clock moves into the next bucket, so the KEY changes
    later = await check_update_rate(
        store, telegram_user_id=USER_ID, now=MOMENT + timedelta(seconds=60), policy=policy
    )

    # Assert
    assert later.is_allowed is True
    assert later.count == 1


async def test_the_verdict_says_how_long_the_window_has_left() -> None:
    """``retry_after_s`` is the only thing that makes "slow down" actionable."""
    # Arrange
    store = InMemoryWindowCounterStore(monotonic=FakeMonotonic())
    policy = InboundPolicy(window_s=60, max_updates=1)

    # Act — 20 seconds into a 60-second window
    verdict = await check_update_rate(
        store, telegram_user_id=USER_ID, now=MOMENT + timedelta(seconds=20), policy=policy
    )

    # Assert
    assert verdict.retry_after_s == 40


async def test_a_counter_store_that_raises_lets_the_update_through() -> None:
    """FAIL OPEN. The opposite of ``hbd.admin.security.ratelimit``, and deliberately so.

    A customer must not be unable to order a song because a counter could not be written;
    an operator must not be able to log in with no working limiter. Same shape, opposite
    rule, which is why the two limiters are two modules.
    """
    # Arrange
    store = ExplodingCounterStore()

    # Act
    verdict = await check_update_rate(store, telegram_user_id=USER_ID, now=MOMENT)

    # Assert
    assert verdict.is_allowed is True
    assert store.calls == 1


# ---------------------------------------------------------------------------
# The data-subject budget
# ---------------------------------------------------------------------------
async def test_the_erasure_budget_counts_on_a_key_of_its_own() -> None:
    """A separate key, not a share of the ordinary ceiling, and that is the whole point.

    ``/privacy``, ``/forget`` and ``/support`` are exempt from the block gate and from the
    update ceiling so that a barred or throttled account can still make a data-subject
    request. Charging them against the counter that is already over its limit would hand the
    exemption back with one hand and take it away with the other.
    """
    # Arrange — an update budget already spent to the last drop.
    store = InMemoryWindowCounterStore()
    policy = InboundPolicy(max_updates=1, erasure_max_updates=2)
    for _ in range(4):
        await check_update_rate(store, telegram_user_id=USER_ID, now=MOMENT, policy=policy)

    # Act
    verdicts = [
        await check_erasure_rate(store, telegram_user_id=USER_ID, now=MOMENT, policy=policy)
        for _ in range(3)
    ]

    # Assert — two through on its own budget, the third asked to wait.
    assert [verdict.is_allowed for verdict in verdicts] == [True, True, False]


async def test_the_erasure_budget_also_fails_open_when_the_counter_cannot_be_written() -> None:
    """Same rule as every other customer-facing limiter here: a broken counter never becomes
    the reason an erasure request is refused."""
    # Arrange
    store = ExplodingCounterStore()

    # Act
    verdict = await check_erasure_rate(store, telegram_user_id=USER_ID, now=MOMENT)

    # Assert
    assert verdict.is_allowed is True
    assert store.calls == 1


# ---------------------------------------------------------------------------
# The notice budget
# ---------------------------------------------------------------------------
async def test_only_the_first_refusal_in_a_window_is_spoken() -> None:
    """Answering every refused update is its own flood — from the one account sending
    enough updates to make that a problem."""
    # Arrange
    store = InMemoryWindowCounterStore(monotonic=FakeMonotonic())

    # Act
    spoken = [
        await claim_notice(store, telegram_user_id=USER_ID, purpose="error.too_fast", now=MOMENT)
        for _ in range(4)
    ]

    # Assert
    assert spoken == [True, False, False, False]


async def test_two_refusal_reasons_have_separate_budgets() -> None:
    """Being told "too fast" must not swallow the sentence that says the account is blocked."""
    # Arrange
    store = InMemoryWindowCounterStore(monotonic=FakeMonotonic())
    await claim_notice(store, telegram_user_id=USER_ID, purpose="error.too_fast", now=MOMENT)

    # Act
    blocked = await claim_notice(
        store, telegram_user_id=USER_ID, purpose="error.blocked", now=MOMENT
    )

    # Assert
    assert blocked is True


async def test_the_notice_budget_speaks_when_it_cannot_be_read() -> None:
    """A duplicate refusal is a far smaller failure than a silent bot."""
    # Arrange
    store = ExplodingCounterStore()

    # Act
    spoken = await claim_notice(
        store, telegram_user_id=USER_ID, purpose="error.blocked", now=MOMENT
    )

    # Assert
    assert spoken is True


# ---------------------------------------------------------------------------
# The policy
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kwargs",
    [
        {"window_s": 0},
        {"max_updates": 0},
        {"block_cache_s": -1},
    ],
)
async def test_a_policy_that_cannot_be_enforced_is_refused_at_construction(
    kwargs: dict[str, int],
) -> None:
    """``window_s`` is a divisor, so a zero would be a ZeroDivisionError on every tap."""
    # Arrange / Act / Assert
    with pytest.raises(ConfigError):
        InboundPolicy(**kwargs)


async def test_the_policy_is_read_off_settings() -> None:
    # Arrange
    settings = Settings(
        _env_file=None,
        telegram_bot_token="123456:test-token-value-for-unit-tests-only",
        database_url="postgresql+asyncpg://hbd:hbd@localhost:5432/hbd_test",
        elevenlabs_api_key="k",
        llm_api_key="k",
        inbound_window_s=15,
        inbound_max_updates=7,
        inbound_block_cache_s=5,
    )

    # Act
    policy = resolve_inbound_policy(settings)

    # Assert
    assert policy == InboundPolicy(window_s=15, max_updates=7, block_cache_s=5)


async def test_an_object_that_is_not_settings_falls_back_to_the_shipped_policy() -> None:
    """``resolve_inbound_policy`` takes ``object`` on purpose — this module is a leaf and
    may not import ``hbd.config`` — so it has to survive being handed anything at all."""
    # Arrange / Act / Assert
    assert resolve_inbound_policy(None) == DEFAULT_INBOUND_POLICY
    assert resolve_inbound_policy(object()) == DEFAULT_INBOUND_POLICY
