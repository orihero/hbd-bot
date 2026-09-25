"""The Gemini TTS key pool (IMAGE_VIDEO_SPEC §5.2; owner decision O8, D23).

The owner supplies 5–6 keys, possibly from several projects, and accepted the ToS risk that
comes with spreading load across them (§11 R2). This module decides **which key the next
call uses** and remembers what each key has been doing; it never makes a call itself.

* **A key is never logged, stored or shown.** Everywhere outside this module's constructor it
  is a :class:`PoolKey` whose ``repr`` is its ``key_ref`` = ``sha256(key)[:8]``, and the Redis
  hash, the log lines and the admin card are all keyed by that ref.
* **Selection** is round-robin over a shared counter (Redis ``INCR tts:gemini:rr`` mod N), so
  the bot's and the worker's calls interleave, skipping a key that is cooling or disabled.
* **Per-key state** lives in the hash ``tts:gemini:key:{key_ref}``: ``cooldown_until``,
  ``consecutive_429``, ``consecutive_5xx``, ``last_ok_at``, ``disabled_until`` and
  ``disabled_reason``. A 429 cools the key for ``Retry-After`` or 30 s × 2^n (cap 15 min); a
  401/403 or an invalid-key 400 disables it for 24 h and logs an ERROR for the operator
  (key_ref only). Success resets both streaks.
* **Health** counts successes and 429s over the last 24 h per key for the admin card.

**A store that cannot be read does not stop narration.** The state is an optimisation over
"try the keys in turn": when Redis is unreachable the pool falls back to an in-process counter
and treats every key as usable, and a key that then 429s simply costs one extra request. The
read-modify-write of a streak counter is not atomic across processes either; a lost increment
shortens one backoff, which is the same order of harm.

The Redis side is behind :class:`KeyPoolStore`, so the provider tests run over
:class:`MemoryKeyPoolStore` — the same semantics in a dict.
"""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable
from uuid import uuid4

from bayram.logging import get_logger
from bayram.providers.tts.transport import utc_now

__all__ = [
    "RR_KEY",
    "STATE_KEY_PREFIX",
    "BASE_COOLDOWN_S",
    "MAX_COOLDOWN_S",
    "DISABLE_FOR",
    "HEALTH_WINDOW",
    "KeyEvent",
    "KeyState",
    "KeyHealth",
    "PoolKey",
    "KeyPoolStore",
    "MemoryKeyPoolStore",
    "RedisKeyPoolStore",
    "GeminiKeyPool",
    "key_ref",
    "parse_retry_after",
]

_LOG = get_logger(__name__)

RR_KEY: Final[str] = "tts:gemini:rr"
STATE_KEY_PREFIX: Final[str] = "tts:gemini:key:"

#: §5.2: 30 s × 2^n, capped at 15 minutes.
BASE_COOLDOWN_S: Final[float] = 30.0
MAX_COOLDOWN_S: Final[float] = 900.0
#: §5.2: a rejected credential is left alone for a day, then tried again.
DISABLE_FOR: Final[timedelta] = timedelta(hours=24)
HEALTH_WINDOW: Final[timedelta] = timedelta(hours=24)

_KEY_REF_CHARS: Final[int] = 8

# Hash fields, spelled once.
_COOLDOWN_UNTIL: Final[str] = "cooldown_until"
_CONSECUTIVE_429: Final[str] = "consecutive_429"
_CONSECUTIVE_5XX: Final[str] = "consecutive_5xx"
_LAST_OK_AT: Final[str] = "last_ok_at"
_DISABLED_UNTIL: Final[str] = "disabled_until"
_DISABLED_REASON: Final[str] = "disabled_reason"


def key_ref(key: str) -> str:
    """The only name a key has outside this module: the first 8 hex of its SHA-256."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:_KEY_REF_CHARS]


class KeyEvent(StrEnum):
    """What the health card counts per key over :data:`HEALTH_WINDOW`."""

    OK = "ok"
    RATE_LIMITED = "rate_limited"


class KeyState(StrEnum):
    AVAILABLE = "available"
    COOLING = "cooling"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class PoolKey:
    """A pool member. The secret is held but never rendered: ``repr`` shows the ref only."""

    ref: str
    secret: str = field(repr=False)

    def __str__(self) -> str:
        return self.ref


@dataclass(frozen=True, slots=True)
class KeyHealth:
    """One row of the admin card (§5.2 "Health"). Carries no key material."""

    key_ref: str
    state: KeyState
    last_ok_at: datetime | None
    cooldown_until: datetime | None
    disabled_until: datetime | None
    disabled_reason: str | None
    ok_24h: int
    rate_limited_24h: int


@runtime_checkable
class KeyPoolStore(Protocol):
    """Where the round-robin counter, per-key state and health events live."""

    async def next_counter(self) -> int: ...

    async def read_state(self, ref: str) -> Mapping[str, str]: ...

    async def write_state(self, ref: str, fields: Mapping[str, str]) -> None: ...

    async def record_event(self, ref: str, event: KeyEvent, at: datetime) -> None: ...

    async def count_events(self, ref: str, event: KeyEvent, since: datetime) -> int: ...


class MemoryKeyPoolStore:
    """:class:`KeyPoolStore` in a dict. The tests' store, and the dev store without Redis."""

    def __init__(self) -> None:
        self._counter = 0
        self._states: dict[str, dict[str, str]] = {}
        self._events: dict[tuple[str, KeyEvent], list[datetime]] = {}

    async def next_counter(self) -> int:
        self._counter += 1
        return self._counter

    async def read_state(self, ref: str) -> Mapping[str, str]:
        return dict(self._states.get(ref, {}))

    async def write_state(self, ref: str, fields: Mapping[str, str]) -> None:
        self._states.setdefault(ref, {}).update(fields)

    async def record_event(self, ref: str, event: KeyEvent, at: datetime) -> None:
        self._events.setdefault((ref, event), []).append(at)

    async def count_events(self, ref: str, event: KeyEvent, since: datetime) -> int:
        return sum(1 for at in self._events.get((ref, event), ()) if at >= since)


class RedisKeyPoolStore:
    """:class:`KeyPoolStore` over Redis. ``ArqRedis`` and ``redis.asyncio.Redis`` both fit.

    Events are a sorted set per key and kind, scored by epoch seconds and trimmed to the
    health window on every write, with a TTL so an idle pool leaves nothing behind.
    """

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def next_counter(self) -> int:
        return int(await self._redis.incr(RR_KEY))

    async def read_state(self, ref: str) -> Mapping[str, str]:
        raw = await self._redis.hgetall(_state_key(ref))
        return {_text(name): _text(value) for name, value in dict(raw or {}).items()}

    async def write_state(self, ref: str, fields: Mapping[str, str]) -> None:
        await self._redis.hset(_state_key(ref), mapping=dict(fields))

    async def record_event(self, ref: str, event: KeyEvent, at: datetime) -> None:
        name = _event_key(ref, event)
        score = at.timestamp()
        await self._redis.zadd(name, {f"{score}:{uuid4().hex[:8]}": score})
        await self._redis.zremrangebyscore(name, "-inf", score - HEALTH_WINDOW.total_seconds())
        await self._redis.expire(name, int(HEALTH_WINDOW.total_seconds()) + 3_600)

    async def count_events(self, ref: str, event: KeyEvent, since: datetime) -> int:
        return int(await self._redis.zcount(_event_key(ref, event), since.timestamp(), "+inf"))


def _state_key(ref: str) -> str:
    return f"{STATE_KEY_PREFIX}{ref}"


def _event_key(ref: str, event: KeyEvent) -> str:
    return f"{STATE_KEY_PREFIX}{ref}:{event.value}"


def _text(value: object) -> str:
    if isinstance(value, bytes | bytearray):
        return value.decode("utf-8", "replace")
    return str(value)


def _parse_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _parse_int(raw: str | None) -> int:
    try:
        return max(int(raw or 0), 0)
    except ValueError:
        return 0


def _state_of(fields: Mapping[str, str], now: datetime) -> KeyState:
    disabled_until = _parse_time(fields.get(_DISABLED_UNTIL))
    if disabled_until is not None and disabled_until > now:
        return KeyState.DISABLED
    cooldown_until = _parse_time(fields.get(_COOLDOWN_UNTIL))
    if cooldown_until is not None and cooldown_until > now:
        return KeyState.COOLING
    return KeyState.AVAILABLE


def parse_retry_after(raw: object) -> float | None:
    """``Retry-After`` in seconds, when it is the numeric form; ``None`` otherwise."""
    if raw is None:
        return None
    try:
        seconds = float(str(raw).strip())
    except ValueError:
        return None
    return seconds if seconds > 0 else None


class GeminiKeyPool:
    """Round-robin over the owner's keys with per-key cooldown and disablement (§5.2)."""

    def __init__(
        self,
        keys: Iterable[str],
        *,
        store: KeyPoolStore,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        members: list[PoolKey] = []
        for raw in keys:
            secret = raw.strip()
            if not secret:
                continue
            ref = key_ref(secret)
            if any(member.ref == ref for member in members):
                continue  # the same key twice is one key; rotating it twice adds nothing
            members.append(PoolKey(ref=ref, secret=secret))
        self._keys: tuple[PoolKey, ...] = tuple(members)
        self._store = store
        self._clock = clock
        self._local_counter = itertools.count(1)

    @property
    def keys(self) -> tuple[PoolKey, ...]:
        return self._keys

    @property
    def refs(self) -> tuple[str, ...]:
        return tuple(key.ref for key in self._keys)

    def __len__(self) -> int:
        return len(self._keys)

    def __repr__(self) -> str:
        return f"GeminiKeyPool(refs={list(self.refs)!r})"

    # -- selection ----------------------------------------------------------
    async def pick(self, *, exclude: Sequence[str] = ()) -> PoolKey | None:
        """The next usable key after the shared counter, skipping ``exclude``; ``None`` if none."""
        if not self._keys:
            return None
        start = await self._next_counter()
        now = self._clock()
        size = len(self._keys)
        for offset in range(size):
            candidate = self._keys[(start + offset) % size]
            if candidate.ref in exclude:
                continue
            fields = await self._read(candidate.ref)
            if _state_of(fields, now) is KeyState.AVAILABLE:
                return candidate
        return None

    # -- outcomes -----------------------------------------------------------
    async def mark_ok(self, key: PoolKey) -> None:
        now = self._clock()
        await self._write(
            key.ref, {_LAST_OK_AT: now.isoformat(), _CONSECUTIVE_429: "0", _CONSECUTIVE_5XX: "0"}
        )
        await self._event(key.ref, KeyEvent.OK, now)

    async def mark_rate_limited(self, key: PoolKey, *, retry_after_s: float | None) -> float:
        """Cool the key; returns the cooldown applied, in seconds."""
        now = self._clock()
        streak = _parse_int((await self._read(key.ref)).get(_CONSECUTIVE_429))
        backoff = min(BASE_COOLDOWN_S * (2**streak), MAX_COOLDOWN_S)
        cooldown = min(retry_after_s, MAX_COOLDOWN_S) if retry_after_s is not None else backoff
        await self._write(
            key.ref,
            {
                _COOLDOWN_UNTIL: (now + timedelta(seconds=cooldown)).isoformat(),
                _CONSECUTIVE_429: str(streak + 1),
            },
        )
        await self._event(key.ref, KeyEvent.RATE_LIMITED, now)
        _LOG.warning(
            "gemini tts key rate limited; cooling it and trying the next",
            extra={"key_ref": key.ref, "cooldown_s": cooldown, "consecutive_429": streak + 1},
        )
        return cooldown

    async def mark_disabled(self, key: PoolKey, *, reason: str) -> None:
        """401/403 or an invalid key: out of rotation for a day, and the operator is told."""
        now = self._clock()
        await self._write(
            key.ref,
            {_DISABLED_UNTIL: (now + DISABLE_FOR).isoformat(), _DISABLED_REASON: reason[:64]},
        )
        # The admin alert (§5.2, §11 R2): key_ref only. Two of these in 30 days is the D23
        # trigger to collapse the pool to one billed project.
        _LOG.error(
            "gemini tts key disabled for 24h",
            extra={"key_ref": key.ref, "reason": reason[:64], "alert": "gemini_tts_key_disabled"},
        )

    async def mark_server_error(self, key: PoolKey) -> None:
        streak = _parse_int((await self._read(key.ref)).get(_CONSECUTIVE_5XX))
        await self._write(key.ref, {_CONSECUTIVE_5XX: str(streak + 1)})

    # -- health -------------------------------------------------------------
    async def snapshot(self) -> tuple[KeyHealth, ...]:
        """One row per key for the admin card (§5.2, §9.4 Health). Never a key."""
        now = self._clock()
        since = now - HEALTH_WINDOW
        rows: list[KeyHealth] = []
        for key in self._keys:
            fields = await self._read(key.ref)
            rows.append(
                KeyHealth(
                    key_ref=key.ref,
                    state=_state_of(fields, now),
                    last_ok_at=_parse_time(fields.get(_LAST_OK_AT)),
                    cooldown_until=_parse_time(fields.get(_COOLDOWN_UNTIL)),
                    disabled_until=_parse_time(fields.get(_DISABLED_UNTIL)),
                    disabled_reason=fields.get(_DISABLED_REASON) or None,
                    ok_24h=await self._count(key.ref, KeyEvent.OK, since),
                    rate_limited_24h=await self._count(key.ref, KeyEvent.RATE_LIMITED, since),
                )
            )
        return tuple(rows)

    # -- store access, never raising ------------------------------------------
    async def _next_counter(self) -> int:
        try:
            return await self._store.next_counter()
        except Exception as exc:
            _LOG.warning(
                "key pool counter unreadable; rotating in-process",
                extra={"error": type(exc).__name__},
            )
            return next(self._local_counter)

    async def _read(self, ref: str) -> Mapping[str, str]:
        try:
            return await self._store.read_state(ref)
        except Exception as exc:
            _LOG.warning(
                "key pool state unreadable; treating the key as usable",
                extra={"key_ref": ref, "error": type(exc).__name__},
            )
            return {}

    async def _write(self, ref: str, fields: Mapping[str, str]) -> None:
        try:
            await self._store.write_state(ref, fields)
        except Exception as exc:
            _LOG.warning(
                "key pool state not written",
                extra={"key_ref": ref, "error": type(exc).__name__},
            )

    async def _event(self, ref: str, event: KeyEvent, at: datetime) -> None:
        try:
            await self._store.record_event(ref, event, at)
        except Exception as exc:
            _LOG.warning(
                "key pool health event not written",
                extra={"key_ref": ref, "error": type(exc).__name__},
            )

    async def _count(self, ref: str, event: KeyEvent, since: datetime) -> int:
        try:
            return await self._store.count_events(ref, event, since)
        except Exception:
            return 0
