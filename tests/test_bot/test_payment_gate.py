"""The payment gate. Out of scope for this build means "always passes", not "absent".

Every failure here also has to put the FSM back. ``handle_confirm`` flips to
``Wizard.submitting`` before it does anything else, so that a second tap does not match its
own state filter; a declined payment or an unreachable queue that left the session in that
state would strand a customer on a confirm screen whose only button no longer worked.

Every ``BotDeps`` built here carries a ``FakeProfiles``, and it is a precondition rather than
a habit: ``walk_to_confirm`` drives the real onboarding screens, so a dispatcher with
``profiles=None`` fails open, treats the caller as onboarded, and answers the walker's first
language press with nothing at all — every test in the file would then fail on "that session
expired" and blame the fallback router for a payment bug that is not there.
``test_walker_preconditions.py`` enforces that statically, so this cannot rot back.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from hbd.bot.app import build_dispatcher
from hbd.bot.callbacks import NavAction, NavCB
from hbd.bot.deps import BotDeps
from hbd.bot.i18n import translate
from hbd.bot.payment import DEFAULT_CURRENCY, FREE_AMOUNT_MINOR, NoopPaymentProvider
from hbd.bot.states import Wizard
from hbd.config import Settings
from hbd.contracts import Language, Ok, PaymentAuthorization, PaymentProvider, Result, ok
from tests.test_bot.conftest import (
    CHAT_ID,
    USER_ID,
    DecliningPaymentProvider,
    FakeProfiles,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
)
from tests.test_bot.test_wizard_flow import press, walk_to_confirm


async def test_noop_provider_authorises_and_charges_nothing() -> None:
    # Arrange
    provider = NoopPaymentProvider()
    order_id = uuid4()

    # Act
    result = await provider.authorize(
        order_id=order_id,
        amount_minor=FREE_AMOUNT_MINOR,
        currency=DEFAULT_CURRENCY,
        telegram_user_id=USER_ID,
    )

    # Assert
    assert isinstance(result, Ok)
    assert result.value.is_authorized
    assert result.value.amount_minor == 0
    assert result.value.order_id == order_id


def test_noop_provider_satisfies_the_payment_protocol() -> None:
    # Arrange / Act / Assert
    assert isinstance(NoopPaymentProvider(), PaymentProvider)


class RecordingPaymentProvider:
    """Authorises, and remembers who it was told is paying."""

    name = "recording"

    def __init__(self) -> None:
        self.payers: list[int] = []

    async def authorize(
        self, *, order_id: UUID, amount_minor: int, currency: str, telegram_user_id: int
    ) -> Result[PaymentAuthorization]:
        self.payers.append(telegram_user_id)
        return ok(
            PaymentAuthorization(
                order_id=order_id,
                provider=self.name,
                reference="recorded",
                amount_minor=amount_minor,
                currency=currency,
                is_authorized=True,
            )
        )


async def test_the_gate_is_told_which_telegram_user_is_paying(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    """The order id is a UUID5 over a draft, so identity has to travel beside it.

    A provider that meters or blocks per person is handed ``telegram_user_id`` and nothing
    else that names a human; passing the wrong one — or a plausible-looking id re-derived
    from somewhere other than the tap — would charge one customer for another's song with
    no symptom at all. ``_build_order`` sets it from ``callback.from_user.id``, and this
    asserts the gate receives exactly that.
    """
    # Arrange
    payment = RecordingPaymentProvider()
    dispatcher = build_dispatcher(
        BotDeps(
            settings=settings,
            submitter=RecordingSubmitter(),
            content=RecordingContentWriter(),
            payment=payment,
            profiles=FakeProfiles(),
        ),
        storage=MemoryStorage(),
    )
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    assert payment.payers == [USER_ID]


async def test_declined_payment_blocks_the_queue_and_keeps_the_user_on_confirm(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    submitter = RecordingSubmitter()
    storage = MemoryStorage()
    deps = BotDeps(
        settings=settings,
        submitter=submitter,
        content=RecordingContentWriter(),
        payment=DecliningPaymentProvider(),
        profiles=FakeProfiles(),
    )
    dispatcher = build_dispatcher(deps, storage=storage)
    state = FSMContext(
        storage=storage, key=StorageKey(bot_id=bot.id, chat_id=CHAT_ID, user_id=USER_ID)
    )
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert — nothing queued, and the user is told, in their language
    assert submitter.submitted == []
    assert await state.get_state() == Wizard.confirm.state
    texts = " ".join(call.text or "" for call in session.calls if hasattr(call, "text"))
    assert translate("wizard.payment_declined", Language.EN) in texts


async def test_queue_failure_keeps_the_user_on_confirm(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    submitter = RecordingSubmitter(failure=RuntimeError("redis is down"))
    storage = MemoryStorage()
    dispatcher = build_dispatcher(
        BotDeps(
            settings=settings,
            submitter=submitter,
            content=RecordingContentWriter(),
            profiles=FakeProfiles(),
        ),
        storage=storage,
    )
    state = FSMContext(
        storage=storage, key=StorageKey(bot_id=bot.id, chat_id=CHAT_ID, user_id=USER_ID)
    )
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert — told what happened, and left on a screen whose button still works
    texts = " ".join(call.text or "" for call in session.calls if hasattr(call, "text"))
    assert translate("wizard.enqueue_failed", Language.EN) in texts
    assert await state.get_state() == Wizard.confirm.state


async def test_a_second_confirm_after_a_queue_failure_is_accepted(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    """The rollback is only worth anything if the retry actually goes through.

    ``handle_confirm`` is filtered on ``Wizard.confirm``, so a failure path that forgot to
    put the state back would leave the button matching no handler at all — a screen that
    looks fine and does nothing, which is worse than the error it followed.
    """
    # Arrange
    submitter = RecordingSubmitter(failure=RuntimeError("redis is down"))
    dispatcher = build_dispatcher(
        BotDeps(
            settings=settings,
            submitter=submitter,
            content=RecordingContentWriter(),
            profiles=FakeProfiles(),
        ),
        storage=MemoryStorage(),
    )
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Act — the queue comes back and the customer presses Confirm again
    submitter.failure = None
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    assert len(submitter.submitted) == 1


async def test_confirm_button_is_not_offered_before_the_wizard_is_complete(
    dispatcher: Dispatcher, bot: Bot, submitter: RecordingSubmitter
) -> None:
    # Arrange — press Confirm at the very first screen
    from tests.test_bot.test_wizard_flow import send

    await send(dispatcher, bot, "/start")

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    assert submitter.submitted == []
