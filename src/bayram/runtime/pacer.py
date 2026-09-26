"""The OUTBOUND pacer: how fast this deployment is allowed to talk to Telegram.

Everything else in this repository meters what comes **in** — ``bayram.ratelimit`` bounds one
customer's tap rate, ``bayram.admin.security.ratelimit`` bounds credential attempts. Nothing
has ever bounded what goes **out**, because until broadcasts there was nothing to bound: a
delivery is one message at the end of a render that took minutes, and a reminder fan-out is
a handful an hour. A campaign is fifty thousand messages that a worker will send as fast as
the event loop can dial, and Telegram answers that with a flood wait on the bot token —
which stops the ORDERS too, not just the campaign. This module is the thing that keeps a
newsletter from taking the product down.

**It is Redis-backed and that is the whole point.** The inbound throttle is deliberately
per-process because it bounds one person's thumb; this one bounds a *token*, which is a
single global resource shared by every worker replica. Two workers each holding their own
in-memory ceiling send at twice the configured rate — and the number an operator set to
stay under Telegram's limit would then be the number that guarantees exceeding it. So the
budget is a Redis fixed-window counter, keyed on the wall-clock second, in the
``RedisWindowCounterStore`` shape the admin limiter already runs on. The window is fixed
rather than sliding for the reason stated in ``bayram.ratelimit``: a burst across a boundary is
bounded by twice the rate for one second, and buying precision past that costs a sorted set
per second and is not what stands between us and a flood wait.

**A flood wait parks EVERY sender, not the one that saw it.** Telegram's ``retry_after`` is
a statement about the bot token, so a replica that keeps sending through another replica's
flood wait is deepening it — ``bayram.bot.delivery`` already records that under a 429 the
second call is the one most likely to make the wait longer. :meth:`SendPacer.park_after_
flood` therefore writes the park to Redis as a key whose TTL *is* the remaining wait, and
every :meth:`SendPacer.acquire` in every process waits it out. The TTL is the deadline: no
absolute instant is exchanged between processes, so two workers whose clocks disagree still
agree on when the park ends.

**How the send job is meant to use it** (§4.3 — the job itself is not this module's
business, but the contract only makes sense stated as a pair):

* ``await pacer.acquire()`` immediately before each send. It returns when there is budget;
* on ``TelegramRetryAfter``, ``defer = await pacer.park_after_flood(exc)``, leave the
  recipient row ``pending``, **end the chunk**, and re-enqueue the successor with
  ``_defer_by=defer``. Do not retry inside the loop;
* ``await pacer.parked_for_s()`` at the top of a chunk, so a chunk that starts inside
  another replica's park defers instead of burning its job timeout asleep. :meth:`acquire`
  waits a park out however long it is — a pacer that gave up and sent anyway would not be a
  pacer — and a chunk that sits in ``acquire`` past ``broadcast_chunk_timeout_s`` is
  cancelled with rows still claimed, which §4.4 counts as neither sent nor failed.

**When Redis cannot be reached it degrades to a per-process pace rather than failing open
or closed.** Failing open is the outage this module exists to prevent, and failing closed
would let a Redis blip abandon a campaign mid-send with half its recipients messaged. So a
store that raises is logged at ERROR and the caller is admitted after ``1 / rate_per_s``
seconds: the same rail with a weaker guarantee — N replicas pace at N times the rate
instead of unboundedly — which is a bounded, temporary, and visible loss.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, Protocol

from aiogram.exceptions import TelegramRetryAfter
from redis.asyncio import Redis

from bayram.config import Settings
from bayram.errors import ConfigError
from bayram.logging import get_logger

__all__ = [
    # Keys
    "SEND_BUDGET_KEY",
    "SEND_PARK_KEY",
    # Policy
    "DEFAULT_SEND_RATE_PER_S",
    "PacerPolicy",
    "DEFAULT_PACER_POLICY",
    "resolve_pacer_policy",
    # Seam
    "SendBudgetStore",
    "RedisSendBudgetStore",
    "InMemorySendBudgetStore",
    # The pacer
    "SendPacer",
]

_LOG = get_logger(__name__)

#: The outbound budget's key prefix; the wall-clock second is appended to it.
#:
#: **Shared by name on purpose.** Telegram's ceiling is per token, not per feature, so the
#: reminder fan-out FR-97 will add must charge this same bucket — otherwise two features
#: each stay under the limit and the token does not. Sharing the name is what makes that a
#: config change rather than a rewrite.
SEND_BUDGET_KEY: Final[str] = "bayram:send:budget"
#: The park. Its presence means "Telegram told us to stop"; its TTL is how much longer.
SEND_PARK_KEY: Final[str] = "bayram:send:park"

#: Messages per second this deployment will send, across every worker process.
#:
#: Twelve. Telegram publishes ~30 messages/second to *different* chats as the point at
#: which a bot starts being limited (and 20/minute into one group), and NFR-23 caps
#: reminders **plus** broadcasts together at half of that. Twelve is under that half and
#: leaves headroom for the reminder traffic sharing this bucket. The published figure is a
#: soft, undocumented-in-detail threshold rather than a contract, which is why the default
#: sits well below it: the cost of being wrong upwards is a flood wait on the token that
#: also stops the orders, and the cost of being wrong downwards is that a 50 000-recipient
#: campaign takes 70 minutes instead of 45.
DEFAULT_SEND_RATE_PER_S: Final[int] = 12

#: Two seconds on a one-second window: long enough that a key cannot expire out from under
#: a caller mid-window, short enough that a dead window is gone before it can be re-read.
#: The key name carries its own second, so a stale key is unreachable, not merely unused.
_BUDGET_TTL_S: Final[int] = 2

#: Added to whatever ``retry_after`` Telegram names. Its number is the earliest moment the
#: wait *might* be over, not a guarantee, and resuming exactly on it is how a flood wait
#: gets extended instead of served.
_PARK_CUSHION_S: Final[float] = 1.0
#: The longest park this module will honour. A ``retry_after`` of an hour — whether Telegram
#: means it or a proxy invented it — would otherwise silently stall every campaign and every
#: reminder with nothing in the panel to explain it. Capping means the send resumes, hits the
#: wait again if it is real, and parks again: slower, but visible and self-correcting.
_MAX_PARK_S: Final[float] = 600.0


@dataclass(frozen=True, slots=True)
class PacerPolicy:
    """Every number the outbound pacer runs on. Immutable, injected, never ambient."""

    rate_per_s: int = DEFAULT_SEND_RATE_PER_S
    budget_key: str = SEND_BUDGET_KEY
    park_key: str = SEND_PARK_KEY

    def __post_init__(self) -> None:
        """Refuse a policy that cannot be enforced, at construction rather than mid-campaign.

        ``rate_per_s`` is a divisor on the degraded path, so a zero here is a
        ``ZeroDivisionError`` the first time Redis blinks — during a send, in a worker, on
        a campaign that is half delivered. Mirrors
        :meth:`bayram.ratelimit.InboundPolicy.__post_init__` so the codebase has one idiom for
        "a policy object validates itself".
        """
        if self.rate_per_s < 1 or not self.budget_key or not self.park_key:
            raise ConfigError(
                "an outbound pacer must admit at least one send a second and be given "
                "both of its keys",
                context={
                    "rate_per_s": self.rate_per_s,
                    "budget_key": self.budget_key,
                    "park_key": self.park_key,
                },
            )


DEFAULT_PACER_POLICY: Final[PacerPolicy] = PacerPolicy()


def resolve_pacer_policy(settings: Settings) -> PacerPolicy:
    """The policy this deployment sends under. One field, read from ``Settings``.

    Typed against ``Settings`` rather than read defensively through ``getattr`` the way
    :func:`bayram.ratelimit.resolve_inbound_policy` does, because that module is a leaf that
    must not import ``bayram.config`` and this one already lives in ``bayram.runtime``, where
    every other module takes ``Settings`` directly.
    """
    return PacerPolicy(rate_per_s=settings.broadcast_send_rate_per_s)


class SendBudgetStore(Protocol):
    """Charge the second's budget, park everyone, ask how long the park has left.

    A protocol rather than a concrete client so the pacer's own decisions — the ordering,
    the boundary sleep, the degraded path — are tested with no server running, and so the
    in-memory implementation below is a class rather than a flag.

    Implementations MAY raise. :class:`SendPacer` treats any exception as "the shared budget
    is unavailable" and falls back to pacing this process alone; see the module docstring.
    """

    async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
        """Add ``amount`` to ``key`` atomically, re-arm the TTL, return the new total."""
        ...

    async def set_park(self, key: str, *, ttl_s: int) -> None:
        """Park every sender for ``ttl_s`` seconds. A later park replaces an earlier one."""
        ...

    async def park_remaining_s(self, key: str) -> float:
        """Seconds left on the park, or ``0.0`` when there is none."""
        ...


class RedisSendBudgetStore:
    """:class:`SendBudgetStore` over Redis, one round trip per operation.

    The budget half is the ``RedisWindowCounterStore`` shape verbatim: ``INCRBY`` then
    ``EXPIRE`` in a transaction, with the ``EXPIRE`` issued unconditionally so a crash
    between the two cannot leave an immortal counter. The key name already carries its
    second, so re-arming cannot let a window outlive its own bucket.

    **The park is stored as a TTL and never as an instant.** ``SET key 1 EX n`` and ``PTTL``
    mean the deadline is Redis's own clock, so two workers with skewed clocks still agree on
    when sending may resume — the mistake a stored epoch would have made possible. ``SET``
    is unconditional rather than "extend if longer": whichever flood wait arrived last is
    the freshest thing Telegram has said about this token, and that is the number to obey.
    """

    __slots__ = ("_client",)

    def __init__(self, client: Redis[str]) -> None:
        self._client = client

    async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.incr(key, amount)
            pipe.expire(key, ttl_s)
            results = await pipe.execute()
        return int(results[0])

    async def set_park(self, key: str, *, ttl_s: int) -> None:
        await self._client.set(key, "1", ex=ttl_s)

    async def park_remaining_s(self, key: str) -> float:
        # PTTL answers -2 for "no such key" and -1 for "no expiry"; both mean "not parked"
        # here, the second because this module never writes the key without one.
        remaining_ms = int(await self._client.pttl(key))
        return remaining_ms / 1000.0 if remaining_ms > 0 else 0.0


class InMemorySendBudgetStore:
    """Per-process counters, for the tests and for a deployment with no Redis at all.

    ``use_fake_providers`` mode and the whole unit suite run without Redis, so a pacer that
    could only be constructed against a server would be a pacer that is switched off exactly
    where a developer would notice it misbehaving. What it does NOT do is the thing the
    Redis store exists for: two processes holding one of these each send at twice the rate.
    Never wire it into a multi-replica deployment.

    Keys carry their own second and expire on read, so the map cannot grow past the handful
    of seconds in flight.
    """

    __slots__ = ("_counters", "_monotonic", "_park_until")

    def __init__(self, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        #: key -> (count, expiry on the monotonic clock).
        self._counters: dict[str, tuple[int, float]] = {}
        self._park_until: dict[str, float] = {}
        #: Monotonic, never wall time: an expiry must not move when NTP steps the clock.
        #: The *window* index in the key still comes from the caller's wall clock, which is
        #: what makes two processes agree on a bucket — two clocks, two questions.
        self._monotonic = monotonic

    async def increment_by(self, key: str, amount: int, *, ttl_s: int) -> int:
        now = self._monotonic()
        self._counters = {name: value for name, value in self._counters.items() if value[1] > now}
        count, expires_at = self._counters.get(key, (0, 0.0))
        if expires_at <= now:
            count, expires_at = 0, now + ttl_s
        self._counters[key] = (count + amount, expires_at)
        return count + amount

    async def set_park(self, key: str, *, ttl_s: int) -> None:
        self._park_until[key] = self._monotonic() + ttl_s

    async def park_remaining_s(self, key: str) -> float:
        return max(0.0, self._park_until.get(key, 0.0) - self._monotonic())


class SendPacer:
    """Admits at most ``rate_per_s`` outbound sends per second across every worker process.

    One instance per job is fine and one per process is fine: the state that matters lives
    in the store, and the only thing held here is the local echo of a park, which exists so
    that a process that saw a flood wait keeps honouring it even if Redis is unreachable at
    the moment it tries to publish it.
    """

    __slots__ = ("_local_park_until", "_now", "_policy", "_sleep", "_store")

    def __init__(
        self,
        store: SendBudgetStore,
        *,
        policy: PacerPolicy = DEFAULT_PACER_POLICY,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._store = store
        self._policy = policy
        #: Wall clock, because the window index is what two processes must agree on and a
        #: monotonic clock is meaningless across them. Injected so a test can drive a second
        #: boundary without spending one.
        self._now = now
        self._sleep = sleep
        #: The park as this process last knew it, on the same clock. Only ever consulted
        #: alongside the store's answer, and only load-bearing while the store is down.
        self._local_park_until = 0.0

    async def acquire(self) -> None:
        """Return when this process may send one message. Sleeps until it may.

        The budget is charged **before** the answer is known, exactly as the inbound
        throttle charges a refused update: a limiter that only counted what it admitted
        would let a caller sit on the line forever. The overspill costs nothing, because the
        retry charges the NEXT second's key and this second's excess expires with it.
        """
        while True:
            parked_s = await self.parked_for_s()
            if parked_s > 0.0:
                await self._sleep(parked_s)
                continue
            now = self._now()
            key = f"{self._policy.budget_key}:{int(now)}"
            try:
                count = await self._store.increment_by(key, 1, ttl_s=_BUDGET_TTL_S)
            except Exception:
                # Deliberately broad, and deliberately still pacing: the store is a protocol
                # whose implementations raise whatever their client raises. Admitting freely
                # here is the flood wait this module exists to prevent; refusing would
                # abandon a half-sent campaign. See the module docstring.
                _LOG.exception(
                    "the outbound budget could not be charged; pacing this process alone",
                    extra={"budget_key": key, "rate_per_s": self._policy.rate_per_s},
                )
                await self._sleep(1.0 / self._policy.rate_per_s)
                return
            if count <= self._policy.rate_per_s:
                return
            await self._sleep(_seconds_to_next_second(now))

    async def parked_for_s(self) -> float:
        """How much longer nothing may be sent. ``0.0`` when the pacer is not parked.

        The maximum of what the store says and what this process last wrote, so a park
        survives the store becoming unreachable a moment after it was published — the case
        where obeying it matters most, because an unreachable Redis is also when the shared
        budget has stopped bounding anything.
        """
        remaining = max(0.0, self._local_park_until - self._now())
        try:
            shared = await self._store.park_remaining_s(self._policy.park_key)
        except Exception:
            _LOG.exception(
                "the outbound park could not be read; only this process's own park applies",
                extra={"park_key": self._policy.park_key},
            )
            return remaining
        return max(remaining, shared)

    async def park(self, seconds: float) -> float:
        """Stop every sender for ``seconds`` (plus a cushion). Returns what was parked.

        The return value is the number the caller defers its successor job by, so the
        cushion and the cap are applied once, here, rather than being re-derived by each
        call site out of a raw ``retry_after``.
        """
        parked_s = min(max(seconds, 0.0) + _PARK_CUSHION_S, _MAX_PARK_S)
        ttl_s = math.ceil(parked_s)
        self._local_park_until = self._now() + parked_s
        try:
            await self._store.set_park(self._policy.park_key, ttl_s=ttl_s)
        except Exception:
            _LOG.exception(
                "the outbound park could not be published; it binds this process only",
                extra={"park_key": self._policy.park_key, "parked_s": parked_s},
            )
        return parked_s

    async def park_after_flood(self, exc: TelegramRetryAfter) -> float:
        """Park because Telegram said so. The only intended caller of :meth:`park`.

        Logged at WARNING and not at ERROR: a flood wait is Telegram working as documented,
        and the operator action it calls for is lowering
        ``BAYRAM_BROADCAST_SEND_RATE_PER_S`` — which is a decision, not an incident.
        """
        parked_s = await self.park(float(exc.retry_after))
        _LOG.warning(
            "telegram asked us to back off; every sender is parked",
            extra={
                "retry_after": exc.retry_after,
                "parked_s": parked_s,
                "rate_per_s": self._policy.rate_per_s,
            },
        )
        return parked_s


def _seconds_to_next_second(now: float) -> float:
    """How long until the budget's next window opens. Never zero, or the retry is a spin."""
    return 1.0 - (now - math.floor(now))
