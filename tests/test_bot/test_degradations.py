"""The unhappy paths that must degrade quietly instead of failing loudly."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import EditMessageText, SendMessage

from hbd.bot import i18n
from hbd.bot.app import build_dispatcher
from hbd.bot.callbacks import NavAction, NavCB
from hbd.bot.delivery import DeliveryLedger, deliver_kit, order_reference
from hbd.bot.deps import BotDeps
from hbd.bot.i18n import translate
from hbd.bot.progress import render_progress
from hbd.bot.states import WIZARD_ORDER, Wizard, WizardStep, next_step, step_for_state
from hbd.config import Settings
from hbd.contracts import AssetKind, Err, Kit, Language, Result, err
from hbd.errors import ErrorCode, PaymentError
from hbd.pipeline.events import PipelineStage, ProgressStatus
from hbd.pipeline.outcome import PipelineGap
from tests.conftest import make_asset
from tests.test_bot.conftest import (
    CHAT_ID,
    RecordingContentWriter,
    RecordingSession,
    RecordingSubmitter,
)
from tests.test_bot.test_progress import event
from tests.test_bot.test_wizard_flow import press, send, walk_to_confirm, walk_to_name


class FailingPaymentProvider:
    """Authorisation that errors rather than declines. A different branch entirely."""

    name = "failing"

    async def authorize(
        self, *, order_id: Any, amount_minor: int, currency: str, telegram_user_id: int
    ) -> Result[Any]:
        return err(PaymentError("the rail is down", context={"order_id": str(order_id)}))


# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------
def test_a_missing_placeholder_renders_visibly_instead_of_raising() -> None:
    # Arrange / Act — the template wants {limit}; it is handed something else
    text = translate("wizard.note.too_long", Language.EN, unrelated="x")

    # Assert
    assert "{limit}" in text


def test_a_broken_template_falls_back_to_the_raw_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — a translator typo that no schema can catch
    monkeypatch.setattr(i18n, "_resolve_template", lambda key, language: "{name!z}")

    # Act
    text = i18n.translate("any.key", Language.EN, name="Aziza")

    # Assert — a copy bug must never take down a delivery
    assert text == "{name!z}"


# ---------------------------------------------------------------------------
# progress
# ---------------------------------------------------------------------------
def test_a_degraded_stage_is_marked_as_best_effort() -> None:
    # Arrange / Act
    text = render_progress(
        event(PipelineStage.VERIFYING_NAME, ProgressStatus.DEGRADED), Language.EN
    )

    # Assert
    assert translate("progress.degraded_suffix", Language.EN) in text


# ---------------------------------------------------------------------------
# states
# ---------------------------------------------------------------------------
def test_next_step_walks_the_declared_order() -> None:
    # Arrange / Act / Assert
    for earlier, later in pairwise(WIZARD_ORDER):
        assert next_step(earlier) is later
    assert next_step(WIZARD_ORDER[-1]) is None


def test_step_for_state_ignores_a_state_that_is_not_a_wizard_step() -> None:
    # Arrange / Act / Assert
    assert step_for_state(None) is None
    assert step_for_state("SomeOtherGroup:whatever") is None
    assert step_for_state(Wizard.name.state) is WizardStep.NAME


# ---------------------------------------------------------------------------
# screens over Telegram
# ---------------------------------------------------------------------------
async def test_a_screen_that_cannot_be_edited_is_sent_as_a_new_message(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    dispatcher = build_dispatcher(
        BotDeps(
            settings=settings,
            submitter=RecordingSubmitter(),
            content=RecordingContentWriter(),
        ),
        storage=MemoryStorage(),
    )
    await send(dispatcher, bot, "/start")
    session.failures["EditMessageText"] = TelegramBadRequest(
        method=EditMessageText(chat_id=CHAT_ID, message_id=1, text="x"),
        message="message is not modified",
    )

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.BACK).pack())

    # Assert — the user still sees the screen
    assert session.named("SendMessage")


# ---------------------------------------------------------------------------
# delivery
# ---------------------------------------------------------------------------
async def test_a_greeting_with_no_file_is_reported(bot: Bot, kit: Kit, tmp_path: Path) -> None:
    # Arrange
    ghost = make_asset(
        tmp_path,
        path=tmp_path / "ghost.ogg",
        kind=AssetKind.GREETING,
        mime="audio/ogg",
        duration_s=20.0,
        persona_id="ghost",
    )
    ghost.path.unlink()
    broken = kit.model_copy(update={"greetings": (ghost,)})

    # Act
    result = await deliver_kit(bot, chat_id=CHAT_ID, kit=broken, language=Language.EN)

    # Assert
    assert isinstance(result, Err)
    assert "greeting:missing-file" in str(result.error.context["failures"])


async def test_a_lyric_sheet_that_cannot_be_sent_is_reported(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    # Arrange
    session.failures["SendMessage"] = TelegramBadRequest(
        method=SendMessage(chat_id=CHAT_ID, text="x"), message="chat not found"
    )

    # Act
    result = await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.EN)

    # Assert
    assert isinstance(result, Err)
    failures = str(result.error.context["failures"])
    assert "lyric_sheet" in failures
    assert "closing" in failures


async def test_a_gap_from_a_stage_nobody_mapped_is_disclosed_without_an_error_string(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """``gap_message_key`` is total: an unmapped stage costs a detail, never the disclosure.

    A gap recorded at PERSISTING is an asset that failed to ARCHIVE — an operator concern
    with nothing a customer can hear, since the file was delivered from local disk either
    way. It must not put ``error.generic`` under a delivered song, and it must not quietly
    turn the closing message back into a clean one.
    """
    # Arrange
    gap = PipelineGap(
        stage=PipelineStage.PERSISTING,
        error_code=ErrorCode.STORAGE_FAILED,
        detail="asset was not archived",
        user_message_key="error.generic",
    )

    # Act
    await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.EN, gaps=(gap,))

    # Assert
    closing = session.named("SendMessage")[-1].text  # type: ignore[attr-defined]
    assert translate("error.generic", Language.EN) not in closing
    assert order_reference(kit.order_id) in closing


async def test_a_ledger_that_forgot_an_order_resends_rather_than_sending_nothing(
    bot: Bot, session: RecordingSession, kit: Kit
) -> None:
    """The ledger is process-local and bounded, so eviction is a real state to survive.

    Losing the song is far worse than sending it twice, so an evicted order falls back to
    a duplicate send — never to a silent no-op.
    """
    # Arrange — a ledger with room for exactly one order, then a second order to evict it
    ledger = DeliveryLedger(max_orders=1)
    await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.EN, ledger=ledger)
    other = kit.model_copy(update={"order_id": uuid4()})
    await deliver_kit(bot, chat_id=CHAT_ID, kit=other, language=Language.EN, ledger=ledger)
    session.clear()

    # Act
    result = await deliver_kit(bot, chat_id=CHAT_ID, kit=kit, language=Language.EN, ledger=ledger)

    # Assert
    assert not isinstance(result, Err)
    assert session.named("SendAudio")


# ---------------------------------------------------------------------------
# payment
# ---------------------------------------------------------------------------
async def test_a_payment_provider_error_is_shown_in_the_user_s_language(
    settings: Settings, bot: Bot, session: RecordingSession
) -> None:
    # Arrange
    submitter = RecordingSubmitter()
    dispatcher = build_dispatcher(
        BotDeps(
            settings=settings,
            submitter=submitter,
            content=RecordingContentWriter(),
            payment=FailingPaymentProvider(),
        ),
        storage=MemoryStorage(),
    )
    await walk_to_confirm(dispatcher, bot)

    # Act
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())

    # Assert
    texts = " ".join(call.text or "" for call in session.calls if hasattr(call, "text"))
    assert translate("error.payment_failed", Language.EN) in texts
    assert submitter.submitted == []


async def test_the_wizard_survives_a_second_run_in_the_same_chat(
    settings: Settings, bot: Bot
) -> None:
    # Arrange
    submitter = RecordingSubmitter()
    dispatcher = build_dispatcher(
        BotDeps(settings=settings, submitter=submitter, content=RecordingContentWriter()),
        storage=MemoryStorage(),
    )

    # Act
    await walk_to_confirm(dispatcher, bot)
    await press(dispatcher, bot, NavCB(action=NavAction.CONFIRM).pack())
    await walk_to_name(dispatcher, bot)

    # Assert — one order queued, and the second wizard is running cleanly
    assert len(submitter.submitted) == 1
