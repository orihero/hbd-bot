"""The window between Confirm and delivery — the one that used to cost real money.

Two defects are pinned here and neither is visible from a single sequential press:

* a double tap on Confirm bought two songs, because everything the handler awaited before
  it flipped the FSM was a window in which both taps passed every gate;
* the FSM was cleared the instant the order was queued, so for the whole generation window
  the bot answered anything the customer typed with "that session expired".

The concurrency tests drive two real ``Update`` objects through a real ``Dispatcher`` with
a payment provider that blocks, because that is the only arrangement in which the second
tap's state filter is evaluated while the first tap is still inside authorisation. Without
the block the fakes never yield and the race cannot happen.

Every ``BotDeps`` here carries an EMPTY ``FakeProfiles``, which is the correct half of the
two-sided rule: these tests reach ``Wizard.submitting`` by WALKING — ``walk_to_confirm``
drives the real onboarding screens and creates the row on the way past — and only then set
the state by hand. A seeded store would work too but would hide the walk's own coverage; a
missing store would fail open, leave the walker's first language press unmatched, and turn
every race assertion below into "that session expired".
"""

from __future__ import annotations

import asyncio
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bayram.bot.app import build_dispatcher
from bayram.bot.callbacks import NavAction, NavCB
from bayram.bot.deps import BotDeps
from bayram.bot.draft import WizardDraft
from bayram.bot.handlers.confirm import _order_id_for
from bayram.bot.handlers.submitting import ORDER_ID_KEY, PROGRESS_MESSAGE_ID_KEY
from bayram.bot.i18n import translate
from bayram.bot.states import Wizard
from bayram.config import Settings
from bayram.contracts import (
    Genre,
    Language,
    Occasion,
    PaymentAuthorization,
    Result,
    VoiceGender,
    ok,
)
from tests.test_bot.conftest import (
    CHAT_ID,
    USER_ID,
    FakeProfiles,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
    callback_update,
    message_update,
)
from tests.test_bot.test_wizard_flow import (
    UZBEK_DISPLAY,
    complete_onboarding,
    press,
    tap,
    walk_to_confirm,
)

#: How many times to yield to the loop before deciding a task has parked where we want it.
#: The dispatcher awaits several layers of middleware and filters, none of which suspends
#: on anything real, so one yield is not enough and a bound beats a sleep.
_YIELDS: int = 50


class GatedPaymentProvider:
    """Authorises, but only once the test lets it — the suspension a real rail would have.

    Every fake in this suite answers without ever yielding to the event loop, so two
    ``feed_update`` calls run strictly one after the other and a double tap cannot race.
    This provider is the one place a handler genuinely parks, which puts the second tap's
    state filter exactly where the defect lived.
    """

    name = "gated"

    def __init__(self) -> None:
        self.calls = 0
        self.gate = asyncio.Event()

    async def authorize(
        self, *, order_id: Any, amount_minor: int, currency: str, telegram_user_id: int
    ) -> Result[Any]:
        self.calls += 1
        await self.gate.wait()
        return ok(
            PaymentAuthorization(
                order_id=order_id,
                provider=self.name,
                reference="gated",
                amount_minor=amount_minor,
                currency=currency,
                is_authorized=True,
            )
        )


async def _settle() -> None:
    for _ in range(_YIELDS):
        await asyncio.sleep(0)


def _draft(**changes: Any) -> WizardDraft:
    return WizardDraft(
        ui_language=Language.EN,
        occasion=Occasion.BIRTHDAY,
        genre=Genre.POP,
        vocal_gender=VoiceGender.FEMALE,
    ).updated(**changes)


# ---------------------------------------------------------------------------
# NAV-01 — a double tap on Confirm must buy exactly one song
# ---------------------------------------------------------------------------
async def test_two_concurrent_confirms_queue_exactly_one_order(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    # Arrange — the second tap arrives while the first is inside authorisation
    submitter = RecordingSubmitter()
    payment = GatedPaymentProvider()
    storage = MemoryStorage()
    dispatcher = build_dispatcher(
        BotDeps(
            settings=settings,
            submitter=submitter,
            content=RecordingContentWriter(),
            payment=payment,
            profiles=FakeProfiles(),
        ),
        storage=storage,
    )
    await walk_to_confirm(dispatcher, bot)
    confirm = NavCB(action=NavAction.CONFIRM).pack()

    # Act — both taps enter the dispatcher before EITHER has been dispatched, which is
    # what one ``getUpdates`` batch delivers and what ``_settle()`` between the two
    # create_task calls quietly rules out.
    first = asyncio.create_task(dispatcher.feed_update(bot, callback_update(confirm)))
    second = asyncio.create_task(dispatcher.feed_update(bot, callback_update(confirm)))
    await _settle()
    payment.gate.set()
    await asyncio.gather(first, second)

    # Assert — one order, and the second tap never even reached the payment gate
    assert len(submitter.submitted) == 1
    assert payment.calls == 1


async def test_the_losing_tap_does_not_land_the_customer_back_on_the_confirm_screen(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    """The park has to survive the double tap, or every guard built on it goes blind.

    Without the dispatcher's per-chat lock both taps read ``Wizard:confirm`` and both ran.
    The loser collided at the ``orders`` primary key, was told "I could not hand this to
    the studio" about an order that was queued and would be delivered, and — worse — was
    put back on ``Wizard.confirm`` by the rollback. ``order_in_flight`` checks the state
    first, so from there Cancel answered "nothing was made, and nothing was kept" while the
    song generated.
    """
    # Arrange
    submitter = RecordingSubmitter()
    payment = GatedPaymentProvider()
    storage = MemoryStorage()
    dispatcher = build_dispatcher(
        BotDeps(
            settings=settings,
            submitter=submitter,
            content=RecordingContentWriter(),
            payment=payment,
            profiles=FakeProfiles(),
        ),
        storage=storage,
    )
    await walk_to_confirm(dispatcher, bot)
    confirm = NavCB(action=NavAction.CONFIRM).pack()

    # Act
    first = asyncio.create_task(dispatcher.feed_update(bot, callback_update(confirm)))
    second = asyncio.create_task(dispatcher.feed_update(bot, callback_update(confirm)))
    await _settle()
    payment.gate.set()
    await asyncio.gather(first, second)

    # Assert — the session is parked on the one order that was queued
    key = StorageKey(bot_id=bot.id, chat_id=CHAT_ID, user_id=USER_ID)
    order, _chat_id, _message_id = submitter.submitted[0]
    assert await storage.get_state(key) == Wizard.submitting.state
    assert (await storage.get_data(key))[ORDER_ID_KEY] == str(order.id)
    texts = " ".join(getattr(call, "text", "") or "" for call in session.calls)
    assert translate("wizard.enqueue_failed", Language.EN) not in texts


async def test_the_second_confirm_is_answered_rather_than_ignored(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    submitter = RecordingSubmitter()
    payment = GatedPaymentProvider()
    dispatcher = build_dispatcher(
        BotDeps(
            settings=settings,
            submitter=submitter,
            content=RecordingContentWriter(),
            payment=payment,
            profiles=FakeProfiles(),
        ),
        storage=MemoryStorage(),
    )
    await walk_to_confirm(dispatcher, bot)
    confirm = NavCB(action=NavAction.CONFIRM).pack()

    # Act
    first = asyncio.create_task(dispatcher.feed_update(bot, callback_update(confirm)))
    await _settle()
    session.clear()
    second = asyncio.create_task(dispatcher.feed_update(bot, callback_update(confirm)))
    await _settle()
    payment.gate.set()
    await asyncio.gather(first, second)

    # Assert — the tap that lost the race is told where its song is, not left silent
    texts = " ".join(getattr(call, "text", "") or "" for call in session.calls)
    assert UZBEK_DISPLAY in texts


def test_the_order_id_is_the_same_for_the_same_draft() -> None:
    # Arrange
    draft = _draft(note="loves plov")

    # Act / Assert — a tap that leaks through collides at the submitter by design
    assert _order_id_for(USER_ID, draft) == _order_id_for(USER_ID, draft)


def test_a_different_answer_or_a_different_person_is_a_different_order() -> None:
    # Arrange
    draft = _draft(note="loves plov")

    # Act / Assert
    assert _order_id_for(USER_ID, draft) != _order_id_for(USER_ID + 1, draft)
    assert _order_id_for(USER_ID, draft) != _order_id_for(USER_ID, draft.updated(note="other"))


def test_the_same_answers_in_a_second_run_are_a_second_order() -> None:
    """A customer who wants another copy of the same song has to be able to buy one.

    Determinism is meant to survive a double tap on ONE confirm screen. Keyed on the
    answers alone it also made a repeat purchase impossible for ever: the second order
    minted the id the first one already holds, died on the ``orders`` primary key, and was
    reported as "I could not hand this to the studio" with no reason and no way out.
    """
    # Arrange — the same person, the same four answers, the same lyric, a new run
    first_run = _draft(session_id="run-one", note="loves plov")
    second_run = first_run.updated(session_id="run-two")

    # Act / Assert
    assert _order_id_for(USER_ID, first_run) != _order_id_for(USER_ID, second_run)


async def test_each_pass_through_the_wizard_gets_its_own_session_id(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext
) -> None:
    """Two runs, two ids — and 🎵 is what opens a run now, not ``/start``.

    The property is the one the order id is derived from, and it is unchanged: two passes over
    the same four answers must mint different ids or the second collides on the ``orders``
    primary key and is reported as "I could not hand this to the studio" for ever.

    What changed is where a run begins. ``/start`` answers "who is this?" and opens no wizard —
    it draws an onboarding screen or the menu — so it mints no draft at all, and this test read
    the mint through it. Driving it with the 🎵 button instead is not a workaround: 🎵 is the
    ONLY way into the wizard now, and ``menu.handle_menu_label`` reaches the same
    ``common.reset_to_welcome`` that ↩️ Start over and 🎂 Make another do.
    """
    # Arrange
    await complete_onboarding(dispatcher, bot)

    # Act — two clean slates, which is what 🎵 performs on a menu it never leaves
    await tap(dispatcher, bot, "menu.generate", Language.EN)
    first = (await state.get_data())["draft"]["session_id"]
    await tap(dispatcher, bot, "menu.generate", Language.EN)
    second = (await state.get_data())["draft"]["session_id"]

    # Assert
    assert first and second and first != second


# ---------------------------------------------------------------------------
# SELL-03 / NAV-02 — the session stays parked while the song is made
# ---------------------------------------------------------------------------
async def test_confirm_parks_the_session_on_the_order_instead_of_clearing_it(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext, submitter: RecordingSubmitter
) -> None:
    # Arrange
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    order, _, progress_message_id = submitter.submitted[0]
    data = await state.get_data()
    assert await state.get_state() == Wizard.submitting.state
    assert data[ORDER_ID_KEY] == str(order.id)
    assert data[PROGRESS_MESSAGE_ID_KEY] == progress_message_id


async def test_typing_while_the_song_is_made_is_answered_with_where_it_is(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())
    session.clear()

    # Act — the customer asks where their song is
    await dispatcher.feed_update(bot, message_update("is it ready?"))

    # Assert — never "that session expired"
    text = session.last_screen.text
    assert text == translate("wizard.queued", Language.EN, name=UZBEK_DISPLAY)
    assert translate("wizard.expired", Language.EN) not in text


async def test_a_stale_button_while_the_song_is_made_does_not_report_an_expired_session(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())
    session.clear()

    # Act — an occasion button from a screen five steps back
    await dispatcher.feed_update(bot, callback_update("occ:birthday"))

    # Assert
    assert session.last_screen.text == translate("wizard.queued", Language.EN, name=UZBEK_DISPLAY)


async def test_typing_while_the_lyric_is_being_written_says_so_rather_than_queued(
    bot: Bot, session: RecordingSession, settings: Settings
) -> None:
    """``Wizard.submitting`` is shared with the lyric write, and the two are not the same.

    Nothing is in the studio while the writer has the brief, so the copy that says a song
    is being made would be a lie. The order id in FSM data is what tells them apart.
    """
    # Arrange — a session parked mid-write: submitting, with a draft, with no order id
    storage = MemoryStorage()
    dispatcher = build_dispatcher(
        BotDeps(
            settings=settings,
            submitter=RecordingSubmitter(),
            content=RecordingContentWriter(),
            profiles=FakeProfiles(),
        ),
        storage=storage,
    )
    state = FSMContext(
        storage=storage, key=StorageKey(bot_id=bot.id, chat_id=CHAT_ID, user_id=USER_ID)
    )
    await walk_to_confirm(dispatcher, bot)
    await state.set_state(Wizard.submitting)
    session.clear()

    # Act
    await dispatcher.feed_update(bot, message_update("anything"))

    # Assert
    assert session.last_screen.text == translate(
        "wizard.lyrics.writing", Language.EN, name=UZBEK_DISPLAY
    )
