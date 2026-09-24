"""The GPU slot (IMAGE_VIDEO_SPEC §3.4): renew and release are compare-and-set on the holder.

The property that matters: an OLD attempt — one whose lock expired and was taken by the next —
can neither extend nor delete the new owner's lock. Asserted over the in-memory store the stage
tests use, and over the real Lua scripts against a live Redis (``integration``).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from bayram.runtime.gpu_lock import (
    GpuSlotStore,
    MemoryGpuSlotStore,
    RedisGpuSlotStore,
    parse_queue_member,
    queue_member,
    queue_score,
)

_PAID = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


async def _old_attempt_cannot_touch_the_new_lock(store: GpuSlotStore, expire: Any) -> None:
    old, new = str(uuid4()), str(uuid4())
    assert await store.acquire(old, ttl_ms=1_000)
    assert not await store.acquire(new, ttl_ms=1_000)

    await expire()
    assert await store.acquire(new, ttl_ms=60_000)

    assert not await store.renew(old, ttl_ms=60_000)
    assert not await store.release(old)
    assert await store.holder() == new
    assert await store.renew(new, ttl_ms=60_000)
    assert await store.release(new)
    assert await store.holder() is None


async def _the_queue_is_fair_and_members_leave(store: GpuSlotStore) -> None:
    first, second = uuid4(), uuid4()
    await store.join(queue_member(second, 0), queue_score(_PAID + timedelta(seconds=5), 0))
    await store.join(queue_member(first, 1), queue_score(_PAID, 1))
    await store.join(queue_member(first, 0), queue_score(_PAID, 0))
    # Joining again keeps the place (ZADD NX).
    await store.join(queue_member(first, 0), queue_score(_PAID + timedelta(hours=1), 0))

    assert await store.members() == (
        queue_member(first, 0),
        queue_member(first, 1),
        queue_member(second, 0),
    )
    assert await store.rank(queue_member(second, 0)) == 2

    await store.leave(queue_member(first, 0), queue_member(first, 1))
    assert await store.rank(queue_member(second, 0)) == 0
    assert await store.rank(queue_member(first, 0)) is None


async def test_memory_lock_is_compare_and_set() -> None:
    store = MemoryGpuSlotStore(now_ms=0)

    async def expire() -> None:
        store.now_ms = 5_000

    await _old_attempt_cannot_touch_the_new_lock(store, expire)


async def test_memory_queue_is_fair() -> None:
    await _the_queue_is_fair_and_members_leave(MemoryGpuSlotStore())


def test_a_queue_member_round_trips_and_a_foreign_one_is_ignored() -> None:
    job = uuid4()
    assert parse_queue_member(queue_member(job, 1)) == (job, 1)
    assert parse_queue_member("not-a-member") is None


# ---------------------------------------------------------------------------
# The Lua, against a real Redis
# ---------------------------------------------------------------------------
@pytest.fixture
async def redis_store() -> AsyncIterator[tuple[RedisGpuSlotStore, Any, str]]:
    from redis.asyncio import Redis

    client = Redis.from_url(os.environ.get("BAYRAM_TEST_REDIS_URL", "redis://localhost:6379/15"))
    try:
        await client.ping()
    except Exception:
        await client.close()
        pytest.skip("no Redis to run the GPU lock's Lua against")
    prefix = f"test:{uuid4().hex}:"
    yield RedisGpuSlotStore(client, prefix=prefix), client, prefix
    keys = [key async for key in client.scan_iter(match=f"{prefix}*")]
    if keys:
        await client.delete(*keys)
    await client.close()


@pytest.mark.integration
async def test_redis_lock_is_compare_and_set(
    redis_store: tuple[RedisGpuSlotStore, Any, str],
) -> None:
    store, client, prefix = redis_store

    async def expire() -> None:
        await client.delete(f"{prefix}media:gpu:lock")

    await _old_attempt_cannot_touch_the_new_lock(store, expire)


@pytest.mark.integration
async def test_redis_queue_is_fair(redis_store: tuple[RedisGpuSlotStore, Any, str]) -> None:
    store, _, _ = redis_store
    await _the_queue_is_fair_and_members_leave(store)


@pytest.mark.integration
async def test_redis_acquire_sets_the_short_ttl(
    redis_store: tuple[RedisGpuSlotStore, Any, str],
) -> None:
    store, client, prefix = redis_store
    holder = str(uuid4())
    assert await store.acquire(holder, ttl_ms=120_000)
    ttl = await client.pttl(f"{prefix}media:gpu:lock")
    assert 0 < ttl <= 120_000
    assert await store.renew(holder, ttl_ms=600_000)
    assert await client.pttl(f"{prefix}media:gpu:lock") > 120_000
