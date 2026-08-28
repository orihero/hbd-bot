"""The payment gate. Out of scope for this build means "always passes", not "absent"."""

from __future__ import annotations

from uuid import uuid4

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
from hbd.contracts import Language, Ok, PaymentProvider
from tests.test_bot.conftest import (
    CHAT_ID,
    USER_ID,
    DecliningPaymentProvider,
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
        order_id=order_id, amount_minor=FREE_AMOUNT_MINOR, currency=DEFAULT_CURRENCY
    )

    # Assert
    assert isinstance(result, Ok)
    assert result.value.is_authorized
    assert result.value.amount_minor == 0
    assert result.value.order_id == order_id


def test_noop_provider_satisfies_the_payment_protocol() -> None:
    # Arrange / Act / Assert
    assert isinstance(NoopPaymentProvider(), PaymentProvider)


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
        BotDeps(settings=settings, submitter=submitter, content=RecordingContentWriter()),
        storage=storage,
    )
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    texts = " ".join(call.text or "" for call in session.calls if hasattr(call, "text"))
    assert translate("wizard.enqueue_failed", Language.EN) in texts


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
