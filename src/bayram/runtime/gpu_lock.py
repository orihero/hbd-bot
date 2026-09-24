"""The GPU slot: one outstanding ``/generate`` from bayram at a time (IMAGE_VIDEO_SPEC §3.4).

The gateway runs one job at a time and has no per-job cancel (§4.2), so bayram keeps its own
queue in front of it rather than stacking POSTs the gateway would serialise anyway — a stacked
POST is a render we can no longer withdraw when its job is failed by the deadline sweep.

**The lock** is ``media:gpu:lock`` = ``SET NX PX 120000`` holding the ``media_attempts.id`` that
owns it. The two-minute TTL covers only the window between acquiring and the POST returning;
**only after the POST returns a remote id** is it extended to the render timeout, and every
``media_poll`` renews it. **Renew and release are a Lua compare-and-set on the attempt id**, so
a late poll or fetch from an OLD attempt — one the deadline sweep already gave up on, whose
lock expired and was taken by the next attempt — can neither extend nor delete the new owner's
lock. A plain ``DEL`` there would let two renders share the GPU.

**The fair queue** is the sorted set ``media:gpu:queue``, member ``{job_id}:{variant}`` (so an
image's two variants both queue), scored by ``paid_at`` then variant. Only the head may take the
lock; everyone else re-enqueues its ``media_submit`` with the next ``submit_seq`` 15 s later.
The member is removed in the same code path that makes the variant or the job terminal, and
``media_sweep`` drops any member whose job is terminal (§3.4). Customer-before-marketing
priority (O11) is a gateway change (G5), not something this queue can do: it only orders
bayram's own jobs.

The Redis side is behind :class:`GpuSlotStore` so the stage tests run over
:class:`MemoryGpuSlotStore` — the same semantics, in a dict — and the Lua is exercised against
a real Redis by an ``integration`` test.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Protocol, runtime_checkable
from uuid import UUID

__all__ = [
    "GPU_LOCK_KEY",
    "GPU_QUEUE_KEY",
    "GPU_LOCK_ACQUIRE_TTL_MS",
    "GpuSlotStore",
    "RedisGpuSlotStore",
    "MemoryGpuSlotStore",
    "queue_member",
    "parse_queue_member",
    "queue_score",
]

GPU_LOCK_KEY: Final[str] = "media:gpu:lock"
GPU_QUEUE_KEY: Final[str] = "media:gpu:queue"

#: §3.4: the acquire-to-POST window. Short, so a worker that dies holding it frees the GPU in
#: two minutes rather than after a whole render timeout.
GPU_LOCK_ACQUIRE_TTL_MS: Final[int] = 120_000

#: Variants per job the score leaves room for. ``outputs_requested`` is CHECKed 1..4.
_VARIANT_SLOTS: Final[int] = 10

# KEYS[1] = lock key; ARGV[1] = holder; ARGV[2] = ttl ms. 1 when the holder matched.
_RENEW_LUA: Final[str] = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

# KEYS[1] = lock key; ARGV[1] = holder. 1 when the holder matched and the key was deleted.
_RELEASE_LUA: Final[str] = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


def queue_member(job_id: UUID | str, variant: int) -> str:
    return f"{job_id}:{variant}"


def parse_queue_member(member: str) -> tuple[UUID, int] | None:
    """``(job_id, variant)``, or ``None`` for a member this module did not write."""
    head, _, tail = member.rpartition(":")
    try:
        return UUID(head), int(tail)
    except ValueError:
        return None


def queue_score(paid_at: datetime, variant: int) -> float:
    """Earlier payment first, then variant 0 before 1. Millisecond resolution."""
    return float(int(paid_at.timestamp() * 1000) * _VARIANT_SLOTS + variant)


@runtime_checkable
class GpuSlotStore(Protocol):
    """The lock and the fair queue. Every method may raise on a Redis failure."""

    async def acquire(self, holder: str, *, ttl_ms: int) -> bool:
        """Take the lock iff nobody holds it. True when THIS call took it."""
        ...

    async def renew(self, holder: str, *, ttl_ms: int) -> bool:
        """Extend the lock iff ``holder`` still owns it (compare-and-set)."""
        ...

    async def release(self, holder: str) -> bool:
        """Delete the lock iff ``holder`` still owns it (compare-and-set)."""
        ...

    async def holder(self) -> str | None: ...

    async def join(self, member: str, score: float) -> None:
        """Enter the queue; a member already in it keeps its place (``ZADD NX``)."""
        ...

    async def leave(self, *members: str) -> None: ...

    async def rank(self, member: str) -> int | None:
        """0 at the head; ``None`` when not queued."""
        ...

    async def members(self) -> tuple[str, ...]:
        """Every member, head first."""
        ...


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes | bytearray):
        return value.decode("utf-8", "replace")
    return str(value)


class RedisGpuSlotStore:
    """:class:`GpuSlotStore` over a ``redis.asyncio`` client (``ArqRedis`` is one).

    ``prefix`` exists for the integration test, which must not touch a live deployment's keys.
    """

    def __init__(self, redis: Any, *, prefix: str = "") -> None:
        self._redis = redis
        self._lock_key = f"{prefix}{GPU_LOCK_KEY}"
        self._queue_key = f"{prefix}{GPU_QUEUE_KEY}"

    async def acquire(self, holder: str, *, ttl_ms: int) -> bool:
        return bool(await self._redis.set(self._lock_key, holder, nx=True, px=ttl_ms))

    async def renew(self, holder: str, *, ttl_ms: int) -> bool:
        result = await self._redis.eval(_RENEW_LUA, 1, self._lock_key, holder, ttl_ms)
        return bool(int(result or 0))

    async def release(self, holder: str) -> bool:
        result = await self._redis.eval(_RELEASE_LUA, 1, self._lock_key, holder)
        return bool(int(result or 0))

    async def holder(self) -> str | None:
        return _text(await self._redis.get(self._lock_key))

    async def join(self, member: str, score: float) -> None:
        await self._redis.zadd(self._queue_key, {member: score}, nx=True)

    async def leave(self, *members: str) -> None:
        if members:
            await self._redis.zrem(self._queue_key, *members)

    async def rank(self, member: str) -> int | None:
        found = await self._redis.zrank(self._queue_key, member)
        return None if found is None else int(found)

    async def members(self) -> tuple[str, ...]:
        raw = await self._redis.zrange(self._queue_key, 0, -1)
        return tuple(text for item in raw if (text := _text(item)) is not None)


@dataclass
class MemoryGpuSlotStore:
    """The same semantics over a dict, for tests and the offline demo.

    The lock's TTL is honoured against ``time.monotonic`` (or :attr:`now_ms`, when a test sets
    it), so "a worker died holding the lock and it expired" is assertable too.
    """

    lock: tuple[str, float] | None = None
    queue: dict[str, float] = field(default_factory=dict)
    now_ms: float | None = None

    def _now(self) -> float:
        return self.now_ms if self.now_ms is not None else time.monotonic() * 1000

    def _live_holder(self) -> str | None:
        if self.lock is None:
            return None
        holder, expires = self.lock
        if expires <= self._now():
            self.lock = None
            return None
        return holder

    async def acquire(self, holder: str, *, ttl_ms: int) -> bool:
        if self._live_holder() is not None:
            return False
        self.lock = (holder, self._now() + ttl_ms)
        return True

    async def renew(self, holder: str, *, ttl_ms: int) -> bool:
        if self._live_holder() != holder:
            return False
        self.lock = (holder, self._now() + ttl_ms)
        return True

    async def release(self, holder: str) -> bool:
        if self._live_holder() != holder:
            return False
        self.lock = None
        return True

    async def holder(self) -> str | None:
        return self._live_holder()

    async def join(self, member: str, score: float) -> None:
        self.queue.setdefault(member, score)

    async def leave(self, *members: str) -> None:
        for member in members:
            self.queue.pop(member, None)

    def _ordered(self) -> list[str]:
        return [member for member, _ in sorted(self.queue.items(), key=lambda kv: (kv[1], kv[0]))]

    async def rank(self, member: str) -> int | None:
        ordered = self._ordered()
        return ordered.index(member) if member in ordered else None

    async def members(self) -> tuple[str, ...]:
        return tuple(self._ordered())
