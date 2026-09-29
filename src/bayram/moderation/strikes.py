"""Strikes, suspension and the per-account screening budget (IMAGE_VIDEO_SPEC §6.4).

**Strikes.** A block before payment is one strike; an output block (L4) or a provider refusal
(L5) is two — the request got as far as a render; a CSAM-class block is three. Three strikes
inside seven days suspend media for seven days (``media.refused.suspended``). **A CSAM-class
block suspends until an operator clears it** (``python -m bayram.tools.media unsuspend``),
whatever the count. Each strike is recorded under an event id derived from the job and the
layer, so a redelivered stage adds nothing.

**The screening budget.** ``media_screen_daily_budget`` screenings per account per UTC day
(default 10). A guard that answers without limit is an oracle: somebody can probe the policy
one word at a time. A request over the budget is refused unscreened. Counted per JOB, so a 🔁
on a busy tray re-screening the same row does not spend twice.

**Where it lives.** Redis — ``media:strikes:{tg}`` (sorted set, member per strike, scored by
time), ``media:suspended:{tg}`` (``strikes`` with a TTL, or ``csam`` with none) and
``media:screens:{tg}:{yyyymmdd}`` (a set of job ids). The ``media_jobs`` rows keep the history
(``error_code``, ``screen_categories``, ``output_categories``) that an operator reads when a
Redis restart without persistence has cleared the counters; the counters are a rate limit,
the rows are the record. :class:`MemoryStrikeStore` is the same semantics in a dict, for the
stage tests; the Redis commands are exercised by an ``integration`` test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable

__all__ = [
    "STRIKE_WINDOW",
    "STRIKE_LIMIT",
    "STRIKE_SUSPENSION",
    "PREPAY_BLOCK_STRIKES",
    "OUTPUT_BLOCK_STRIKES",
    "CSAM_STRIKES",
    "SuspensionReason",
    "Suspension",
    "StrikeStore",
    "RedisStrikeStore",
    "MemoryStrikeStore",
    "record_block",
    "strikes_key",
    "suspended_key",
    "screens_key",
]

STRIKE_WINDOW: Final[timedelta] = timedelta(days=7)
STRIKE_LIMIT: Final[int] = 3
STRIKE_SUSPENSION: Final[timedelta] = timedelta(days=7)
PREPAY_BLOCK_STRIKES: Final[int] = 1
OUTPUT_BLOCK_STRIKES: Final[int] = 2
CSAM_STRIKES: Final[int] = 3
#: The day-set outlives its day by one, so a request straddling midnight reads a live key.
_SCREENS_TTL_S: Final[int] = 2 * 86_400


class SuspensionReason(StrEnum):
    STRIKES = "strikes"
    #: Until an operator clears it — never on a timer (§6.4).
    CSAM = "csam"


@dataclass(frozen=True, slots=True)
class Suspension:
    reason: SuspensionReason


def strikes_key(telegram_user_id: int) -> str:
    return f"media:strikes:{telegram_user_id}"


def suspended_key(telegram_user_id: int) -> str:
    return f"media:suspended:{telegram_user_id}"


def screens_key(telegram_user_id: int, now: datetime) -> str:
    return f"media:screens:{telegram_user_id}:{now.strftime('%Y%m%d')}"


@runtime_checkable
class StrikeStore(Protocol):
    """The counters. Every method may raise on a Redis failure; callers decide what that means."""

    async def add_strikes(
        self, telegram_user_id: int, *, event_id: str, weight: int, now: datetime
    ) -> int:
        """Record ``weight`` strikes under ``event_id`` (idempotent). Strikes in the window."""
        ...

    async def suspend(
        self, telegram_user_id: int, *, reason: SuspensionReason, now: datetime
    ) -> None:
        """Suspend: ``strikes`` for :data:`STRIKE_SUSPENSION` from ``now``, ``csam`` until
        cleared. A ``csam`` suspension is never replaced by a ``strikes`` one."""
        ...

    async def suspension(self, telegram_user_id: int, *, now: datetime) -> Suspension | None: ...

    async def clear(self, telegram_user_id: int) -> bool:
        """An operator lifts the suspension and forgets the strikes. True if one was lifted."""
        ...

    async def count_screen(self, telegram_user_id: int, *, job_id: str, now: datetime) -> int:
        """Count ``job_id`` against today's budget (idempotent). Screenings today."""
        ...

    async def screens_today(self, telegram_user_id: int, *, now: datetime) -> int: ...


async def record_block(
    store: StrikeStore,
    telegram_user_id: int,
    *,
    event_id: str,
    weight: int,
    is_csam: bool,
    now: datetime,
) -> Suspension | None:
    """Strike for one block, and suspend when the rule says so. The suspension, if any.

    A CSAM-class suspension is written FIRST: it does not depend on the count, and a Redis
    error on the strike write must not be what skips it.
    """
    if is_csam:
        await store.suspend(telegram_user_id, reason=SuspensionReason.CSAM, now=now)
        await store.add_strikes(telegram_user_id, event_id=event_id, weight=weight, now=now)
        return Suspension(SuspensionReason.CSAM)
    count = await store.add_strikes(telegram_user_id, event_id=event_id, weight=weight, now=now)
    if count >= STRIKE_LIMIT:
        await store.suspend(telegram_user_id, reason=SuspensionReason.STRIKES, now=now)
        return Suspension(SuspensionReason.STRIKES)
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes | bytearray):
        return value.decode("utf-8", "replace")
    return str(value)


def _reason(raw: Any) -> Suspension | None:
    text = _text(raw)
    if text is None:
        return None
    try:
        return Suspension(SuspensionReason(text))
    except ValueError:
        # An unknown value is somebody's hand edit; it still suspends, and never expires
        # by our doing — the safe reading of "suspended, reason unclear".
        return Suspension(SuspensionReason.CSAM)


#: A ``strikes`` suspension, set only when the key holds nothing or another ``strikes`` —
#: one server-side step, so a ``csam`` written between a GET and a SET can never be replaced
#: by a seven-day TTL (any value but ``strikes`` reads as CSAM-class, :func:`_reason`).
_SUSPEND_FOR_STRIKES_LUA: Final[str] = """
local current = redis.call('GET', KEYS[1])
if current and current ~= ARGV[1] then
  return 0
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[2]))
return 1
"""


class RedisStrikeStore:
    """:class:`StrikeStore` over a ``redis.asyncio`` client (``ArqRedis`` is one)."""

    def __init__(self, redis: Any, *, prefix: str = "") -> None:
        self._redis = redis
        self._prefix = prefix

    async def add_strikes(
        self, telegram_user_id: int, *, event_id: str, weight: int, now: datetime
    ) -> int:
        key = f"{self._prefix}{strikes_key(telegram_user_id)}"
        stamp = now.timestamp()
        members = {f"{event_id}#{index}": stamp for index in range(weight)}
        if members:
            await self._redis.zadd(key, members, nx=True)
        await self._redis.zremrangebyscore(key, "-inf", (now - STRIKE_WINDOW).timestamp())
        await self._redis.expire(key, int(STRIKE_WINDOW.total_seconds()) + 86_400)
        return int(await self._redis.zcard(key))

    async def suspend(
        self, telegram_user_id: int, *, reason: SuspensionReason, now: datetime
    ) -> None:
        del now  # Redis keeps the clock: the TTL is relative
        key = f"{self._prefix}{suspended_key(telegram_user_id)}"
        if reason is SuspensionReason.CSAM:
            await self._redis.set(key, reason.value)
            return
        await self._redis.eval(
            _SUSPEND_FOR_STRIKES_LUA,
            1,
            key,
            reason.value,
            str(int(STRIKE_SUSPENSION.total_seconds())),
        )

    async def suspension(self, telegram_user_id: int, *, now: datetime) -> Suspension | None:
        del now  # the key's TTL is the clock
        return _reason(await self._redis.get(f"{self._prefix}{suspended_key(telegram_user_id)}"))

    async def clear(self, telegram_user_id: int) -> bool:
        removed = await self._redis.delete(
            f"{self._prefix}{suspended_key(telegram_user_id)}",
            f"{self._prefix}{strikes_key(telegram_user_id)}",
        )
        return int(removed or 0) > 0

    async def count_screen(self, telegram_user_id: int, *, job_id: str, now: datetime) -> int:
        key = f"{self._prefix}{screens_key(telegram_user_id, now)}"
        await self._redis.sadd(key, job_id)
        await self._redis.expire(key, _SCREENS_TTL_S)
        return int(await self._redis.scard(key))

    async def screens_today(self, telegram_user_id: int, *, now: datetime) -> int:
        return int(await self._redis.scard(f"{self._prefix}{screens_key(telegram_user_id, now)}"))


@dataclass
class MemoryStrikeStore:
    """The same semantics over dicts. Nothing here reads the wall clock: every expiry is read
    against the ``now`` the caller passes, so a test moves time by moving its clock."""

    strikes: dict[int, dict[str, datetime]] = field(default_factory=dict)
    suspended: dict[int, tuple[SuspensionReason, datetime | None]] = field(default_factory=dict)
    screens: dict[str, set[str]] = field(default_factory=dict)
    now: datetime | None = None

    async def add_strikes(
        self, telegram_user_id: int, *, event_id: str, weight: int, now: datetime
    ) -> int:
        self.now = now
        held = self.strikes.setdefault(telegram_user_id, {})
        for index in range(weight):
            held.setdefault(f"{event_id}#{index}", now)
        floor = now - STRIKE_WINDOW
        for member in [m for m, at in held.items() if at <= floor]:
            del held[member]
        return len(held)

    async def suspend(
        self, telegram_user_id: int, *, reason: SuspensionReason, now: datetime
    ) -> None:
        self.now = now
        current = self.suspended.get(telegram_user_id)
        if current is not None and current[0] is SuspensionReason.CSAM:
            return
        self.suspended[telegram_user_id] = (
            reason,
            None if reason is SuspensionReason.CSAM else now + STRIKE_SUSPENSION,
        )

    async def suspension(self, telegram_user_id: int, *, now: datetime) -> Suspension | None:
        self.now = now
        found = self.suspended.get(telegram_user_id)
        if found is None:
            return None
        reason, until = found
        if until is not None and until <= now:
            del self.suspended[telegram_user_id]
            return None
        return Suspension(reason)

    async def clear(self, telegram_user_id: int) -> bool:
        lifted = self.suspended.pop(telegram_user_id, None) is not None
        self.strikes.pop(telegram_user_id, None)
        return lifted

    async def count_screen(self, telegram_user_id: int, *, job_id: str, now: datetime) -> int:
        self.now = now
        day = self.screens.setdefault(screens_key(telegram_user_id, now), set())
        day.add(job_id)
        return len(day)

    async def screens_today(self, telegram_user_id: int, *, now: datetime) -> int:
        self.now = now
        return len(self.screens.get(screens_key(telegram_user_id, now), set()))
