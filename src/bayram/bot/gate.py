"""The first thing every inbound update meets, and the only thing that can refuse one.

**Why OUTER, and why registered per event type.** ``dispatcher.message.outer_middleware``
runs before the observer's filters, which is the whole point: an inner middleware only sees
updates some handler already claimed, so a blocked account could still walk the bot through
a state machine simply by sending something no filter matches. Registering the same
instance on ``message`` and on ``callback_query`` — rather than once on ``update`` — is what
lets the refusal be shaped for the surface it arrives on: a refused callback **must** be
answered or the client spins forever, and answering it is also a reply rather than a new
chat message, which is what keeps a refusal from being its own flood.

**Where this sits in the chain, and what that costs.** aiogram's ``FSMContextMiddleware`` is
an outer middleware on the ``update`` observer and acquires the per-chat isolation lock
before propagating (``aiogram/fsm/middleware.py``), so everything here runs **inside that
lock** — the lock the double-tap guarantee depends on. Nothing below may therefore await a
write. The user upsert is offered to a bounded queue with ``put_nowait`` and drained by a
background task; the block read is cached for a minute; the throttle touches an in-process
dict by default. The one unavoidable await is ``resolve_language_or_none``, an FSM-storage
read that aiogram has already primed by loading ``raw_state`` from the same key — and it is
read ONCE, with both values the decision needs derived from it, because a second
``state.get_data()`` inside the isolation lock would serialise one chat's updates behind a
second storage round trip for no new information.

**What this middleware deliberately does NOT do: the onboarding check.** An account with no
phone number is turned back by a ROUTER (``bayram.bot.handlers.onboarding``), not from here, and
the reason is not the one an earlier draft of the specification gave. That draft argued the
check must stay out of the middleware because the middleware runs inside the FSM isolation
lock — but so does everything else: ``FSMContextMiddleware`` is an outer middleware on the
``update`` observer and holds the lock across the WHOLE router tree, so a router filter runs
inside exactly the lock that was offered as the reason to avoid one. The lock argument does
not distinguish the two layers at all. The real reason is a capability: a middleware can
neither set FSM state nor render a screen. The most it can do is refuse an update with one
canned sentence — and "please tell me which language to speak, and then your number" is a
screen with buttons on it, not a refusal.

``ErrorGuardMiddleware`` is registered INNER (``bayram.bot.app.build_dispatcher``) and outer
middlewares run first, so it does **not** wrap this one: an exception escaping here would
reach aiogram's ``ErrorsMiddleware`` and the chat would simply go quiet. Hence
:meth:`InboundGateMiddleware._refusal_for` catches everything and returns "no refusal" —
this gate FAILS OPEN. A meter that cannot be read is not a reason to stop selling songs.

**The erasure carve-out is not negotiable — but it is not unmetered either.**
``/privacy``, ``/forget`` and ``/support`` reach their handler whatever this gate thinks
about the account: blocking is an operator action of indefinite length, and it may never
become the mechanism by which a data-subject request is denied. They are exempt from the
ORDINARY throttle for the same reason — the person most likely to be over it is the person
whose ``/forget`` must still land — and they carry a small budget of their own instead
(``InboundPolicy.erasure_max_updates``). They are not the "one canned message each" an
earlier draft of this docstring claimed: ``handle_forget`` rewrites every ledger row for
the account and deletes its balance, so with no limiter at all the exemption was an
unmetered write amplifier. A throttled repeat is refused with ``error.too_fast`` and loses
nothing, because all three commands are idempotent.

**Order, and why it is that order.** No ``from_user`` → straight through, because there is
no account to meter. Then the touch is offered, so an account that is about to be refused
still gets the row that makes it blockable. Then the carve-out. Then the block gate, which
outranks the throttle because "this account cannot order songs" is the truer sentence to
send someone who is both blocked and impatient. Then the throttle.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Protocol

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

from bayram.bot.handlers.common import COMMAND_PREFIX
from bayram.bot.i18n import FALLBACK_LANGUAGE, translate
from bayram.bot.middleware import resolve_language_or_none
from bayram.bot.ports import Clock, utc_now
from bayram.contracts import Language, Result, is_ok
from bayram.entitlements import EntitlementStore
from bayram.logging import get_logger
from bayram.ratelimit import (
    DEFAULT_INBOUND_POLICY,
    InboundPolicy,
    InMemoryWindowCounterStore,
    WindowCounterStore,
    check_erasure_rate,
    check_update_rate,
    claim_notice,
)

__all__ = [
    "ERASURE_COMMANDS",
    "TouchWriter",
    "TOUCH_QUEUE_MAXSIZE",
    "UserTouch",
    "TouchQueue",
    "TouchDrain",
    "InboundGateMiddleware",
]

_LOG = get_logger(__name__)

#: The commands that always reach their handler. See the module docstring: these are the
#: data-subject surface, and a control that can deny them is a control that will be used to.
#: ``tests/test_bot/test_gate_middleware.py`` asserts each one is really registered by
#: ``handlers.commands.build_router``, so a rename there cannot silently empty this set.
ERASURE_COMMANDS: Final[frozenset[str]] = frozenset({"privacy", "forget", "support"})

#: What a refused account is told. Both are rendered with no parameters — every ``error.*``
#: key in the catalogues is placeholder-free by test, because the worker renders them bare.
_BLOCKED_MESSAGE_KEY: Final[str] = "error.blocked"
_TOO_FAST_MESSAGE_KEY: Final[str] = "error.too_fast"

#: How many touches may wait to be written before new ones are dropped.
#:
#: Bounded on purpose and generously sized: a thousand pending upserts is far more backlog
#: than a single polling process can produce while its drain is healthy, so reaching this
#: means the writer is wedged — and the right answer to a wedged writer is to drop a
#: liveness ping loudly, never to make a customer's tap wait on it.
TOUCH_QUEUE_MAXSIZE: Final[int] = 1_000

#: Accounts whose last-written minute is remembered by the drain, and whose block answer is
#: remembered by the gate. Both maps are cleared wholesale when they exceed this — the cost
#: is one redundant upsert and one extra read per account, which is exactly what the maps
#: were saving, and never a wrong answer.
_MEMO_MAX_ACCOUNTS: Final[int] = 50_000

#: Telegram truncates a callback answer at 200 characters and 400s on a longer one.
_CALLBACK_ANSWER_MAX_CHARS: Final[int] = 200

#: The coalescing bucket for the user upsert: one write per account per minute.
_TOUCH_BUCKET_S: Final[int] = 60


@dataclass(frozen=True, slots=True)
class UserTouch:
    """ "This account is alive, and it is reading in this language." A liveness ping.

    Carries the language because this is the **first writer in the system that refreshes
    ``users.ui_language``** — ``repository._ensure_user`` deliberately does not — and it is
    the reason an account that never confirmed an order has a row for an operator to block.

    It is no longer the ONLY writer of that column: ``db.users_sql.ensure_user`` refreshes it
    authoritatively when a customer picks a language in onboarding or in Settings. That is
    what makes it safe for this one to DECLINE to write rather than guess — see
    :attr:`ui_language` below. The deliberate writer records the choice; this one only
    refreshes the column when the update it is serving genuinely told us a language.
    """

    telegram_user_id: int
    #: The language this update was read in, or ``None`` when nobody has chosen one yet.
    #:
    #: ``None`` is not a missing value to be filled in with a default — it means "do not
    #: write the column", and the store honours it by leaving whatever is there alone. A
    #: fallback here would be indistinguishable from a choice: every update from a customer
    #: who has never been asked would stamp UZ_LATN over the column, and so would every
    #: update in the minute after a ``state.clear()`` wiped the language cache.
    #:
    #: One consequence, harmless and stated so nobody has to rediscover it:
    #: :meth:`TouchDrain._write`'s per-minute dedupe keys on the account alone, so a ``None``
    #: touch can suppress a real one that arrives in the same bucket. It costs nothing,
    #: because ``UserProfileStore.record_language`` writes ``users.ui_language`` directly and
    #: never goes through this queue — this path is a refresher, not the record of a choice.
    ui_language: Language | None
    at: datetime

    @property
    def bucket(self) -> int:
        """Which minute this touch belongs to. Two touches sharing one are one write."""
        return int(self.at.timestamp()) // _TOUCH_BUCKET_S


class TouchQueue:
    """A bounded hand-off whose producer side NEVER awaits and never raises.

    That is the entire reason it exists. :class:`InboundGateMiddleware` runs inside the FSM
    isolation lock, so a write there serialises one chat's updates behind a database round
    trip — and the lock is what makes the Confirm state filter a real gate rather than a
    hint. An upsert on the hot path would not merely be slow, it would widen the window the
    lock was added to close.

    A full queue **drops**, and says so at WARNING with a running total. Dropping a liveness
    ping is a real loss (a late ``last_seen_at``, a stale ``ui_language``) and it is
    deliberately the loss taken, because the alternatives are worse: blocking makes the
    customer wait on our bookkeeping, and an unbounded queue turns a wedged writer into a
    memory leak that ends the process.
    """

    __slots__ = ("_dropped", "_queue")

    def __init__(self, *, maxsize: int = TOUCH_QUEUE_MAXSIZE) -> None:
        self._queue: asyncio.Queue[UserTouch] = asyncio.Queue(maxsize=max(1, maxsize))
        self._dropped = 0

    @property
    def dropped(self) -> int:
        """Touches lost to a full queue since this process started. Never resets."""
        return self._dropped

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def offer(self, touch: UserTouch) -> bool:
        """Hand a touch over without blocking. ``False`` means it was dropped."""
        try:
            self._queue.put_nowait(touch)
        except asyncio.QueueFull:
            self._dropped += 1
            _LOG.warning(
                "inbound touch dropped: the drain is not keeping up",
                extra={
                    "telegram_user_id": touch.telegram_user_id,
                    "dropped_total": self._dropped,
                    "pending": self._queue.qsize(),
                },
            )
            return False
        return True

    async def take(self) -> UserTouch:
        """The next touch, waiting for one. Only the drain calls this."""
        return await self._queue.get()

    def take_all(self) -> tuple[UserTouch, ...]:
        """Everything queued right now, without waiting. Used by ``aclose``."""
        drained: list[UserTouch] = []
        while True:
            try:
                drained.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                return tuple(drained)


class TouchWriter(Protocol):
    """The ONE method :class:`TouchDrain` is allowed to call. Narrower than the store.

    ``EntitlementStore`` satisfies this structurally, so the gate hands its own meter
    straight over — but naming the single method here rather than depending on the whole
    protocol is what makes it impossible for the drain to grow a second reason to touch the
    ledger. The bot may not write a credit (``bayram.bot.deps.BotDeps.entitlements``), and a
    background task with a full ``EntitlementStore`` in hand is exactly where that rule
    would erode without anyone noticing.
    """

    async def touch(self, telegram_user_id: int, *, ui_language: Language | None) -> Result[None]:
        """Record that this account is alive and, when told, which language it reads.

        ``ui_language`` is optional in the strong sense: ``None`` means the column must be
        left as it is, not that the implementation should choose a default. See
        :attr:`UserTouch.ui_language`.
        """
        ...


class TouchDrain:
    """The background writer behind :class:`TouchQueue`. One upsert per account per minute.

    Coalescing is what makes the queue affordable: a customer walking the wizard produces a
    touch per tap, and every one of them would otherwise be an identical ``UPDATE`` of
    ``last_seen_at``. A minute is the resolution ``last_seen_at`` is actually read at, so
    nothing downstream can tell the difference.

    The loop is written so that nothing can kill it. A store that raises is logged and the
    drain carries on with the next touch — a single bad row must not silently stop every
    later account from getting one. ``CancelledError`` is a ``BaseException`` on 3.12, so
    the broad ``except Exception`` below does not swallow the shutdown.
    """

    __slots__ = ("_queue", "_store", "_task", "_written")

    def __init__(self, store: TouchWriter, queue: TouchQueue) -> None:
        self._store = store
        self._queue = queue
        self._task: asyncio.Task[None] | None = None
        #: account -> the minute bucket last written for it.
        self._written: dict[int, int] = {}

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Begin draining. Idempotent, so a restarted dispatcher does not stack tasks."""
        if self.is_running:
            return
        self._task = asyncio.create_task(self._run(), name="bayram-touch-drain")

    async def aclose(self) -> None:
        """Stop the loop, then write whatever was still queued.

        Draining on the way out matters more than it looks: a shutdown is exactly when the
        backlog is largest, and these rows are what an operator blocks an account by.
        """
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self.drain_pending()

    async def drain_pending(self) -> int:
        """Write everything queued right now. Returns how many upserts actually happened.

        Guarded per row, exactly as :meth:`_run` is. This is reached from :meth:`aclose`,
        which rides ``dispatcher.shutdown`` — so an unguarded write that raised would take
        the rest of the backlog AND the shutdown hook with it, at the moment the docstring
        above says the backlog is largest.
        """
        written = 0
        for touch in self._queue.take_all():
            if await self._write_safely(touch):
                written += 1
        return written

    async def _run(self) -> None:
        while True:
            await self._write_safely(await self._queue.take())

    async def _write_safely(self, touch: UserTouch) -> bool:
        """:meth:`_write`, with the promise that nothing it does can end the caller.

        Broad on purpose: ``EntitlementStore`` promises a ``Result`` and never an exception,
        but the drain is the one place where believing that promise would end every later
        write in the process — or, from ``drain_pending``, the shutdown itself.
        """
        try:
            return await self._write(touch)
        except Exception:
            _LOG.exception(
                "the touch drain could not write; it stays alive",
                extra={"telegram_user_id": touch.telegram_user_id},
            )
            return False

    async def _write(self, touch: UserTouch) -> bool:
        if self._written.get(touch.telegram_user_id) == touch.bucket:
            return False
        result = await self._store.touch(touch.telegram_user_id, ui_language=touch.ui_language)
        if not is_ok(result):
            _LOG.warning(
                "could not record that an account is alive", extra=result.error.to_log_dict()
            )
            return False
        if len(self._written) >= _MEMO_MAX_ACCOUNTS:
            self._written = {}
        self._written[touch.telegram_user_id] = touch.bucket
        return True


@dataclass(frozen=True, slots=True)
class _Refusal:
    """One decided refusal. ``is_spoken`` is the notice budget's answer, not a preference."""

    message_key: str
    language: Language
    is_spoken: bool


@dataclass(frozen=True, slots=True)
class _CachedBlock:
    is_blocked: bool
    expires_at: datetime


class InboundGateMiddleware(BaseMiddleware):
    """Touch, block gate, throttle — in that order, inside the lock, failing open.

    Register the SAME instance on both observers: the throttle counter, the block cache and
    the touch queue are per-instance, and two instances would give one account two budgets.
    """

    def __init__(
        self,
        *,
        entitlements: EntitlementStore | None = None,
        counters: WindowCounterStore | None = None,
        policy: InboundPolicy = DEFAULT_INBOUND_POLICY,
        clock: Clock = utc_now,
        touches: TouchQueue | None = None,
    ) -> None:
        self._entitlements = entitlements
        self._counters = counters if counters is not None else InMemoryWindowCounterStore()
        self._policy = policy
        self._clock = clock
        self._block_ttl = timedelta(seconds=policy.block_cache_s)
        self._blocked: dict[int, _CachedBlock] = {}
        #: Public so a test can read the drop counter and a composition root can size it.
        self.touches = touches if touches is not None else TouchQueue()
        #: ``None`` when no meter is wired at all — the shape the whole existing bot suite
        #: runs in (``tests/test_bot/conftest.py`` builds ``BotDeps`` with no
        #: ``entitlements``). With no store there is nothing to touch and nothing to read a
        #: block from, so those two steps are skipped and only the throttle applies.
        self.drain = TouchDrain(entitlements, self.touches) if entitlements is not None else None

    async def start(self) -> None:
        """Wired to ``dispatcher.startup``; no-op when no meter is configured."""
        if self.drain is not None:
            await self.drain.start()

    async def aclose(self) -> None:
        """Wired to ``dispatcher.shutdown``. Drains the backlog before the process goes."""
        if self.drain is not None:
            await self.drain.aclose()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        refusal = await self._refusal_for(event, data)
        if refusal is None:
            return await handler(event, data)
        await self._deliver(event, refusal)
        return None

    async def _refusal_for(self, event: TelegramObject, data: dict[str, Any]) -> _Refusal | None:
        """The whole decision, wrapped so that nothing it does can stop the handler running.

        The handler call is deliberately OUTSIDE this ``try``: catching around it too would
        let a handler that raised be invoked a second time by the fail-open path.
        """
        try:
            return await self._decide(event, data)
        except Exception:
            _LOG.exception(
                "the inbound gate failed open; the update is being handled unmetered",
                extra={"event_type": type(event).__name__},
            )
            return None

    async def _decide(self, event: TelegramObject, data: dict[str, Any]) -> _Refusal | None:
        telegram_user_id = _user_id(event)
        if telegram_user_id is None:
            return None
        state = data.get("state")
        chosen = await resolve_language_or_none(state if isinstance(state, FSMContext) else None)
        #: The language to SPEAK in. ``chosen`` is what we are willing to WRITE; the two are
        #: deliberately different values derived from ONE read, because ``_refuse`` and
        #: ``_meter_the_erasure_request`` render ``error.blocked`` and ``error.too_fast``,
        #: and a refusal with no language is not a refusal anyone can read. A second
        #: ``state.get_data()`` inside the FSM isolation lock is not acceptable — see this
        #: module's docstring.
        spoken = chosen or FALLBACK_LANGUAGE
        now = self._clock()
        self.touches.offer(UserTouch(telegram_user_id=telegram_user_id, ui_language=chosen, at=now))
        if _is_erasure_request(event):
            return await self._meter_the_erasure_request(telegram_user_id, spoken, now)
        if await self._is_blocked(telegram_user_id, now):
            _LOG.info("blocked account refused", extra={"telegram_user_id": telegram_user_id})
            return await self._refuse(_BLOCKED_MESSAGE_KEY, spoken, telegram_user_id, now)
        verdict = await check_update_rate(
            self._counters, telegram_user_id=telegram_user_id, now=now, policy=self._policy
        )
        if verdict.is_allowed:
            return None
        _LOG.warning(
            "inbound update throttled",
            extra={
                "telegram_user_id": telegram_user_id,
                "update_count": verdict.count,
                "retry_after_s": verdict.retry_after_s,
            },
        )
        return await self._refuse(_TOO_FAST_MESSAGE_KEY, spoken, telegram_user_id, now)

    async def _meter_the_erasure_request(
        self, telegram_user_id: int, language: Language, now: datetime
    ) -> _Refusal | None:
        """Let a data-subject command past the block gate — but not past every limiter.

        The carve-out exists so that an account an operator has barred can still ask to be
        forgotten, and that survives intact: this never refuses with ``error.blocked`` and
        it never consults the block cache. What it adds is a budget of its own, because
        ``handlers.commands.handle_forget`` is not the "one canned message" the exemption was
        costed at — it clears the FSM, writes state three times, and opens a transaction that
        UPDATEs every ``credit_ledger`` row for the account and DELETEs its balance. Exempt
        from the ordinary throttle as well, those three commands were an unmetered write
        amplifier reachable by holding a key down.

        A refused repeat loses nothing: all three are idempotent, and the refusal is
        ``error.too_fast`` — "send it again in a moment" — never a denial of the request.
        """
        verdict = await check_erasure_rate(
            self._counters, telegram_user_id=telegram_user_id, now=now, policy=self._policy
        )
        if verdict.is_allowed:
            return None
        _LOG.warning(
            "a data-subject command was throttled",
            extra={
                "telegram_user_id": telegram_user_id,
                "update_count": verdict.count,
                "retry_after_s": verdict.retry_after_s,
            },
        )
        return await self._refuse(_TOO_FAST_MESSAGE_KEY, language, telegram_user_id, now)

    async def _refuse(
        self, message_key: str, language: Language, telegram_user_id: int, now: datetime
    ) -> _Refusal:
        is_spoken = await claim_notice(
            self._counters,
            telegram_user_id=telegram_user_id,
            purpose=message_key,
            now=now,
            policy=self._policy,
        )
        return _Refusal(message_key=message_key, language=language, is_spoken=is_spoken)

    async def _is_blocked(self, telegram_user_id: int, now: datetime) -> bool:
        """Cached for ``policy.block_cache_s``. Fails OPEN on an unreadable meter.

        ``balance_for`` is the only non-writing member of ``EntitlementStore``, so it is
        also the only one this gate may call: the bot must never be able to move a credit
        (``bayram.bot.deps.BotDeps.entitlements``). Reading a whole balance to learn one
        boolean is the price of not widening that protocol, and the cache makes it at most
        one query per account per minute.

        A failed read is logged at WARNING and **not cached**, so the next update tries
        again rather than treating a blip as a minute of amnesty.
        """
        if self._entitlements is None:
            return False
        cached = self._blocked.get(telegram_user_id)
        if cached is not None and cached.expires_at > now:
            return cached.is_blocked
        result = await self._entitlements.balance_for(telegram_user_id)
        if not is_ok(result):
            _LOG.warning(
                "could not read the account state; letting the update through",
                extra=result.error.to_log_dict(),
            )
            return False
        if len(self._blocked) >= _MEMO_MAX_ACCOUNTS:
            self._blocked = {}
        self._blocked[telegram_user_id] = _CachedBlock(
            is_blocked=result.value.is_blocked, expires_at=now + self._block_ttl
        )
        return result.value.is_blocked

    async def _deliver(self, event: TelegramObject, refusal: _Refusal) -> None:
        """Say it once, and always clear the spinner. Best effort; a failure is logged only.

        A callback is answered whether or not the notice budget allows words, because an
        unanswered callback query leaves a loading spinner on the customer's button for
        Telegram's own timeout — which reads as a frozen bot, not as a refusal.
        """
        text = translate(refusal.message_key, refusal.language) if refusal.is_spoken else None
        try:
            if isinstance(event, CallbackQuery):
                await event.answer(
                    text[:_CALLBACK_ANSWER_MAX_CHARS] if text is not None else None,
                    show_alert=text is not None,
                )
                return
            if isinstance(event, Message) and text is not None:
                await event.answer(text)
        except TelegramAPIError:
            _LOG.exception(
                "could not deliver the inbound refusal",
                extra={"event_type": type(event).__name__, "message_key": refusal.message_key},
            )


def _user_id(event: TelegramObject) -> int | None:
    """The account behind this update, or ``None`` — a channel post has no ``from_user``."""
    user = getattr(event, "from_user", None)
    telegram_user_id = getattr(user, "id", None)
    return telegram_user_id if isinstance(telegram_user_id, int) else None


def _is_erasure_request(event: TelegramObject) -> bool:
    """Is this one of the three commands that always get through?

    ``/forget@some_bot`` is the form Telegram sends in a group, and a command with an
    argument is still a command, so both are stripped before the comparison. ``casefold``
    because Telegram clients happily send ``/Forget``.
    """
    if not isinstance(event, Message):
        return False
    text = event.text or event.caption or ""
    if not text.startswith(COMMAND_PREFIX):
        return False
    word = text.split(maxsplit=1)[0].removeprefix(COMMAND_PREFIX)
    return word.split("@", 1)[0].casefold() in ERASURE_COMMANDS
