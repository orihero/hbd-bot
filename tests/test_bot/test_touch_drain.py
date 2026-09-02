"""The user upsert, off the hot path: a bounded queue, a loud drop, a coalescing drain.

The reason all of this exists rather than one ``await store.touch(...)`` in the middleware
is one line of aiogram: ``FSMContextMiddleware`` acquires the per-chat isolation lock before
propagating an update, so anything the gate awaits serialises that chat behind it — and that
lock is what makes the Confirm state filter a real gate rather than a hint. A slow write
there does not merely delay a tap, it widens the double-tap window the lock was added to
close.

So the producer side must never block and must never raise (:class:`TouchQueue`) and the
writer must be able to fall behind without costing anyone anything except accuracy
(:class:`TouchDrain`). Both halves are tested here on their own, because the failure they
guard against — a wedged database — is exactly the state in which the middleware tests would
still pass.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

import hbd.bot.gate as gate_module
from hbd.bot.gate import TouchDrain, TouchQueue, UserTouch
from hbd.contracts import Language, Result, err, ok
from hbd.errors import StorageError

USER_ID = 1_000_777
MOMENT = datetime(2026, 3, 21, 9, 0, 0, tzinfo=UTC)


def touch(
    *, telegram_user_id: int = USER_ID, at: datetime = MOMENT, language: Language = Language.EN
) -> UserTouch:
    return UserTouch(telegram_user_id=telegram_user_id, ui_language=language, at=at)


class RecordingTouchStore:
    """Records every upsert the drain actually performs. Can be told to fail, or to hang."""

    def __init__(self, *, failure: StorageError | None = None) -> None:
        self.written: list[tuple[int, Language]] = []
        self.failure = failure
        self.explode = False
        #: Set to a real event to make every write wait for it — a wedged database.
        self.gate: asyncio.Event | None = None

    async def touch(self, telegram_user_id: int, *, ui_language: Language) -> Result[None]:
        if self.gate is not None:
            await self.gate.wait()
        if self.explode:
            raise RuntimeError("the store is on fire")
        if self.failure is not None:
            return err(self.failure)
        self.written.append((telegram_user_id, ui_language))
        return ok(None)


async def settle() -> None:
    """Give the drain task a few turns of the loop to pick up what was queued."""
    for _ in range(8):
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------
async def test_offering_a_touch_never_blocks() -> None:
    # Arrange
    queue = TouchQueue(maxsize=4)

    # Act
    accepted = queue.offer(touch())

    # Assert
    assert accepted is True
    assert queue.pending == 1


async def test_a_full_queue_drops_loudly_instead_of_raising_or_waiting() -> None:
    """The two alternatives are both worse than a lost liveness ping.

    Blocking makes a customer's tap wait on our bookkeeping, inside the isolation lock;
    growing without bound turns a wedged writer into the thing that ends the process. So a
    full queue drops — and keeps a running total, because a drop that nobody counts is the
    same as a metric that lies.
    """
    # Arrange
    queue = TouchQueue(maxsize=2)
    queue.offer(touch())
    queue.offer(touch())

    # Act
    accepted = queue.offer(touch())

    # Assert
    assert accepted is False
    assert queue.dropped == 1
    assert queue.pending == 2


async def test_the_drop_counter_never_resets() -> None:
    """It is an operator's only signal that the writer has been falling behind."""
    # Arrange
    queue = TouchQueue(maxsize=1)
    queue.offer(touch())

    # Act
    for _ in range(3):
        queue.offer(touch())

    # Assert
    assert queue.dropped == 3


# ---------------------------------------------------------------------------
# The drain
# ---------------------------------------------------------------------------
async def test_the_drain_writes_what_it_is_handed() -> None:
    # Arrange
    store = RecordingTouchStore()
    queue = TouchQueue()
    drain = TouchDrain(store, queue)
    await drain.start()

    # Act
    queue.offer(touch())
    await settle()
    await drain.aclose()

    # Assert
    assert store.written == [(USER_ID, Language.EN)]


async def test_a_minute_of_taps_becomes_one_upsert() -> None:
    """Coalescing is what makes the queue affordable at all.

    Walking the wizard produces a touch per tap and every one of them is the same
    ``UPDATE last_seen_at``. A minute is the resolution anything downstream reads that
    column at, so nothing can tell the difference.
    """
    # Arrange
    store = RecordingTouchStore()
    queue = TouchQueue()
    drain = TouchDrain(store, queue)

    # Act — ten taps spread across the same minute
    for second in range(0, 50, 5):
        queue.offer(touch(at=MOMENT + timedelta(seconds=second)))
    await drain.drain_pending()

    # Assert
    assert len(store.written) == 1


async def test_the_next_minute_is_written_again() -> None:
    """Coalescing must not become "written once and never again", or ``last_seen_at``
    would freeze at whenever the process started."""
    # Arrange
    store = RecordingTouchStore()
    queue = TouchQueue()
    drain = TouchDrain(store, queue)

    # Act
    queue.offer(touch(at=MOMENT))
    queue.offer(touch(at=MOMENT + timedelta(seconds=61)))
    await drain.drain_pending()

    # Assert
    assert len(store.written) == 2


async def test_two_accounts_in_one_minute_are_both_written() -> None:
    """The coalescing key is (account, minute) — one busy customer must not silence another."""
    # Arrange
    store = RecordingTouchStore()
    queue = TouchQueue()
    drain = TouchDrain(store, queue)

    # Act
    queue.offer(touch(telegram_user_id=1))
    queue.offer(touch(telegram_user_id=2))
    await drain.drain_pending()

    # Assert
    assert [written[0] for written in store.written] == [1, 2]


async def test_closing_the_drain_writes_what_was_still_queued() -> None:
    """A shutdown is exactly when the backlog is largest, and these rows are what an
    operator blocks an account by. Throwing them away on the way out is the one moment the
    queue's whole point would be lost."""
    # Arrange — nothing running, so everything offered is still sitting in the queue
    store = RecordingTouchStore()
    queue = TouchQueue()
    drain = TouchDrain(store, queue)
    queue.offer(touch(telegram_user_id=1))
    queue.offer(touch(telegram_user_id=2))

    # Act
    await drain.aclose()

    # Assert
    assert len(store.written) == 2
    assert queue.pending == 0


async def test_a_store_that_raises_during_the_shutdown_drain_still_writes_the_rest() -> None:
    """The shutdown path needs the same guard the loop has, and for longer odds.

    ``drain_pending`` is reached from ``aclose``, which rides ``dispatcher.shutdown``. It
    used to call ``_write`` bare while ``_run`` wrapped the identical call — so one raising
    write aborted the remaining backlog AND the shutdown hook, at exactly the moment this
    class's own docstring says the backlog is largest.
    """

    # Arrange — the first write blows up, the rest are perfectly writable.
    class _ExplodesOnce(RecordingTouchStore):
        async def touch(self, telegram_user_id: int, *, ui_language: Language) -> Result[None]:
            if telegram_user_id == 1:
                raise RuntimeError("the store is on fire")
            return await super().touch(telegram_user_id, ui_language=ui_language)

    store = _ExplodesOnce()
    queue = TouchQueue()
    drain = TouchDrain(store, queue)
    queue.offer(touch(telegram_user_id=1))
    queue.offer(touch(telegram_user_id=2))

    # Act — this must not raise out of the dispatcher's shutdown hook.
    await drain.aclose()

    # Assert
    assert store.written == [(2, Language.EN)]
    assert queue.pending == 0


async def test_a_store_that_returns_an_error_does_not_stop_the_next_write() -> None:
    """One unwritable account must not silence every later one."""
    # Arrange
    store = RecordingTouchStore(failure=StorageError("the users table is unavailable"))
    queue = TouchQueue()
    drain = TouchDrain(store, queue)
    queue.offer(touch(telegram_user_id=1))
    await drain.drain_pending()
    store.failure = None

    # Act
    queue.offer(touch(telegram_user_id=2))
    written = await drain.drain_pending()

    # Assert
    assert written == 1
    assert store.written == [(2, Language.EN)]


async def test_a_failed_write_is_retried_rather_than_remembered_as_done() -> None:
    """The coalescing memo records what was WRITTEN, not what was attempted.

    Recording the attempt would mean a minute in which the database was down became a
    minute the drain believes it has already covered — and the account would silently keep
    its stale ``ui_language`` until the next minute came round.
    """
    # Arrange
    store = RecordingTouchStore(failure=StorageError("the users table is unavailable"))
    queue = TouchQueue()
    drain = TouchDrain(store, queue)
    queue.offer(touch())
    await drain.drain_pending()

    # Act — the same minute, once the store has recovered
    store.failure = None
    queue.offer(touch())
    written = await drain.drain_pending()

    # Assert
    assert written == 1


async def test_a_store_that_raises_leaves_the_drain_alive() -> None:
    """``EntitlementStore`` promises a ``Result`` and never an exception; this is the one
    loop where believing that promise would end every later write in the process."""
    # Arrange
    store = RecordingTouchStore()
    store.explode = True
    queue = TouchQueue()
    drain = TouchDrain(store, queue)
    await drain.start()
    queue.offer(touch(telegram_user_id=1))
    await settle()

    # Act
    store.explode = False
    queue.offer(touch(telegram_user_id=2))
    await settle()

    # Assert
    assert drain.is_running is True
    assert store.written == [(2, Language.EN)]
    await drain.aclose()


async def test_starting_twice_does_not_stack_two_drains() -> None:
    """``dispatcher.startup`` fires once per poll, and a reconnecting bot polls again."""
    # Arrange
    store = RecordingTouchStore()
    queue = TouchQueue()
    drain = TouchDrain(store, queue)

    # Act
    await drain.start()
    first = drain._task
    await drain.start()

    # Assert
    assert drain._task is first
    await drain.aclose()


async def test_a_wedged_store_fills_the_queue_and_costs_the_customer_nothing() -> None:
    """The whole design, end to end: the writer hangs, the queue fills, offers keep
    returning immediately and the drops are counted. Not one of them waits."""
    # Arrange — a store that never returns
    store = RecordingTouchStore()
    store.gate = asyncio.Event()
    queue = TouchQueue(maxsize=2)
    drain = TouchDrain(store, queue)
    await drain.start()

    # Act — far more offers than the queue can hold
    for index in range(20):
        queue.offer(touch(telegram_user_id=index))
    await settle()

    # Assert
    assert queue.dropped >= 17
    assert store.written == []
    store.gate.set()
    await drain.aclose()


async def test_the_coalescing_memo_forgets_everything_rather_than_growing_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One entry per account, in a process that runs for months.

    Forgetting costs one redundant upsert per account — exactly what the memo was saving —
    and never a wrong row, so dropping it wholesale is the right last resort. The cap is
    patched rather than reached: fifty thousand accounts is not a unit test.
    """
    # Arrange
    monkeypatch.setattr(gate_module, "_MEMO_MAX_ACCOUNTS", 2)
    store = RecordingTouchStore()
    queue = TouchQueue()
    drain = TouchDrain(store, queue)

    # Act — three accounts in one minute, then the first one again in that same minute
    for telegram_user_id in (1, 2, 3, 1):
        queue.offer(touch(telegram_user_id=telegram_user_id))
    await drain.drain_pending()

    # Assert — account 1 was written twice: the memo was dropped, not silently unbounded
    assert [written[0] for written in store.written] == [1, 2, 3, 1]
