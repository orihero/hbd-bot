"""The read-only entitlement gate on the Confirm screen.

Two properties are load-bearing and each is tested directly rather than inferred:

* **the gate never writes.** :class:`FakeEntitlements` records every call to every WRITE
  method on the protocol, and the tests assert that list is empty. That is the whole
  reason the debit lives in the worker: ``_authorize_and_submit`` has three early returns
  after the gate — payment declined, ``_start_progress`` returned ``None``,
  ``submitter.submit`` returned ``Err`` — and none of them can reach a refund, because no
  ``orders`` row and no ARQ job exist yet;
* **a terminal refusal is not a dead end.** Out of credits and blocked end on a start-over
  keyboard with a route to a human, not back on a Confirm button that cannot succeed. The
  in-flight cap deliberately does NOT: that one lifts on its own when the song lands, so
  re-arming Confirm is the honest answer there.

Every test builds its own ``BotDeps``. The shared ``deps`` fixture wires no meter at all
(tests/test_bot/conftest.py), which is exactly what keeps the other twenty-odd bot modules
running through an unmetered gate — so this file is the only coverage the gate has.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from hbd.bot.app import build_dispatcher
from hbd.bot.callbacks import NavAction, NavCB
from hbd.bot.deps import BotDeps
from hbd.bot.i18n import translate
from hbd.bot.states import Wizard
from hbd.config import Settings
from hbd.contracts import Language, Result, err, ok
from hbd.entitlements import ChargeOutcome, CreditBalance, SettlementOutcome
from hbd.errors import HbdError, StorageError
from tests.test_bot.conftest import (
    FakeProfiles,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    buttons,
)
from tests.test_bot.test_wizard_flow import press, walk_to_confirm

#: The day the allowance after ``FIXED_MOMENT`` (2026-03-21) opens, with the shipped
#: 30-day window measured from the 1970 epoch. Written out rather than recomputed with
#: ``period_start`` so that a change to the window arithmetic fails HERE, in the copy the
#: customer reads, instead of agreeing with itself.
NEXT_GRANT_DAY = "2026-04-07"


class FakeEntitlements:
    """A meter the bot can read, which shouts if the bot ever writes to it.

    Structurally a :class:`hbd.entitlements.EntitlementStore`. ``in_flight`` is DERIVED
    from ``open_orders`` minus the order being confirmed, exactly as the real ledger
    derives it from unsettled debits, so a test can seed "this account already has a song
    being made" without the excluded-order rule quietly making it zero.
    """

    def __init__(
        self, *, credits: int = 3, is_blocked: bool = False, failure: HbdError | None = None
    ) -> None:
        self.credits = credits
        self.is_blocked = is_blocked
        self.failure = failure
        self.open_orders: set[UUID] = set()
        #: Every ``balance_for`` call, as the order id it was told to exclude.
        self.reads: list[UUID | None] = []
        #: Every WRITE the gate attempted. The point of the whole file is that it is empty.
        self.writes: list[str] = []
        #: Every account ``/forget`` asked this store to erase.
        self.erased: list[int] = []

    async def balance_for(
        self, telegram_user_id: int, *, exclude_order_id: UUID | None = None
    ) -> Result[CreditBalance]:
        self.reads.append(exclude_order_id)
        if self.failure is not None:
            return err(self.failure)
        others = [order for order in self.open_orders if order != exclude_order_id]
        return ok(
            CreditBalance(
                telegram_user_id=telegram_user_id,
                credits=self.credits,
                in_flight=len(others),
                is_blocked=self.is_blocked,
            )
        )

    # -- writes. None of these may ever be reached from the bot ------------

    def _snapshot(self, telegram_user_id: int) -> CreditBalance:
        return CreditBalance(
            telegram_user_id=telegram_user_id,
            credits=self.credits,
            in_flight=len(self.open_orders),
            is_blocked=self.is_blocked,
        )

    async def charge(
        self, *, telegram_user_id: int, order_id: UUID, actor: str, cost: int = 1
    ) -> Result[tuple[ChargeOutcome, CreditBalance]]:
        self.writes.append("charge")
        return ok((ChargeOutcome.CHARGED, self._snapshot(telegram_user_id)))

    async def settle(
        self, *, telegram_user_id: int, order_id: UUID, outcome: SettlementOutcome, actor: str
    ) -> Result[bool]:
        self.writes.append("settle")
        return ok(True)

    async def grant(
        self, *, telegram_user_id: int, credits: int, idempotency_key: str, actor: str
    ) -> Result[CreditBalance]:
        self.writes.append("grant")
        return ok(self._snapshot(telegram_user_id))

    async def set_blocked(self, telegram_user_id: int, *, is_blocked: bool) -> Result[None]:
        self.writes.append("set_blocked")
        return ok(None)

    async def touch(self, telegram_user_id: int, *, ui_language: Language | None) -> Result[None]:
        # ``Language | None`` and not ``Language``: the inbound gate now meets people who have
        # never answered the language question, and ``None`` is how it says "I do not know yet"
        # instead of clobbering a stored choice with the operator's default. A fake that kept
        # the narrow parameter would not merely be stale — parameter types are contravariant,
        # so it would stop being a structural ``EntitlementStore`` and ``mypy --strict`` would
        # fail at the assignment into ``BotDeps.entitlements``.
        self.writes.append("touch")
        return ok(None)

    async def forget(self, telegram_user_id: int) -> Result[None]:
        # Recorded as a write like the rest, so the "the gate never writes" assertions
        # below also prove the gate never erases anybody. Only `/forget` may call this,
        # and `test_commands.py` asserts that it does — from the other side of the fence.
        self.writes.append("forget")
        self.erased.append(telegram_user_id)
        return ok(None)


def enforcing(settings: Settings) -> Settings:
    """The same settings with the balance check switched on.

    ``credits_enforced`` ships False — the meter is wired, observable and dark — so a test
    of the refusal has to turn it on explicitly. That is the flag's whole contract.
    """
    return settings.model_copy(update={"credits_enforced": True})


def wire(
    settings: Settings,
    submitter: RecordingSubmitter,
    credits: FakeEntitlements,
    clock: Callable[[], datetime],
) -> BotDeps:
    """A metered dispatcher's dependencies, profile store included.

    ``profiles`` is not decoration. Every test in this file reaches the Confirm screen through
    :func:`~tests.test_bot.test_wizard_flow.walk_to_confirm`, which now drives the real
    onboarding screens; with no store at all the fail-open rule (C1-5) treats the caller as
    already onboarded, so ``/start`` draws the menu, the walker's ``LanguageCB(slot=UI)`` press
    matches no handler, and every assertion below fails with "that session expired" — a message
    about the fallback router, in a file about credits. A fresh EMPTY store per call is the
    right one: the walk is what creates the row, and sharing one between dispatchers would let
    a test inherit an account another test onboarded.
    """
    return BotDeps(
        settings=settings,
        submitter=submitter,
        content=RecordingContentWriter(),
        clock=clock,
        entitlements=credits,
        profiles=FakeProfiles(),
    )


def screen_texts(session: RecordingSession) -> str:
    """Everything that was put in front of the user, sent or edited, as one string."""
    return " ".join(call.text or "" for call in session.calls if hasattr(call, "text"))


async def test_an_exhausted_allowance_is_refused_before_anything_is_queued(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    # Arrange
    credits = FakeEntitlements(credits=0)
    dispatcher = build_dispatcher(
        wire(enforcing(settings), submitter, credits, clock), storage=storage
    )
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert — nothing queued, and the customer was told why on the screen they were on
    assert submitter.submitted == []
    assert translate("error.credits_exhausted", Language.EN) in screen_texts(session)


async def test_the_exhausted_refusal_names_the_day_the_next_song_opens(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """A refusal a customer cannot act on sends them to support, or away.

    The allowance is rolling, so there is a real day on which this account can order
    again. Saying it is what makes the refusal true as well as final.
    """
    # Arrange
    credits = FakeEntitlements(credits=0)
    dispatcher = build_dispatcher(
        wire(enforcing(settings), submitter, credits, clock), storage=storage
    )
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    expected = translate("credits.next_opens", Language.EN, next_grant_at=NEXT_GRANT_DAY)
    assert expected in screen_texts(session)
    assert NEXT_GRANT_DAY in expected


async def test_the_exhausted_refusal_ends_on_a_start_over_screen_not_on_confirm(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    state: FSMContext,
    clock: Callable[[], datetime],
) -> None:
    """Re-arming a Confirm button that cannot succeed is the dead end this branch exists for.

    Nothing inside the wizard changes this answer — only the calendar does — so the screen
    the customer is left holding must offer the one thing that still leads somewhere.
    """
    # Arrange
    credits = FakeEntitlements(credits=0)
    dispatcher = build_dispatcher(
        wire(enforcing(settings), submitter, credits, clock), storage=storage
    )
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    offered = {data for _text, data in buttons(session.last_screen.reply_markup)}
    # Both buttons are NAMED rather than checked for membership. ``start_over_keyboard`` grew a
    # 🏠 Back to menu row (CONTRACTS §5), and a superset assertion would have absorbed that
    # silently — as it would absorb the row's later disappearance, which is the regression worth
    # catching: a customer out of credits cannot start over to any effect, so the way home is
    # the only button on this screen that leads anywhere.
    assert offered == {
        NavCB(action=NavAction.START_OVER).pack(),
        NavCB(action=NavAction.TO_MENU).pack(),
    }
    assert await state.get_state() is None


async def test_the_confirm_screen_gate_reads_the_meter_and_writes_nothing_to_it(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """The core safety property: no bot-side path can consume a credit, because none writes.

    The three early returns after this gate cannot compensate a debit — there is no orders
    row and no ARQ job yet — so the only defence that works is having nothing to undo.
    """
    # Arrange
    credits = FakeEntitlements(credits=0)
    dispatcher = build_dispatcher(
        wire(enforcing(settings), submitter, credits, clock), storage=storage
    )
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert — one read of THIS order, told to leave it out, and not one write
    #
    # Filtered rather than counted: since WU8 the inbound gate reads the same meter once
    # per account per cache window to answer "is this account blocked?", and that read
    # passes no order id. The read this test is about is the one that names an order.
    assert credits.writes == []
    order_reads = [read for read in credits.reads if read is not None]
    assert len(order_reads) == 1


async def test_a_dark_meter_lets_an_empty_account_straight_through(
    settings: Settings,
    bot: Bot,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """The shipped configuration. The merge must not be what starts refusing customers."""
    # Arrange — wired and readable, but HBD_CREDITS_ENFORCED is off
    credits = FakeEntitlements(credits=0)
    dispatcher = build_dispatcher(wire(settings, submitter, credits, clock), storage=storage)
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    assert len(submitter.submitted) == 1
    assert credits.writes == []


async def test_a_blocked_account_is_refused_even_with_credits_and_the_meter_dark(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """The block gate refuses ABUSE, not customers, so it is never behind ``credits_enforced``.

    The account is blocked mid-session, AFTER the walk, and that is the honest shape rather
    than a convenience. Since WU8 an account that is already blocked never reaches this
    screen at all — ``hbd.bot.gate`` refuses the ``/start`` — so the case this gate is the
    last defence for is the one where the block lands while someone is part-way through:
    the inbound gate is still holding a cached "not blocked" for up to
    ``HBD_INBOUND_BLOCK_CACHE_S``, and the Confirm screen reads the meter live.
    """
    # Arrange
    credits = FakeEntitlements(credits=99)
    dispatcher = build_dispatcher(wire(settings, submitter, credits, clock), storage=storage)
    await walk_to_confirm(dispatcher, bot)
    credits.is_blocked = True

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    assert submitter.submitted == []
    assert translate("error.blocked", Language.EN) in screen_texts(session)
    offered = {data for _text, data in buttons(session.last_screen.reply_markup)}
    # Both buttons, for the reason given on the exhausted-allowance case above: the 🏠 row is
    # part of what "not a dead end" now means, and an exact set is what keeps it there.
    assert offered == {
        NavCB(action=NavAction.START_OVER).pack(),
        NavCB(action=NavAction.TO_MENU).pack(),
    }


async def test_a_second_song_is_refused_while_the_first_one_is_still_being_made(
    settings: Settings,
    bot: Bot,
    session: RecordingSession,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """The cap refuses a genuinely NEW order, which is the only version of this worth testing.

    The second run is a full fresh walk through the wizard: ``reset_to_welcome`` mints a new
    ``session_id``, so the UUID5 order id differs from the first. Replaying the first draft
    instead would have been refused by ``RecordingSubmitter``'s own duplicate-id guard, and
    the test would have proved nothing about the in-flight cap at all.
    """
    # Arrange — one song already queued and unsettled
    credits = FakeEntitlements(credits=9)
    dispatcher = build_dispatcher(wire(settings, submitter, credits, clock), storage=storage)
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())
    first_order, _chat, _message = submitter.submitted[0]
    credits.open_orders.add(first_order.id)
    session.clear()

    # Act — the customer walks the whole wizard again and confirms a different draft
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert — a new order id, refused by the cap and nothing else
    assert len(submitter.submitted) == 1
    assert translate("error.too_many_in_flight", Language.EN) in screen_texts(session)
    assert credits.writes == []


async def test_the_in_flight_refusal_leaves_the_confirm_button_armed(
    settings: Settings,
    bot: Bot,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    state: FSMContext,
    clock: Callable[[], datetime],
) -> None:
    """This refusal lifts on its own, so it is a wait and not a dead end.

    Pressing Confirm again once the first song lands genuinely works, which is why this
    branch puts the customer back on the confirm screen rather than clearing the session
    the way the out-of-credits branch does.
    """
    # Arrange
    credits = FakeEntitlements(credits=9)
    credits.open_orders.add(UUID("11111111-2222-3333-4444-555555555555"))
    dispatcher = build_dispatcher(wire(settings, submitter, credits, clock), storage=storage)
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    assert submitter.submitted == []
    assert await state.get_state() == Wizard.confirm.state


async def test_an_account_with_credits_gets_through_and_is_submitted_exactly_once(
    settings: Settings,
    bot: Bot,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    # Arrange
    credits = FakeEntitlements(credits=1)
    dispatcher = build_dispatcher(
        wire(enforcing(settings), submitter, credits, clock), storage=storage
    )
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    assert len(submitter.submitted) == 1
    assert credits.writes == []


async def test_a_meter_that_cannot_be_read_lets_the_order_through(
    settings: Settings,
    bot: Bot,
    storage: MemoryStorage,
    submitter: RecordingSubmitter,
    clock: Callable[[], datetime],
) -> None:
    """Fails OPEN, deliberately.

    The worker gate reads the same rows inside the transaction that charges, so an
    unreadable meter here costs a refused customer one minute of progress bar before they
    are told — which is exactly where they were told before this gate existed. Failing
    closed would turn a database blip into a product-wide outage.
    """
    # Arrange
    credits = FakeEntitlements(credits=0, failure=StorageError("the database is unreachable"))
    dispatcher = build_dispatcher(
        wire(enforcing(settings), submitter, credits, clock), storage=storage
    )
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    assert len(submitter.submitted) == 1


async def test_a_queue_failure_after_the_gate_leaves_the_meter_untouched_and_a_retry_works(
    settings: Settings,
    bot: Bot,
    storage: MemoryStorage,
    clock: Callable[[], datetime],
) -> None:
    """The exact shape the read-only gate exists to make harmless.

    A bot-side debit would have been spent here on a Redis blip, with no order row and no
    job for any settlement path to find — and the second press mints the same UUID5, so
    the customer would have been charged twice for one song.
    """
    # Arrange
    submitter = RecordingSubmitter(failure=RuntimeError("redis is down"))
    credits = FakeEntitlements(credits=1)
    dispatcher = build_dispatcher(
        wire(enforcing(settings), submitter, credits, clock), storage=storage
    )
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Act — the queue comes back and the customer presses Confirm again
    submitter.failure = None
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    assert len(submitter.submitted) == 1
    assert credits.writes == []
