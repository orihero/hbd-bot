"""Fixed-window metering for INBOUND customer updates. Fails **open**, by design.

This is deliberately a *second* implementation of the fixed-window idea that
``bayram.admin.security.ratelimit`` already runs on the admin login route, and the duplication
is the correct trade rather than an oversight. The two limiters meter different things and
their central policy decision is the exact opposite of each other:

* the admin limiter guards ``/auth/login``, the one unauthenticated argon2 oracle in the
  process, so when its counter store is unreachable the answer is **denied**. A login
  attempt with no working limiter is an unlimited login attempt;
* this one guards the customer wizard, where the counter store being unreachable must
  **not** stop a customer ordering a song. Refusing every update because a counter is down
  turns a Redis blip into a total outage of the product, and the thing it would be
  protecting is a per-user tap rate, not a CPU-exhaustion vector.

Sharing one module would mean one class carrying both policies behind a flag, and a flag
whose two settings are "outage" and "unbounded brute force" is the kind of thing that gets
set wrong once. Two small modules that each state their own rule cannot.

**Everything here is a leaf.** It imports ``bayram.errors``, ``bayram.logging`` and the standard
library, and nothing else — not ``bayram.config`` (see :func:`resolve_inbound_policy`, which
reads a ``Settings`` defensively through ``getattr`` exactly as ``bayram.entitlements`` does),
not ``aiogram``. The aiogram half lives in ``bayram.bot.gate``.

**The window is fixed, not sliding.** A fixed window admits a burst across a boundary — up
to ``2 * max_updates`` in one window's worth of wall time — and that is fine for what this
bounds: it is an abuse rail on a human tapping buttons, not a billing meter. A sliding
window costs a sorted set per user and buys precision nobody here needs.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from bayram.errors import ConfigError
from bayram.logging import get_logger

__all__ = [
    # Policy
    "InboundPolicy",
    "DEFAULT_INBOUND_POLICY",
    "resolve_inbound_policy",
    # Values
    "ThrottleVerdict",
    # Seam
    "WindowCounterStore",
    "InMemoryWindowCounterStore",
    # Decisions
    "check_update_rate",
    "check_erasure_rate",
    "claim_notice",
]

_LOG = get_logger(__name__)

#: One minute. Long enough that a burst of taps is smoothed, short enough that a customer
#: who genuinely hit the ceiling is not locked out of their own wizard for a coffee break.
_DEFAULT_WINDOW_S: Final[int] = 60
#: Updates one account may send per window before the gate starts refusing.
#:
#: Thirty, not ten. A full walk through the wizard is about ten updates, a customer who
#: changes their mind about the genre and re-reads the lyric is more, and the cost of being
#: wrong in the tight direction is that an honest customer is told to slow down in the
#: middle of ordering. The number that matters for abuse is the order of magnitude: thirty
#: a minute stops a script, and no human reaches it.
_DEFAULT_MAX_UPDATES: Final[int] = 30
#: How long a "is this account blocked?" answer may be reused before it is read again.
#:
#: The cost of the cache is the lag on an *unblock*: an operator who lifts a block waits up
#: to this long, per process. The cost of not having it is one database round trip on every
#: inbound update, taken inside the FSM isolation lock — see ``bayram.bot.gate``.
_DEFAULT_BLOCK_CACHE_S: Final[int] = 60
#: Data-subject commands one account may send per window.
#:
#: Three, not thirty and not unlimited. ``/privacy``, ``/forget`` and ``/support`` bypass the
#: block gate and the ordinary ceiling by design, so this is the ONLY thing standing between
#: a script and an unbounded number of erasure transactions plus outbound messages. Nobody
#: sends a fourth ``/forget`` inside a minute for a reason the second did not already serve,
#: and the command is idempotent, so the refusal costs a real person nothing.
_DEFAULT_ERASURE_MAX_UPDATES: Final[int] = 3

#: Namespaced so a future Redis-backed store cannot collide with the admin limiter's keys,
#: which live under ``bayram:admin:rl``.
_KEY_PREFIX: Final[str] = "bayram:bot:rl"

#: When the in-memory store holds more keys than this it prunes; see
#: :class:`InMemoryWindowCounterStore` for what happens if pruning is not enough.
_DEFAULT_MAX_KEYS: Final[int] = 50_000


@dataclass(frozen=True, slots=True)
class InboundPolicy:
    """Every number the inbound gate runs on. Immutable, injected, never ambient."""

    window_s: int = _DEFAULT_WINDOW_S
    max_updates: int = _DEFAULT_MAX_UPDATES
    block_cache_s: int = _DEFAULT_BLOCK_CACHE_S
    #: How many data-subject commands (``/privacy``, ``/forget``, ``/support``) one account
    #: may send per window. Its own budget rather than none at all: those three are exempt
    #: from the block gate on purpose — a control of indefinite length must not be the
    #: mechanism by which an erasure request is denied — but exempting them from the
    #: *limiter* too made them an unmetered write amplifier. ``handle_forget`` is not a
    #: canned message: it clears the FSM, writes state, and opens a transaction that UPDATEs
    #: every ``credit_ledger`` row for the account and DELETEs its ``credit_accounts`` row.
    #: A few per minute is more than any human needs, and ``/forget`` is idempotent, so a
    #: throttled repeat loses nothing.
    erasure_max_updates: int = _DEFAULT_ERASURE_MAX_UPDATES

    def __post_init__(self) -> None:
        """Refuse a policy that cannot be enforced, at construction rather than per update.

        ``window_s`` is a divisor in :func:`_window_index`, so a zero here is a
        ``ZeroDivisionError`` on a customer's next tap — inside the FSM isolation lock, on
        every update, forever. A ``ConfigError`` at wiring time is the same bug found by
        the operator instead. Mirrors
        :meth:`bayram.entitlements.EntitlementPolicy.__post_init__` so the codebase has one
        idiom for "a policy object validates itself", not two.
        """
        if (
            self.window_s < 1
            or self.max_updates < 1
            or self.block_cache_s < 0
            or self.erasure_max_updates < 1
        ):
            raise ConfigError(
                "an inbound window must be at least a second, admit at least one update, "
                "and cache a block for a non-negative time",
                context={
                    "window_s": self.window_s,
                    "max_updates": self.max_updates,
                    "block_cache_s": self.block_cache_s,
                    "erasure_max_updates": self.erasure_max_updates,
                },
            )


DEFAULT_INBOUND_POLICY: Final[InboundPolicy] = InboundPolicy()


def resolve_inbound_policy(settings: object | None = None) -> InboundPolicy:
    """Build the policy this deployment runs on, reading ``Settings`` defensively.

    ``object`` rather than ``Settings``, and ``getattr`` rather than attribute access, for
    the same reason :func:`bayram.entitlements.resolve_entitlement_policy` does it: this module
    is a leaf and importing ``bayram.config`` would give it the one edge it has none of.
    """
    if settings is None:
        return DEFAULT_INBOUND_POLICY
    return InboundPolicy(
        window_s=_positive_int(settings, "inbound_window_s") or _DEFAULT_WINDOW_S,
        max_updates=_positive_int(settings, "inbound_max_updates") or _DEFAULT_MAX_UPDATES,
        block_cache_s=_positive_int(settings, "inbound_block_cache_s") or _DEFAULT_BLOCK_CACHE_S,
        erasure_max_updates=(
            _positive_int(settings, "inbound_erasure_max_updates") or _DEFAULT_ERASURE_MAX_UPDATES
        ),
    )


def _positive_int(settings: object, name: str) -> int | None:
    """``getattr`` narrowed to a usable int. ``bool`` is excluded — it is an ``int`` here."""
    value = getattr(settings, name, None)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


@dataclass(frozen=True, slots=True)
class ThrottleVerdict:
    """The throttle's answer for one update.

    ``count`` is reported rather than hidden because it is the only thing that tells an
    operator whether a refusal was one tap over the line or a script hammering the bot, and
    those two want different responses.
    """

    is_allowed: bool
    count: int
    retry_after_s: int


class WindowCounterStore(Protocol):
    """Bump a key and expire it. That is the whole backend contract.

    A protocol rather than a concrete client so the *policy* — the ordering, the ceiling,
    the fail-open rule — is tested with no server running, and so a Redis-backed
    implementation is a new class rather than an edit to the decisions below.

    Implementations MAY raise. Every caller in this module treats an exception as "the
    limiter is not working" and **allows** the update; see the module docstring for why
    that is the opposite of the admin limiter's rule.
    """

    async def increment(self, key: str, *, ttl_s: int) -> int:
        """Increment ``key``, arm its TTL, and return the new count."""
        ...


class InMemoryWindowCounterStore:
    """Per-process counters. The **default**, and for this repo that is not a compromise.

    The bot deploys as a single polling process, the whole test suite runs with
    ``MemoryStorage`` and no Redis at all, and ``use_fake_providers`` mode has no Redis
    either — so a Redis-only limiter would be a limiter that is switched off in three of the
    four ways this program is ever run.

    What it does not do, stated plainly rather than left to be discovered: the counters are
    **per process**. The day a second bot instance polls, each keeps its own ceiling and the
    effective limit doubles. That is a known, accepted limit of this build (a Redis
    implementation is a class satisfying :class:`WindowCounterStore` and an owned client
    closed in ``main._shutdown``), and it is honest because the thing being bounded is a
    single customer's tap rate, not a security boundary.

    Memory is bounded in two stages. Keys carry their own window index, so a user leaves at
    most a couple of dead keys behind per window and an ordinary prune reclaims them. If a
    prune still leaves more keys than the cap — which needs tens of thousands of *distinct
    accounts inside one window* — the whole map is dropped. Forgetting every counter grants
    everyone one fresh window, which is precisely this module's failure policy already, and
    is strictly better than an unbounded dict in a long-lived process.
    """

    __slots__ = ("_counters", "_max_keys", "_monotonic")

    def __init__(
        self,
        *,
        max_keys: int = _DEFAULT_MAX_KEYS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        #: key -> (count, expiry on the monotonic clock).
        self._counters: dict[str, tuple[int, float]] = {}
        self._max_keys = max(1, max_keys)
        #: Monotonic, never wall time: expiry must not move when NTP steps the clock. The
        #: *window* index in the key still comes from the caller's wall clock, which is what
        #: makes two processes agree on a bucket; these two clocks answer different
        #: questions and are deliberately not the same one.
        self._monotonic = monotonic

    async def increment(self, key: str, *, ttl_s: int) -> int:
        now = self._monotonic()
        self._prune(now)
        count, expires_at = self._counters.get(key, (0, 0.0))
        if expires_at <= now:
            count, expires_at = 0, now + ttl_s
        self._counters[key] = (count + 1, expires_at)
        return count + 1

    def _prune(self, now: float) -> None:
        if len(self._counters) <= self._max_keys:
            return
        self._counters = {key: value for key, value in self._counters.items() if value[1] > now}
        if len(self._counters) > self._max_keys:
            _LOG.warning(
                "the inbound counter map is full; every window is starting over",
                extra={"key_count": len(self._counters), "max_keys": self._max_keys},
            )
            self._counters = {}


def _window_index(now: datetime, window_s: int) -> int:
    return int(now.timestamp()) // window_s


def _seconds_left(now: datetime, window_s: int) -> int:
    return window_s - int(now.timestamp()) % window_s


async def check_update_rate(
    store: WindowCounterStore,
    *,
    telegram_user_id: int,
    now: datetime,
    policy: InboundPolicy = DEFAULT_INBOUND_POLICY,
) -> ThrottleVerdict:
    """Charge one update against this account's window and say whether it may proceed.

    The counter is charged **before** the answer is known, so an update that is refused
    still counts. That is what makes the ceiling a ceiling: a limiter that only counted the
    updates it allowed would let a caller sit exactly on the line forever.
    """
    window = _window_index(now, policy.window_s)
    key = f"{_KEY_PREFIX}:upd:{window}:{telegram_user_id}"
    try:
        count = await store.increment(key, ttl_s=policy.window_s)
    except Exception:
        # Deliberately broad, and deliberately allowing: the store is a protocol whose
        # implementations raise whatever their client raises, and a customer must not be
        # locked out of ordering a song because a counter could not be written.
        _LOG.exception(
            "the inbound throttle could not count; the update is allowed through",
            extra={"telegram_user_id": telegram_user_id},
        )
        return ThrottleVerdict(is_allowed=True, count=0, retry_after_s=0)
    return ThrottleVerdict(
        is_allowed=count <= policy.max_updates,
        count=count,
        retry_after_s=_seconds_left(now, policy.window_s),
    )


async def check_erasure_rate(
    store: WindowCounterStore,
    *,
    telegram_user_id: int,
    now: datetime,
    policy: InboundPolicy = DEFAULT_INBOUND_POLICY,
) -> ThrottleVerdict:
    """The same limiter, on its own generous key, for the three data-subject commands.

    A SEPARATE key rather than a share of the ordinary budget, because the point of the
    carve-out is that a person who has exhausted the update ceiling — or been blocked
    outright — can still ask to be forgotten. Charging those requests against the counter
    that is already over its limit would give the exemption back with one hand and take it
    away with the other.

    Fails open exactly as :func:`check_update_rate` does, and for the same reason.
    """
    window = _window_index(now, policy.window_s)
    key = f"{_KEY_PREFIX}:era:{window}:{telegram_user_id}"
    try:
        count = await store.increment(key, ttl_s=policy.window_s)
    except Exception:
        _LOG.exception(
            "the erasure throttle could not count; the request is allowed through",
            extra={"telegram_user_id": telegram_user_id},
        )
        return ThrottleVerdict(is_allowed=True, count=0, retry_after_s=0)
    return ThrottleVerdict(
        is_allowed=count <= policy.erasure_max_updates,
        count=count,
        retry_after_s=_seconds_left(now, policy.window_s),
    )


async def claim_notice(
    store: WindowCounterStore,
    *,
    telegram_user_id: int,
    purpose: str,
    now: datetime,
    policy: InboundPolicy = DEFAULT_INBOUND_POLICY,
) -> bool:
    """May this account be *told* about ``purpose`` right now? One notice per window.

    A refusal that answers every refused update is its own flood: the account that is being
    throttled is precisely the one sending enough updates to make a reply per update a
    problem, and a blocked account can otherwise pull an unlimited number of outbound
    messages out of the bot simply by typing. Metering the *notice* on its own key — rather
    than reusing the update counter, which is already over its ceiling by the time anyone
    asks — keeps the refusal informative on the first tap and silent thereafter.

    Fails open in the speaking direction: if the counter cannot be written, say it. A
    duplicate refusal is a much smaller failure than a silent one, which reads as a dead bot.
    """
    window = _window_index(now, policy.window_s)
    key = f"{_KEY_PREFIX}:say:{purpose}:{window}:{telegram_user_id}"
    try:
        count = await store.increment(key, ttl_s=policy.window_s)
    except Exception:
        _LOG.exception(
            "the notice budget could not be read; the refusal is sent anyway",
            extra={"telegram_user_id": telegram_user_id, "purpose": purpose},
        )
        return True
    return count <= 1
