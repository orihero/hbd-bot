"""The outbound pacer: the ceiling is shared, a flood wait parks everyone, Redis is optional.

Three things here are load-bearing and the rest is arithmetic:

* :func:`test_two_senders_share_one_ceiling` is why this module exists at all. A pacer whose
  counter lives in one process is a pacer that admits ``rate_per_s`` per *replica*, so the
  number an operator set to stay under Telegram's limit becomes the number that guarantees
  exceeding it. The assertion is made by driving TWO pacers against ONE store, which is what
  two workers are;
* :func:`test_a_flood_wait_parks_a_sender_that_never_saw_it` is the other half of the same
  fact: ``retry_after`` is about the bot token, so a replica that keeps sending through
  another replica's wait is deepening it;
* :func:`test_a_broken_store_still_paces_this_process` pins the degraded path. Failing open
  there is the outage the module exists to prevent, and failing closed abandons a campaign
  half-sent, so the tested behaviour is neither.

No Redis and no fakeredis: the store is a three-method protocol, so the pacer's own logic is
exercised against the in-memory implementation the module ships, and the one Redis-shaped
thing worth asserting — that the adapter issues ``INCRBY``/``EXPIRE`` in a transaction and
reads the park as a TTL rather than as a stored instant — is asserted against a fake
pipeline, exactly as ``tests/test_admin/test_ratelimit.py`` does it.

The clock is injected and ``sleep`` advances it, so a test that waits out a 600-second park
costs nothing and the assertions are on the seconds ASKED FOR, not on elapsed wall time.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator, Sequence
from typing import Final, Self, cast

import pytest
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage
from redis.asyncio import Redis

from bayram.config import ENV_PREFIX, Settings
from bayram.errors import ConfigError
from bayram.runtime.pacer import (
    DEFAULT_SEND_RATE_PER_S,
    SEND_BUDGET_KEY,
    SEND_PARK_KEY,
    InMemorySendBudgetStore,
    PacerPolicy,
    RedisSendBudgetStore,
    SendPacer,
    resolve_pacer_policy,
)

#: A quarter past a whole second, so "sleep to the next window" is 0.75 and a test that got
#: the boundary arithmetic backwards cannot pass by accident on a round number.
_START: Final[float] = 1_757_000_000.25
_LOGGER: Final[str] = "bayram.runtime.pacer"


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A developer's own ``BAYRAM_`` variables must not decide what this deployment sends at."""
    for name in tuple(os.environ):
        if name.startswith(ENV_PREFIX):
            monkeypatch.delenv(name, raising=False)
    yield


class _Clock:
    """Wall time a test can drive. ``sleep`` advances it, so a boundary costs no wall time."""

    def __init__(self, *, start: float = _START) -> None:
        self.now = start
        #: Every sleep the pacer asked for, in order. The whole point of the pacer is WHEN
        #: it waits and for how long, so this list is the assertion in most tests below.
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class _BrokenStore:
    """Redis is down. Every call raises, which is what the degraded path must survive."""

    def __init__(self) -> None:
        self.calls = 0

    async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
        self.calls += 1
        raise ConnectionError("redis is unreachable")

    async def set_park(self, key: str, *, ttl_s: int) -> None:
        self.calls += 1
        raise ConnectionError("redis is unreachable")

    async def park_remaining_s(self, key: str) -> float:
        self.calls += 1
        raise ConnectionError("redis is unreachable")


def _pacer(
    clock: _Clock,
    *,
    rate_per_s: int = 3,
    store: InMemorySendBudgetStore | _BrokenStore | None = None,
) -> SendPacer:
    return SendPacer(
        store if store is not None else InMemorySendBudgetStore(monotonic=clock.time),
        policy=PacerPolicy(rate_per_s=rate_per_s),
        now=clock.time,
        sleep=clock.sleep,
    )


def _flood(retry_after: int) -> TelegramRetryAfter:
    return TelegramRetryAfter(
        method=SendMessage(chat_id=1, text="happy birthday"),
        message="Too Many Requests: retry after",
        retry_after=retry_after,
    )


# ---------------------------------------------------------------------------
# The ceiling
# ---------------------------------------------------------------------------
async def test_the_rate_is_admitted_without_waiting_and_the_next_send_waits_out_the_second() -> (
    None
):
    clock = _Clock()
    pacer = _pacer(clock, rate_per_s=3)

    for _ in range(3):
        await pacer.acquire()

    assert clock.slept == []

    await pacer.acquire()

    # 0.75 to the next whole second, not a full second and not zero: the window is fixed and
    # keyed on the wall-clock second, so the wait is to the BOUNDARY.
    assert clock.slept == [0.75]
    assert clock.now == pytest.approx(_START + 0.75)


async def test_the_budget_starts_over_in_the_next_second() -> None:
    clock = _Clock()
    pacer = _pacer(clock, rate_per_s=2)

    await pacer.acquire()
    await pacer.acquire()
    clock.now += 1.0  # a second passes while the caller is doing its own work

    await pacer.acquire()
    await pacer.acquire()

    assert clock.slept == []


async def test_two_senders_share_one_ceiling() -> None:
    """TWO pacers, ONE store: the shape of two worker replicas on one Redis.

    If the counter were per process this would admit four sends in one second at a
    configured rate of two, which is precisely the doubling that makes the operator's number
    a lie. The assertion is that the third acquire — whichever process makes it — waits.
    """
    clock = _Clock()
    store = InMemorySendBudgetStore(monotonic=clock.time)
    worker_a = _pacer(clock, rate_per_s=2, store=store)
    worker_b = _pacer(clock, rate_per_s=2, store=store)

    await worker_a.acquire()
    await worker_b.acquire()
    assert clock.slept == []

    await worker_b.acquire()

    assert clock.slept == [0.75]


async def test_a_refused_send_still_charges_the_second_it_was_refused_in() -> None:
    """The overspill is charged and then abandoned with its window; it never carries over.

    The charge happens before the answer is known — the inbound throttle's rule, for the
    same reason — so the second a caller was pushed out of is fuller than its ceiling. What
    must NOT happen is that overspill following it into the next window, which would turn
    one burst into a permanently shrinking budget.
    """
    clock = _Clock()
    pacer = _pacer(clock, rate_per_s=2)

    for _ in range(3):
        await pacer.acquire()
    assert clock.slept == [0.75]

    # The window it woke into is untouched by the three charges made in the previous one.
    await pacer.acquire()

    assert clock.slept == [0.75]


# ---------------------------------------------------------------------------
# The park
# ---------------------------------------------------------------------------
async def test_a_flood_wait_parks_a_sender_that_never_saw_it() -> None:
    """``retry_after`` is a statement about the token, so it binds every process."""
    clock = _Clock()
    store = InMemorySendBudgetStore(monotonic=clock.time)
    worker_a = _pacer(clock, store=store)
    worker_b = _pacer(clock, store=store)

    parked_s = await worker_a.park_after_flood(_flood(30))
    await worker_b.acquire()

    assert parked_s == 31.0
    assert clock.slept == [31.0]


async def test_the_park_is_the_wait_plus_a_cushion_and_is_what_the_job_defers_by() -> None:
    """Telegram's number is the earliest the wait MIGHT be over, so we resume after it."""
    clock = _Clock()
    pacer = _pacer(clock)

    assert await pacer.park_after_flood(_flood(5)) == 6.0


async def test_an_absurd_retry_after_is_capped_rather_than_stalling_every_campaign() -> None:
    clock = _Clock()
    pacer = _pacer(clock)

    assert await pacer.park_after_flood(_flood(86_400)) == 600.0


async def test_a_flood_wait_is_logged_at_warning_with_the_number_telegram_named(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = _Clock()
    pacer = _pacer(clock)

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await pacer.park_after_flood(_flood(12))

    record = next(r for r in caplog.records if "asked us to back off" in r.message)
    assert record.levelno == logging.WARNING
    assert record.retry_after == 12  # type: ignore[attr-defined]


async def test_the_park_expires_and_sending_resumes_by_itself() -> None:
    clock = _Clock()
    pacer = _pacer(clock)

    await pacer.park_after_flood(_flood(2))
    await pacer.acquire()  # waits the park out
    clock.slept.clear()

    await pacer.acquire()

    assert clock.slept == []
    assert await pacer.parked_for_s() == 0.0


# ---------------------------------------------------------------------------
# When Redis is not there
# ---------------------------------------------------------------------------
async def test_a_broken_store_still_paces_this_process(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Neither open nor closed: the send is admitted, but only after 1/rate seconds."""
    clock = _Clock()
    store = _BrokenStore()
    pacer = _pacer(clock, rate_per_s=4, store=store)

    with caplog.at_level(logging.ERROR, logger=_LOGGER):
        await pacer.acquire()

    assert clock.slept == [0.25]
    assert any("could not be charged" in record.message for record in caplog.records)


async def test_a_park_binds_this_process_even_when_it_cannot_be_published(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The moment the store is unreachable is the moment obeying a flood wait matters most.

    With no shared budget, the only thing left standing between this process and a deeper
    flood wait is its own memory of the one it already received.
    """
    clock = _Clock()
    pacer = _pacer(clock, store=_BrokenStore())

    with caplog.at_level(logging.ERROR, logger=_LOGGER):
        parked_s = await pacer.park_after_flood(_flood(9))
        remaining_s = await pacer.parked_for_s()

    assert parked_s == 10.0
    assert remaining_s == 10.0
    assert any("could not be published" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------
def test_a_pacer_that_admits_nothing_is_refused_at_construction() -> None:
    with pytest.raises(ConfigError):
        PacerPolicy(rate_per_s=0)


def test_the_rate_comes_from_settings_and_ships_under_telegrams_ceiling() -> None:
    settings = Settings(
        _env_file=None,
        telegram_bot_token="t",
        database_url="sqlite+aiosqlite:///:memory:",
        elevenlabs_api_key="k",
        llm_api_key="k",
        broadcast_send_rate_per_s=7,
    )

    assert resolve_pacer_policy(settings).rate_per_s == 7
    # 30 msg/s is where Telegram documents a bot starting to be limited, and NFR-23 caps
    # reminders plus broadcasts at half of it. A default that crept over 15 would be a
    # default that plans to exceed the budget the whole product shares.
    assert DEFAULT_SEND_RATE_PER_S == 12
    assert Settings.model_fields["broadcast_send_rate_per_s"].default <= 15


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
        return (9, True)


class _FakeRedis:
    def __init__(self, *, pttl_ms: int = -2) -> None:
        self.commands: list[tuple[str, object, object]] = []
        self._pttl_ms = pttl_ms

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        assert transaction is True
        return _FakePipeline(self.commands)

    async def set(self, name: str, value: str, ex: int | None = None) -> bool:
        self.commands.append(("set", name, ex))
        return True

    async def pttl(self, name: str) -> int:
        self.commands.append(("pttl", name, None))
        return self._pttl_ms


async def test_the_redis_adapter_increments_and_expires_in_one_transaction() -> None:
    client = _FakeRedis()
    store = RedisSendBudgetStore(cast("Redis[str]", client))

    count = await store.increment_by(f"{SEND_BUDGET_KEY}:1757000000", 1, ttl_s=2)

    assert count == 9
    assert client.commands == [
        ("incr", f"{SEND_BUDGET_KEY}:1757000000", 1),
        ("expire", f"{SEND_BUDGET_KEY}:1757000000", 2),
    ]


async def test_the_park_is_written_as_a_ttl_and_read_back_as_one() -> None:
    """No instant crosses the wire, so two workers with skewed clocks still agree."""
    client = _FakeRedis(pttl_ms=4_500)
    store = RedisSendBudgetStore(cast("Redis[str]", client))

    await store.set_park(SEND_PARK_KEY, ttl_s=31)
    remaining_s = await store.park_remaining_s(SEND_PARK_KEY)

    assert remaining_s == 4.5
    assert client.commands == [("set", SEND_PARK_KEY, 31), ("pttl", SEND_PARK_KEY, None)]


@pytest.mark.parametrize("pttl_ms", [-2, -1])
async def test_a_missing_or_immortal_park_key_is_not_a_park(pttl_ms: int) -> None:
    """PTTL answers -2 for "no key" and -1 for "no expiry"; both mean "send"."""
    store = RedisSendBudgetStore(cast("Redis[str]", _FakeRedis(pttl_ms=pttl_ms)))

    assert await store.park_remaining_s(SEND_PARK_KEY) == 0.0
